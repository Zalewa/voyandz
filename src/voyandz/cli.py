# coding: utf-8
from . import config, logging, version
import voyandz

from optparse import OptionParser
import os
import sys


def main():
    profile_file = os.environ.get(config.PROFILE_ENV)
    if profile_file:
        import yappi
        yappi.start()
    try:
        print_version()
        options = parse_args()
        if options.version:
            sys.exit(0)
        print("", file=sys.stderr)
        app = voyandz.create_app()
        try:
            cfg = init_app_config(app, options.conffile)
        except config.ConfigError:
            sys.exit(1)
        with app.app_context():
            from . import server
            server.autostart()
        app.run(host=cfg['listenaddr'], port=cfg['listenport'], debug=options.develop,
                request_handler=logging.FormattedRequestHandler)
    finally:
        if profile_file:
            yappi.stop()
            pstats = yappi.convert2pstats(yappi.get_func_stats())
            pstats.dump_stats(profile_file)
            with open(profile_file + ".threads", "w") as threads_file:
                yappi.get_thread_stats().print_all(threads_file)


def print_version(file=sys.stderr):
    print("{} {} ({})".format(
        version.FULLNAME,
        version.VERSION, version.YEARSPAN),
        file=file)
    print("On MIT License; no warranty", file=file)


def parse_args():
    opt_parser = OptionParser()
    opt_parser.add_option('-f', dest='conffile',
                          help='change config file (default: {})'.format(config.DEFAULT_CONFFILE),
                          default=config.DEFAULT_CONFFILE)
    opt_parser.add_option('--develop', default=False, action='store_true',
                          help='enable development mode')
    opt_parser.add_option('-V', '--version', dest='version', default=False,
                          action='store_true', help='display version and quit')
    options, _ = opt_parser.parse_args()
    return options


def init_app_config(app, conffile=None):
    if conffile is None:
        conffile = os.environ.get(config.CONFFILE_ENV) or config.DEFAULT_CONFFILE
    app.logger.info("Using config file '{}'".format(conffile))
    try:
        cfg = config.load_config_from_file(conffile)
    except config.ConfigError as e:
        print("config error '{}': {}".format(conffile, e))
        raise
    app.config[config.CONF_KEY] = cfg
    return cfg
