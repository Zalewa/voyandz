#!/usr/bin/env python3
from flask import Flask, send_file, make_response, Response
from io import BytesIO
import os
import subprocess


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
           '-f', 'mpjpeg', '-s', 'hd720',
           '-vcodec', 'h264_nvenc', '-qp', '23', '-']
    return Response(_stream(cmd), mimetype="video/ts")


def _stream(cmd):
    app.logger.debug('stream: {}'.format(' '.join(cmd)))

    def generate():
        pread, pwrite = os.pipe()
        try:
            try:
                p = subprocess.Popen(cmd, stdin=None, stdout=pwrite, stderr=subprocess.DEVNULL, close_fds=True)
            finally:
                os.close(pwrite)
            try:
                pread = os.fdopen(pread, "rb")
                while True:
                    chunk = pread.read(10240)
                    if not chunk:
                        app.logger.debug('no more chunk')
                        break
                    yield chunk
            finally:
                p.terminate()
                try:
                    p.wait(1.0)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
                app.logger.debug('mpjpeg is kill')
        finally:
            if hasattr(pread, "close"):
                pread.close()
            else:
                os.close(pread)
            app.logger.debug('mpjpeg pipe is kill')
    return generate()
