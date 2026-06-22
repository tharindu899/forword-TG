"""Resumable old-post copier with one persistent owner-PM status card."""

from __future__ import annotations

import logging
import threading
import time
from html import escape
from dataclasses import dataclass
from typing import Any

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .api import BotApi
from .store import Store

LOGGER = logging.getLogger(__name__)


def format_duration(seconds: float | None) -> str:
    if seconds is None or seconds < 0 or seconds == float("inf"):
        return "calculating…"
    value = int(seconds)
    hours, rest = divmod(value, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def as_int(value: str, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def as_float(value: str, default: float) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def is_fatal(description: str) -> bool:
    lowered = description.lower()
    return any(token in lowered for token in (
        "not enough rights",
        "chat not found",
        "bot was kicked",
        "bot is not a member",
        "forbidden",
        "unauthorized",
        "have no rights",
        "chat_admin_required",
        "admin required",
        "message_delete_forbidden",
        "delete messages",
    ))


def status_title(state: str) -> str:
    titles = {
        "running": "📦 Channel copy running",
        "stopping": "⏳ Channel copy pausing",
        "paused": "⏸ Channel copy paused",
        "completed": "✅ Channel copy complete",
        "error": "❌ Channel copy stopped",
        "idle": "🧭 Channel copier ready",
    }
    return titles.get(state.lower(), "🧭 Channel copier status")


@dataclass(frozen=True)
class CopyConfig:
    source: str
    target: str
    start_id: int
    end_id: int
    batch_size: int
    delay_seconds: float
    individual_delay_seconds: float
    owner_id: int
    status_every_ids: int
    status_every_seconds: int


class StatusCard:
    """Maintains one compact editable owner-PM control and progress card."""

    def __init__(self, api: BotApi, store: Store, owner_id: int) -> None:
        self.api = api
        self.store = store
        self.owner_id = owner_id
        self.last_processed = -1
        self.last_sent_at = 0.0

    @staticmethod
    def stats(job: dict[str, Any]) -> dict[str, float | int | None]:
        start = int(job.get("start_id", 1))
        end = int(job.get("end_id", 0))
        total = max(0, end - start + 1)
        next_id = int(job.get("next_id", start))
        processed = min(total, max(0, next_id - start))
        started_at = float(job.get("started_at") or 0)
        elapsed = max(0.0, time.time() - started_at) if started_at else 0.0
        speed = processed / elapsed if elapsed > 0 else 0.0
        remaining = max(0, total - processed)
        eta = remaining / speed if speed > 0 else None
        percent = (processed / total * 100) if total else 0.0
        return {
            "total": total,
            "processed": processed,
            "remaining": remaining,
            "percent": percent,
            "elapsed": elapsed,
            "speed": speed,
            "eta": eta,
        }

    @staticmethod
    def progress_bar(percent: float, width: int = 12) -> str:
        """Render a precise compact bar.

        ■ marks fully completed cells, □ marks remaining cells, and one
        intermediate cell (▤ ▥ ▦ ▧ ▨ or ▩) represents the fractional part
        between the two. This keeps the visual fill accurate without rounding
        the bar up too early.
        """
        partial_cells = ("▤", "▥", "▦", "▧", "▨", "▩")
        safe_width = max(1, int(width))
        clipped = max(0.0, min(100.0, float(percent)))
        units = (clipped / 100.0) * safe_width
        full = min(safe_width, int(units))

        # 100% must contain completed cells only.
        if full >= safe_width:
            return "■" * safe_width

        fraction = units - full
        partial = ""
        if fraction > 1e-9:
            # Choose one of six visible in-between states. A tiny fraction
            # uses ▤; a near-full fractional cell uses ▩.
            index = min(len(partial_cells) - 1, max(0, int(fraction * len(partial_cells))))
            partial = partial_cells[index]

        empty = safe_width - full - (1 if partial else 0)
        return "■" * full + partial + "□" * empty

    @staticmethod
    def keyboard(job: dict[str, Any]) -> InlineKeyboardMarkup:
        """Use compact two-column controls; odd final actions are full width."""
        state = str(job.get("status", "idle")).lower()
        operation = str(job.get("operation", "copy")).lower()
        if state in {"running", "stopping"}:
            return InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("⏸ Pause", callback_data="pause"),
                    InlineKeyboardButton("🔄 Refresh", callback_data="status"),
                ],
            ])

        if operation == "delete" and state == "paused":
            return InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("▶️ Resume Delete", callback_data="start"),
                    InlineKeyboardButton("⚙️ Setup", callback_data="setup"),
                ],
                [InlineKeyboardButton("🔄 Refresh", callback_data="status")],
            ])

        if operation == "delete" and state in {"completed", "error"}:
            return InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🗑 Delete Messages", callback_data="delete:choose"),
                    InlineKeyboardButton("⚙️ Setup", callback_data="setup"),
                ],
                [InlineKeyboardButton("🔄 Refresh", callback_data="status")],
            ])

        start_text = "▶️ Resume" if state == "paused" else "▶️ Start"
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚙️ Setup", callback_data="setup"),
                InlineKeyboardButton(start_text, callback_data="start"),
            ],
            [
                InlineKeyboardButton("🧪 Test", callback_data="input:test"),
                InlineKeyboardButton("🗑 Delete", callback_data="delete:choose"),
            ],
            [InlineKeyboardButton("🔄 Refresh", callback_data="status")],
        ])

    @staticmethod
    def _short(value: str, limit: int = 24) -> str:
        value = value or "not set"
        return value if len(value) <= limit else value[: limit - 1] + "…"

    @classmethod
    def text(cls, job: dict[str, Any], settings: dict[str, str], title: str | None = None, note: str = "") -> str:
        data = cls.stats(job)
        state = str(job.get("status", "idle")).lower()
        operation = str(job.get("operation", "copy")).lower()
        is_delete = operation == "delete"
        state_badges = {
            "running": ("🟢", "RUNNING"),
            "stopping": ("🟠", "PAUSING"),
            "paused": ("🟡", "PAUSED"),
            "completed": ("✅", "COMPLETE"),
            "error": ("🔴", "ERROR"),
            "idle": ("🔵", "READY"),
        }
        icon, label = state_badges.get(state, ("🔵", state.upper() or "READY"))
        processed = int(data["processed"])
        total = int(data["total"])
        percent = float(data["percent"])
        next_id = int(job.get("next_id", 1))
        bar = cls.progress_bar(percent)
        source = escape(cls._short(str(settings.get("source_channel") or "not set")))
        target = escape(cls._short(str(settings.get("target_channel") or "not set")))
        speed_name = "Safe" if int(settings.get("batch_size") or 25) <= 12 else ("Fast" if int(settings.get("batch_size") or 25) >= 40 else "Balanced")

        if is_delete:
            selected_channel = escape(cls._short(str(job.get("delete_channel") or "not set")))
            selected_role = escape(str(job.get("delete_role") or "channel").title())
            rows = [
                f"{icon} <b>{label}</b>  •  <b>DELETE</b>  •  <code>{percent:.1f}%</code>",
                f"<code>{bar}</code>  <b>{processed:,} / {total:,}</b>",
                f"🗑 <b>{int(job.get('deleted', 0)):,}</b> deleted  •  ⏭ <b>{int(job.get('skipped', 0)):,}</b> skipped",
                f"📥 Next <code>{next_id:,}</code>  •  ⚡ <code>{float(data['speed']):.2f}/s</code>",
                f"⏳ <code>{format_duration(data['eta'])}</code>  •  🕒 <code>{format_duration(float(data['elapsed']))}</code>",
                f"🎯 <code>{int(job.get('start_id', 1)):,} → {int(job.get('end_id', 0)):,}</code>  •  ⚡ <code>{speed_name}</code>",
                f"🧹 <b>{selected_role}</b>  <code>{selected_channel}</code>",
            ]
            heading = "CHANNEL DELETE"
        else:
            rows = [
                f"{icon} <b>{label}</b>  •  <code>{percent:.1f}%</code>",
                f"<code>{bar}</code>  <b>{processed:,} / {total:,}</b>",
                f"✅ <b>{int(job.get('copied', 0)):,}</b> copied  •  ⏭ <b>{int(job.get('skipped', 0)):,}</b> skipped",
                f"📥 Next <code>{next_id:,}</code>  •  ⚡ <code>{float(data['speed']):.2f}/s</code>",
                f"⏳ <code>{format_duration(data['eta'])}</code>  •  🕒 <code>{format_duration(float(data['elapsed']))}</code>",
                f"🎯 <code>{int(job.get('start_id', 1)):,} → {int(job.get('end_id', 0)):,}</code>  •  ⚡ <code>{speed_name}</code>",
                f"📥 <code>{source}</code>",
                f"📤 <code>{target}</code>",
            ]
            heading = "CHANNEL COPIER"
        detail = note or str(job.get("note") or job.get("error") or "")
        content = list(rows)
        if detail:
            content.append(f"💬 {escape(detail)}")
        if not content:
            content.append("ℹ️ No status details available")

        lines = [f"▤ <b>{heading}</b>"]
        for index, row in enumerate(content):
            branch = "└" if index == len(content) - 1 else "├"
            lines.append(f"{branch} {row}")
        return "\n".join(lines)

    @staticmethod
    def _can_replace_card(description: str) -> bool:
        lowered = description.lower()
        return any(token in lowered for token in (
            "message to edit not found",
            "message can't be edited",
            "message identifier is not specified",
        ))

    @staticmethod
    def _not_modified(description: str) -> bool:
        lowered = description.lower()
        return "message_not_modified" in lowered or "message is not modified" in lowered or "not modified" in lowered

    def update(
        self,
        job: dict[str, Any],
        *,
        title: str | None = None,
        note: str = "",
        allow_create: bool = True,
    ) -> bool:
        """Edit the one known owner card.

        Background copy updates call this with ``allow_create=False``. That
        prevents a restart, a stale card ID, or a transient edit failure from
        creating a stream of new private messages. A fresh card is created
        only when the owner explicitly uses /start or /status.
        """
        if self.owner_id <= 0:
            return False
        chat_id = str(self.owner_id)
        text = self.text(job, self.store.settings(), title=title, note=note)
        markup = self.keyboard(job)

        stored_chat = str(job.get("status_chat_id") or "")
        message_id = job.get("status_message_id") if stored_chat == chat_id else None
        if message_id:
            ok, data = self.api.edit_status_message(chat_id, int(message_id), text, reply_markup=markup)
            description = str(data.get("description", ""))
            if ok or self._not_modified(description):
                return True
            if data.get("network_error"):
                LOGGER.warning("Could not update owner status card: %s", description)
                return False
            if not self._can_replace_card(description):
                LOGGER.warning("Could not update owner status card: %s", description or "Unknown error")
                return False
            job["status_message_id"] = None
            job["status_chat_id"] = ""
            self.store.save_job(job)

        if not allow_create:
            return False

        ok, data = self.api.send_status_message(chat_id, text, reply_markup=markup)
        if ok:
            job["status_chat_id"] = chat_id
            job["status_message_id"] = data.get("result", {}).get("message_id")
            self.store.save_job(job)
            LOGGER.info("Owner compact control card created in private chat %s.", chat_id)
            return True

        description = str(data.get("description", "Unknown error"))
        LOGGER.warning("Could not create owner status card: %s", description)
        return False

    def maybe(self, job: dict[str, Any], config: CopyConfig, force: bool = False) -> None:
        now = time.time()
        processed = int(self.stats(job)["processed"])
        ids_due = processed - self.last_processed >= config.status_every_ids
        time_due = now - self.last_sent_at >= config.status_every_seconds
        if not force and not (ids_due or time_due):
            return
        self.update(job, allow_create=False)
        self.last_processed = processed
        self.last_sent_at = now


