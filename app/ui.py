"""Shared compact panel renderer for every private user."""
from __future__ import annotations

import time
from html import escape
from typing import Any

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup


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


def job_stats(job: dict[str, Any]) -> dict[str, float | int | None]:
    start = int(job.get("start_id", 1))
    end = int(job.get("end_id", 0))
    total = max(0, end - start + 1)
    next_id = int(job.get("next_id", start))
    processed = min(total, max(0, next_id - start))
    started_at = float(job.get("started_at") or 0.0)
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


def progress_bar(percent: float, width: int = 12) -> str:
    """■ full, □ empty, and one ▤→▩ partial cell."""
    partial_cells = ("▤", "▥", "▦", "▧", "▨", "▩")
    width = max(1, int(width))
    units = max(0.0, min(100.0, float(percent))) / 100.0 * width
    full = min(width, int(units))
    if full >= width:
        return "■" * width
    fraction = units - full
    partial = ""
    if fraction > 1e-9:
        partial = partial_cells[min(len(partial_cells) - 1, int(fraction * len(partial_cells)))]
    return "■" * full + partial + "□" * (width - full - (1 if partial else 0))


def _short(value: str, limit: int = 28) -> str:
    value = value or "not set"
    return value if len(value) <= limit else value[: limit - 1] + "…"


def speed_name(settings: dict[str, str]) -> str:
    try:
        batch = int(settings.get("batch_size") or 25)
        delay = float(settings.get("delay_seconds") or 0.6)
    except ValueError:
        batch, delay = 25, 0.6
    if batch <= 12 or delay >= 0.8:
        return "Safe"
    if batch >= 40 or delay <= 0.4:
        return "Fast"
    return "Balanced"


def _symbol(title: str, rows: list[str]) -> str:
    lines = [f"▤ <b>{title}</b>"]
    for index, row in enumerate(rows):
        lines.append(("└" if index == len(rows) - 1 else "├") + " " + row)
    return "\n".join(lines)


def _quiet_panel_text(job: dict[str, Any], note: str = "") -> str:
    """Render a short, non-progress panel whenever no task is active.

    The detailed counters, progress bar, next ID, speed, and channel IDs are
    deliberately hidden until a copy or delete task is running or paused.
    """
    state = str(job.get("status", "idle")).lower()
    operation = str(job.get("operation", "copy")).lower()
    message_note = note or str(job.get("note") or job.get("error") or "")

    if state == "completed":
        label = "DELETE FINISHED" if operation == "delete" else "COPY FINISHED"
        rows = ["✅ <b>" + label + "</b>", "⚙️ Choose Setup or Copy for your next task."]
    elif state == "error":
        rows = ["🔴 <b>TASK STOPPED</b>", "⚙️ Check Setup, then start again when ready."]
    else:
        rows = ["🔵 <b>READY</b>", "⚙️ Configure a task when you are ready."]

    if message_note:
        rows.append(f"💬 {escape(_short(message_note, 80))}")
    return _symbol("CHANNEL COPIER", rows)


def panel_text(settings: dict[str, str], job: dict[str, Any], note: str = "") -> str:
    """Show full task telemetry only for an active or paused task."""
    state = str(job.get("status", "idle")).lower()
    if state not in {"running", "paused"}:
        return _quiet_panel_text(job, note)

    stats = job_stats(job)
    operation = str(job.get("operation", "copy")).lower()
    icon, label = {
        "running": ("🟢", "RUNNING"),
        "paused": ("🟡", "PAUSED"),
    }.get(state, ("🔵", "READY"))
    is_delete = operation == "delete"
    header = "CHANNEL DELETE" if is_delete else "CHANNEL COPIER"
    processed = int(stats["processed"])
    total = int(stats["total"])
    percent = float(stats["percent"])
    bar = progress_bar(percent)
    rows: list[str] = [
        f"{icon} <b>{label}</b>  •  <code>{percent:.1f}%</code>",
        f"<code>{bar}</code>  <b>{processed:,} / {total:,}</b>",
    ]
    if is_delete:
        rows.append(
            f"🗑 <b>{int(job.get('deleted', 0)):,}</b> deleted  •  ⏭ <b>{int(job.get('skipped', 0)):,}</b> skipped"
        )
    else:
        rows.append(
            f"✅ <b>{int(job.get('copied', 0)):,}</b> copied  •  ⏭ <b>{int(job.get('skipped', 0)):,}</b> skipped"
        )
    rows += [
        f"📥 Next <code>{int(job.get('next_id', 1)):,}</code>  •  ⚡ <code>{float(stats['speed']):.2f}/s</code>",
        f"⏳ <code>{format_duration(stats['eta'])}</code>  •  🕒 <code>{format_duration(float(stats['elapsed']))}</code>",
        f"🎯 <code>{int(job.get('start_id', 1)):,} → {int(job.get('end_id', 0)):,}</code>  •  ⚡ <code>{speed_name(settings)}</code>",
    ]
    if is_delete:
        rows.append(
            f"🧹 {escape(str(job.get('delete_role') or 'channel').title())}  "
            f"<code>{escape(_short(str(job.get('delete_channel') or 'not set')))}</code>"
        )
    else:
        rows.append(f"📥 <code>{escape(_short(settings.get('source_channel', '')))}</code>")
        rows.append(f"📤 <code>{escape(_short(settings.get('target_channel', '')))}</code>")
    message_note = note or str(job.get("note") or job.get("error") or "")
    if message_note:
        rows.append(f"💬 {escape(_short(message_note, 80))}")
    return _symbol(header, rows)


def main_keyboard(job: dict[str, Any]) -> InlineKeyboardMarkup:
    """Keep action buttons minimal; no Refresh button is needed for auto-updates."""
    state = str(job.get("status", "idle")).lower()
    if state == "running":
        return InlineKeyboardMarkup([[InlineKeyboardButton("⏸ Pause", callback_data="task:pause")]])
    if state == "paused":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("▶️ Resume", callback_data="task:resume"), InlineKeyboardButton("⚙️ Setup", callback_data="setup:open")],
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Setup", callback_data="setup:open"), InlineKeyboardButton("▶️ Copy", callback_data="task:copy")],
    ])
