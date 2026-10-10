"""Bounded, local decision evidence without raw tool arguments or transcripts."""

import datetime
import json
import os
from pathlib import Path
import threading


class PermissionAudit:
    def __init__(self, path: Path, *, root: Path, max_bytes=256 * 1024):
        self.path = path
        self.root = root.resolve()
        self.max_bytes = max_bytes
        self._lock = threading.Lock()

    def record(self, *, action: str | None, allowed: bool, source: str, actor: int) -> bool:
        record = {"schema": 1, "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  "action": action, "allowed": allowed, "source": source, "actor": actor}
        data = (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")
        if len(data) > self.max_bytes:
            return False
        try:
            with self._lock:
                previous = self.path.with_name(self.path.name + ".previous")
                for path in (self.path, previous):
                    if path.is_symlink() or not path.resolve().is_relative_to(self.root):
                        return False
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.path.exists() and self.path.stat().st_size + len(data) > self.max_bytes:
                    os.replace(self.path, previous)
                flags = os.O_CREAT | os.O_APPEND | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
                fd = os.open(self.path, flags, 0o600)
                with os.fdopen(fd, "ab") as file:
                    file.write(data)
                    file.flush()
                    os.fsync(file.fileno())
            return True
        except (OSError, RuntimeError, ValueError):
            return False
