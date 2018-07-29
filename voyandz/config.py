import os
import yaml


DEFAULT_CONFFILE = "/etc/voyandz"
CONFFILE_ENV = "VOYANDZ_CONFFILE"
CONF_KEY = "voyandz"


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
    pages.setdefault('config', False)
    pages.setdefault('home', True)
    pages.setdefault('stat', True)
    cfg.setdefault('streams', {})
    cfg.setdefault('feeds', {})
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
