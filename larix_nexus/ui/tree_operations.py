# -*- coding: utf-8 -*-
"""Tree widget operations for Larix Nexus."""

from PySide6.QtCore import Qt, QSignalBlocker, QThread, QTimer, QMetaObject
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QTreeWidgetItem, QMessageBox, QTreeWidget
from PySide6.QtGui import QIcon
from ..utils.helpers import normalize_id, normalize_project_id
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
        vp = self.tree.viewport()
        if vp is not None:
            vp.update()
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
        QMessageBox.warning(self, "Ошибка", f"Не удалось загрузить дерево папок: {e}")
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
                    pass

            QTimer.singleShot(0, _run)
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
                from PySide6.QtCore import QTimer
                try:
                    trace("soft_refresh: scheduling reload for folder_id={}", current_fid)
                except Exception:
                    pass

                def _reload_current_folder():
                    try:
                        # If the UI is already closing, don't touch Qt objects.
                        try:
                            from shiboken6 import isValid  # type: ignore
                            tree = getattr(self, "tree", None)
                            if tree is None or not isValid(tree):
                                return
                        except Exception:
                            pass

                        try:
                            trace("soft_reload: starting for folder_id={}", current_fid)
                        except Exception:
                            pass

                        name = ""
                        try:
                            item = self.folder_item_by_id.get(current_fid)
                            if item is not None:
                                # Validate QTreeWidgetItem before accessing
                                try:
                                    from shiboken6 import isValid
                                    if not isValid(item):
                                        try:
                                            trace("soft_reload: item is invalid, skipping")
                                        except Exception:
                                            pass
                                        return
                                except Exception:
                                    # shiboken6 not available, try to access anyway
                                    pass
                                name = item.text(0)
                            else:
                                try:
                                    trace("soft_reload: item not found in folder_item_by_id")
                                except Exception:
                                    pass
                        except Exception as e:
                            try:
                                trace("soft_reload: error getting item name: {}", str(e))
                            except Exception:
                                pass

                        node = {"type": "folder", "id": current_fid, "name": name, "projectId": project_id}
                        try:
                            trace("soft_reload: calling open_folder_node for {}", name)
                        except Exception:
                            pass
                        self.open_folder_node(node, save_to_history=False)
                        try:
                            trace("soft_reload: completed successfully")
                        except Exception:
                            pass
                    except Exception as e:
                        try:
                            trace("soft_reload: ERROR: {}", str(e))
                            import traceback
                            trace("soft_reload: TRACEBACK: {}", traceback.format_exc())
                        except Exception:
                            pass

                QTimer.singleShot(0, _reload_current_folder)
            except Exception as e:
                try:
                    trace("soft_refresh: ERROR scheduling reload: {}", str(e))
                except Exception:
                    pass
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
            vp = self.tree.viewport()
            if vp is not None:
                vp.update() 

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
    try:
        trace("open_folder_node: start")
    except Exception:
        pass

    if not isinstance(node, dict):
        try:
            trace("open_folder_node: node is not dict, returning")
        except Exception:
            pass
        return

    typ = node.get("type", "").lower()
    if typ not in ("folder", "dir", "directory", "папка"):
        try:
            trace("open_folder_node: node type is not folder, returning")
        except Exception:
            pass
        return

    fid = normalize_id(node.get("id") or node.get("folderId"))
    if not fid:
        try:
            trace("open_folder_node: no folder id, returning")
        except Exception:
            pass
        return

    # Get project_id from node or current project
    project_id = node.get("projectId") or node.get("project_id") or self.current_project_id()

    print(f"[open_folder_node] Opening folder: fid={fid}, name={node.get('name')}, project_id={project_id}")
    try:
        trace("open_folder_node: calling api.list_files")
    except Exception:
        pass
    try:
        files = self.api.list_files(fid, project_id=project_id) or []
        print(f"[open_folder_node] Got {len(files)} files from API")
        try:
            trace("open_folder_node: got {} files", len(files))
        except Exception:
            pass
    except Exception as e:
        print(f"[open_folder_node] ERROR loading files: {e}")
        try:
            trace("open_folder_node: ERROR loading files: {}", str(e))
        except Exception:
            pass
        QMessageBox.warning(self, "Ошибка", f"Не удалось загрузить файлы: {e}")
        return

    self.files_current = files
    try:
        trace("open_folder_node: calling update_table")
    except Exception:
        pass
    try:
        self.update_table()
        try:
            trace("open_folder_node: update_table completed")
        except Exception:
            pass
    except Exception as e:
        print(f"[open_folder_node] ERROR in update_table: {e}")
        try:
            trace("open_folder_node: ERROR in update_table: {}", str(e))
        except Exception:
            pass
        import traceback
        traceback.print_exc()

    # Enrich files with metadata (including createdBy/modifiedBy)
    try:
        trace("open_folder_node: calling lazy_enrich_current_files")
    except Exception:
        pass
    try:
        self.lazy_enrich_current_files(limit_per_folder=300)
        try:
            trace("open_folder_node: lazy_enrich_current_files completed")
        except Exception:
            pass
    except Exception as e:
        print(f"[open_folder_node] ERROR in lazy_enrich_current_files: {e}")
        try:
            trace("open_folder_node: ERROR in lazy_enrich_current_files: {}", str(e))
        except Exception:
            pass
        import traceback
        traceback.print_exc()

    # Update path label
    name = node.get("name") or node.get("title") or "Без названия"
    try:
        trace("open_folder_node: calling update_path_label")
    except Exception:
        pass
    try:
        self.update_path_label()
        try:
            trace("open_folder_node: update_path_label completed")
        except Exception:
            pass
    except Exception as e:
        print(f"[open_folder_node] ERROR in update_path_label: {e}")
        try:
            trace("open_folder_node: ERROR in update_path_label: {}", str(e))
        except Exception:
            pass
        import traceback
        traceback.print_exc()

    # Save to history
    if save_to_history:
        history = getattr(self, "_folder_history", [])
        history.append(node)
        self._folder_history = history
        try:
            trace("open_folder_node: saved to history")
        except Exception:
            pass

    try:
        trace("open_folder_node: completed successfully")
    except Exception:
        pass


