"""Overlord setup window: API keys, project folders, and approval settings.

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
from tkinter import filedialog, messagebox, ttk
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.commands import _decode_dotenv, set_env_value  # noqa: E402
from modules.version import display_version  # noqa: E402
from modules.gui_settings import (  # noqa: E402
    PROJECT_FOLDERS, PROJECT_ROOTS, AUTO_APPROVE, AUTO_EDITS, WORK_APPROVAL,
    SETTING_NAMES, decode_paths, encode_paths, PERMISSION_LEVEL, PERMISSION_LEVELS, permission_level,
)

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
                                      "OVERLORD_WORKER_OPENROUTER_API_KEY", OPENROUTER_ENABLED) + SETTING_NAMES)
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

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=12, pady=12)
        outer = ttk.Frame(notebook, style="Setup.TFrame", padding=16)
        notebook.add(outer, text="API keys")
        projects = ttk.Frame(notebook, style="Setup.TFrame", padding=16)
        notebook.add(projects, text="Projects")
        self.project_folders = self._folder_list(projects, "Individual project folders",
                                                current.get(PROJECT_FOLDERS, ""))
        self.project_roots = self._folder_list(projects, "Folders containing projects",
                                              current.get(PROJECT_ROOTS, ""))
        self.legacy_root = current.get("OVERLORD_PROJECTS_ROOT", "")
        if self.legacy_root and self.legacy_root not in self.project_roots.get(0, "end"):
            self.project_roots.insert("end", self.legacy_root)
        ttk.Label(projects, style="Muted.TLabel", wraplength=520,
                  text="Add a project itself, or a parent such as source/repos. These folders "
                       "become available to /work and worker dispatch. The current workspace "
                       "and standard Projects/Documents folders remain available.").pack(pady=8)

        permissions = ttk.Frame(notebook, style="Setup.TFrame", padding=16)
        notebook.add(permissions, text="Permissions")
        truth = lambda key: current.get(key, "0").lower() in ("1", "true", "yes", "on")
        self.auto_edits = tk.BooleanVar(value=truth(AUTO_EDITS))
        ttk.Label(permissions, text="Bridge permission level", style="Setup.TLabel").pack(anchor="w", pady=8)
        self.permission_level = ttk.Combobox(permissions, state="readonly", values=PERMISSION_LEVELS)
        self.permission_level.set(permission_level(current.get(PERMISSION_LEVEL), legacy_auto=truth(AUTO_APPROVE)))
        self.permission_level.pack(anchor="w")
        ttk.Label(permissions, style="Muted.TLabel", wraplength=520,
                  text="ask: prompt for actions · safe: approve routine commands (default)\n"
                       "full: approve bridge actions until changed. For timed full access, "
                       "use /permissions full 10 in Telegram.").pack(anchor="w", pady=8)
        ttk.Checkbutton(permissions, text="Auto-approve Claude edits inside its workspace",
                        variable=self.auto_edits, style="Setup.TCheckbutton").pack(anchor="w", pady=8)
        ttk.Label(permissions, text="Free-model project work: ask before", style="Setup.TLabel").pack(anchor="w", pady=8)
        self.work_approval = ttk.Combobox(permissions, state="readonly", values=("all", "commands", "none"))
        self.work_approval.set(current.get(WORK_APPROVAL, "all"))
        self.work_approval.pack(anchor="w")
        ttk.Label(permissions, style="Muted.TLabel", wraplength=520,
                  text="all: writes and commands · commands: shell commands only · none: no prompts.\n"
                       "Off-limits rules still apply. Native engine sandbox and permission rules "
                       "also apply. Session grants can be inspected or revoked in Telegram with /permissions.").pack(anchor="w", pady=12)
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
        ttk.Label(self.root, textvariable=self.status, style="Muted.TLabel", wraplength=520,
                  justify="left").pack(fill="x", padx=16)
        buttons = ttk.Frame(self.root, style="Setup.TFrame")
        buttons.pack(fill="x", padx=16, pady=12)
        ttk.Button(buttons, text="Save", command=self.save).pack(side="right")
        ttk.Button(buttons, text="Close", command=self.root.destroy).pack(side="right", padx=8)

    def _folder_list(self, parent, title: str, saved: str):
        ttk.Label(parent, text=title, style="Setup.TLabel").pack(anchor="w", pady=(8, 2))
        listing = tk.Listbox(parent, width=72, height=5, bg="#172033", fg="#e5e7eb",
                             selectbackground="#1d4ed8", exportselection=False)
        listing.pack(fill="x")
        try:
            paths = decode_paths(saved)
        except (ValueError, OSError, RuntimeError):
            # Preserve saved rows even if a drive is temporarily disconnected.
            try:
                paths = json.loads(saved) if saved else []
            except ValueError:
                paths = []
        if isinstance(paths, list):
            for path in paths:
                if isinstance(path, (str, Path)):
                    listing.insert("end", str(path))
        buttons = ttk.Frame(parent, style="Setup.TFrame")
        buttons.pack(anchor="w", pady=4)
        def add():
            path = filedialog.askdirectory(parent=self.root, title=title)
            if path and path not in listing.get(0, "end"):
                listing.insert("end", path)
        def remove():
            for index in reversed(listing.curselection()):
                listing.delete(index)
        ttk.Button(buttons, text="Add folder…", command=add).pack(side="left")
        ttk.Button(buttons, text="Remove", command=remove).pack(side="left", padx=6)
        return listing

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
            PERMISSION_LEVEL: self.permission_level.get(),
            AUTO_APPROVE: "1" if self.permission_level.get() == "full" else "0",
            AUTO_EDITS: "1" if self.auto_edits.get() else "0",
            WORK_APPROVAL: self.work_approval.get(),
        }
        try:
            values[PROJECT_FOLDERS] = encode_paths(list(self.project_folders.get(0, "end")))
            values[PROJECT_ROOTS] = encode_paths(list(self.project_roots.get(0, "end")))
            # Migrated into the root list, so removing a legacy row really removes it.
            values["OVERLORD_PROJECTS_ROOT"] = ""
        except (ValueError, OSError, RuntimeError) as exc:
            self.status.set(f"✗ {exc}")
            return
        try:
            save_settings(self.env_path, values)
        except OSError as exc:
            messagebox.showerror("Overlord Setup", f"Could not write {self.env_path}:\n{exc}")
            return
        reloaded = request_reload(self.command_path)
        self.status.set("✓ Saved. " + (
            "A running Overlord will pick the settings up within a second or two."
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
