import os
import yaml


DEFAULT_CONFFILE = "/etc/voyandz"
CONFFILE_ENV = "VOYANDZ_CONFFILE"
CONF_KEY = "voyandz"

PROFILE_ENV = "VOYANDZ_PROFILE"


class ConfigError(Exception):
    pass


def init_app_config(app, conffile=None):
    '''This function is designed to exit the application
    if config loading fails.
    '''
    if conffile is None:
        conffile = os.environ.get(CONFFILE_ENV) or DEFAULT_CONFFILE
    app.logger.info("Using config file '{}'".format(conffile))
    try:
        cfg = load_config_from_file(conffile)
    except ConfigError as e:
        print("config error '{}': {}".format(conffile, e))
        raise
    app.config[CONF_KEY] = cfg
    return cfg


def load_config_from_file(filepath):
    try:
        with open(filepath, 'r') as f:
            return load_config(f)
    except IOError as e:
        raise ConfigError(str(e)) from e


def load_config(io):
    try:
        cfg = yaml.safe_load(io) or {}
    except yaml.error.YAMLError as e:
        raise ConfigError(str(e)) from e
    cfg.setdefault('listenaddr', '127.0.0.1')
    cfg.setdefault('listenport', 8090)
    cfg.setdefault('pages', {})
    pages = cfg['pages']
    if hasattr(pages, "setdefault"):
        pages.setdefault('config', False)
        pages.setdefault('home', True)
        pages.setdefault('stat', True)
    cfg.setdefault('streams', {})
    cfg.setdefault('feeds', {})
    _validate(cfg)
    _normalize_stream_urls(cfg)
    # TODO: more default values
    return cfg


def _normalize_stream_urls(cfg):
    for stream in cfg['streams'].values():
        if 'url' in stream:
            stream_url = str(stream['url'])
            stream_url = stream_url.lstrip('/')
            if stream_url:
                stream['url'] = stream_url
            else:
                del stream['url']


def _validate(cfg):
    # listenport
    if not _is_valid_port(cfg["listenport"]):
        raise ConfigError("listenport must be in range 1 - 65535")
    # logdir
    if cfg.get("logdir"):
        if not os.path.isdir(cfg["logdir"]):
            raise ConfigError("logdir doesn't exist")
        if not os.access(cfg["logdir"], os.W_OK):
            raise ConfigError("denied write access to logdir")
    # feeds
    if not isinstance(cfg["feeds"], dict):
        raise ConfigError("feeds must be a dict")
    for feed_name, feed in cfg["feeds"].items():
        if feed_name == "":
            raise ConfigError("feed with no name detected")
        if not isinstance(feed, dict):
            raise ConfigError("feed '{}' has invalid definition".format(feed_name))
        if not feed.get("command"):
            raise ConfigError("feed '{}' has invalid command".format(feed_name))
    # streams
    if not isinstance(cfg["streams"], dict):
        raise ConfigError("streams must be a dict")
    for stream_name, stream in cfg["streams"].items():
        if stream_name == "":
            raise ConfigError("stream with no name detected")
        if not isinstance(stream, dict):
            raise ConfigError("stream '{}' has invalid definition".format(stream_name))
        for field in ["command", "mimetype", "type"]:
            if not stream.get(field):
                raise ConfigError(
                    "stream '{}' has invalid or "
                    "missing field '{}'".format(stream_name, field))
    # pages
    if not isinstance(cfg["pages"], dict):
        raise ConfigError("pages must be a dict")


def _is_valid_port(port):
    try:
        if not str(port).isdigit():
            return False
    except ValueError:
        return False
    port = int(port)
    return port > 0 and port <= 0xffff
