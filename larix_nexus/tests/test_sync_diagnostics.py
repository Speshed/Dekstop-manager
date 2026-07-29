from types import SimpleNamespace
from unittest.mock import Mock

from larix_nexus.sync import manager as manager_module


def test_sync_exception_log_is_structured_and_redacts_path(monkeypatch):
    logged = []
    monkeypatch.setattr(manager_module, "sync_log", lambda *args, **kwargs: logged.append((args, kwargs)))

    manager_module._log_sync_exception(
        "schedule",
        OSError(r"C:\Users\alice\sync\state.json: access denied"),
        "Timer scheduling failed",
    )

    assert logged[0][1]["component"] == "sync"
    assert logged[0][1]["op"] == "schedule"
    assert logged[0][1]["result"] == "error"
    assert "state.json" not in logged[0][1]["reason"]
    assert "OSError" in logged[0][1]["reason"]


def test_worker_completion_clears_running_and_reschedules():
    obj = SimpleNamespace(
        _auto_sync_running=True,
        autoSyncResult=Mock(),
        _cleanup_auto_sync_thread=Mock(),
        _schedule_next_sync=Mock(),
    )

    manager_module.FolderSyncManager._on_auto_sync_worker_finished(obj, [])

    assert obj._auto_sync_running is False
    obj._cleanup_auto_sync_thread.assert_called_once_with()
    obj._schedule_next_sync.assert_called_once_with()
