"""Runtime configuration for the multi-user Hugging Face Pyrogram copier."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]


def load_dotenv(path: Path | None = None) -> None:
    env_path = path or BASE_DIR / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def env_text(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def env_int(name: str, default: int = 0) -> int:
    try:
        return int(env_text(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be a whole number.") from exc


def env_bool(name: str, default: bool = False) -> bool:
    raw = env_text(name, "true" if default else "false").lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false.")


class Settings:
    def __init__(self) -> None:
        load_dotenv()
        self.bot_token = env_text("BOT_TOKEN")
        self.owner_id = env_int("OWNER_ID", 0)  # optional operator / legacy migration only
        self.api_id = env_int("API_ID", 0)
        self.api_hash = env_text("API_HASH")
        self.session_name = env_text("SESSION_NAME", "channel_copier_mtproto_bot")
        self.data_dir = Path(env_text("DATA_DIR", str(BASE_DIR / "data"))).expanduser()
        self.auto_resume = env_bool("AUTO_RESUME", False)
        self.allow_all_users = env_bool("ALLOW_ALL_USERS", True)
        self.max_active_jobs = max(1, env_int("MAX_ACTIVE_JOBS", 3))
        self.log_level = env_text("LOG_LEVEL", "INFO").upper()
        self.ipv6 = env_bool("PYROGRAM_IPV6", False)
        # Optional public force subscription. A single @username is enough.
        # Leave FORCE_SUB_CHANNEL empty to keep it disabled.
        self.force_sub_channel = env_text("FORCE_SUB_CHANNEL")

    def validate(self) -> None:
        if not self.bot_token or ":" not in self.bot_token:
            raise ValueError("BOT_TOKEN is missing or invalid. Add it as a Space Secret.")
        if self.owner_id < 0:
            raise ValueError("OWNER_ID must be a positive Telegram user ID or 0.")
        if self.api_id <= 0:
            raise ValueError("API_ID is required for MTProto/Pyrogram bot login.")
        if not self.api_hash:
            raise ValueError("API_HASH is required for MTProto/Pyrogram bot login.")
        if self.force_sub_channel and not self.force_sub_channel.startswith("@"):
            raise ValueError("FORCE_SUB_CHANNEL must be a public channel username such as @TharinduHub.")
        self.data_dir.mkdir(parents=True, exist_ok=True)
