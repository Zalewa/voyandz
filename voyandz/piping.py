# coding: utf-8
from .logging import logopen

import atexit
import errno
import os
import threading
import time
import select
import shlex
import subprocess
import sys


# TODO optimal read size?
_PIPE_CHUNK_SIZE = select.PIPE_BUF
_FEED_RPIPE_TIMEOUT = 1.0
_CLIENT_WPIPE_TIMEOUT = 1.0


class Error(Exception):
    pass


class FeedReuseError(Error):
    def __init__(self, details, feed_id, *args):
        super(FeedReuseError, self).__init__(
            "tried to incorrectly reuse feed{}, feed_id: {}".format(
                " {}".format(details) if details else "",
                feed_id),
            feed_id,
            *args)


class NoSuchFeedError(Error):
    pass


class NoSuchStreamError(Error):
    pass


def stream(cfg, stream_name):
    try:
        stream_cfg = cfg['streams'][stream_name]
    except KeyError:
        raise NoSuchStreamError(stream_name)
    try:
        mimetype = stream_cfg["mimetype"]
    except KeyError:
        raise Error("stream '{}' is of unknown mimetype".format(mimetype))
    feeds_cfg = cfg.get('feeds', {})
    stream_type = stream_cfg.get("type")
    try:
        if stream_type == "stream":
            output = _stream(stream_name, stream_cfg, feeds_cfg, cfg.get('logdir'))
        elif stream_type == "shot":
            output = _shot(stream_cfg, feeds_cfg)
        else:
            raise Error("stream '{}' is of unknown type".format(stream_name))
    except Exception as e:
        if isinstance(e, Error):
            raise
        else:
            raise Error(str(e)) from e
    return stream_type, mimetype, output


def _stream(stream_name, stream_cfg, feeds_cfg, logdir):
    cmd = stream_cfg['command']
    stream_id = "stream_{}".format(stream_name)

    def generate():
        with _feed_for_stream(stream_cfg, feeds_cfg, logdir=logdir) as feed:
            with _global_ctx.feed(stream_id, cmd, feed,
                                  logdir=logdir) as stream:
                stream_rpipe = stream.new_reader()
                try:
                    while stream.is_alive():
                        #print("reading chunk for stream '{}'".format(stream_id), file=sys.stderr) # TODO XXX
                        chunk = os.read(stream_rpipe, _PIPE_CHUNK_SIZE)
                        if not chunk:
                            break
                        yield chunk
                finally:
                    os.close(stream_rpipe)
    return generate()


def _shot(stream_cfg, feeds_cfg):
    cmd = shlex.split(stream_cfg['command'])
    with _feed_for_stream(stream_cfg, feeds_cfg, logdir=stream_cfg.get('logdir')) as feed:
        stdin = None
        if feed:
            stdin = feed.new_reader()
        try:
            p = subprocess.Popen(cmd, stdin=stdin, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, close_fds=True)
        finally:
            if stdin is not None:
                os.close(stdin)
        stdout, stderr = p.communicate()
        ec = p.wait()
        if ec == 0:
            return stdout
        else:
            raise Error(stderr.decode('utf-8', 'replace'))


def _feed_for_stream(stream_cfg, feeds_cfg, logdir):
    feed_name = stream_cfg.get('feed')
    if not feed_name:
        return _null_feed
    try:
        feed_cfg = feeds_cfg[feed_name]
    except KeyError:
        raise NoSuchFeedError("feed '{}' cannot be found".format(feed_name))
    return _feed(feed_name, feed_cfg, logdir=logdir)


def _feed(feed_name, feed_cfg, logdir):
    command = feed_cfg['command']
    mode = feed_cfg.get('mode', 'on-demand')
    if isinstance(mode, str):
        mode = mode.lower()
    return _global_ctx.feed("feed_{}".format(feed_name),
                            command, mode=mode, logdir=logdir)


@atexit.register
def _teardown(*args):
    _global_ctx.close()


