"""Cooperating Git index protection for pre-existing untracked owner files.

This is not a sandbox: alternate indexes, direct Git database writes and child
processes that outlive a tool call are outside the contract. No owner file content
is read. Ordinary commands hold Git's index.lock only for their execution.
"""
from __future__ import annotations

import os
import re
import shlex
from contextlib import asynccontextmanager
from pathlib import Path

from modules.worker_changes import _git


class WorkerIndexGuard:
    def __init__(self):
        self.protected = set()
        self.index = None

    async def acquire(self, folder, allowed, owned_paths=()):
        if not (folder / ".git").exists():
            return
        names, cut, ok = await _git(folder, "ls-files", "--others", "--exclude-standard", "-z", limit=2_000_000)
        if cut or not ok or "\ufffd" in names:
            raise RuntimeError("owner Git index inventory unavailable")
        owned = {os.path.normcase(str((folder / name).resolve())) for name in owned_paths}
        self.protected = {name for name in names.split("\0") if name
                          and allowed(folder / name)
                          and os.path.normcase(str((folder / name).resolve())) not in owned}
        if not self.protected:
            return
        index, cut, ok = await _git(folder, "rev-parse", "--git-path", "index")
        if cut or not ok or not index.strip():
            raise RuntimeError("owner Git index location unavailable")
        self.index = (folder / index.strip()).resolve()

    def context(self):
        return {"preexisting_untracked_owner_paths": sorted(self.protected)[:100],
                "count": len(self.protected), "paths_partial": len(self.protected) > 100,
                "rule": "These are owner files, not worker-created changes. Do not stage or commit them. "
                        "Read-only validation needs no commit. An unrelated dirty tree is allowed. "
                        "A model reviewer cannot grant ownership or require a clean tree."}

    @asynccontextmanager
    async def command(self, folder, tool, arguments):
        if not self.protected or tool not in {"run_command", "run_python"}:
            yield None
            return
        error = {"ok": False, "error": "owner_git_index_protected",
                 "message": "Pre-existing untracked owner files must stay outside commits. "
                            "Use a single explicit git add with only owned file paths, then a separate git commit. "
                            "Do not bypass index protection or commit owner files to satisfy model review."}
        command = arguments.get("command", arguments.get("cmd", "")) if tool == "run_command" else ""
        # Only simple literal Git operations may run without the temporary lock.
        # Parsing is mechanical shell syntax, never conversational intent.
        tokens = []
        if command and not re.search(r"[&|;<>\r\n`$%!]", command):
            try:
                tokens = [t.strip('\"') for t in shlex.split(command, posix=False)]
            except ValueError:
                pass
        direct = len(tokens) >= 2 and tokens[0].lower() in {"git", "git.exe"}
        unlock = False
        if direct and tokens[1] == "add":
            paths = tokens[2:]
            if paths[:1] == ["--"]:
                paths = paths[1:]
            targets = {os.path.normcase(str((folder / p).resolve())) for p in paths}
            protected = {os.path.normcase(str((folder / p).resolve())) for p in self.protected}
            unlock = bool(paths) and all(not p.startswith("-") and not any(c in p for c in "*?[]")
                                         and (folder / p).is_file()
                                         and (folder / p).resolve().is_relative_to(folder.resolve()) for p in paths)
            unlock = unlock and not targets.intersection(protected)
            if not unlock:
                yield error
                return
        elif direct and tokens[1] == "commit":
            if not (len(tokens) == 2 or (len(tokens) == 4 and tokens[2] in {"-m", "--message"})):
                yield error
                return
            names, cut, ok = await _git(folder, "ls-files", "--cached", "-z", limit=2_000_000)
            staged = set(names.split("\0"))
            if cut or not ok or self.protected.intersection(staged):
                yield error
                return
            unlock = True
        if unlock:
            yield None
            return
        lock = Path(str(self.index) + ".lock")
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except OSError:
            yield error
            return
        try:
            yield None
        finally:
            os.close(fd)
            lock.unlink()
