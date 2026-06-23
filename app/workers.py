"""Per-user copy/delete workers and same-card progress updates."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from .api import BotApi
from .store import Store
from .ui import format_duration, job_stats, main_keyboard, panel_text

LOGGER = logging.getLogger(__name__)


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
        "not enough rights", "chat not found", "bot was kicked", "bot is not a member",
        "forbidden", "unauthorized", "have no rights", "admin required", "peer_id_invalid",
        "peer id being used is invalid", "not known yet", "access hash", "message_delete_forbidden",
    ))


@dataclass(frozen=True)
class JobConfig:
    user_id: int
    source: str
    target: str
    start_id: int
    end_id: int
    batch_size: int
    delay_seconds: float
    individual_delay_seconds: float
    status_every_ids: int
    status_every_seconds: int


@dataclass(frozen=True)
class DeleteConfig:
    user_id: int
    channel: str
    role: str
    start_id: int
    end_id: int
    batch_size: int
    delay_seconds: float
    individual_delay_seconds: float
    status_every_ids: int
    status_every_seconds: int


class StatusCard:
    """Edits only the matching user's single stored panel; never sends progress spam."""

    def __init__(self, api: BotApi, store: Store, user_id: int) -> None:
        self.api = api
        self.store = store
        self.user_id = int(user_id)
        self.last_processed = -1
        self.last_sent_at = 0.0

    def update(self, *, force: bool = False, config: JobConfig | DeleteConfig | None = None) -> bool:
        job = self.store.job(self.user_id)
        settings = self.store.settings(self.user_id)
        stats = job_stats(job)
        now = time.time()
        if not force and config:
            if (
                int(stats["processed"]) - self.last_processed < config.status_every_ids
                and now - self.last_sent_at < config.status_every_seconds
            ):
                return False
        chat_id = str(job.get("status_chat_id") or self.user_id)
        message_id = int(job.get("status_message_id") or 0)
        if not message_id:
            return False
        ok, data = self.api.edit_status_message(chat_id, message_id, panel_text(settings, job), main_keyboard(job))
        detail = str(data.get("description", ""))
        if ok or "message_not_modified" in detail.lower() or "message was not modified" in detail.lower():
            self.last_processed = int(stats["processed"])
            self.last_sent_at = now
            return True
        LOGGER.warning("User %s panel update skipped: %s", self.user_id, detail or "unknown error")
        return False


class BaseWorker:
    def __init__(self, api: BotApi, store: Store, config: JobConfig | DeleteConfig, on_finished: Callable[[int, str], None]) -> None:
        self.api = api
        self.store = store
        self.config = config
        self.on_finished = on_finished
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._run, name=f"channel-job-{config.user_id}", daemon=True)

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
            time.sleep(min(0.25, deadline - time.monotonic()))

    def _log(self, job: dict[str, Any], label: str) -> None:
        stats = job_stats(job)
        operation = str(job.get("operation", "copy"))
        amount = int(job.get("deleted" if operation == "delete" else "copied", 0))
        noun = "deleted" if operation == "delete" else "copied"
        LOGGER.info(
            "user=%s %s: %s/%s (%.1f%%) | %s %s, skipped %s | %.2f IDs/s | ETA %s",
            self.config.user_id,
            label,
            f"{int(stats['processed']):,}", f"{int(stats['total']):,}", float(stats["percent"]),
            noun, f"{amount:,}", f"{int(job.get('skipped', 0)):,}",
            float(stats["speed"]), format_duration(stats["eta"]),
        )

    def _save_finish(self, job: dict[str, Any], state: str, note: str) -> None:
        job["status"] = state
        job["note"] = note
        job["interrupted"] = False
        if state != "error":
            job["error"] = ""
        else:
            job["error"] = note
        self.store.save_job(self.config.user_id, job)
        StatusCard(self.api, self.store, self.config.user_id).update(force=True)
        self.on_finished(self.config.user_id, state)