class _GlobalContext:
    def __init__(self):
        self._feeds = {}
        self._feed_lock = threading.Lock()

    def feed(self, feed_id, cmd, input_feed=None, mode="on-demand",
             logdir=None):
        with self._feed_lock:
            feed = self._feeds.get(feed_id)
            if feed is None:
                feed = _Feed(feed_id, cmd, input_feed, mode=mode,
                             logdir=logdir)
                self._feeds[feed_id] = feed
            if input_feed is not feed.input_feed:
                raise FeedReuseError("with a different input feed", feed_id)
            if mode != feed.mode:
                raise FeedReuseError("with a different mode", feed_id)
            return feed

    def close(self):
        with self._feed_lock:
            for feed in self._feeds.values():
                feed._close()
            self._feeds = {}


class _Feed:
    def __init__(self, feed_id, cmd, input_feed, mode="on-demand",
                 logdir=None):
        if not self._is_mode_valid(mode):
            raise Error("invalid mode '{}'".format(mode))
        self.input_feed = input_feed
        self.mode = mode
        self._feed_id = feed_id
        self._logdir = logdir
        self._acquired = 0
        self._lock = threading.Lock()
        self._process = None
        self._rpipe = None
        self._cmd = cmd
        self._buffer = None
        self._thread = None
        self._closed = True

    def new_reader(self):
        print("creating new pipe set for feed {}".format(self._feed_id), file=sys.stderr) # TODO XXX
        return self._buffer.new_reader()

    def is_alive(self):
        p = self._process
        return p is not None and p.poll() is None

    def open(self):
        with self._lock:
            if self._acquired == 0:
                if self._closed:
                    self._open()
            self._acquired += 1

    def close(self):
        with self._lock:
            self._acquired -= 1
            if self._acquired <= 0:
                if self.mode == "on-demand":
                    self._close()
                elif isinstance(self.mode, (int, float)):
                    t = threading.Thread(target=self._delayed_close, args=(self.mode,))
                    t.daemon = True
                    t.start()

    def _delayed_close(self, delay):
        time.sleep(delay)
        with self._lock:
            if self._acquired <= 0:
                self._close()

    def _open(self):
        cmd = shlex.split(self._cmd)
        feed_rpipe = None
        wpipe = None
        try:
            self._rpipe, wpipe = os.pipe()
            self._buffer = _MultiClientBuffer()
            if self.input_feed:
                feed_rpipe = self.input_feed.new_reader()
            try:
                if self._logdir:
                    logfile = logopen(self._logdir,
                                      "{}.log".format(self._feed_id))
                else:
                    logfile = subprocess.DEVNULL
                self._process = subprocess.Popen(
                    cmd, stdin=feed_rpipe, stdout=wpipe,
                    stderr=logfile, close_fds=True)
            finally:
                if logfile != subprocess.DEVNULL:
                    logfile.close()
                if feed_rpipe is not None:
                    os.close(feed_rpipe)
                    feed_rpipe = None
                os.close(wpipe)
                wpipe = None
            self._closed = False
            thread = threading.Thread(target=self._buffer_loop)
            thread.daemon = True
            thread.start()
            self._thread = thread
        except BaseException:
            self._close()
            raise
        finally:
            if feed_rpipe is not None:
                os.close(feed_rpipe)
            if wpipe is not None:
                os.close(wpipe)

    def _close(self):
        self._buffer.close()
        self._closed = True
        # Stop process.
        p = self._process
        self._process = None
        if p:
            p.terminate()
            try:
                p.wait(1.0)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        # Close read pipe.
        rpipe = self._rpipe
        self._rpipe = None
        if rpipe:
            os.close(rpipe)
        # Close piping thread.
        thread = self._thread
        self._thread = None
        if thread:
            thread.join()

    def _buffer_loop(self):
        while not self._closed and self.is_alive():
            rpipe = self._rpipe
            if not rpipe:
                break
            rpipes, _, _ = select.select([rpipe], [], [], _FEED_RPIPE_TIMEOUT)
            if rpipes:
                chunk = os.read(rpipe, _PIPE_CHUNK_SIZE)
                if not chunk:
                    break
                #print("writing chunk to buffer '{}'".format(self._feed_id), file=sys.stderr) # TODO XXX
                self._buffer.write(chunk)
                #print("written '{}'".format(self._feed_id)) # TODO XXX
        # This will break all connections and effectively close the feed.
        self._buffer.close()
        # TODO respawn?

    def _is_mode_valid(self, mode):
        return mode in ["continuous", "on-demand"] or isinstance(mode, (float, int))

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()


