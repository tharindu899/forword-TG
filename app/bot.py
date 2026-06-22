"""Owner-only private command interface for the Render channel copier."""

from __future__ import annotations

import logging
import re
import signal
import threading
import time
from typing import Any

from .api import BotApi
from .copier import CopyController
from .store import Store

LOGGER = logging.getLogger(__name__)

COMMANDS = [
    {"command": "start", "description": "Show channel copier help"},
    {"command": "help", "description": "Show all commands"},
    {"command": "menu", "description": "Show command menu and examples"},
    {"command": "id", "description": "Show your Telegram user ID"},
    {"command": "claim", "description": "Claim bot if OWNER_ID is empty"},
    {"command": "owner", "description": "Show current controller owner"},
    {"command": "appstatus", "description": "Check Render secret setup safely"},
    {"command": "setsource", "description": "Set old/source channel ID"},
    {"command": "settarget", "description": "Set new/target channel ID"},
    {"command": "setrange", "description": "Set START_ID END_ID"},
    {"command": "setstart", "description": "Set first source message ID"},
    {"command": "setend", "description": "Set last source message ID"},
    {"command": "test", "description": "Test copying one old file"},
    {"command": "copy", "description": "Start the configured range"},
    {"command": "pause", "description": "Pause safely after current request"},
    {"command": "resume", "description": "Resume the saved copy job"},
    {"command": "restart", "description": "Copy the range again from the start"},
    {"command": "status", "description": "Refresh the single live PM card"},
    {"command": "config", "description": "Show saved channels and range"},
    {"command": "setbatch", "description": "Set batch size: 1-100"},
    {"command": "setdelay", "description": "Set delay after each batch"},
    {"command": "setinterval", "description": "Set PM update IDs and seconds"},
]

HELP_TEXT = """📦 Channel copier control bot

1) Setup
/setsource -1001234567890
/settarget -1001234567890
/setrange 1 2123
/test 181

2) Copy
/copy — start the configured range
/status — refresh the one live status card
/pause — save progress safely
/resume — continue saved work
/restart — start configured range again

3) Speed
/setbatch 25 — 1 to 100 IDs per request
/setdelay 0.6 — seconds after each batch
/setinterval 25 20 — update card every 25 IDs or 20 seconds

4) Checks
/config — source, target, range, speed options
/appstatus — confirms BOT_TOKEN / OWNER_ID / API_ID / API_HASH without showing secrets
/owner — current controlling user
/id — your Telegram user ID

Tip: you can paste a private source message link anywhere an ID is accepted. Example: t.me/c/3033186334/181.

The bot cannot list old history. It scans every ID in your range and skips deleted, protected, service, text-only, or non-copyable posts."""


