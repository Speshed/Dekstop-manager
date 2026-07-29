import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from larix_nexus.sync import engine as engine_module
from larix_nexus.sync import manager as manager_module


def _manager_without_init():
    manager = manager_module.FolderSyncManager.__new__(manager_module.FolderSyncManager)
    manager.map = {}
    return manager


def test_manager_save_mappings_false_does_not_purge(monkeypatch):
    manager = _manager_without_init()
    purge = Mock()
    log = Mock()
    manager._purge_stale_sync_artifacts = purge

    monkeypatch.setattr(manager_module, "load_sync_mappings", lambda: {"mappings": {}})
    monkeypatch.setattr(manager_module, "save_sync_mappings", Mock(return_value=False))
    monkeypatch.setattr(manager_module, "sync_log", log)

    with pytest.raises(RuntimeError, match="save sync mappings"):
        manager._save()

    purge.assert_not_called()
    assert not any("успешно" in str(call) for call in log.call_args_list)


def test_add_sync_mapping_failure_is_not_success_and_rolls_back(monkeypatch):
    manager = _manager_without_init()
    monkeypatch.setattr(manager_module, "clear_sync_state", Mock(return_value=True))
    manager._save = Mock(side_effect=RuntimeError("mapping write failed"))

    with pytest.raises(RuntimeError, match="mapping write failed"):
        manager.add_sync(12, "C:/sync", 34)

    assert manager.map == {}


def test_sync_files_new_state_false_returns_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(engine_module, "load_sync_state", lambda project_id, folder_id: ({}, False))
    monkeypatch.setattr(engine_module, "get_local_files", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        engine_module,
        "get_cloud_files",
        lambda *args, **kwargs: engine_module.CloudScanResult({}, "complete"),
    )
    monkeypatch.setattr(engine_module, "save_sync_state", Mock(return_value=False))

    result = engine_module.sync_files_new(Mock(), 1, 2, str(tmp_path))

    assert result["success"] is False
    assert result["errors"]
    assert "state write" in result["errors"][0].lower()


def test_sync_files_new_state_true_preserves_success(monkeypatch, tmp_path):
    monkeypatch.setattr(engine_module, "load_sync_state", lambda project_id, folder_id: ({}, False))
    monkeypatch.setattr(engine_module, "get_local_files", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        engine_module,
        "get_cloud_files",
        lambda *args, **kwargs: engine_module.CloudScanResult({}, "complete"),
    )
    save_state = Mock(return_value=True)
    monkeypatch.setattr(engine_module, "save_sync_state", save_state)

    result = engine_module.sync_files_new(Mock(), 1, 2, str(tmp_path))

    assert result["success"] is True
    assert result["errors"] == []
    save_state.assert_called_once()


def test_sync_files_new_state_exception_is_not_success(monkeypatch, tmp_path):
    monkeypatch.setattr(engine_module, "load_sync_state", lambda project_id, folder_id: ({}, False))
    monkeypatch.setattr(engine_module, "get_local_files", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        engine_module,
        "get_cloud_files",
        lambda *args, **kwargs: engine_module.CloudScanResult({}, "complete"),
    )
    monkeypatch.setattr(engine_module, "save_sync_state", Mock(side_effect=OSError("write failed")))

    with pytest.raises(OSError):
        engine_module.sync_files_new(Mock(), 1, 2, str(tmp_path))
