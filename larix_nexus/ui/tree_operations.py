# -*- coding: utf-8 -*-
"""Tree widget operations for Larix Nexus."""

from PySide6.QtCore import Qt, QSignalBlocker, QThread, QTimer, QMetaObject
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QTreeWidgetItem, QMessageBox, QTreeWidget
from PySide6.QtGui import QIcon
from ..utils.helpers import normalize_id
from ..api import APIClient
from ..constants import FOLDER_ICON_PATH


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
    
    # Preload icon once.
    try:
        folder_icon = QIcon(FOLDER_ICON_PATH)
    except Exception:
        folder_icon = QIcon()

    def add_items(parent: QTreeWidgetItem, items: list):
        for item in items:
            if not isinstance(item, dict):
                continue
            typ = item.get("type", "").lower()
            if typ not in ("folder", "dir", "directory", "папка"):
                continue

            fid = item.get("id")
            name = item.get("name") or item.get("title") or "Без названия"

            tree_item = QTreeWidgetItem(parent)
            tree_item.setText(0, name)
            tree_item.setData(0, Qt.UserRole, item)
            tree_item.setData(0, Qt.UserRole + 1, fid)

            try:
                if not folder_icon.isNull():
                    tree_item.setIcon(0, folder_icon)
            except Exception:
                pass

            if fid:
                self.folder_item_by_id[fid] = tree_item

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


def load_tree_for_project(self, project_id: int | str):
    """Load tree for specified project."""
    project_id = normalize_id(project_id)
    
    try:
        nodes = self.api.list_folders(project_id) or []
    except Exception as e:
        QMessageBox.warning(self, "Ошибка", f"Не удалось загрузить дерево папок: {e}")
        return
    
    self.populate_tree_widget(self.tree, nodes)
    
    # Restore sync badges
    try:
        sync_mappings = getattr(self, "_sync_mappings", {})
        for fid, item in self.folder_item_by_id.items():
            if fid in sync_mappings:
                item.setData(0, Qt.UserRole + 2, "sync")
    except Exception:
        pass


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

        # Restore sync badges
        try:
            sync_mappings = getattr(self, "_sync_mappings", {})
            for fid, item in self.folder_item_by_id.items():
                if fid in sync_mappings:
                    item.setData(0, Qt.UserRole + 2, "sync")
        except Exception:
            pass

        # Restore selection and reload files. Do it on next tick to avoid
        # re-entrancy while the tree is being rebuilt.
        if current_fid and current_fid in self.folder_item_by_id:
            try:
                self.tree.setCurrentItem(self.folder_item_by_id[current_fid])
            except Exception:
                pass

            try:
                from PySide6.QtCore import QTimer

                def _reload_current_folder():
                    try:
                        name = ""
                        try:
                            name = self.folder_item_by_id[current_fid].text(0)
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


