import os
import sys
from argparse import ArgumentParser

import voyandz
from . import config, logging, version


def main():
    profile_file = os.environ.get(config.PROFILE_ENV)
    if profile_file:
        import yappi
        yappi.start()
    try:
        print_version()
        args = parse_args()
        print("", file=sys.stderr)
        app = voyandz.create_app()
        try:
            cfg = init_app_config(app, args.conffile)
        except config.ConfigError:
            sys.exit(1)
        with app.app_context():
            from . import server
            server.autostart()
        app.run(host=cfg['listenaddr'], port=cfg['listenport'], debug=args.develop,
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
    argp = ArgumentParser()
    argp.add_argument('-f', dest='conffile',
                      help='change config file (%(default)s)',
                      default=config.DEFAULT_CONFFILE)
    argp.add_argument('--develop', default=False, action='store_true',
                      help='enable development mode')
    argp.add_argument('-V', '--version', action='version',
                      version='{} {}'.format(version.NAME, version.VERSION))
    return argp.parse_args()


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
