from types import SimpleNamespace
from unittest.mock import Mock

import requests

from larix_nexus.api.client import APIClient
from larix_nexus.api import client as client_module
from larix_nexus.ui import main_window
from larix_nexus.utils.i18n import TRANSLATIONS_EN, TRANSLATIONS_RU
import main as app_main


def _api(monkeypatch):
    api = APIClient("https://example.test")
    api.token = "test-token"
    return api


def test_list_projects_returns_none_on_network_error(monkeypatch):
    api = _api(monkeypatch)
    request = Mock(side_effect=requests.ConnectionError("offline"))
    monkeypatch.setattr(client_module.requests, "get", request)

    assert api.list_projects() is None
    request.assert_called_once()


def test_list_projects_returns_empty_list_for_valid_empty_response(monkeypatch):
    api = _api(monkeypatch)
    response = Mock(status_code=200)
    response.json.return_value = []
    response.raise_for_status.return_value = None
    monkeypatch.setattr(client_module.requests, "get", Mock(return_value=response))

    assert api.list_projects() == []


def test_startup_project_check_distinguishes_none_from_empty_list():
    assert app_main._project_list_check_succeeded(None) is False
    assert app_main._project_list_check_succeeded([]) is True


def test_ensure_projects_loaded_keeps_existing_combo_on_network_error(monkeypatch):
    combo = Mock()
    combo.count.return_value = 1
    window = SimpleNamespace(
        api=SimpleNamespace(list_projects=Mock(return_value=None)),
        cb_projects=combo,
    )
    monkeypatch.setattr(main_window, "t", lambda key, **kwargs: key)

    main_window.MainWindow.ensure_projects_loaded(window)

    combo.clear.assert_not_called()
    combo.addItem.assert_not_called()


def test_on_logged_in_keeps_projects_combo_on_network_error(monkeypatch):
    combo = Mock()
    window = SimpleNamespace(
        api=SimpleNamespace(
            current_username="user",
            selected_workspace_id=None,
            change_workspace=Mock(),
            list_projects=Mock(return_value=None),
        ),
        btn_login=Mock(),
        btn_user=Mock(),
        cb_projects=combo,
        status=Mock(),
        _begin_busy_status=Mock(),
        _update_busy_status=Mock(),
        _end_busy_status=Mock(),
    )
    monkeypatch.setattr(main_window, "load_settings", lambda: {"workspace_id": "ws-1"})
    monkeypatch.setattr(main_window, "t", lambda key, **kwargs: key)

    main_window.MainWindow.on_logged_in(window)

    combo.clear.assert_not_called()
    combo.addItem.assert_not_called()
    window._end_busy_status.assert_called_once()


def test_choose_workspace_clears_projects_combo_on_network_error(monkeypatch):
    combo = Mock()
    api = SimpleNamespace(
        list_workspaces=Mock(return_value=[{"id": "ws-1", "name": "Workspace"}]),
        change_workspace=Mock(return_value=True),
        selected_workspace_id=None,
        list_projects=Mock(return_value=None),
    )
    window = SimpleNamespace(
        api=api,
        cb_projects=combo,
        _begin_busy_status=Mock(),
        _update_busy_status=Mock(),
        _end_busy_status=Mock(),
        set_initial_view=Mock(),
    )

    class Dialog:
        def __init__(self, *args):
            pass

        def exec(self):
            return main_window.QDialog.DialogCode.Accepted

        def selected_workspace_id(self):
            return "ws-1"

    monkeypatch.setattr(main_window, "WorkspaceDialog", Dialog)
    monkeypatch.setattr(main_window, "load_settings", lambda: {})
    monkeypatch.setattr(main_window, "save_settings", lambda settings: None)
    monkeypatch.setattr(main_window, "t", lambda key, **kwargs: key)
    monkeypatch.setattr(main_window.QMessageBox, "warning", lambda *args: None)

    main_window.MainWindow.choose_workspace(window)

    combo.clear.assert_called_once_with()
    combo.addItem.assert_called_once_with("common.select_project", userData=None)


class _ProjectsCombo:
    def __init__(self):
        self.items = []
        self.index = -1

    def blockSignals(self, _value):
        pass

    def clear(self):
        self.items = []

    def addItem(self, title, userData=None):
        self.items.append((title, userData))

    def count(self):
        return len(self.items)

    def itemData(self, index):
        return self.items[index][1]

    def setCurrentIndex(self, index):
        self.index = index

    def setEnabled(self, _value):
        pass


def test_reconnect_project_restore_selects_saved_project_before_loading_tree(monkeypatch):
    combo = _ProjectsCombo()
    loaded = []
    window = SimpleNamespace(
        cb_projects=combo,
        _startup_project_load_generation=1,
        _startup_project_restore_context={
            "project_id": "project-p",
            "folder_context": {},
            "expanded_folder_ids": {"folder-1"},
        },
        _end_busy_status=Mock(),
        load_tree_for_project=lambda project_id, **kwargs: loaded.append(
            (project_id, combo.itemData(combo.index), kwargs)
        ) or True,
        _complete_reconnect_restore=Mock(),
    )
    monkeypatch.setattr(main_window, "t", lambda key, **kwargs: key)

    main_window.MainWindow._finish_startup_projects_load(
        window,
        1,
        [{"id": "project-first", "name": "First"}, {"id": "project-p", "name": "P"}],
    )

    assert combo.itemData(combo.index) == "project-p"
    assert loaded == [("project-p", "project-p", {"hide_connection_panel_on_success": False, "expanded_folder_ids": {"folder-1"}})]
    window._complete_reconnect_restore.assert_called_once_with(True, None)


def test_reconnect_restore_clears_tree_when_saved_project_is_missing(monkeypatch):
    combo = _ProjectsCombo()
    window = SimpleNamespace(
        cb_projects=combo,
        _startup_project_load_generation=1,
        _startup_project_restore_context={"project_id": "project-p"},
        _end_busy_status=Mock(),
        set_initial_view=Mock(),
        _complete_reconnect_restore=Mock(),
    )
    monkeypatch.setattr(main_window, "t", lambda key, **kwargs: key)

    main_window.MainWindow._finish_startup_projects_load(window, 1, [{"id": "other"}])

    assert combo.index == 0
    window.set_initial_view.assert_called_once()
    window._complete_reconnect_restore.assert_called_once_with(False, "connection.project_unavailable")


def test_reconnect_button_labels_are_not_uppercase():
    assert TRANSLATIONS_RU["connection.retry_button"] == "Переподключиться"
    assert TRANSLATIONS_EN["connection.retry_button"] == "Reconnect"
