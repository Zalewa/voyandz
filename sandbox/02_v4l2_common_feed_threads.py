#!/usr/bin/env python3
from flask import Flask, send_file, make_response, Response, g, request, stream_with_context
from logging.config import dictConfig
from io import BytesIO
import atexit
import errno
import logging
import os
import subprocess
import threading


INPUT = '/dev/video0'
FFMPEG = "/home/test/ffmpeg-nvenc/ffmpeg"


dictConfig({
    'version': 1,
    'formatters': {'default': {
        'format': '[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
    }},
    'handlers': {'wsgi': {
        'class': 'logging.StreamHandler',
        'stream': 'ext://flask.logging.wsgi_errors_stream',
        'formatter': 'default'
    }},
    'root': {
        'level': 'DEBUG',
        'handlers': ['wsgi']
    }
})

app = Flask(__name__)
#logging.getLogger('werkzeug').disabled = True
werkzeug_log = logging.getLogger('werkzeug')
#werkzeug_log.setLevel(logging.ERROR)
#app.logger.setLevel(logging.ERROR)
#app.logger.disabled = True


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
           '-f', 'mpjpeg', '-s', 'hd720',
           '-vcodec', 'h264_nvenc', '-qp', '23', '-']
    return Response(_stream(cmd), mimetype="video/ts")


@app.route('/erreur')
def erreur():
    raise Exception('im so sorry')


@app.route('/captured_erreur')
def captured_erreur():
    try:
        raise Exception('capture me')
    except Exception as e:
        app.logger.error(e)
    return "it's grand 2"


@atexit.register
def teardown(*args):
    app.logger.debug('teardown')
    app.logger.debug(global_ctx)
    global_ctx.close()


def _stream(cmd):
    app.logger.debug('stream: {}'.format(' '.join(cmd)))

    def generate():
        with global_ctx.feed(cmd) as feed:
            g.clientid = global_ctx.next_id()
            while True:
                chunk = feed.read(g.clientid)
                if not chunk:
                    break
                yield chunk
    return stream_with_context(generate())


class _GlobalContext:
    def __init__(self):
        app.logger.debug('_GlobalContext')
        self._feeds = {}
        self._feed_lock = threading.Lock()
        self._atomic_id = threading.Lock()
        self._next_id = 1

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

    def next_id(self):
        with self._atomic_id:
            id_ = self._next_id
            self._next_id += 1
            return id_


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

    def read(self, client_id):
        app.logger.debug("feed read {}".format(client_id))
        return self._buffer.read(client_id)

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
        self._buffer.close()

    def _buffer_loop(self):
        while not self._closed:
            chunk = os.read(self._rpipe, 10240)
            if not chunk:
                break
            self._buffer.write(chunk)
            if self._buffer.buffer_len() > 1024 * 1024:
                self._buffer.cull()

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
        self._buffer = b''
        self._offsets = {}
        self._end_offset = 0
        self._start_offset = 0
        self._closed = False
        self._condition = threading.Condition()

    def read(self, client_id):
        offset = self._offsets.get(client_id, self._end_offset)
        while not self._closed:
            with self._condition:
                chunk = self._buffer[offset:]
                if not chunk:
                    self._condition.wait(0.5)
                    continue
                self._offsets[client_id] = offset + len(chunk)
            return chunk
        return b''

    def write(self, chunk):
        with self._condition:
            if self._closed:
                raise IOError(errno.EPIPE, "buffer closed")
            self._buffer += chunk
            self._end_offset += len(chunk)
            self._condition.notify_all()

    def cull(self):
        with self._condition:
            min_start_offset = min(self._offsets.values())
            delta = min_start_offset - self._start_offset
            if delta > 0:
                self._buffer = self._buffer[delta:]
                self._start_offset = delta

    def close(self):
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def buffer_len(self):
        return len(self._buffer)


global_ctx = _GlobalContext()
