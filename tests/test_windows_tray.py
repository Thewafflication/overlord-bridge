from modules.windows_tray import WindowsTray


def test_tray_title_tracks_active_brain():
    tray = WindowsTray(lambda: None)
    assert "starting" in tray._title()

    tray.set_brain("codex")

    assert tray._title() == "Overlord — codex — running"


def test_tray_stop_action_requests_graceful_shutdown():
    stopped = []
    icon_stops = []
    tray = WindowsTray(lambda: stopped.append(True))

    class FakeIcon:
        def stop(self):
            icon_stops.append(True)

    tray._stop_clicked(FakeIcon(), None)

    assert stopped == [True]
    assert icon_stops == [True]


def test_show_console_launches_and_signals_tk_window(monkeypatch):
    tray = WindowsTray(lambda: None)
    signals = []
    monkeypatch.setattr(
        tray, "_launch_console_viewer", lambda: True
    )
    monkeypatch.setattr(tray, "_signal_console", signals.append)

    tray._show_console_clicked(None, None)

    assert signals == ["show"]


def test_failed_console_launch_is_not_signaled(monkeypatch):
    tray = WindowsTray(lambda: None)
    signals = []
    monkeypatch.setattr(
        tray, "_launch_console_viewer", lambda: False
    )
    monkeypatch.setattr(tray, "_signal_console", signals.append)

    tray._show_console_clicked(None, None)

    assert signals == []
