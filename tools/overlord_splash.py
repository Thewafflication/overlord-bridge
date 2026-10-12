"""Start-up splash for the Overlord bridge: stage, progress and a live log tail."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.version import display_version  # noqa: E402

POLL_MS = 150
MAX_LINES = 400
READY_LINGER_MS = 700
BENIGN_FAILURE_LINGER_MS = 4000
GIVE_UP_SECONDS = 180.0
# Failures that are expected outcomes, not something to stare at.
BENIGN_FAILURES = ("already running",)


def read_state(path: Path) -> dict:
    """The latest state, or an empty dict while the bridge has not written one."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return True  # unknown parent: do not close on that basis
    if sys.platform == "win32":
        import ctypes

        process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED
        if not process:
            return False
        try:
            code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(process, ctypes.byref(code))
            return bool(ok) and code.value == 259  # STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(process)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def tail_new(path: Path, offset: int) -> tuple[list[str], int]:
    """Complete log lines appended after *offset*; restarts if the file rotated."""
    try:
        size = path.stat().st_size
    except OSError:
        return [], offset
    if size < offset:
        offset = 0
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            chunk = handle.read()
    except OSError:
        return [], offset
    end = chunk.rfind(b"\n")
    if end < 0:
        return [], offset
    text = chunk[: end + 1].decode("utf-8", errors="replace")
    return text.splitlines(), offset + end + 1


def decide(state: dict, *, elapsed: float, parent_alive: bool,
           give_up: float = GIVE_UP_SECONDS) -> tuple[str, str]:
    """What the splash should do now: (action, message).

    Actions: ``wait`` (keep showing), ``ready`` (close soon), ``failed`` (show the
    problem), ``benign`` (an expected stop such as a second instance).
    """
    status = state.get("state")
    if status == "ready":
        return "ready", "Online"
    if status == "failed":
        detail = str(state.get("detail") or state.get("stage") or "Start-up failed")
        if any(marker in detail.lower() for marker in BENIGN_FAILURES):
            return "benign", detail
        return "failed", detail
    if not parent_alive:
        return "failed", "Overlord stopped before it finished starting. See the log above."
    if elapsed > give_up:
        return "failed", f"Still not online after {int(give_up)}s. See the log above."
    return "wait", str(state.get("stage") or "Starting…")


def level_for_line(line: str) -> str:
    for level in ("ERROR", "WARNING", "DEBUG", "INFO"):
        if f" {level} " in line:
            return level.lower()
    return "plain"


