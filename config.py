from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    secret_key: str = "dev-only-change-me"
    admin_token: str | None = None
    database_path: Path = BASE_DIR / "instance" / "transitnotice.db"
    demo_feed_path: Path = BASE_DIR / "instance" / "demo_feed.json"
    sample_data_path: Path = BASE_DIR / "sample_data" / "sample_notices.json"
    live_sources_file: Path | None = None
    enable_demo_source: bool = True
    display_timezone: str = "Asia/Kolkata"
    freshness_minutes: int = 360
    refresh_interval_minutes: int = 15
    enable_scheduler: bool = False
    scheduler_tick_seconds: int = 30
    request_timeout: float = 10.0
    max_retries: int = 3
    backoff_seconds: float = 1.5
    min_request_interval: float = 5.0
    manual_refresh_cooldown: int = 20
    max_notification_attempts: int = 3
    user_agent: str = "TransitNoticeBot/1.0 (student project)"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    mail_from: str = ""
    weather_enabled: bool = True
    weather_lat: float = 13.0827
    weather_lon: float = 80.2707
    weather_label: str = "Demo map area"
    weather_cache_minutes: int = 15
    map_tiles_enabled: bool = True
    map_center_lat: float = 13.0827
    map_center_lon: float = 80.2707
    max_login_failures: int = 5
    log_to_file: bool = True
    log_dir: Path = BASE_DIR / "logs"

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host and self.mail_from)

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(BASE_DIR / ".env")
        live = os.getenv("LIVE_SOURCES_FILE", "").strip()
        db_path = os.getenv("DATABASE_PATH", "").strip()
        defaults = cls()
        return cls(
            secret_key=os.getenv("SECRET_KEY", defaults.secret_key),
            admin_token=os.getenv("ADMIN_TOKEN") or None,
            database_path=Path(db_path) if db_path else defaults.database_path,
            live_sources_file=Path(live) if live else None,
            enable_demo_source=_env_bool("ENABLE_DEMO_SOURCE", True),
            display_timezone=os.getenv("DISPLAY_TIMEZONE", defaults.display_timezone),
            freshness_minutes=_env_int("FRESHNESS_MINUTES", defaults.freshness_minutes),
            refresh_interval_minutes=_env_int("REFRESH_INTERVAL_MINUTES", defaults.refresh_interval_minutes),
            enable_scheduler=_env_bool("ENABLE_SCHEDULER", False),
            request_timeout=_env_float("REQUEST_TIMEOUT", defaults.request_timeout),
            max_retries=_env_int("MAX_RETRIES", defaults.max_retries),
            backoff_seconds=_env_float("BACKOFF_SECONDS", defaults.backoff_seconds),
            min_request_interval=_env_float("MIN_REQUEST_INTERVAL", defaults.min_request_interval),
            user_agent=os.getenv("USER_AGENT", defaults.user_agent),
            weather_enabled=_env_bool("WEATHER_ENABLED", True),
            weather_lat=_env_float("WEATHER_LAT", defaults.weather_lat),
            weather_lon=_env_float("WEATHER_LON", defaults.weather_lon),
            weather_label=os.getenv("WEATHER_LABEL", defaults.weather_label),
            map_tiles_enabled=_env_bool("MAP_TILES_ENABLED", True),
            map_center_lat=_env_float("MAP_CENTER_LAT", defaults.map_center_lat),
            map_center_lon=_env_float("MAP_CENTER_LON", defaults.map_center_lon),
            smtp_host=os.getenv("SMTP_HOST", ""),
            smtp_port=_env_int("SMTP_PORT", 587),
            smtp_username=os.getenv("SMTP_USERNAME", ""),
            smtp_password=os.getenv("SMTP_PASSWORD", ""),
            smtp_use_tls=_env_bool("SMTP_USE_TLS", True),
            mail_from=os.getenv("MAIL_FROM", ""),
        )
