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
from larix_nexus.sync import manager as manager_module
from larix_nexus.ui import upload_operations


def _owner(api, settings, monkeypatch, status=None):
    owner = SimpleNamespace(api=api, status=status or Mock())
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
    assert result["success"] is False


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
