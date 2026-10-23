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


def read_requests(path: Path, offset: int = 0) -> Tuple[List[str], int]:
    """Return the messages queued after *offset* and the new offset.

    Only whole lines are read; a message still being written stays unread
    until the writer finishes it.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return [], offset
    if size < offset:
        # The file was rotated or truncated; start over.
        offset = 0
    if size == offset:
        return [], offset
    try:
        # Read raw bytes from the current offset to avoid mis‑counting because
        # Windows text mode converts CRLF to LF.  We keep the byte offset in the
        # caller so the same value can be used each iteration.
        with path.open("rb") as f:
            f.seek(offset)
            raw = f.read()
    except OSError:
        return [], offset
    # Find complete records in bytes before decoding. Replacement characters
    # and Windows newline translation must never change the consumed offset.
    consumed = raw.rfind(b"\n") + 1
    if not consumed:
        return [], offset
    text = raw[:consumed].decode("utf-8", errors="replace")
    messages: List[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("text"), str):
            txt = payload["text"].strip()
            if txt:
                messages.append(txt)
    return messages, offset + consumed


__all__ = ["DEFAULT_REQUEST_FILE", "append_request", "read_requests", "request_id"]