class CopyWorker:
    def __init__(self, api: BotApi, store: Store, config: CopyConfig, on_finished: callable) -> None:
        self.api = api
        self.store = store
        self.config = config
        self.on_finished = on_finished
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._run, name="channel-copy-worker", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def alive(self) -> bool:
        return self.thread.is_alive()

    def request_stop(self) -> None:
        self._stop.set()

    def stopped(self) -> bool:
        return self._stop.is_set()

    def _sleep(self, seconds: float) -> None:
        deadline = time.monotonic() + max(0, seconds)
        while time.monotonic() < deadline and not self.stopped():
            time.sleep(min(0.25, max(0, deadline - time.monotonic())))

    def _checkpoint(self, job: dict[str, Any], next_id: int, *, copied: int = 0, skipped: int = 0) -> dict[str, Any]:
        job["next_id"] = next_id
        job["copied"] = int(job.get("copied", 0)) + copied
        job["skipped"] = int(job.get("skipped", 0)) + skipped
        job["status"] = "running"
        job["operation"] = "copy"
        job["note"] = ""
        self.store.save_job(job)
        return job

    def _log_progress(self, job: dict[str, Any], label: str) -> None:
        data = StatusCard.stats(job)
        LOGGER.info(
            "%s: %s/%s (%.1f%%) | copied %s, skipped %s | %.2f IDs/s | ETA %s",
            label,
            f"{int(data['processed']):,}",
            f"{int(data['total']):,}",
            float(data["percent"]),
            f"{int(job.get('copied', 0)):,}",
            f"{int(job.get('skipped', 0)):,}",
            float(data["speed"]),
            format_duration(data["eta"]),
        )

    def _finish(self, job: dict[str, Any], status: str, note: str = "") -> None:
        job["status"] = status
        job["interrupted"] = False
        job["note"] = note
        if status != "error":
            job["error"] = ""
        elif note:
            job["error"] = note
        self.store.save_job(job)
        StatusCard(self.api, self.store, self.config.owner_id).update(job, allow_create=False)
        self.on_finished(status)

    def _run(self) -> None:
        job = self.store.job()
        card = StatusCard(self.api, self.store, self.config.owner_id)
        job.update({
            "status": "running",
            "operation": "copy",
            "deleted": 0,
            "delete_channel": "",
            "delete_role": "",
            "start_id": self.config.start_id,
            "end_id": self.config.end_id,
            "error": "",
            "note": "",
            "interrupted": False,
        })
        if not float(job.get("started_at") or 0):
            job["started_at"] = time.time()
        if int(job.get("next_id", self.config.start_id)) < self.config.start_id:
            job["next_id"] = self.config.start_id
        self.store.save_job(job)

        current = max(self.config.start_id, int(job["next_id"]))
        if current > self.config.end_id:
            self._finish(job, "completed", "This range was already completed.")
            return

        LOGGER.info(
            "Copying %s source IDs from %s to %s (%s-%s).",
            f"{self.config.end_id - current + 1:,}",
            self.config.source,
            self.config.target,
            current,
            self.config.end_id,
        )
        card.maybe(job, self.config, force=True)
        self._log_progress(job, "Starting")

        while current <= self.config.end_id and not self.stopped():
            last = min(self.config.end_id, current + self.config.batch_size - 1)
            batch = list(range(current, last + 1))
            ok, data = self.api.copy_messages(self.config.target, self.config.source, batch, self.stopped)

            if ok:
                copied = len(data.get("result") or [])
                job = self._checkpoint(job, last + 1, copied=copied, skipped=len(batch) - copied)
                current = last + 1
                self._log_progress(job, f"IDs {batch[0]}-{batch[-1]}")
                card.maybe(job, self.config)
            else:
                detail = str(data.get("description", "Unknown Telegram error"))
                if data.get("stopped") or self.stopped():
                    break
                if is_fatal(detail):
                    LOGGER.error("Fatal Telegram error: %s", detail)
                    self._finish(job, "error", detail)
                    return

                LOGGER.warning("IDs %s-%s need individual checks: %s", batch[0], batch[-1], detail)
                for message_id in batch:
                    if self.stopped():
                        break
                    one_ok, one_data = self.api.copy_message(
                        self.config.target,
                        self.config.source,
                        message_id,
                        self.stopped,
                    )
                    if one_ok:
                        job = self._checkpoint(job, message_id + 1, copied=1)
                    else:
                        one_detail = str(one_data.get("description", "Unknown Telegram error"))
                        if one_data.get("stopped") or self.stopped():
                            break
                        if is_fatal(one_detail):
                            LOGGER.error("Fatal Telegram error: %s", one_detail)
                            self._finish(job, "error", one_detail)
                            return
                        job = self._checkpoint(job, message_id + 1, skipped=1)
                    current = message_id + 1
                    card.maybe(job, self.config)
                    self._sleep(self.config.individual_delay_seconds)
                self._log_progress(job, f"IDs {batch[0]}-{min(last, current - 1)}")

            self._sleep(self.config.delay_seconds)

        if self.stopped():
            job["status"] = "paused"
            job["note"] = "Tap Start / Resume to continue from the saved next source ID."
            self.store.save_job(job)
            LOGGER.info("Copy paused safely at source ID %s.", job["next_id"])
            card.update(job)
            self.on_finished("paused")
            return

        self._log_progress(job, "Finished")
        self._finish(job, "completed", "All IDs in the configured range were processed.")
        LOGGER.info("Finished. Copied %s, skipped %s.", job["copied"], job["skipped"])


