"""Per-user SQLite storage for the multi-user channel copier.

Every Telegram user gets an isolated settings object, isolated task state, and
one private status-card ID. No user can read or edit another user's profile.
"""
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
    "status": "idle",  # idle | running | paused | completed | error
    "operation": "copy",  # copy | delete
    "start_id": 1,
    "end_id": 0,
    "next_id": 1,
    "copied": 0,
    "deleted": 0,
    "skipped": 0,
    "started_at": 0.0,
    "updated_at": 0.0,
    "error": "",
    "note": "",
    "interrupted": False,
    "delete_channel": "",
    "delete_role": "",
    "status_chat_id": "",
    "status_message_id": None,
}


class Store:
    """Thread-safe profile store keyed strictly by Telegram user ID."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._create_tables()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _create_tables(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id INTEGER PRIMARY KEY,
                    settings_json TEXT NOT NULL,
                    job_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )

    @staticmethod
    def _encode(data: dict[str, Any]) -> str:
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _decode(raw: str, default: dict[str, Any]) -> dict[str, Any]:
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            data = {}
        result = default.copy()
        if isinstance(data, dict):
            result.update(data)
        return result

    @staticmethod
    def _user_id(user_id: int | str) -> int:
        value = int(user_id)
        if value <= 0:
            raise ValueError("Telegram user ID must be positive.")
        return value

    def ensure_user(self, user_id: int | str) -> None:
        uid = self._user_id(user_id)
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO user_profiles(user_id, settings_json, job_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (uid, self._encode(DEFAULT_SETTINGS), self._encode(DEFAULT_JOB), now, now),
            )

    def _profile(self, user_id: int | str) -> sqlite3.Row:
        uid = self._user_id(user_id)
        self.ensure_user(uid)
        with self._lock:
            row = self._conn.execute(
                "SELECT user_id, settings_json, job_json FROM user_profiles WHERE user_id = ?", (uid,)
            ).fetchone()
        if row is None:  # pragma: no cover - defensive fallback
            raise RuntimeError("Could not create the user profile.")
        return row

    def _write(self, user_id: int, settings: dict[str, Any], job: dict[str, Any]) -> None:
        now = time.time()
        job = DEFAULT_JOB | job
        job["updated_at"] = now
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE user_profiles
                SET settings_json = ?, job_json = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (self._encode(settings), self._encode(job), now, int(user_id)),
            )

    def settings(self, user_id: int | str) -> dict[str, str]:
        row = self._profile(user_id)
        values = self._decode(str(row["settings_json"]), DEFAULT_SETTINGS)
        return {key: str(values.get(key, default)) for key, default in DEFAULT_SETTINGS.items()}

    def set(self, user_id: int | str, key: str, value: str | int | float) -> None:
        uid = self._user_id(user_id)
        row = self._profile(uid)
        settings = self._decode(str(row["settings_json"]), DEFAULT_SETTINGS)
        job = self._decode(str(row["job_json"]), DEFAULT_JOB)
        settings[str(key)] = str(value)
        self._write(uid, settings, job)

    def update_settings(self, user_id: int | str, values: dict[str, str | int | float]) -> None:
        uid = self._user_id(user_id)
        row = self._profile(uid)
        settings = self._decode(str(row["settings_json"]), DEFAULT_SETTINGS)
        job = self._decode(str(row["job_json"]), DEFAULT_JOB)
        for key, value in values.items():
            settings[str(key)] = str(value)
        self._write(uid, settings, job)

    def job(self, user_id: int | str) -> dict[str, Any]:
        row = self._profile(user_id)
        return self._decode(str(row["job_json"]), DEFAULT_JOB)

    def save_job(self, user_id: int | str, job: dict[str, Any]) -> None:
        uid = self._user_id(user_id)
        row = self._profile(uid)
        settings = self._decode(str(row["settings_json"]), DEFAULT_SETTINGS)
        self._write(uid, settings, job)

    def reset_job(self, user_id: int | str, start_id: int, end_id: int) -> dict[str, Any]:
        uid = self._user_id(user_id)
        previous = self.job(uid)
        job = DEFAULT_JOB.copy()
        job.update(
            {
                "status_chat_id": previous.get("status_chat_id", ""),
                "status_message_id": previous.get("status_message_id"),
                "start_id": int(start_id),
                "end_id": int(end_id),
                "next_id": int(start_id),
            }
        )
        self.save_job(uid, job)
        return job

    def bind_panel(self, user_id: int | str, chat_id: int | str, message_id: int) -> None:
        uid = self._user_id(user_id)
        job = self.job(uid)
        job["status_chat_id"] = str(chat_id)
        job["status_message_id"] = int(message_id)
        self.save_job(uid, job)

    def clear_field(self, user_id: int | str, field: str) -> None:
        """Clear one saved configuration field and safely reset only this user's job."""
        uid = self._user_id(user_id)
        if field not in {"source", "target", "range"}:
            raise ValueError("Unknown field.")
        values: dict[str, str | int] = {}
        if field == "source":
            values["source_channel"] = ""
        elif field == "target":
            values["target_channel"] = ""
        else:
            values["range_start"] = 1
            values["range_end"] = 0
        self.update_settings(uid, values)
        previous = self.job(uid)
        job = DEFAULT_JOB.copy()
        job["status_chat_id"] = previous.get("status_chat_id", "")
        job["status_message_id"] = previous.get("status_message_id")
        self.save_job(uid, job)

    def recover_after_restart(self) -> list[int]:
        """Mark interrupted jobs paused. Never resume another user's job automatically."""
        changed: list[int] = []
        with self._lock:
            rows = self._conn.execute("SELECT user_id, settings_json, job_json FROM user_profiles").fetchall()
        for row in rows:
            uid = int(row["user_id"])
            job = self._decode(str(row["job_json"]), DEFAULT_JOB)
            if str(job.get("status", "")).lower() in {"running", "stopping"}:
                job["status"] = "paused"
                job["interrupted"] = True
                job["note"] = "The service restarted. Tap Resume when you are ready."
                self.save_job(uid, job)
                changed.append(uid)
        return changed

    def users_with_jobs(self) -> list[int]:
        with self._lock:
            rows = self._conn.execute("SELECT user_id FROM user_profiles").fetchall()
        return [int(row["user_id"]) for row in rows]

    def migrate_legacy_owner(self, user_id: int | str) -> bool:
        """Best-effort one-time migration from the prior single-owner schema.

        It only runs when the new profile does not exist yet and only for the
        optional configured operator account. Other users always get fresh,
        private profiles.
        """
        uid = self._user_id(user_id)
        with self._lock:
            existing = self._conn.execute("SELECT 1 FROM user_profiles WHERE user_id = ?", (uid,)).fetchone()
            tables = {
                str(row["name"])
                for row in self._conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
            }
        if existing or not {"kv", "state"}.issubset(tables):
            return False

        try:
            with self._lock:
                rows = self._conn.execute("SELECT key, value FROM kv").fetchall()
                old_job_row = self._conn.execute("SELECT value FROM state WHERE key = 'job'").fetchone()
            old_settings = DEFAULT_SETTINGS.copy()
            for row in rows:
                key = str(row["key"])
                if key in old_settings:
                    old_settings[key] = str(row["value"])
            old_job = self._decode(str(old_job_row["value"]) if old_job_row else "{}", DEFAULT_JOB)
            now = time.time()
            with self._lock, self._conn:
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO user_profiles(user_id, settings_json, job_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (uid, self._encode(old_settings), self._encode(old_job), now, now),
                )
            return True
        except Exception:  # noqa: BLE001
            return False
