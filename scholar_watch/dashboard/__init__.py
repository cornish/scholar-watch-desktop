"""Flask dashboard app factory."""

from flask import Flask

from ..config import AppConfig, load_config
from ..database import get_session, init_db


def create_app(config: AppConfig | None = None) -> Flask:
    """Create and configure the Flask application."""
    if config is None:
        config = load_config()

    app = Flask(__name__)
    app.config["APP_CONFIG"] = config
    app.config["SECRET_KEY"] = "scholar-watch-dev-key"

    # Ensure DB is initialized
    init_db(config)

    from .routes import bp
    app.register_blueprint(bp)

    @app.teardown_appcontext
    def close_session(exception=None):
        session = getattr(app, "_db_session", None)
        if session:
            session.close()

    return app
