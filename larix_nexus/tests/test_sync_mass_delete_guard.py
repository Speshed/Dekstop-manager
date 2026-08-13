from pathlib import Path

import pytest

from larix_nexus.sync import engine


def _snapshot(count):
    return {
        f"file-{index}.txt": {"local": {"exists": True}, "cloud": {"exists": True}}
        for index in range(count)
    }


class _DeleteTrackingApi:
    def __init__(self):
        self.deleted_documents = []
        self.deleted_folders = []

    def delete_document(self, document_id):
        self.deleted_documents.append(document_id)

    def delete_folder(self, folder_id):
        self.deleted_folders.append(folder_id)


def test_auto_mass_delete_is_blocked_before_executor(monkeypatch, tmp_path: Path):
    api = _DeleteTrackingApi()
    old_state = {path: {"id": path} for path in _snapshot(20)}
    cloud_files = {
        path: {"id": path, "is_folder": False, "lastModified": 1}
        for path in old_state
    }
    executed = False

    monkeypatch.setattr(engine, "load_sync_state", lambda *_: (old_state, True))
    monkeypatch.setattr(engine, "get_local_files", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        engine,
        "get_cloud_files",
        lambda *_args, **_kwargs: engine.CloudScanResult(cloud_files, "complete"),
    )

    def plan(*_args, **_kwargs):
        return [{"action": "delete_cloud", "path": path} for path in old_state]

    monkeypatch.setattr(engine, "compare_and_plan_sync", plan)

    def executor(*_args, **_kwargs):
        nonlocal executed
        executed = True
        return {}

    monkeypatch.setattr(engine, "execute_sync_operations", executor)
    result = engine.sync_files_new(api, 1, "root", str(tmp_path), sync_mode="auto")

    assert result["success"] is False
    assert result["blocked_by_guard"] is True
    assert result["guard"]["delete_count"] == 20
    assert result["stats"]["deleted_cloud"] == 0
    assert result["stats"]["deleted_local"] == 0
    assert executed is False
    assert api.deleted_documents == []
    assert api.deleted_folders == []


@pytest.mark.parametrize("allow_mass_delete", [False, True])
def test_mass_delete_guard_keeps_strict_threshold_and_explicit_override(allow_mass_delete):
    operations = [{"action": "delete_cloud", "path": f"f-{i}"} for i in range(2)]
    result = engine.check_mass_delete_guard(
        operations,
        _snapshot(10),
        threshold_percent=20,
        allow_mass_delete=allow_mass_delete,
        sync_mode="manual",
    )

    assert result["delete_percent"] == 20
    assert result["ok"] is True
    assert result["blocked_by_guard"] is False


def test_mass_delete_guard_blocks_above_threshold_in_auto():
    operations = [{"action": "delete_cloud", "path": f"f-{i}"} for i in range(3)]
    result = engine.check_mass_delete_guard(
        operations,
        _snapshot(10),
        threshold_percent=20,
        allow_mass_delete=False,
        sync_mode="auto",
    )

    assert result["ok"] is False
    assert result["blocked_by_guard"] is True


def test_small_complete_delete_is_blocked_even_below_min_files():
    operations = [{"action": "delete_cloud", "path": f"f-{i}"} for i in range(4)]
    result = engine.check_mass_delete_guard(operations, _snapshot(4), threshold_percent=20, min_files=10)
    assert result["ok"] is False
    assert result["blocked_by_guard"] is True
    assert result["delete_count"] == 4
    assert result["total_files"] == 4


def test_one_of_four_delete_is_blocked_by_threshold():
    result = engine.check_mass_delete_guard(
        [{"action": "delete_cloud", "path": "f-0"}],
        _snapshot(4),
        threshold_percent=20,
        min_files=10,
    )
    assert result["blocked_by_guard"] is True


def test_guard_allows_no_delete_operations():
    result = engine.check_mass_delete_guard([], _snapshot(4), min_files=10)
    assert result["ok"] is True
    assert result["blocked_by_guard"] is False


def test_guard_ignores_many_local_deletions():
    operations = [
        {"action": "delete_local", "path": f"local-{index}"}
        for index in range(20)
    ]
    result = engine.check_mass_delete_guard(operations, _snapshot(20))
    assert result["ok"] is True
    assert result["blocked_by_guard"] is False
    assert result["delete_count"] == 0
    assert result["delete_percent"] == 0.0
    assert result["sample_paths"] == []
    assert result["actions_by_type"]["delete_local"] == 20


def test_guard_blocks_cloud_deletions_above_threshold():
    operations = [
        {"action": "delete_cloud", "path": f"cloud-{index}"}
        for index in range(3)
    ]
    result = engine.check_mass_delete_guard(operations, _snapshot(10), threshold_percent=20)
    assert result["ok"] is False
    assert result["blocked_by_guard"] is True
    assert result["delete_count"] == 3
    assert result["delete_percent"] == 30.0
    assert result["sample_paths"] == ["cloud-0", "cloud-1", "cloud-2"]


def test_guard_mixed_plan_risk_uses_only_cloud_deletions():
    operations = [
        {"action": "delete_local", "path": f"local-{index}"}
        for index in range(20)
    ] + [{"action": "delete_cloud", "path": "cloud-0"}]
    result = engine.check_mass_delete_guard(operations, _snapshot(10), threshold_percent=20)
    assert result["ok"] is True
    assert result["blocked_by_guard"] is False
    assert result["delete_count"] == 1
    assert result["delete_percent"] == 10.0
    assert result["sample_paths"] == ["cloud-0"]
    assert result["actions_by_type"] == {"delete_local": 20, "delete_cloud": 1}
