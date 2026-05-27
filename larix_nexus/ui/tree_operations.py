# -*- coding: utf-8 -*-
"""Tree widget operations for Larix Nexus."""

import functools
from PySide6.QtCore import Qt, QSignalBlocker, QThread, QTimer, QMetaObject
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QTreeWidgetItem, QMessageBox, QTreeWidget, QMenu
from PySide6.QtGui import QIcon
from ..utils.helpers import normalize_id, normalize_project_id, enrich_id_types, open_in_os
from ..utils.logging import sync_log
from ..utils.ui_trace import trace
from ..utils.i18n import t
from ..api import APIClient
from ..constants import FOLDER_ICON_PATH, SYNC_ROLE, NOTIFY_ROLE


def _item_parent_folder_id(item: dict) -> str:
    """Best-effort parent folder id extraction for file items."""
    if not isinstance(item, dict):
        return ""
    for k in ("folderId", "folder_id", "parent_id", "parentFolderId", "parentFolderID"):
        try:
            v = item.get(k)
        except Exception:
            v = None
        pid = normalize_id(v)
        if pid:
            return pid
    return ""


def _find_tree_item_by_folder_id(self, folder_id: str):
    """Return QTreeWidgetItem for folder id (from loaded tree map)."""
    try:
        return get_folder_tree_item(self, folder_id)
    except Exception:
        return None


def _go_to_file_parent_folder(self, item: dict) -> bool:
    """In flat mode: open parent folder in tree and focus file in table."""
    try:
        file_id = normalize_id((item or {}).get("id") or (item or {}).get("documentId"))
    except Exception:
        file_id = ""
    try:
        file_name = (item or {}).get("originalName") or (item or {}).get("name") or ""
    except Exception:
        file_name = ""

    try:
        sync_log("UI: go_to_file_parent_folder requested file_id={} name={}", file_id, file_name)
    except Exception:
        pass

    parent_id = _item_parent_folder_id(item)
    if not parent_id:
        try:
            msg = "Не удалось определить папку файла"
            if hasattr(self, "_show_status_message"):
                self._show_status_message(msg, 3500, owner="ui", force=True)
            elif hasattr(self, "status") and self.status is not None:
                self.status.showMessage(msg, 3500)
        except Exception:
            pass
        try:
            keys = []
            try:
                keys = list((item or {}).keys())
            except Exception:
                keys = []
            sync_log(
                "UI: go_to_file_parent_folder failed: no parent id file_id={} name={} keys={}",
                file_id,
                file_name,
                keys,
            )
        except Exception:
            pass
        return False

    # Find folder tree item, with one soft refresh fallback.
    folder_item = _find_tree_item_by_folder_id(self, parent_id)
    if folder_item is None:
        try:
            sync_log("UI: go_to_file_parent_folder folder_id={} not in tree, soft refresh", parent_id)
        except Exception:
            pass
        try:
            if hasattr(self, "soft_refresh_and_restore_view"):
                self.soft_refresh_and_restore_view()
        except Exception:
            pass
        folder_item = _find_tree_item_by_folder_id(self, parent_id)

    if folder_item is None:
        try:
            msg = "Папка файла не найдена в дереве проекта"
            if hasattr(self, "_show_status_message"):
                self._show_status_message(msg, 4500, owner="ui", force=True)
            elif hasattr(self, "status") and self.status is not None:
                self.status.showMessage(msg, 4500)
        except Exception:
            pass
        try:
            sync_log(
                "UI: go_to_file_parent_folder failed: folder not found in tree file_id={} name={} folder_id={}",
                file_id,
                file_name,
                parent_id,
            )
        except Exception:
            pass
        return False

    # Disable flat mode without triggering extra loads.
    try:
        if getattr(self, "cb_flat", None) is not None and self.cb_flat.isChecked():
            try:
                blocker = QSignalBlocker(self.cb_flat)
            except Exception:
                blocker = None
            try:
                self.cb_flat.setChecked(False)
            finally:
                try:
                    if blocker is not None:
                        del blocker
                except Exception:
                    pass
        self._flat_recursive_mode = False
        self._flat_base_folder_id = None
        self._flat_files_source = []
    except Exception:
        pass

    # Select folder in tree and open it.
    try:
        self.tree.setCurrentItem(folder_item)
    except Exception:
        pass
    try:
        node = folder_item.data(0, Qt.UserRole)
    except Exception:
        node = None

    if not isinstance(node, dict):
        node = {"type": "folder", "id": parent_id, "name": "", "projectId": self.current_project_id()}

    opened = False
    try:
        opened = bool(self.open_folder_node(node, save_to_history=True))
    except Exception:
        opened = False

    try:
        self.update_path_label()
    except Exception:
        pass

    if not opened:
        try:
            sync_log(
                "UI: go_to_file_parent_folder failed to open folder file_id={} name={} folder_id={}",
                file_id,
                file_name,
                parent_id,
            )
        except Exception:
            pass
        return False

    # After table refresh, try to select and scroll to the file.
    def _select_in_table():
        try:
            if not file_id:
                return
            model = self.table.model() if hasattr(self, "table") else None
            rows = model.rowCount() if model is not None else 0
            for row in range(rows):
                try:
                    idx = model.index(row, 0)
                    v = model.data(idx, Qt.UserRole)
                    if not isinstance(v, dict):
                        continue
                    vid = normalize_id(v.get("id") or v.get("documentId"))
                    if vid and vid == file_id:
                        try:
                            self.table.selectRow(row)
                        except Exception:
                            pass
                        try:
                            from PySide6.QtWidgets import QAbstractItemView

                            self.table.scrollTo(idx, QAbstractItemView.PositionAtCenter)
                        except Exception:
                            pass
                        return
                except Exception:
                    continue
        except Exception:
            return

    try:
        QTimer.singleShot(0, _select_in_table)
    except Exception:
        _select_in_table()

    try:
        sync_log(
            "UI: go_to_file_parent_folder ok file_id={} name={} folder_id={}",
            file_id,
            file_name,
            parent_id,
        )
    except Exception:
        pass
    return True


def get_folder_tree_item(self, folder_id):
    """Return QTreeWidgetItem for a folder id (keys are normalized strings)."""
    key = normalize_id(folder_id)
    if not key:
        return None
    return (getattr(self, "folder_item_by_id", {}) or {}).get(key)


