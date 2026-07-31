from larix_nexus.ui.operation_coordinator import FileOperationCoordinator
from larix_nexus.ui.folder_actions import copy_folder_action, copy_selected_action, _do_copy_folder
from larix_nexus.ui import main_window
from larix_nexus.ui import sync_handlers


def test_user_operation_has_exclusive_slot_and_release_allows_next():
    coordinator = FileOperationCoordinator()

    assert coordinator.try_acquire_user("copy")
    assert not coordinator.try_acquire_user("move")
    assert coordinator.active_operation == "copy"

    assert coordinator.release("copy")
    assert coordinator.try_acquire_user("upload")
    assert coordinator.release("upload")
    assert coordinator.try_acquire_user("download")
    assert coordinator.release("download")


def test_deferred_auto_sync_is_not_ui_operation_and_starts_after_release():
    callbacks = []
    coordinator = FileOperationCoordinator(lambda: callbacks.append("ready"))

    assert coordinator.try_acquire_user("copy")
    assert not coordinator.try_acquire_auto()
    assert coordinator.auto_pending
    assert callbacks == []

    assert coordinator.release("copy")
    assert callbacks == ["ready"]
    assert not coordinator.auto_pending
    assert coordinator.try_acquire_auto()
    assert coordinator.active_operation == "sync"
    assert coordinator.release("sync")


def test_coordinator_diagnostics_include_source_and_owner_transitions(caplog):
    coordinator = FileOperationCoordinator()
    with caplog.at_level("DEBUG"):
        assert coordinator.try_acquire_user("copy", source="copy")
        assert not coordinator.try_acquire_user("sync", source="manual_sync")
        assert not coordinator.release("sync", source="manual_sync")
        assert coordinator.release("copy", source="copy")

    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "source=copy" in text
    assert "source=manual_sync" in text
    assert "acquire-rejected" in text
    assert "release-ignored-owner-mismatch" in text


def test_new_coordinator_is_free_and_active_operation_is_not_reset_by_diagnostics():
    coordinator = FileOperationCoordinator()
    assert coordinator.active_operation is None
    assert coordinator.try_acquire_user("copy", source="copy")
    # Diagnostics are observational; an active worker remains protected.
    assert coordinator.active_operation == "copy"


def test_copy_entry_point_does_not_acquire_before_selection_while_sync_is_active():
    class FakeWindow:
        def __init__(self):
            self._file_operations = FileOperationCoordinator()
            self._file_operations.try_acquire_user("sync")
            self.warning_count = 0

        def _show_file_operation_busy_warning(self):
            self.warning_count += 1

        def _try_acquire_file_operation(self, operation):
            if self._file_operations.try_acquire_user(operation):
                return True
            self._show_file_operation_busy_warning()
            return False

        def get_checked_visible_items(self):
            return []
        def get_selected_items(self):
            return []

    window = FakeWindow()
    copy_selected_action(window)

    assert window.warning_count == 0
    assert window._file_operations.active_operation == "sync"


def test_copy_folder_cancel_leaves_coordinator_free():
    class Window:
        def __init__(self):
            self._file_operations = FileOperationCoordinator()

        def selected_item(self):
            return {"type": "folder", "id": "source", "name": "Source"}

        def _prompt_folder_select(self, *args, **kwargs):
            return {}

    window = Window()
    copy_folder_action(window)
    assert window._file_operations.active_operation is None


def test_copy_folder_rejected_at_real_start_does_not_release_other_owner():
    class Window:
        def __init__(self):
            self._file_operations = FileOperationCoordinator()
            self._file_operations.try_acquire_user("sync", source="manual_sync")
            self.api = type("Api", (), {})()

        def current_project_id(self):
            return "project"

        def _try_acquire_file_operation(self, operation, source=None):
            return self._file_operations.try_acquire_user(operation, source=source or operation)

    window = Window()
    _do_copy_folder(window, "source", "destination", "Copy", "/tmp/copy")
    assert window._file_operations.active_operation == "sync"


def test_busy_warning_does_not_replace_active_operation_status(monkeypatch):
    class Status:
        def __init__(self):
            self.messages = []

        def showMessage(self, *args):
            self.messages.append(args)

    class Window:
        status = Status()
        _file_operations = FileOperationCoordinator()

    window = Window()
    window._file_operations.try_acquire_user("copy")
    monkeypatch.setattr(main_window.QMessageBox, "information", lambda *args: None)

    main_window.MainWindow._show_file_operation_busy_warning(window)

    assert window.status.messages == []


def test_busy_warning_uses_status_fallback_only_when_idle(monkeypatch):
    class Status:
        def __init__(self):
            self.messages = []

        def showMessage(self, *args):
            self.messages.append(args)

    class Window:
        status = Status()
        _file_operations = FileOperationCoordinator()

    window = Window()
    def fail_message_box(*args):
        raise RuntimeError("no GUI")

    monkeypatch.setattr(main_window.QMessageBox, "information", fail_message_box)
    main_window.MainWindow._show_file_operation_busy_warning(window)

    assert window.status.messages == [("Дождитесь завершения текущей операции", 5000)]


def test_sync_all_is_rejected_before_starting_when_copy_is_active():
    class Window:
        def __init__(self):
            self._file_operations = FileOperationCoordinator()
            self._file_operations.try_acquire_user("copy")
            self.warning_count = 0
            self.sync2 = type("Sync", (), {"map": {"one": {}}})()

        def _try_acquire_file_operation(self, operation):
            if self._file_operations.try_acquire_user(operation):
                return True
            self.warning_count += 1
            return False

    window = Window()
    sync_handlers._on_sync_all_clicked(window)

    assert window.warning_count == 1
    assert window._file_operations.active_operation == "copy"
    assert not hasattr(window, "_sync_all_pending")


def test_sync_all_group_slot_releases_once_after_last_fast_worker():
    class Window:
        def __init__(self):
            self._file_operations = FileOperationCoordinator()
            self._file_operations.try_acquire_user("sync")
            self._sync_all_operation_active = True
            self._sync_all_pending = 2

        def _release_file_operation(self, operation):
            self._file_operations.release(operation)

    window = Window()
    window._sync_all_pending = max(0, window._sync_all_pending - 1)
    assert not sync_handlers._finish_sync_all_if_done(window, "first_worker")
    assert window._sync_all_pending == 1
    assert window._file_operations.active_operation == "sync"

    window._sync_all_pending = max(0, window._sync_all_pending - 1)
    assert sync_handlers._finish_sync_all_if_done(window, "last_worker")
    assert window._sync_all_pending == 0
    assert window._sync_all_operation_active is False
    assert window._file_operations.active_operation is None
    assert not sync_handlers._finish_sync_all_if_done(window, "duplicate_callback")
