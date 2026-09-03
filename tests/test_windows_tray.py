from modules.windows_tray import WindowsTray


def test_tray_title_tracks_active_brain():
    tray = WindowsTray(lambda: None)
    assert "starting" in tray._title()

    tray.set_brain("codex")

    # The version rides along in the tooltip so a running tray identifies the
    # build it came from without opening the console.
    assert tray._title() == f"Overlord {tray.version} — codex — running"
    assert tray.version.startswith("v")


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


def test_console_toggle_shows_hidden_window(monkeypatch):
    tray = WindowsTray(lambda: None)
    signals = []
    monkeypatch.setattr(tray, "_console_is_visible", lambda: False)
    monkeypatch.setattr(
        tray, "_launch_console_viewer", lambda: True
    )
    monkeypatch.setattr(tray, "_signal_console", signals.append)

    tray._toggle_console_clicked(None, None)

    assert signals == ["show"]


def test_console_toggle_hides_visible_window(monkeypatch):
    tray = WindowsTray(lambda: None)
    signals = []
    monkeypatch.setattr(tray, "_console_is_visible", lambda: True)
    monkeypatch.setattr(tray, "_signal_console", signals.append)

    tray._toggle_console_clicked(None, None)

    assert signals == ["hide"]


def test_console_menu_uses_one_state_aware_label(monkeypatch):
    tray = WindowsTray(lambda: None)
    monkeypatch.setattr(tray, "_console_is_visible", lambda: False)
    assert tray._console_menu_label() == "Show Console"
    monkeypatch.setattr(tray, "_console_is_visible", lambda: True)
    assert tray._console_menu_label() == "Hide Console"


def test_failed_console_launch_is_not_signaled(monkeypatch):
    tray = WindowsTray(lambda: None)
    signals = []
    monkeypatch.setattr(tray, "_console_is_visible", lambda: False)
    monkeypatch.setattr(
        tray, "_launch_console_viewer", lambda: False
    )
    monkeypatch.setattr(tray, "_signal_console", signals.append)

    tray._toggle_console_clicked(None, None)

    assert signals == []