class CopyWorker(BaseWorker):
    def _checkpoint(self, job: dict[str, Any], next_id: int, copied: int = 0, skipped: int = 0) -> dict[str, Any]:
        job["next_id"] = int(next_id)
        job["copied"] = int(job.get("copied", 0)) + int(copied)
        job["skipped"] = int(job.get("skipped", 0)) + int(skipped)
        job["status"] = "running"
        job["operation"] = "copy"
        job["note"] = ""
        self.store.save_job(self.config.user_id, job)
        return job

    def _run(self) -> None:
        cfg = self.config
        assert isinstance(cfg, JobConfig)
        job = self.store.job(cfg.user_id)
        job.update({
            "status": "running", "operation": "copy", "deleted": 0,
            "delete_channel": "", "delete_role": "", "start_id": cfg.start_id, "end_id": cfg.end_id,
            "next_id": max(cfg.start_id, int(job.get("next_id", cfg.start_id))),
            "note": "", "error": "", "interrupted": False,
        })
        if not float(job.get("started_at") or 0):
            job["started_at"] = time.time()
        self.store.save_job(cfg.user_id, job)
        card = StatusCard(self.api, self.store, cfg.user_id)
        card.update(force=True)
        current = int(job["next_id"])
        LOGGER.info("user=%s copy start (%s-%s)", cfg.user_id, current, cfg.end_id)

        while current <= cfg.end_id and not self.stopped():
            last = min(cfg.end_id, current + cfg.batch_size - 1)
            ids = list(range(current, last + 1))
            ok, data = self.api.copy_messages(cfg.target, cfg.source, ids, self.stopped)
            if ok:
                copied = len(data.get("result") or [])
                job = self._checkpoint(job, last + 1, copied=copied, skipped=len(ids) - copied)
                current = last + 1
                self._log(job, f"IDs {ids[0]}-{ids[-1]}")
                card.update(config=cfg)
            else:
                detail = str(data.get("description", "Unknown Telegram error"))
                if data.get("stopped") or self.stopped():
                    break
                if is_fatal(detail):
                    self._save_finish(job, "error", detail)
                    return
                for msg_id in ids:
                    if self.stopped():
                        break
                    one_ok, one = self.api.copy_message(cfg.target, cfg.source, msg_id, self.stopped)
                    if one_ok:
                        job = self._checkpoint(job, msg_id + 1, copied=1)
                    else:
                        one_detail = str(one.get("description", "Unknown Telegram error"))
                        if one.get("stopped") or self.stopped():
                            break
                        if is_fatal(one_detail):
                            self._save_finish(job, "error", one_detail)
                            return
                        job = self._checkpoint(job, msg_id + 1, skipped=1)
                    current = msg_id + 1
                    card.update(config=cfg)
                    self._sleep(cfg.individual_delay_seconds)
                self._log(job, f"IDs {ids[0]}-{min(last, current - 1)}")
            self._sleep(cfg.delay_seconds)

        if self.stopped():
            job["status"] = "paused"
            job["note"] = "Paused safely. Tap Resume to continue from the saved next ID."
            self.store.save_job(cfg.user_id, job)
            card.update(force=True)
            self.on_finished(cfg.user_id, "paused")
            return
        self._log(job, "Finished")
        self._save_finish(job, "completed", "Copy finished. You can change setup for another migration.")


