from types import SimpleNamespace

from larix_nexus.ui import sync_handlers


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
