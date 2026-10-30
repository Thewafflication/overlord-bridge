"""Bounded, read-only Git evidence for independent worker completion review."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable

from modules.command_activity import redact_text


async def _git(folder: Path, *args: str, limit: int = 32000) -> tuple[str, bool, bool]:
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "--no-pager", "--literal-pathspecs", *args, cwd=folder,
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL)
        async def read():
            data = bytearray()
            while len(data) <= limit:
                chunk = await proc.stdout.read(min(8192, limit + 1 - len(data)))
                if not chunk:
                    code = await proc.wait()
                    return bytes(data), False, code == 0
                data.extend(chunk)
            return bytes(data[:limit]), True, False
        data, truncated, ok = await asyncio.wait_for(read(), 5)
        return data.decode("utf-8", errors="replace"), truncated, ok
    except (OSError, asyncio.TimeoutError):
        return "", False, False
    finally:
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()


async def baseline(folder: Path, allowed: Callable[[Path], bool]) -> dict:
    if not (folder / ".git").exists():
        return {"available": False, "reason": "worker folder is not a Git root"}
    head, _, ok = await _git(folder, "rev-parse", "--verify", "HEAD")
    head = head.strip()
    if not ok or len(head) not in (40, 64) or any(c not in "0123456789abcdef" for c in head):
        return {"available": False, "reason": "initial HEAD unavailable"}
    paths, partial = await _paths(folder, head, allowed)
    return {"available": True, "head": head, "preexisting_paths": [p for p, _ in paths],
            "initial_paths_partial": partial}


async def _paths(folder: Path, head: str, allowed: Callable[[Path], bool]):
    changed, cut, ok = await _git(folder, "diff", "--no-renames", "--name-only", "-z", head, "--", ".")
    new, cut_new, ok_new = await _git(folder, "ls-files", "--others", "--exclude-standard", "-z", "--", ".")
    rows = [(p, False) for p in changed.split("\0") if p]
    rows += [(p, True) for p in new.split("\0") if p]
    result = []
    partial = cut or cut_new or not ok or not ok_new
    for name, untracked in rows:
        path = folder / name
        # Filter before either asking Git for content or opening an untracked file.
        if not allowed(path) or path.suffix.lower() in {".log", ".mkv", ".mp4"}:
            partial = True
            continue
        if len(result) >= 40:
            partial = True
            break
        result.append((name, untracked))
    return result, partial


async def evidence(folder: Path, initial: dict, allowed: Callable[[Path], bool]) -> dict:
    if not initial.get("available"):
        return dict(initial)
    head, cut, ok = await _git(folder, "rev-parse", "--verify", "HEAD")
    rows, partial = await _paths(folder, initial["head"], allowed)
    result = {"available": ok, "initial_head": initial["head"], "current_head": head.strip(),
              "preexisting_paths": initial["preexisting_paths"], "files": [],
              "partial": partial or cut or initial["initial_paths_partial"]}
    budget = 24000
    for name, untracked in rows:
        if budget <= 0:
            result["partial"] = True
            break
        cap = min(8000, budget)
        if untracked:
            try:
                with (folder / name).open("rb") as stream:
                    data = stream.read(cap + 1)
                text = data[:cap].decode("utf-8") if b"\0" not in data else "[binary file]"
                truncated = len(data) > cap
            except (OSError, UnicodeError):
                text, truncated = "[unreadable or binary file]", True
        else:
            text, truncated, read_ok = await _git(folder, "diff", "--no-renames", "--no-ext-diff", "--no-textconv",
                "--unified=3", initial["head"], "--", name, limit=cap)
            if not read_ok and not truncated:
                text, truncated = "[diff unavailable]", True
        if (folder / name).is_dir():
            text += "\n[nested repository contents not inspected]"
            truncated = True
        text = redact_text(text)[:cap]
        result["files"].append({"path": name, "untracked": untracked, "content": text,
                                "truncated": truncated})
        result["partial"] |= truncated
        budget -= len(text)
    return result
