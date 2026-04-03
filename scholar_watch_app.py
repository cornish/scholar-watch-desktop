"""PyInstaller entry point — launches the desktop app directly."""

from scholar_watch.config import load_config
from scholar_watch.desktop.app import start_app

if __name__ == "__main__":
    config = load_config()
    start_app(config)
