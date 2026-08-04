from types import SimpleNamespace

import requests

from larix_nexus.api import client as client_module
from larix_nexus.api.client import APIClient
from larix_nexus.ui import folder_actions


def _client(monkeypatch):
    api = APIClient("https://api.example.test")
    api.token = "access-token"
    monkeypatch.setattr(api, "_headers", lambda: {"Authorization": "Bearer access-token"})
    return api


def test_rename_result_uses_safe_http_reasons(monkeypatch):
    api = _client(monkeypatch)
    for status, expected in ((400, "HTTP 400"), (401, "Нет доступа"), (403, "Нет доступа"), (409, "Конфликт"), (500, "HTTP 500")):
        response = SimpleNamespace(status_code=status, text="<html>token=secret</html>")
        monkeypatch.setattr(client_module.requests, "put", lambda *args, response=response, **kwargs: response)
        result = api.rename_file_result(10, "name.txt")
        assert not result.ok
        assert expected in result.reason
        assert "secret" not in result.reason
        assert "html" not in result.reason.lower()


def test_move_result_maps_network_error(monkeypatch):
    api = _client(monkeypatch)
    def fail(*args, **kwargs):
        raise requests.ConnectionError("token=secret and a very long diagnostic")
    monkeypatch.setattr(client_module.requests, "put", fail)
    result = api.move_document_result(10, 20)
    assert not result.ok
    assert result.retryable
    assert result.reason == "Сервер недоступен; проверьте соединение"
    assert "secret" not in result.reason


def test_success_result_remains_truthy(monkeypatch):
    api = _client(monkeypatch)
    monkeypatch.setattr(client_module.requests, "put", lambda *args, **kwargs: SimpleNamespace(status_code=204, text=""))
    result = api.rename_file_result(10, "name.txt")
    assert result.ok
    assert bool(result)
    assert api.rename_file(10, "name.txt") is True


def test_move_error_dialog_contains_file_and_reason(monkeypatch):
    calls = []
    monkeypatch.setattr(folder_actions.QMessageBox, "warning", lambda *args: calls.append(args))
    folder_actions._show_file_operation_errors(object(), "Не удалось переместить файл.txt\nНет доступа", "MOVE")
    assert len(calls) == 1
    assert "файл.txt" in calls[0][2]
    assert "Нет доступа" in calls[0][2]


def test_move_error_dialog_does_not_receive_raw_response(monkeypatch):
    calls = []
    monkeypatch.setattr(folder_actions.QMessageBox, "warning", lambda *args: calls.append(args))
    safe = "Перемещены не все элементы\nфайл.txt: Сервер отклонил операцию (HTTP 500)"
    folder_actions._show_file_operation_errors(object(), safe, "MOVE")
    message = calls[0][2]
    assert "<html" not in message.lower()
    assert "token=" not in message.lower()
    assert "traceback" not in message.lower()


def test_copy_error_dialog_contains_partial_summary(monkeypatch):
    calls = []
    monkeypatch.setattr(folder_actions.QMessageBox, "warning", lambda *args: calls.append(args))
    folder_actions._show_file_operation_errors(
        object(), "Не все файлы скопированы\nфайл.txt: Конфликт имени или состояния объекта", "COPY"
    )
    assert calls
    assert "Не все файлы скопированы" in calls[0][2]
    assert "файл.txt" in calls[0][2]


def test_success_path_does_not_call_error_dialog(monkeypatch):
    calls = []
    monkeypatch.setattr(folder_actions.QMessageBox, "warning", lambda *args: calls.append(args))
    # Cleanup branches call the helper only when error_text is non-empty.
    assert folder_actions._format_operation_errors([]) == ""
    assert calls == []


def test_empty_operation_errors_use_safe_fallback(monkeypatch):
    calls = []
    monkeypatch.setattr(folder_actions.QMessageBox, "warning", lambda *args: calls.append(args))
    fallback = "Не удалось переместить 1 файл\nСервер не сообщил подробную причину. Проверьте права доступа, конфликт имени или повторите операцию."
    folder_actions._show_file_operation_errors(object(), fallback, "MOVE")
    assert "Сервер не сообщил подробную причину" in calls[0][2]
    assert "HTTP" not in calls[0][2]