def _restore_tree_badges(self, project_id: int | str) -> None:
    """Re-apply sync/notify badges after tree rebuild.

    Badges are drawn by the tree item delegate based on SYNC_ROLE / NOTIFY_ROLE.
    They are not persisted in the Qt model across restarts, so we must re-set
    roles from persisted app state.
    """
    try:
        project_id_norm = normalize_project_id(project_id)
    except Exception:
        project_id_norm = normalize_id(project_id)

    # Sync badges
    try:
        mgr = getattr(self, "sync2", None)
        for fid, item in (getattr(self, "folder_item_by_id", {}) or {}).items():
            try:
                fid_norm = normalize_id(fid)
            except Exception:
                fid_norm = str(fid)
            is_synced = False
            try:
                if mgr is not None and hasattr(mgr, "is_synced"):
                    is_synced = bool(mgr.is_synced(fid_norm))
            except Exception:
                is_synced = False
            if is_synced:
                try:
                    item.setData(0, SYNC_ROLE, True)
                except Exception:
                    pass
    except Exception:
        pass

    # Notification badges
    try:
        from larix_nexus.notifications import load_folder_notifications

        subs = load_folder_notifications() or []
    except Exception:
        subs = []

    try:
        pending = getattr(self, "_pending_notifications", {}) or {}
    except Exception:
        pending = {}

    try:
        subscribed_ids: set[str] = set()
        for s in subs:
            try:
                if normalize_project_id(s.get("project_id")) != project_id_norm:
                    continue
                subscribed_ids.add(normalize_id(s.get("folder_id")))
            except Exception:
                continue

        pending_ids = {normalize_id(k) for k in (pending or {}).keys()}

        for fid, item in (getattr(self, "folder_item_by_id", {}) or {}).items():
            try:
                fid_norm = normalize_id(fid)
            except Exception:
                fid_norm = str(fid)
            if fid_norm not in subscribed_ids:
                continue
            try:
                item.setData(0, NOTIFY_ROLE, True if fid_norm in pending_ids else False)
            except Exception:
                pass
    except Exception:
        pass

    try:
        self.tree.viewport().update()
    except Exception:
        pass


def populate_tree_widget(self, tree: QTreeWidget | None = None, nodes: list | None = None):
    """Populate tree widget with folder nodes."""
    if tree is None:
        tree = self.tree

    # Avoid native crash if the underlying QObject was deleted.
    try:
        from shiboken6 import isValid  # type: ignore
        if tree is None or not isValid(tree):
            return
    except Exception:
        if tree is None:
            return

    if nodes is None:
        project_id = self.current_project_id()
        if not project_id:
            return
        try:
            nodes = self.api.list_folders(project_id) or []
        except Exception:
            return

    try:
        trace("populate_tree_widget: start nodes={}", len(nodes) if isinstance(nodes, list) else -1)
    except Exception:
        pass
    
    # Preload icon once.
    try:
        folder_icon = QIcon(FOLDER_ICON_PATH)
    except Exception:
        folder_icon = QIcon()

    created = 0

    def add_items(parent: QTreeWidgetItem, items: list):
        nonlocal created
        for item in items:
            if not isinstance(item, dict):
                continue
            typ = item.get("type", "").lower()
            if typ not in ("folder", "dir", "directory", "папка"):
                continue

            enrich_id_types(item)
            
            fid = item.get("id")
            name = item.get("name") or item.get("title") or "Без названия"

            tree_item = QTreeWidgetItem(parent)
            created += 1
            tree_item.setText(0, name)
            tree_item.setToolTip(0, str(name))
            tree_item.setData(0, Qt.UserRole, item)
            tree_item.setData(0, Qt.UserRole + 1, fid)

            try:
                if not folder_icon.isNull():
                    tree_item.setIcon(0, folder_icon)
            except Exception:
                pass

            if fid:
                fid_key = normalize_id(fid)
                if fid_key:
                    self.folder_item_by_id[fid_key] = tree_item

            children = item.get("children") or []
            if children:
                add_items(tree_item, children)

    blocker = None
    try:
        try:
            blocker = QSignalBlocker(tree)
        except Exception:
            blocker = None

        try:
            tree.setUpdatesEnabled(False)
        except Exception:
            pass

        tree.clear()
        self.folder_item_by_id = {}

        root = tree.invisibleRootItem()
        add_items(root, nodes)
        try:
            tree.expandAll()
        except Exception:
            pass

        try:
            trace(
                "populate_tree_widget: done created={} folder_map={}",
                created,
                len(getattr(self, "folder_item_by_id", {}) or {}),
            )
        except Exception:
            pass
    finally:
        try:
            tree.setUpdatesEnabled(True)
        except Exception:
            pass
        try:
            if blocker is not None:
                del blocker
        except Exception:
            pass


def load_tree_for_project(self, project_id: int | str, hide_connection_panel_on_success: bool = True):
    """Load tree for specified project."""
    project_id = normalize_id(project_id)
    if not project_id:
        return False

    try:
        trace("load_tree_for_project: start project_id={}", project_id)
    except Exception:
        pass
    
    try:
        result = self.api.list_folders_result(project_id, force=True)
    except Exception as e:
        print(f"[tree_context_menu] Failed to load folders: {e}")
        result = None

    if not getattr(result, "ok", False):
        error_code = getattr(result, "error", "connection_lost") if result is not None else "connection_lost"
        try:
            self._connection_retry_context = {"kind": "tree", "project_id": project_id}
            self._show_connection_panel(error_code, context=self._connection_retry_context)
        except Exception:
            pass
        return False

    nodes = getattr(result, "data", None) or []

    try:
        trace("load_tree_for_project: nodes={}", len(nodes) if isinstance(nodes, list) else -1)
    except Exception:
        pass

    self.full_tree = nodes
    
    self.populate_tree_widget(self.tree, nodes)

    # Restore badges (sync + notifications)
    try:
        _restore_tree_badges(self, project_id)
    except Exception:
        pass

    opened = False
    if isinstance(nodes, list) and nodes:
        first_node = next((node for node in nodes if isinstance(node, dict)), None)
        if isinstance(first_node, dict):
            try:
                first_item = get_folder_tree_item(self, first_node.get("id"))
                if first_item is not None:
                    self.tree.setCurrentItem(first_item)
            except Exception:
                pass
            try:
                opened = bool(self.open_folder_node(first_node, save_to_history=False))
            except Exception:
                opened = False
    else:
        try:
            self.tree.setCurrentItem(None)
        except Exception:
            pass
        root_node = {"type": "folder", "id": project_id, "name": t("folder.root"), "children": [], "projectId": project_id}
        try:
            opened = bool(self.open_folder_node(root_node, save_to_history=False))
        except Exception:
            opened = False

    if opened and hide_connection_panel_on_success:
        try:
            self._hide_connection_panel()
        except Exception:
            pass

    return opened