def lazy_enrich_current_files(self, limit_per_folder: int = 200):
    """Lazy enrich current files with metadata."""
    try:
        trace("lazy_enrich: start")
    except Exception:
        pass

    project_id = self.current_project_id()
    if not project_id:
        try:
            trace("lazy_enrich: no project_id, returning")
        except Exception:
            pass
        return

    files = getattr(self, "files_current", [])
    if not files:
        try:
            trace("lazy_enrich: no files, returning")
        except Exception:
            pass
        return

    try:
        trace("lazy_enrich: processing {} files", len(files))
    except Exception:
        pass
    print(f"[lazy_enrich] Starting enrichment for {len(files)} files")

    from concurrent.futures import ThreadPoolExecutor, as_completed
    from PySide6.QtWidgets import QApplication

    def fetch_details(item):
        try:
            item_type = item.get("type")
            item_id = item.get("id")
            if not item_id:
                return
            if item_type == "folder":
                d = self.api.get_folder_details(item_id)
            elif item_type == "file":
                d = self.api.get_document_details(item_id)
            else:
                return
            if d:
                if "createdBy" in d: item["createdBy"] = d["createdBy"]
                if "modifiedBy" in d: item["modifiedBy"] = d["modifiedBy"]
                if "createTime" in d and not item.get("createTime"): item["createTime"] = d["createTime"]
                if "modifTime" in d and not item.get("modifTime"): item["modifTime"] = d["modifTime"]
                if "version" in d and not item.get("version"): item["version"] = d["version"]
        except Exception as e:
            print(f"[lazy_enrich] ERROR fetching details for {item.get('name')}: {e}")
            try:
                trace("lazy_enrich: ERROR fetching details: {}", str(e))
            except Exception:
                pass

    try:
        trace("lazy_enrich: creating ThreadPoolExecutor")
    except Exception:
        pass
    try:
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(fetch_details, it) for it in files if it.get("id")]
            print(f"[lazy_enrich] Submitted {len(futures)} enrichment tasks")
            completed = 0
            for _ in as_completed(futures):
                completed += 1
                if completed % 10 == 0:
                    print(f"[lazy_enrich] Progress: {completed}/{len(futures)}")
        print(f"[lazy_enrich] Completed all {len(futures)} enrichment tasks")
        try:
            trace("lazy_enrich: completed successfully")
        except Exception:
            pass
    except Exception as e:
        print(f"[lazy_enrich] FATAL ERROR: {e}")
        try:
            trace("lazy_enrich: FATAL ERROR: {}", str(e))
        except Exception:
            pass
        import traceback
        traceback.print_exc()


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
