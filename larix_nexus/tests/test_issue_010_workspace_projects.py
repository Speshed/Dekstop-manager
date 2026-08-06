from types import SimpleNamespace
from unittest.mock import Mock

import requests

from larix_nexus.api import client as client_module
from larix_nexus.api.client import APIClient
from larix_nexus.ui import main_window


class _ProjectsCombo:
    def __init__(self, items=None):
        self.items = list(items or [])
        self.index = 0 if self.items else -1
        self.enabled = True

    def blockSignals(self, _value):
        pass

    def clear(self):
        self.items = []
        self.index = -1

    def addItem(self, title, userData=None):
        self.items.append((title, userData))

    def count(self):
        return len(self.items)

    def itemData(self, index):
        return self.items[index][1]

    def setCurrentIndex(self, index):
        self.index = index

    def currentIndex(self):
        return self.index

    def setEnabled(self, value):
        self.enabled = value


def _api(monkeypatch, payload):
    api = APIClient("https://example.test")
    api.token = "test-token"
    api.selected_workspace_id = "ws-current"
    response = Mock(status_code=200)
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    monkeypatch.setattr(client_module.requests, "get", Mock(return_value=response))
    return api


def _workspace_dialog(monkeypatch, workspace_id):
    class Dialog:
        def __init__(self, *args):
            pass

        def exec(self):
            return main_window.QDialog.DialogCode.Accepted

        def selected_workspace_id(self):
            return workspace_id

    monkeypatch.setattr(main_window, "WorkspaceDialog", Dialog)


def _choose_window(api, combo, saved_workspace="ws-old"):
    return SimpleNamespace(
        api=api,
        cb_projects=combo,
        _begin_busy_status=Mock(),
        _update_busy_status=Mock(),
        _end_busy_status=Mock(),
        set_initial_view=Mock(),
        status=Mock(),
        _startup_project_load_generation=3,
    ), {"workspace_id": saved_workspace}


def test_list_projects_filters_to_selected_workspace(monkeypatch):
    api = _api(
        monkeypatch,
        [
            {"id": "mine", "workspaceId": "ws-current"},
            {"id": "other", "workspace_id": "ws-other"},
            {"id": "missing"},
        ],
    )
    assert [project["id"] for project in api.list_projects()] == ["mine"]


def test_list_projects_returns_empty_for_workspace_without_matches(monkeypatch):
    api = _api(monkeypatch, [{"id": "other", "workspaceId": "ws-other"}])
    assert api.list_projects() == []


def test_list_projects_excludes_projects_without_workspace_metadata(monkeypatch):
    api = _api(monkeypatch, [{"id": "missing"}, {"id": "also-missing", "name": "x"}])
    assert api.list_projects() == []


def test_list_projects_preserves_none_for_network_error(monkeypatch):
    api = APIClient("https://example.test")
    api.token = "test-token"
    api.selected_workspace_id = "ws-current"
    monkeypatch.setattr(
        client_module.requests,
        "get",
        Mock(side_effect=requests.ConnectionError("offline")),
    )
    assert api.list_projects() is None


def test_choose_workspace_empty_result_replaces_old_projects(monkeypatch):
    combo = _ProjectsCombo([("Old", "old-project")])
    api = SimpleNamespace(
        list_workspaces=Mock(return_value=[{"id": "ws-new", "name": "New"}]),
        change_workspace=Mock(return_value=True),
        list_projects=Mock(return_value=[]),
        selected_workspace_id="ws-old",
    )
    window, settings = _choose_window(api, combo)
    _workspace_dialog(monkeypatch, "ws-new")
    saved = []
    monkeypatch.setattr(main_window, "load_settings", lambda: dict(settings))
    monkeypatch.setattr(main_window, "save_settings", lambda value: saved.append(value))
    monkeypatch.setattr(main_window, "t", lambda key, **kwargs: key)

    main_window.MainWindow.choose_workspace(window)

    assert combo.items == [("common.select_project", None)]
    assert combo.enabled is True
    assert window.set_initial_view.called
    assert saved == [{"workspace_id": "ws-new"}]


