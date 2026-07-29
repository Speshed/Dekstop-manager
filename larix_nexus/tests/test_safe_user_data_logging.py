import builtins
import json
from types import SimpleNamespace
from unittest.mock import Mock

from larix_nexus.models.files_table import FilesTableModel
from larix_nexus.models import files_table
from larix_nexus.notifications import manager
from larix_nexus.ui import notification_handlers


def test_notification_save_and_load_do_not_print_user_data(monkeypatch):
    printed = Mock()
    monkeypatch.setattr(builtins, "print", printed)
    monkeypatch.setattr(
        manager,
        "load_notifications",
        lambda: {"subscriptions": {}},
    )
    monkeypatch.setattr(manager, "save_notifications", lambda _data: True)

    assert manager.save_folder_notification(1, 2, "C:/private", [{"name": "secret.txt"}])
    manager.load_folder_notifications()

    printed.assert_not_called()


def test_mime_data_payload_schema_is_unchanged_and_does_not_print(monkeypatch):
    printed = Mock()
    monkeypatch.setattr(builtins, "print", printed)
    model = FilesTableModel.__new__(FilesTableModel)
    model._data = [
        {
            "id": "file-secret",
            "type": "file",
            "name": "secret.txt",
            "folderId": "folder-secret",
            "projectId": "project-secret",
        }
    ]
    index = SimpleNamespace(row=lambda: 0, isValid=lambda: True)

    mime_data = model.mimeData([index])
    payload = json.loads(bytes(mime_data.data("application/x-larix-nexus-items")).decode())

    assert payload == {
        "source": "table",
        "items": [
            {
                "id": "file-secret",
                "type": "file",
                "name": "secret.txt",
                "folderId": "folder-secret",
                "projectId": "project-secret",
            }
        ],
    }
    printed.assert_not_called()


def test_mime_data_error_log_contains_only_exception_type(monkeypatch):
    class BadItem(dict):
        def get(self, *_args, **_kwargs):
            raise ValueError("private-file-name.txt")

    model = FilesTableModel.__new__(FilesTableModel)
    model._data = [BadItem()]
    index = SimpleNamespace(row=lambda: 0, isValid=lambda: True)
    logger = Mock()
    monkeypatch.setattr(files_table.logging, "getLogger", lambda *_args, **_kwargs: logger)

    model.mimeData([index])

    messages = " ".join(str(call) for call in logger.debug.call_args_list)
    assert "FILES_TABLE mime data item skipped" in messages
    assert "ValueError" in messages
    assert "private-file-name.txt" not in messages


def test_notification_poll_without_token_does_not_print(monkeypatch):
    printed = Mock()
    monkeypatch.setattr(builtins, "print", printed)
    window = SimpleNamespace(
        api=SimpleNamespace(token=None),
        _update_global_notification_badge=Mock(),
    )

    notification_handlers._check_notifications(window)

    printed.assert_not_called()


def test_empty_notification_poll_updates_badge_without_printing(monkeypatch):
    printed = Mock()
    monkeypatch.setattr(builtins, "print", printed)
    badge = Mock()
    window = SimpleNamespace(
        api=SimpleNamespace(token="token"),
        _update_global_notification_badge=badge,
    )
    monkeypatch.setattr(notification_handlers, "load_folder_notifications", lambda: [])

    notification_handlers._check_notifications(window)

    badge.assert_called_once_with()
    printed.assert_not_called()


def test_subscribe_empty_folder_saves_empty_baseline(monkeypatch):
    save = Mock()
    monkeypatch.setattr(notification_handlers, "is_folder_notification_enabled", lambda *_args: False)
    monkeypatch.setattr(notification_handlers, "save_folder_notification", save)
    monkeypatch.setattr(notification_handlers, "_folder_tree_path", lambda *_args: "Folder")
    monkeypatch.setattr(notification_handlers, "_current_workspace_id", lambda _self: 9)
    monkeypatch.setattr(notification_handlers, "QMessageBox", SimpleNamespace(information=Mock(), warning=Mock()))
    monkeypatch.setattr(notification_handlers.QTimer, "singleShot", Mock())
    window = SimpleNamespace(
        current_project_id=lambda: 3,
        _subscriptions={},
        _build_notification_file_state=Mock(return_value=[]),
        _cloud_state_for_folder=Mock(return_value={}),
        _update_notify_icon=Mock(),
        _build_notify_menu=Mock(),
    )

    notification_handlers.toggle_folder_notifications(window, {"id": 7, "title": "Folder"})

    save.assert_called_once_with(3, 7, "Folder", [], workspace_id=9)
    assert "7" in window._subscriptions


def test_folder_save_reports_false_when_atomic_write_fails(monkeypatch):
    monkeypatch.setattr(manager, "load_notifications", lambda: {"subscriptions": {}})
    monkeypatch.setattr(manager, "save_notifications", lambda _data: False)

    assert not manager.save_folder_notification(1, 2, "Folder", [])


def test_pending_save_reports_false_when_atomic_write_fails(monkeypatch):
    monkeypatch.setattr(manager, "load_notifications", lambda: {"subscriptions": {}})
    monkeypatch.setattr(manager, "save_notifications", lambda _data: False)

    assert not manager.save_pending_notifications({})


