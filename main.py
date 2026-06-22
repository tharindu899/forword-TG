#!/usr/bin/env python3
"""Render entry point for the Telegram Channel Copier control bot."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from app.api import BotApi
from app.bot import ControlBot, install_signal_handlers
from app.config import Settings
from app.store import Store


def configure_logging(level: str, data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    format_text = "%(asctime)s | %(levelname)-5s | %(name)s | %(message)s"
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    try:
        handlers.append(logging.FileHandler(data_dir / "copier.log", encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(level=getattr(logging, level, logging.INFO), format=format_text, handlers=handlers)


def main() -> int:
    settings = Settings()
    settings.validate()
    configure_logging(settings.log_level, settings.data_dir)
    logger = logging.getLogger(__name__)

    store = Store(settings.data_dir / "channel_copier.sqlite3")
    api = BotApi(settings.bot_token, timeout=settings.http_timeout, network_retry_seconds=settings.network_retry_seconds)
    bot = ControlBot(
        api=api,
        store=store,
        configured_owner_id=settings.owner_id,
        auto_resume=settings.auto_resume,
        poll_timeout=settings.poll_timeout,
        api_id_configured=bool(settings.api_id),
        api_hash_configured=bool(settings.api_hash),
    )
    install_signal_handlers(bot)
    logger.info("Data directory: %s", settings.data_dir)
    logger.info("Auto resume: %s", settings.auto_resume)
    try:
        bot.start()
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
    except Exception as exc:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-5s | %(message)s")
        logging.getLogger(__name__).exception("Startup failed: %s", exc)
        raise SystemExit(1)