def test_choose_workspace_load_error_does_not_restore_old_projects(monkeypatch):
    combo = _ProjectsCombo([("Old", "old-project")])
    api = SimpleNamespace(
        list_workspaces=Mock(return_value=[{"id": "ws-new", "name": "New"}]),
        change_workspace=Mock(return_value=True),
        list_projects=Mock(return_value=None),
        selected_workspace_id="ws-old",
    )
    window, settings = _choose_window(api, combo)
    _workspace_dialog(monkeypatch, "ws-new")
    monkeypatch.setattr(main_window, "load_settings", lambda: dict(settings))
    monkeypatch.setattr(main_window, "save_settings", lambda value: None)
    monkeypatch.setattr(main_window, "t", lambda key, **kwargs: key)
    monkeypatch.setattr(main_window.QMessageBox, "warning", lambda *args: None)

    main_window.MainWindow.choose_workspace(window)

    assert combo.items == [("common.select_project", None)]
    assert api.list_projects.call_count == 1


def test_choose_workspace_activation_failure_does_not_load_or_save(monkeypatch):
    combo = _ProjectsCombo([("Old", "old-project")])
    api = SimpleNamespace(
        list_workspaces=Mock(return_value=[{"id": "ws-new", "name": "New"}]),
        change_workspace=Mock(return_value=False),
        list_projects=Mock(),
        selected_workspace_id="ws-old",
    )
    window, settings = _choose_window(api, combo)
    _workspace_dialog(monkeypatch, "ws-new")
    saved = Mock()
    monkeypatch.setattr(main_window, "load_settings", lambda: dict(settings))
    monkeypatch.setattr(main_window, "save_settings", saved)
    monkeypatch.setattr(main_window, "t", lambda key, **kwargs: key)

    main_window.MainWindow.choose_workspace(window)

    assert combo.items == [("Old", "old-project")]
    api.list_projects.assert_not_called()
    saved.assert_not_called()
    assert api.selected_workspace_id == "ws-old"


def test_startup_worker_does_not_load_after_activation_failure():
    api = SimpleNamespace(change_workspace=Mock(return_value=False), list_projects=Mock())
    worker = main_window._StartupProjectLoadWorker(api, "ws-new", 7)
    results = []
    worker.finished.connect(lambda generation, result: results.append((generation, result)))

    worker.run()

    api.list_projects.assert_not_called()
    assert results == [(7, {"workspace_id": "ws-new", "projects": None, "error": "workspace_activation"})]


def test_stale_startup_result_cannot_replace_current_workspace(monkeypatch):
    combo = _ProjectsCombo([("New", "new-project")])
    window = SimpleNamespace(
        cb_projects=combo,
        api=SimpleNamespace(selected_workspace_id="ws-new"),
        _startup_project_load_generation=5,
        _startup_project_load_workspace_id="ws-new",
        _startup_project_restore_context=None,
        _end_busy_status=Mock(),
    )
    monkeypatch.setattr(main_window, "t", lambda key, **kwargs: key)

    main_window.MainWindow._finish_startup_projects_load(
        window,
        4,
        {
            "workspace_id": "ws-old",
            "projects": [{"id": "old-project", "name": "Old"}],
        },
    )

    assert combo.items == [("New", "new-project")]


def test_startup_activation_error_clears_projects_from_previous_workspace(monkeypatch):
    combo = _ProjectsCombo([("Old", "old-project")])
    window = SimpleNamespace(
        cb_projects=combo,
        api=SimpleNamespace(selected_workspace_id="ws-old"),
        _startup_project_load_generation=5,
        _startup_project_load_workspace_id="ws-new",
        _startup_project_restore_context=None,
        _end_busy_status=Mock(),
        set_initial_view=Mock(),
    )
    monkeypatch.setattr(main_window, "t", lambda key, **kwargs: key)

    main_window.MainWindow._finish_startup_projects_load(
        window,
        5,
        {
            "workspace_id": "ws-new",
            "projects": None,
            "error": "workspace_activation",
        },
    )

    assert combo.items == [("common.select_project", None)]
    window.set_initial_view.assert_called_once()
