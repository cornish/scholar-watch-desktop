"""Helpers for the AppSetting key/value store (DB-backed user settings)."""

from sqlalchemy.orm import Session

from .models import AppSetting

# Known keys
CITING_ENABLED = "citing_enabled"          # "1"/"0" — master on/off for citing-paper fetches
BROWSER_CONNECTED = "browser_connected"    # "1" once the user has done the one-time Chrome login


def get_setting(session: Session, key: str, default: str | None = None) -> str | None:
    row = session.get(AppSetting, key)
    return row.value if row is not None else default


def set_setting(session: Session, key: str, value: str) -> None:
    row = session.get(AppSetting, key)
    if row is None:
        session.add(AppSetting(key=key, value=value))
    else:
        row.value = value
    session.commit()


def get_bool(session: Session, key: str, default: bool) -> bool:
    val = get_setting(session, key)
    if val is None:
        return default
    return val == "1"
