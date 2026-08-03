import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QStatusBar

from larix_nexus.ui.main_window import MainWindow
from larix_nexus.ui.widgets import BusyDots, FileOperationStatusShell, FileOperationStatusWidget, RainbowStatusProgress
from larix_nexus.constants import THEME_DARK, THEME_LIGHT


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


def test_operation_status_widget_lifecycle_and_cancel(qapp):
    widget = FileOperationStatusWidget()
    assert not widget.isVisible()
    calls = []

    widget.start("copy", "source", "destination", 3, lambda: calls.append("cancel"))
    assert widget.isVisible()
    assert widget.title_label.text() == "Копирование файлов…"
    assert widget.source_label._full_text == "source"
    assert widget.destination_label._full_text == "destination"
    assert widget._direction == "right"

    widget.set_progress(1, 3, "item")
    assert widget.progress_bar.value() == 1
    assert widget.progress_bar.maximum() == 3
    widget.cancel_button.click()
    assert calls == ["cancel"]

    widget.finish()
    assert widget.isVisible()
    assert not widget.progress.isVisible()
    assert widget._cancel_callback is None
    widget.deleteLater()


def test_operation_status_widget_dark_theme_and_direction(qapp):
    widget = FileOperationStatusWidget()
    widget.set_dark_theme(True)
    assert "background: transparent" in widget.styleSheet()
    assert "#ffffff" in widget.styleSheet()
    right = widget.arrow_label.pixmap().toImage()

    widget.set_direction("left")
    left = widget.arrow_label.pixmap().toImage()
    assert right != left
    widget.deleteLater()


def test_copy_move_cancel_widgets_are_not_created_anymore():
    source = (Path(__file__).resolve().parents[1] / "ui" / "folder_actions.py").read_text(encoding="utf-8")
    assert "copyCancelBtn" not in source
    assert "moveCancelBtn" not in source


def test_main_window_progress_shows_generic_panel_and_mirrors_rainbow_state(qapp):
    status = QStatusBar()
    progress = RainbowStatusProgress()
    panel = FileOperationStatusWidget()
    assert len(panel.findChildren(RainbowStatusProgress)) == 1
    assert not panel.findChildren(BusyDots)
    window = SimpleNamespace(
        status=status,
        progress=progress,
        file_operation_status=panel,
        _progress_cancel_handler=None,
    )
    status.messageChanged.connect(lambda message: MainWindow._on_status_message_changed(window, message))
    progress.rangeChanged.connect(lambda minimum, maximum: MainWindow._on_progress_range_changed(window, minimum, maximum))
    progress.valueChanged.connect(lambda value: MainWindow._on_progress_value_changed(window, value))

    MainWindow._set_progress_visible(window, True)
    assert panel.isVisible()
    assert panel.progress.isVisible()
    assert panel.progress.width() > 0
    assert panel.progress.parent() is panel
    assert panel._mode == "generic"
    assert panel.title_label.text() == "Загрузка..."

    status.showMessage("Загрузка…")
    assert panel.title_label.text() == "Загрузка…"
    status.showMessage("Очень длинный статус " * 40)
    assert panel.progress.width() > 0
    progress.setRange(0, 0)
    assert panel.progress_bar.minimum() == 0
    assert panel.progress_bar.maximum() == 0
    assert panel.progress._indeterminate is True
    progress.setRange(0, 10)
    progress.setValue(4)
    assert panel.progress_bar.maximum() == 10
    assert panel.progress_bar.value() == 4

    MainWindow._set_progress_visible(window, False)
    assert panel.isVisible()
    assert not panel.progress.isVisible()
    assert panel.title_label.text().startswith("Очень длинный статус")
    panel.deleteLater()
    progress.deleteLater()
    status.deleteLater()


def test_transfer_panel_has_priority_over_generic_visibility(qapp):
    status = QStatusBar()
    progress = RainbowStatusProgress()
    panel = FileOperationStatusWidget()
    window = SimpleNamespace(status=status, progress=progress, file_operation_status=panel, _progress_cancel_handler=None)

    panel.start_transfer("copy", "from", "to", 2)
    MainWindow._set_progress_visible(window, False)
    status.showMessage("Загрузка…")
    MainWindow._on_status_message_changed(window, status.currentMessage())

    assert panel.isVisible()
    assert panel._mode == "transfer"
    assert panel.title_label.text() == "Копирование файлов…"
    panel.finish()
    panel.deleteLater()
    progress.deleteLater()
    status.deleteLater()


