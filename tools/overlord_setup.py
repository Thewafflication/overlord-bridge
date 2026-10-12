"""Overlord setup window: NVIDIA / OpenRouter API keys for the free-model brain.

Keys are typed into this window by the user and written to the bridge's ``.env``;
nothing is sent anywhere except to the provider, and only when "Test" is pressed.
After saving, a running bridge is asked to reload them (no restart needed).
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.commands import _decode_dotenv, set_env_value  # noqa: E402
from modules.version import display_version  # noqa: E402

NVIDIA_KEY = "OVERLORD_WORKER_NVIDIA_API_KEY"
OPENROUTER_KEY = "OVERLORD_FREE_OPENROUTER_API_KEY"
OPENROUTER_ENABLED = "OVERLORD_FREE_OPENROUTER_ENABLED"
NVIDIA_MODELS_URL = "https://integrate.api.nvidia.com/v1/models"
OPENROUTER_KEY_URL = "https://openrouter.ai/api/v1/auth/key"
NVIDIA_KEYS_PAGE = "https://build.nvidia.com/settings/api-keys"
OPENROUTER_KEYS_PAGE = "https://openrouter.ai/settings/keys"


def read_env(path: Path, names: tuple[str, ...]) -> dict[str, str]:
    """Current values of *names* in a dotenv file (last assignment wins)."""
    try:
        text = _decode_dotenv(path.read_bytes())
    except OSError:
        return {}
    found: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() in names:
            found[key.strip()] = value.strip().strip('"').strip("'")
    return found


def mask(key: str) -> str:
    """Show enough of a key to recognise it, never enough to use it."""
    key = key.strip()
    if not key:
        return "not set"
    if len(key) <= 10:
        return "•" * len(key)
    return f"{key[:5]}…{key[-4:]}"


def check_nvidia_format(key: str) -> str | None:
    """A problem with the shape of an NVIDIA key, or None if it looks right."""
    key = key.strip()
    if not key:
        return "Enter a key first."
    if any(ch.isspace() for ch in key):
        return "The key contains spaces or line breaks; paste only the key itself."
    if not key.startswith("nvapi-"):
        return "NVIDIA API keys start with “nvapi-”."
    if len(key) < 20:
        return "That key looks too short."
    return None


def _get(url: str, key: str, timeout: float) -> tuple[int, str]:
    request = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, (exc.read() or b"").decode("utf-8", errors="replace")


def probe_key(url: str, key: str, label: str, timeout: float = 15.0) -> tuple[bool, str]:
    """Ask the provider whether *key* works. Returns (ok, human message)."""
    try:
        status, body = _get(url, key.strip(), timeout)
    except (OSError, urllib.error.URLError) as exc:
        return False, f"Could not reach {label}: {getattr(exc, 'reason', exc)}"
    if status == 200:
        return True, f"{label} accepted the key."
    if status in (401, 403):
        return False, f"{label} rejected the key (HTTP {status}). Check it was copied completely."
    if status == 429:
        return True, f"{label} is rate limiting right now, but the key was recognised."
    return False, f"{label} answered HTTP {status}."


def save_settings(env_path: Path, values: dict[str, str | None]) -> None:
    """Write each name; ``None`` leaves it alone, ``""`` clears it."""
    for name, value in values.items():
        if value is not None:
            set_env_value(env_path, name, value.strip())


def request_reload(command_path: Path | None) -> bool:
    """Ask a running bridge to re-read the keys (atomic write of its command file)."""
    if command_path is None:
        return False
    try:
        command_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = command_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"action": "reload_env", "at": time.time_ns()}),
                             encoding="utf-8")
        temporary.replace(command_path)
    except OSError:
        return False
    return True


class SetupWindow:
    def __init__(self, env_path: Path, command_path: Path | None) -> None:
        self.env_path, self.command_path = env_path, command_path
        current = read_env(env_path, (NVIDIA_KEY, "NVIDIA_API_KEY", OPENROUTER_KEY,
                                      "OVERLORD_WORKER_OPENROUTER_API_KEY", OPENROUTER_ENABLED))
        self.saved_nvidia = current.get(NVIDIA_KEY) or current.get("NVIDIA_API_KEY", "")
        self.saved_openrouter = (current.get(OPENROUTER_KEY)
                                 or current.get("OVERLORD_WORKER_OPENROUTER_API_KEY", ""))
        enabled = current.get(OPENROUTER_ENABLED, "1").strip().lower() not in ("0", "false", "no", "off")

        self.root = tk.Tk()
        self.root.title(f"Overlord Setup — {display_version()}")
        self.root.configure(bg="#111827")
        self.root.resizable(False, False)
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        for name, fg in (("Setup.TLabel", "#e5e7eb"), ("Muted.TLabel", "#94a3b8"),
                         ("Setup.TCheckbutton", "#e5e7eb")):
            style.configure(name, background="#111827", foreground=fg)
        style.configure("Setup.TFrame", background="#111827")

        outer = ttk.Frame(self.root, style="Setup.TFrame", padding=16)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Free-model API keys", style="Setup.TLabel",
                  font=("Segoe UI Semibold", 13)).grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(outer, style="Muted.TLabel", wraplength=520, justify="left",
                  text="Used by the free chat brain (/brain free). Keys are stored in this "
                       "install's .env file and sent only to the provider.").grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(2, 12))

        self.nvidia = self._key_row(outer, 2, "NVIDIA NIM", self.saved_nvidia,
                                    self.test_nvidia, NVIDIA_KEYS_PAGE)
        self.openrouter = self._key_row(outer, 5, "OpenRouter", self.saved_openrouter,
                                        self.test_openrouter, OPENROUTER_KEYS_PAGE)
        self.use_openrouter = tk.BooleanVar(value=enabled)
        ttk.Checkbutton(outer, text="Use OpenRouter free models (chat is sent to the model "
                                    "provider)", variable=self.use_openrouter,
                        style="Setup.TCheckbutton").grid(row=8, column=0, columnspan=4,
                                                         sticky="w", pady=(8, 0))
        self.status = tk.StringVar(value="Leave a key blank to keep the saved one.")
        ttk.Label(outer, textvariable=self.status, style="Muted.TLabel", wraplength=520,
                  justify="left").grid(row=9, column=0, columnspan=4, sticky="w", pady=(12, 0))
        buttons = ttk.Frame(outer, style="Setup.TFrame")
        buttons.grid(row=10, column=0, columnspan=4, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Save", command=self.save).pack(side="right")
        ttk.Button(buttons, text="Close", command=self.root.destroy).pack(side="right", padx=8)

    def _key_row(self, parent, row, label, saved, tester, page):
        ttk.Label(parent, text=label, style="Setup.TLabel").grid(row=row, column=0, sticky="w")
        ttk.Label(parent, text=f"saved: {mask(saved)}", style="Muted.TLabel").grid(
            row=row, column=1, columnspan=3, sticky="w", padx=8)
        entry = ttk.Entry(parent, width=52, show="•")
        entry.grid(row=row + 1, column=0, columnspan=2, sticky="we", pady=(2, 0))
        show = tk.BooleanVar(value=False)
        ttk.Checkbutton(parent, text="Show", variable=show, style="Setup.TCheckbutton",
                        command=lambda: entry.configure(show="" if show.get() else "•")).grid(
            row=row + 1, column=2, padx=6)
        ttk.Button(parent, text="Test", command=lambda: tester(entry.get() or saved)).grid(
            row=row + 1, column=3)
        link = ttk.Label(parent, text=f"Get a key: {page}", style="Muted.TLabel", cursor="hand2")
        link.grid(row=row + 2, column=0, columnspan=4, sticky="w", pady=(2, 8))
        link.bind("<Button-1>", lambda _e: self._open(page))
        return entry

    def _open(self, url: str) -> None:
        import webbrowser

        webbrowser.open(url)

    # -- actions -------------------------------------------------------------
    def _background(self, work: Callable[[], tuple[bool, str]]) -> None:
        self.status.set("Testing…")

        def run() -> None:
            ok, message = work()
            self.root.after(0, lambda: self.status.set(("✓ " if ok else "✗ ") + message))

        threading.Thread(target=run, daemon=True).start()

    def test_nvidia(self, key: str) -> None:
        problem = check_nvidia_format(key)
        if problem:
            self.status.set("✗ " + problem)
            return
        self._background(lambda: probe_key(NVIDIA_MODELS_URL, key, "NVIDIA"))

    def test_openrouter(self, key: str) -> None:
        if not key.strip():
            self.status.set("✗ Enter a key first.")
            return
        self._background(lambda: probe_key(OPENROUTER_KEY_URL, key, "OpenRouter"))

    def save(self) -> None:
        nvidia, openrouter = self.nvidia.get().strip(), self.openrouter.get().strip()
        if nvidia:
            problem = check_nvidia_format(nvidia)
            if problem:
                self.status.set("✗ " + problem)
                return
        values: dict[str, str | None] = {
            NVIDIA_KEY: nvidia or None,
            OPENROUTER_KEY: openrouter or None,
            OPENROUTER_ENABLED: "1" if self.use_openrouter.get() else "0",
        }
        try:
            save_settings(self.env_path, values)
        except OSError as exc:
            messagebox.showerror("Overlord Setup", f"Could not write {self.env_path}:\n{exc}")
            return
        reloaded = request_reload(self.command_path)
        self.status.set("✓ Saved. " + (
            "A running Overlord will pick the keys up within a second or two."
            if reloaded else "Restart Overlord to apply them."))
        for entry in (self.nvidia, self.openrouter):
            entry.delete(0, "end")

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    default_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--env", type=Path, default=default_root / ".env")
    parser.add_argument("--command", type=Path, default=default_root / "run" / "console-command.json")
    args = parser.parse_args()
    SetupWindow(args.env, args.command).run()


if __name__ == "__main__":
    main()
