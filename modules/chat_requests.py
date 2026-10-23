"""A small append-only queue of chat requests from the desktop console.

The console is a separate process from the bridge, so a message typed in the
window has to travel through the filesystem. The bridge already uses a
single-slot command file for its buttons, but that slot can only hold one
request: two quick messages would overwrite each other and the first would be
lost without a trace.

So chat messages get their own append-only JSON Lines file instead:

    {"at": 1730000000000000000, "text": "what is up"}

The console appends one line per message; the bridge follows the file by byte
offset and dispatches every line it has not seen yet. A trailing partial line
(a write in progress) is left for the next pass, so a half-written message is
never dispatched as a truncated one.
"""

from __future__ import annotations

import json
import hashlib
import os
import time
from pathlib import Path
from typing import List, Tuple

# The console writes here; the bridge reads here.
DEFAULT_REQUEST_FILE = Path("run") / "console-chat.jsonl"


def request_id() -> int:
    """A timestamp that never repeats inside one process."""
    return time.time_ns()


def append_request(path: Path, text: str) -> bool:
    """Append one chat request to the queue. Never raises."""
    clean = (text or "").strip()
    if not clean:
        return False
    payload = {"at": request_id(), "text": clean}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        return False
    return True


def read_request_batch(path: Path, offset: int = 0):
    """Return (text, raw end offset) records plus the complete-record boundary."""
    records = []
    try:
        with path.open("rb") as stream:
            if os.fstat(stream.fileno()).st_size < offset:
                offset = 0
            stream.seek(offset)
            end = offset
            while len(records) < 100:
                raw = stream.readline()
                if not raw or not raw.endswith(b"\n"):
                    break
                end = stream.tell()
                try:
                    payload = json.loads(raw.decode("utf-8", errors="replace"))
                except ValueError:
                    continue
                if isinstance(payload, dict) and isinstance(payload.get("text"), str):
                    text = payload["text"].strip()
                    if text:
                        records.append((text, end))
            return records, end
    except OSError:
        return [], offset


def read_requests(path: Path, offset: int = 0) -> Tuple[List[str], int]:
    records, end = read_request_batch(path, offset)
    return [text for text, _ in records], end


class RequestReader:
    """Persist delivery receipts; replay unacknowledged messages after restart."""
    def __init__(self, path: Path):
        self.path = path
        self.cursor = path.with_suffix(path.suffix + ".cursor.json")
        self.state = {"offset": 0, "identity": None, "anchor": ""}
        self.pending = False
        try:
            saved = json.loads(self.cursor.read_text(encoding="utf-8"))
            if (isinstance(saved, dict) and type(saved.get("offset")) is int
                    and saved["offset"] >= 0 and isinstance(saved.get("anchor"), str)
                    and isinstance(saved.get("identity"), list)):
                self.state = saved
        except (OSError, ValueError):
            pass

    def _anchor(self, offset):
        with self.path.open("rb") as stream:
            stream.seek(max(0, offset - 64))
            return hashlib.sha256(stream.read(min(offset, 64))).hexdigest()

    def _save(self):
        temporary = self.cursor.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.state), encoding="utf-8")
        temporary.replace(self.cursor)
        self.pending = False

    def read(self):
        if self.pending:
            self._save()
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            return [], self.state["offset"]
        identity = [stat.st_dev, stat.st_ino]
        offset = self.state["offset"]
        if (identity != self.state["identity"] or stat.st_size < offset
                or (offset and self._anchor(offset) != self.state["anchor"])):
            self.state = {"offset": 0, "identity": identity, "anchor": ""}
        return read_request_batch(self.path, self.state["offset"])

    def acknowledge(self, offset):
        self.state["offset"] = offset
        self.state["anchor"] = self._anchor(offset)
        self.pending = True
        self._save()


__all__ = ["DEFAULT_REQUEST_FILE", "append_request", "read_requests", "read_request_batch", "RequestReader", "request_id"]
