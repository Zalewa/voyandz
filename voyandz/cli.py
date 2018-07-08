# coding: utf-8
from . import config, logging, version
import voyandz

from optparse import OptionParser
import sys


def main():
    print_version()
    options = parse_args()
    if options.version:
        exit(0)
    print("", file=sys.stderr)
    try:
        cfg = config.init_app_config(voyandz.app, options.conffile)
    except config.ConfigError:
        exit(1)
    voyandz.app.run(host=cfg['listenaddr'], port=cfg['listenport'],
                    request_handler=logging.FormattedRequestHandler)


def print_version(file=sys.stderr):
    print("{} ({}) {} ({})".format(
        version.FULLNAME, voyandz.__name__,
        version.VERSION, version.YEARSPAN),
        file=file)
    print("On MIT License; no warranty", file=file)


def parse_args():
    opt_parser = OptionParser()
    opt_parser.add_option('-f', dest='conffile',
                          help='change config file (default: {})'.format(config.DEFAULT_CONFFILE),
                          default=config.DEFAULT_CONFFILE)
    opt_parser.add_option('-V', '--version', dest='version', default=False,
                          action='store_true', help='display version and quit')
    options, _ = opt_parser.parse_args()
    return options
