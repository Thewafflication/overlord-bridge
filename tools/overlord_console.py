"""Tk rich-text live console for the Windows Overlord tray application."""

from __future__ import annotations

import argparse
import os
import tkinter as tk
from pathlib import Path
from tkinter import ttk

POLL_MS = 300
INITIAL_TAIL_BYTES = 160_000
MAX_WIDGET_LINES = 5_000


def level_for_line(line: str) -> str:
    """Return the rich-text tag for one standard Overlord log line."""
    for level in ("ERROR", "WARNING", "DEBUG", "INFO"):
        if f" {level} " in line:
            return level.lower()
    return "plain"


class OverlordConsole:
    def __init__(self, log_path: Path, signal_path: Path) -> None:
        self.log_path = log_path
        self.signal_path = signal_path
        self.offset = 0
        self.file_identity: tuple[int, int, int] | None = None
        self.signal_mtime = 0

        self.root = tk.Tk()
        self.root.title("Overlord Console")
        self.root.geometry("1000x620")
        self.root.minsize(640, 360)
        self.root.configure(bg="#111827")
        self.root.protocol("WM_DELETE_WINDOW", self.hide)

        self.autoscroll = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value=f"Live log: {self.log_path}")
        self._build_ui()
        self._configure_tags()
        self._seek_initial_tail()
        self.root.after(POLL_MS, self.poll)

    def _build_ui(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Console.TFrame", background="#111827")
        style.configure(
            "Console.TLabel", background="#111827", foreground="#94a3b8"
        )
        style.configure(
            "Console.TCheckbutton", background="#111827", foreground="#e5e7eb"
        )

        outer = ttk.Frame(self.root, style="Console.TFrame", padding=10)
        outer.pack(fill="both", expand=True)
        toolbar = ttk.Frame(outer, style="Console.TFrame")
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Label(
            toolbar,
            text="OVERLORD",
            style="Console.TLabel",
            font=("Segoe UI Semibold", 12),
        ).pack(side="left")
        ttk.Button(toolbar, text="Clear", command=self.clear).pack(side="right")
        ttk.Button(toolbar, text="Copy All", command=self.copy_all).pack(
            side="right", padx=6
        )
        ttk.Button(toolbar, text="Hide", command=self.hide).pack(side="right")
        ttk.Checkbutton(
            toolbar,
            text="Autoscroll",
            variable=self.autoscroll,
            style="Console.TCheckbutton",
        ).pack(side="right", padx=10)

        text_frame = ttk.Frame(outer, style="Console.TFrame")
        text_frame.pack(fill="both", expand=True)
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical")
        scrollbar.pack(side="right", fill="y")
        self.text = tk.Text(
            text_frame,
            bg="#07101f",
            fg="#dbeafe",
            insertbackground="#ffffff",
            selectbackground="#1d4ed8",
            relief="flat",
            padx=12,
            pady=10,
            wrap="none",
            font=("Cascadia Mono", 10),
            yscrollcommand=scrollbar.set,
            state="disabled",
        )
        self.text.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=self.text.yview)
        ttk.Label(outer, textvariable=self.status, style="Console.TLabel").pack(
            fill="x", pady=(7, 0)
        )

    def _configure_tags(self) -> None:
        self.text.tag_configure("error", foreground="#fb7185")
        self.text.tag_configure("warning", foreground="#fbbf24")
        self.text.tag_configure("info", foreground="#bfdbfe")
        self.text.tag_configure("debug", foreground="#64748b")
        self.text.tag_configure("plain", foreground="#d1d5db")

    def _seek_initial_tail(self) -> None:
        try:
            size = self.log_path.stat().st_size
        except OSError:
            return
        self.offset = max(0, size - INITIAL_TAIL_BYTES)

    def _append(self, content: str) -> None:
        if not content:
            return
        self.text.configure(state="normal")
        for line in content.splitlines(keepends=True):
            self.text.insert("end", line, level_for_line(line))
        line_count = int(self.text.index("end-1c").split(".", 1)[0])
        if line_count > MAX_WIDGET_LINES:
            self.text.delete("1.0", f"{line_count - MAX_WIDGET_LINES}.0")
        self.text.configure(state="disabled")
        if self.autoscroll.get():
            self.text.see("end")

    def _read_new_log(self) -> None:
        try:
            stat = self.log_path.stat()
        except OSError:
            self.status.set(f"Waiting for log: {self.log_path}")
            return
        identity = (stat.st_dev, stat.st_ino, stat.st_ctime_ns)
        if self.file_identity is not None and identity != self.file_identity:
            self.offset = 0
        if stat.st_size < self.offset:
            self.offset = 0
        self.file_identity = identity
        try:
            with self.log_path.open("r", encoding="utf-8", errors="replace") as stream:
                stream.seek(self.offset)
                content = stream.read()
                self.offset = stream.tell()
        except OSError as exc:
            self.status.set(f"Log read error: {exc}")
            return
        self._append(content)
        self.status.set(f"Live • {self.log_path} • PID {os.getpid()}")

    def _check_signal(self) -> None:
        try:
            mtime = self.signal_path.stat().st_mtime_ns
        except OSError:
            return
        if mtime == self.signal_mtime:
            return
        self.signal_mtime = mtime
        try:
            action = self.signal_path.read_text(encoding="utf-8").strip().lower()
        except OSError:
            return
        if action == "hide":
            self.hide()
        elif action == "show":
            self.show()

    def poll(self) -> None:
        self._read_new_log()
        self._check_signal()
        self.root.after(POLL_MS, self.poll)

    def show(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(200, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()

    def hide(self) -> None:
        self.root.withdraw()

    def clear(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def copy_all(self) -> None:
        content = self.text.get("1.0", "end-1c")
        self.root.clipboard_clear()
        self.root.clipboard_append(content)

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--signal", type=Path, required=True)
    args = parser.parse_args()
    OverlordConsole(args.log, args.signal).run()


if __name__ == "__main__":
    main()
