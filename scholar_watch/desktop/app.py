"""Eel desktop app entry point."""

import eel

from ..config import AppConfig
from ..database import init_db

# Import api module to register @eel.expose functions
from . import api  # noqa: F401


def start_app(config: AppConfig) -> None:
    """Initialize the database, configure Eel, and launch the desktop window."""
    init_db(config)
    api.set_config(config)

    import os
    web_dir = os.path.join(os.path.dirname(__file__), "web")
    eel.init(web_dir)

    try:
        eel.start("index.html", size=(1200, 800), mode="edge")
    except EnvironmentError:
        # Edge not available, try Chrome
        try:
            eel.start("index.html", size=(1200, 800), mode="chrome")
        except EnvironmentError:
            # Fall back to default browser
            eel.start("index.html", size=(1200, 800), mode="default")
