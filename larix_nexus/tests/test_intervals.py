from types import SimpleNamespace
from unittest.mock import Mock

from larix_nexus.ui import main_window


class _FakeTimer:
    def __init__(self):
        self.interval = None
        self.started = 0

    def setInterval(self, interval):
        self.interval = interval

    def start(self):
        self.started += 1


def test_notification_interval_is_saved_and_rescheduled(monkeypatch):
    settings = {"sync": {}}
    saved = []
    monkeypatch.setattr(main_window, "load_settings", lambda: settings)
    monkeypatch.setattr(main_window, "save_settings", lambda value: saved.append(value))

    window = SimpleNamespace(
        _notifications_timer=object(),
        _schedule_next_notification_timer=Mock(),
    )
    main_window.MainWindow._set_notification_interval(window, 600)

    assert settings["sync"]["notification_refresh_interval"] == 600
    assert saved == [settings]
    window._schedule_next_notification_timer.assert_called_once_with()


def test_sync_interval_updates_manager_and_ui_timer(monkeypatch):
    settings = {"sync": {}}
    saved = []
    monkeypatch.setattr(main_window, "load_settings", lambda: settings)
    monkeypatch.setattr(main_window, "save_settings", lambda value: saved.append(value))
    sync_manager = Mock()
    timer = _FakeTimer()
    window = SimpleNamespace(sync2=sync_manager, _auto_refresh_timer=timer)

    main_window.MainWindow._set_sync_interval(window, 900)

    assert settings["sync"]["auto_sync_interval"] == 900
    assert saved == [settings]
    sync_manager.set_sync_interval.assert_called_once_with(900)
    assert timer.interval == 900_000
    assert timer.started == 1
