"""One source of truth for the Overlord version string.

The version is declared once, in ``pyproject.toml``. This module resolves it at
runtime in three steps, each a fallback for the last:

  1. ``pyproject.toml`` sitting next to this source tree — if it is there, it is
     the truth about the code actually being imported,
  2. installed package metadata, for a wheel with no source tree beside it,
  3. a hardcoded constant, so a packaging accident degrades to a stale number
     rather than to a crash on startup.

Order matters, and pyproject deliberately wins. Overlord normally runs straight
from a checkout with an editable install, and ``overlord_bridge.egg-info`` there
is only as fresh as the last ``pip install -e .`` — it reported 0.1.0 for four
tagged releases. The file you edit must be the file that is believed.

The short git revision is read straight out of ``.git`` rather than by shelling
out: ``git`` is often absent from a service's PATH on Windows, and startup must
not wait on a subprocess.
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("overlord.version")

PACKAGE_NAME = "overlord-bridge"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Last resort only, for a build with neither metadata nor a source tree. Bump
# it with pyproject.toml — test_version.py fails if the two drift apart, which
# is how 0.1.0 once survived four tagged releases.
FALLBACK_VERSION = "1.0.24"


def _from_metadata() -> str | None:
    try:
        from importlib import metadata

        return metadata.version(PACKAGE_NAME)
    except Exception:  # noqa: BLE001 - not installed, or metadata is unreadable
        return None


def _from_pyproject() -> str | None:
    path = PROJECT_ROOT / "pyproject.toml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    in_project = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("["):
            in_project = line == "[project]"
            continue
        if in_project and line.startswith("version"):
            _, _, value = line.partition("=")
            return value.strip().strip('"').strip("'") or None
    return None


def base_version() -> str:
    return _from_pyproject() or _from_metadata() or FALLBACK_VERSION


def git_revision(short: int = 7) -> str | None:
    """The checked-out commit's short sha, or None outside a git checkout."""
    git_dir = PROJECT_ROOT / ".git"
    try:
        if git_dir.is_file():
            # A worktree or submodule: .git is a file pointing at the real dir.
            pointer = git_dir.read_text(encoding="utf-8").strip()
            if pointer.startswith("gitdir:"):
                candidate = Path(pointer.split(":", 1)[1].strip())
                git_dir = (
                    candidate if candidate.is_absolute() else PROJECT_ROOT / candidate
                )
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not head.startswith("ref:"):
        return head[:short] or None
    ref = head.split(":", 1)[1].strip()
    try:
        return (git_dir / ref).read_text(encoding="utf-8").strip()[:short] or None
    except OSError:
        pass
    # A repo that has been `git gc`'d keeps refs in packed-refs, not as files.
    try:
        for line in (git_dir / "packed-refs").read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or " " not in line:
                continue
            sha, _, name = line.partition(" ")
            if name.strip() == ref:
                return sha[:short] or None
    except OSError:
        pass
    return None


def version_string() -> str:
    """``0.1.0`` in a release, ``0.1.0+2576523`` in a checkout."""
    revision = git_revision()
    return f"{base_version()}+{revision}" if revision else base_version()


def display_version() -> str:
    """The human-facing form used in Telegram, the tray, and the console."""
    return f"v{version_string()}"


__version__ = base_version()