class _MultiClientBuffer:
    def __init__(self):
        self._pipes = {}
        self._pipes_lock = threading.Lock()
        self._closed = False

    def new_reader(self):
        with self._pipes_lock:
            if self._closed:
                raise IOError(errno.EIO, "already closed")
            rpipe, wpipe = os.pipe()
            print("\tcreated pipeset r={}, w={}".format(rpipe, wpipe), file=sys.stderr) # TODO XXX
            #os.set_blocking(wpipe, False)
            self._pipes[wpipe] = _PipeBuffer(wpipe)
            return rpipe

    def write(self, chunk):
        if self._closed:
            return
        # Select pipes to write to.
        with self._pipes_lock:
            pipes = dict(self._pipes)
        if not pipes:
            return
        _, ready_pipes, _ = select.select([], list(pipes.keys()), [], _CLIENT_WPIPE_TIMEOUT)
        unready_pipes = [pipe for pipe in pipes if pipe not in ready_pipes]
        if unready_pipes:
            print("ready {}, unready {}".format(ready_pipes, unready_pipes), file=sys.stderr) # TODO XXX
        kill_pipes = set()
        # Write to ready pipes.
        for wpipe in ready_pipes:
            pipebuf = pipes.get(wpipe)
            try:
                #print("WRITING {}, {}".format(wpipe, len(chunk)), file=sys.stderr) # TODO XXX
                written = pipebuf.write(chunk)
                #print("WRITTEN {}, {}".format(wpipe, written), file=sys.stderr) # TODO XXX
            except IOError:
                print("IOIO on wpipe {}".format(wpipe), file=sys.stderr) # TODO XXX
                kill_pipes.add(wpipe)
        # Buffer unready pipes and kill ones that timed out.
        for wpipe in unready_pipes:
            pipebuf = pipes.get(wpipe)
            if not pipebuf or pipebuf.timedout:
                print("killing timedout wpipe: {}".format(wpipe), file=sys.stderr) # TODO XXX
                kill_pipes.add(wpipe)
                continue
            pipebuf.store_buffer(chunk)
        # Kill pipes that are targeted for termination.
        if kill_pipes:
            with self._pipes_lock:
                for wpipe in kill_pipes:
                    print("killing wpipe: {}".format(wpipe), file=sys.stderr) # TODO XXX
                    if wpipe in self._pipes:
                        print("yes wpipe: {} is so kill".format(wpipe), file=sys.stderr) # TODO XXX
                        os.close(wpipe)
                        del self._pipes[wpipe]

    def close(self):
        with self._pipes_lock:
            print("closing multiclientbuffer {:x}".format(id(self)), file=sys.stderr) # TODO XXX
            self._closed = True
            for wpipe in self._pipes:
                os.close(wpipe)
            self._pipes = {}


class _PipeBuffer:
    def __init__(self, pipe):
        self._pipe = pipe
        self._buffer = b''
        self._last_ready = _monotonic()

    @property
    def timedout(self):
        return (_monotonic() - self._last_ready) > _CLIENT_WPIPE_TIMEOUT

    def write(self, chunk):
        payload = self._buffer + chunk
        self._buffer = b''
        try:
            written_len = os.write(self._pipe, payload)
        except OSError as e:
            if e.errno in [errno.EAGAIN, errno.EWOULDBLOCK]:
                self._buffer = payload
            else:
                raise
        else:
            self._last_ready = _monotonic()
            if written_len < len(payload):
                self._buffer = payload[written_len:]

    def store_buffer(self, chunk):
        self._buffer += chunk


class _NullFeed:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def __bool__(self):
        return False


def _monotonic():
    return time.clock_gettime(time.CLOCK_MONOTONIC_RAW)


_null_feed = _NullFeed()
_global_ctx = _GlobalContext()
