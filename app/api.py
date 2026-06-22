"""Small Telegram Bot API client using only Python's standard library."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

LOGGER = logging.getLogger(__name__)


class TelegramApiError(RuntimeError):
    pass


class BotApi:
    def __init__(self, token: str, timeout: int = 45, network_retry_seconds: int = 8) -> None:
        self.base_url = f"https://api.telegram.org/bot{token}/"
        self.timeout = timeout
        self.network_retry_seconds = network_retry_seconds

    def call(self, method: str, payload: dict[str, Any] | None = None) -> tuple[bool, dict[str, Any]]:
        request = urllib.request.Request(
            self.base_url + method,
            data=json.dumps(payload or {}, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "TelegramChannelCopierRender/2.0"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return False, {"description": f"Network error: {exc}", "network_error": True}

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return False, {"description": f"Invalid Telegram response: {body[:300]}"}
        return bool(data.get("ok")), data

    def call_retry(
        self,
        method: str,
        payload: dict[str, Any] | None = None,
        stop_requested: Callable[[], bool] | None = None,
        log_network_errors: bool = True,
    ) -> tuple[bool, dict[str, Any]]:
        is_stopped = stop_requested or (lambda: False)
        while not is_stopped():
            ok, data = self.call(method, payload)
            if ok:
                return True, data

            retry_after = data.get("parameters", {}).get("retry_after")
            if retry_after:
                wait = max(1, int(retry_after)) + 1
                LOGGER.warning("Telegram flood limit during %s; waiting %ss.", method, wait)
                self._sleep_interruptible(wait, is_stopped)
                continue

            if data.get("network_error"):
                if log_network_errors:
                    LOGGER.warning("%s. Retrying %s in %ss.", data.get("description", "Network error"), method, self.network_retry_seconds)
                self._sleep_interruptible(self.network_retry_seconds, is_stopped)
                continue

            return False, data
        return False, {"description": "Stopped", "stopped": True}

    @staticmethod
    def _sleep_interruptible(seconds: float, stop_requested: Callable[[], bool]) -> None:
        deadline = time.monotonic() + max(0, seconds)
        while time.monotonic() < deadline and not stop_requested():
            time.sleep(min(0.5, max(0, deadline - time.monotonic())))

    def get_me(self) -> dict[str, Any]:
        ok, data = self.call_retry("getMe")
        if not ok:
            raise TelegramApiError(data.get("description", "getMe failed"))
        return data["result"]

    def set_commands(self, commands: list[dict[str, str]]) -> None:
        """Register the command menu automatically whenever the worker starts.

        Telegram keeps commands by scope. We update both the default scope and
        the private-chat scope so the menu appears reliably in the owner's bot PM
        without any BotFather command setup.
        """
        scopes: list[dict[str, Any] | None] = [
            None,
            {"type": "all_private_chats"},
        ]
        successes = 0
        for scope in scopes:
            payload: dict[str, Any] = {"commands": commands}
            if scope is not None:
                payload["scope"] = scope
            ok, data = self.call_retry("setMyCommands", payload)
            if ok:
                successes += 1
                continue
            scope_name = scope["type"] if scope else "default"
            LOGGER.warning(
                "Could not register %s bot command menu: %s",
                scope_name,
                data.get("description", "Unknown error"),
            )
        if successes:
            LOGGER.info(
                "Registered %d command%s automatically in the bot menu (%d scope%s).",
                len(commands),
                "" if len(commands) == 1 else "s",
                successes,
                "" if successes == 1 else "s",
            )

    @staticmethod
    def _message_payload(chat_id: str | int, text: str) -> dict[str, Any]:
        return {
            "chat_id": chat_id,
            "text": text,
            "disable_notification": True,
            "disable_web_page_preview": True,
        }

    def send_message(
        self,
        chat_id: str | int,
        text: str,
        *,
        reply_to_message_id: int | None = None,
        disable_notification: bool = True,
    ) -> tuple[bool, dict[str, Any]]:
        payload = self._message_payload(chat_id, text)
        payload["disable_notification"] = disable_notification
        if reply_to_message_id:
            payload["reply_parameters"] = {"message_id": reply_to_message_id, "allow_sending_without_reply": True}
        return self.call_retry("sendMessage", payload)

    def send_status_message(self, chat_id: str | int, text: str) -> tuple[bool, dict[str, Any]]:
        """One-shot status send: never block copying forever on a status outage."""
        return self.call("sendMessage", self._message_payload(chat_id, text))

    def edit_status_message(self, chat_id: str | int, message_id: int, text: str) -> tuple[bool, dict[str, Any]]:
        """One-shot status edit so one temporary network error does not create spam."""
        return self.call(
            "editMessageText",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "disable_web_page_preview": True,
            },
        )

    def copy_messages(self, target: str, source: str, message_ids: list[int], stop_requested: Callable[[], bool]) -> tuple[bool, dict[str, Any]]:
        return self.call_retry(
            "copyMessages",
            {"chat_id": target, "from_chat_id": source, "message_ids": message_ids, "disable_notification": True},
            stop_requested=stop_requested,
        )

    def copy_message(self, target: str, source: str, message_id: int, stop_requested: Callable[[], bool]) -> tuple[bool, dict[str, Any]]:
        return self.call_retry(
            "copyMessage",
            {"chat_id": target, "from_chat_id": source, "message_id": message_id, "disable_notification": True},
            stop_requested=stop_requested,
        )

    def get_updates(self, offset: int | None, timeout: int) -> tuple[bool, dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        return self.call_retry("getUpdates", payload, log_network_errors=False)
