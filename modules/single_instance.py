"""Cross-platform OS lock that permits one Overlord bridge per machine user."""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path


class AlreadyRunningError(RuntimeError):
    """Raised when another process already owns the Overlord singleton lock."""


class SingleInstance:
    """An OS-owned lock that is released when the process exits or crashes."""

    def __init__(self, name: str = "overlord-bridge") -> None:
        self.name = re.sub(r"[^A-Za-z0-9_.-]", "-", name)
        self._handle: int | None = None
        self._fd: int | None = None

    def acquire(self) -> None:
        if self._handle is not None or self._fd is not None:
            return
        if sys.platform == "win32":
            self._acquire_windows()
        else:
            self._acquire_posix()

    def _acquire_windows(self) -> None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_mutex = kernel32.CreateMutexW
        create_mutex.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        create_mutex.restype = wintypes.HANDLE
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = (wintypes.HANDLE,)
        close_handle.restype = wintypes.BOOL

        # Local\ spans all processes in this Windows logon session. Unlike a
        # PID file, the kernel releases it automatically after a hard crash.
        handle = create_mutex(None, True, f"Local\\{self.name}")
        if not handle:
            raise OSError(ctypes.get_last_error(), "Could not create singleton mutex")
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            close_handle(handle)
            raise AlreadyRunningError("another Overlord instance is already running")
        self._handle = int(handle)

    def _acquire_posix(self) -> None:
        import fcntl

        path = Path(tempfile.gettempdir()) / f"{self.name}.lock"
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(fd)
            raise AlreadyRunningError(
                "another Overlord instance is already running"
            ) from exc
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode("ascii"))
        self._fd = fd

    def release(self) -> None:
        if self._handle is not None:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.ReleaseMutex.argtypes = (wintypes.HANDLE,)
            kernel32.ReleaseMutex.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel32.CloseHandle.restype = wintypes.BOOL
            kernel32.ReleaseMutex(self._handle)
            kernel32.CloseHandle(self._handle)
            self._handle = None
        if self._fd is not None:
            import fcntl

            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None

    def __enter__(self) -> "SingleInstance":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()