class Splash:
    def __init__(self, log_path: Path, state_path: Path, offset: int, parent_pid: int) -> None:
        self.log_path, self.state_path = log_path, state_path
        self.offset, self.parent_pid = offset, parent_pid
        self.started = time.monotonic()
        self.finished = False

        self.root = tk.Tk()
        self.root.title("Overlord")
        self.root.overrideredirect(True)
        self.root.configure(bg="#111827")
        self.root.attributes("-topmost", True)
        width, height = 560, 330
        x = (self.root.winfo_screenwidth() - width) // 2
        y = (self.root.winfo_screenheight() - height) // 3
        self.root.geometry(f"{width}x{height}+{x}+{y}")

        outer = tk.Frame(self.root, bg="#111827", highlightthickness=1,
                         highlightbackground="#334155", padx=18, pady=14)
        outer.pack(fill="both", expand=True)
        header = tk.Frame(outer, bg="#111827")
        header.pack(fill="x")
        tk.Label(header, text="OVERLORD", bg="#111827", fg="#e5e7eb",
                 font=("Segoe UI Semibold", 16)).pack(side="left")
        tk.Label(header, text=display_version(), bg="#111827", fg="#64748b",
                 font=("Segoe UI", 9)).pack(side="left", padx=(10, 0), pady=(6, 0))
        self.elapsed = tk.StringVar(value="0s")
        tk.Label(header, textvariable=self.elapsed, bg="#111827", fg="#64748b",
                 font=("Segoe UI", 9)).pack(side="right", pady=(6, 0))

        self.stage = tk.StringVar(value="Starting…")
        self.stage_label = tk.Label(outer, textvariable=self.stage, bg="#111827", fg="#bfdbfe",
                                    font=("Segoe UI", 11), anchor="w")
        self.stage_label.pack(fill="x", pady=(10, 6))
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Splash.Horizontal.TProgressbar", troughcolor="#1e293b",
                        background="#3b82f6", bordercolor="#111827", lightcolor="#3b82f6",
                        darkcolor="#3b82f6")
        self.bar = ttk.Progressbar(outer, mode="indeterminate",
                                   style="Splash.Horizontal.TProgressbar")
        self.bar.pack(fill="x")
        self.bar.start(12)

        frame = tk.Frame(outer, bg="#07101f")
        frame.pack(fill="both", expand=True, pady=(10, 0))
        self.text = tk.Text(frame, bg="#07101f", fg="#d1d5db", relief="flat", wrap="none",
                            font=("Cascadia Mono", 8), padx=8, pady=6, state="disabled",
                            height=8)
        self.text.pack(fill="both", expand=True)
        for tag, colour in (("error", "#fb7185"), ("warning", "#fbbf24"), ("info", "#93c5fd"),
                            ("debug", "#64748b"), ("plain", "#d1d5db")):
            self.text.tag_configure(tag, foreground=colour)
        self.close_button = ttk.Button(outer, text="Close", command=self.root.destroy)
        self.root.after(POLL_MS, self.poll)

    def _append(self, lines: list[str]) -> None:
        if not lines:
            return
        self.text.configure(state="normal")
        for line in lines:
            self.text.insert("end", line + "\n", level_for_line(line))
        count = int(self.text.index("end-1c").split(".", 1)[0])
        if count > MAX_LINES:
            self.text.delete("1.0", f"{count - MAX_LINES}.0")
        self.text.configure(state="disabled")
        self.text.see("end")

    def poll(self) -> None:
        lines, self.offset = tail_new(self.log_path, self.offset)
        self._append(lines)
        elapsed = time.monotonic() - self.started
        self.elapsed.set(f"{int(elapsed)}s")
        if self.finished:
            return
        state = read_state(self.state_path)
        if self.parent_pid and state.get("pid") != self.parent_pid:
            state = {}  # left over from an earlier run; wait for this one's first report
        action, message = decide(
            state, elapsed=elapsed, parent_alive=pid_alive(self.parent_pid)
        )
        if action == "wait":
            self.stage.set(message)
        elif action == "ready":
            self.finish("Online", "#86efac", READY_LINGER_MS)
            return
        elif action == "benign":
            self.finish(message, "#fbbf24", BENIGN_FAILURE_LINGER_MS)
            return
        else:
            self.finish(message, "#fb7185", None)
            return
        self.root.after(POLL_MS, self.poll)

    def finish(self, message: str, colour: str, close_after_ms: int | None) -> None:
        self.finished = True
        self.bar.stop()
        self.stage.set(message)
        self.stage_label.configure(fg=colour, wraplength=520, justify="left")
        if close_after_ms is None:  # a real failure stays until dismissed
            self.close_button.pack(anchor="e", pady=(8, 0))
            self.root.after(POLL_MS, self._keep_tailing)
        else:
            self.root.after(close_after_ms, self.root.destroy)

    def _keep_tailing(self) -> None:
        lines, self.offset = tail_new(self.log_path, self.offset)
        self._append(lines)
        self.root.after(500, self._keep_tailing)

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--log-offset", type=int, default=0)
    parser.add_argument("--parent-pid", type=int, default=0)
    args = parser.parse_args()
    Splash(args.log, args.state, args.log_offset, args.parent_pid).run()


if __name__ == "__main__":
    main()
