# -*- coding: utf-8 -*-
"""Tree widget operations for Larix Nexus."""

import functools
from PySide6.QtCore import Qt, QSignalBlocker, QThread, QTimer, QMetaObject
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QTreeWidgetItem, QMessageBox, QTreeWidget
from PySide6.QtGui import QIcon
from ..utils.helpers import normalize_id, normalize_project_id, enrich_id_types
from ..utils.ui_trace import trace
from ..api import APIClient
from ..constants import FOLDER_ICON_PATH, SYNC_ROLE, NOTIFY_ROLE


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


def load_tree_for_project(self, project_id: int | str):
    """Load tree for specified project."""
    project_id = normalize_id(project_id)

    try:
        trace("load_tree_for_project: start project_id={}", project_id)
    except Exception:
        pass
    
    try:
        nodes = self.api.list_folders(project_id) or []
    except Exception as e:
        print(f"[tree_context_menu] Failed to load folders: {e}")
        return

    try:
        trace("load_tree_for_project: nodes={}", len(nodes) if isinstance(nodes, list) else -1)
    except Exception:
        pass
    
    self.populate_tree_widget(self.tree, nodes)

    # Restore badges (sync + notifications)
    try:
        _restore_tree_badges(self, project_id)
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

        # Badges are restored by load_tree_for_project()

        # Restore selection and reload files. Do it on next tick to avoid
        # re-entrancy while the tree is being rebuilt.
        if current_fid and current_fid in self.folder_item_by_id:
            try:
                self.tree.setCurrentItem(self.folder_item_by_id[current_fid])
            except Exception:
                pass

            try:

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
            # Clear sync badge immediately (delegate uses SYNC_ROLE).
            item.setData(0, SYNC_ROLE, False)
            self.tree.viewport().update()

            # Use status bar instead of QMessageBox to avoid crash on Windows + Python 3.13
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()
            try:
                if hasattr(self, 'status'):
                    self.status.showMessage("Синхронизация отключена.", 3000)
            except Exception:
                pass
        except Exception as e:
            print(f"[tree_context_menu] Error in unsync: {e}")
            import traceback
            traceback.print_exc()
        return
    if act_sync and chosen == act_sync:
        print("[tree_context_menu] Sync clicked")
        try:
            proj = self.current_project_id()
        except Exception:
            proj = None
        if not proj:
            # Use status bar instead of QMessageBox to avoid crash on Windows + Python 3.13
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()
            try:
                if hasattr(self, 'status'):
                    self.status.showMessage("Не выбран проект.", 3000)
            except Exception:
                pass
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
                print(f"[tree_context_menu] Failed to show notifications: {e}")
        return

    if act_sub and chosen == act_sub:
        print("[tree_context_menu] Toggle subscription clicked")
        if node:
            try:
                self.toggle_folder_notifications(node)
            except Exception as e:
                print(f"[tree_context_menu] Failed to toggle subscription: {e}")
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
        for f in files:
            if isinstance(f, dict):
                enrich_id_types(f)
        print(f"[open_folder_node] Got {len(files)} files from API")
        # Debug: print first file structure
        if files:
            print(f"[open_folder_node] First file keys: {list(files[0].keys()) if isinstance(files[0], dict) else 'not a dict'}")
            print(f"[open_folder_node] First file: {files[0] if len(files) > 0 else 'empty'}")
    except Exception as e:
        print(f"[open_folder_node] ERROR loading files: {e}")
        return

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
    self.update_table()
    
    # Update path label
    name = node.get("name") or node.get("title") or "Без названия"
    self.update_path_label()
    
    # Save to history
    if save_to_history:
        history = getattr(self, "_folder_history", [])
        history.append(node)
        self._folder_history = history


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
    MainWindowClass.lazy_enrich_file_list = lazy_enrich_file_list
    MainWindowClass.on_flat_toggled = on_flat_toggled
    MainWindowClass.update_path_label = update_path_label
