import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from larix_nexus.ui.table_operations import _update_actions_enabled


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


def _window(qapp, items):
    buttons = SimpleNamespace(
        btn_download=QPushButton(),
        btn_upload=QPushButton(),
        btn_rename=QPushButton(),
        btn_compare=QPushButton(),
        btn_move=QPushButton(),
        btn_copy=QPushButton(),
        btn_delete=QPushButton(),
    )
    table = SimpleNamespace(
        selectionModel=lambda: SimpleNamespace(selectedRows=lambda: []),
    )
    window = SimpleNamespace(
        **vars(buttons),
        table=table,
        current_project_id=lambda: 1,
        selected_item=lambda: items[0] if items else {},
        get_action_selected_items=lambda: list(items),
    )
    return window


def test_no_selection_disables_copy_and_move(qapp):
    window = _window(qapp, [])

    _update_actions_enabled(window)

    assert not window.btn_copy.isEnabled()
    assert not window.btn_move.isEnabled()


def test_selected_file_enables_copy_and_move(qapp):
    window = _window(qapp, [{"type": "file", "id": 1}])

    _update_actions_enabled(window)

    assert window.btn_copy.isEnabled()
    assert window.btn_move.isEnabled()


def test_checked_file_with_empty_row_selection_enables_both(qapp):
    window = _window(qapp, [{"type": "file", "id": 1}])

    _update_actions_enabled(window)

    assert window.btn_copy.isEnabled()
    assert window.btn_move.isEnabled()


def test_selected_folder_allows_copy_and_explains_disabled_move(qapp):
    window = _window(qapp, [{"type": "folder", "id": 2}])

    _update_actions_enabled(window)

    assert window.btn_copy.isEnabled()
    assert not window.btn_move.isEnabled()
    assert "Перемещ" in window.btn_move.toolTip()


def test_clearing_last_checked_item_disables_both(qapp):
    window = _window(qapp, [{"type": "file", "id": 1}])
    _update_actions_enabled(window)
    window.get_action_selected_items = lambda: []

    _update_actions_enabled(window)

    assert not window.btn_copy.isEnabled()
    assert not window.btn_move.isEnabled()


def test_active_buttons_call_each_handler_once(qapp):
    window = _window(qapp, [{"type": "file", "id": 1}])
    copy_handler = Mock()
    move_handler = Mock()
    window.btn_copy.clicked.connect(copy_handler)
    window.btn_move.clicked.connect(move_handler)
    _update_actions_enabled(window)

    window.btn_copy.click()
    window.btn_move.click()

    copy_handler.assert_called_once()
    move_handler.assert_called_once()
