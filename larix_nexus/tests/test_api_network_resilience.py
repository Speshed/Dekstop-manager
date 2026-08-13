from io import BytesIO
from pathlib import Path
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
import requests

from larix_nexus.api import client as client_module
from larix_nexus.ui import download_operations, upload_operations


def _response(status, payload=None):
    payload = payload if payload is not None else {"success": False}
    response = Mock()
    response.status_code = status
    response.ok = 200 <= status < 300
    response.content = b"response"
    response.text = "response"
    response.headers = {"Content-Length": "8"}
    response.json.return_value = payload
    response.raise_for_status.side_effect = (
        requests.HTTPError(f"HTTP {status}") if status >= 400 else None
    )
    return response


def _client(monkeypatch):
    api = client_module.APIClient("https://example.test")
    api.token = "test-token"
    monkeypatch.setattr(client_module.time, "sleep", lambda *_args: None)
    return api


def _download_response(chunks, content_length=None, error=None):
    response = MagicMock()
    response.status_code = 200
    response.headers = {} if content_length is None else {"Content-Length": content_length}
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.raise_for_status.return_value = None

    def stream():
        for chunk in chunks:
            yield chunk
        if error is not None:
            raise error

    response.iter_content.return_value = stream()
    return response


def _download_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(client_module, "DOWNLOAD_DIR", str(tmp_path))
    return tmp_path / "download.bin"


def _part_files(tmp_path):
    return list(tmp_path.glob(".*.part"))


def test_upload_timeout_is_bounded_and_user_safe(monkeypatch, tmp_path: Path):
    api = _client(monkeypatch)
    source = tmp_path / "payload.bin"
    source.write_bytes(b"data")
    calls = []

    def timeout(*_args, **_kwargs):
        calls.append(1)
        raise requests.Timeout("secret-token must not reach UI")

    monkeypatch.setattr(api, "_post_multipart_with_fallback", timeout)

    assert api.upload_file(10, str(source), "payload.bin", 4) is False
    assert len(calls) == 3
    assert "secret-token" not in api._last_upload_error
    assert "время" in api._last_upload_error.lower()


def test_download_401_returns_failure_without_retry(monkeypatch):
    api = _client(monkeypatch)
    response = _response(401)
    get = Mock(return_value=response)
    monkeypatch.setattr(client_module.requests, "get", get)

    assert api.download_file(42, "file.bin") == ""
    get.assert_called_once()
    assert get.call_args.kwargs["timeout"] == 60


@pytest.mark.parametrize("status", [429, 500, 503])
def test_upload_retries_only_retryable_http_statuses(monkeypatch, tmp_path: Path, status):
    api = _client(monkeypatch)
    source = tmp_path / "payload.bin"
    source.write_bytes(b"data")
    success = _response(201, {"success": True, "data": [{"id": 7, "name": "payload.bin"}]})
    responses = [_response(status), _response(status), success]
    post = Mock(side_effect=responses)
    monkeypatch.setattr(api, "_post_multipart_with_fallback", post)

    assert api.upload_file(10, str(source), "payload.bin", 4) is True
    assert post.call_count == 3


def test_upload_does_not_retry_for_forbidden(monkeypatch, tmp_path: Path):
    api = _client(monkeypatch)
    source = tmp_path / "payload.bin"
    source.write_bytes(b"data")
    post = Mock(return_value=_response(403))
    monkeypatch.setattr(api, "_post_multipart_with_fallback", post)

    assert api.upload_file(10, str(source), "payload.bin", 4) is False
    post.assert_called_once()


def test_batch_upload_cancel_is_immediate():
    owner = SimpleNamespace(api=Mock())
    worker = upload_operations._BatchUploadWorker(owner, 1, 2, [], 4)

    worker.cancel()

    assert worker._cancelled.is_set()


def test_download_failure_clears_progress(monkeypatch):
    self = SimpleNamespace(
        api=SimpleNamespace(
            download_file=Mock(
                side_effect=requests.Timeout(r"C:\\secret\\a.bin https://example.test/files/9")
            )
        ),
        _set_progress_visible=Mock(),
        progress=SimpleNamespace(setRange=Mock(), setValue=Mock()),
        status=SimpleNamespace(showMessage=Mock()),
        _ask_mode=Mock(return_value="A"),
        _unique_name=Mock(side_effect=lambda _d, name: name),
    )
    wait = Mock()
    logged = []
    monkeypatch.setattr(download_operations, "WaitDialog", Mock(return_value=wait))
    monkeypatch.setattr(download_operations.QApplication, "processEvents", Mock())
    monkeypatch.setattr(download_operations, "t", lambda key, **_kwargs: key)
    monkeypatch.setattr(download_operations, "sync_log", lambda *args, **kwargs: logged.append((args, kwargs)))

    result = download_operations.ensure_downloaded(self, {"type": "file", "id": 9, "name": "a.bin"})

    assert result == ""
    self._set_progress_visible.assert_any_call(False)
    assert self._set_progress_visible.call_args_list[-1].args == (False,)
    wait.set_done.assert_called_once_with("download.download_failed")
    self.status.showMessage.assert_called_once_with("download.download_failed", 5000)
    assert logged[0][1]["component"] == "download"
    assert logged[0][1]["op"] == "ensure_downloaded"
    assert logged[0][1]["result"] == "error"
    assert logged[0][1]["reason"] == "Timeout: download operation failed"
    assert "Timeout" in logged[0][1]["reason"]
    assert "secret" not in logged[0][1]["reason"]
    assert "https://" not in logged[0][1]["reason"]
    assert "a.bin" not in logged[0][1]["reason"]


