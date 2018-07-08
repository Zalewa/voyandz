# coding: utf-8
from select import select
import atexit
import errno
import os
import threading
import subprocess
import sys


# TODO optimal read size?
_PIPE_CHUNK_SIZE = 10240


class Error(Exception):
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
    stream_type = stream_cfg.get("type")
    if stream_type == "stream":
        output = _stream(stream_cfg)  # pass feeds
    elif stream_type == "shot":
        output = _shot(stream_cfg)  # pass feeds
    else:
        raise Error("stream '{}' is of unknown type".format(stream_name))
    return stream_type, mimetype, output


def _stream(stream_cfg):
    cmd = stream_cfg['command']

    def generate():
        with _global_ctx.feed(cmd) as feed:
            rpipe = feed.new_reader()
            print("new feed {}".format(rpipe), file=sys.stderr)
            try:
                while feed.is_alive():
                    chunk = os.read(rpipe, _PIPE_CHUNK_SIZE)
                    print("  kunky chunk", file=sys.stderr)
                    if not chunk:
                        break
                    yield chunk
            finally:
                print("klosing rpipe, connection is going away {}".format(rpipe), file=sys.stderr)
                os.close(rpipe)
    return generate()


def _shot(stream_cfg):
    cmd = stream_cfg['command']
    p = subprocess.Popen(cmd, stdin=None, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, close_fds=True, shell=True)
    stdout, stderr = p.communicate()
    ec = p.wait()
    if ec == 0:
        return stdout
    else:
        raise Error(stderr.decode('utf-8', 'replace'))


@atexit.register
def _teardown(*args):
    _global_ctx.close()


class _GlobalContext:
    def __init__(self):
        self._feeds = {}
        self._feed_lock = threading.Lock()

    def feed(self, cmd):
        with self._feed_lock:
            feed_id = ' '.join(cmd)
            feed = self._feeds.get(feed_id)
            if feed is None:
                feed = _Feed(cmd)
                self._feeds[feed_id] = feed
            return feed

    def close(self):
        with self._feed_lock:
            for feed in self._feeds.values():
                feed._close()
            self._feeds = {}


class _Feed:
    def __init__(self, cmd):
        self._acquired = 0
        self._lock = threading.Lock()
        self._process = None
        self._rpipe = None
        self._cmd = cmd
        self._buffer = None
        self._thread = None
        self._closed = False

    def new_reader(self):
        return self._buffer.new_reader()

    def is_alive(self):
        p = self._process
        return p is not None and p.poll() is None

    def _open(self):
        self._closed = False
        self._buffer = _MultiClientBuffer()
        self._rpipe, wpipe = os.pipe()
        try:
            try:
                # TODO please, dont devnull stderr
                self._process = subprocess.Popen(
                    self._cmd, stdin=None, stdout=wpipe,
                    stderr=subprocess.DEVNULL, close_fds=True, shell=True)
            finally:
                os.close(wpipe)
            thread = threading.Thread(target=self._buffer_loop)
            thread.daemon = True
            thread.start()
            self._thread = thread
        except BaseException:
            self._close()
            raise

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
            rpipes, _, _ = select([self._rpipe], [], [], 1.0)
            if rpipes:
                chunk = os.read(self._rpipe, _PIPE_CHUNK_SIZE)
                if not chunk:
                    break
                self._buffer.write(chunk)
        # This will break all connections and effectively close the feed.
        self._buffer.close()
        # TODO respawn?

    def __enter__(self):
        with self._lock:
            if self._acquired == 0:
                self._open()
            self._acquired += 1
        return self

    def __exit__(self, *args):
        with self._lock:
            self._acquired -= 1
            if self._acquired <= 0:
                self._close()


class _MultiClientBuffer:
    def __init__(self):
        self._pipes = []
        self._pipes_lock = threading.Lock()
        self._closed = False

    def new_reader(self):
        with self._pipes_lock:
            if self._closed:
                raise IOError(errno.EIO, "already closed")
            rpipe, wpipe = os.pipe()
            self._pipes.append(wpipe)
            return rpipe

    def write(self, chunk):
        if self._closed:
            return
        with self._pipes_lock:
            pipes = list(self._pipes)
        for wpipe in pipes:
            try:
                os.write(wpipe, chunk)
            except IOError:
                with self._pipes_lock:
                    if wpipe in self._pipes:
                        os.close(wpipe)
                        del self._pipes[self._pipes.index(wpipe)]

    def close(self):
        with self._pipes_lock:
            self._closed = True
            for wpipe in self._pipes:
                os.close(wpipe)
            self._pipes = []


_global_ctx = _GlobalContext()
