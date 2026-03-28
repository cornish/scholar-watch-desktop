"""YAML configuration loading with environment variable interpolation."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class DatabaseConfig:
    path: str = "data/scholar_watch.db"

    @property
    def uri(self) -> str:
        db_path = Path(self.path)
        if not db_path.is_absolute():
            db_path = PROJECT_ROOT / db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{db_path}"


@dataclass
class ProxyConfig:
    type: str = "none"
    api_key: str = ""
    http: str = ""
    https: str = ""


@dataclass
class ScrapingConfig:
    min_delay: float = 5.0
    max_delay: float = 15.0
    max_publications: int = 500
    proxy: ProxyConfig = field(default_factory=ProxyConfig)


@dataclass
class ResearcherEntry:
    scholar_id: str
    name: str = ""


@dataclass
class SmtpConfig:
    host: str = "smtp.gmail.com"
    port: int = 587
    use_tls: bool = True
    username: str = ""
    password: str = ""


@dataclass
class EmailConfig:
    enabled: bool = False
    smtp: SmtpConfig = field(default_factory=SmtpConfig)
    from_address: str = ""
    to_addresses: list[str] = field(default_factory=list)
    subject_prefix: str = "[Scholar Watch]"


@dataclass
class DashboardConfig:
    host: str = "127.0.0.1"
    port: int = 5000
    debug: bool = False


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 9743
    secret_key: str = "dev-key-change-me"


def load_server_config() -> ServerConfig:
    """Load server config from environment variables."""
    return ServerConfig(
        host=os.environ.get("SCHOLAR_WATCH_HOST", "127.0.0.1"),
        port=int(os.environ.get("SCHOLAR_WATCH_PORT", "9743")),
        secret_key=os.environ.get(
            "SCHOLAR_WATCH_SECRET_KEY", "dev-key-change-me"
        ),
    )


@dataclass
class AppConfig:
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    scraping: ScrapingConfig = field(default_factory=ScrapingConfig)
    researchers: list[ResearcherEntry] = field(default_factory=list)
    email: EmailConfig = field(default_factory=EmailConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)


def _interpolate_env_vars(value: str) -> str:
    """Replace ${VAR_NAME} patterns with environment variable values."""
    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        return os.environ.get(var_name, match.group(0))
    return re.sub(r"\$\{(\w+)\}", replacer, value)


def _interpolate_recursive(obj):
    """Recursively interpolate environment variables in a config dict."""
    if isinstance(obj, str):
        return _interpolate_env_vars(obj)
    if isinstance(obj, dict):
        return {k: _interpolate_recursive(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_interpolate_recursive(item) for item in obj]
    return obj


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Load configuration from YAML file.

    Searches in order:
    1. Explicit path if provided
    2. config/config.yaml
    3. config/config.example.yaml (fallback)
    """
    if config_path:
        path = Path(config_path)
    else:
        path = PROJECT_ROOT / "config" / "config.yaml"
        if not path.exists():
            path = PROJECT_ROOT / "config" / "config.example.yaml"

    if not path.exists():
        return AppConfig()

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    raw = _interpolate_recursive(raw)

    db_cfg = DatabaseConfig(**raw.get("database", {}))

    scraping_raw = raw.get("scraping", {})
    proxy_raw = scraping_raw.pop("proxy", {})
    proxy_cfg = ProxyConfig(**proxy_raw)
    scraping_cfg = ScrapingConfig(**scraping_raw, proxy=proxy_cfg)

    researchers = [
        ResearcherEntry(**r) for r in raw.get("researchers", [])
    ]

    email_raw = raw.get("email", {})
    smtp_raw = email_raw.pop("smtp", {})
    smtp_cfg = SmtpConfig(**smtp_raw)
    email_cfg = EmailConfig(**email_raw, smtp=smtp_cfg)

    dashboard_cfg = DashboardConfig(**raw.get("dashboard", {}))

    return AppConfig(
        database=db_cfg,
        scraping=scraping_cfg,
        researchers=researchers,
        email=email_cfg,
        dashboard=dashboard_cfg,
    )
