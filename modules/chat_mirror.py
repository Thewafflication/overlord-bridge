"""Durable chat transcript shared by the bridge and the desktop console.

The bridge owns the conversation; the console is a separate process that only
reads. Both sides therefore meet at one append-only JSON Lines file:

    {"seq": 1, "at": 1730000000.0, "role": "owner", "source": "telegram", "text": "..."}

``role`` is ``owner`` (the human) or ``overlord`` (the assistant). ``source``
says where the message entered the system, so the console can show that a
message typed in the window was also delivered to Telegram.

The file appends records and periodically retains a bounded tail. Readers
follow byte offsets and reset when the file is replaced or truncated. Records that are half-written
(the bridge was killed mid-append) are ignored rather than crashing the reader.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Dict, Iterator, List, Tuple

ROLE_OWNER = "owner"
ROLE_OVERLORD = "overlord"
SOURCE_TELEGRAM = "telegram"
SOURCE_GUI = "gui"


class ChatMirror:
    """Append-only transcript of the owner/Overlord conversation."""

    def __init__(self, path: Path, *, max_bytes: int = 2 * 1024 * 1024) -> None:
        self.path = path
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self._sequence = 0

    def append(self, role: str, text: str, source: str = SOURCE_TELEGRAM) -> None:
        """Record one message. Never raises: mirroring must not break chat."""
        clean = (text or "").strip()
        if not clean:
            return
        with self._lock:
            self._sequence += 1
            record = {
                "seq": self._sequence,
                "at": time.time(),
                "role": role,
                "source": source,
                "text": clean,
            }
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                    stream.flush()
                if self.path.stat().st_size > self.max_bytes:
                    with self.path.open("rb") as stream:
                        stream.seek(max(0, self.path.stat().st_size - self.max_bytes // 2))
                        stream.readline()  # discard a potentially partial first record
                        tail = stream.read()
                    if not tail:
                        # Keep a single large latest record rather than losing it.
                        raw = self.path.read_bytes()
                        tail = raw[raw.rfind(b"\n", 0, len(raw) - 1) + 1:]
                    temporary = self.path.with_suffix(".rotate.tmp")
                    temporary.write_bytes(tail)
                    temporary.replace(self.path)
            except OSError:
                self._sequence -= 1

    def read_since(self, offset: int = 0) -> Tuple[List[Dict], int]:
        """Return the records appended after *offset* and the new offset.

        A trailing partial line (a write in progress) is left unread: the
        offset stays at the last complete record so the next call picks it up.
        """
        try:
            size = self.path.stat().st_size
        except OSError:
            return [], offset
        if size < offset:
            # The file was rotated or truncated; start over.
            offset = 0
        if size == offset:
            return [], offset
        try:
            with self.path.open("rb") as stream:
                stream.seek(offset)
                raw = stream.read()
        except OSError:
            return [], offset
        consumed = raw.rfind(b"\n") + 1
        if not consumed:
            return [], offset
        content = raw[:consumed].decode("utf-8", errors="replace")
        records: List[Dict] = []
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if (
                isinstance(record, dict)
                and isinstance(record.get("text"), str)
            ):
                records.append(record)
        return records, offset + consumed

    def iter_all(self) -> Iterator[Dict]:
        """Yield every complete record in the transcript, oldest first."""
        offset = 0
        while True:
            records, offset = self.read_since(offset)
            if not records:
                return
            for record in records:
                yield record


def default_path(base_dir: Path) -> Path:
    """The transcript location used by the bridge and the console."""
    return Path(base_dir) / "run" / "chat-mirror.jsonl"


class DisabledChatMirror:
    """A mirror that records nothing, for a bridge with no transcript.

    The transcript is a convenience for the desktop window, never a
    requirement for the conversation itself. A bridge that was assembled
    without one (a test, or a half-built instance) must still serve messages
    rather than fail on every one of them.
    """

    def append(self, role: str, text: str, source: str = SOURCE_TELEGRAM) -> None:
        return None

    def read_since(self, offset: int = 0) -> Tuple[List[Dict], int]:
        return [], offset

    def iter_all(self) -> Iterator[Dict]:
        return iter(())


def describe_source(source: str) -> str:
    """Human label for where a message came from."""
    if source == SOURCE_GUI:
        return "GUI"
    if source == SOURCE_TELEGRAM:
        return "Telegram"
    return source or "unknown"


__all__ = [
    "ChatMirror",
    "DisabledChatMirror",
    "ROLE_OWNER",
    "ROLE_OVERLORD",
    "SOURCE_GUI",
    "SOURCE_TELEGRAM",
    "default_path",
    "describe_source",
]
