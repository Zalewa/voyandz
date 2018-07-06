from voyandz import app, config
import flask

from pprint import pformat
import os


@app.route('/')
def hello():
    return "voyandz reporting for duty"


@app.route('/stream/')
def stream():
    return "no streams yet"


@app.route('/cfg')
def cfg():
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


def _cfg(path=""):
    tokens = [t for t in path.split('/') if t]
    root = app.config[config.CONF_KEY]
    for token in tokens:
        root = root[token]
    return root
