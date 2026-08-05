import inspect
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from larix_nexus.ui import main_window


def _app():
    return QApplication.instance() or QApplication([])


def test_compare_button_disabled_for_single_version():
    _app()
    button = QPushButton()
    allowed = main_window._configure_version_compare_button(button, 1, "Для сравнения нужны как минимум 2 версии файла.")
    assert allowed is False
    assert button.isEnabled() is False
    assert button.toolTip()


def test_compare_button_enabled_for_two_versions():
    _app()
    button = QPushButton()
    allowed = main_window._configure_version_compare_button(button, 2, "Для сравнения нужны как минимум 2 версии файла.")
    assert allowed is True
    assert button.isEnabled() is True
    assert button.toolTip() == ""


def test_versions_dialog_has_neutral_header_style():
    source = inspect.getsource(main_window.MainWindow._show_versions_for_node)
    assert "QHeaderView::section" in source
    assert "QHeaderView::section:hover" in source
    assert "QHeaderView::section:pressed" in source
    assert "hh.setHighlightSections(False)" in source


def test_version_context_menu_exec_is_inside_handler():
    source = inspect.getsource(main_window.MainWindow._show_versions_for_node)
    handler_start = source.index("def _version_context_menu")
    exec_pos = source.index("chosen = menu.exec(")
    assert exec_pos > handler_start
    assert "QTimer.singleShot(0, _open_version_public_link)" in source
    assert "table.verticalHeader().setHighlightSections(False)" in source
