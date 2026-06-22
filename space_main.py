#!/usr/bin/env python3
"""Hugging Face Docker Space entry point — Pyrogram MTProto version."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pyrogram import Client

from app.pyrogram_compat import apply_peer_id_compat

from app.api import BotApi
from app.bot import ControlBot
from app.config import Settings
from app.store import Store


class ServiceRunner:
    def __init__(self, settings: Settings, store: Store) -> None:
        self.settings = settings
        self.store = store
        self.thread: threading.Thread | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.bot: ControlBot | None = None
        self.client: Client | None = None
        self.ready = threading.Event()
        self.failed: str = ""

    def start(self) -> None:
        self.thread = threading.Thread(target=self._thread_main, name="pyrogram-mtproto-bot", daemon=True)
        self.thread.start()

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception as exc:  # noqa: BLE001
            self.failed = str(exc)
            logging.getLogger(__name__).exception("Pyrogram MTProto service stopped: %s", exc)
        finally:
            self.ready.set()

    async def _run(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.client = Client(
            name=self.settings.session_name,
            api_id=self.settings.api_id,
            api_hash=self.settings.api_hash,
            bot_token=self.settings.bot_token,
            workdir=str(self.settings.data_dir),
            ipv6=self.settings.ipv6,
            sleep_threshold=90,
            no_updates=False,
        )
        await self.client.start()
        api = BotApi(self.client, self.loop)
        self.bot = ControlBot(
            client=self.client,
            api=api,
            store=self.store,
            configured_owner_id=self.settings.owner_id,
            auto_resume=self.settings.auto_resume,
            api_id_configured=bool(self.settings.api_id),
            api_hash_configured=bool(self.settings.api_hash),
        )
        self.ready.set()
        try:
            await self.bot.start()
        finally:
            api.close()
            await self.client.stop()

    def stop(self) -> None:
        if self.loop and self.bot:
            self.loop.call_soon_threadsafe(lambda: asyncio.create_task(self.bot.stop()))

    def alive(self) -> bool:
        return bool(self.thread and self.thread.is_alive())


class HealthHandler(BaseHTTPRequestHandler):
    runner: ServiceRunner | None = None

    def do_GET(self) -> None:  # noqa: N802
        runner = self.runner
        alive = bool(runner and runner.alive())
        status = 200 if alive else 503
        body = {
            "service": "telegram-channel-copier-pyrogram",
            "status": "running" if alive else "bot-worker-not-running",
            "ready": bool(runner and runner.ready.is_set()),
            "error": runner.failed if runner else "runner not created",
            "transport": "MTProto / Pyrogram",
        }
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args: object) -> None:  # noqa: A003
        logging.getLogger("health").info("%s - %s", self.address_string(), fmt % args)


# Sri Lanka has a fixed UTC+05:30 offset and no daylight-saving changes.
# A custom formatter keeps container, Pyrogram, and copier logs in Sri Lankan time
# even when the Hugging Face host itself runs in UTC.
SRI_LANKA_TZ = timezone(timedelta(hours=5, minutes=30), name="SLST")


class SriLankaFormatter(logging.Formatter):
    """Render every logging record in Asia/Colombo time."""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:  # noqa: N802
        local_time = datetime.fromtimestamp(record.created, tz=SRI_LANKA_TZ)
        if datefmt:
            return local_time.strftime(datefmt)
        return f"{local_time:%Y-%m-%d %H:%M:%S},{int(record.msecs):03d} SLST"


def configure_logging(level: str, data_dir: Path) -> None:
    """Configure stdout and file logs in Sri Lankan Standard Time (UTC+05:30)."""
    data_dir.mkdir(parents=True, exist_ok=True)

    # Also expose TZ for libraries that use the process-local clock directly.
    os.environ["TZ"] = "Asia/Colombo"
    if hasattr(time, "tzset"):
        time.tzset()

    formatter = SriLankaFormatter("%(asctime)s | %(levelname)-5s | %(name)s | %(message)s")
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    try:
        handlers.append(logging.FileHandler(data_dir / "copier.log", encoding="utf-8"))
    except OSError:
        pass

    for handler in handlers:
        handler.setFormatter(formatter)

    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        handlers=handlers,
        force=True,
    )


def main() -> int:
    settings = Settings(); settings.validate()
    apply_peer_id_compat()
    configure_logging(settings.log_level, settings.data_dir)
    logger = logging.getLogger(__name__)
    store = Store(settings.data_dir / "channel_copier.sqlite3")
    runner = ServiceRunner(settings, store)
    runner.start()

    HealthHandler.runner = runner
    port = int(os.environ.get("PORT", "7860"))
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    logger.info("Hugging Face Space health endpoint listening on port %s", port)
    logger.info("Data directory: %s", settings.data_dir)
    logger.info("Transport: Pyrogram MTProto. API_ID/API_HASH are required; Bot API HTTP is not used.")
    logger.info("New private-channel ID compatibility: enabled.")

    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        runner.stop()
        server.server_close()
        if runner.thread:
            runner.thread.join(timeout=15)
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
