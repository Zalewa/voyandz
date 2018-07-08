from werkzeug.serving import WSGIRequestHandler, _log as werkzeug_log
import flask

from types import MethodType
import logging
import time


def _format_time(self, record, *args, **kwargs):
    ct = self.converter(record.created)
    t = time.strftime("%Y-%m-%d %H:%M:%S", ct)
    s = "%s.%03d" % (t, record.msecs)
    return s


class LogFormatter(logging.Formatter):
    _DATEFMT = '%Y-%m-%d %H:%M:%S'
    _REQUEST_FORMATTER = logging.Formatter(
        '[%(asctime)s] %(levelname)s in %(module)s: %(message)s '
        '(%(remote_addr)s / %(url)s)',
        datefmt=_DATEFMT
    )
    _NORMAL_FORMATTER = logging.Formatter(
        '[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
        datefmt=_DATEFMT
    )

    _REQUEST_FORMATTER.formatTime = MethodType(_format_time, _REQUEST_FORMATTER)
    _NORMAL_FORMATTER.formatTime = MethodType(_format_time, _NORMAL_FORMATTER)

    def format(self, record):
        if flask.request:
            record.url = flask.request.url
            record.remote_addr = flask.request.remote_addr
            return self._REQUEST_FORMATTER.format(record)
        else:
            return self._NORMAL_FORMATTER.format(record)


class FormattedRequestHandler(WSGIRequestHandler):
    '''Gets rid of extraneous logging artifacts.

    Credit: https://stackoverflow.com/a/36302219/1089357
    '''
    # Just like WSGIRequestHandler, but without "- -"
    def log(self, type, message, *args):
        werkzeug_log(type, '[{}.{:03}] {} - {}\n'.format(
            time.strftime('%Y-%m-%d %H:%M:%S'),
            int((time.time() * 1000) % 1000),
            self.address_string(),
            message % args))

    def log_request(self, code='-', size='-'):
        self.log('info', '"%s" %s %s', self.requestline, code, size)
