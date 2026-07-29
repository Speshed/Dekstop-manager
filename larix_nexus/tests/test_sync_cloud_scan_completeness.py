from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from larix_nexus.sync import engine


def _details(timestamp=10):
    return {
        "createTime": timestamp,
        "modifTime": timestamp,
        "size": 1,
        "version": 1,
    }


class _CloudApi:
    def __init__(self, details):
        self.details = details

    def list_folders(self, project_id, force=True):
        return [{"id": "root", "children": [{"type": "file", "name": name, "id": file_id} for name, file_id in (("a.txt", "a"), ("b.txt", "b"))]}]

    def get_document_details(self, file_id):
        value = self.details[file_id]
        if isinstance(value, Exception):
            raise value
        return value

    def list_documents_in_folder(self, folder_id, force=True):
        return []


class _DocumentsFailureApi(_CloudApi):
    def list_folders(self, project_id, force=True):
        return [{"id": "root", "children": []}]

    def list_documents_in_folder(self, folder_id, force=True):
        raise RuntimeError("temporary document listing failure")


class _CloudScanFailureApi(_CloudApi):
    def list_folders(self, project_id, force=True):
        raise RuntimeError("temporary tree failure")

    def get_folder_details(self, folder_id, force=True):
        raise RuntimeError("temporary folder failure")


class _EmptyCloudApi(_CloudApi):
    def list_folders(self, project_id, force=True):
        return [{"id": "root", "children": []}]


def test_cloud_scan_reports_partial_details_failure_without_false_success():
    scan = engine.get_cloud_files(_CloudApi({"a": RuntimeError("temporary"), "b": _details()}), 1, "root")

    assert scan.status == "partial"
    assert "b.txt" in scan
    assert "a.txt" not in scan
    assert scan.errors
    assert scan.failed_documents == [{"id": "a", "path": "a.txt"}]


def test_incomplete_scan_never_plans_deletes():
    old = {"a.txt": {"id": "a", "lastModified": 10}}
    local = {"a.txt": {"lastModified": 10}}

    operations = engine.compare_and_plan_sync(old, local, {"b.txt": {"id": "b"}}, cloud_scan_status="partial")

    assert not [op for op in operations if op["action"] in {"delete_local", "delete_cloud"}]


def test_partial_initial_scan_returns_failure_without_executor_or_state_save(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(engine, "load_sync_state", lambda project_id, folder_id: ({"a.txt": {"id": "a"}}, True))
    monkeypatch.setattr(engine, "get_local_files", lambda *args, **kwargs: {"a.txt": {"lastModified": 10}})
    monkeypatch.setattr(engine, "get_cloud_files", lambda *args, **kwargs: engine.CloudScanResult({}, "partial", ["details unavailable"], [{"id": "a", "path": "a.txt"}]))
    executor = monkeypatch.setattr(engine, "execute_sync_operations", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("executor called")))
    monkeypatch.setattr(engine, "save_sync_state", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("state saved")))

    result = engine.sync_files_new(_CloudApi({}), 1, "root", str(tmp_path))

    assert result["success"] is False
    assert result["cloud_scan_incomplete"] is True
    assert result["cloud_scan_status"] == "partial"
    assert result["errors"] == ["details unavailable"]


def test_partial_post_operation_rescan_preserves_previous_state(monkeypatch, tmp_path: Path):
    scans = iter([
        engine.CloudScanResult({"a.txt": {"id": "a", "lastModified": 1}}, "complete"),
        engine.CloudScanResult({}, "partial", ["temporary details failure"]),
    ])
    saved = []
    monkeypatch.setattr(engine, "load_sync_state", lambda project_id, folder_id: ({"a.txt": {"id": "a", "lastModified": 1}}, True))
    monkeypatch.setattr(engine, "get_local_files", lambda *args, **kwargs: {"a.txt": {"lastModified": 10}})
    monkeypatch.setattr(engine, "get_cloud_files", lambda *args, **kwargs: next(scans))
    monkeypatch.setattr(engine, "execute_sync_operations", lambda *args, **kwargs: {"downloaded": 0, "uploaded": 1, "deleted_local": 0, "deleted_cloud": 0, "errors": [], "failed_uploads": [], "failed_downloads": [], "failed_deletes_local": [], "failed_deletes_cloud": []})
    monkeypatch.setattr(engine, "save_sync_state", lambda *args, **kwargs: saved.append(args))

    result = engine.sync_files_new(_CloudApi({}), 1, "root", str(tmp_path))

    assert result["success"] is False
    assert result["cloud_scan_incomplete"] is True
    assert saved == []


def test_complete_scan_keeps_normal_delete_planning():
    old = {"a.txt": {"id": "a", "lastModified": 10}}
    local = {"a.txt": {"lastModified": 10}}
    cloud = {"b.txt": {"id": "b", "lastModified": 10}}

    operations = engine.compare_and_plan_sync(old, local, cloud, cloud_scan_status="complete")

    assert "delete_local" in {op["action"] for op in operations}


def test_document_listing_failure_is_not_complete_and_sync_does_not_write_state(monkeypatch, tmp_path: Path):
    scan = engine.get_cloud_files(_DocumentsFailureApi({}), 1, "root")
    assert scan.status == "failed"
    assert scan.errors

    monkeypatch.setattr(engine, "load_sync_state", lambda project_id, folder_id: ({}, True))
    monkeypatch.setattr(engine, "get_local_files", lambda *args, **kwargs: {})
    monkeypatch.setattr(engine, "get_cloud_files", lambda *args, **kwargs: scan)
    monkeypatch.setattr(engine, "execute_sync_operations", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("executor called")))
    monkeypatch.setattr(engine, "save_sync_state", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("state saved")))

    result = engine.sync_files_new(_DocumentsFailureApi({}), 1, "root", str(tmp_path))

    assert result["success"] is False
    assert result["cloud_scan_status"] == "failed"


def test_top_level_cloud_scan_failure_is_not_complete_and_does_not_write_state(monkeypatch, tmp_path: Path):
    scan = engine.get_cloud_files(_CloudScanFailureApi({}), 1, "root")
    assert scan.status == "failed"
    assert scan.errors

    monkeypatch.setattr(engine, "load_sync_state", lambda project_id, folder_id: ({}, True))
    monkeypatch.setattr(engine, "get_local_files", lambda *args, **kwargs: {})
    monkeypatch.setattr(engine, "get_cloud_files", lambda *args, **kwargs: scan)
    monkeypatch.setattr(engine, "execute_sync_operations", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("executor called")))
    monkeypatch.setattr(engine, "save_sync_state", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("state saved")))

    result = engine.sync_files_new(_CloudScanFailureApi({}), 1, "root", str(tmp_path))

    assert result["success"] is False
    assert result["cloud_scan_status"] == "failed"


def test_successfully_empty_cloud_catalog_is_complete():
    scan = engine.get_cloud_files(_EmptyCloudApi({}), 1, "root")

    assert dict(scan) == {}
    assert scan.status == "complete"
    assert scan.errors == []
