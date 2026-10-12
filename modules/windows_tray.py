"""Native Windows notification-area lifecycle control for Overlord."""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

from modules.version import display_version

log = logging.getLogger("overlord.tray")
ICON_PATH = Path(__file__).resolve().parent.parent / "assets" / "overlord.png"


class WindowsTray:
    """Run a small pystray icon with a right-click Stop action."""

    def __init__(
        self,
        on_stop: Callable[[], None],
        log_path: Path | None = None,
        status_path: Path | None = None,
        command_path: Path | None = None,
    ) -> None:
        self.on_stop = on_stop
        self.log_path = log_path
        self.status_path = status_path
        self.command_path = command_path
        self.version = display_version()
        self._brain_name = "starting"
        self._icon = None
        self._thread: threading.Thread | None = None
        self._console_process: subprocess.Popen | None = None
        self._console_signal = (
            log_path.parent / "console-window.signal" if log_path is not None else None
        )
        self._console_state = (
            log_path.parent / "console-window.state" if log_path is not None else None
        )

    def start(self, brain_name: str) -> bool:
        if sys.platform != "win32":
            return False
        self._brain_name = brain_name
        try:
            import pystray
            from PIL import Image, ImageDraw
        except ImportError as exc:
            log.warning("Windows tray unavailable; run run-windows.ps1 -Install: %s", exc)
            return False

        if ICON_PATH.exists():
            image = Image.open(ICON_PATH).convert("RGBA")
        else:
            image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.ellipse((4, 4, 60, 60), fill=(34, 90, 190, 255))
            draw.ellipse((16, 16, 48, 48), outline=(255, 255, 255, 255), width=6)

        menu = pystray.Menu(
            pystray.MenuItem(
                lambda item: f"Overlord {self.version} ({self._brain_name})",
                lambda icon, item: None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(self._console_menu_label, self._toggle_console_clicked),
            pystray.MenuItem("API keys…", self._setup_clicked),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Stop Overlord", self._stop_clicked),
        )
        self._icon = pystray.Icon("overlord", image, self._title(), menu)
        self._thread = threading.Thread(
            target=self._icon.run,
            daemon=True,
            name="overlord-tray",
        )
        self._thread.start()
        log.info("Windows notification-area icon started")
        return True

    def _title(self) -> str:
        return f"Overlord {self.version} — {self._brain_name} — running"

    def set_brain(self, brain_name: str) -> None:
        self._brain_name = brain_name
        if self._icon is not None:
            self._icon.title = self._title()
            self._icon.update_menu()

    def _stop_clicked(self, icon, item) -> None:
        log.info("Stop requested from Windows notification-area icon")
        self.on_stop()
        icon.stop()

    def _console_is_visible(self) -> bool:
        if self._console_process is None or self._console_process.poll() is not None:
            return False
        if self._console_state is None:
            return True
        try:
            return self._console_state.read_text(encoding="utf-8").strip() == "visible"
        except OSError:
            return True

    def _console_menu_label(self, item=None) -> str:
        return "Hide Console" if self._console_is_visible() else "Show Console"

    def _toggle_console_clicked(self, icon, item) -> None:
        if self._console_is_visible():
            self._signal_console("hide")
            log.info("Hid Overlord console")
        elif self._launch_console_viewer():
            self._signal_console("show")

    def _setup_clicked(self, icon, item) -> None:
        self.launch_setup()

    def launch_setup(self) -> bool:
        """Open the API-key setup window (separate process, like the console)."""
        root = Path(__file__).resolve().parent.parent
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if not pythonw.exists():
            pythonw = Path(sys.executable)
        arguments = [str(pythonw), str(root / "tools" / "overlord_setup.py"),
                     "--env", str(root / ".env")]
        if self.command_path is not None:
            arguments.extend(("--command", str(self.command_path)))
        try:
            subprocess.Popen(arguments, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            log.warning("Could not open the setup window: %s", exc)
            return False
        return True

    def _signal_console(self, action: str) -> None:
        if self._console_signal is None:
            return
        try:
            self._console_signal.parent.mkdir(parents=True, exist_ok=True)
            self._console_signal.write_text(action, encoding="utf-8")
            if self._console_state is not None:
                state = "visible" if action == "show" else "hidden"
                self._console_state.write_text(state, encoding="utf-8")
        except OSError as exc:
            log.warning("Could not signal Overlord console window: %s", exc)

    def _launch_console_viewer(self) -> bool:
        """Fallback for GUI-style launches that have no attached console."""
        if self.log_path is None:
            log.warning("Cannot show console: no console or log path is available")
            return False
        if self._console_process is not None and self._console_process.poll() is None:
            return True
        if self._console_state is not None:
            self._console_state.unlink(missing_ok=True)
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if not pythonw.exists():
            pythonw = Path(sys.executable)
        viewer = Path(__file__).resolve().parent.parent / "tools" / "overlord_console.py"
        arguments = [
            str(pythonw),
            str(viewer),
            "--log",
            str(self.log_path),
            "--signal",
            str(self._console_signal),
            "--state",
            str(self._console_state),
        ]
        if self.status_path is not None:
            arguments.extend(("--status", str(self.status_path)))
        if self.command_path is not None:
            arguments.extend(("--command", str(self.command_path)))
        try:
            self._console_process = subprocess.Popen(
                arguments,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            log.warning("Could not open Overlord console viewer: %s", exc)
            return False
        log.info("Opened Overlord Tk console")
        return True

    def stop(self) -> None:
        if self._console_process is not None and self._console_process.poll() is None:
            self._console_process.terminate()
        if self._icon is not None:
            self._icon.stop()
        if (
            self._thread is not None
            and self._thread is not threading.current_thread()
            and self._thread.is_alive()
        ):
            self._thread.join(timeout=2)
