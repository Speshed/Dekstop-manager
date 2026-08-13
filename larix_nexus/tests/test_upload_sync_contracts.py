import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from larix_nexus.api.client import APIClient
from larix_nexus.api import client as client_module
from larix_nexus.sync.engine import execute_sync_operations
from larix_nexus.sync import engine as engine_module
from larix_nexus.sync import manager as manager_module
from larix_nexus.ui import upload_operations


def _owner(api, settings, monkeypatch, status=None):
    owner = SimpleNamespace(
        api=api,
        status=status or Mock(),
        _ensure_subfolder=Mock(return_value=20),
    )
    monkeypatch.setattr(upload_operations, "load_settings", lambda: dict(settings))
    monkeypatch.setattr(upload_operations, "save_settings", lambda value: settings.update(value))
    return owner


@pytest.mark.parametrize(
    ("saved", "types", "expected"),
    [(None, {"4": "PDF"}, 4), (4, {"4": "PDF", "7": "BIM"}, 4), (99, {"4": "PDF"}, 4)],
)
def test_recursive_upload_selects_server_document_type(tmp_path, monkeypatch, saved, types, expected):
    api = Mock()
    api.get_document_types.return_value = types
    api.upload_file.return_value = True
    settings = {} if saved is None else {"last_document_type_id": saved}
    owner = _owner(api, settings, monkeypatch)
    monkeypatch.setattr(owner, "_ensure_subfolder", lambda project, parent, name: 20)

    (tmp_path / "file.bin").write_bytes(b"data")
    upload_operations._upload_dir_recursive(owner, 1, 2, Path(tmp_path))

    assert api.upload_file.call_args.kwargs["document_type_id"] == expected
    assert settings["last_document_type_id"] == expected


def test_recursive_upload_without_document_types_does_not_upload(tmp_path, monkeypatch):
    api = Mock()
    api.get_document_types.return_value = {}
    status = Mock()
    owner = _owner(api, {}, monkeypatch)
    owner.status = status
    (tmp_path / "file.bin").write_bytes(b"data")

    upload_operations._upload_dir_recursive(owner, 1, 2, Path(tmp_path))

    api.upload_file.assert_not_called()
    status.showMessage.assert_called_once()


class _Response:
    status_code = 200
    headers = {"content-length": "4"}
    text = '[{"success": true, "documentId": 77}]'

    def json(self):
        return [{"success": True, "documentId": 77}]

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        yield b"data"


def test_copy_document_uses_server_type_without_implicit_100(monkeypatch):
    client = APIClient("https://example.test")
    client.token = "test-token"
    client.get_document_details = Mock(return_value={"name": "source.bin"})
    client.get_document_types = Mock(return_value={"4": "PDF"})
    monkeypatch.setattr(client_module.requests, "get", lambda *args, **kwargs: _Response())
    captured = {}

    def upload(*args, **kwargs):
        captured.update(kwargs)
        return _Response()

    client._post_multipart_with_fallback = upload
    assert client.copy_document(1, 2) == 77
    assert '"documentType": "4"' in captured["metadata_json"]
    assert '"documentType": "100"' not in captured["metadata_json"]


def test_copy_document_without_source_or_available_type_does_not_upload(monkeypatch):
    client = APIClient("https://example.test")
    client.token = "test-token"
    client.get_document_details = Mock(return_value={"name": "source.bin"})
    client.get_document_types = Mock(return_value={})
    upload = Mock()
    client._post_multipart_with_fallback = upload

    assert client.copy_document(1, 2) is False
    upload.assert_not_called()


def test_execute_sync_operations_stops_after_cancellation(tmp_path):
    (tmp_path / "first.txt").write_text("one", encoding="utf-8")
    (tmp_path / "second.txt").write_text("two", encoding="utf-8")
    api = Mock()
    calls = []
    cancelled = {"value": False}

    def upload(*args, **kwargs):
        calls.append(args[2])
        cancelled["value"] = True
        return True

    api.upload_file.side_effect = upload
    operations = [
        {"action": "upload", "path": "first.txt", "is_folder": False, "parent_folder_id": 1},
        {"action": "upload", "path": "second.txt", "is_folder": False, "parent_folder_id": 1},
    ]
    result = execute_sync_operations(
        api,
        1,
        1,
        str(tmp_path),
        operations,
        cancel_check=lambda: cancelled["value"],
    )

    assert result["cancelled"] is True
    assert calls == ["first.txt"]
    assert result["errors"]


def test_execute_sync_operations_cancellation_before_first_operation(tmp_path):
    result = execute_sync_operations(
        Mock(), 1, 1, str(tmp_path),
        [{"action": "upload", "path": "never.txt", "is_folder": False}],
        cancel_check=lambda: True,
    )

    assert result["cancelled"] is True
    assert result["uploaded"] == 0
    assert result["errors"]


def test_execute_sync_operations_normal_stats_are_not_cancelled(tmp_path):
    result = execute_sync_operations(Mock(), 1, 1, str(tmp_path), [])

    assert result["cancelled"] is False
    assert result["errors"] == []


