from voyandz import app, config, logging, piping, stats, version

import flask
import werkzeug.serving

from io import BytesIO
import datetime
import json


_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S UTC"

flask.logging.default_handler.setFormatter(logging.LogFormatter())
_autostarted = False
_start_date = datetime.datetime.now(datetime.timezone.utc)


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
        stream_type, stream_mimetype, output = piping.stream(_cfg(), name, _logdir())
    except piping.NoSuchStreamError:
        flask.abort(404)
    except piping.Error as e:
        app.logger.exception(e)
        return flask.make_response("<pre>{}</pre>".format(
            flask.escape(str(e))), 500)
    else:
        if stream_type == piping.StreamType.STREAM:
            return flask.Response(output, mimetype=stream_mimetype)
        elif stream_type == piping.StreamType.SHOT:
            return flask.send_file(BytesIO(output), mimetype=stream_mimetype)
        else:
            return flask.make_response("this stream is of unknown type", 500)


@app.route('/config')
def config_page():
    if not _cfg('pages/config') and not _is_debug_mode():
        flask.abort(403)
    output = json.dumps(app.config['voyandz'], indent=2)
    return flask.Response(output, mimetype="application/json")


@app.route('/stat')
def stat():
    if not _cfg('pages/stat'):
        flask.abort(403)
    now_date = _nowdate()
    uptime = logging.time_to_duration(
        now_date.timestamp() - _start_date.timestamp())
    all_feeds = sorted(_cfg('feeds').keys(), key=lambda k: k.lower())
    feeds_stats = [piping.feed_stats(feed) for feed in all_feeds]
    all_streams = sorted(_cfg('streams').keys(), key=lambda k: k.lower())
    stream_stats = [piping.stream_stats(stream) for stream in all_streams]
    return flask.render_template(
        'stat.html',
        start_date=_start_date.strftime(_DATETIME_FORMAT),
        current_date=now_date.strftime(_DATETIME_FORMAT),
        uptime=uptime,
        feeds=feeds_stats, streams=stream_stats,
        totals=stats.Totals(feed_stats=feeds_stats, stream_stats=stream_stats),
        server_version=version.VERSION)


@app.before_first_request
def init():
    # Known problem: this can't configure listen port and listen address.
    if not _is_cfg_loaded():
        config.init_app_config(app, None)
    autostart()


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


def autostart():
    global _autostarted

    if _is_debug_mode() and not _is_debug_mode_in_reloader():
        # Debug mode will start the actual application in
        # a subprocess. The parent process will still call
        # this function, but should not execute the autostart
        # code.
        #
        # Also, this check is a hacky workaround at best,
        # probably resulting in a flimsy behavior that may
        # change drastically with different Flask versions.
        return
    if _autostarted:
        return
    if not _is_cfg_loaded():
        raise config.ConfigError("config must be loaded before autostart")
    _autostarted = True
    for feed_name, feed in _cfg("feeds").items():
        if piping.Mode.of(feed.get("mode")) == piping.Mode.AUTOSTART:
            feed = piping.feed_pipeline(_cfg("feeds"), feed_name, _logdir())
            # This 'open' action doesn't have a corresponding
            # 'close'. Autostart feeds are meant to be running
            # for the entire lifetime of the server.
            feed.open()


def _home_page():
    streams = sorted(_cfg("streams").items(), key=lambda i: i[0].lower())
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
        if path == stream_url:
            return stream_name
    return None


def _logdir():
    return _cfg().get("logdir")


def _cfg(path=""):
    tokens = [t for t in path.split('/') if t]
    root = app.config[config.CONF_KEY]
    for token in tokens:
        root = root[token]
    return root


def _is_cfg_loaded():
    return config.CONF_KEY in app.config


def _is_debug_mode():
    if hasattr(flask.app, "get_debug_flag"):
        return flask.app.get_debug_flag()
    else:
        # Err on the side of no-debug mode if we can't determine.
        return False


def _is_debug_mode_in_reloader():
    return _is_debug_mode() and werkzeug.serving.is_running_from_reloader()


def _nowdate():
    return datetime.datetime.now(datetime.timezone.utc)
