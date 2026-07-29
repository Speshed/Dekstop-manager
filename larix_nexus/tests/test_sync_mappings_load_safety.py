import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from larix_nexus.sync import manager as manager_module


def _paths(monkeypatch, tmp_path):
    mappings_path = tmp_path / "mappings.json"
    monkeypatch.setattr(manager_module, "_sync_mappings_path", lambda: str(mappings_path))
    monkeypatch.setattr(manager_module, "_legacy_sync_mappings_path", lambda: str(tmp_path / "legacy.json"))
    return mappings_path


def _manager(map_value=None, trusted=False, reason=""):
    manager = manager_module.FolderSyncManager.__new__(manager_module.FolderSyncManager)
    manager.map = map_value or {}
    manager._mappings_load_trusted = trusted
    manager._mappings_load_reason = reason
    manager._mappings_load_status = "ok" if trusted else "failed"
    return manager


def test_valid_mappings_are_trusted_and_purge_gets_active_mapping(monkeypatch, tmp_path):
    path = _paths(monkeypatch, tmp_path)
    payload = {"version": 1, "mappings": {"7": {"local_path": "sync", "project_id": 42}}}
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(manager_module, "atomic_read_json", lambda *args, **kwargs: payload)
    purge = Mock(return_value=1)
    monkeypatch.setattr(manager_module, "purge_orphan_sync_state_files", purge)

    loaded = manager_module.load_sync_mappings()
    manager = _manager({"7": payload["mappings"]["7"]}, trusted=loaded.status == "ok")
    manager._purge_stale_sync_artifacts()

    assert loaded.status == "ok"
    purge.assert_called_once_with({"7": payload["mappings"]["7"]})


def test_valid_empty_mappings_is_ok_and_purge_policy_is_explicit(monkeypatch, tmp_path):
    path = _paths(monkeypatch, tmp_path)
    payload = {"version": 1, "mappings": {}}
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(manager_module, "atomic_read_json", lambda *args, **kwargs: payload)
    purge = Mock(return_value=0)
    legacy_purge = Mock(return_value=True)
    monkeypatch.setattr(manager_module, "purge_orphan_sync_state_files", purge)
    monkeypatch.setattr(manager_module, "purge_legacy_global_sync_state", legacy_purge)

    loaded = manager_module.load_sync_mappings()
    manager = _manager({}, trusted=loaded.status == "ok")
    manager._purge_stale_sync_artifacts()

    assert loaded.status == "ok"
    purge.assert_called_once_with({})
    legacy_purge.assert_called_once_with()


def test_corrupt_existing_mappings_is_failed_and_cannot_purge(monkeypatch, tmp_path):
    path = _paths(monkeypatch, tmp_path)
    path.write_text('{"mappings":', encoding="utf-8")
    monkeypatch.setattr(manager_module, "atomic_read_json", lambda *args, **kwargs: {"version": 1, "mappings": {}})
    purge = Mock()
    monkeypatch.setattr(manager_module, "purge_orphan_sync_state_files", purge)
    monkeypatch.setattr(manager_module, "purge_legacy_global_sync_state", Mock())

    loaded = manager_module.load_sync_mappings()
    manager = _manager({"7": {"project_id": 42}}, reason=loaded.reason)
    monkeypatch.setattr(manager_module, "load_sync_mappings", lambda: loaded)
    manager._load()
    manager._purge_stale_sync_artifacts()

    assert loaded.status == "failed"
    assert manager._mappings_load_trusted is False
    assert manager.map == {}
    purge.assert_not_called()
    assert path.read_text(encoding="utf-8") == '{"mappings":'


def test_atomic_and_direct_read_failures_are_failed_and_skip_purge(monkeypatch, tmp_path):
    path = _paths(monkeypatch, tmp_path)
    path.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(manager_module, "atomic_read_json", Mock(side_effect=OSError("locked")))
    purge = Mock()
    monkeypatch.setattr(manager_module, "purge_orphan_sync_state_files", purge)

    loaded = manager_module.load_sync_mappings()
    manager = _manager(reason=loaded.reason)
    manager._purge_stale_sync_artifacts()

    assert loaded.status == "failed"
    assert "atomic read failed" in loaded.reason
    purge.assert_not_called()


def test_direct_fallback_after_atomic_failure_is_trusted(monkeypatch, tmp_path):
    path = _paths(monkeypatch, tmp_path)
    payload = {"version": 1, "mappings": {"9": {"local_path": "sync", "project_id": 55}}}
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(manager_module, "atomic_read_json", Mock(side_effect=OSError("locked")))

    loaded = manager_module.load_sync_mappings()

    assert loaded.status == "ok"
    assert loaded["mappings"] == payload["mappings"]


def test_successful_save_marks_mappings_trusted_and_purges(monkeypatch):
    manager = _manager({"3": {"local_path": "sync", "project_id": 8}}, trusted=True)
    payload = manager_module.SyncMappingsLoadResult({"version": 1, "mappings": {}}, "ok")
    monkeypatch.setattr(manager_module, "load_sync_mappings", lambda: payload)
    monkeypatch.setattr(manager_module, "save_sync_mappings", Mock(return_value=True))
    manager._purge_stale_sync_artifacts = Mock()

    assert manager._save() is True
    assert manager._mappings_load_trusted is True
    manager._purge_stale_sync_artifacts.assert_called_once_with()
