# coding: utf-8
from . import version
import flask

__version__ = version.VERSION


def create_app():
    app = flask.Flask(__name__)

    with app.app_context():
        # Create routes
        from . import server  # noqa
        return app