def refresh_tree(self):
    """Refresh tree widget with current project folders."""
    project_id = self.current_project_id()
    if not project_id:
        return
    self.soft_refresh_and_restore_view()


def soft_refresh_and_restore_view(self):
    """Soft refresh tree and restore current view state."""
    # Ensure all UI work runs on the GUI thread.
    try:
        app = QApplication.instance()
        gui_th = app.thread() if app is not None else None
        if gui_th is not None and QThread.currentThread() is not gui_th:
            try:
                trace("soft_refresh: non-gui thread -> queue")
            except Exception:
                pass
            if getattr(self, "_soft_refresh_pending", False):
                return
            self._soft_refresh_pending = True

            def _run():
                try:
                    self._soft_refresh_pending = False
                    self.soft_refresh_and_restore_view()
                except Exception:
                    self._soft_refresh_pending = False

            try:
                QTimer.singleShot(0, _run)
            except Exception:
                try:
                    QMetaObject.invokeMethod(self, "soft_refresh_and_restore_view", Qt.QueuedConnection)
                except Exception:
                    pass
            return
    except Exception:
        pass

    try:
        try:
            trace("soft_refresh: start")
        except Exception:
            pass
        # Capture only stable identifiers from the current selection.
        current_fid = None
        current_item = None
        try:
            current_item = self.tree.currentItem()
        except Exception:
            current_item = None
        if current_item:
            try:
                current_fid = current_item.data(0, Qt.UserRole + 1)
            except Exception:
                current_fid = None

        project_id = None
        try:
            project_id = self.current_project_id()
        except Exception:
            project_id = None
        if project_id:
            self.load_tree_for_project(project_id)

        try:
            trace("soft_refresh: after load_tree project_id={} current_fid={}", project_id, current_fid)
        except Exception:
            pass

        current_fid_key = normalize_id(current_fid) if current_fid else ""
        if current_fid_key and current_fid_key in getattr(self, "folder_item_by_id", {}):
            try:
                self.tree.setCurrentItem(self.folder_item_by_id[current_fid_key])
            except Exception:
                pass

            try:
                def _reload_current_folder():
                    try:
                        name = ""
                        try:
                            name = self.folder_item_by_id[current_fid_key].text(0)
                        except Exception:
                            name = ""
                        node = {"type": "folder", "id": current_fid, "name": name, "projectId": project_id}
                        self.open_folder_node(node, save_to_history=False)
                    except Exception:
                        pass

                QTimer.singleShot(0, _reload_current_folder)
            except Exception:
                try:
                    node = {"type": "folder", "id": current_fid, "name": "", "projectId": project_id}
                    self.open_folder_node(node, save_to_history=False)
                except Exception:
                    pass
    except Exception:
        pass


def on_tree_click(self, item: QTreeWidgetItem, _col: int):
    """Handle tree widget item click."""
    if not item:
        return
    node = item.data(0, Qt.UserRole)
    if isinstance(node, dict) and node.get("type") in ("folder", "dir", "directory", "папка"):
        self.open_folder_node(node)


def _history_node_id(node: dict) -> str:
    try:
        return normalize_id((node or {}).get("id") or (node or {}).get("folderId"))
    except Exception:
        return ""


def _update_back_button_state(self):
    history = getattr(self, "_folder_history", []) or []
    try:
        if hasattr(self, "btn_back"):
            self.btn_back.setEnabled(len(history) > 1)
    except Exception:
        pass


