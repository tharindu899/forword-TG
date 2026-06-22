"""Resumable old-post copier with one persistent owner-PM status card."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

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
    """Maintains exactly one editable progress/status message in the owner's PM."""

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

    @classmethod
    def text(cls, job: dict[str, Any], settings: dict[str, str], title: str | None = None, note: str = "") -> str:
        data = cls.stats(job)
        state = str(job.get("status", "idle")).upper()
        lines = [
            title or status_title(str(job.get("status", "idle"))),
            "",
            f"State: {state}",
            f"Source: {settings.get('source_channel') or 'not set'}",
            f"Target: {settings.get('target_channel') or 'not set'}",
            f"Range: {int(job.get('start_id', 1)):,}–{int(job.get('end_id', 0)):,}",
            f"Progress: {int(data['processed']):,}/{int(data['total']):,} ({float(data['percent']):.1f}%)",
            f"Copied: {int(job.get('copied', 0)):,}  |  Skipped: {int(job.get('skipped', 0)):,}",
            f"Next source ID: {int(job.get('next_id', 1)):,}",
            f"Speed: {float(data['speed']):.2f} IDs/s  |  ETA: {format_duration(data['eta'])}",
            f"Elapsed: {format_duration(float(data['elapsed']))}",
            f"Batch: {settings.get('batch_size', '25')}  |  Delay: {settings.get('delay_seconds', '0.60')}s",
            "",
            "This is the single live status message. It updates in place.",
        ]
        detail = note or str(job.get("note") or job.get("error") or "")
        if detail:
            lines.extend(["", f"Note: {detail}"])
        return "\n".join(lines)

    @staticmethod
    def _can_replace_card(description: str) -> bool:
        lowered = description.lower()
        return any(token in lowered for token in (
            "message to edit not found",
            "message can't be edited",
            "message identifier is not specified",
        ))

    def update(self, job: dict[str, Any], *, title: str | None = None, note: str = "") -> bool:
        if self.owner_id <= 0:
            return False
        chat_id = str(self.owner_id)
        text = self.text(job, self.store.settings(), title=title, note=note)

        stored_chat = str(job.get("status_chat_id") or "")
        message_id = job.get("status_message_id") if stored_chat == chat_id else None
        if message_id:
            ok, data = self.api.edit_status_message(chat_id, int(message_id), text)
            description = str(data.get("description", ""))
            if ok or "message is not modified" in description.lower():
                return True
            if data.get("network_error"):
                LOGGER.warning("Could not update owner status card: %s", description)
                return False
            if not self._can_replace_card(description):
                LOGGER.warning("Could not update owner status card: %s", description or "Unknown error")
                return False
            # The old card was deleted or cannot be edited. Replace it once.
            job["status_message_id"] = None
            job["status_chat_id"] = ""
            self.store.save_job(job)

        ok, data = self.api.send_status_message(chat_id, text)
        if ok:
            job["status_chat_id"] = chat_id
            job["status_message_id"] = data.get("result", {}).get("message_id")
            self.store.save_job(job)
            LOGGER.info("Owner status card created in private chat %s.", chat_id)
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
        self.update(job)
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
        StatusCard(self.api, self.store, self.config.owner_id).update(job)
        self.on_finished(status)

    def _run(self) -> None:
        job = self.store.job()
        card = StatusCard(self.api, self.store, self.config.owner_id)
        job.update({
            "status": "running",
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
            job["note"] = "Use /resume to continue from the saved next source ID."
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
        self._worker: CopyWorker | None = None

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
            raise ValueError("Claim the bot first with /claim, or set OWNER_ID in Render.")
        if not source or not target:
            raise ValueError("Set source and target first: /setsource … then /settarget …")
        if source == target:
            raise ValueError("Source and target must be different channels.")
        if require_range and (start_id < 1 or end_id < start_id):
            raise ValueError("Set a valid range first: /setrange START_ID END_ID")
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

    def publish_status(self) -> bool:
        return self.card().update(self.store.job())

    def status_text(self) -> str:
        return StatusCard.text(self.store.job(), self.store.settings())

    def start(self, restart: bool = False) -> tuple[bool, str]:
        with self._lock:
            if self.worker_running():
                return False, "A copy job is already running. Check the live status card or use /pause."
            try:
                config = self.current_config()
            except ValueError as exc:
                return False, str(exc)

            job = self.store.job()
            same_range = int(job["start_id"]) == config.start_id and int(job["end_id"]) == config.end_id
            if job["status"] == "completed" and same_range and not restart:
                return False, "This range is complete. Use /restart to copy it again, or /setrange for another range."
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

            self.card().update(job, title="📦 Channel copy starting")
            self._worker = CopyWorker(self.api, self.store, config, self._on_finished)
            self._worker.start()
            return True, "Copy started. The live card in this private chat will update in place."

    def pause(self) -> tuple[bool, str]:
        with self._lock:
            if not self.worker_running() or not self._worker:
                job = self.store.job()
                if job["status"] == "running":
                    job["status"] = "paused"
                    job["note"] = "No active worker remains. Use /resume to continue."
                    self.store.save_job(job)
                self.publish_status()
                return False, "No active copy thread is running."
            self._worker.request_stop()
            job = self.store.job()
            job["status"] = "stopping"
            job["note"] = "Pause requested. Waiting for the current Telegram request to finish safely."
            self.store.save_job(job)
            self.publish_status()
            return True, "Pause requested. The status card will change to PAUSED when safe."

    def test_copy(self, message_id: int) -> tuple[bool, str]:
        with self._lock:
            if self.worker_running():
                return False, "Pause the active job before testing another message."
            try:
                config = self.current_config(require_range=False)
            except ValueError as exc:
                return False, str(exc)
        ok, data = self.api.copy_message(config.target, config.source, message_id, lambda: False)
        if ok:
            target_id = data.get("result", {}).get("message_id", "?")
            return True, f"✅ Test passed. Source {message_id:,} copied as target message {target_id}."
        return False, f"❌ Test failed: {data.get('description', 'Unknown Telegram error')}"

    def _on_finished(self, _status: str) -> None:
        with self._lock:
            self._worker = None

    def request_shutdown_pause(self) -> None:
        with self._lock:
            if self._worker and self._worker.alive():
                self._worker.request_stop()
