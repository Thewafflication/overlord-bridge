"""Start-up progress shared with the splash window.

The bridge takes a while to come up (library imports, Telegram, the brain), and
runs without a console when launched from the Start Menu. It therefore writes its
progress to a small state file that ``tools/overlord_splash.py`` displays. This
module is deliberately light (stdlib only): it is imported before the heavy
libraries so the splash can appear immediately.

``report`` is a no-op until ``begin`` configures a path, so importing the bridge
(tests, tools) never touches the filesystem or opens a window.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

_state_path: Path | None = None
_started = 0.0


def _write(state: str, stage: str, detail: str) -> None:
    if _state_path is None:
        return
    payload = {"state": state, "stage": stage, "detail": detail,
               "pid": os.getpid(), "started": _started, "at": time.time()}
    try:
        _state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = _state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        temporary.replace(_state_path)
    except OSError:
        pass  # progress display must never be the reason start-up fails


def report(stage: str, *, state: str = "starting", detail: str = "") -> None:
    """Record a start-up step. ``state`` is starting | ready | failed."""
    _write(state, stage, detail)


def ready(detail: str = "") -> None:
    _write("ready", "Online", detail)


def failed(stage: str, detail: str = "") -> None:
    _write("failed", stage, detail)


def begin(base_dir: Path) -> None:
    """Configure the state file and (on Windows) open the splash window."""
    global _state_path, _started
    run_dir = Path(base_dir) / "run"
    _state_path = run_dir / "startup.json"
    _started = time.time()
    _write("starting", "Loading libraries", "")
    if sys.platform != "win32" or os.environ.get("OVERLORD_SPLASH", "1").strip().lower() in (
        "0", "false", "no", "off"
    ):
        return
    log_path = run_dir / "overlord.log"
    try:
        offset = log_path.stat().st_size
    except OSError:
        offset = 0
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else Path(sys.executable)
    try:
        subprocess.Popen(
            [str(interpreter), str(Path(base_dir) / "tools" / "overlord_splash.py"),
             "--log", str(log_path), "--state", str(_state_path),
             "--log-offset", str(offset), "--parent-pid", str(os.getpid())],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            close_fds=True,
        )
    except OSError:
        pass  # no splash is not a start-up failure
