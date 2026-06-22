"""Runtime configuration for the Render Telegram channel copier."""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]


def load_dotenv(path: Path | None = None) -> None:
    """Load a small local .env file without a third-party dependency."""
    env_path = path or BASE_DIR / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def env_text(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def env_int(name: str, default: int = 0) -> int:
    raw = env_text(name, str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc


def env_bool(name: str, default: bool = False) -> bool:
    raw = env_text(name, "true" if default else "false").lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false, got {raw!r}")


class Settings:
    """Runtime settings read from Render variables or a local .env file."""

    def __init__(self) -> None:
        load_dotenv()
        self.bot_token = env_text("BOT_TOKEN")
        self.owner_id = env_int("OWNER_ID", 0)

        # Kept as optional Render secrets because the owner requested the
        # Telegram app values to be part of the deployment configuration.
        # This bot deliberately uses the Bot API, so it never logs in as a
        # user and does not transmit these values to Telegram.
        self.api_id = env_text("API_ID") or env_text("APP_ID")
        self.api_hash = env_text("API_HASH") or env_text("APP_HASH")

        self.data_dir = Path(env_text("DATA_DIR", str(BASE_DIR / "data"))).expanduser()
        self.auto_resume = env_bool("AUTO_RESUME", True)
        self.poll_timeout = max(5, min(env_int("POLL_TIMEOUT_SECONDS", 25), 50))
        self.http_timeout = max(10, env_int("HTTP_TIMEOUT_SECONDS", 45))
        self.network_retry_seconds = max(2, env_int("NETWORK_RETRY_SECONDS", 8))
        self.log_level = env_text("LOG_LEVEL", "INFO").upper()

    @property
    def app_credentials_configured(self) -> bool:
        return bool(self.api_id and self.api_hash)

    def validate(self) -> None:
        if not self.bot_token or ":" not in self.bot_token:
            raise ValueError("BOT_TOKEN is missing or invalid. Set it in Render Environment settings.")
        if self.owner_id < 0:
            raise ValueError("OWNER_ID must be a positive Telegram user ID or 0.")
        self.data_dir.mkdir(parents=True, exist_ok=True)
