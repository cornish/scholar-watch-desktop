"""Flask dashboard app factory."""

from flask import Flask, g

from ..auth import login_manager
from ..config import AppConfig, ServerConfig, load_config, load_server_config
from ..database import get_session, init_db


def create_app(
    config: AppConfig | None = None,
    server_config: ServerConfig | None = None,
) -> Flask:
    """Create and configure the Flask application."""
    if config is None:
        config = load_config()
    if server_config is None:
        server_config = load_server_config()

    app = Flask(__name__)
    app.config["APP_CONFIG"] = config
    app.config["SECRET_KEY"] = server_config.secret_key

    # Ensure DB is initialized
    init_db(config)

    # Initialize Flask-Login
    login_manager.init_app(app)

    from .routes import bp
    app.register_blueprint(bp)

    @app.before_request
    def open_session():
        g.db_session = get_session(config)

    @app.teardown_appcontext
    def close_session(exception=None):
        session = g.pop("db_session", None)
        if session is not None:
            session.close()

    return app
