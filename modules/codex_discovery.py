"""Locate the Codex CLI consistently for brains, workers, and launchers."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def resolve_codex_binary(configured: str = "codex") -> str:
    """Return a usable Codex executable path when one can be discovered."""
    setting = (configured or "codex").strip()
    candidate = Path(setting).expanduser()
    if candidate.is_absolute() and candidate.is_file():
        return str(candidate.resolve())

    command = shutil.which(setting)
    if command:
        return str(Path(command).resolve())

    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            root = Path(local_app_data) / "OpenAI" / "Codex" / "bin"
            try:
                bundled = sorted(
                    root.rglob("codex.exe"),
                    key=lambda path: path.stat().st_mtime,
                    reverse=True,
                )
            except OSError:
                bundled = []
            if bundled:
                return str(bundled[0].resolve())
    return setting