@pytest.mark.parametrize("is_folder, method_name", [(False, "delete_document"), (True, "delete_folder")])
@pytest.mark.parametrize("delete_result", [True, False])
def test_execute_sync_operations_cloud_delete_bool_contract(tmp_path, is_folder, method_name, delete_result):
    api = Mock()
    getattr(api, method_name).return_value = delete_result
    path = "folder/file.txt" if not is_folder else "folder"

    result = execute_sync_operations(
        api, 1, 1, str(tmp_path),
        [{"action": "delete_cloud", "path": path, "cloud_id": "cloud-id", "is_folder": is_folder}],
    )

    assert result["deleted_cloud"] == (1 if delete_result is True else 0)
    assert result["failed_deletes_cloud"] == ([] if delete_result is True else [path])
    assert result["errors"] == ([] if delete_result is True else [result["errors"][0]])
    if delete_result is False:
        assert path in result["errors"][0]


@pytest.mark.parametrize("is_folder, method_name", [(False, "delete_document"), (True, "delete_folder")])
def test_execute_sync_operations_cloud_delete_exception_is_failure(tmp_path, is_folder, method_name):
    api = Mock()
    getattr(api, method_name).side_effect = RuntimeError("API unavailable")
    path = "folder/file.txt" if not is_folder else "folder"

    result = execute_sync_operations(
        api, 1, 1, str(tmp_path),
        [{"action": "delete_cloud", "path": path, "cloud_id": "cloud-id", "is_folder": is_folder}],
    )

    assert result["deleted_cloud"] == 0
    assert result["failed_deletes_cloud"] == [path]
    assert result["errors"]
    assert path in result["errors"][0]


def test_sync_files_new_cancellation_skips_rescan_and_state_save(monkeypatch, tmp_path):
    local_calls = []
    cloud_calls = []
    saved = []
    local_files = {"a.txt": {"lastModified": 20}}
    cloud_files = engine_module.CloudScanResult({"a.txt": {"id": "a", "lastModified": 10}}, "complete")

    monkeypatch.setattr(engine_module, "load_sync_state", lambda project_id, folder_id: ({"a.txt": {"id": "a", "lastModified": 10}}, True))

    def get_local(*args, **kwargs):
        local_calls.append(True)
        return local_files

    def get_cloud(*args, **kwargs):
        cloud_calls.append(True)
        return cloud_files

    monkeypatch.setattr(engine_module, "get_local_files", get_local)
    monkeypatch.setattr(engine_module, "get_cloud_files", get_cloud)
    monkeypatch.setattr(engine_module, "execute_sync_operations", lambda *args, **kwargs: {
        "downloaded": 0,
        "uploaded": 1,
        "deleted_local": 0,
        "deleted_cloud": 0,
        "errors": ["Синхронизация отменена"],
        "failed_uploads": [],
        "failed_downloads": [],
        "failed_deletes_local": [],
        "failed_deletes_cloud": [],
        "cancelled": True,
    })
    monkeypatch.setattr(engine_module, "save_sync_state", lambda *args, **kwargs: saved.append(args))

    result = engine_module.sync_files_new(Mock(), 1, "root", str(tmp_path))

    assert result["success"] is False
    assert result["cancelled"] is True
    assert result["stats"]["uploaded"] == 1
    assert result["errors"] == ["Синхронизация отменена"]
    assert saved == []
    assert len(local_calls) == 1
    assert len(cloud_calls) == 1


def test_initial_sync_worker_reports_cancelled_and_releases_busy(monkeypatch):
    owner = Mock()
    owner._sync_ui_hooks.return_value = {}
    owner._set_busy = Mock()
    monkeypatch.setattr(manager_module, "load_sync_state", lambda project, folder: ({}, False))
    monkeypatch.setattr(
        manager_module,
        "sync_files_new",
        lambda **kwargs: {"success": False, "cancelled": True, "errors": ["cancelled"], "stats": {}},
    )

    worker = manager_module._InitialSyncWorker(Mock(), 10, "local", 20, owner)
    finished = []
    worker.sig_finished.connect(lambda ok, errors: finished.append((ok, errors)))
    worker.run()

    assert finished == [(False, 0)]
    assert owner._set_busy.call_args_list == [call("10", True), call("10", False)]


def test_initial_sync_worker_keeps_errors_for_final_user_dialog(monkeypatch):
    owner = Mock()
    owner._sync_ui_hooks.return_value = {}
    owner._set_busy = Mock()
    details = [
        "Download failed: denied.pdf (HTTP 403: Нет доступа)",
        "Download failed: missing.pdf (HTTP 404: Файл не найден)",
    ]
    monkeypatch.setattr(manager_module, "load_sync_state", lambda project, folder: ({}, False))
    monkeypatch.setattr(
        manager_module,
        "sync_files_new",
        lambda **kwargs: {"success": False, "errors": details, "stats": {}},
    )

    worker = manager_module._InitialSyncWorker(Mock(), 10, "local", 20, owner)
    finished = []
    worker.sig_finished.connect(lambda ok, errors: finished.append((ok, errors)))

    worker.run()

    assert worker._errors == details
    assert finished == [(False, 2)]
