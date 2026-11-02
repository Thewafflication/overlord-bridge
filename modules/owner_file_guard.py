"""Windows deletion protection for owner files present before a free worker starts.

Handles prevent delete/rename, including child-process cleanup, without reading
file contents. In-place writes remain possible: this is not a code sandbox or
an overwrite backup. Committed clean files and worker-created files are exempt.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from modules.worker_changes import _git

MAX_FILES = 20000
MAX_REPOS = 100


class OwnerFileGuard:
    def __init__(self):
        self._handles = []
        self._close = None

    @property
    def count(self):
        return len(self._handles)

    def close(self):
        while self._handles:
            self._close(self._handles.pop())

    async def acquire(self, folder: Path, allowed: Callable[[Path], bool]):
        if os.name != "nt":
            return
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                           wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        self._close = kernel.CloseHandle
        try:
            paths = await _owner_paths(folder, allowed)
            for path in paths:
                # GENERIC_READ is required for mandatory sharing enforcement;
                # metadata-only access does NOT prevent DeleteFile on Windows.
                # No ReadFile call, inheritable handle, or reparse traversal.
                handle = create(str(path), 0x80000000, 3, None, 3, 0x00200080, None)
                if handle in (None, ctypes.c_void_p(-1).value):
                    raise OSError(ctypes.get_last_error(), "cannot protect pre-existing owner file")
                self._handles.append(handle)
        except BaseException:
            self.close()
            raise


async def _owner_paths(folder: Path, allowed: Callable[[Path], bool]) -> list[Path]:
    """Read path metadata only; bounded and fail closed on incomplete enumeration."""
    root = folder.resolve()
    result: set[Path] = set()
    visited: set[Path] = set()

    def add(path):
        # Check every ancestor before resolving: junctions must not lead outside
        # the project or cause traversal of unrelated/forbidden directories.
        if not path.is_relative_to(root):
            raise RuntimeError("owner-file inventory escaped project")
        for parent in path.parents:
            if parent == root:
                break
            if hasattr(parent, "is_junction") and parent.is_junction():
                raise RuntimeError("owner-file inventory traverses a reparse directory")
            if parent.is_symlink():
                raise RuntimeError("owner-file inventory traverses a symbolic directory")
        if allowed(path) and path.is_file() and not path.is_symlink():
            result.add(path)
            if len(result) > MAX_FILES:
                raise RuntimeError("owner-file inventory exceeds protection limit")

    async def git(repo, *args):
        text, cut, ok = await _git(repo, *args, limit=2_000_000)
        if cut or not ok or "\ufffd" in text:
            raise RuntimeError("cannot enumerate all pre-existing owner paths")
        return text

    async def visit(repo):
        if repo in visited:
            return
        visited.add(repo)
        if len(visited) > MAX_REPOS:
            raise RuntimeError("owner-file inventory exceeds repository limit")
        if (repo / ".git").exists():
            for args in (("diff", "--name-only", "--no-renames", "--diff-filter=ACMRT", "-z", "--"),
                         ("diff", "--cached", "--name-only", "--no-renames", "--diff-filter=ACMRT", "-z", "--"),
                         ("ls-files", "--others", "--exclude-standard", "-z", "--")):
                for name in (await git(repo, *args)).split("\0"):
                    if name:
                        candidate = repo / name
                        if not allowed(candidate):
                            continue
                        if candidate.is_dir() and not candidate.is_symlink() and (candidate / ".git").exists():
                            if hasattr(candidate, "is_junction") and candidate.is_junction():
                                raise RuntimeError("nested repository is a reparse directory")
                            await visit(candidate)
                        else:
                            add(candidate)
            # Index metadata locates initialized nested repositories without
            # opening .gitmodules, executing hooks, or fetching anything.
            for entry in (await git(repo, "ls-files", "--stage", "-z")).split("\0"):
                if entry.startswith("160000 ") and "\t" in entry:
                    child = repo / entry.split("\t", 1)[1]
                    if child.is_symlink() or (hasattr(child, "is_junction") and child.is_junction()):
                        raise RuntimeError("nested repository is a reparse directory")
                    if child.is_relative_to(root) and allowed(child) and (child / ".git").exists():
                        await visit(child)
        else:
            # Loose-script projects also contain owner data. Never follow links
            # or descend into the Git database; ignored Git files are exempt.
            def failed_walk(error):
                raise error
            for here, dirs, files in os.walk(repo, followlinks=False, onerror=failed_walk):
                base = Path(here)
                dirs[:] = [d for d in dirs if d != ".git" and allowed(base / d)
                           and not (base / d).is_symlink()
                           and not (hasattr(base / d, "is_junction") and (base / d).is_junction())]
                for name in files:
                    add(base / name)

    await visit(root)
    return sorted(result)
