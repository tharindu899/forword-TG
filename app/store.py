"""SQLite persistence for channel settings, job state, and status-card identity."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


DEFAULT_SETTINGS: dict[str, str] = {
    "source_channel": "",
    "target_channel": "",
    "range_start": "1",
    "range_end": "0",
    "batch_size": "25",
    "delay_seconds": "0.60",
    "individual_delay_seconds": "0.12",
    "status_every_ids": "25",
    "status_every_seconds": "20",
}

DEFAULT_JOB: dict[str, Any] = {
    "status": "idle",
    "start_id": 1,
    "end_id": 0,
    "next_id": 1,
    "copied": 0,
    "skipped": 0,
    "started_at": 0.0,
    "updated_at": 0.0,
    "error": "",
    "note": "",
    "interrupted": False,
    # One persistent owner-PM message. It survives range changes and restart.
    "status_chat_id": "",
    "status_message_id": None,
}


class Store:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._create_tables()
        for key, value in DEFAULT_SETTINGS.items():
            self._set_default(key, value)
        if self.get_job_raw() is None:
            self.save_job(DEFAULT_JOB.copy())

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _create_tables(self) -> None:
        with self._lock, self._conn:
            self._conn.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            self._conn.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

    def _set_default(self, key: str, value: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("INSERT OR IGNORE INTO kv(key, value) VALUES (?, ?)", (key, value))

    def get(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self._conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def set(self, key: str, value: str | int | float) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO kv(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )

    def settings(self) -> dict[str, str]:
        return {key: self.get(key, default) for key, default in DEFAULT_SETTINGS.items()}

    def get_owner_id(self) -> int:
        raw = self.get("owner_id", "0")
        try:
            return int(raw)
        except ValueError:
            return 0

    def set_owner_id(self, user_id: int) -> None:
        self.set("owner_id", user_id)

    def get_update_offset(self) -> int | None:
        raw = self.get("update_offset", "")
        try:
            return int(raw) if raw else None
        except ValueError:
            return None

    def set_update_offset(self, offset: int) -> None:
        self.set("update_offset", offset)

    def get_job_raw(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM state WHERE key = 'job'").fetchone()
        if not row:
            return None
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return None

    def job(self) -> dict[str, Any]:
        raw = self.get_job_raw() or {}
        result = DEFAULT_JOB.copy()
        result.update(raw)
        return result

    def save_job(self, job: dict[str, Any]) -> None:
        state = DEFAULT_JOB | job
        state["updated_at"] = time.time()
        encoded = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO state(key, value) VALUES ('job', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (encoded,),
            )

    def reset_job(self, start_id: int, end_id: int) -> dict[str, Any]:
        previous = self.job()
        job = DEFAULT_JOB.copy()
        # Preserve the one owner-PM status card so no extra status posts appear.
        job.update({
            "status_chat_id": previous.get("status_chat_id", ""),
            "status_message_id": previous.get("status_message_id"),
            "start_id": start_id,
            "end_id": end_id,
            "next_id": start_id,
        })
        self.save_job(job)
        return job

    def recover_after_restart(self) -> dict[str, Any]:
        job = self.job()
        if job["status"] in {"running", "stopping"}:
            job["status"] = "paused"
            job["interrupted"] = True
            job["note"] = "Hugging Face Space restarted while copying."
            self.save_job(job)
        return job