def test_failed_folder_save_does_not_add_runtime_subscription(monkeypatch):
    monkeypatch.setattr(notification_handlers, "is_folder_notification_enabled", lambda *_args: False)
    monkeypatch.setattr(notification_handlers, "save_folder_notification", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(notification_handlers, "_folder_tree_path", lambda *_args: "Folder")
    monkeypatch.setattr(notification_handlers, "_current_workspace_id", lambda _self: 9)
    warning = Mock()
    monkeypatch.setattr(notification_handlers, "QMessageBox", SimpleNamespace(information=Mock(), warning=warning))
    window = SimpleNamespace(
        current_project_id=lambda: 3,
        _subscriptions={},
        _build_notification_file_state=Mock(return_value=[]),
    )

    notification_handlers.toggle_folder_notifications(window, {"id": 7, "title": "Folder"})

    assert window._subscriptions == {}
    warning.assert_called_once()


def test_failed_folder_unsubscribe_keeps_runtime_subscription(monkeypatch):
    warning = Mock()
    monkeypatch.setattr(notification_handlers, "is_folder_notification_enabled", lambda *_args: True)
    monkeypatch.setattr(notification_handlers, "remove_folder_notification", lambda *_args: False)
    monkeypatch.setattr(notification_handlers, "_folder_tree_path", lambda *_args: "Folder")
    monkeypatch.setattr(notification_handlers, "_current_workspace_id", lambda _self: 9)
    monkeypatch.setattr(notification_handlers, "QMessageBox", SimpleNamespace(information=Mock(), warning=warning))
    window = SimpleNamespace(
        current_project_id=lambda: 3,
        _subscriptions={"7": {"file_state": []}},
    )

    notification_handlers.toggle_folder_notifications(window, {"id": 7, "title": "Folder"})

    assert "7" in window._subscriptions
    warning.assert_called_once()


def test_successful_folder_unsubscribe_removes_runtime_subscription(monkeypatch):
    information = Mock()
    monkeypatch.setattr(notification_handlers, "is_folder_notification_enabled", lambda *_args: True)
    monkeypatch.setattr(notification_handlers, "remove_folder_notification", lambda *_args: True)
    monkeypatch.setattr(notification_handlers, "_folder_tree_path", lambda *_args: "Folder")
    monkeypatch.setattr(notification_handlers, "_current_workspace_id", lambda _self: 9)
    monkeypatch.setattr(notification_handlers, "QMessageBox", SimpleNamespace(information=information, warning=Mock()))
    window = SimpleNamespace(
        current_project_id=lambda: 3,
        _subscriptions={"7": {"file_state": []}},
        _update_notify_icon=Mock(),
        _build_notify_menu=Mock(),
    )

    notification_handlers.toggle_folder_notifications(window, {"id": 7, "title": "Folder"})

    assert "7" not in window._subscriptions
    information.assert_called_once()


def test_bulk_unsubscribe_keeps_failed_subscription(monkeypatch):
    remove = Mock(side_effect=[True, False])
    warning = Mock()
    monkeypatch.setattr(
        notification_handlers,
        "load_folder_notifications",
        lambda: [{"project_id": 3, "folder_id": 7}, {"project_id": 3, "folder_id": 8}],
    )
    monkeypatch.setattr(notification_handlers, "remove_folder_notification", remove)
    monkeypatch.setattr(notification_handlers, "save_pending_notifications", Mock())
    monkeypatch.setattr(notification_handlers, "QMessageBox", SimpleNamespace(warning=warning, information=Mock()))
    window = SimpleNamespace(
        _subscriptions={"7": {}, "8": {}},
        _pending_notifications={"7": {}, "8": {}},
        folder_item_by_id={},
        _update_notify_icon=Mock(),
        _build_notify_menu=Mock(),
        status=SimpleNamespace(showMessage=Mock()),
    )

    notification_handlers._on_unsubscribe_all_notifications(window)

    assert window._subscriptions == {"8": {}}
    assert window._pending_notifications == {"8": {}}
    assert remove.call_count == 2
    warning.assert_called_once()


def test_bulk_unsubscribe_all_failures_do_not_report_full_success(monkeypatch):
    warning = Mock()
    monkeypatch.setattr(
        notification_handlers,
        "load_folder_notifications",
        lambda: [{"project_id": 3, "folder_id": 7}],
    )
    monkeypatch.setattr(notification_handlers, "remove_folder_notification", lambda *_args: False)
    monkeypatch.setattr(notification_handlers, "save_pending_notifications", Mock())
    monkeypatch.setattr(notification_handlers, "QMessageBox", SimpleNamespace(warning=warning, information=Mock()))
    window = SimpleNamespace(
        _subscriptions={"7": {}},
        _pending_notifications={"7": {}},
        folder_item_by_id={},
        _update_notify_icon=Mock(),
        _build_notify_menu=Mock(),
        status=SimpleNamespace(showMessage=Mock()),
    )

    notification_handlers._on_unsubscribe_all_notifications(window)

    assert window._subscriptions == {"7": {}}
    warning.assert_called_once()
    window.status.showMessage.assert_not_called()
