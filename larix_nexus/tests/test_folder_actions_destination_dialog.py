import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from larix_nexus.ui import folder_actions


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


def test_prompt_folder_select_builds_light_and_dark_qss_without_nameerror(qapp, monkeypatch):
    window = QWidget()
    window.current_folder_node = lambda: None
    window.current_project_id = lambda: 24
    window.full_tree = [{"id": 1, "type": "folder", "name": "Target", "children": []}]
    window.api = type("Api", (), {"list_folders": lambda *_args, **_kwargs: []})()
    monkeypatch.setattr(QDialog, "exec", lambda _dialog: QDialog.Rejected)

    for is_dark in (False, True):
        monkeypatch.setattr(folder_actions, "_is_dark_mode", lambda: is_dark)
        result = folder_actions._prompt_folder_select(window, "Select destination", can_select_current=True)
        assert result is None

    window.deleteLater()
