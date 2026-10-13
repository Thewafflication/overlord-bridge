"""Shell activity in the bridge log consumed by the desktop console."""
from __future__ import annotations

import logging
import os
import threading
from collections import OrderedDict

log = logging.getLogger("overlord.commands")
_shared_seen: OrderedDict[tuple, None] = OrderedDict()
_shared_lock = threading.Lock()


def _display(value: object) -> str:
    text = str(value)
    for name, secret in os.environ.items():
        if len(secret) >= 8 and any(word in name.upper() for word in ("TOKEN", "KEY", "PASSWORD", "SECRET")):
            text = text.replace(secret, "[redacted]")
    return text.replace("\r", "\\r").replace("\n", "\\n")[:8000]


def log_command(engine: str, phase: str, command: object, cwd: object = "", *, exit_code=None) -> None:
    if isinstance(command, list):
        command = " ".join(str(part) for part in command)
    result = f" | exit={exit_code}" if exit_code is not None else ""
    log.info("COMMAND %s %s | cwd=%s | %s%s", _display(engine), phase,
             _display(cwd), _display(command), result)


def log_shared_shell(transcript: object, tool_id: str, phase: str, command: object, cwd: object) -> None:
    """A shared Claude transcript is polled repeatedly; show each event once."""
    key = (str(transcript), tool_id, phase)
    with _shared_lock:
        if key in _shared_seen:
            return
        _shared_seen[key] = None
        while len(_shared_seen) > 4096:
            _shared_seen.popitem(last=False)
    log_command("claude shared", phase, command, cwd)