def test_status_shell_remains_visible_when_operation_panel_finishes(qapp):
    status = QStatusBar()
    status.setObjectName("operationStatusBar")
    status.setFixedHeight(56)
    window = SimpleNamespace(status=status)
    MainWindow._set_status_shell_theme(window, False)
    status.show()
    shell = FileOperationStatusShell(status)
    status.addWidget(shell)
    window.file_operation_shell = shell
    panel = shell.operation_widget
    assert len(shell.findChildren(RainbowStatusProgress)) == 1
    panel.start_transfer("copy", "from", "to", 1)
    panel.finish()

    assert status.isVisible()
    assert shell.isVisible()
    assert shell.height() == 56
    assert "border-top" not in status.styleSheet()
    assert "border: none" in status.styleSheet()
    assert shell.card.objectName() == "unifiedStatusCard"
    assert shell.card.testAttribute(Qt.WA_StyledBackground)
    assert "#ffffff" in shell.card.styleSheet()
    assert "#dedede" in shell.card.styleSheet()
    assert panel.isVisible()
    assert not panel.progress.isVisible()

    MainWindow._set_status_shell_theme(window, True)
    assert "#1e1e1e" in shell.card.styleSheet()
    assert "#1c1c1c" not in shell.card.styleSheet()
    assert "#383838" in shell.card.styleSheet()
    shell.deleteLater()
    status.deleteLater()


def test_generic_loading_text_is_cleared_when_progress_finishes(qapp):
    status = QStatusBar()
    progress = RainbowStatusProgress()
    panel = FileOperationStatusWidget()
    window = SimpleNamespace(
        status=status,
        progress=progress,
        file_operation_status=panel,
        _progress_cancel_handler=None,
        _generic_status_text="",
        _sync_status_lock=False,
    )
    status.showMessage("Загрузка…")
    MainWindow._set_progress_visible(window, True)
    assert panel.title_label.text() == "Загрузка…"
    MainWindow._set_progress_visible(window, False)
    assert panel.title_label.text() == ""
    status.deleteLater()
    progress.deleteLater()
    panel.deleteLater()


def test_main_window_status_card_is_permanent_for_messages_and_operations(qapp):
    window = MainWindow()
    window.show()
    qapp.processEvents()
    card = window.file_operation_shell
    panel = window.file_operation_status

    assert card.isVisible()
    window.status.showMessage("Загружено проектов: 4")
    qapp.processEvents()
    assert card.isVisible()
    assert panel.title_label.text() == "Загружено проектов: 4"

    window.status.clearMessage()
    qapp.processEvents()
    assert card.isVisible()

    panel.start_transfer("copy", "source", "destination", 1)
    panel.finish()
    assert card.isVisible()

    MainWindow._set_progress_visible(window, True)
    MainWindow._set_progress_visible(window, False)
    assert card.isVisible()

    MainWindow._set_status_shell_theme(window, True)
    assert card.isVisible()
    MainWindow._set_status_shell_theme(window, False)
    assert card.isVisible()

    window.close()
    window.deleteLater()


def test_main_window_status_card_has_symmetric_vertical_insets(qapp):
    window = MainWindow()
    window.show()
    qapp.processEvents()

    status = window.status
    shell = window.file_operation_shell
    card = shell.card
    card_top = shell.y() + card.y()
    card_bottom = card_top + card.height()
    card_left = shell.x() + card.x()
    card_right = card_left + card.width()
    contents = status.contentsRect()
    contents_left = contents.x()
    contents_right = contents.x() + contents.width()

    assert not status.isSizeGripEnabled()
    assert card_top > 0
    assert card_bottom < status.height()
    assert card_top == status.height() - card_bottom
    # Offscreen Qt keeps a 2 px native inset on the permanent-widget side
    # even after the QSizeGrip reserve is disabled.
    assert abs((card_left - contents_left) - (contents_right - card_right)) <= 2

    window.close()
    window.deleteLater()


def test_main_window_initial_status_card_follows_applied_theme(qapp):
    previous_theme = qapp.property("nik_theme")
    qapp.setProperty("nik_theme", THEME_DARK)
    dark_window = MainWindow()
    try:
        assert dark_window._current_theme == THEME_DARK
        assert dark_window.theme_toggle.isChecked()
        assert "#1e1e1e" in dark_window.file_operation_shell.card.styleSheet()
        assert "background-color: #ffffff" not in dark_window.file_operation_shell.card.styleSheet()
        assert dark_window.file_operation_status._dark is True

        dark_window._on_theme_toggled(False)
        assert dark_window._current_theme == THEME_LIGHT
        assert not dark_window.theme_toggle.isChecked()
        assert "#ffffff" in dark_window.file_operation_shell.card.styleSheet()
        assert dark_window.file_operation_status._dark is False

        dark_window._on_theme_toggled(True)
        assert dark_window._current_theme == THEME_DARK
        assert dark_window.file_operation_status._dark is True
    finally:
        dark_window.close()
        dark_window.deleteLater()
        qapp.setProperty("nik_theme", previous_theme)

    qapp.setProperty("nik_theme", THEME_LIGHT)
    light_window = MainWindow()
    try:
        assert light_window._current_theme == THEME_LIGHT
        assert not light_window.theme_toggle.isChecked()
        assert "#ffffff" in light_window.file_operation_shell.card.styleSheet()
        assert light_window.file_operation_status._dark is False
    finally:
        light_window.close()
        light_window.deleteLater()
        qapp.setProperty("nik_theme", previous_theme)