class DeleteWorker(BaseWorker):
    def _checkpoint(self, job: dict[str, Any], next_id: int, deleted: int = 0, skipped: int = 0) -> dict[str, Any]:
        job["next_id"] = int(next_id)
        job["deleted"] = int(job.get("deleted", 0)) + int(deleted)
        job["skipped"] = int(job.get("skipped", 0)) + int(skipped)
        job["status"] = "running"
        job["operation"] = "delete"
        job["note"] = ""
        self.store.save_job(self.config.user_id, job)
        return job

    def _run(self) -> None:
        cfg = self.config
        assert isinstance(cfg, DeleteConfig)
        job = self.store.job(cfg.user_id)
        job.update({
            "status": "running", "operation": "delete", "start_id": cfg.start_id, "end_id": cfg.end_id,
            "next_id": max(cfg.start_id, int(job.get("next_id", cfg.start_id))),
            "delete_channel": cfg.channel, "delete_role": cfg.role,
            "note": "", "error": "", "interrupted": False,
        })
        if not float(job.get("started_at") or 0):
            job["started_at"] = time.time()
        self.store.save_job(cfg.user_id, job)
        card = StatusCard(self.api, self.store, cfg.user_id)
        card.update(force=True)
        current = int(job["next_id"])
        LOGGER.info("user=%s delete start (%s-%s)", cfg.user_id, current, cfg.end_id)

        while current <= cfg.end_id and not self.stopped():
            last = min(cfg.end_id, current + cfg.batch_size - 1)
            ids = list(range(current, last + 1))
            ok, data = self.api.delete_messages(cfg.channel, ids, self.stopped)
            if ok:
                job = self._checkpoint(job, last + 1, deleted=len(ids))
                current = last + 1
                self._log(job, f"IDs {ids[0]}-{ids[-1]}")
                card.update(config=cfg)
            else:
                detail = str(data.get("description", "Unknown Telegram error"))
                if data.get("stopped") or self.stopped():
                    break
                if is_fatal(detail):
                    self._save_finish(job, "error", detail)
                    return
                for msg_id in ids:
                    if self.stopped():
                        break
                    one_ok, one = self.api.delete_message(cfg.channel, msg_id, self.stopped)
                    if one_ok:
                        job = self._checkpoint(job, msg_id + 1, deleted=1)
                    else:
                        one_detail = str(one.get("description", "Unknown Telegram error"))
                        if one.get("stopped") or self.stopped():
                            break
                        if is_fatal(one_detail):
                            self._save_finish(job, "error", one_detail)
                            return
                        job = self._checkpoint(job, msg_id + 1, skipped=1)
                    current = msg_id + 1
                    card.update(config=cfg)
                    self._sleep(cfg.individual_delay_seconds)
                self._log(job, f"IDs {ids[0]}-{min(last, current - 1)}")
            self._sleep(cfg.delay_seconds)

        if self.stopped():
            job["status"] = "paused"
            job["note"] = "Deletion paused safely. Tap Resume to continue from the saved next ID."
            self.store.save_job(cfg.user_id, job)
            card.update(force=True)
            self.on_finished(cfg.user_id, "paused")
            return
        self._log(job, "Finished")
        self._save_finish(job, "completed", "Deletion finished for the confirmed range.")


