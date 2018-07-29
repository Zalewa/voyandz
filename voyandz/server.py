from voyandz import app, config, logging, piping
import flask

from io import BytesIO
import json
import os


flask.logging.default_handler.setFormatter(logging.LogFormatter())


@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def hello(path):
    # Try to match path to a stream with customized URL.
    if path:
        stream_name = _find_stream(path)
        if stream_name:
            return stream(stream_name)
        else:
            return flask.abort(404)
    elif _cfg("pages/home"):
        return _home_page()
    else:
        flask.abort(403)


@app.route('/stream/<name>')
def stream(name):
    try:
        stream_type, stream_mimetype, output = piping.stream(_cfg(), name)
    except piping.NoSuchStreamError as e:
        flask.abort(404)
    except piping.Error as e:
        app.logger.exception(e)
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
    output = json.dumps(app.config['voyandz'], indent=2)
    return flask.Response(output, mimetype="application/json")


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


def _home_page():
    streams = _cfg("streams")
    pages = _cfg("pages")
    config_page = pages["config"]
    stat_page = pages["stat"]
    return flask.render_template(
        "home.html", streams=streams,
        any_page=any([stat_page, config_page]),
        stat_page=stat_page, config_page=config_page)


def _find_stream(path):
    if not path:
        raise ValueError("empty path")
    # Trim the initial '/' if present to match to paths
    # where config did not specify the prefixing '/'
    if path[0] == '/':
        path = path[1:]
    if not path:
        raise ValueError("stream cannot be at root path")
    streams = _cfg("streams")
    for stream_name, stream in streams.items():
        stream_url = stream.get("url") or ""
        # Trim the initial '/' from the config path.
        if stream_url and stream_url[0] == '/':
            stream_url = stream_url[1:]
        if path == stream_url:
            return stream_name
    return None


def _cfg(path=""):
    tokens = [t for t in path.split('/') if t]
    root = app.config[config.CONF_KEY]
    for token in tokens:
        root = root[token]
    return root
