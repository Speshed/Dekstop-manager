import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QAbstractItemView
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtTest import QTest
from PySide6.QtGui import QColor, QPalette
from larix_nexus.api.client import PopupComboBox
from larix_nexus.ui.ui_helpers import _style_combo_popup_view

from larix_nexus.ui.dialogs import BatchDownloadDialog, BatchUploadDialog, ConflictListItem
from larix_nexus.constants import CHECK_ICON_OFF_PATH, CHECK_ICON_ON_PATH, CHECK_ICON_MID_PATH


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_conflict_item_preserves_filename_and_tooltip(qapp):
    path = "root/very-long-parent-directory/Test file 017.png"
    item = ConflictListItem(None, path, {})
    item.resize(220, 50)
    item.show()
    qapp.processEvents()

    assert item._full_path == path
    assert item.name_label.toolTip() == path
    assert item.name_label.text().startswith("Test file")

    updated = "root/another-parent/Test file 031.png"
    item.set_name(updated)
    item.set_active(True)
    qapp.processEvents()
    assert item._full_path == updated
    assert item.name_label.toolTip() == updated
    assert item.name_label.text().startswith("Test file")
    item.close()


def test_target_combos_use_controlled_popup(qapp):
    projects = PopupComboBox()
    projects.setObjectName("projectsCombo")
    projects.addItems(["Select", "One"])
    workspaces = PopupComboBox()
    workspaces.setObjectName("workspacesCombo")
    workspaces.addItems(["Select", "One"])
    dark_palette = workspaces.palette()
    dark_palette.setColor(QPalette.Window, QColor("#121212"))
    workspaces.setPalette(dark_palette)
    _style_combo_popup_view(projects, "projectsComboView", dark=False)
    _style_combo_popup_view(workspaces, "workspacesComboView", dark=True)
    for combo, view_name, hover in (
        (projects, "projectsComboView", "#FFE3C2"),
        (
            workspaces,
            "workspacesComboView",
            "rgba(247, 146, 30, 0.15)",
        ),
    ):
        view = combo.view()
        assert view.objectName() == view_name
        assert view.hasMouseTracking()
        combo.show()
        combo.showPopup()
        qapp.processEvents()
        popup = combo._controlled_popup
        popup_view = combo._controlled_popup_view
        assert popup is not view.window()
        assert popup.objectName() == "controlledComboPopup"
        popup_qss = popup.styleSheet()
        assert "border: 1px solid #F7921E" in popup_qss
        assert "QListView::item:hover" in popup_qss
        assert hover in popup_qss
        assert "QListView::item:selected:hover" in popup_qss
        assert popup_qss.count(hover) >= 2
        assert "border-color" not in popup_qss
        assert "background: transparent" in popup_qss
        assert "margin: 0px; padding: 8px 10px" in popup_qss
        assert popup_view.editTriggers() == QAbstractItemView.NoEditTriggers
        combo.hidePopup()


def test_controlled_popup_selects_and_closes(qapp):
    combo = PopupComboBox()
    combo.addItems(["Select", "One"])
    opened = []
    combo.aboutToPopup.connect(lambda: opened.append(True))
    combo.show()
    combo.showPopup()
    qapp.processEvents()

    assert opened == [True]
    popup_view = combo._controlled_popup_view
    popup_view.clicked.emit(combo.model().index(1, 0))
    qapp.processEvents()
    assert combo.currentIndex() == 1
    assert combo._controlled_popup is None


def test_popup_closes_before_queued_index_commit(qapp):
    events = []

    class TrackedPopupComboBox(PopupComboBox):
        def hidePopup(self):
            events.append("hide")
            super().hidePopup()

        def setCurrentIndex(self, index):
            events.append(("set", index))
            super().setCurrentIndex(index)

    combo = TrackedPopupComboBox()
    combo.addItems(["Select", "One"])
    combo.show()
    combo.showPopup()
    events.clear()
    combo._popup_item_activated(combo.model().index(1, 0))

    assert events == ["hide"]
    qapp.processEvents()
    assert events == ["hide", ("set", 1)]
    assert combo.currentIndex() == 1


def test_controlled_popup_closes_on_escape(qapp):
    combo = PopupComboBox()
    combo.addItems(["Select", "One"])
    combo.show()
    combo.showPopup()
    qapp.processEvents()
    popup = combo._controlled_popup
    QTest.keyClick(combo._controlled_popup_view, Qt.Key_Escape)
    qapp.processEvents()
    assert not popup.isVisible()


def test_controlled_popup_ignores_invalid_and_activates_enter_path(qapp):
    combo = PopupComboBox()
    combo.addItems(["Select", "One"])
    combo.setCurrentIndex(1)
    combo.show()
    combo.showPopup()
    qapp.processEvents()
    view = combo._controlled_popup_view
    view.clicked.emit(QModelIndex())
    assert combo.currentIndex() == 1
    assert combo._controlled_popup is not None

    view.activated.emit(combo.model().index(0, 0))
    qapp.processEvents()
    assert combo.currentIndex() == 0
    assert combo._controlled_popup is None


