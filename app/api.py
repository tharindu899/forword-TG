"""Synchronous adapter around the live Pyrogram MTProto client.

The copy worker runs in a thread, while Pyrogram runs on asyncio.  This module
bridges that safely and never calls api.telegram.org.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any, Callable, Iterable

from pyrogram import Client, raw
from pyrogram.errors import FloodWait
from pyrogram.types import InlineKeyboardMarkup

LOGGER = logging.getLogger(__name__)


class BotApi:
    """Small MTProto facade used by the copier and the single status card."""

    def __init__(self, client: Client, loop: asyncio.AbstractEventLoop) -> None:
        self.client = client
        self.loop = loop
        self._closed = threading.Event()

    def close(self) -> None:
        self._closed.set()

    @staticmethod
    def _error(exc: BaseException) -> dict[str, Any]:
        detail = str(exc) or exc.__class__.__name__
        return {
            "description": detail,
            "network_error": isinstance(exc, (OSError, ConnectionError, TimeoutError, FutureTimeout)),
        }

    def _run(self, coro: Any, timeout: float = 180.0) -> tuple[bool, Any]:
        if self._closed.is_set() or self.loop.is_closed():
            return False, {"description": "MTProto client is stopping.", "stopped": True}
        try:
            future = asyncio.run_coroutine_threadsafe(coro, self.loop)
            return True, future.result(timeout=timeout)
        except FutureTimeout:
            return False, {"description": "MTProto request timed out.", "network_error": True}
        except Exception as exc:  # noqa: BLE001 - convert Telegram errors to a stable worker shape
            return False, self._error(exc)

    async def _wait_flood(self, seconds: int, should_stop: Callable[[], bool]) -> bool:
        remaining = max(1, int(seconds))
        LOGGER.warning("Telegram flood wait: pausing %ss before retrying.", remaining)
        while remaining > 0:
            if should_stop():
                return False
            await asyncio.sleep(min(1, remaining))
            remaining -= 1
        return True

    async def _copy_ids(self, target: str, source: str, ids: list[int], should_stop: Callable[[], bool]) -> dict[str, Any]:
        """Copy explicit old post IDs without original-channel attribution."""
        if should_stop():
            return {"stopped": True}

        # This queries only the supplied IDs; it does not enumerate history.
        messages = await self.client.get_messages(source, ids)
        if not isinstance(messages, list):
            messages = [messages]
        copyable = [m.id for m in messages if m and not getattr(m, "empty", False) and getattr(m, "media", None)]
        if not copyable:
            return {"result": [], "skipped_all": True}

        try:
            response = await self.client.invoke(
                raw.functions.messages.ForwardMessages(
                    from_peer=await self.client.resolve_peer(source),
                    id=copyable,
                    random_id=[self.client.rnd_id() for _ in copyable],
                    to_peer=await self.client.resolve_peer(target),
                    drop_author=True,
                )
            )
        except FloodWait as exc:
            if not await self._wait_flood(int(exc.value), should_stop):
                return {"stopped": True}
            return await self._copy_ids(target, source, ids, should_stop)

        created: list[dict[str, int]] = []
        for update in getattr(response, "updates", []):
            message = getattr(update, "message", None)
            message_id = getattr(message, "id", None)
            if message_id:
                created.append({"message_id": int(message_id)})
        if not created:
            # Telegram accepted the forwarding request but returned a compact
            # update container. The accepted input count is still accurate.
            created = [{"message_id": 0} for _ in copyable]
        return {"result": created}

    async def _verify_peer(self, chat: str | int) -> dict[str, Any]:
        """Resolve one configured channel and return a concise diagnostic."""
        peer = await self.client.resolve_peer(self._chat(chat))
        return {
            "id": int(getattr(peer, "channel_id", 0) or getattr(peer, "chat_id", 0) or getattr(peer, "user_id", 0) or 0),
            "type": peer.__class__.__name__,
        }

    def verify_peer(self, chat: str | int) -> tuple[bool, dict[str, Any]]:
        ok, data = self._run(self._verify_peer(chat), timeout=90)
        return (True, data) if ok else (False, data)

    def copy_messages(
        self,
        target: str,
        source: str,
        message_ids: Iterable[int],
        should_stop: Callable[[], bool],
    ) -> tuple[bool, dict[str, Any]]:
        ids = [int(item) for item in message_ids]
        ok, data = self._run(self._copy_ids(target, source, ids, should_stop), timeout=300)
        if not ok:
            return False, data
        if data.get("stopped"):
            return False, {"description": "Copy stopped.", "stopped": True}
        return True, data

    def copy_message(
        self,
        target: str,
        source: str,
        message_id: int,
        should_stop: Callable[[], bool],
    ) -> tuple[bool, dict[str, Any]]:
        return self.copy_messages(target, source, [message_id], should_stop)

    @staticmethod
    def _chat(chat_id: str | int) -> str | int:
        return int(chat_id) if str(chat_id).lstrip("-").isdigit() else str(chat_id)

    async def _send(
        self,
        chat_id: str | int,
        text: str,
        reply_to_message_id: int | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> dict[str, Any]:
        msg = await self.client.send_message(
            chat_id=self._chat(chat_id),
            text=text,
            reply_to_message_id=reply_to_message_id,
            disable_web_page_preview=True,
            reply_markup=reply_markup,
        )
        return {"result": {"message_id": int(msg.id)}}

    def send_message(
        self,
        chat_id: str | int,
        text: str,
        reply_to_message_id: int | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        ok, data = self._run(self._send(chat_id, text, reply_to_message_id, reply_markup), timeout=90)
        return (True, data) if ok else (False, data)

    def send_status_message(
        self,
        chat_id: str | int,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        return self.send_message(chat_id, text, reply_markup=reply_markup)

    async def _edit(
        self,
        chat_id: str | int,
        message_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> dict[str, Any]:
        msg = await self.client.edit_message_text(
            chat_id=self._chat(chat_id),
            message_id=int(message_id),
            text=text,
            disable_web_page_preview=True,
            reply_markup=reply_markup,
        )
        return {"result": {"message_id": int(msg.id)}}

    def edit_status_message(
        self,
        chat_id: str | int,
        message_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        ok, data = self._run(self._edit(chat_id, message_id, text, reply_markup), timeout=90)
        return (True, data) if ok else (False, data)