def tree_context_menu(self, pos):
    """Show context menu for tree widget."""
    from PySide6.QtWidgets import QMenu
    import PySide6.QtCore as QtCore
    
    item = self.tree.itemAt(pos)
    if not item:
        return
    
    node = item.data(0, Qt.UserRole)
    if not isinstance(node, dict):
        return
    
    try:
        typ = str((node or {}).get("type") or "").lower()
    except Exception:
        typ = ""
    if typ != "folder":
        return

    menu = QMenu(self)
    menu.setObjectName("treeMenu")
    
    act_zip = menu.addAction("Скачать как ZIP")
    act_folder = menu.addAction("Скачать структуру")
    menu.addSeparator()
    
    act_copy_folder = menu.addAction("Копировать папку...")
    act_move_folder = menu.addAction("Переместить папку...")
    menu.addSeparator()

    folder_id = (node or {}).get("id")
    fid_key = normalize_id(folder_id)
    pth = ""
    is_synced = bool(getattr(self, 'sync2', None) and self.sync2.is_synced(folder_id))
    act_path_open = None
    act_unsync = None
    act_sync = None
    act_sync_now = None
    act_view_notif = None
    act_sub = None
    
    if is_synced:
        try:
            pth = self.sync2.get_sync_path(folder_id)
            act_path_open = menu.addAction("Путь синхронизации…")
            act_path_open.setToolTip(pth)
        except Exception:
            pth = ""
        try:
            eta_ms = -1
            cfg = self.sync2.map.get(fid_key) if hasattr(self, 'sync2') else None
            if cfg and bool(cfg.get('initial_ok')) and self.sync2.timer.isActive():
                eta_ms = int(self.sync2.timer.remainingTime())
            def _fmt_eta(ms: int) -> str:
                try:
                    if ms is None or ms < 0:
                        return "—"
                    s = int(ms // 1000)
                    m, s = divmod(max(0, s), 60)
                    if m > 0:
                        return f"{m} мин {s:02d} сек"
                    return f"{s} сек"
                except Exception:
                    return "—"
            eta_text = _fmt_eta(eta_ms)
            act_eta = menu.addAction(f"Следующая синхронизация: через {eta_text}")
            act_eta.setEnabled(False)
        except Exception:
            pass
        act_unsync = menu.addAction("Отключить синхронизацию")
    else:
        act_sync = menu.addAction("Синхронизировать...")
        try:
            act_sync.setEnabled(bool(self.api.is_available()))
        except Exception:
            pass

    if is_synced:
        try:
            act_sync_now = menu.addAction("Синхронизировать сейчас")
        except Exception:
            act_sync_now = None

    subscribed = False
    has_changes = False
    try:
        menu.addSeparator()
        title = item.text(0)
        folder_id_int = fid_key
        
        try:
            subscribed = folder_id_int in getattr(self, '_subscriptions', {})
        except Exception:
            subscribed = False

        try:
            has_changes = folder_id_int in self._pending_notifications
        except Exception:
            has_changes = False

        if subscribed and has_changes:
            act_view_notif = menu.addAction("Уведомления")

        try:
            if subscribed:
                act_sub = menu.addAction("Отписаться от уведомлений")
            else:
                act_sub = menu.addAction("Подписаться на уведомления")
        except Exception:
            act_sub = None

    except Exception:
        pass

    print(f"[tree_context_menu] Showing menu for folder: {(node or {}).get('name')}")
    try:
        chosen = self._menu_exec(menu, self.tree.mapToGlobal(pos))
    except Exception as e:
        print(f"[tree_context_menu] _menu_exec failed, using menu.exec_: {e}")
        chosen = menu.exec_(self.tree.mapToGlobal(pos))
    print(f"[tree_context_menu] Chosen action: {chosen}")
    if not chosen:
        return

    print(f"[tree_context_menu] Comparing chosen with actions...")
    print(f"[tree_context_menu] act_zip={act_zip}, act_folder={act_folder}, act_copy_folder={act_copy_folder}, act_move_folder={act_move_folder}")
    print(f"[tree_context_menu] act_sync={act_sync}, act_unsync={act_unsync}, act_path_open={act_path_open}, act_sync_now={act_sync_now}")
    print(f"[tree_context_menu] act_view_notif={act_view_notif}, act_sub={act_sub}")
    
    if chosen == act_zip:
        print("[tree_context_menu] Download ZIP clicked")
        self.download_folder_as_zip(node)
        return
    if chosen == act_folder:
        print("[tree_context_menu] Download structure clicked")
        self.download_folder_plain(node)
        return
    if act_sync_now and chosen == act_sync_now:
        print("[tree_context_menu] Sync now clicked")
        try:
            self._trigger_sync_now(folder_id)
        except Exception:
            pass
        return
    if act_path_open and chosen == act_path_open:
        print("[tree_context_menu] Open path clicked")
        if pth:
            try:
                import os
                import subprocess
                import sys
                if sys.platform == "win32":
                    os.startfile(pth)
                elif sys.platform == "darwin":
                    subprocess.run(["open", pth])
                else:
                    subprocess.run(["xdg-open", pth])
            except Exception:
                pass
        return

    if act_unsync and chosen == act_unsync:
        print("[tree_context_menu] Unsync clicked")
        try:
            self.sync2.remove_sync(folder_id)
            SYNC_ROLE = Qt.UserRole + 2
            item.setData(0, SYNC_ROLE, False)
            self.tree.viewport().update()

            QMessageBox.information(self, "Синхронизация", "Синхронизация отключена.")
        except Exception:
            pass
        return
    if act_sync and chosen == act_sync:
        print("[tree_context_menu] Sync clicked")
        try:
            proj = self.current_project_id()
        except Exception:
            proj = None
        if not proj:
            QMessageBox.warning(self, "Синхронизация", "Не выбран проект.")
            return
        try:
            folder_title = item.text(0)
        except Exception:
            try:
                folder_title = (node or {}).get("name") or ""
            except Exception:
                folder_title = ""
        QtCore.QTimer.singleShot(0, lambda fid=folder_id, ft=folder_title, pid=proj: self._sync_add_mapping(fid, ft, pid))
        return

    if act_copy_folder and chosen == act_copy_folder:
        print("[tree_context_menu] Copy folder clicked")
        try:
            self.copy_folder_action()
        except Exception:
            pass
        return

    if act_move_folder and chosen == act_move_folder:
        print("[tree_context_menu] Move folder clicked")
        try:
            self.move_folder_action()
        except Exception:
            pass
        return

    if act_view_notif and chosen == act_view_notif:
        print("[tree_context_menu] View notifications clicked")
        if node:
            try:
                folder_id_check = normalize_id((node or {}).get("id"))
                if folder_id_check:
                    self._show_changes_dialog(folder_id_check)
            except Exception as e:
                QMessageBox.warning(self, "Ошибка", f"Не удалось показать уведомления: {e}")
        return

    if act_sub and chosen == act_sub:
        print("[tree_context_menu] Toggle subscription clicked")
        if node:
            try:
                self.toggle_folder_notifications(node)
            except Exception as e:
                QMessageBox.warning(self, "Ошибка", f"Не удалось изменить подписку: {e}")
        return
    
    print(f"[tree_context_menu] No action matched, chosen={chosen}, type={type(chosen)}")


def go_to_project_root(self):
    """Navigate to project root folder."""
    project_id = self.current_project_id()
    if not project_id:
        return
    
    root_node = {"type": "folder", "id": project_id, "name": "Корень", "children": [], "projectId": project_id}
    self.open_folder_node(root_node)


def go_back(self):
    """Navigate back in folder history."""
    history = getattr(self, "_folder_history", [])
    if not history:
        return
    
    # Remove current folder from history
    if history:
        history.pop()
    
    # Get previous folder
    if history:
        prev_node = history[-1]
        self.open_folder_node(prev_node, save_to_history=False)


def open_folder_node(self, node: dict, save_to_history: bool = True):
    """Open folder and display its contents."""
    if not isinstance(node, dict):
        return

    typ = node.get("type", "").lower()
    if typ not in ("folder", "dir", "directory", "папка"):
        return

    fid = normalize_id(node.get("id") or node.get("folderId"))
    if not fid:
        return

    # Get project_id from node or current project
    project_id = node.get("projectId") or node.get("project_id") or self.current_project_id()

    print(f"[open_folder_node] Opening folder: fid={fid}, name={node.get('name')}, project_id={project_id}")
    try:
        files = self.api.list_files(fid, project_id=project_id) or []
        print(f"[open_folder_node] Got {len(files)} files from API")
    except Exception as e:
        print(f"[open_folder_node] ERROR loading files: {e}")
        QMessageBox.warning(self, "Ошибка", f"Не удалось загрузить файлы: {e}")
        return

    self.files_current = files
    self.update_table()
    
    # Update path label
    name = node.get("name") or node.get("title") or "Без названия"
    self.update_path_label()
    
    # Save to history
    if save_to_history:
        history = getattr(self, "_folder_history", [])
        history.append(node)
        self._folder_history = history


def lazy_enrich_current_files(self, limit_per_folder: int = 200):
    """Lazy enrich current files with metadata."""
    project_id = self.current_project_id()
    if not project_id:
        return
    
    files = getattr(self, "files_current", [])
    if not files:
        return
    
    # Group by folder
    folders = {}
    for item in files:
        if not isinstance(item, dict):
            continue
        fid = item.get("folderId") or item.get("folder_id") or item.get("parent")
        if fid:
            fid = normalize_id(fid)
            folders.setdefault(fid, []).append(item)
    
    # Enrich each folder
    for fid, items in folders.items():
        if len(items) > limit_per_folder:
            continue
        try:
            details = self.api.get_folder_details(fid)
            if details:
                for item in items:
                    item_id = normalize_id(item.get("id"))
                    if item_id in details:
                        item.update(details[item_id])
        except Exception:
            pass


def on_flat_toggled(self, _checked: bool):
    """Handle flat view toggle."""
    project_id = self.current_project_id()
    if not project_id:
        return
    self.refresh_tree()


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
            self.lbl_path.setText("Корень")
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
    MainWindowClass.on_flat_toggled = on_flat_toggled
    MainWindowClass.update_path_label = update_path_label
