"""ClubModule application package.

Gunicorn on the stage server still starts the app as ``app:app``. Keep that
entrypoint working without importing the full Flask application during ordinary
``app.core`` imports used by background scripts.
"""


def __getattr__(name):
    if name == "app":
        from app.main import app as flask_app

        return flask_app
    raise AttributeError(name)
