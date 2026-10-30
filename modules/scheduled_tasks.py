"""Persistent owner-managed schedules, independent of the active brain."""
from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timezone
import json
import logging
import math
from pathlib import Path
import re
import time
import uuid

log = logging.getLogger("overlord.schedules")
USAGE = """Scheduled tasks (Overlord must be running)
/schedule — list tasks and IDs
/schedule in 30m <task> — run once after a delay
/schedule at 2026-11-01T09:00:00-06:00 <task> — run once at an explicit time
/schedule every 24h <task> — repeat at a fixed interval
/schedule edit <id> <task> — change future task text; keep timing and state
/schedule pause|resume|remove|run <id>
Durations: seconds (s), minutes (m), hours (h), days (d), minimum 60s.
Overdue tasks run once when idle; recurring tasks skip missed intervals.
Tasks use the active brain and current permissions. /stop stops a running turn;
pause or remove its schedule to prevent future runs."""


def duration(value: str) -> int:
    match = re.fullmatch(r"([1-9][0-9]{0,7})([smhd])", value.lower())
    if not match:
        raise ValueError("Use a duration such as 30m, 2h or 1d.")
    seconds = int(match[1]) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[match[2]]
    if not 60 <= seconds <= 366 * 86400:
        raise ValueError("Duration must be between 60 seconds and 366 days.")
    return seconds


def timestamp(value: str) -> float:
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if date.tzinfo is None:
        raise ValueError("Include a UTC offset, for example -06:00, or Z for UTC.")
    return date.timestamp()


def display_time(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).astimezone().isoformat(timespec="seconds")


class ScheduledTasks:
    def __init__(self, path: Path, *, send, start, busy, clock=time.time):
        self.path, self.send, self.start, self.busy, self.clock = path, send, start, busy, clock
        self.tasks = {}
        self.load_error = ""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("version") != 1 or not isinstance(data.get("tasks"), dict):
                raise ValueError("Unsupported schedules file")
            for key, row in data["tasks"].items():
                if (not isinstance(row, dict) or row.get("id") != key
                        or not isinstance(row.get("prompt"), str) or not row["prompt"].strip()
                        or row.get("state") not in {"active", "paused", "dispatched", "failed"}
                        or type(row.get("interval")) is not int or not 0 <= row["interval"] <= 366 * 86400
                        or (row["interval"] and row["interval"] < 60)
                        or type(row.get("next_run")) not in (int, float)
                        or not math.isfinite(row["next_run"])):
                    raise ValueError("Invalid scheduled task")
            self.tasks = data["tasks"]
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            self.load_error = f"Cannot load schedules; original file preserved: {exc}"
            log.error(self.load_error)

    def _save(self, tasks):
        if self.load_error:
            raise ValueError(self.load_error)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"version": 1, "tasks": tasks}, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
        self.tasks = tasks

    def handle(self, chat_id, text):
        try:
            reply = self.command(text)
        except (ValueError, OSError, OverflowError) as exc:
            reply = f"Schedule not changed: {exc}"
        self.send(chat_id, reply)

    def command(self, text):
        if self.load_error:
            raise ValueError(self.load_error)
        parts = text.strip().split(maxsplit=3)
        action = parts[1].lower() if len(parts) > 1 else "list"
        if action in {"list", "help"}:
            if action == "help" or not self.tasks:
                return USAGE
            return "Scheduled tasks:\n" + "\n".join(
                f"{row['id']} · {row['state']} · {display_time(row['next_run'])} · "
                f"{'every ' + str(row['interval']) + 's' if row['interval'] else 'once'} · {row['prompt']}"
                for row in self.tasks.values()) + "\n/schedule help for commands."
        tasks = copy.deepcopy(self.tasks)
        now = self.clock()
        if action in {"in", "at", "every"}:
            if len(parts) != 4 or not parts[3].strip():
                return USAGE
            if len(tasks) >= 100:
                raise ValueError("Limit of 100 schedules reached; remove old tasks first.")
            if len(parts[3]) > 16000:
                raise ValueError("Task must be at most 16,000 characters.")
            interval = duration(parts[2]) if action != "at" else 0
            due = timestamp(parts[2]) if action == "at" else now + interval
            if due <= now:
                raise ValueError("Choose a future time.")
            key = uuid.uuid4().hex[:12]
            tasks[key] = {"id": key, "prompt": parts[3], "state": "active", "next_run": due,
                          "interval": interval if action == "every" else 0, "last_dispatch": None}
            reply = f"Scheduled {key} for {display_time(due)}. " + (
                f"Repeats every {interval}s." if action == "every" else "Runs once.")
        elif action == "edit":
            if len(parts) != 4 or not parts[3].strip():
                return USAGE
            key = parts[2]
            if key not in tasks:
                raise ValueError("Unknown task ID. Use /schedule to list IDs.")
            tasks[key]["prompt"] = parts[3]
            reply = f"Schedule {key}: task updated for future runs; timing and state unchanged."
        elif action in {"pause", "resume", "remove", "run"}:
            if len(parts) != 3:
                return USAGE
            key = parts[2]
            if key not in tasks:
                raise ValueError("Unknown task ID. Use /schedule to list IDs.")
            if action == "remove":
                del tasks[key]
            else:
                tasks[key]["state"] = "paused" if action == "pause" else "active"
                if action == "run":
                    tasks[key]["next_run"] = now
                elif action == "resume" and tasks[key]["interval"]:
                    tasks[key]["next_run"] = now + tasks[key]["interval"]
            reply = f"Schedule {key}: {action}." + (" Queued until idle." if action == "run" else "")
        else:
            return USAGE
        self._save(tasks)
        return reply

    def tick(self, chat_id):
        if self.load_error or self.busy():
            return
        now = self.clock()
        due = sorted((row for row in self.tasks.values()
                      if row["state"] == "active" and row["next_run"] <= now), key=lambda row: row["next_run"])
        if not due:
            return
        row = due[0]
        tasks = copy.deepcopy(self.tasks)
        claimed = tasks[row["id"]]
        claimed["last_dispatch"] = now
        if row["interval"]:
            claimed["next_run"] += (int((now - row["next_run"]) // row["interval"]) + 1) * row["interval"]
        else:
            claimed["state"] = "dispatched"
        # Persist before starting: a crash must not silently replay work already started.
        self._save(tasks)
        try:
            if not self.start(chat_id, f"Scheduled task {row['id']}:\n{row['prompt']}"):
                raise RuntimeError("The active brain did not accept the task")
        except Exception as exc:
            tasks = copy.deepcopy(self.tasks)
            tasks[row["id"]]["state"] = "failed"
            self._save(tasks)
            self.send(chat_id, f"Schedule {row['id']} failed to dispatch: {exc}. Use /schedule run to retry.")
            return
        self.send(chat_id, f"Started scheduled task {row['id']}: {row['prompt']}")

    async def watch(self, chat_id):
        if self.load_error:
            self.send(chat_id, self.load_error)
        while True:
            try:
                self.tick(chat_id)
            except Exception:
                log.exception("Scheduled task poll failed")
            await asyncio.sleep(5)