class ControlBot:
    def __init__(
        self,
        api: BotApi,
        store: Store,
        configured_owner_id: int,
        auto_resume: bool,
        poll_timeout: int,
        *,
        api_id_configured: bool,
        api_hash_configured: bool,
    ) -> None:
        self.api = api
        self.store = store
        self.configured_owner_id = configured_owner_id if configured_owner_id > 0 else 0
        self.auto_resume = auto_resume
        self.poll_timeout = poll_timeout
        self.api_id_configured = api_id_configured
        self.api_hash_configured = api_hash_configured
        self.stop_event = threading.Event()

        if self.configured_owner_id:
            # Render's explicit OWNER_ID is authoritative after each deploy.
            self.store.set_owner_id(self.configured_owner_id)
        self.controller = CopyController(api, store, self.owner_id())

    def owner_id(self) -> int:
        return self.configured_owner_id or self.store.get_owner_id()

    def start(self) -> None:
        self.api.set_commands(COMMANDS)
        me = self.api.get_me()
        LOGGER.info("Connected as @%s (id=%s)", me.get("username", "unknown"), me.get("id", "?"))
        LOGGER.info(
            "Secrets: BOT_TOKEN configured; OWNER_ID=%s; API_ID=%s; API_HASH=%s.",
            "set" if self.owner_id() else "not set",
            "set" if self.api_id_configured else "not set",
            "set" if self.api_hash_configured else "not set",
        )

        job = self.store.recover_after_restart()
        owner = self.owner_id()
        self.controller.set_owner_id(owner)
        if owner and self.auto_resume and job.get("interrupted"):
            ok, text = self.controller.start()
            LOGGER.info("Auto-resume: %s", text)
            if not ok:
                self.controller.publish_status()

        while not self.stop_event.is_set():
            self.poll_once()

        self.controller.request_shutdown_pause()
        LOGGER.info("Control bot stopped.")

    def stop(self, *_args: Any) -> None:
        self.stop_event.set()
        self.controller.request_shutdown_pause()

    def poll_once(self) -> None:
        offset = self.store.get_update_offset()
        ok, data = self.api.get_updates(offset, self.poll_timeout)
        if not ok:
            description = str(data.get("description", "Unknown getUpdates error"))
            if "conflict" in description.lower():
                LOGGER.error("Another bot instance is polling this token. Keep only one Render worker running.")
                time.sleep(10)
            elif not data.get("stopped"):
                LOGGER.warning("getUpdates failed: %s", description)
                time.sleep(3)
            return

        for update in data.get("result", []):
            update_id = int(update.get("update_id", 0))
            try:
                self.handle_update(update)
            except Exception:
                LOGGER.exception("Failed to handle Telegram update %s", update_id)
            finally:
                if update_id:
                    self.store.set_update_offset(update_id + 1)

    def handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message")
        if not isinstance(message, dict):
            return
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        text = str(message.get("text") or "").strip()
        chat_id = chat.get("id")
        user_id = sender.get("id")
        if not isinstance(chat_id, int) or not isinstance(user_id, int) or chat.get("type") != "private":
            return
        if not text.startswith("/"):
            return

        command, args = self.parse_command(text)
        if command in {"id", "whoami"}:
            self.reply(chat_id, message, f"Your Telegram user ID: {user_id}")
            return

        owner = self.owner_id()
        if not owner:
            if command == "claim":
                self.store.set_owner_id(user_id)
                self.controller.set_owner_id(user_id)
                self.reply(
                    chat_id,
                    message,
                    "✅ You now own this control bot. Add it as admin in source and target channels, then use /help.",
                )
                self.controller.publish_status()
            else:
                self.reply(chat_id, message, "This bot has no owner yet. Send /claim from the account that should control it.")
            return

        if user_id != owner:
            return
        if command == "claim":
            self.reply(chat_id, message, "This bot is already owned by your account.")
            return
        self.handle_owner_command(command, args, chat_id, message)

    @staticmethod
    def parse_command(text: str) -> tuple[str, list[str]]:
        parts = text.split()
        head = parts[0].split("@", 1)[0].lower().lstrip("/")
        return head, parts[1:]

    def reply(self, chat_id: int, message: dict[str, Any], text: str) -> None:
        ok, data = self.api.send_message(chat_id, text, reply_to_message_id=message.get("message_id"))
        if not ok:
            LOGGER.warning("Could not send control reply: %s", data.get("description", "Unknown error"))

    def ensure_not_running(self, chat_id: int, message: dict[str, Any]) -> bool:
        if self.controller.worker_running():
            self.reply(chat_id, message, "A copy job is running. Use /pause, wait for the live card to show PAUSED, then change IDs/settings.")
            return False
        return True

    def reset_for_changed_range(self) -> None:
        settings = self.store.settings()
        start = self.parse_message_id(settings["range_start"])
        end = self.parse_message_id(settings["range_end"])
        if start and end and end >= start:
            self.store.reset_job(start, end)
            self.controller.publish_status()

    def app_status_text(self) -> str:
        owner = self.owner_id()
        return (
            "🔐 Render secret status\n\n"
            "BOT_TOKEN: configured (never shown)\n"
            f"OWNER_ID: {owner if owner else 'not set — use /claim'}\n"
            f"API_ID / APP_ID: {'configured' if self.api_id_configured else 'not set'}\n"
            f"API_HASH / APP_HASH: {'configured' if self.api_hash_configured else 'not set'}\n\n"
            "This copier uses Telegram Bot API, so only BOT_TOKEN is required for copying. API_ID and API_HASH are stored as optional Render secrets and are never displayed or used for a user login."
        )

    def config_text(self) -> str:
        settings = self.store.settings()
        return (
            "⚙️ Saved copy configuration\n\n"
            f"Source: {settings['source_channel'] or 'not set'}\n"
            f"Target: {settings['target_channel'] or 'not set'}\n"
            f"Range: {settings['range_start']}–{settings['range_end']}\n"
            f"Batch: {settings['batch_size']} IDs\n"
            f"Delay: {settings['delay_seconds']} seconds\n"
            f"PM update: every {settings['status_every_ids']} IDs or {settings['status_every_seconds']}s\n\n"
            "All live job status uses one editable message in this bot PM."
        )

    def handle_owner_command(self, command: str, args: list[str], chat_id: int, message: dict[str, Any]) -> None:
        if command in {"start", "help", "menu"}:
            self.reply(chat_id, message, HELP_TEXT)
            self.controller.publish_status()
            return
        if command == "status":
            # Intentionally no extra reply: the existing PM status card is edited.
            self.controller.publish_status()
            return
        if command == "owner":
            owner = self.owner_id()
            source = "Render OWNER_ID" if self.configured_owner_id else "claimed owner"
            self.reply(chat_id, message, f"👤 Controller owner: {owner}\nSource: {source}")
            return
        if command == "appstatus":
            self.reply(chat_id, message, self.app_status_text())
            return
        if command == "config":
            self.reply(chat_id, message, self.config_text())
            return
        if command == "setsource":
            if not self.ensure_not_running(chat_id, message):
                return
            if len(args) != 1:
                self.reply(chat_id, message, "Usage: /setsource -1001234567890\nYou may also paste a t.me/c/... source link.")
                return
            source = self.parse_channel_reference(args[0])
            if not source:
                self.reply(chat_id, message, "Invalid source. Use -100… , @publicchannel, or a private t.me/c/... link.")
                return
            self.store.set("source_channel", source)
            self.reset_for_changed_range()
            self.reply(chat_id, message, f"✅ Source channel saved: {source}")
            return
        if command == "settarget":
            if not self.ensure_not_running(chat_id, message):
                return
            if len(args) != 1:
                self.reply(chat_id, message, "Usage: /settarget -1001234567890\nYou may also paste a t.me/c/... target link.")
                return
            target = self.parse_channel_reference(args[0])
            if not target:
                self.reply(chat_id, message, "Invalid target. Use -100… , @publicchannel, or a private t.me/c/... link.")
                return
            self.store.set("target_channel", target)
            self.reset_for_changed_range()
            self.reply(chat_id, message, f"✅ Target channel saved: {target}")
            return
        if command == "setrange":
            if not self.ensure_not_running(chat_id, message):
                return
            if len(args) != 2:
                self.reply(chat_id, message, "Usage: /setrange START_ID END_ID\nExample: /setrange 1 2123")
                return
            start, end = (self.parse_message_id(value) for value in args)
            if not start or not end or start < 1 or end < start:
                self.reply(chat_id, message, "Invalid range. END_ID must be equal to or larger than START_ID.")
                return
            self.store.set("range_start", start)
            self.store.set("range_end", end)
            self.store.reset_job(start, end)
            self.controller.publish_status()
            self.reply(chat_id, message, f"✅ Range saved: {start:,}–{end:,}. Progress reset.")
            return
        if command in {"setstart", "setend"}:
            if not self.ensure_not_running(chat_id, message):
                return
            if len(args) != 1:
                self.reply(chat_id, message, f"Usage: /{command} MESSAGE_ID")
                return
            value = self.parse_message_id(args[0])
            if not value or value < 1:
                self.reply(chat_id, message, "Invalid message ID.")
                return
            key = "range_start" if command == "setstart" else "range_end"
            self.store.set(key, value)
            settings = self.store.settings()
            start, end = int(settings["range_start"]), int(settings["range_end"])
            if end < start:
                self.reply(chat_id, message, "Saved, but the range is incomplete. Set the other endpoint so END_ID ≥ START_ID.")
            else:
                self.store.reset_job(start, end)
                self.controller.publish_status()
                self.reply(chat_id, message, f"✅ Range saved: {start:,}–{end:,}. Progress reset.")
            return
        if command == "setbatch":
            if not self.ensure_not_running(chat_id, message):
                return
            if len(args) != 1 or not args[0].isdigit() or not 1 <= int(args[0]) <= 100:
                self.reply(chat_id, message, "Usage: /setbatch 25\nChoose a whole number from 1 to 100.")
                return
            self.store.set("batch_size", int(args[0]))
            self.controller.publish_status()
            self.reply(chat_id, message, f"✅ Batch size saved: {args[0]} IDs.")
            return
        if command == "setdelay":
            if not self.ensure_not_running(chat_id, message):
                return
            if len(args) != 1:
                self.reply(chat_id, message, "Usage: /setdelay 0.6")
                return
            try:
                delay = float(args[0])
                if not 0 <= delay <= 30:
                    raise ValueError
            except ValueError:
                self.reply(chat_id, message, "Delay must be a number from 0 to 30 seconds.")
                return
            self.store.set("delay_seconds", f"{delay:.2f}")
            self.controller.publish_status()
            self.reply(chat_id, message, f"✅ Batch delay saved: {delay:.2f}s.")
            return
        if command == "setinterval":
            if not self.ensure_not_running(chat_id, message):
                return
            if len(args) != 2 or not all(value.isdigit() for value in args):
                self.reply(chat_id, message, "Usage: /setinterval 25 20\nFirst = IDs, second = seconds.")
                return
            every_ids, every_seconds = (int(value) for value in args)
            if not 1 <= every_ids <= 500 or not 5 <= every_seconds <= 300:
                self.reply(chat_id, message, "IDs must be 1–500 and seconds must be 5–300.")
                return
            self.store.set("status_every_ids", every_ids)
            self.store.set("status_every_seconds", every_seconds)
            self.controller.publish_status()
            self.reply(chat_id, message, f"✅ PM card updates every {every_ids} IDs or {every_seconds}s.")
            return
        if command == "test":
            if len(args) != 1:
                self.reply(chat_id, message, "Usage: /test OLD_FILE_MESSAGE_ID\nExample: /test 181")
                return
            message_id = self.parse_message_id(args[0])
            if not message_id:
                self.reply(chat_id, message, "Invalid source message ID.")
                return
            _ok, text = self.controller.test_copy(message_id)
            self.reply(chat_id, message, text)
            return
        if command in {"copy", "resume", "restart"}:
            restart = command == "restart"
            if command == "resume" and self.store.job()["status"] != "paused":
                self.reply(chat_id, message, "The job is not paused. Use /copy for a new configured range.")
                return
            ok, text = self.controller.start(restart=restart)
            if not ok:
                self.reply(chat_id, message, text)
            return
        if command == "pause":
            ok, text = self.controller.pause()
            if not ok:
                self.reply(chat_id, message, text)
            return

        self.reply(chat_id, message, "Unknown command. Use /help.")

    @staticmethod
    def parse_message_id(value: str) -> int | None:
        token = value.strip().rstrip("/")
        if token.isdigit():
            return int(token)
        match = re.search(r"/(\d+)$", token)
        return int(match.group(1)) if match else None

    @staticmethod
    def parse_channel_reference(value: str) -> str | None:
        token = value.strip().rstrip("/")
        if token.startswith("-100") and token[4:].isdigit():
            return token
        if token.startswith("@") and len(token) > 1 and re.fullmatch(r"@[A-Za-z0-9_]+", token):
            return token
        private_match = re.search(r"(?:https?://)?t\.me/c/(\d+)(?:/\d+)?$", token, flags=re.IGNORECASE)
        if private_match:
            return f"-100{private_match.group(1)}"
        public_match = re.search(r"(?:https?://)?t\.me/([A-Za-z0-9_]+)(?:/\d+)?$", token, flags=re.IGNORECASE)
        if public_match:
            return f"@{public_match.group(1)}"
        return None


def install_signal_handlers(bot: ControlBot) -> None:
    signal.signal(signal.SIGTERM, bot.stop)
    signal.signal(signal.SIGINT, bot.stop)