class JobManager:
    """Owns independent workers. A user's task never replaces another user's task."""

    def __init__(self, api: BotApi, store: Store, max_active_jobs: int = 3) -> None:
        self.api = api
        self.store = store
        self.max_active_jobs = max(1, int(max_active_jobs))
        self._lock = threading.RLock()
        self._workers: dict[int, BaseWorker] = {}

    def _cleanup(self) -> None:
        self._workers = {uid: worker for uid, worker in self._workers.items() if worker.alive()}

    def running(self, user_id: int) -> bool:
        with self._lock:
            self._cleanup()
            worker = self._workers.get(int(user_id))
            return bool(worker and worker.alive())

    def pause(self, user_id: int) -> tuple[bool, str]:
        with self._lock:
            worker = self._workers.get(int(user_id))
            if worker and worker.alive():
                worker.request_stop()
                job = self.store.job(user_id)
                job["status"] = "paused"
                job["note"] = "Pausing safely after the current Telegram request."
                self.store.save_job(user_id, job)
                return True, "Pause requested."
            job = self.store.job(user_id)
            if str(job.get("status")) == "running":
                job["status"] = "paused"
                job["note"] = "Task paused."
                self.store.save_job(user_id, job)
                return True, "Paused."
            return False, "There is no active task to pause."

    def _capacity_ok(self) -> bool:
        self._cleanup()
        return len(self._workers) < self.max_active_jobs

    @staticmethod
    def _worker_done(_user_id: int, _state: str) -> None:
        return

    def _settings_config(self, user_id: int, *, require_range: bool = True) -> JobConfig:
        s = self.store.settings(user_id)
        source = s["source_channel"].strip()
        target = s["target_channel"].strip()
        start = as_int(s["range_start"], 1)
        end = as_int(s["range_end"], 0)
        if not source or not target:
            raise ValueError("Set Source and Target first.")
        if source == target:
            raise ValueError("Source and Target must be different channels.")
        if require_range and (start < 1 or end < start):
            raise ValueError("Set a valid message range first.")
        return JobConfig(
            user_id=int(user_id), source=source, target=target, start_id=start, end_id=end,
            batch_size=max(1, min(as_int(s["batch_size"], 25), 100)),
            delay_seconds=max(0.0, as_float(s["delay_seconds"], 0.6)),
            individual_delay_seconds=max(0.0, as_float(s["individual_delay_seconds"], 0.12)),
            status_every_ids=max(1, as_int(s["status_every_ids"], 25)),
            status_every_seconds=max(5, as_int(s["status_every_seconds"], 20)),
        )

    def _peer_check(self, label: str, chat: str) -> tuple[bool, str]:
        ok, data = self.api.verify_peer(chat)
        if ok:
            return True, ""
        detail = str(data.get("description", "Unknown Telegram error"))
        return False, f"{label} cannot be reached: {detail}"

    def start_copy(self, user_id: int, *, resume: bool = False) -> tuple[bool, str]:
        with self._lock:
            if self.running(user_id):
                return False, "Your task is already running."
            if not self._capacity_ok():
                return False, "The bot is busy with other tasks. Try again shortly."
            try:
                cfg = self._settings_config(user_id)
            except ValueError as exc:
                return False, str(exc)
            for label, chat in (("Source", cfg.source), ("Target", cfg.target)):
                ok, detail = self._peer_check(label, chat)
                if not ok:
                    return False, detail
            old = self.store.job(user_id)
            if not resume or str(old.get("operation")) != "copy" or str(old.get("status")) not in {"paused", "running"}:
                job = self.store.reset_job(user_id, cfg.start_id, cfg.end_id)
            else:
                job = old
                job["start_id"], job["end_id"] = cfg.start_id, cfg.end_id
                job["next_id"] = max(cfg.start_id, int(job.get("next_id", cfg.start_id)))
            job.update({"status": "running", "operation": "copy", "note": "Copy started.", "error": "", "interrupted": False})
            self.store.save_job(user_id, job)
            worker = CopyWorker(self.api, self.store, cfg, self._worker_done)
            self._workers[int(user_id)] = worker
            worker.start()
            return True, "Copy started."

    def start_delete(self, user_id: int, role: str, start_id: int, end_id: int) -> tuple[bool, str]:
        with self._lock:
            if self.running(user_id):
                return False, "Pause your active task before deleting."
            if not self._capacity_ok():
                return False, "The bot is busy with other tasks. Try again shortly."
            role = role.lower().strip()
            if role not in {"source", "target"}:
                return False, "Choose Source or Target."
            if int(start_id) < 1 or int(end_id) < int(start_id):
                return False, "Choose a valid delete range."
            s = self.store.settings(user_id)
            channel = str(s.get(f"{role}_channel", "")).strip()
            if not channel:
                return False, f"Set your {role.title()} channel first."
            ok, detail = self._peer_check(role.title(), channel)
            if not ok:
                return False, detail
            cfg = DeleteConfig(
                user_id=int(user_id), channel=channel, role=role, start_id=int(start_id), end_id=int(end_id),
                batch_size=max(1, min(as_int(s["batch_size"], 25), 100)),
                delay_seconds=max(0.0, as_float(s["delay_seconds"], 0.6)),
                individual_delay_seconds=max(0.0, as_float(s["individual_delay_seconds"], 0.12)),
                status_every_ids=max(1, as_int(s["status_every_ids"], 25)),
                status_every_seconds=max(5, as_int(s["status_every_seconds"], 20)),
            )
            job = self.store.reset_job(user_id, cfg.start_id, cfg.end_id)
            job.update({
                "status": "running", "operation": "delete", "delete_channel": channel, "delete_role": role,
                "note": "Confirmed deletion started.", "error": "", "interrupted": False,
            })
            self.store.save_job(user_id, job)
            worker = DeleteWorker(self.api, self.store, cfg, self._worker_done)
            self._workers[int(user_id)] = worker
            worker.start()
            return True, "Deletion started."

    def resume(self, user_id: int) -> tuple[bool, str]:
        job = self.store.job(user_id)
        if str(job.get("status")) != "paused":
            return False, "There is no paused task to resume."
        if str(job.get("operation")) == "delete":
            return self.start_delete(user_id, str(job.get("delete_role") or ""), int(job.get("start_id", 1)), int(job.get("end_id", 0)))
        return self.start_copy(user_id, resume=True)
