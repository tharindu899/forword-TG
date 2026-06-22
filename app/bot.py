"""Owner-only compact inline control panel for the Pyrogram channel copier."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from dataclasses import dataclass
from typing import Any

from pyrogram import Client, filters
from pyrogram.handlers import CallbackQueryHandler, MessageHandler
from pyrogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from .api import BotApi
from .copier import CopyController
from .store import Store

LOGGER = logging.getLogger(__name__)

# Keep Telegram's visible slash-command menu small. Everything else is in buttons.
MENU_COMMANDS: list[BotCommand] = [
    BotCommand("start", "Open or refresh the panel"),
    BotCommand("copy", "Start or resume copy"),
    BotCommand("pause", "Pause safely"),
    BotCommand("status", "Refresh progress"),
]
VISIBLE_COMMAND_NAMES = [item.command for item in MENU_COMMANDS]
HIDDEN_COMMAND_NAMES = ["claim", "syncmenu"]
ALL_COMMAND_NAMES = VISIBLE_COMMAND_NAMES + HIDDEN_COMMAND_NAMES


@dataclass
class PendingInput:
    action: str
    panel_id: int


class ControlBot:
    """Runs one editable owner-PM card: setup, controls, and live progress."""

    def __init__(
        self,
        client: Client,
        api: BotApi,
        store: Store,
        configured_owner_id: int,
        auto_resume: bool,
        *,
        api_id_configured: bool,
        api_hash_configured: bool,
    ) -> None:
        self.client = client
        self.api = api
        self.store = store
        self.configured_owner_id = configured_owner_id if configured_owner_id > 0 else 0
        self.auto_resume = auto_resume
        self.api_id_configured = api_id_configured
        self.api_hash_configured = api_hash_configured
        if self.configured_owner_id:
            self.store.set_owner_id(self.configured_owner_id)
        self.controller = CopyController(api, store, self.owner_id())
        self._stop = asyncio.Event()
        self._menu_task: asyncio.Task[Any] | None = None
        self._pending: dict[int, PendingInput] = {}

    def owner_id(self) -> int:
        return self.configured_owner_id or self.store.get_owner_id()

    async def start(self) -> None:
        self.client.add_handler(
            MessageHandler(self.on_command, filters.private & filters.command(ALL_COMMAND_NAMES)),
            group=0,
        )
        self.client.add_handler(CallbackQueryHandler(self.on_callback), group=0)
        self.client.add_handler(
            MessageHandler(
                self.on_text_input,
                filters.private & filters.text & ~filters.command(ALL_COMMAND_NAMES),
            ),
            group=1,
        )

        known_dialogs = await self.prime_peer_cache()
        me = await self.client.get_me()
        LOGGER.info("Connected via MTProto as @%s (id=%s)", me.username or "unknown", me.id)
        LOGGER.info("Peer cache warmed from %s dialog(s); private channel IDs can now be resolved.", known_dialogs)
        LOGGER.info("Bot transport: Pyrogram MTProto. One-message compact PM panel enabled.")
        LOGGER.info(
            "Secrets: BOT_TOKEN configured; OWNER_ID=%s; API_ID=%s; API_HASH=%s.",
            "set" if self.owner_id() else "not set",
            "set" if self.api_id_configured else "not set",
            "set" if self.api_hash_configured else "not set",
        )
        self.queue_menu_sync(force=False)

        job = self.store.recover_after_restart()
        owner = self.owner_id()
        self.controller.set_owner_id(owner)
        if owner and self.auto_resume and job.get("interrupted"):
            ok, text = await asyncio.to_thread(self.controller.start)
            LOGGER.info("Auto-resume: %s", text)
            if not ok:
                await asyncio.to_thread(self.controller.publish_status)

        await self._stop.wait()
        await asyncio.to_thread(self.controller.request_shutdown_pause)
        if self._menu_task:
            self._menu_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._menu_task

    async def stop(self) -> None:
        self._stop.set()

    async def prime_peer_cache(self) -> int:
        """Fetch the bot's dialogs once so Pyrogram stores channel access hashes.

        MTProto requires an access hash for private channels. A bot may be an
        administrator already, but a fresh Hugging Face session has no local
        peer cache until it receives that dialog information.
        """
        count = 0
        try:
            async for _dialog in self.client.get_dialogs(limit=100):
                count += 1
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Could not warm peer cache from dialogs: %s", exc)
        return count

    # ------------------------------------------------------------------
    # Telegram command-menu setup
    # ------------------------------------------------------------------
    def queue_menu_sync(self, *, force: bool) -> None:
        if self._menu_task and not self._menu_task.done():
            self._menu_task.cancel()
        self._menu_task = asyncio.create_task(
            self._register_menu_forever(force=force), name="register-compact-bot-menu"
        )

    async def _set_menu_for_scope(self, label: str, scope: Any | None, *, force: bool) -> tuple[bool, str]:
        try:
            if force:
                if scope is None:
                    await self.client.delete_bot_commands()
                else:
                    await self.client.delete_bot_commands(scope=scope)
            if scope is None:
                await self.client.set_bot_commands(MENU_COMMANDS)
            else:
                await self.client.set_bot_commands(MENU_COMMANDS, scope=scope)
            return True, label
        except Exception as exc:  # noqa: BLE001
            return False, f"{label}: {exc}"

    async def _register_menu_forever(self, *, force: bool) -> None:
        delay = 5
        while not self._stop.is_set():
            owner = self.owner_id()
            scopes: list[tuple[str, Any | None]] = [
                ("default", None),
                ("all private chats", BotCommandScopeAllPrivateChats()),
            ]
            if owner > 0:
                scopes.append(("owner private chat", BotCommandScopeChat(chat_id=owner)))

            results = [await self._set_menu_for_scope(label, scope, force=force) for label, scope in scopes]
            successful = [text for ok, text in results if ok]
            failed = [text for ok, text in results if not ok]
            if "all private chats" in successful or "owner private chat" in successful:
                LOGGER.info(
                    "Registered compact command menu (%s commands) in: %s.",
                    len(MENU_COMMANDS), ", ".join(successful),
                )
                if failed:
                    LOGGER.warning("Optional command-menu scope failure: %s", " | ".join(failed))
                return

            LOGGER.warning(
                "Command-menu registration did not reach a private-chat scope: %s. Retrying in %ss.",
                " | ".join(failed) or "unknown error", delay,
            )
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
            delay = min(delay * 2, 60)
            force = False

    # ------------------------------------------------------------------
    # Symbol-line visual helpers
    # ------------------------------------------------------------------
    @staticmethod
    def symbol_panel(title: str, rows: list[str], note: str = "") -> str:
        """One compact style for every bot card: ▤ header + ├ / └ rows."""
        content = list(rows)
        if note:
            content.append(f"💬 {note}")
        if not content:
            content.append("ℹ️ No details available")

        lines = [f"▤ <b>{title}</b>"]
        for index, row in enumerate(content):
            branch = "└" if index == len(content) - 1 else "├"
            lines.append(f"{branch} {row}")
        return "\n".join(lines)

    @staticmethod
    def _short(value: str, limit: int = 22) -> str:
        value = value or "not set"
        return value if len(value) <= limit else value[: limit - 1] + "…"

    def speed_name(self) -> str:
        s = self.store.settings()
        batch = int(s.get("batch_size") or 25)
        delay = float(s.get("delay_seconds") or 0.6)
        if batch <= 12 or delay >= 0.8:
            return "Safe"
        if batch >= 40 or delay <= 0.4:
            return "Fast"
        return "Balanced"

    def setup_text(self, note: str = "") -> str:
        s = self.store.settings()
        rows = [
            "⚙️ <b>SETUP</b>",
            f"📥 Source  <code>{self._short(s['source_channel'], 28)}</code>",
            f"📤 Target  <code>{self._short(s['target_channel'], 28)}</code>",
            f"🎯 Range  <code>{s['range_start']} → {s['range_end']}</code>",
            f"⚡ Speed  <code>{self.speed_name()}</code>",
        ]
        return self.symbol_panel("CHANNEL COPIER", rows, note or "Tap a field, then send one value.")

    def setup_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📥 Source", callback_data="input:source"),
                InlineKeyboardButton("📤 Target", callback_data="input:target"),
            ],
            [
                InlineKeyboardButton("🎯 Range", callback_data="input:range"),
                InlineKeyboardButton("🧪 Test", callback_data="input:test"),
            ],
            [
                InlineKeyboardButton(f"⚡ {self.speed_name()}", callback_data="speed"),
                InlineKeyboardButton("◀️ Panel", callback_data="status"),
            ],
        ])

    def speed_text(self) -> str:
        return self.symbol_panel(
            "COPY SPEED",
            [
                "⚖️ <b>Balanced</b>  recommended",
                "🐢 Safe  •  slower and steadier",
                "🚀 Fast  •  quicker, may hit limits",
            ],
            "Choose one speed preset below.",
        )

    @staticmethod
    def speed_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🐢 Safe", callback_data="speed:safe"),
                InlineKeyboardButton("⚖️ Balanced", callback_data="speed:balanced"),
            ],
            [InlineKeyboardButton("🚀 Fast", callback_data="speed:fast")],
            [InlineKeyboardButton("◀️ Setup", callback_data="setup")],
        ])

    def input_text(self, action: str, error: str = "") -> str:
        prompts = {
            "source": ("SOURCE CHANNEL", "Send old channel ID, @username, or post link.", "<code>@old_channel_username</code>"),
            "target": ("TARGET CHANNEL", "Send new channel ID or @username.", "<code>@new_channel_username</code>"),
            "range": ("MESSAGE RANGE", "Send start and end message IDs.", "<code>1 2123</code>"),
            "test": ("TEST FILE", "Send one file ID or Telegram post link.", "<code>181</code>"),
        }
        title, guidance, example = prompts[action]
        note = error or f"Reply with one value  •  Example {example}"
        return self.symbol_panel(title, [f"✍️ {guidance}"], note)

    def input_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[InlineKeyboardButton("✕ Cancel", callback_data="input:cancel")]])

    # ------------------------------------------------------------------
    # Owner/auth and silent helpers
    # ------------------------------------------------------------------
    def is_owner(self, user_id: int) -> bool:
        owner = self.owner_id()
        return owner > 0 and user_id == owner

    async def claim_if_needed(self, message: Message, command: str) -> bool:
        if not message.from_user:
            return False
        user_id = int(message.from_user.id)
        owner = self.owner_id()
        if owner:
            return user_id == owner
        if command == "claim":
            self.store.set_owner_id(user_id)
            self.controller.set_owner_id(user_id)
            self.queue_menu_sync(force=True)
            await asyncio.to_thread(self.controller.publish_status)
            return False
        # A misconfigured owner is the only case where a separate reply is needed.
        # It still uses the same compact branch style as every other bot card.
        with contextlib.suppress(Exception):
            await message.reply_text(
                self.symbol_panel(
                    "ACCESS REQUIRED",
                    [
                        "🔒 Set <code>OWNER_ID</code> in Space Secrets",
                        "🔄 Restart the Space after saving it",
                    ],
                    "Or send <code>/claim</code> once from your owner account.",
                ),
                disable_web_page_preview=True,
            )
        return False

    async def delete_user_message(self, message: Message) -> None:
        """Best-effort cleanup of setup replies and typed commands in the owner PM."""
        with contextlib.suppress(Exception):
            await message.delete()

    async def edit_panel(self, query: CallbackQuery, text: str, markup: InlineKeyboardMarkup) -> None:
        try:
            if query.message:
                await query.message.edit_text(text, disable_web_page_preview=True, reply_markup=markup)
        except Exception as exc:  # noqa: BLE001
            if "MESSAGE_NOT_MODIFIED" not in str(exc).upper():
                LOGGER.warning("Could not edit compact panel: %s", exc)

    async def edit_panel_by_id(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        markup: InlineKeyboardMarkup,
    ) -> None:
        try:
            await self.client.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                disable_web_page_preview=True,
                reply_markup=markup,
            )
        except Exception as exc:  # noqa: BLE001
            if "MESSAGE_NOT_MODIFIED" not in str(exc).upper():
                LOGGER.warning("Could not edit compact panel by id: %s", exc)

    async def set_status_note(self, note: str) -> None:
        job = self.store.job()
        job["note"] = note
        self.store.save_job(job)
        await asyncio.to_thread(self.controller.publish_status)

    async def ensure_not_running(self, panel_id: int, owner_id: int) -> bool:
        if await asyncio.to_thread(self.controller.worker_running):
            await self.edit_panel_by_id(
                owner_id,
                panel_id,
                self.setup_text("⏳ Pause the running task before changing setup."),
                self.setup_keyboard(),
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Commands: no extra bot cards; existing control card updates in place.
    # ------------------------------------------------------------------
    async def on_command(self, _client: Client, message: Message) -> None:
        if not message.from_user or not message.text:
            return
        command, _args = self.parse_command(message.text)
        if not await self.claim_if_needed(message, command):
            return

        if command == "start" or command == "status":
            await asyncio.to_thread(self.controller.publish_status)
        elif command == "copy":
            await self.start_or_resume()
        elif command == "pause":
            await self.pause_job()
        elif command == "syncmenu":
            self.queue_menu_sync(force=True)
            await self.set_status_note("🔄 Command menu refresh requested. Close and reopen this PM once the log confirms it.")
        elif command == "claim":
            await asyncio.to_thread(self.controller.publish_status)

        await self.delete_user_message(message)

    async def start_or_resume(self) -> tuple[bool, str]:
        job = self.store.job()
        if job.get("status") == "completed":
            text = "✅ This range is complete. Open Setup and choose a new range."
            await self.set_status_note(text)
            return False, text
        ok, text = await asyncio.to_thread(self.controller.start, False)
        if not ok:
            await self.set_status_note(f"⚠️ {text}")
        return ok, text

    async def pause_job(self) -> tuple[bool, str]:
        ok, text = await asyncio.to_thread(self.controller.pause)
        if not ok:
            await self.set_status_note(f"⚠️ {text}")
        return ok, text

    # ------------------------------------------------------------------
    # Inline callbacks and in-place reply prompts
    # ------------------------------------------------------------------
    async def on_callback(self, _client: Client, query: CallbackQuery) -> None:
        if not query.from_user:
            return
        user_id = int(query.from_user.id)
        if not self.is_owner(user_id):
            await query.answer("Owner only.", show_alert=True)
            return
        data = query.data or ""

        if data == "status" or data == "home":
            await query.answer("Panel refreshed")
            await asyncio.to_thread(self.controller.publish_status)
            return
        if data == "setup":
            await query.answer()
            await self.edit_panel(query, self.setup_text(), self.setup_keyboard())
            return
        if data == "speed":
            await query.answer()
            await self.edit_panel(query, self.speed_text(), self.speed_keyboard())
            return
        if data.startswith("speed:"):
            if await asyncio.to_thread(self.controller.worker_running):
                await query.answer("Pause the task before changing speed.", show_alert=True)
                return
            preset = data.split(":", 1)[1]
            await self.apply_speed_preset(preset)
            await query.answer(f"{preset.title()} speed saved")
            await self.edit_panel(query, self.setup_text(f"✅ {preset.title()} speed saved."), self.setup_keyboard())
            return
        if data == "start":
            ok, text = await self.start_or_resume()
            await query.answer("Copy started" if ok else text[:180], show_alert=not ok)
            return
        if data == "pause":
            ok, text = await self.pause_job()
            await query.answer("Pause requested" if ok else text[:180], show_alert=not ok)
            return
        if data == "sync":
            self.queue_menu_sync(force=True)
            await query.answer("Menu refresh started")
            return
        if data == "input:cancel":
            self._pending.pop(user_id, None)
            await query.answer("Cancelled")
            await self.edit_panel(query, self.setup_text(), self.setup_keyboard())
            return
        if data.startswith("input:"):
            action = data.split(":", 1)[1]
            await self.ask_for_input(query, action)
            return

        await query.answer()

    async def ask_for_input(self, query: CallbackQuery, action: str) -> None:
        if action not in {"source", "target", "range", "test"} or not query.message or not query.from_user:
            return
        if not await self.ensure_not_running(int(query.message.id), int(query.from_user.id)):
            await query.answer("Pause task before editing.", show_alert=True)
            return
        self._pending[int(query.from_user.id)] = PendingInput(action=action, panel_id=int(query.message.id))
        await query.answer("Send one reply")
        await self.edit_panel(query, self.input_text(action), self.input_keyboard())

    async def on_text_input(self, _client: Client, message: Message) -> None:
        if not message.from_user or not message.text or message.text.startswith("/"):
            return
        user_id = int(message.from_user.id)
        if not self.is_owner(user_id):
            return
        pending = self._pending.get(user_id)
        if not pending:
            return
        # A reply is preferred. A plain message is also accepted for Android clients.
        if message.reply_to_message and int(message.reply_to_message.id) != pending.panel_id:
            return
        self._pending.pop(user_id, None)
        if not await self.ensure_not_running(pending.panel_id, user_id):
            await self.delete_user_message(message)
            return
        await self.apply_input(user_id, pending, message.text.strip())
        await self.delete_user_message(message)

    async def apply_input(self, user_id: int, pending: PendingInput, raw: str) -> None:
        action = pending.action
        if action in {"source", "target"}:
            value = self.parse_channel_reference(raw)
            if not value:
                await self.edit_panel_by_id(
                    user_id, pending.panel_id,
                    self.input_text(action, "⚠️ Invalid value. Send -100…, @channel, or t.me link."),
                    self.input_keyboard(),
                )
                self._pending[user_id] = pending
                return
            self.store.set("source_channel" if action == "source" else "target_channel", value)
            await self.reset_for_changed_range()
            label = "source" if action == "source" else "target"
            await self.edit_panel_by_id(
                user_id, pending.panel_id,
                self.setup_text(f"✅ {label.title()} saved."),
                self.setup_keyboard(),
            )
            return

        if action == "range":
            values = [self.parse_message_id(part) for part in re.split(r"[\s,\-]+", raw.strip()) if part]
            if len(values) != 2 or not all(values) or int(values[0]) < 1 or int(values[1]) < int(values[0]):
                await self.edit_panel_by_id(
                    user_id, pending.panel_id,
                    self.input_text("range", "⚠️ Use two IDs: 1 2123"),
                    self.input_keyboard(),
                )
                self._pending[user_id] = pending
                return
            start, end = int(values[0]), int(values[1])
            self.store.set("range_start", start)
            self.store.set("range_end", end)
            self.store.reset_job(start, end)
            await self.edit_panel_by_id(
                user_id, pending.panel_id,
                self.setup_text(f"✅ Range saved: <code>{start:,} → {end:,}</code>"),
                self.setup_keyboard(),
            )
            return

        if action == "test":
            msg_id = self.parse_message_id(raw)
            if not msg_id:
                await self.edit_panel_by_id(
                    user_id, pending.panel_id,
                    self.input_text("test", "⚠️ Send one message ID or post link."),
                    self.input_keyboard(),
                )
                self._pending[user_id] = pending
                return
            ok, text = await asyncio.to_thread(self.controller.test_copy, msg_id)
            note = text.replace("✅ ", "✅ ").replace("❌ ", "❌ ")
            await self.edit_panel_by_id(user_id, pending.panel_id, self.setup_text(note), self.setup_keyboard())

    async def apply_speed_preset(self, preset: str) -> None:
        presets = {
            "safe": {"batch_size": 10, "delay_seconds": "0.90", "individual_delay_seconds": "0.18"},
            "balanced": {"batch_size": 25, "delay_seconds": "0.60", "individual_delay_seconds": "0.12"},
            "fast": {"batch_size": 50, "delay_seconds": "0.40", "individual_delay_seconds": "0.08"},
        }
        for key, value in presets.get(preset, presets["balanced"]).items():
            self.store.set(key, value)

    async def reset_for_changed_range(self) -> None:
        s = self.store.settings()
        start = self.parse_message_id(s["range_start"])
        end = self.parse_message_id(s["range_end"])
        if start and end and end >= start:
            self.store.reset_job(start, end)

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------
    @staticmethod
    def parse_command(text: str) -> tuple[str, list[str]]:
        parts = text.split()
        if not parts:
            return "", []
        return parts[0].split("@", 1)[0].lower().lstrip("/"), parts[1:]

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
        if token.startswith("@") and re.fullmatch(r"@[A-Za-z0-9_]+", token):
            return token
        private = re.search(r"(?:https?://)?t\.me/c/(\d+)(?:/\d+)?$", token, re.I)
        if private:
            return f"-100{private.group(1)}"
        public = re.search(r"(?:https?://)?t\.me/([A-Za-z0-9_]+)(?:/\d+)?$", token, re.I)
        if public:
            return f"@{public.group(1)}"
        return None
