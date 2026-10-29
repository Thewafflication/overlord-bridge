"""Validated project and permission settings shared by the setup UI and bridge."""
from __future__ import annotations

import json
from pathlib import Path

PROJECT_FOLDERS = "OVERLORD_PROJECT_FOLDERS"
PROJECT_ROOTS = "OVERLORD_PROJECTS_ROOTS"
AUTO_APPROVE = "OVERLORD_AUTO_APPROVE"
AUTO_EDITS = "OVERLORD_CLAUDE_AUTO_APPROVE_EDITS"
WORK_APPROVAL = "OVERLORD_FREE_WORK_APPROVAL"
PERMISSION_LEVEL = "OVERLORD_PERMISSION_LEVEL"
PERMISSION_LEVELS = ("ask", "safe", "full")
SETTING_NAMES = (PROJECT_FOLDERS, PROJECT_ROOTS, "OVERLORD_PROJECTS_ROOT",
                 AUTO_APPROVE, AUTO_EDITS, WORK_APPROVAL, PERMISSION_LEVEL)


def default_project_roots() -> str:
    """Initial editable roots; an explicitly saved empty list disables them."""
    return json.dumps([str(p) for p in (Path.home() / "Projects", Path.home() / "Documents")
                       if p.is_dir()])


def permission_level(value: str | None, *, legacy_auto: bool = False) -> str:
    if value is None:
        return "full" if legacy_auto else "safe"
    normalized = value.strip().lower()
    return normalized if normalized in PERMISSION_LEVELS else "ask"


def decode_paths(value: str) -> list[Path]:
    if not value.strip():
        return []
    values = json.loads(value)
    if not isinstance(values, list) or any(not isinstance(p, str) for p in values):
        raise ValueError("Project folders must be a JSON list of paths.")
    return validate_paths(values)


def validate_paths(values: list[str]) -> list[Path]:
    from modules.brain import PermissionGate

    paths: list[Path] = []
    for value in values:
        if not value.strip():
            continue
        path = Path(value.strip()).expanduser()
        if not path.is_absolute():
            raise ValueError(f"Choose an absolute folder path: {value}")
        path = path.resolve()
        if PermissionGate.offlimits_match([str(path)]):
            raise ValueError("An off-limits folder cannot be added as a project.")
        if path == Path.home().resolve() or path == Path(path.anchor):
            raise ValueError("Choose a specific project folder, not home or a drive root.")
        if not path.is_dir():
            raise ValueError(f"Folder does not exist: {path}")
        if path not in paths:
            paths.append(path)
    return paths


def encode_paths(values: list[str]) -> str:
    return json.dumps([str(p) for p in validate_paths(values)], ensure_ascii=False)
