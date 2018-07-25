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
        self._plumbing = _Plumbing()
        self._plumbing.start()
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
        self._plumbing.stop()

    def add_pipeline(self, pipeline):
        self._plumbing.add_pipeline(pipeline)


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
            pipeline = _Pipeline(self._rpipe, self._buffer,
                                 lifecheck=self.is_alive,
                                 deadhandler=None)
            _global_ctx.add_pipeline(pipeline)
        except BaseException:
            self._close()
            raise
        finally:
            if feed_rpipe is not None:
                os.close(feed_rpipe)
            if wpipe is not None:
                os.close(wpipe)

    def _close(self):
        self._closed = True
        self._buffer.close()
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
        for pipe in self._copy_pipes().values():
            pipe.write(chunk)

    def flush(self, wpipes, amount):
        pipes = self._copy_pipes()
        bad_wpipes = []
        for wpipe in wpipes:
            try:
                pipe = pipes[wpipe]
                pipe.flush(amount)
            except OSError:
                bad_wpipes.append(wpipe)
        if bad_wpipes:
            with self._pipes_lock:
                for wpipe in bad_wpipes:
                    try:
                        os.close(wpipe)
                    except OSError:
                        pass
                    if wpipe in self._pipes:
                        del self._pipes[wpipe]

    def pending_wpipes(self):
        return [wpipe for (wpipe, pipe) in self._copy_pipes().items() if pipe.pending]

    def close(self):
        with self._pipes_lock:
            print("closing multiclientbuffer {:x}, was already closed? {}".format(id(self), self._closed), file=sys.stderr) # TODO XXX
            self._closed = True
            for wpipe in self._pipes:
                os.close(wpipe)
            self._pipes = {}

    def _copy_pipes(self):
        with self._pipes_lock:
            return dict(self._pipes)


class _PipeBuffer:
    def __init__(self, pipe):
        self._pipe = pipe
        self._buffer = b''
        self._last_ready = _monotonic()

    @property
    def timedout(self):
        return (_monotonic() - self._last_ready) > _CLIENT_WPIPE_TIMEOUT

    @property
    def pending(self):
        return self._buffer

    def write(self, chunk):
        self._buffer += chunk

    def flush(self, amount):
        payload = self._buffer
        try:
            if payload:
                written_len = os.write(self._pipe, payload[:amount])
        except OSError as e:
            if e.errno not in [errno.EAGAIN, errno.EWOULDBLOCK]:
                raise
        else:
            self._last_ready = _monotonic()
            self._buffer = payload[written_len:]

    def fileno(self):
        return self._pipe


class _Plumbing:
    def __init__(self):
        self._pipelines = {}
        self._lock = threading.Condition()
        self._thread = None
        self._running = False

    def add_pipeline(self, pipeline):
        with self._lock:
            self._pipelines[pipeline.feed_pipe] = pipeline
            self._lock.notify_all()

    def start(self):
        try:
            self._running = True
            t = threading.Thread(target=self._run)
            t.daemon = True
            t.start()
        except BaseException:
            self._running = False
            raise
        self._thread = t

    def stop(self):
        with self._lock:
            self._running = False
            self._lock.notify_all()
        t = self._thread
        if t:
            t.join()
        self._thread = None

    def _run(self):
        while self._running:
            with self._lock:
                while self._running and not self._pipelines:
                    print("awaiting first pipeline", file=sys.stderr) # TODO XXX
                    self._lock.wait()
                if not self._running:
                    break
            self._run_step()

    def _run_step(self):
        with self._lock:
            pipelines = dict(self._pipelines)
        if not pipelines:
            return
        dead_feed_pipes = set()
        # Prepare pending selections.
        feed_pipes = [feed_pipe for feed_pipe in pipelines]
        all_pending_pipelines = []
        all_pending_wpipes = []
        for pipeline in pipelines.values():
            if not pipeline.lifecheck():
                print("ZDHECLME {:x}".format(id(pipeline)), file=sys.stderr) # TODO XXX
                dead_feed_pipes.add(pipeline.feed_pipe)
                continue
            pending_wpipes = pipeline.outbuffer.pending_wpipes()
            if pending_wpipes:
                all_pending_pipelines.append(pipeline)
                all_pending_wpipes += pending_wpipes
        #print("pipki {}, {}".format(feed_pipes, all_pending_wpipes), file=sys.stderr) # TODO XXX
        ready_feed_pipes, ready_pending_wpipes, _ = select.select(feed_pipes, all_pending_wpipes, [])
        # Deal with new data.
        for feed_pipe in ready_feed_pipes:
            chunk = os.read(feed_pipe, _PIPE_CHUNK_SIZE)
            if not chunk:
                dead_feed_pipes.add(feed_pipe)
                continue
            buf = pipelines[feed_pipe].outbuffer
            buf.write(chunk)
        # Deal with data that was already waiting to be piped out.
        if ready_pending_wpipes:
            for pipeline in all_pending_pipelines:
                pending_wpipes_for_this_buf = [wpipe for wpipe in ready_pending_wpipes
                                               if wpipe in pipeline.outbuffer.pending_wpipes()]
                if pending_wpipes_for_this_buf:
                    pipeline.outbuffer.flush(pending_wpipes_for_this_buf, _PIPE_CHUNK_SIZE)
        # Reap graveyard.
        if dead_feed_pipes:
            print("graveyard", file=sys.stderr) # TODO XXX
            dead_pipelines = []
            with self._lock:
                for feed_pipe in dead_feed_pipes:
                    dead_pipelines.append(self._pipelines[feed_pipe])
                    del self._pipelines[feed_pipe]
            for pipeline in dead_pipelines:
                pipeline.deadhandler()


class _Pipeline:
    def __init__(self, feed_pipe, outbuffer, lifecheck, deadhandler=None):
        self.feed_pipe = feed_pipe
        self.outbuffer = outbuffer
        self.lifecheck = lifecheck or (lambda: False)
        self.deadhandler = deadhandler or (lambda: None)


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