def tree_context_menu(self, pos):
    """Show context menu for tree widget folders (download, sync, notifications)."""
    item = self.tree.itemAt(pos)
    if not item:
        return
    node = item.data(0, Qt.UserRole)
    try:
        typ = str((node or {}).get("type") or "").lower()
    except Exception:
        typ = ""
    if typ != "folder":
        return

    menu = QMenu(self)
    menu.setObjectName("treeMenu")
    act_zip = menu.addAction(t("context.download_as_zip"))
    act_folder = menu.addAction(t("context.download_structure"))
    menu.addSeparator()

    act_copy_folder = menu.addAction(t("context.copy_folder"))
    menu.addSeparator()

    folder_id = (node or {}).get("id")
    fid_key = normalize_id(folder_id)
    is_synced = bool(getattr(self, "sync2", None) and self.sync2.is_synced(folder_id))

    act_path_open = None
    act_eta = None
    act_unsync = None
    act_sync = None
    act_sync_now = None
    pth = ""

    if is_synced:
        try:
            pth = self.sync2.get_sync_path(folder_id)
            act_path_open = menu.addAction(t("context.sync_path"))
            act_path_open.setToolTip(pth)
        except Exception:
            pth = ""
        try:
            eta_ms = -1
            cfg = self.sync2.map.get(fid_key) if hasattr(self, "sync2") else None
            if cfg and bool(cfg.get("initial_ok")) and self.sync2.timer.isActive():
                eta_ms = int(self.sync2.timer.remainingTime())

            def _fmt_eta(ms: int) -> str:
                try:
                    if ms is None or ms < 0:
                        return "—"
                    s = int(ms // 1000)
                    m, s = divmod(max(0, s), 60)
                    if m > 0:
                        return t("time.min_sec", m=m, s=s)
                    return t("time.sec", n=s)
                except Exception:
                    return "—"

            eta_text = _fmt_eta(eta_ms)
            act_eta = menu.addAction(t("context.sync_next", eta=eta_text))
            act_eta.setEnabled(False)
        except Exception:
            pass
        act_unsync = menu.addAction(t("context.sync_disable"))
    else:
        act_sync = menu.addAction(t("context.sync"))
        try:
            act_sync.setEnabled(bool(self.api.is_available()))
        except Exception:
            pass

    if is_synced:
        try:
            act_sync_now = menu.addAction(t("context.sync_now"))
        except Exception:
            act_sync_now = None

    try:
        menu.addSeparator()
        subscribed = False
        has_changes = False
        folder_id_int = fid_key
        try:
            subscribed = folder_id_int in getattr(self, "_subscriptions", {})
        except Exception:
            subscribed = False
        try:
            has_changes = fid_key in (getattr(self, "_pending_notifications", {}) or {})
        except Exception:
            has_changes = False

        act_view_notif = None
        act_sub = None
        if subscribed and has_changes:
            act_view_notif = menu.addAction(t("context.notifications"))
        try:
            if subscribed:
                act_sub = menu.addAction(t("context.unsubscribe_notifications"))
            else:
                act_sub = menu.addAction(t("context.subscribe_notifications"))
        except Exception:
            act_sub = None
    except Exception:
        act_view_notif = None
        act_sub = None

    chosen = None
    try:
        chosen = self._menu_exec(menu, self.tree.mapToGlobal(pos))
    except Exception:
        try:
            chosen = menu.exec(self.tree.mapToGlobal(pos))
        except Exception:
            chosen = None
    try:
        sync_log("SYNC_MENU: chosen action {}", (getattr(chosen, "text", lambda: None)() if chosen else None))
    except Exception:
        pass
    if not chosen:
        return

    if chosen == act_zip:
        self.download_folder_as_zip(node)
        return
    if chosen == act_folder:
        self.download_folder_plain(node)
        return
    if is_synced and chosen == act_sync_now:
        try:
            self._trigger_sync_now(folder_id)
        except Exception:
            pass
        return
    if is_synced and chosen == act_path_open:
        if pth:
            try:
                open_in_os(pth)
            except Exception:
                pass
        return
    if is_synced and chosen == act_unsync:
        try:
            self.sync2.remove_sync(folder_id)
            item.setData(0, SYNC_ROLE, False)
            self.tree.viewport().update()
            try:
                from larix_nexus.ui.main_window import cleanup_removed

                cleanup_removed(self.tree)
            except Exception:
                pass
            QTimer.singleShot(
                0,
                lambda: QMessageBox.information(self, t("sync.title"), t("sync.disabled")),
            )
        except Exception:
            pass
        return
    if (not is_synced) and chosen == act_sync:
        try:
            proj = self.current_project_id()
        except Exception:
            proj = None
        if not proj:
            QTimer.singleShot(
                0,
                lambda: QMessageBox.warning(self, t("sync.title"), t("sync.no_project")),
            )
            return
        try:
            folder_title = item.text(0)
        except Exception:
            try:
                folder_title = (node or {}).get("name") or ""
            except Exception:
                folder_title = ""

        def add_mapping():
            try:
                self._sync_add_mapping(folder_id, folder_title, proj)
            except Exception:
                pass

        QTimer.singleShot(0, add_mapping)
        return
    if chosen == act_copy_folder:
        self.copy_folder_action(node)
        return
    if chosen == act_view_notif:
        if node:
            try:
                folder_id_check = normalize_id((node or {}).get("id"))
                if folder_id_check:
                    self._show_changes_dialog(folder_id_check)
            except Exception as e:
                QTimer.singleShot(
                    0,
                    lambda err=e: QMessageBox.warning(
                        self, t("common.error"), t("sync.notifications_error", error=err)
                    ),
                )
        return
    if chosen == act_sub or (
        chosen
        and chosen.text()
        in (t("context.subscribe_notifications"), t("context.unsubscribe_notifications"))
    ):
        if node:
            self.toggle_folder_notifications(node)
        return


def go_to_project_root(self):
    """Navigate to project root folder."""
    project_id = self.current_project_id()
    if not project_id:
        return

    # Virtual root: not a real folder id on the backend.
    root_node = {
        "type": "folder",
        "id": project_id,
        "name": t("folder.root"),
        "children": (getattr(self, "full_tree", None) or []),
        "projectId": project_id,
        "_virtual_project_root": True,
    }

    # Root is not a selectable tree item; clear selection so helpers like
    # _is_root_open()/update_path_label treat it as root.
    try:
        if hasattr(self, "tree") and self.tree is not None:
            self.tree.clearSelection()
            try:
                self.tree.setCurrentItem(None)
            except Exception:
                pass
    except Exception:
        pass
    self.open_folder_node(root_node)


def go_back(self):
    """Navigate back in folder history."""
    history = list(getattr(self, "_folder_history", []) or [])
    if len(history) <= 1:
        self._folder_history = history[:1] if history else []
        _update_back_button_state(self)
        return

    history.pop()
    prev_node = history[-1] if history else None
    self._folder_history = history
    if isinstance(prev_node, dict):
        self.open_folder_node(prev_node, save_to_history=False)
    _update_back_button_state(self)


def open_folder_node(self, node: dict, save_to_history: bool = True):
    """Open folder and display its contents."""
    if not isinstance(node, dict):
        return False

    typ = node.get("type", "").lower()
    if typ not in ("folder", "dir", "directory", "папка"):
        return False

    fid = normalize_id(node.get("id") or node.get("folderId"))
    if not fid:
        return False

    current_fid = ""
    try:
        folder_ctx = getattr(self, "_current_folder_context", {}) or {}
        current_fid = normalize_id(folder_ctx.get("folder_id")) if folder_ctx.get("folder_id") is not None else ""
    except Exception:
        current_fid = ""
    if not current_fid:
        try:
            current_item = self.tree.currentItem() if hasattr(self, "tree") else None
            if current_item is not None:
                current_fid = normalize_id(current_item.data(0, Qt.UserRole + 1))
        except Exception:
            current_fid = ""

    folder_changed = bool(current_fid and current_fid != fid)

    # Get project_id from node or current project
    project_id = node.get("projectId") or node.get("project_id") or self.current_project_id()

    # Virtual project root: show direct top-level folders from loaded tree,
    # do not call list_files_result(project_id, project_id).
    try:
        is_virtual_root = bool(node.get("_virtual_project_root"))
    except Exception:
        is_virtual_root = False

    if is_virtual_root:
        try:
            root_children = getattr(self, "full_tree", None) or []
        except Exception:
            root_children = []

        folders = []
        for it in root_children:
            if not isinstance(it, dict):
                continue
            try:
                tt = str(it.get("type") or "").lower()
            except Exception:
                tt = ""
            if tt not in ("folder", "dir", "directory", "папка"):
                continue
            it["type"] = "folder"
            try:
                enrich_id_types(it)
            except Exception:
                pass
            folders.append(it)

        self.files_current = folders
        try:
            # Root is not a real folder; ensure we're not in a stale flat recursive mode.
            self._flat_recursive_mode = False
        except Exception:
            pass
        try:
            self.update_table()
        except Exception:
            pass

        # Update path label
        try:
            self.update_path_label()
        except Exception:
            pass
        try:
            if hasattr(self, "_save_current_folder_context"):
                self._save_current_folder_context({"id": fid, "name": t("folder.root"), "projectId": project_id})
        except Exception:
            pass

        # Save to history
        if save_to_history:
            history = list(getattr(self, "_folder_history", []) or [])
            node_id = _history_node_id(node)
            last_id = _history_node_id(history[-1]) if history else ""
            if node_id and node_id != last_id:
                history.append(node)
            self._folder_history = history
        else:
            self._folder_history = list(getattr(self, "_folder_history", []) or [])
        _update_back_button_state(self)
        return True

    print(f"[open_folder_node] Opening folder: fid={fid}, name={node.get('name')}, project_id={project_id}")

    if folder_changed:
        try:
            self.checked.clear()
        except Exception:
            pass
        self._selection_mode_anchor_row = None
        try:
            if hasattr(self, "_clear_row_selection_for_selection_mode"):
                self._clear_row_selection_for_selection_mode()
        except Exception:
            pass
        try:
            self.update_header_checkbox()
        except Exception:
            pass
        try:
            self._update_actions_enabled()
        except Exception:
            pass
        try:
            self._update_selection_mode_panel()
        except Exception:
            pass

    try:
        try:
            if hasattr(self, "_set_progress_visible"):
                self._set_progress_visible(True)
                self.progress.setRange(0, 0)
            if hasattr(self, "status"):
                if hasattr(self, "_show_status_message"):
                    self._show_status_message(t("status.loading_items"), owner="ui")
                else:
                    self.status.showMessage(t("status.loading_items"))
            QApplication.processEvents()
        except Exception:
            pass

        try:
            result = self.api.list_files_result(fid, project_id=project_id)
            if not getattr(result, "ok", False):
                error_code = getattr(result, "error", "connection_lost")
                try:
                    self._connection_retry_context = {
                        "kind": "folder",
                        "project_id": project_id,
                        "folder_context": {"folder_id": fid, "name": node.get("name") or node.get("title") or "", "project_id": project_id},
                    }
                    self._show_connection_panel(error_code, context=self._connection_retry_context)
                except Exception:
                    pass
                _update_back_button_state(self)
                return False
            files = getattr(result, "data", None) or []
            for f in files:
                if isinstance(f, dict):
                    enrich_id_types(f)
            print(f"[open_folder_node] Got {len(files)} files from API")
            if not files:
                try:
                    docs = self.api.list_documents_in_folder(fid) or []
                except Exception as e:
                    print(f"[open_folder_node] fallback list_documents_in_folder({fid}) ERROR: {e}")
                    docs = []
                if docs:
                    print(f"[open_folder_node] fallback list_documents_in_folder({fid}) -> {len(docs)} docs")
                    for doc in docs:
                        if not isinstance(doc, dict):
                            continue
                        doc["type"] = "file"
                        try:
                            enrich_id_types(doc)
                        except Exception:
                            pass
                        if not doc.get("folderId") and not doc.get("folder_id"):
                            doc["folderId"] = fid
                        files.append(doc)
            # Debug: print first file structure
            if files:
                print(f"[open_folder_node] First file keys: {list(files[0].keys()) if isinstance(files[0], dict) else 'not a dict'}")
                print(f"[open_folder_node] First file: {files[0] if len(files) > 0 else 'empty'}")
        except Exception as e:
            print(f"[open_folder_node] ERROR loading files: {e}")
            _update_back_button_state(self)
            return False

        self.files_current = files
        # Debug: try to enrich first file with full details
        if files and len(files) > 0 and isinstance(files[0], dict) and files[0].get('type') == 'file':
            doc_id = files[0].get('id')
            if doc_id:
                try:
                    doc_details = self.api.get_document_details(doc_id)
                    print(f"[open_folder_node] Document details for {doc_id}: {doc_details}")
                    # Check which fields are missing in list response
                    print(f"[open_folder_node] Missing fields comparison:")
                    print(f"  list response: {files[0]}")
                    print(f"  full details:   {doc_details}")
                except Exception as e:
                    print(f"[open_folder_node] ERROR getting doc details: {e}")

        # Enrich files with full metadata to ensure all fields (createdBy, createTime, modifTime, modifiedBy) are available
        try:
            self.lazy_enrich_current_files()
        except Exception as e:
            print(f"[open_folder_node] ERROR enriching files: {e}")
        # If "Без папок" is enabled, immediately replace the table source with
        # the recursive flat list for this folder.
        try:
            if getattr(self, "cb_flat", None) is not None and self.cb_flat.isChecked() and hasattr(self, "_apply_recursive_flat_view"):
                self._apply_recursive_flat_view(node)
            else:
                self.update_table()
        except Exception as e:
            print(f"[no-folders] ERROR applying flat view after open_folder_node: {e}")
            self.update_table()
    finally:
        try:
            if hasattr(self, "_set_progress_visible"):
                self._set_progress_visible(False)
            if hasattr(self, "status"):
                msg = t("status.loaded_items", count=len(getattr(self, 'files_current', []) or []))
                if hasattr(self, "_show_status_message"):
                    self._show_status_message(msg, 2500, owner="ui")
                else:
                    self.status.showMessage(msg, 2500)
        except Exception:
            pass
    
    # Update path label
    name = node.get("name") or node.get("title") or t("common.no_name")
    self.update_path_label()
    try:
        if hasattr(self, "_save_current_folder_context"):
            self._save_current_folder_context({"id": fid, "name": name, "projectId": project_id})
    except Exception:
        pass
    
    # Save to history
    if save_to_history:
        history = list(getattr(self, "_folder_history", []) or [])
        node_id = _history_node_id(node)
        last_id = _history_node_id(history[-1]) if history else ""
        if node_id and node_id != last_id:
            history.append(node)
        self._folder_history = history
    else:
        self._folder_history = list(getattr(self, "_folder_history", []) or [])
    _update_back_button_state(self)
    return True


def lazy_enrich_file_list(self, files: list, force_refresh: bool = False) -> int:
    """Enrich a list of files with metadata without grouping by folder.

    Args:
        files: List of file dicts to enrich
        force_refresh: If True, force refresh even if files are already enriched

    Returns:
        Number of files enriched
    """
    if not isinstance(files, list):
        return 0

    print(f"[lazy_enrich_file_list] Starting enrichment for {len(files)} files (no folder grouping)")

    # Initialize document details cache if not exists
    if not hasattr(self, "_doc_details_cache"):
        self._doc_details_cache = {}

    total_enriched = 0
    total_from_cache = 0

    for item in files:
        if not isinstance(item, dict) or item.get("type") != "file":
            continue

        item_id = normalize_id(item.get("id"))
        if not item_id:
            continue

        # Check if file already has all required fields
        has_creator = bool(item.get("createdBy"))
        has_create_time = bool(item.get("createTime") or item.get("createdAt"))
        has_modif_time = bool(item.get("modifTime") or item.get("updatedAt") or item.get("modifiedDate"))
        has_modified_by = bool(item.get("modifiedBy") or item.get("author"))

        if not force_refresh and has_creator and has_create_time and has_modif_time and has_modified_by:
            continue

        doc_details = None
        # Try to get from cache first
        if item_id in self._doc_details_cache and not force_refresh:
            doc_details = self._doc_details_cache[item_id]
            total_from_cache += 1
        else:
            # Fetch from API
            try:
                doc_details = self.api.get_document_details(item_id)
                if doc_details and isinstance(doc_details, dict):
                    # Cache the details
                    self._doc_details_cache[item_id] = doc_details
                else:
                    continue
            except Exception as e:
                continue

        if doc_details and isinstance(doc_details, dict):
            # Update item with full details
            updated = False
            if not has_creator and doc_details.get("createdBy"):
                item["createdBy"] = doc_details.get("createdBy")
                updated = True
            if not has_create_time and (doc_details.get("createTime") or doc_details.get("createdAt")):
                item["createTime"] = doc_details.get("createTime") or doc_details.get("createdAt")
                updated = True
            if not has_modif_time and (doc_details.get("modifTime") or doc_details.get("updatedAt") or doc_details.get("modifiedDate")):
                item["modifTime"] = doc_details.get("modifTime") or doc_details.get("updatedAt") or doc_details.get("modifiedDate")
                updated = True
            if not has_modified_by and (doc_details.get("modifiedBy") or doc_details.get("author")):
                item["modifiedBy"] = doc_details.get("modifiedBy") or doc_details.get("author")
                updated = True

            if updated:
                total_enriched += 1

    print(f"[lazy_enrich_file_list] Enrichment completed: {total_enriched} files enriched, {total_from_cache} from cache")
    return total_enriched


def lazy_enrich_current_files(self, limit_per_folder: int = 200, force_refresh: bool = False):
    """Lazy enrich current files with metadata by calling get_document_details for each file.

    Args:
        limit_per_folder: Maximum number of files per folder to enrich (default: 200)
        force_refresh: If True, force refresh even if files are already enriched
    """
    project_id = self.current_project_id()
    if not project_id:
        return

    files = getattr(self, "files_current", [])
    if not files:
        return

    print(f"[lazy_enrich_current_files] Starting enrichment for {len(files)} files")

    # Initialize document details cache if not exists
    if not hasattr(self, "_doc_details_cache"):
        self._doc_details_cache = {}

    # Check which fields are missing from file list response
    # These are the fields needed by FilesTableModel:
    # - createdBy (column 5)
    # - createTime/createdAt (column 6)
    # - modifTime/updatedAt/modifiedDate (column 7)
    # - modifiedBy/author (column 8)

    # Group files by folder (or "unknown" if no folderId)
    folders = {}
    for item in files:
        if not isinstance(item, dict):
            continue
        fid = item.get("folderId") or item.get("folder_id") or item.get("parent")
        if fid:
            fid = normalize_id(fid)
        else:
            fid = "unknown"
        folders.setdefault(fid, []).append(item)

    # Enrich each folder's files
    total_enriched = 0
    total_from_cache = 0
    for fid, items in folders.items():
        if len(items) > limit_per_folder:
            print(f"[lazy_enrich_current_files] Skipping folder {fid} - too many files ({len(items)} > {limit_per_folder})")
            continue

        print(f"[lazy_enrich_current_files] Enriching folder {fid} with {len(items)} files")

        for item in items:
            if item.get("type") != "file":
                continue

            item_id = normalize_id(item.get("id"))
            if not item_id:
                continue

            # Check if file already has all required fields
            has_creator = bool(item.get("createdBy"))
            has_create_time = bool(item.get("createTime") or item.get("createdAt"))
            has_modif_time = bool(item.get("modifTime") or item.get("updatedAt") or item.get("modifiedDate"))
            has_modified_by = bool(item.get("modifiedBy") or item.get("author"))

            if not force_refresh and has_creator and has_create_time and has_modif_time and has_modified_by:
                print(f"[lazy_enrich_current_files] File {item_id} already has all fields, skipping")
                continue

            doc_details = None
            # Try to get from cache first
            if item_id in self._doc_details_cache and not force_refresh:
                doc_details = self._doc_details_cache[item_id]
                total_from_cache += 1
                print(f"[lazy_enrich_current_files] Using cached details for file {item_id}")
            else:
                # Fetch from API
                try:
                    doc_details = self.api.get_document_details(item_id)
                    if doc_details and isinstance(doc_details, dict):
                        # Cache the details
                        self._doc_details_cache[item_id] = doc_details
                    else:
                        print(f"[lazy_enrich_current_files] No details returned for file {item_id}")
                        continue
                except Exception as e:
                    print(f"[lazy_enrich_current_files] ERROR enriching file {item_id}: {e}")
                    continue

            if doc_details and isinstance(doc_details, dict):
                # Update item with full details from get_document_details
                # Only update missing fields to preserve any data
                updated = False
                if not has_creator and doc_details.get("createdBy"):
                    item["createdBy"] = doc_details.get("createdBy")
                    updated = True
                if not has_create_time and (doc_details.get("createTime") or doc_details.get("createdAt")):
                    item["createTime"] = doc_details.get("createTime") or doc_details.get("createdAt")
                    updated = True
                if not has_modif_time and (doc_details.get("modifTime") or doc_details.get("updatedAt") or doc_details.get("modifiedDate")):
                    item["modifTime"] = doc_details.get("modifTime") or doc_details.get("updatedAt") or doc_details.get("modifiedDate")
                    updated = True
                if not has_modified_by and (doc_details.get("modifiedBy") or doc_details.get("author")):
                    item["modifiedBy"] = doc_details.get("modifiedBy") or doc_details.get("author")
                    updated = True

                if updated:
                    total_enriched += 1
                    print(f"[lazy_enrich_current_files] Enriched file {item_id}: {doc_details.get('name') or doc_details.get('fileName')}")

    print(f"[lazy_enrich_current_files] Enrichment completed: {total_enriched} files enriched, {total_from_cache} from cache")


def on_flat_toggled(self, _checked: bool):
    """Handle flat view toggle."""
    try:
        checked = bool(getattr(self, "cb_flat", None) is not None and self.cb_flat.isChecked())
    except Exception:
        checked = bool(_checked)

    if checked:
        if not hasattr(self, "_apply_recursive_flat_view"):
            print("[no-folders] ERROR: _apply_recursive_flat_view is missing")
            return
        try:
            self._apply_recursive_flat_view()
        except Exception as e:
            print(f"[no-folders] ERROR applying flat view: {e}")
        return

    # Disabled: return to normal direct-level listing.
    try:
        self._flat_recursive_mode = False
        self._flat_base_folder_id = None
        self._flat_files_source = []
    except Exception:
        pass

    try:
        current_item = self.tree.currentItem() if hasattr(self, "tree") else None
        current_node = current_item.data(0, Qt.UserRole) if current_item is not None else None
    except Exception:
        current_node = None

    try:
        if isinstance(current_node, dict):
            self.open_folder_node(current_node, save_to_history=False)
        else:
            self.go_to_project_root()
    except Exception as e:
        print(f"[no-folders] ERROR restoring normal view: {e}")

    try:
        self.apply_table_filters()
    except Exception:
        pass


def _flat_base_node(self) -> dict | None:
    """Return base folder node for flat mode (current tree selection or root)."""
    try:
        item = self.tree.currentItem() if hasattr(self, "tree") else None
        node = item.data(0, Qt.UserRole) if item is not None else None
        if isinstance(node, dict):
            return node
    except Exception:
        pass

    project_id = None
    try:
        project_id = self.current_project_id()
    except Exception:
        project_id = None
    if not project_id:
        return None
    return {"type": "folder", "id": project_id, "name": t("folder.root"), "children": [], "projectId": project_id}


def _collect_folder_ids_recursive(self, base_id: str, project_id: str) -> list[str]:
    """Discover base + all descendant folder ids by recursively listing folder contents."""
    if not base_id or not project_id:
        return []

    def _is_folder(it: dict) -> bool:
        try:
            tt = str(it.get("type") or "").lower()
            return tt in ("folder", "dir", "directory", "папка")
        except Exception:
            return False

    def _fid(it: dict) -> str:
        try:
            return normalize_id(it.get("id") or it.get("folderId") or it.get("folder_id"))
        except Exception:
            return ""

    out: list[str] = []
    seen: set[str] = set()
    q: list[str] = [base_id]
    seen.add(base_id)

    while q:
        fid = q.pop(0)
        out.append(fid)

        try:
            res = self.api.list_files_result(fid, project_id=project_id)
        except Exception as e:
            print(f"[no-folders] ERROR list_files_result({fid}) while collecting folders: {e}")
            continue
        if not getattr(res, "ok", False):
            err = getattr(res, "error", None)
            print(f"[no-folders] list_files_result({fid}) not ok error={err}")
            continue

        items = getattr(res, "data", None) or []
        for it in items:
            if not isinstance(it, dict) or (not _is_folder(it)):
                continue
            cid = _fid(it)
            if not cid or cid in seen:
                continue
            seen.add(cid)
            q.append(cid)

    return out


def _flat_item_type(self, item: dict) -> str:
    """Classify API item for flat mode as folder/file/other."""
    if not isinstance(item, dict):
        return "other"

    raw_type = str(item.get("type") or item.get("kind") or item.get("nodeType") or "").strip().lower()
    if raw_type in ("folder", "dir", "directory", "папка"):
        return "folder"
    if raw_type in ("file", "document", "doc", "файл", "документ"):
        return "file"

    # Some API payloads omit `type` but still expose folder-ish structure.
    if item.get("children") is not None or item.get("folders") is not None:
        return "folder"

    file_markers = (
        item.get("fileName"),
        item.get("originalName"),
        item.get("mimeType"),
        item.get("extension"),
        item.get("size"),
        item.get("documentId"),
    )
    if any(v not in (None, "") for v in file_markers):
        return "file"

    return "other"


def _collect_folder_nodes_recursive(self, node: dict) -> list[dict]:
    """Collect folder nodes for the subtree rooted at `node` using loaded folder tree.

    Supports both nesting keys: "children" and "folders".
    This is mainly used for diagnostics/compatibility; flat-mode loading uses API recursion.
    """
    if not isinstance(node, dict):
        return []

    base_id = normalize_id(node.get("id") or node.get("folderId"))
    project_id = normalize_id(node.get("projectId") or node.get("project_id") or self.current_project_id())
    if not base_id or not project_id:
        return []

    if base_id == project_id:
        base = {"type": "folder", "id": base_id, "projectId": project_id, "children": (getattr(self, "full_tree", None) or [])}
    else:
        try:
            base = self._find_folder_in_tree(getattr(self, "full_tree", None) or [], base_id)
        except Exception:
            base = None
        if not isinstance(base, dict):
            base = {"type": "folder", "id": base_id, "projectId": project_id, "children": []}

    out: list[dict] = []

    def walk(n: dict) -> None:
        if not isinstance(n, dict):
            return
        typ = str(n.get("type") or "").lower()
        is_folder = typ in ("folder", "dir", "directory", "папка")
        if not is_folder:
            try:
                is_folder = (isinstance(n.get("children"), list) or isinstance(n.get("folders"), list))
            except Exception:
                is_folder = False
        if not is_folder:
            return
        out.append(n)
        for ch in (n.get("children") or n.get("folders") or []):
            if isinstance(ch, dict):
                walk(ch)

    walk(base)
    return out


def _load_flat_files_for_node(self, node: dict) -> list[dict]:
    """Load flat recursive file list for node subtree via API."""
    if not isinstance(node, dict):
        return []

    project_id = normalize_id(node.get("projectId") or node.get("project_id") or self.current_project_id())
    base_id = normalize_id(node.get("id") or node.get("folderId"))
    if not project_id or not base_id:
        print(f"[no-folders] ERROR: missing ids base_id={base_id} project_id={project_id}")
        return []

    print(f"[no-folders] base_id={base_id}")

    try:
        # Extra diagnostic: what the loaded tree thinks the subtree is.
        tn = self._collect_folder_nodes_recursive(node)
        tids = [normalize_id(x.get("id") or x.get("folderId")) for x in tn if isinstance(x, dict)]
        print(f"[no-folders] tree_subtree_folders={len(tids)} ids={tids}")
    except Exception as e:
        print(f"[no-folders] ERROR collecting subtree from loaded tree: {e}")

    files_out: list[dict] = []
    seen_files: set[str] = set()
    visited: list[str] = []
    seen_folders: set[str] = {base_id}
    queue: list[str] = [base_id]
    total_folder_refs = 0

    while queue:
        fid = queue.pop(0)
        visited.append(fid)

        items = []
        res_ok = False
        try:
            res = self.api.list_files_result(fid, project_id=project_id)
            res_ok = bool(getattr(res, "ok", False))
            if res_ok:
                items = list(getattr(res, "data", None) or [])
            else:
                err = getattr(res, "error", None)
                print(f"[no-folders] list_files_result({fid}) not ok error={err}")
        except Exception as e:
            print(f"[no-folders] ERROR list_files_result({fid}): {e}")

        print(f"[no-folders] list_files_result({fid}) -> {len(items)} items")

        folder_refs_in_items = 0
        file_count_before = len(files_out)
        for item in items:
            if not isinstance(item, dict):
                continue
            item_type = self._flat_item_type(item)
            if item_type == "folder":
                child_id = normalize_id(item.get("id") or item.get("folderId") or item.get("folder_id"))
                if child_id and child_id not in seen_folders:
                    seen_folders.add(child_id)
                    queue.append(child_id)
                if child_id:
                    folder_refs_in_items += 1
                continue
            if item_type != "file":
                continue

            item["type"] = "file"
            try:
                enrich_id_types(item)
            except Exception:
                pass
            if not item.get("folderId") and not item.get("folder_id"):
                item["folderId"] = fid
            file_id = normalize_id(item.get("id") or item.get("documentId"))
            if file_id and file_id in seen_files:
                continue
            if file_id:
                seen_files.add(file_id)
            files_out.append(item)

        total_folder_refs += folder_refs_in_items
        print(
            f"[no-folders] folder={fid} files_added={len(files_out) - file_count_before} folders_found={folder_refs_in_items}"
        )

        if res_ok and not items:
            try:
                docs = self.api.list_documents_in_folder(fid) or []
            except Exception as e:
                print(f"[no-folders] fallback list_documents_in_folder({fid}) ERROR: {e}")
                docs = []
            print(f"[no-folders] fallback list_documents_in_folder({fid}) -> {len(docs)} docs")
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                doc["type"] = "file"
                try:
                    enrich_id_types(doc)
                except Exception:
                    pass
                if not doc.get("folderId") and not doc.get("folder_id"):
                    doc["folderId"] = fid
                doc_id = normalize_id(doc.get("id") or doc.get("documentId"))
                if doc_id and doc_id in seen_files:
                    continue
                if doc_id:
                    seen_files.add(doc_id)
                files_out.append(doc)

    print(f"[no-folders] folder_ids_visited={visited}")
    print(f"[no-folders] folders_found={total_folder_refs}")
    print(f"[no-folders] flat_files_total={len(files_out)}")
    return files_out


def _apply_recursive_flat_view(self, base_node: dict | None = None) -> None:
    """Build and apply recursive flat file list as the table source."""
    base = base_node if isinstance(base_node, dict) else self._flat_base_node()
    if not isinstance(base, dict):
        print("[no-folders] ERROR: no base node")
        return

    base_id = normalize_id(base.get("id") or base.get("folderId"))
    if not base_id:
        print("[no-folders] ERROR: base_id is empty")
        return

    try:
        # Cache by base folder id to avoid API calls on each keystroke.
        if getattr(self, "_flat_recursive_mode", False) and getattr(self, "_flat_base_folder_id", None) == base_id:
            files = list(getattr(self, "_flat_files_source", []) or [])
        else:
            prev_files_count = len(getattr(self, "files_current", []) or [])
            files = self._load_flat_files_for_node(base)
            if not files and prev_files_count:
                print(
                    f"[no-folders] WARNING empty flat result for base_id={base_id} previous_visible_files={prev_files_count}"
                )
            self._flat_files_source = files
            self._flat_base_folder_id = base_id
    except Exception as e:
        print(f"[no-folders] ERROR building flat list: {e}")
        files = []

    self._flat_recursive_mode = True

    # Source model must contain only files.
    self.files_current = [it for it in (files or []) if isinstance(it, dict) and str(it.get("type") or "").lower() == "file"]

    try:
        from larix_nexus.models.files_table import FilesTableModel
        self.files_model = FilesTableModel(self.files_current, self.icon_provider, self.checked)
        self.proxy.setSourceModel(self.files_model)
    except Exception as e:
        print(f"[no-folders] ERROR replacing model: {e}")

    try:
        self.apply_table_filters()
    except Exception:
        pass


def update_path_label(self):
    """Update path label with current folder path."""
    if not hasattr(self, "lbl_path"):
        return
    
    current_fid = None
    current_item = self.tree.currentItem()
    if current_item:
        current_fid = current_item.data(0, Qt.UserRole + 1)
    
    if not current_fid:
        project_id = self.current_project_id()
        if project_id:
            self.lbl_path.setText(t("folder.root"))
        else:
            self.lbl_path.setText("")
        return
    
    # Build path
    path_parts = []
    item = current_item
    while item:
        fid = item.data(0, Qt.UserRole + 1)
        name = item.text(0)
        path_parts.append(name)
        item = item.parent()
    
    if path_parts:
        path_parts.reverse()
        path = " / ".join(path_parts)
        self.lbl_path.setText(path)
    else:
        self.lbl_path.setText("")


def inject_tree_operations_to_main_window(MainWindowClass):
    """Inject tree operations into MainWindow class."""
    MainWindowClass.get_folder_tree_item = get_folder_tree_item
    MainWindowClass._restore_tree_badges = _restore_tree_badges
    MainWindowClass.populate_tree_widget = populate_tree_widget
    MainWindowClass.load_tree_for_project = load_tree_for_project
    MainWindowClass.refresh_tree = refresh_tree
    MainWindowClass.soft_refresh_and_restore_view = soft_refresh_and_restore_view
    MainWindowClass.on_tree_click = on_tree_click
    MainWindowClass.tree_context_menu = tree_context_menu
    MainWindowClass.go_to_project_root = go_to_project_root
    MainWindowClass.go_back = go_back
    MainWindowClass.open_folder_node = open_folder_node
    MainWindowClass.lazy_enrich_current_files = lazy_enrich_current_files
    MainWindowClass.lazy_enrich_file_list = lazy_enrich_file_list
    MainWindowClass.on_flat_toggled = on_flat_toggled
    MainWindowClass.update_path_label = update_path_label

    # "Без папок" recursive flat view helpers.
    MainWindowClass._flat_base_node = _flat_base_node
    MainWindowClass._collect_folder_ids_recursive = _collect_folder_ids_recursive
    MainWindowClass._flat_item_type = _flat_item_type
    MainWindowClass._collect_folder_nodes_recursive = _collect_folder_nodes_recursive
    MainWindowClass._load_flat_files_for_node = _load_flat_files_for_node
    MainWindowClass._apply_recursive_flat_view = _apply_recursive_flat_view

    # Flat-mode navigation helper (context menu action).
    MainWindowClass._item_parent_folder_id = _item_parent_folder_id
    MainWindowClass._find_tree_item_by_folder_id = _find_tree_item_by_folder_id
    MainWindowClass._go_to_file_parent_folder = _go_to_file_parent_folder