@pytest.mark.parametrize("dialog_type", [BatchUploadDialog, BatchDownloadDialog])
@pytest.mark.parametrize("total", [1, 8, 150])
def test_batch_dialog_keeps_list_scrollable_and_controls_below(qapp, dialog_type, total):
    dialog = dialog_type(None, total, None)
    for index in range(total):
        name = f"root/parent/Test file {index:03d}.png"
        dialog.add_entry(str(index), {"type": "file", "name": name}, name)
    dialog.set_total_conflicts(0)
    dialog.resize(400, 330)
    dialog.show()
    qapp.processEvents()

    if total == 150:
        assert dialog.list_widget.verticalScrollBar().maximum() > 0
    assert dialog.list_widget.geometry().bottom() < dialog.progress_label.geometry().top()
    assert dialog.progress_label.geometry().bottom() < dialog.btn_cancel.geometry().top()
    assert dialog.height() <= 380
    dialog.close()


def test_batch_download_dialog_loads_packed_status_icon(qapp):
    dialog = BatchDownloadDialog(None, 1, None)
    assert "packed" in dialog._status_icons
    assert not dialog._status_icons["packed"].isNull()
    dialog.add_entry("one", {"type": "file", "name": "one.txt"}, "one.txt")
    dialog.set_status("one", "packed", "packed")
    assert dialog._rows["one"][1].status == "packed"
    dialog.close()


def test_batch_status_icons_use_pause_for_queued_and_process_for_active(qapp):
    dialog = BatchDownloadDialog(None, 1, None)
    dialog.add_entry("one", {"type": "file", "name": "one.txt"}, "one.txt")

    dialog.set_status("one", "queued")
    row = dialog._rows["one"][1]
    assert not row.status_label.hasScaledContents()
    assert row.status == "queued"
    assert not row.status_label.pixmap().isNull()
    assert row.status_label.toolTip()

    dialog.set_status("one", "process")
    assert row.status == "process"
    assert not row.status_label.pixmap().isNull()
    dialog.close()


def test_batch_download_dialog_hides_folder_conflicts_for_zip(qapp):
    dialog = BatchDownloadDialog(None, 2, None, operation_mode="download_to_zip")
    dialog.set_conflicts_enabled(False)
    dialog.set_total_conflicts(2)
    dialog.show()
    qapp.processEvents()

    assert not dialog.apply_all_box.isVisible()
    assert not dialog.info_label.isVisible()
    assert not dialog.btn_replace.isVisible()
    assert not dialog.btn_copy.isVisible()
    assert not dialog.conflict_label.isVisible()
    assert dialog.conflict_label.text() == ""
    assert dialog.ask_conflict("one", "one.txt", 1) == ("cancel", False)
    dialog.close()


def test_batch_download_dialog_shows_folder_conflicts_only_when_found(qapp):
    dialog = BatchDownloadDialog(None, 2, None, operation_mode="download_to_folder")
    dialog.set_total_conflicts(0)
    dialog.show()
    qapp.processEvents()
    assert not dialog.apply_all_box.isVisible()
    assert not dialog.info_label.isVisible()
    assert not dialog.conflict_label.isVisible()

    dialog.set_total_conflicts(1)
    qapp.processEvents()
    assert dialog.apply_all_box.isVisible()
    assert dialog.info_label.isVisible()
    assert dialog.btn_replace.isVisible()
    assert dialog.btn_copy.isVisible()
    assert dialog.conflict_label.isVisible()
    dialog.close()


def test_bulk_conflict_checkboxes_have_visible_shared_indicator_style(qapp):
    dialogs = [
        BatchDownloadDialog(None, 1, None),
        BatchUploadDialog(None, 1, None),
    ]
    try:
        styles = []
        for dialog in dialogs:
            dialog.set_total_conflicts(1)
            dialog.show()
            qapp.processEvents()

            checkbox = dialog.apply_all_box
            style = checkbox.styleSheet()
            styles.append(style)
            assert checkbox.isVisible()
            assert checkbox.sizeHint().width() > 0
            assert checkbox.sizeHint().height() > 0
            assert "QCheckBox::indicator:unchecked" in style
            assert "QCheckBox::indicator:checked" in style
            assert "QCheckBox::indicator:indeterminate" in style
            assert "width: 18px" in style
            assert "height: 18px" in style
            assert "image: url('" in style
            assert all("\\" not in path for path in (
                CHECK_ICON_OFF_PATH, CHECK_ICON_ON_PATH, CHECK_ICON_MID_PATH,
            ))
        assert styles[0] == styles[1]
    finally:
        for dialog in dialogs:
            dialog.close()
