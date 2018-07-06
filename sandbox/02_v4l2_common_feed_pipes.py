#!/usr/bin/env python3
from flask import Flask, send_file, make_response, Response, g, request, stream_with_context
from io import BytesIO
import atexit
import errno
import os
import subprocess
import threading


INPUT = '/dev/video0'
FFMPEG = "/home/test/ffmpeg-nvenc/ffmpeg"
app = Flask(__name__)


@app.route('/pic')
def pic():
    cmd = [FFMPEG, '-s', 'uhd2160', '-i', INPUT,
           '-vframes', '1', '-vcodec', 'png', '-f', 'image2pipe', '-']
    app.logger.debug('exec: {}'.format(' '.join(cmd)))
    p = subprocess.Popen(cmd, stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
    stdout, stderr = p.communicate()
    ec = p.wait()
    if ec == 0:
        return send_file(BytesIO(stdout), mimetype="image/png")
    else:
        return make_response("<pre>{}</pre>".format(stderr.decode('utf-8', 'replace')), 500)


@app.route('/mpjpeg')
def mpjpeg():
    cmd = [FFMPEG, '-s', 'uhd2160', '-i', INPUT,
           '-f', 'mpjpeg', '-s', 'hd720',
           '-qmin', '1', '-qmax', '6', '-r', '15', '-']
    return Response(_stream(cmd), mimetype="multipart/x-mixed-replace;boundary=ffserver")


@app.route('/ts')
def ts():
    cmd = [FFMPEG, '-s', 'uhd2160', '-i', INPUT,
           '-f', 'mpegts', '-s', 'hd720',
           '-vcodec', 'h264_nvenc', '-qp', '23',
           '-g', '30', '-bf', '0', '-zerolatency', '1',
           '-strict_gop', '1', '-sc_threshold', '0', '-']
    return Response(_stream(cmd), mimetype="video/ts")


@atexit.register
def teardown(*args):
    app.logger.debug('teardown')
    app.logger.debug(global_ctx)
    global_ctx.close()


def _stream(cmd):
    app.logger.debug('stream: {}'.format(' '.join(cmd)))

    def generate():
        with global_ctx.feed(cmd) as feed:
            rpipe = feed.new_reader()
            try:
                while True:
                    chunk = os.read(rpipe, 10240)
                    if not chunk:
                        break
                    yield chunk
            finally:
                os.close(rpipe)
    return stream_with_context(generate())


class _GlobalContext:
    def __init__(self):
        app.logger.debug('_GlobalContext')
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
        app.logger.debug("feed new reader")
        return self._buffer.new_reader()

    def _open(self):
        app.logger.debug("feed open")
        self._closed = False
        self._buffer = _MultiClientBuffer()
        self._rpipe, wpipe = os.pipe()
        try:
            try:
                self._process = subprocess.Popen(self._cmd, stdin=None, stdout=wpipe, stderr=subprocess.DEVNULL, close_fds=True)
            finally:
                os.close(wpipe)
            thread = threading.Thread(target=self._buffer_loop)
            thread.daemon = True
            thread.start()
            self._thread = thread
        except:
            if self._rpipe is not None:
                os.close(self._rpipe)
                self._rpipe = None
            self._closed = True
            raise

    def _close(self):
        app.logger.debug("feed close")
        self._buffer.close()
        self._closed = True
        p = self._process
        if p:
            p.terminate()
            try:
                p.wait(1.0)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        self._process = None
        if self._rpipe:
            os.close(self._rpipe)
            self._rpipe = None
        thread = self._thread
        self._thread = None
        if thread:
            thread.join()

    def _buffer_loop(self):
        while not self._closed:
            chunk = os.read(self._rpipe, 10240)
            if not chunk:
                break
            self._buffer.write(chunk)

    def __enter__(self):
        with self._lock:
            if self._acquired == 0:
                self._open()
            self._acquired += 1
            app.logger.debug("feed enter {}".format(self._acquired))
        return self

    def __exit__(self, *args):
        with self._lock:
            app.logger.debug("feed exit {}".format(self._acquired))
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
            self._pipes.append((rpipe, wpipe))
            return rpipe

    def write(self, chunk):
        if self._closed:
            return
        pipes_to_del = []
        try:
            with self._pipes_lock:
                pipes = list(self._pipes)
            for idx, (_, wpipe) in enumerate(pipes):
                try:
                    os.write(wpipe, chunk)
                except BrokenPipeError:
                    pipes_to_del.append(idx)
                    os.close(wpipe)
                except Exception:
                    pipes_to_del = range(len(pipes))
                    raise
        finally:
            with self._pipes_lock:
                for pipe_idx in reversed(pipes_to_del):
                    del self._pipes[pipe_idx]

    def close(self):
        with self._pipes_lock:
            self._closed = True
            for _, wpipe in self._pipes:
                os.close(wpipe)
            self._pipes = []


global_ctx = _GlobalContext()