def test_download_stream_error_does_not_leave_partial_final(monkeypatch, tmp_path):
    api = _client(monkeypatch)
    destination = _download_dir(monkeypatch, tmp_path)
    response = _download_response([b"old"], content_length="8", error=requests.RequestException("network"))
    monkeypatch.setattr(client_module.requests, "get", Mock(return_value=response))

    assert api.download_file(42, destination.name) == ""
    assert not destination.exists()
    assert _part_files(tmp_path) == []


def test_write_file_to_cancel_timeout_is_tolerant_and_stops_stream(monkeypatch):
    api = _client(monkeypatch)
    cancel_event = threading.Event()
    response = _download_response([b"first", b"second"], content_length="11")

    def stream_with_cancel():
        yield b"first"
        cancel_event.set()
        yield b"second"

    response.iter_content.return_value = stream_with_cancel()
    get = Mock(return_value=response)
    monkeypatch.setattr(client_module.requests, "get", get)
    output = BytesIO()

    assert api.write_file_to(42, output, cancel_event=cancel_event) is False
    assert output.getvalue() == b"first"
    assert get.call_args.kwargs["timeout"] == (10, 10)
    assert get.call_args.kwargs["timeout"][1] != 2


def test_write_file_to_timeout_keeps_retry_logic_with_cancel_event(monkeypatch):
    api = _client(monkeypatch)
    cancel_event = threading.Event()
    timed_out = _download_response([], content_length="2", error=requests.Timeout("read"))
    success = _download_response([b"ok"], content_length="2")
    get = Mock(side_effect=[timed_out, success])
    monkeypatch.setattr(client_module.requests, "get", get)
    output = BytesIO()

    assert api.write_file_to(42, output, cancel_event=cancel_event, max_retries=2) is True
    assert output.getvalue() == b"ok"


def test_write_file_to_http_403_keeps_safe_status_and_does_not_retry(monkeypatch):
    api = _client(monkeypatch)
    response = _download_response([], content_length="0")
    response.status_code = 403
    response.raise_for_status.side_effect = requests.HTTPError("403")
    get = Mock(return_value=response)
    monkeypatch.setattr(client_module.requests, "get", get)

    assert api.write_file_to(42, BytesIO(), max_retries=3) is False
    assert api._last_download_status == 403
    assert "доступ" in api._last_download_error.lower()
    get.assert_called_once()


def test_download_stream_error_preserves_existing_destination(monkeypatch, tmp_path):
    api = _client(monkeypatch)
    destination = _download_dir(monkeypatch, tmp_path)
    destination.write_bytes(b"old bytes")
    response = _download_response([b"new"], content_length="8", error=requests.RequestException("network"))
    monkeypatch.setattr(client_module.requests, "get", Mock(return_value=response))

    assert api.download_file(42, destination.name) == ""
    assert destination.read_bytes() == b"old bytes"
    assert _part_files(tmp_path) == []


def test_download_content_length_mismatch_preserves_destination(monkeypatch, tmp_path):
    api = _client(monkeypatch)
    destination = _download_dir(monkeypatch, tmp_path)
    destination.write_bytes(b"old bytes")
    response = _download_response([b"new"], content_length="8")
    monkeypatch.setattr(client_module.requests, "get", Mock(return_value=response))

    assert api.download_file(42, destination.name) == ""
    assert destination.read_bytes() == b"old bytes"
    assert _part_files(tmp_path) == []


def test_download_success_atomically_replaces_destination(monkeypatch, tmp_path):
    api = _client(monkeypatch)
    destination = _download_dir(monkeypatch, tmp_path)
    destination.write_bytes(b"old bytes")
    response = _download_response([b"new", b" bytes"], content_length="9")
    monkeypatch.setattr(client_module.requests, "get", Mock(return_value=response))

    result = api.download_file(42, destination.name)

    assert result == str(destination)
    assert destination.read_bytes() == b"new bytes"
    assert _part_files(tmp_path) == []


def test_download_success_without_content_length_reports_progress_safely(monkeypatch, tmp_path):
    api = _client(monkeypatch)
    destination = _download_dir(monkeypatch, tmp_path)
    response = _download_response([b"one", b"two"])
    monkeypatch.setattr(client_module.requests, "get", Mock(return_value=response))
    progress = Mock()

    result = api.download_file(42, destination.name, progress_cb=progress)

    assert result == str(destination)
    assert destination.read_bytes() == b"onetwo"
    assert progress.call_count == 0
    assert _part_files(tmp_path) == []


def test_download_replace_error_preserves_destination_and_cleans_part(monkeypatch, tmp_path):
    api = _client(monkeypatch)
    destination = _download_dir(monkeypatch, tmp_path)
    destination.write_bytes(b"old bytes")
    response = _download_response([b"new bytes"], content_length="9")
    monkeypatch.setattr(client_module.requests, "get", Mock(return_value=response))
    monkeypatch.setattr(client_module.os, "replace", Mock(side_effect=OSError("replace failed")))

    assert api.download_file(42, destination.name) == ""
    assert destination.read_bytes() == b"old bytes"
    assert _part_files(tmp_path) == []
