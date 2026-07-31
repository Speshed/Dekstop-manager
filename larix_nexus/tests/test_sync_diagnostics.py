from types import SimpleNamespace
from unittest.mock import Mock

from larix_nexus.sync import manager as manager_module
from larix_nexus.ui.operation_coordinator import FileOperationCoordinator


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


def test_auto_operation_release_is_idempotent_after_start_failure():
    callback = Mock()
    obj = SimpleNamespace(
        _auto_operation_release_done=False,
        _auto_sync_running=False,
        _operation_finished=callback,
    )

    manager_module.FolderSyncManager._finish_auto_operation(obj, "worker_start_exception")
    manager_module.FolderSyncManager._finish_auto_operation(obj, "thread_finished_unexpectedly")

    callback.assert_called_once_with()
    assert obj._auto_operation_release_done is True


def test_unexpected_auto_sync_thread_finish_releases_once():
    callback = Mock()
    obj = SimpleNamespace(
        _auto_sync_running=True,
        _auto_operation_release_done=False,
        _operation_finished=callback,
        _cleanup_auto_sync_thread=Mock(),
    )
    obj._finish_auto_operation = lambda reason: manager_module.FolderSyncManager._finish_auto_operation(obj, reason)

    manager_module.FolderSyncManager._on_auto_sync_thread_finished(obj)
    manager_module.FolderSyncManager._on_auto_sync_thread_finished(obj)

    callback.assert_called_once_with()
    assert obj._auto_sync_running is False


def test_auto_sync_group_finish_with_no_pending_workers_does_not_leave_slot():
    coordinator = FileOperationCoordinator()
    coordinator.try_acquire_user("sync", source="sync_all")
    obj = SimpleNamespace(
        _sync_all_operation_active=True,
        _sync_all_pending=0,
        _sync_all_release_done=False,
        _file_operations=coordinator,
    )

    # The group helper in sync_handlers is the single release owner.
    from larix_nexus.ui import sync_handlers

    obj._release_file_operation = lambda operation, **kwargs: coordinator.release(
        operation, source=kwargs.get("source", "sync_all")
    )
    assert sync_handlers._finish_sync_all_if_done(obj, "no_valid_folders")
    assert coordinator.active_operation is None
    assert obj._sync_all_operation_active is False
    assert obj._sync_all_pending == 0


def test_periodic_timeout_defers_when_external_operation_owns_slot():
    obj = SimpleNamespace(
        _sync_interval=300,
        map={"one": {}},
        api=SimpleNamespace(token="token"),
        _auto_sync_running=False,
        _auto_sync_deferred=False,
        _auto_operation_guard=lambda: False,
        _schedule_next_sync=Mock(),
    )

    manager_module.FolderSyncManager._on_periodic_timeout(obj)

    assert obj._auto_sync_deferred is True
    obj._schedule_next_sync.assert_called_once_with()
    assert not hasattr(obj, "_auto_sync_thread")
