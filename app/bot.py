"""Multi-user private control panels.

Every user can use the bot when ALLOW_ALL_USERS=true. Profiles, jobs, pending
inputs, confirmations, and panel message IDs are keyed by Telegram user ID.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from html import escape
from dataclasses import dataclass
from typing import Any

from pyrogram import Client, filters
from pyrogram.handlers import CallbackQueryHandler, MessageHandler
from pyrogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from .api import BotApi
from .store import Store
from .ui import main_keyboard, panel_text, speed_name
from .workers import JobManager, StatusCard

LOGGER = logging.getLogger(__name__)

MENU_COMMANDS: list[BotCommand] = [
    BotCommand("start", "Open a fresh private panel"),
    BotCommand("help", "Show the compact command guide"),
    BotCommand("copy", "Start or resume your copy"),
    BotCommand("pause", "Pause your active task"),
    BotCommand("status", "Refresh your own status"),
    BotCommand("clean", "Clear source, target, or range"),
    BotCommand("delete", "Delete one message or a range"),
]
COMMAND_NAMES = [item.command for item in MENU_COMMANDS]


@dataclass
class PendingInput:
    action: str
    panel_id: int


@dataclass
class PendingDelete:
    role: str
    start_id: int
    end_id: int
    panel_id: int
    mode: str


class ControlBot:
    def __init__(
        self,
        client: Client,
        api: BotApi,
        store: Store,
        *,
        configured_owner_id: int = 0,
        allow_all_users: bool = True,
        max_active_jobs: int = 3,
        api_id_configured: bool = True,
        api_hash_configured: bool = True,
        force_sub_channel: str = "",
    ) -> None:
        self.client = client
        self.api = api
        self.store = store
        self.configured_owner_id = int(configured_owner_id or 0)
        self.allow_all_users = bool(allow_all_users)
        self.api_id_configured = api_id_configured
        self.api_hash_configured = api_hash_configured
        self.force_sub_channel = force_sub_channel.strip()
        # FORCE_SUB_CHANNEL is the only setup value. The title is fetched
        # from Telegram once at startup and falls back to the @username.
        self.force_sub_title = self.force_sub_channel.lstrip("@") or "Update Channel"
        self.force_sub_url = (
            f"https://t.me/{self.force_sub_channel[1:]}" if self.force_sub_channel.startswith("@") else ""
        )
        self.manager = JobManager(api, store, max_active_jobs=max_active_jobs)
        self._pending: dict[int, PendingInput] = {}
        self._delete_pending: dict[int, PendingDelete] = {}
        self._stop = asyncio.Event()
        self._menu_task: asyncio.Task[Any] | None = None

    async def _load_force_sub_title(self) -> None:
        """Load the public channel display name from FORCE_SUB_CHANNEL.

        The @username remains the fallback, so the gate still works even when
        Telegram cannot resolve the title during startup.
        """
        if not self.force_sub_enabled:
            return
        try:
            chat = await self.client.get_chat(self.force_sub_channel)
            title = str(getattr(chat, "title", "") or "").strip()
            if title:
                self.force_sub_title = title
                LOGGER.info("Force-subscription channel resolved: %s (%s).", title, self.force_sub_channel)
        except Exception as exc:  # noqa: BLE001
            LOGGER.info("Force-subscription title lookup skipped for %s: %s", self.force_sub_channel, exc)

    def _force_sub_label(self) -> str:
        title = escape(self.force_sub_title)
        username = escape(self.force_sub_channel)
        return f"<b>{title}</b> · <code>{username}</code>" if username else f"<b>{title}</b>"

    def permitted(self, user_id: int) -> bool:
        return self.allow_all_users or (self.configured_owner_id > 0 and int(user_id) == self.configured_owner_id)

    async def start(self) -> None:
        self.client.add_handler(MessageHandler(self.on_command, filters.private & filters.command(COMMAND_NAMES)), group=0)
        self.client.add_handler(CallbackQueryHandler(self.on_callback), group=0)
        self.client.add_handler(MessageHandler(self.on_channel_post, filters.channel), group=0)
        self.client.add_handler(MessageHandler(self.on_text_input, filters.private & filters.text & ~filters.command(COMMAND_NAMES)), group=1)

        if self.configured_owner_id:
            if self.store.migrate_legacy_owner(self.configured_owner_id):
                LOGGER.info("Migrated the legacy single-user panel state for configured operator %s.", self.configured_owner_id)
        recovered = self.store.recover_after_restart()
        if recovered:
            LOGGER.info("Marked %s interrupted user task(s) as paused after restart.", len(recovered))

        me = await self.client.get_me()
        await self._load_force_sub_title()
        LOGGER.info("Connected via MTProto as @%s (id=%s)", me.username or "unknown", me.id)
        LOGGER.info("Multi-user mode: %s; max active jobs=%s.", "enabled" if self.allow_all_users else "operator only", self.manager.max_active_jobs)
        LOGGER.info("Force subscription: %s.", "enabled" if self.force_sub_enabled else "disabled")
        LOGGER.info("Peer cache warm-up skipped: Telegram bots cannot use GetDialogs.")
        LOGGER.info("Secrets: BOT_TOKEN configured; API_ID=%s; API_HASH=%s.", "set" if self.api_id_configured else "not set", "set" if self.api_hash_configured else "not set")
        self._menu_task = asyncio.create_task(self._register_menu(), name="register-multiuser-menu")
        await self._stop.wait()
        if self._menu_task:
            self._menu_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._menu_task

    async def stop(self) -> None:
        self._stop.set()

    async def on_channel_post(self, _client: Client, message: Message) -> None:
        chat = getattr(message, "chat", None)
        if chat:
            LOGGER.debug("Received channel update for %s.", getattr(chat, "id", "unknown"))

    async def _register_menu(self) -> None:
        delay = 5
        while not self._stop.is_set():
            try:
                await self.client.set_bot_commands(MENU_COMMANDS)
                await self.client.set_bot_commands(MENU_COMMANDS, scope=BotCommandScopeAllPrivateChats())
                LOGGER.info("Registered multi-user command menu (%s commands) for private chats.", len(MENU_COMMANDS))
                return
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Command menu registration failed: %s. Retrying in %ss.", exc, delay)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
                delay = min(delay * 2, 60)

    @staticmethod
    def _symbol(title: str, rows: list[str]) -> str:
        lines = [f"▤ <b>{title}</b>"]
        for i, row in enumerate(rows or ["ℹ️ No details"]):
            lines.append(("└" if i == len(rows) - 1 else "├") + " " + row)
        return "\n".join(lines)

    @staticmethod
    def _parse_channel(raw: str) -> str:
        """Accept -100 IDs, @usernames, and ordinary Telegram post links."""
        value = raw.strip().rstrip("/")
        compact = value.removeprefix("https://").removeprefix("http://")
        if compact.startswith("t.me/"):
            parts = [part for part in compact.split("/")[1:] if part]
            # Private channel link: t.me/c/<internal_channel_id>/<message_id>
            if len(parts) >= 3 and parts[0] == "c" and parts[1].isdigit():
                return "-100" + parts[1]
            # Public channel link: t.me/<username>/<message_id>
            if len(parts) >= 2 and parts[0] not in {"c", "joinchat"} and not parts[0].startswith("+"):
                return "@" + parts[0].lstrip("@")
        if value.startswith("@") and len(value) > 1:
            return value
        if value.startswith("-100") and value[4:].isdigit():
            return value
        return ""

    @staticmethod
    def _parse_id(raw: str) -> int | None:
        text = raw.strip().rstrip("/")
        if text.isdigit():
            return int(text)
        match = re.search(r"/(\d+)$", text)
        return int(match.group(1)) if match else None

    @staticmethod
    def _parse_range(raw: str) -> tuple[int, int] | None:
        pieces = [part for part in re.split(r"[\s,\-]+", raw.strip()) if part]
        if len(pieces) != 2 or not all(piece.isdigit() for piece in pieces):
            return None
        start, end = int(pieces[0]), int(pieces[1])
        return (start, end) if start >= 1 and end >= start else None

    async def _delete_user_message(self, message: Message) -> None:
        with contextlib.suppress(Exception):
            await message.delete()

    async def _edit_direct(self, user_id: int, panel_id: int, text: str, markup: InlineKeyboardMarkup) -> bool:
        """Edit only the user's currently bound panel card.

        The bound panel ID changes when /start creates a fresh card. Old cards
        remain untouched and cannot become the live task card again.
        """
        job = self.store.job(user_id)
        current_panel_id = int(job.get("status_message_id") or 0)
        current_chat_id = int(job.get("status_chat_id") or user_id)
        if current_panel_id != int(panel_id) or current_chat_id != int(user_id):
            LOGGER.debug("Skipped stale panel edit for user %s (message %s).", user_id, panel_id)
            return False
        try:
            await self.client.edit_message_text(user_id, panel_id, text, reply_markup=markup, disable_web_page_preview=True)
            return True
        except Exception as exc:  # noqa: BLE001
            if "MESSAGE_NOT_MODIFIED" not in str(exc).upper():
                LOGGER.debug("Panel edit for user %s skipped: %s", user_id, exc)
            return False

    @property
    def force_sub_enabled(self) -> bool:
        return bool(self.force_sub_channel)

    async def _subscription_status(self, user_id: int) -> str:
        """Return ok, not_joined, or error without leaking other user data."""
        if not self.force_sub_enabled:
            return "ok"
        try:
            member = await self.client.get_chat_member(self.force_sub_channel, user_id)
            raw_status = str(getattr(member, "status", "")).lower()
            if any(flag in raw_status for flag in ("left", "banned", "kicked")):
                return "not_joined"
            return "ok"
        except Exception as exc:  # noqa: BLE001
            detail = f"{type(exc).__name__}: {exc}".lower()
            if any(token in detail for token in ("usernotparticipant", "not participant", "not a participant")):
                return "not_joined"
            LOGGER.warning("Force-subscription check failed for user %s: %s", user_id, exc)
            return "error"

    def subscription_text(self, status: str = "not_joined") -> str:
        channel = self._force_sub_label()
        rows = [
            f"📢 Join {channel} to unlock the bot.",
            "🔒 Your own channels and tasks stay private after access is verified.",
            "✅ Join the channel, then press <b>Verify Access</b>.",
        ]
        if status == "error":
            rows.insert(2, "⚠️ Verification is unavailable. Add this bot as an admin in the required channel.")
        return self._symbol("CHAN RELAY", rows)

    def subscription_keyboard(self) -> InlineKeyboardMarkup:
        rows: list[list[InlineKeyboardButton]] = []
        if self.force_sub_url:
            rows.append([
                InlineKeyboardButton("📢 Join Channel", url=self.force_sub_url),
                InlineKeyboardButton("✅ Verify Access", callback_data="sub:check"),
            ])
        else:
            rows.append([InlineKeyboardButton("✅ Verify Access", callback_data="sub:check")])
        return InlineKeyboardMarkup(rows)

    async def _show_subscription_gate(self, user_id: int, *, panel_id: int = 0, status: str = "not_joined") -> None:
        text = self.subscription_text(status)
        markup = self.subscription_keyboard()
        if panel_id and await self._edit_direct(user_id, panel_id, text, markup):
            return
        job = self.store.job(user_id)
        current_id = int(job.get("status_message_id") or 0)
        if current_id and await self._edit_direct(user_id, current_id, text, markup):
            return
        try:
            message = await self.client.send_message(user_id, text, reply_markup=markup, disable_web_page_preview=True)
            self.store.bind_panel(user_id, user_id, int(message.id))
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Could not show subscription gate for user %s: %s", user_id, exc)

    async def _subscription_allowed(self, user_id: int, *, panel_id: int = 0) -> bool:
        status = await self._subscription_status(user_id)
        if status == "ok":
            return True
        await self._show_subscription_gate(user_id, panel_id=panel_id, status=status)
        return False

    def welcome_text(self) -> str:
        return self._symbol("CHAN RELAY", [
            "👋 <b>Welcome to @ChanRelayBot.</b>",
            "📦 Copy media and manage message ranges between channels.",
            "🔒 Every user gets a private workspace and private live task card.",
            "⚙️ Open your panel when you are ready.",
        ])

    def welcome_keyboard(self) -> InlineKeyboardMarkup:
        rows = [[
            InlineKeyboardButton("⚙️ Open Panel", callback_data="panel:main"),
            InlineKeyboardButton("❓ Help", callback_data="help:open"),
        ]]
        return InlineKeyboardMarkup(rows)

    def help_text(self) -> str:
        return self._symbol("HELP", [
            "🔒 Only your own setup and task are shown.",
            "▶️ <code>/start</code>  New private panel",
            "❓ <code>/help</code>  This guide",
            "📦 <code>/copy</code>  Start a configured copy",
            "⏸ <code>/pause</code>  Pause your own task",
            "🔄 <code>/status</code>  Refresh your panel",
            "🧹 <code>/clean</code>  Clear saved source, target, or range",
            "🗑 <code>/delete</code>  Delete after confirmation",
        ])

    def help_keyboard(self) -> InlineKeyboardMarkup:
        rows = [[InlineKeyboardButton("◀️ Back to Panel", callback_data="panel:main")]]
        return InlineKeyboardMarkup(rows)

    async def create_welcome(self, user_id: int) -> bool:
        """Create one fresh panel and make it the only card that receives updates."""
        self.store.ensure_user(user_id)
        self._pending.pop(user_id, None)
        self._delete_pending.pop(user_id, None)
        try:
            status = await self._subscription_status(user_id)
            text = self.welcome_text() if status == "ok" else self.subscription_text(status)
            markup = self.welcome_keyboard() if status == "ok" else self.subscription_keyboard()
            message = await self.client.send_message(
                user_id,
                text,
                reply_markup=markup,
                disable_web_page_preview=True,
            )
            self.store.bind_panel(user_id, user_id, int(message.id))
            return True
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Could not create fresh panel for user %s: %s", user_id, exc)
            return False

    async def ensure_main(self, user_id: int, *, force_create: bool = True, note: str = "") -> bool:
        self.store.ensure_user(user_id)
        job = self.store.job(user_id)
        settings = self.store.settings(user_id)
        text = panel_text(settings, job, note)
        markup = main_keyboard(job)
        message_id = int(job.get("status_message_id") or 0)
        chat_id = str(job.get("status_chat_id") or user_id)
        if message_id:
            try:
                await self.client.edit_message_text(int(chat_id), message_id, text, reply_markup=markup, disable_web_page_preview=True)
                self.store.bind_panel(user_id, user_id, message_id)
                return True
            except Exception as exc:  # noqa: BLE001
                if "MESSAGE_NOT_MODIFIED" in str(exc).upper():
                    return True
                LOGGER.debug("Stored panel unavailable for user %s: %s", user_id, exc)
        if not force_create:
            return False
        try:
            message = await self.client.send_message(user_id, text, reply_markup=markup, disable_web_page_preview=True)
            self.store.bind_panel(user_id, user_id, int(message.id))
            return True
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Could not create panel for user %s: %s", user_id, exc)
            return False

    async def _show(self, user_id: int, text: str, markup: InlineKeyboardMarkup) -> None:
        await self.ensure_main(user_id, force_create=True)
        job = self.store.job(user_id)
        panel_id = int(job.get("status_message_id") or 0)
        if panel_id:
            await self._edit_direct(user_id, panel_id, text, markup)

    async def _adopt_callback_panel(self, query: CallbackQuery) -> tuple[int, int] | None:
        """Accept callbacks only from a user's newest bound panel.

        This prevents an old card from being rebound and receiving the live
        update stream after the user opened a fresh /start card.
        """
        if not query.from_user or not query.message:
            return None
        user_id = int(query.from_user.id)
        if not self.permitted(user_id):
            await query.answer("This bot is not available for this account.", show_alert=True)
            return None
        if int(query.message.chat.id) != user_id:
            await query.answer("Open your own private panel first.", show_alert=True)
            return None
        self.store.ensure_user(user_id)
        panel_id = int(query.message.id)
        job = self.store.job(user_id)
        current_panel_id = int(job.get("status_message_id") or 0)
        current_chat_id = int(job.get("status_chat_id") or user_id)
        if panel_id != current_panel_id or current_chat_id != user_id:
            await query.answer("This is an old card. Send /start to open your latest panel.", show_alert=True)
            return None
        return user_id, panel_id

    def setup_text(self, user_id: int, note: str = "") -> str:
        s = self.store.settings(user_id)
        rows = [
            "⚙️ <b>SETUP</b>",
            f"📥 Source  <code>{s['source_channel'] or 'not set'}</code>",
            f"📤 Target  <code>{s['target_channel'] or 'not set'}</code>",
            f"🎯 Range  <code>{s['range_start']} → {s['range_end']}</code>",
            f"⚡ Speed  <code>{speed_name(s)}</code>",
        ]
        if note:
            rows.append(f"💬 {note}")
        return self._symbol("CHANNEL COPIER", rows)

    @staticmethod
    def setup_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Source", callback_data="input:source"), InlineKeyboardButton("📤 Target", callback_data="input:target")],
            [InlineKeyboardButton("🎯 Range", callback_data="input:range"), InlineKeyboardButton("🧪 Test", callback_data="input:test")],
            [InlineKeyboardButton("⚡ Speed", callback_data="speed:open"), InlineKeyboardButton("◀️ Back to Panel", callback_data="panel:main")],
        ])

    def input_text(self, action: str, error: str = "") -> str:
        details = {
            "source": ("SOURCE CHANNEL", "Reply with a private channel ID, @username, or Telegram post link."),
            "target": ("TARGET CHANNEL", "Reply with a private channel ID, @username, or Telegram post link."),
            "range": ("MESSAGE RANGE", "Reply with two IDs: <code>100 250</code>"),
            "test": ("TEST MESSAGE", "Reply with one source media message ID or post link."),
        }
        title, text = details[action]
        rows = [f"📝 {text}"]
        if error:
            rows.append(error)
        rows.append("✕ Cancel returns to Setup.")
        return self._symbol(title, rows)

    @staticmethod
    def input_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[InlineKeyboardButton("✕ Cancel", callback_data="flow:cancel")]])

    def clean_text(self) -> str:
        return self._symbol("CLEAN SETTINGS", ["🧹 Choose only the saved field you want to clear.", "Your other settings stay unchanged."])

    @staticmethod
    def clean_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑 Source", callback_data="clean:ask:source"), InlineKeyboardButton("🗑 Target", callback_data="clean:ask:target")],
            [InlineKeyboardButton("🗑 Range", callback_data="clean:ask:range")],
            [InlineKeyboardButton("◀️ Back to Panel", callback_data="panel:main")],
        ])

    def clean_confirm_text(self, field: str) -> str:
        name = {"source": "Source Channel", "target": "Target Channel", "range": "Message Range"}[field]
        return self._symbol("CONFIRM CLEAN", [f"⚠️ Clear saved <b>{name}</b>?", "This resets only your own saved setting and task counters."])

    @staticmethod
    def clean_confirm_keyboard(field: str) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🗑 Clear {field.title()}", callback_data=f"clean:confirm:{field}"), InlineKeyboardButton("✕ Cancel", callback_data="flow:cancel")],
        ])

    def delete_choice_text(self) -> str:
        return self._symbol("DELETE MESSAGES", ["⚠️ Deletion is permanent.", "Choose one message or a bounded range. A final confirmation is required."])

    @staticmethod
    def delete_choice_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑 One Message", callback_data="delete:mode:message"), InlineKeyboardButton("🎯 Message Range", callback_data="delete:mode:range")],
            [InlineKeyboardButton("◀️ Back to Panel", callback_data="panel:main")],
        ])

    def delete_channel_text(self, mode: str, user_id: int) -> str:
        s = self.store.settings(user_id)
        return self._symbol("DELETE CHANNEL", [
            f"🗑 Mode  <code>{'One Message' if mode == 'message' else 'Message Range'}</code>",
            f"📥 Source  <code>{s['source_channel'] or 'not set'}</code>",
            f"📤 Target  <code>{s['target_channel'] or 'not set'}</code>",
            "Choose exactly one channel.",
        ])

    def delete_channel_keyboard(self, mode: str, user_id: int) -> InlineKeyboardMarkup:
        s = self.store.settings(user_id)
        buttons: list[InlineKeyboardButton] = []
        if s["source_channel"]:
            buttons.append(InlineKeyboardButton("📥 Source", callback_data=f"delete:channel:{mode}:source"))
        if s["target_channel"]:
            buttons.append(InlineKeyboardButton("📤 Target", callback_data=f"delete:channel:{mode}:target"))
        rows: list[list[InlineKeyboardButton]] = []
        if len(buttons) >= 2:
            rows.append(buttons[:2])
        elif buttons:
            rows.append([buttons[0]])
        rows.append([InlineKeyboardButton("◀️ Back", callback_data="delete:open")])
        return InlineKeyboardMarkup(rows)

    def delete_input_text(self, mode: str, role: str, error: str = "") -> str:
        prompt = "Reply with one message ID or post link." if mode == "message" else "Reply with two IDs: <code>100 250</code>."
        rows = [f"🧹 Channel  <code>{role.title()}</code>", f"📝 {prompt}", "✕ Cancel returns to the panel."]
        if error:
            rows.insert(2, error)
        return self._symbol("DELETE INPUT", rows)

    @staticmethod
    def delete_input_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[InlineKeyboardButton("✕ Cancel", callback_data="flow:cancel")]])

    def delete_confirm_text(self, pending: PendingDelete, user_id: int) -> str:
        s = self.store.settings(user_id)
        channel = s.get(f"{pending.role}_channel", "")
        total = pending.end_id - pending.start_id + 1
        return self._symbol("CONFIRM DELETE", [
            "⚠️ <b>Messages cannot be restored.</b>",
            f"🧹 Channel  <code>{channel or 'not set'}</code>",
            f"🎯 Range  <code>{pending.start_id:,} → {pending.end_id:,}</code>  •  <code>{total:,} IDs</code>",
            "Press the red delete button only when this is correct.",
        ])

    @staticmethod
    def delete_confirm_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[InlineKeyboardButton("🗑 CONFIRM DELETE", callback_data="delete:confirm"), InlineKeyboardButton("✕ Cancel", callback_data="flow:cancel")]])

    def speed_text(self) -> str:
        return self._symbol("SPEED PROFILE", ["🐢 Safe: fewer flood waits", "⚡ Balanced: recommended", "🚀 Fast: more Telegram rate limits"])

    @staticmethod
    def speed_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🐢 Safe", callback_data="speed:set:safe"), InlineKeyboardButton("⚡ Balanced", callback_data="speed:set:balanced")],
            [InlineKeyboardButton("🚀 Fast", callback_data="speed:set:fast")],
            [InlineKeyboardButton("◀️ Back to Setup", callback_data="setup:open")],
        ])

    async def on_command(self, _client: Client, message: Message) -> None:
        if not message.from_user:
            return
        user_id = int(message.from_user.id)
        if not self.permitted(user_id):
            return
        command = (message.command[0] if message.command else "start").lower()
        self.store.ensure_user(user_id)
        await self._delete_user_message(message)
        if command == "start":
            await self.create_welcome(user_id)
            return
        if not await self._subscription_allowed(user_id):
            return
        if command == "help":
            await self._show(user_id, self.help_text(), self.help_keyboard())
            return
        if command == "status":
            await self.ensure_main(user_id, force_create=True)
            return
        if command == "copy":
            ok, text = await asyncio.to_thread(self.manager.start_copy, user_id, resume=False)
            if ok:
                await self.ensure_main(user_id, note="✅ Copy started.")
            else:
                await self.ensure_main(user_id, note=f"⚠️ {text}")
            return
        if command == "pause":
            ok, text = await asyncio.to_thread(self.manager.pause, user_id)
            await self.ensure_main(user_id, note=("✅ " if ok else "⚠️ ") + text)
            return
        if command == "clean":
            await self._show(user_id, self.clean_text(), self.clean_keyboard())
            return
        if command == "delete":
            await self._show(user_id, self.delete_choice_text(), self.delete_choice_keyboard())
            return

    async def on_callback(self, _client: Client, query: CallbackQuery) -> None:
        adopted = await self._adopt_callback_panel(query)
        if not adopted or not query.data:
            return
        user_id, panel_id = adopted
        data = query.data
        if data == "sub:check":
            status = await self._subscription_status(user_id)
            if status == "ok":
                await query.answer("Access verified")
                await self._edit_direct(user_id, panel_id, self.welcome_text(), self.welcome_keyboard())
            else:
                await query.answer("Join the channel first." if status == "not_joined" else "Verification is unavailable.", show_alert=True)
                await self._edit_direct(user_id, panel_id, self.subscription_text(status), self.subscription_keyboard())
            return
        if not await self._subscription_allowed(user_id, panel_id=panel_id):
            await query.answer("Join the required channel first.", show_alert=True)
            return
        if data == "help:open":
            await query.answer()
            await self._edit_direct(user_id, panel_id, self.help_text(), self.help_keyboard())
            return
        if data == "panel:main" or data == "panel:refresh":
            await query.answer()
            await self.ensure_main(user_id, force_create=True)
            return
        if data == "setup:open":
            if self.manager.running(user_id):
                await query.answer("Pause the task before editing setup.", show_alert=True)
                return
            await query.answer()
            await self._edit_direct(user_id, panel_id, self.setup_text(user_id), self.setup_keyboard())
            return
        if data == "task:copy":
            ok, text = await asyncio.to_thread(self.manager.start_copy, user_id, resume=False)
            await query.answer("Started" if ok else text[:160], show_alert=not ok)
            await self.ensure_main(user_id, note=("✅ " if ok else "⚠️ ") + text)
            return
        if data == "task:resume":
            ok, text = await asyncio.to_thread(self.manager.resume, user_id)
            await query.answer("Resumed" if ok else text[:160], show_alert=not ok)
            await self.ensure_main(user_id, note=("✅ " if ok else "⚠️ ") + text)
            return
        if data == "task:pause":
            ok, text = await asyncio.to_thread(self.manager.pause, user_id)
            await query.answer("Pausing" if ok else text[:160], show_alert=not ok)
            await self.ensure_main(user_id, note=("✅ " if ok else "⚠️ ") + text)
            return
        if data == "flow:cancel":
            self._pending.pop(user_id, None)
            self._delete_pending.pop(user_id, None)
            await query.answer("Cancelled")
            await self.ensure_main(user_id, force_create=True)
            return
        if data.startswith("input:"):
            action = data.split(":", 1)[1]
            if self.manager.running(user_id):
                await query.answer("Pause the task before editing setup.", show_alert=True)
                return
            self._pending[user_id] = PendingInput(action=action, panel_id=panel_id)
            await query.answer("Send one reply")
            await self._edit_direct(user_id, panel_id, self.input_text(action), self.input_keyboard())
            return
        if data == "speed:open":
            await query.answer()
            await self._edit_direct(user_id, panel_id, self.speed_text(), self.speed_keyboard())
            return
        if data.startswith("speed:set:"):
            profile = data.rsplit(":", 1)[1]
            profiles = {"safe": (10, 0.9), "balanced": (25, 0.6), "fast": (40, 0.35)}
            batch, delay = profiles.get(profile, profiles["balanced"])
            self.store.update_settings(user_id, {"batch_size": batch, "delay_seconds": delay})
            await query.answer("Speed saved")
            await self._edit_direct(user_id, panel_id, self.setup_text(user_id, f"✅ {profile.title()} speed saved."), self.setup_keyboard())
            return
        if data.startswith("clean:ask:"):
            field = data.rsplit(":", 1)[1]
            if field not in {"source", "target", "range"}:
                await query.answer("Unknown field", show_alert=True)
                return
            await query.answer()
            await self._edit_direct(user_id, panel_id, self.clean_confirm_text(field), self.clean_confirm_keyboard(field))
            return
        if data.startswith("clean:confirm:"):
            field = data.rsplit(":", 1)[1]
            self.store.clear_field(user_id, field)
            await query.answer("Cleared")
            await self.ensure_main(user_id, note=f"✅ {field.title()} cleared.")
            return
        if data == "delete:open":
            if self.manager.running(user_id):
                await query.answer("Pause the task before deleting.", show_alert=True)
                return
            self._delete_pending.pop(user_id, None)
            await query.answer()
            await self._edit_direct(user_id, panel_id, self.delete_choice_text(), self.delete_choice_keyboard())
            return
        if data.startswith("delete:mode:"):
            mode = data.rsplit(":", 1)[1]
            if mode not in {"message", "range"}:
                await query.answer("Unknown delete mode", show_alert=True)
                return
            await query.answer()
            await self._edit_direct(user_id, panel_id, self.delete_channel_text(mode, user_id), self.delete_channel_keyboard(mode, user_id))
            return
        if data.startswith("delete:channel:"):
            _, _, mode, role = data.split(":", 3)
            if mode not in {"message", "range"} or role not in {"source", "target"}:
                await query.answer("Unknown delete option", show_alert=True)
                return
            if not self.store.settings(user_id).get(f"{role}_channel"):
                await query.answer("That channel is not set.", show_alert=True)
                return
            self._pending[user_id] = PendingInput(action=f"delete:{mode}:{role}", panel_id=panel_id)
            await query.answer("Send the ID or range")
            await self._edit_direct(user_id, panel_id, self.delete_input_text(mode, role), self.delete_input_keyboard())
            return
        if data == "delete:confirm":
            pending = self._delete_pending.get(user_id)
            if not pending:
                await query.answer("Confirmation expired. Open /delete again.", show_alert=True)
                await self.ensure_main(user_id, force_create=True)
                return
            ok, text = await asyncio.to_thread(self.manager.start_delete, user_id, pending.role, pending.start_id, pending.end_id)
            if ok:
                self._delete_pending.pop(user_id, None)
            await query.answer("Deletion started" if ok else text[:160], show_alert=not ok)
            await self.ensure_main(user_id, note=("✅ " if ok else "⚠️ ") + text)
            return
        await query.answer()

    async def on_text_input(self, _client: Client, message: Message) -> None:
        if not message.from_user or not message.text or message.text.startswith("/"):
            return
        user_id = int(message.from_user.id)
        if not self.permitted(user_id):
            return
        pending = self._pending.get(user_id)
        if not pending:
            return
        if not await self._subscription_allowed(user_id, panel_id=pending.panel_id):
            await self._delete_user_message(message)
            return
        if message.reply_to_message and int(message.reply_to_message.id) != pending.panel_id:
            return
        self._pending.pop(user_id, None)
        raw = message.text.strip()
        await self._delete_user_message(message)
        action = pending.action
        if action in {"source", "target"}:
            value = self._parse_channel(raw)
            if not value:
                self._pending[user_id] = pending
                await self._edit_direct(user_id, pending.panel_id, self.input_text(action, "⚠️ Send a valid ID, @username, or post link."), self.input_keyboard())
                return
            self.store.set(user_id, f"{action}_channel", value)
            s = self.store.settings(user_id)
            self.store.reset_job(user_id, int(s["range_start"]), int(s["range_end"]))
            await self._edit_direct(user_id, pending.panel_id, self.setup_text(user_id, f"✅ {action.title()} saved."), self.setup_keyboard())
            return
        if action == "range":
            parsed = self._parse_range(raw)
            if not parsed:
                self._pending[user_id] = pending
                await self._edit_direct(user_id, pending.panel_id, self.input_text("range", "⚠️ Use two IDs: 100 250"), self.input_keyboard())
                return
            start, end = parsed
            self.store.update_settings(user_id, {"range_start": start, "range_end": end})
            self.store.reset_job(user_id, start, end)
            await self._edit_direct(user_id, pending.panel_id, self.setup_text(user_id, f"✅ Range saved: <code>{start:,} → {end:,}</code>"), self.setup_keyboard())
            return
        if action == "test":
            message_id = self._parse_id(raw)
            if not message_id:
                self._pending[user_id] = pending
                await self._edit_direct(user_id, pending.panel_id, self.input_text("test", "⚠️ Send one valid message ID."), self.input_keyboard())
                return
            s = self.store.settings(user_id)
            if not s["source_channel"] or not s["target_channel"]:
                await self._edit_direct(user_id, pending.panel_id, self.setup_text(user_id, "⚠️ Set Source and Target before testing."), self.setup_keyboard())
                return
            ok, data = await asyncio.to_thread(self.api.copy_message, s["target_channel"], s["source_channel"], message_id, lambda: False)
            note = "✅ Test copied without source attribution." if ok else f"❌ Test failed: {data.get('description', 'Unknown error')}"
            await self._edit_direct(user_id, pending.panel_id, self.setup_text(user_id, note), self.setup_keyboard())
            return
        if action.startswith("delete:"):
            _, mode, role = action.split(":", 2)
            if mode == "message":
                message_id = self._parse_id(raw)
                if not message_id:
                    self._pending[user_id] = pending
                    await self._edit_direct(user_id, pending.panel_id, self.delete_input_text(mode, role, "⚠️ Send one valid message ID."), self.delete_input_keyboard())
                    return
                pending_delete = PendingDelete(role, message_id, message_id, pending.panel_id, mode)
            else:
                parsed = self._parse_range(raw)
                if not parsed:
                    self._pending[user_id] = pending
                    await self._edit_direct(user_id, pending.panel_id, self.delete_input_text(mode, role, "⚠️ Use two IDs: 100 250"), self.delete_input_keyboard())
                    return
                pending_delete = PendingDelete(role, parsed[0], parsed[1], pending.panel_id, mode)
            self._delete_pending[user_id] = pending_delete
            await self._edit_direct(user_id, pending.panel_id, self.delete_confirm_text(pending_delete, user_id), self.delete_confirm_keyboard())
