from larix_nexus.ui.operation_coordinator import FileOperationCoordinator
from larix_nexus.ui.folder_actions import copy_selected_action


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


def test_copy_entry_point_does_not_open_selection_while_sync_is_active():
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
            raise AssertionError("copy selection must not be inspected while busy")

    window = FakeWindow()
    copy_selected_action(window)

    assert window.warning_count == 1
