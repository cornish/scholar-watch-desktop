"""Eel desktop app entry point."""

import os
import sys

import eel

from ..config import AppConfig
from ..database import init_db

# Import api module to register @eel.expose functions
from . import api  # noqa: F401


def _web_dir() -> str:
    """Locate the web/ folder in both dev and PyInstaller frozen modes."""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "scholar_watch", "desktop", "web")
    return os.path.join(os.path.dirname(__file__), "web")


def start_app(config: AppConfig) -> None:
    """Initialize the database, configure Eel, and launch the desktop window."""
    init_db(config)
    api.set_config(config)

    eel.init(_web_dir())

    try:
        eel.start("index.html", size=(1200, 800), mode="edge")
    except EnvironmentError:
        # Edge not available, try Chrome
        try:
            eel.start("index.html", size=(1200, 800), mode="chrome")
        except EnvironmentError:
            # Fall back to default browser
            eel.start("index.html", size=(1200, 800), mode="default")
