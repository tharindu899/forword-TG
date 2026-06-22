"""Confirmed, resumable one-channel message deletion worker.

Deletion is intentionally separate from copying. The owner must choose exactly
one configured channel and press the explicit confirmation button in the private
control panel before this worker can start. A custom delete range is optional;
the saved copy range is used as the bounded default.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

from .api import BotApi
from .copier import StatusCard, format_duration, is_fatal
from .store import Store

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeleteConfig:
    channel: str
    channel_label: str
    start_id: int
    end_id: int
    batch_size: int
    delay_seconds: float
    individual_delay_seconds: float
    owner_id: int
    status_every_ids: int
    status_every_seconds: int


class DeleteWorker:
    """Deletes an explicitly confirmed message-ID range from one channel."""

    def __init__(
        self,
        api: BotApi,
        store: Store,
        config: DeleteConfig,
        on_finished: Callable[[str], None],
    ) -> None:
        self.api = api
        self.store = store
        self.config = config
        self.on_finished = on_finished
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._run, name="channel-delete-worker", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def alive(self) -> bool:
        return self.thread.is_alive()

    def request_stop(self) -> None:
        self._stop.set()

    def stopped(self) -> bool:
        return self._stop.is_set()

    def _sleep(self, seconds: float) -> None:
        deadline = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < deadline and not self.stopped():
            time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))

    def _checkpoint(self, job: dict, next_id: int, *, deleted: int = 0, skipped: int = 0) -> dict:
        job["next_id"] = int(next_id)
        job["deleted"] = int(job.get("deleted", 0)) + int(deleted)
        job["skipped"] = int(job.get("skipped", 0)) + int(skipped)
        job["status"] = "running"
        job["operation"] = "delete"
        job["note"] = ""
        self.store.save_job(job)
        return job

    def _log_progress(self, job: dict, label: str) -> None:
        data = StatusCard.stats(job)
        LOGGER.info(
            "%s: %s/%s (%.1f%%) | deleted %s, skipped %s | %.2f IDs/s | ETA %s",
            label,
            f"{int(data['processed']):,}",
            f"{int(data['total']):,}",
            float(data["percent"]),
            f"{int(job.get('deleted', 0)):,}",
            f"{int(job.get('skipped', 0)):,}",
            float(data["speed"]),
            format_duration(data["eta"]),
        )

    def _finish(self, job: dict, status: str, note: str = "") -> None:
        job["status"] = status
        job["operation"] = "delete"
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
            "operation": "delete",
            "delete_channel": self.config.channel,
            "delete_role": self.config.channel_label,
            "status": "running",
            "start_id": self.config.start_id,
            "end_id": self.config.end_id,
            "next_id": max(self.config.start_id, int(job.get("next_id", self.config.start_id))),
            "started_at": float(job.get("started_at") or time.time()),
            "note": "",
            "error": "",
            "interrupted": False,
        })
        self.store.save_job(job)
        card.update(job, allow_create=False)

        current = int(job["next_id"])
        while current <= self.config.end_id and not self.stopped():
            last = min(self.config.end_id, current + self.config.batch_size - 1)
            batch = list(range(current, last + 1))
            ok, data = self.api.delete_messages(self.config.channel, batch, self.stopped)
            if ok:
                job = self._checkpoint(job, last + 1, deleted=len(batch))
                current = last + 1
                self._log_progress(job, f"IDs {batch[0]}-{batch[-1]}")
                card.maybe(job, self.config)
            else:
                detail = str(data.get("description", "Unknown Telegram error"))
                if data.get("stopped") or self.stopped():
                    break
                if is_fatal(detail):
                    LOGGER.error("Fatal Telegram delete error: %s", detail)
                    self._finish(job, "error", detail)
                    return

                LOGGER.warning("IDs %s-%s need individual delete checks: %s", batch[0], batch[-1], detail)
                for message_id in batch:
                    if self.stopped():
                        break
                    one_ok, one_data = self.api.delete_message(self.config.channel, message_id, self.stopped)
                    if one_ok:
                        job = self._checkpoint(job, message_id + 1, deleted=1)
                    else:
                        one_detail = str(one_data.get("description", "Unknown Telegram error"))
                        if one_data.get("stopped") or self.stopped():
                            break
                        if is_fatal(one_detail):
                            LOGGER.error("Fatal Telegram delete error: %s", one_detail)
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
            job["operation"] = "delete"
            job["note"] = "Deletion paused safely. Tap Start / Resume to continue from the saved next message ID."
            self.store.save_job(job)
            LOGGER.info("Deletion paused safely at message ID %s.", job["next_id"])
            card.update(job, allow_create=False)
            self.on_finished("paused")
            return

        self._log_progress(job, "Finished")
        self._finish(job, "completed", "All messages in the confirmed delete range were processed.")
        LOGGER.info("Deletion finished. Deleted %s, skipped %s.", job.get("deleted", 0), job.get("skipped", 0))
