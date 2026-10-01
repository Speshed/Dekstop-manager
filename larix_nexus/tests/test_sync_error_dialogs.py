from types import SimpleNamespace

import pytest

from larix_nexus.ui import sync_handlers
from larix_nexus.sync import manager as sync_manager


def test_sync_error_summary_is_bounded_and_deduplicated(monkeypatch):
    shown = []
    monkeypatch.setattr(sync_handlers.safe_dialogs, "show_warning", lambda *_args: shown.append(_args))

    sync_handlers._show_sync_errors_summary(
        SimpleNamespace(),
        "initial",
        "C:/sync",
        ["a.txt: HTTP 403: нет доступа", "a.txt: HTTP 403: нет доступа"]
        + [f"file-{i}: HTTP 500" for i in range(25)],
        error_count=27,
    )

    assert len(shown) == 1
    body = shown[0][2]
    assert body.count("a.txt: HTTP 403") == 1
    assert "И ещё" in body
    assert "_sync_errors.log" in body


def test_sync_error_summary_uses_fallback_when_details_are_missing(monkeypatch):
    shown = []
    monkeypatch.setattr(sync_handlers.safe_dialogs, "show_warning", lambda *_args: shown.append(_args))

    sync_handlers._show_sync_errors_summary(SimpleNamespace(), "auto", "C:/sync", [], error_count=3)

    assert len(shown) == 1
    assert "ошибок: 3" in shown[0][2]
    assert "sync.log" in shown[0][2]


def test_auto_sync_error_summary_uses_safe_warning_once(monkeypatch):
    shown = []
    monkeypatch.setattr(sync_handlers.safe_dialogs, "show_warning", lambda *_args: shown.append(_args))
    window = SimpleNamespace(
        _show_status_message=lambda *_args, **_kwargs: None,
        _refresh_synced_folder=lambda *_args: None,
        _show_sync_errors_summary=lambda mode, path, errors, **kwargs: sync_handlers._show_sync_errors_summary(window, mode, path, errors, **kwargs),
        folder_item_by_id={},
    )
    sync_handlers._on_auto_sync_result(
        window,
        [{
            "success": False,
            "folder_id": "1",
            "local_root": "C:/sync",
            "stats": {"errors": ["file.pdf: HTTP 403: нет доступа"]},
            "errors": [],
        }],
    )
    assert len(shown) == 1


def test_auto_sync_result_merges_top_level_and_mapping_errors(monkeypatch):
    shown = []
    monkeypatch.setattr(sync_handlers.safe_dialogs, "show_warning", lambda *_args: shown.append(_args))
    statuses = []
    window = SimpleNamespace(
        _show_status_message=lambda *args, **kwargs: statuses.append((args, kwargs)),
        _refresh_synced_folder=lambda *_args: None,
        _show_sync_errors_summary=lambda mode, path, errors, **kwargs: sync_handlers._show_sync_errors_summary(window, mode, path, errors, **kwargs),
        folder_item_by_id={},
    )
    sync_handlers._on_auto_sync_result(window, [{
        "success": False,
        "folder_id": "1",
        "local_root": "C:/sync",
        "stats": {"errors": []},
        "errors": ["project_id_missing"],
        "mapping_errors": ["mapping_missing", "folder_busy"],
    }])
    assert len(shown) == 1
    body = shown[0][2]
    assert "project_id_missing" in body
    assert "mapping_missing" in body
    assert "folder_busy" not in body
    assert "Пропущено папок: 1" in statuses[0][0][0]


def test_auto_sync_error_channels_are_normalized_and_deduplicated():
    errors, busy = sync_handlers._normalise_auto_sync_errors({
        "stats": {"errors": ["project_id_missing", "folder_busy"]},
        "errors": ["project_id_missing", "initial_ok_false"],
        "mapping_errors": ["mapping_missing", "folder_busy"],
    })
    assert errors == ["project_id_missing", "initial_ok_false", "mapping_missing"]
    assert busy == ["folder_busy"]


def test_folder_busy_message_variants_are_not_real_errors():
    assert sync_handlers._normalise_auto_sync_errors({"errors": ["Folder busy"]}) == ([], ["Folder busy"])
    assert sync_handlers._normalise_auto_sync_errors({"errors": ["Mapping invalid: folder_busy"]}) == (
        [], ["Mapping invalid: folder_busy"]
    )