class CopyController:
    def __init__(self, api: BotApi, store: Store, owner_id: int) -> None:
        self.api = api
        self.store = store
        self.owner_id = owner_id
        self._lock = threading.RLock()
        self._worker: Any | None = None

    def set_owner_id(self, owner_id: int) -> None:
        with self._lock:
            self.owner_id = owner_id

    def worker_running(self) -> bool:
        return bool(self._worker and self._worker.alive())

    def card(self) -> StatusCard:
        return StatusCard(self.api, self.store, self.owner_id)

    def current_config(self, require_range: bool = True) -> CopyConfig:
        settings = self.store.settings()
        source = settings["source_channel"].strip()
        target = settings["target_channel"].strip()
        start_id = as_int(settings["range_start"], 1)
        end_id = as_int(settings["range_end"], 0)
        if self.owner_id <= 0:
            raise ValueError("Set OWNER_ID in Hugging Face Space Secrets, then restart the Space.")
        if not source or not target:
            raise ValueError("Open /start → Setup and set the source and target channels first.")
        if source == target:
            raise ValueError("Source and target must be different channels.")
        if require_range and (start_id < 1 or end_id < start_id):
            raise ValueError("Open /start → Setup and set a valid message range first.")
        if not require_range and (start_id < 1 or end_id < start_id):
            start_id, end_id = 1, 1

        return CopyConfig(
            source=source,
            target=target,
            start_id=start_id,
            end_id=end_id,
            batch_size=max(1, min(as_int(settings["batch_size"], 25), 100)),
            delay_seconds=max(0.0, as_float(settings["delay_seconds"], 0.6)),
            individual_delay_seconds=max(0.0, as_float(settings["individual_delay_seconds"], 0.12)),
            owner_id=self.owner_id,
            status_every_ids=max(1, as_int(settings["status_every_ids"], 25)),
            status_every_seconds=max(5, as_int(settings["status_every_seconds"], 20)),
        )

    def adopt_status_card(self, chat_id: int, message_id: int) -> bool:
        """Mark the currently pressed owner panel as the one active card.

        This is what guarantees that button actions, setup replies, progress,
        pause, errors, and completion all edit the same message instead of
        creating a second card.
        """
        with self._lock:
            if self.owner_id <= 0 or int(chat_id) != int(self.owner_id) or int(message_id) <= 0:
                return False
            job = self.store.job()
            if str(job.get("status_chat_id") or "") == str(chat_id) and int(job.get("status_message_id") or 0) == int(message_id):
                return True
            job["status_chat_id"] = str(chat_id)
            job["status_message_id"] = int(message_id)
            self.store.save_job(job)
            return True

    def publish_status(self, allow_create: bool = True) -> bool:
        return self.card().update(self.store.job(), allow_create=allow_create)

    def status_text(self) -> str:
        return StatusCard.text(self.store.job(), self.store.settings())

    def _delete_config(self, role: str, start_id: int, end_id: int, *, resume: bool = False) -> Any:
        """Build a validated delete worker configuration for exactly one channel."""
        from .deleter import DeleteConfig

        selected_role = role.strip().lower()
        if selected_role not in {"source", "target"}:
            raise ValueError("Choose Source or Target before deleting messages.")
        if self.owner_id <= 0:
            raise ValueError("Set OWNER_ID in Hugging Face Space Secrets, then restart the Space.")
        if int(start_id) < 1 or int(end_id) < int(start_id):
            raise ValueError("Set a valid delete range first.")
        settings = self.store.settings()
        channel = str(settings.get(f"{selected_role}_channel", "")).strip()
        if not channel:
            raise ValueError(f"Set the {selected_role} channel before deleting messages.")
        return DeleteConfig(
            channel=channel,
            channel_label=selected_role,
            start_id=int(start_id),
            end_id=int(end_id),
            batch_size=max(1, min(as_int(settings["batch_size"], 25), 100)),
            delay_seconds=max(0.0, as_float(settings["delay_seconds"], 0.6)),
            individual_delay_seconds=max(0.0, as_float(settings["individual_delay_seconds"], 0.12)),
            owner_id=self.owner_id,
            status_every_ids=max(1, as_int(settings["status_every_ids"], 25)),
            status_every_seconds=max(5, as_int(settings["status_every_seconds"], 20)),
        )

    def start_delete(self, role: str, start_id: int, end_id: int) -> tuple[bool, str]:
        """Start a deletion only after the UI confirmation step has completed."""
        from .deleter import DeleteWorker

        with self._lock:
            if self.worker_running():
                return False, "A task is already running. Pause it before starting deletion."
            try:
                config = self._delete_config(role, start_id, end_id)
            except ValueError as exc:
                return False, str(exc)

            peer_ok, peer_data = self.api.verify_peer(config.channel)
            if not peer_ok:
                return False, self._peer_hint(config.channel_label.title(), str(peer_data.get("description", "Unknown Telegram error")))

            job = self.store.reset_job(config.start_id, config.end_id)
            job.update({
                "operation": "delete",
                "delete_channel": config.channel,
                "delete_role": config.channel_label,
                "status": "running",
                "note": "Confirmed deletion is starting. The same private card will update in place.",
                "error": "",
                "interrupted": False,
            })
            self.store.save_job(job)
            self.card().update(job, allow_create=False)
            self._worker = DeleteWorker(self.api, self.store, config, self._on_finished)
            self._worker.start()
            return True, "Deletion started. The same private card will update in place."

    def resume_delete(self) -> tuple[bool, str]:
        from .deleter import DeleteWorker

        with self._lock:
            if self.worker_running():
                return False, "A task is already running. Use Pause first."
            job = self.store.job()
            if str(job.get("operation", "copy")) != "delete":
                return False, "No paused delete task is available."
            role = str(job.get("delete_role") or "").strip().lower()
            try:
                config = self._delete_config(role, int(job.get("start_id", 1)), int(job.get("end_id", 0)), resume=True)
            except ValueError as exc:
                return False, str(exc)
            if str(job.get("delete_channel") or "") != config.channel:
                return False, "Delete channel was changed. Re-open Delete Messages and confirm a new range."

            job["status"] = "running"
            job["operation"] = "delete"
            job["note"] = ""
            job["error"] = ""
            job["interrupted"] = False
            self.store.save_job(job)
            self.card().update(job, allow_create=False)
            self._worker = DeleteWorker(self.api, self.store, config, self._on_finished)
            self._worker.start()
            return True, "Deletion resumed from the saved next message ID."

    def start(self, restart: bool = False) -> tuple[bool, str]:
        with self._lock:
            if self.worker_running():
                return False, "A copy job is already running. Use the Pause button on the live status card."
            existing = self.store.job()
            if str(existing.get("operation", "copy")) == "delete" and str(existing.get("status", "")) == "paused":
                # The main Start / Resume button must continue a paused delete
                # task instead of unexpectedly switching back to copy mode.
                return self.resume_delete()
            try:
                config = self.current_config()
            except ValueError as exc:
                return False, str(exc)

            job = existing
            same_range = int(job["start_id"]) == config.start_id and int(job["end_id"]) == config.end_id
            if job["status"] == "completed" and same_range and not restart:
                return False, "This range is complete. Open Setup to choose a new range."
            if restart or not same_range or job["status"] in {"idle", "completed", "error"}:
                job = self.store.reset_job(config.start_id, config.end_id)
            elif job["status"] == "paused":
                job["status"] = "running"
                job["error"] = ""
                job["note"] = ""
                job["interrupted"] = False
                self.store.save_job(job)
            else:
                job["status"] = "running"
                job["note"] = ""
                self.store.save_job(job)

            self.card().update(job, title="📦 Channel copy starting", allow_create=False)
            self._worker = CopyWorker(self.api, self.store, config, self._on_finished)
            self._worker.start()
            return True, "Copy started. The live card in this private chat will update in place."

    def pause(self) -> tuple[bool, str]:
        with self._lock:
            if not self.worker_running() or not self._worker:
                job = self.store.job()
                if job["status"] == "running":
                    job["status"] = "paused"
                    job["note"] = "No active worker remains. Tap Start / Resume to continue."
                    self.store.save_job(job)
                self.publish_status(allow_create=False)
                return False, "No active task is running."
            self._worker.request_stop()
            job = self.store.job()
            job["status"] = "stopping"
            job["note"] = "Pause requested. Waiting for the current Telegram request to finish safely."
            self.store.save_job(job)
            self.publish_status(allow_create=False)
            return True, "Pause requested. The status card will change to PAUSED when safe."

    @staticmethod
    def _peer_hint(label: str, detail: str) -> str:
        lowered = detail.lower()
        if "peer_id_invalid" in lowered or "peer id" in lowered or "not known yet" in lowered:
            return (
                f"❌ {label} channel cannot be resolved. Add the bot as an administrator in that channel, "
                "then restart the Space and test again."
            )
        if "channel_private" in lowered or "not a member" in lowered or "forbidden" in lowered:
            return f"❌ {label} channel is not accessible to the bot. Add the bot as an administrator, then retry."
        return f"❌ {label} check failed: {detail}"

    def test_copy(self, message_id: int) -> tuple[bool, str]:
        with self._lock:
            if self.worker_running():
                return False, "Pause the active job before testing another message."
            try:
                config = self.current_config(require_range=False)
            except ValueError as exc:
                return False, str(exc)

        # Test both configured peers first, so an invalid source/target is shown clearly.
        source_ok, source_data = self.api.verify_peer(config.source)
        if not source_ok:
            return False, self._peer_hint("Source", str(source_data.get("description", "Unknown Telegram error")))

        target_ok, target_data = self.api.verify_peer(config.target)
        if not target_ok:
            return False, self._peer_hint("Target", str(target_data.get("description", "Unknown Telegram error")))

        ok, data = self.api.copy_message(config.target, config.source, message_id, lambda: False)
        if ok:
            result = data.get("result") or []
            first = result[0] if isinstance(result, list) and result else {}
            target_id = first.get("message_id", "?") if isinstance(first, dict) else "?"
            suffix = f" as target message {target_id}" if target_id not in {0, "?"} else ""
            return True, f"✅ Test passed. Source {message_id:,} was copied{suffix}."
        detail = str(data.get("description", "Unknown Telegram error"))
        if "chat_forwards_restricted" in detail.lower() or "forwards restricted" in detail.lower():
            return False, "❌ Test file is protected by Telegram content protection and cannot be copied."
        return False, f"❌ Test failed: {detail}"

    def _on_finished(self, _status: str) -> None:
        with self._lock:
            self._worker = None

    def request_shutdown_pause(self) -> None:
        with self._lock:
            if self._worker and self._worker.alive():
                self._worker.request_stop()
