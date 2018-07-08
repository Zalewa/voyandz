from voyandz import app, config, logging, piping
import flask

from io import BytesIO
from pprint import pformat
import os


flask.logging.default_handler.setFormatter(logging.LogFormatter())


@app.route('/')
def hello():
    return "voyandz reporting for duty"


@app.route('/stream/<name>')
def stream(name):
    try:
        stream_type, stream_mimetype, output = piping.stream(_cfg(), name)
    except piping.NoSuchStreamError as e:
        flask.abort(404)
    except piping.Error as e:
        return flask.make_response("<pre>{}</pre>".format(
            flask.escape(str(e))), 500)
    else:
        if stream_type == "stream":
            return flask.Response(output, mimetype=stream_mimetype)
        elif stream_type == "shot":
            return flask.send_file(BytesIO(output), mimetype=stream_mimetype)
        else:
            return flask.make_response("this stream is of unknown type", 500)


@app.route('/config')
def config_page():
    if not _cfg('pages/config') and os.environ.get('FLASK_ENV') != 'development':
        flask.abort(403)
    configdump = pformat(app.config['voyandz'])
    return "<pre>{}</pre>".format(flask.escape(configdump))


@app.route('/stat')
def stat():
    if not _cfg('pages/stat'):
        flask.abort(403)
    return "no stats available currently"


@app.before_first_request
def init():
    # Known problem: this can't configure listen port and listen address.
    if config.CONF_KEY not in app.config:
        config.init_app_config(app, None)


@app.after_request
def add_headers(request):
    """
    Add headers to both force latest IE rendering engine or Chrome Frame,
    and also to cache the rendered page for 10 minutes.

    Credit: https://stackoverflow.com/a/34067710/1089357
    """
    request.headers["Cache-Control"] = ("no-cache, no-store, "
                                        "must-revalidate, public, max-age=0")
    request.headers["Pragma"] = "no-cache"
    request.headers["Expires"] = "0"
    return request


def _cfg(path=""):
    tokens = [t for t in path.split('/') if t]
    root = app.config[config.CONF_KEY]
    for token in tokens:
        root = root[token]
    return root
