import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QToolButton

from larix_nexus.ui.main_window import MainWindow
from larix_nexus.utils.i18n import t


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


def test_selection_mode_uses_toolbar_indicator_without_resizing_table(qapp):
    window = MainWindow()
    window.show()
    qapp.processEvents()
    try:
        indicator = window.selection_mode_indicator
        assert isinstance(indicator, QToolButton)
        assert indicator.isCheckable()
        assert indicator.iconSize() == window.btn_delete.iconSize()
        assert not indicator.isVisible()
        assert not window.selection_mode_panel.isVisible()
        assert not indicator.icon().isNull()
        assert indicator.toolTip() == t("selection_mode.hint")

        table_y = window.table.geometry().y()
        window.checked.add("selection-test")
        window._update_selection_mode_panel()
        qapp.processEvents()

        assert indicator.isVisible()
        assert indicator.isChecked()
        assert window.selection_mode_panel.isVisible() is False
        assert window.table.geometry().y() == table_y

        window.checked.clear()
        window._update_selection_mode_panel()
        assert not indicator.isVisible()
        assert not indicator.isChecked()
        assert window.table.geometry().y() == table_y
    finally:
        window.close()
        window.deleteLater()


def test_selection_mode_indicator_is_thematic_and_accepts_tooltip_hover(qapp):
    window = MainWindow()
    try:
        window._on_theme_toggled(True)
        dark_image = window.selection_mode_indicator.icon().pixmap(window.selection_mode_indicator.iconSize()).toImage()
        dark_pixels = [
            dark_image.pixelColor(x, y)
            for y in range(dark_image.height())
            for x in range(dark_image.width())
            if dark_image.pixelColor(x, y).alpha() > 20
        ]
        assert dark_pixels
        assert sum((p.red() + p.green() + p.blue()) / 3 for p in dark_pixels) / len(dark_pixels) > 150

        window._on_theme_toggled(False)
        light_image = window.selection_mode_indicator.icon().pixmap(window.selection_mode_indicator.iconSize()).toImage()
        light_pixels = [
            light_image.pixelColor(x, y)
            for y in range(light_image.height())
            for x in range(light_image.width())
            if light_image.pixelColor(x, y).alpha() > 20
        ]
        assert light_pixels
        assert sum((p.red() + p.green() + p.blue()) / 3 for p in light_pixels) / len(light_pixels) < 150
        assert not window.selection_mode_indicator.testAttribute(Qt.WA_TransparentForMouseEvents)
        assert window.selection_mode_indicator.toolTip() == t("selection_mode.hint")
        assert "selectionModeIndicator:checked" in window.selection_mode_indicator.styleSheet()
    finally:
        window.close()
        window.deleteLater()
