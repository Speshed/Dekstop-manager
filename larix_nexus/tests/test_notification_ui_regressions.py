from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from larix_nexus.ui import main_window, tree_operations
from larix_nexus.utils.i18n import t


class _Action:
    def __init__(self, text):
        self._text = text

    def text(self):
        return self._text

    def setToolTip(self, _value):
        pass

    def setEnabled(self, _value):
        pass


class _Menu:
    def __init__(self, _parent):
        self.actions = []

    def setObjectName(self, _value):
        pass

    def addAction(self, text):
        action = _Action(text)
        self.actions.append(action)
        return action

    def addSeparator(self):
        pass


class _ProjectCombo:
    def __init__(self):
        self.items = [("existing placeholder", None)]
        self.blocked = False

    def count(self):
        return len(self.items)

    def blockSignals(self, value):
        self.blocked = value

    def clear(self):
        self.items.clear()

    def addItem(self, text, userData=None):
        self.items.append((text, userData))

    def itemText(self, index):
        return self.items[index][0]

    def itemData(self, index):
        return self.items[index][1]


def test_tree_context_menu_uses_saved_subscription_with_empty_runtime_state(monkeypatch):
    saved_check = Mock(return_value=True)
    monkeypatch.setattr(tree_operations, "is_folder_notification_enabled", saved_check)
    monkeypatch.setattr(tree_operations, "QMenu", _Menu)

    node = {"type": "folder", "id": "42", "projectId": "7"}
    item = SimpleNamespace(data=lambda *_args: node)
    tree = SimpleNamespace(itemAt=lambda _pos: item, mapToGlobal=lambda pos: pos)
    toggled = Mock()

    window = SimpleNamespace(
        tree=tree,
        sync2=None,
        api=SimpleNamespace(is_available=lambda: True),
        current_project_id=lambda: "7",
        _subscriptions={},
        _pending_notifications={},
        _menu_exec=lambda menu, _pos: next(
            action for action in menu.actions
            if action.text() == t("context.unsubscribe_notifications")
        ),
        toggle_folder_notifications=toggled,
    )

    tree_operations.tree_context_menu(window, SimpleNamespace())

    saved_check.assert_called_once_with("7", "42")
    toggled.assert_called_once_with(node)


def test_project_combo_skips_blank_names_and_keeps_placeholder_and_id():
    combo = _ProjectCombo()
    window = SimpleNamespace(
        api=SimpleNamespace(
            list_projects=lambda: [
                {"id": 11, "name": "   "},
                {"id": 22, "title": "  Real project  "},
            ]
        ),
        cb_projects=combo,
    )

    main_window.MainWindow.ensure_projects_loaded(window)

    assert combo.items == [(t("common.select_project"), None), ("Real project", 22)]
    assert all(combo.itemText(i).strip() for i in range(combo.count()))


def test_init_notifications_ui_assigns_main_icon_to_tray(monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets

    icon_paths = []

    class FakeIcon:
        def __init__(self, path=None):
            self.path = path
            icon_paths.append(path)

        def isNull(self):
            return False

    monkeypatch.setattr(main_window, "QIcon", FakeIcon)

    class FakeTimer:
        def __init__(self, _parent=None):
            self.timeout = SimpleNamespace(connect=lambda _callback: None)

        def setSingleShot(self, _value):
            pass

        def start(self, _value):
            pass

    class FakeTray:
        instance = None

        def __init__(self, _parent):
            self.icon = None
            FakeTray.instance = self

        def setIcon(self, icon):
            self.icon = icon

        def setToolTip(self, _value):
            pass

        def show(self):
            pass

        @staticmethod
        def isSystemTrayAvailable():
            return False

    monkeypatch.setattr(QtWidgets, "QSystemTrayIcon", FakeTray)
    monkeypatch.setattr(main_window, "QTimer", FakeTimer)
    monkeypatch.setattr(main_window, "load_settings", lambda: {"sync": {"auto_sync_interval": 300}})

    window = SimpleNamespace(
        _schedule_next_notification_timer=Mock(),
        _check_notifications=Mock(),
        installEventFilter=Mock(),
        windowIcon=lambda: FakeIcon("window"),
    )

    main_window.MainWindow._init_notifications_ui(window)

    assert FakeTray.instance is not None
    assert not FakeTray.instance.icon.isNull()
    assert FakeTray.instance.icon.path == main_window.ICON_PATH
    assert main_window.ALARM_ICON_PATH not in icon_paths
