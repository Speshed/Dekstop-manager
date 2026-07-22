import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication

from larix_nexus.ui.dialogs import BatchDownloadDialog, BatchUploadDialog, ConflictListItem


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