def test_sync_error_records_exclude_busy_and_include_context():
    records = sync_handlers._sync_error_records({
        "local_root": "C:/sync",
        "errors": ["HTTP 500", "Folder busy"],
        "mapping_errors": ["mapping_missing"],
    }, "auto")
    assert [item["error"] for item in records] == ["HTTP 500", "mapping_missing"]
    assert all(item["mode"] == "auto" and item["folder"] == "C:/sync" for item in records)


def test_error_button_visibility_follows_persistent_records(monkeypatch):
    class Button:
        def __init__(self):
            self.visible = None
        def setVisible(self, value):
            self.visible = bool(value)

    button = Button()
    window = SimpleNamespace(btn_sync_errors=button)
    monkeypatch.setattr(sync_handlers, "load_sync_errors", lambda: [])
    sync_handlers._update_sync_error_button(window)
    assert button.visible is False
    monkeypatch.setattr(sync_handlers, "load_sync_errors", lambda: [{"error": "boom"}])
    sync_handlers._update_sync_error_button(window)
    assert button.visible is True


def test_sync_error_clipboard_text_includes_log_paths():
    text = sync_handlers._format_sync_errors_text(
        [{"timestamp": "2026-01-01T12:00:00", "mode": "auto", "folder": "C:/sync", "error": "HTTP 500"}],
        "C:/logs/sync.log",
        ["C:/sync/_sync_errors.log"],
    )
    assert "HTTP 500" in text
    assert "C:/logs/sync.log" in text
    assert "C:/sync/_sync_errors.log" in text


def test_auto_worker_exception_is_structured_failure_without_success_signal():
    class FailingManager:
        def sync_all(self, **_kwargs):
            raise RuntimeError("top-level sync failure")

    runner = sync_manager._AutoSyncAllRunner(FailingManager())
    finished = []
    runner.sig_finished.connect(finished.append)
    runner.run()

    assert len(finished) == 1
    assert finished[0][0]["worker_exception"] is True
    assert finished[0][0]["success"] is False
    assert "top-level sync failure" in finished[0][0]["errors"]


def test_manual_worker_exception_is_structured_failure():
    class FailingManager:
        def sync_now(self, *_args, **_kwargs):
            raise RuntimeError("manual worker failure")

    runner = sync_manager._ImmediateSyncRunner(FailingManager(), 42)
    results = []
    runner.sig_result.connect(results.append)
    runner.run()

    assert len(results) == 1
    assert results[0]["worker_exception"] is True
    assert results[0]["folder_id"] == "42"
    assert "manual worker failure" in results[0]["errors"]


def test_sync_all_does_not_emit_success_finished_on_top_level_exception():
    manager = sync_manager.FolderSyncManager.__new__(sync_manager.FolderSyncManager)
    sync_manager.QtCore.QObject.__init__(manager)
    manager.api = SimpleNamespace(token="token")
    manager.map = {"1": {}}
    manager._busy_folders = set()
    manager._validate_mapping_for_sync = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
    finished = []
    manager.autoSyncFinished.connect(lambda: finished.append(True))

    with pytest.raises(RuntimeError, match="boom"):
        manager.sync_all(sync_mode="auto")

    assert finished == []


def test_successful_sync_does_not_show_error_summary():
    summary_calls = []
    status_calls = []
    window = SimpleNamespace(
        _sync_path="C:/sync",
        _show_status_message=lambda *args, **kwargs: status_calls.append((args, kwargs)),
        _show_sync_errors_summary=lambda *args, **kwargs: summary_calls.append((args, kwargs)),
    )

    sync_handlers._on_sync_finished(window, True, 0)

    assert summary_calls == []
    assert status_calls
    assert "Синхронизация завершена" in status_calls[0][0][0]


def test_cancelled_initial_sync_does_not_show_error_summary():
    summary_calls = []
    status_calls = []
    worker = SimpleNamespace(_cancelled=True, local_path="C:/sync", _errors=[])
    window = SimpleNamespace(
        _sync_worker=worker,
        _sync_path="C:/sync",
        _show_status_message=lambda *args, **kwargs: status_calls.append((args, kwargs)),
        _show_sync_errors_summary=lambda *args, **kwargs: summary_calls.append((args, kwargs)),
    )

    sync_handlers._on_sync_finished(window, False, 0)

    assert summary_calls == []
    assert status_calls
    assert "отменена" in status_calls[0][0][0].lower()
