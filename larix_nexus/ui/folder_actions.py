# -*- coding: utf-8 -*-
"""Folder copy/move actions for Larix Nexus."""

import os
from PySide6.QtCore import Qt, QObject, QEvent, QModelIndex
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QInputDialog, QDialog, QVBoxLayout, QDialogButtonBox, QTreeWidget, QTreeWidgetItem, QMessageBox, QAbstractItemView
from PySide6.QtCore import QTimer
from .widgets import TreeBranchProxyStyle
from .delegates import MenuLikeTreeDelegate
from ..utils.logging import sync_log
from ..utils.copy_logger import copy_log


def _generate_unique_name(existing_names: set[str], name: str) -> str:
    """Generate unique name (file.txt -> file_копия.txt) if name is taken.
    
    Args:
        existing_names: Set of existing filenames in destination folder
        name: Original filename
    
    Returns:
        Unique filename with suffix if needed
    """
    base, ext = os.path.splitext(name)
    base = (base or "").strip()
    if not base:
        base = name.strip()
        ext = ""
    if not base:
        base = "file"
    
    name_lower = name.lower()
    existing_lower = {n.lower() for n in existing_names}
    
    if name_lower not in existing_lower:
        return name
    
    candidate = f"{base}_копия{ext}"
    idx = 2
    while candidate.lower() in existing_lower:
        candidate = f"{base}_копия{idx}{ext}"
        idx += 1
    return candidate


def copy_folder_action(self):
    """Copy selected folder to another folder."""
    item = self.selected_item()
    if not item or item.get("type") != "folder":
        print("Выберите папку для копирования.")
        return
    
    src_folder_id = item.get("id")
    src_name = item.get("name") or item.get("title") or "Без названия"
    
    result = self._prompt_folder_select("Выберите папку назначения для копирования", can_select_current=False)
    if not result:
        return
    
    dest_folder_id = result.get("id")
    dest_path = result.get("path")
    
    if dest_folder_id == src_folder_id:
        print("Нельзя скопировать папку в саму себя.")
        return
    
    new_name = f"{src_name}_копия"
    
    # Use QTimer to delay execution
    QTimer.singleShot(500, lambda: self._do_copy_folder(src_folder_id, dest_folder_id, new_name, dest_path))


def copy_selected_action(self):
    """Copy selected files/folders to another folder."""
    try:
        copy_log("[COPY] copy_selected_action: START", component="COPY")
    except Exception as e:
        pass
    try:
        items = self.get_checked_visible_items()
    except Exception as e:
        copy_log("[COPY] copy_selected_action: ERROR getting checked items: {}", str(e), component="COPY")
        import traceback
        traceback.print_exc()
        items = []
    
    copy_log("[COPY] copy_selected_action: checked items count = {}", len(items), component="COPY")
    
    if not items:
        try:
            items = self.get_selected_items()
            copy_log("[COPY] copy_selected_action: selected items count = {}", len(items), component="COPY")
        except Exception as e:
            copy_log("[COPY] copy_selected_action: ERROR getting selected items: {}", str(e), component="COPY")
            import traceback
            traceback.print_exc()
            items = []
    
    copy_log("[COPY] copy_selected_action: total items to copy = {}", len(items), component="COPY")
    
    if not items:
        copy_log("[COPY] copy_selected_action: NO ITEMS - no action", component="COPY")
        print("Выберите файлы или папки для копирования.")
        return
    
    project_id = self.current_project_id()
    copy_log("[COPY] copy_selected_action: project_id = {}", project_id, component="COPY")
    if not project_id:
        copy_log("[COPY] copy_selected_action: NO PROJECT - no action", component="COPY")
        print("Не выбран проект.")
        return
    
    # Get source folder info before opening destination dialog
    source_folder_node = self.current_folder_node()
    source_path = None
    if source_folder_node:
        source_name = source_folder_node.get("name") or source_folder_node.get("title") or "Без названия"
        source_path = f"\"{source_name}\""
    
    result = self._prompt_folder_select("Выберите папку назначения для копирования", can_select_current=True)
    copy_log("[COPY] copy_selected_action: folder select result = {}", str(result), component="COPY")
    if not result:
        copy_log("[COPY] copy_selected_action: CANCELLED - no folder selected", component="COPY")
        return
    
    # Add source path to result
    result["source_path"] = source_path
    
    # Use QTimer to delay execution and let dialog fully close
    QTimer.singleShot(500, lambda: self._do_copy(items, result))


def _do_copy(self, items, result):
    """Actually perform copy operation."""
    try:
        copy_log("[COPY] _do_copy: START", component="COPY")
    except Exception:
        pass
    
    dest_folder_id = result.get("id")
    dest_path = result.get("path")
    source_path = result.get("source_path", "текущей папки")
    copy_log("[COPY] _do_copy: source_path={}, dest_folder_id = {}, dest_path = {}", source_path, dest_folder_id, dest_path, component="COPY")
    
    # Get files in destination folder to check for duplicates
    dest_files = set()
    try:
        dest_files = self._existing_names_for_folder(dest_folder_id)
        copy_log("[COPY] destination folder has {} files: {}", len(dest_files), list(dest_files), component="COPY")
    except Exception as e:
        copy_log("[COPY] ERROR getting destination folder list: {}", str(e), component="COPY")
        dest_files = set()
    
    n_items = len(items)
    n_folders = sum(1 for it in items if it.get("type") == "folder")
    n_files = n_items - n_folders
    
    copy_log("[COPY] _do_copy: n_folders={}, n_files={}", n_folders, n_files, component="COPY")
    
    def _plural_form(n, forms):
        """Get correct plural form for Russian language.
        
        Args:
            n: number
            forms: tuple of (1, 2, 5) forms (e.g., ('файл', 'файла', 'файлов'))
        """
        n_mod10 = n % 10
        n_mod100 = n % 100
        if 10 < n_mod100 < 20:
            return forms[2]
        if n_mod10 == 1:
            return forms[0]
        if 2 <= n_mod10 <= 4:
            return forms[1]
        return forms[2]
    
    msg_parts = []
    if n_folders:
        folder_form = _plural_form(n_folders, ('папка', 'папки', 'папок'))
        msg_parts.append(f"{n_folders} {folder_form}")
    if n_files:
        file_form = _plural_form(n_files, ('файл', 'файла', 'файлов'))
        msg_parts.append(f"{n_files} {file_form}")
    msg = ", ".join(msg_parts)
    copy_log("[COPY] _do_copy: msg = {}", msg, component="COPY")
    
    ok_count = 0
    error_count = 0
    
    from PySide6.QtWidgets import QApplication
    
    self._set_progress_visible(True)
    self.progress.setRange(0, n_items)
    self.progress.setValue(0)
    QApplication.processEvents()
    
    for i, item in enumerate(items):
        self.progress.setValue(i + 1)
        self.status.showMessage(f"Копирование: {i+1} из {n_items} ({source_path} → {dest_path})")
        QApplication.processEvents()
        copy_log("[COPY] _do_copy: processing item {}/{}", i+1, n_items, component="COPY")
        try:
            item_id = item.get("id")
            item_type = item.get("type")
            item_name = item.get("name") or item.get("title") or "Без названия"
            
            copy_log("[COPY] item: id={}, type={}, name={}", item_id, item_type, item_name, component="COPY")
            
            # Generate unique name based on existing files in destination
            new_name = _generate_unique_name(dest_files, item_name)
            copy_log("[COPY] using name: {}", new_name, component="COPY")
            
            # Add the new name to the set to avoid conflicts for subsequent items
            dest_files.add(new_name)
            
            if item_type == "folder":
                copy_log("[COPY] copying FOLDER {} to {}", item_name, dest_folder_id, component="COPY")
                
                new_name = new_name.strip()
                copy_log("[COPY] calling api.copy_folder({}, {}, {})", item_id, dest_folder_id, new_name, component="COPY")
                
                new_id = self.api.copy_folder(item_id, dest_folder_id, new_name)
                copy_log("[COPY] copy_folder returned: {}", new_id, component="COPY")
                
                if new_id:
                    ok_count += 1
                    copy_log("[COPY] folder copy SUCCESS", component="COPY")
                else:
                    error_count += 1
                    copy_log("[COPY] folder copy FAILED - no ID returned", component="COPY")
            elif item_type == "file":
                copy_log("[COPY] copying FILE {} to {}", item_name, dest_folder_id, component="COPY")
                
                new_name = new_name.strip()
                copy_log("[COPY] calling api.copy_document({}, {}, {})", item_id, dest_folder_id, new_name, component="COPY")
                
                result = self.api.copy_document(item_id, dest_folder_id, new_name)
                copy_log("[COPY] copy_document returned: {}", result, component="COPY")
                
                if result:
                    ok_count += 1
                    copy_log("[COPY] file copy SUCCESS", component="COPY")
                else:
                    error_count += 1
                    copy_log("[COPY] file copy FAILED - False returned", component="COPY")
            else:
                copy_log("[COPY] UNKNOWN item type: {}", item_type, component="COPY")
                error_count += 1
        except Exception as e:
            copy_log("[COPY] ERROR copying item: {}", str(e), component="COPY")
            import traceback
            traceback.print_exc()
            error_count += 1
    
    copy_log("[COPY] _do_copy: FINAL - ok={}, error={}", ok_count, error_count, component="COPY")
    
    self._set_progress_visible(False)
    self.status.clearMessage()
    
    if error_count == 0:
        self.status.showMessage(f"Успешно скопировано: {msg} из {source_path} в {dest_path}", 4000)
    elif ok_count == 0:
        self.status.showMessage(f"Не удалось скопировать {msg} из {source_path}", 4000)
    else:
        self.status.showMessage(f"Успешно скопировано: {ok_count} из {n_items} (ошибок: {error_count}) из {source_path} в {dest_path}", 4000)
    
    # Refresh UI after copy (next tick to avoid re-entrancy)
    try:
        QTimer.singleShot(0, self.soft_refresh_and_restore_view)
    except Exception:
        try:
            self.soft_refresh_and_restore_view()
        except Exception:
            pass
    
    copy_log("[COPY] _do_copy: FINISHED - result: ok={}, error={}", ok_count, error_count, component="COPY")
    
    copy_log("[COPY] _do_copy: END", component="COPY")


def _do_move(self, items, result, project_id):
    """Actually perform move operation."""
    try:
        sync_log("[MOVE] _do_move: START", component="MOVE")
    except Exception:
        pass
    
    dest_folder_id = result.get("id")
    dest_path = result.get("path")
    source_path = result.get("source_path", "текущей папки")
    
    n_items = len(items)
    n_folders = sum(1 for it in items if it.get("type") == "folder")
    n_files = n_items - n_folders
    
    def _plural_form(n, forms):
        """Get correct plural form for Russian language."""
        n_mod10 = n % 10
        n_mod100 = n % 100
        if 10 < n_mod100 < 20:
            return forms[2]
        if n_mod10 == 1:
            return forms[0]
        if 2 <= n_mod10 <= 4:
            return forms[1]
        return forms[2]
    
    msg_parts = []
    if n_folders:
        folder_form = _plural_form(n_folders, ('папка', 'папки', 'папок'))
        msg_parts.append(f"{n_folders} {folder_form}")
    if n_files:
        file_form = _plural_form(n_files, ('файл', 'файла', 'файлов'))
        msg_parts.append(f"{n_files} {file_form}")
    msg = ", ".join(msg_parts)
    
    ok_count = 0
    error_count = 0

    from PySide6.QtWidgets import QApplication
    
    self._set_progress_visible(True)
    self.progress.setRange(0, n_items)
    self.progress.setValue(0)
    QApplication.processEvents()

    for i, item in enumerate(items):
        self.progress.setValue(i + 1)
        self.status.showMessage(f"Перемещение: {i+1} из {n_items} ({source_path} → {dest_path})")
        QApplication.processEvents()
        try:
            item_id = item.get("id")
            item_type = (item.get("type") or "").lower()
            item_name = item.get("name") or item.get("title") or "Без названия"

            if not item_id:
                error_count += 1
                continue

            if item_type in ("folder", "dir", "directory", "папка"):
                try:
                    if dest_folder_id and str(item_id) == str(dest_folder_id):
                        error_count += 1
                        continue
                except Exception:
                    pass
                if self.api.update_folder(item_id, project_id, item_name, dest_folder_id):
                    ok_count += 1
                else:
                    error_count += 1
            elif item_type in ("file", "document", "doc"):
                moved = False
                try:
                    moved = bool(self.api.move_document(item_id, dest_folder_id))
                except Exception:
                    moved = False
                if moved:
                    ok_count += 1
                else:
                    # Fallback: copy+delete (keeps UX working even if API update fails)
                    try:
                        sync_log("[MOVE] move_document failed; fallback copy+delete for id={} name={} -> {}", item_id, item_name, dest_folder_id, component="MOVE")
                    except Exception:
                        pass
                    try:
                        ok_copy = bool(self.api.copy_document(item_id, dest_folder_id, item_name))
                        ok_del = bool(self.api.delete_document(item_id)) if ok_copy else False
                        if ok_copy and ok_del:
                            ok_count += 1
                        else:
                            error_count += 1
                    except Exception:
                        error_count += 1
            else:
                error_count += 1
        except Exception as e:
            sync_log("[MOVE] ERROR moving item: {}", str(e), component="MOVE")
            import traceback
            traceback.print_exc()
            error_count += 1

    self._set_progress_visible(False)
    self.status.clearMessage()

    if error_count == 0:
        self.status.showMessage(f"Успешно перемещено: {msg} из {source_path} в {dest_path}", 4000)
    elif ok_count == 0:
        self.status.showMessage(f"Не удалось переместить {msg} из {source_path}", 4000)
    else:
        self.status.showMessage(f"Успешно перемещено: {ok_count} из {n_items} (ошибок: {error_count}) из {source_path} в {dest_path}", 4000)

    # Refresh UI after move (next tick to avoid re-entrancy)
    try:
        QTimer.singleShot(0, self.soft_refresh_and_restore_view)
    except Exception:
        try:
            self.soft_refresh_and_restore_view()
        except Exception:
            pass

    sync_log("[MOVE] _do_move: FINISHED - result: ok={}, error={}", ok_count, error_count, component="MOVE")

    # TEMP: Skip messagebox to prevent crash
    # if error_count == 0:
    #     QMessageBox.information(self, "Перемещение", f"Все {msg} успешно перемещены в \"{dest_path}\".")
    # elif ok_count == 0:
    #     QMessageBox.warning(self, "Перемещение", f"Не удалось переместить {msg}.")
    # else:
    #     QMessageBox.warning(self, "Перемещение", f"Успешно: {ok_count}, ошибок: {error_count}.")

    sync_log("[MOVE] _do_move: END", component="MOVE")


def _do_copy_folder(self, src_folder_id, dest_folder_id, new_name, dest_path):
    """Actually perform folder copy operation."""
    try:
        new_id = self.api.copy_folder(src_folder_id, dest_folder_id, new_name)
        if new_id:
            print(f"Папка \"{new_name}\" успешно скопирована в \"{dest_path}\".")
        else:
            print("Не удалось скопировать папку через API.")
    except Exception as e:
        print(f"Ошибка при копировании папки: {e}")


def _do_move_folder(self, folder_id, project_id, name, dest_folder_id, dest_path):
    """Actually perform folder move operation."""
    if self.api.update_folder(folder_id, project_id, name, dest_folder_id):
        print(f"Папка \"{name}\" успешно перемещена в \"{dest_path}\".")
    else:
        print("Не удалось переместить папку.")



def move_folder_action(self):
    """Move selected folder to another folder."""
    item = self.selected_item()
    if not item or item.get("type") != "folder":
        print("Выберите папку для перемещения.")
        return
    
    folder_id = item.get("id")
    name = item.get("name") or item.get("title") or "Без названия"
    project_id = self.current_project_id()
    
    result = self._prompt_folder_select("Выберите папку назначения для перемещения", can_select_current=False)
    if not result:
        return
    
    dest_folder_id = result.get("id")
    dest_path = result.get("path")
    
    if dest_folder_id == folder_id:
        print("Нельзя переместить папку в саму себя.")
        return
    
    # Use QTimer to delay execution
    QTimer.singleShot(500, lambda: self._do_move_folder(folder_id, project_id, name, dest_folder_id, dest_path))


def move_selected_action(self):
    """Move selected files/folders to another folder."""
    try:
        items = self.get_checked_visible_items()
    except Exception:
        items = []
    
    if not items:
        sel = self.selected_item()
        if sel:
            items = [sel]
    
    if not items:
        print("Выберите файлы или папки для перемещения.")
        return
    
    project_id = self.current_project_id()
    
    # Get source folder info before opening destination dialog
    source_folder_node = self.current_folder_node()
    source_path = None
    if source_folder_node:
        source_name = source_folder_node.get("name") or source_folder_node.get("title") or "Без названия"
        source_path = f"\"{source_name}\""
    
    result = self._prompt_folder_select("Выберите папку назначения для перемещения", can_select_current=True)
    if not result:
        return
    
    # Add source path to result
    result["source_path"] = source_path
    
    # Use QTimer to delay execution and let dialog fully close
    QTimer.singleShot(500, lambda: self._do_move(items, result, project_id))


def _prompt_folder_select(self, title: str, can_select_current: bool = False) -> dict:
    """Show dialog to select a folder from project tree.

    Args:
        title: Dialog title
        can_select_current: Whether user can select current folder

    Returns:
        dict with 'id' and 'path' of selected folder, or None if cancelled
    """
    dialog = QDialog(self)
    dialog.setWindowTitle(title)
    dialog.setMinimumWidth(500)
    dialog.setMinimumHeight(400)
    dialog.setAttribute(Qt.WA_DeleteOnClose, False)
    # Defensive: ensure closing this dialog can't quit the whole app
    try:
        dialog.setAttribute(Qt.WA_QuitOnClose, False)
    except Exception:
        pass

    layout = QVBoxLayout(dialog)
    
    # IMPORTANT: keep Python-owned Qt objects referenced for the whole dialog
    # lifetime. PySide6 can crash (process exit) if an eventFilter/style/delegate
    # python wrapper gets GC'ed while Qt still calls into it.
    tree = QTreeWidget(dialog)
    
    # Apply same styling as main tree widget
    tree.setObjectName("docsTree")
    tree.setMouseTracking(True)
    try:
        tree.setUniformRowHeights(True)
    except Exception:
        pass
    tree.setSelectionBehavior(QAbstractItemView.SelectRows)
    tree.setAllColumnsShowFocus(False)
    try:
        tree.setFocusPolicy(Qt.NoFocus)
    except Exception:
        pass
    tree.setAlternatingRowColors(False)
    tree.setRootIsDecorated(True)
    tree.setItemsExpandable(True)
    tree.setExpandsOnDoubleClick(True)
    
    # Apply TreeBranchProxyStyle for branch arrows
    try:
        tree._branch_style = TreeBranchProxyStyle(tree.style())
        tree.setStyle(tree._branch_style)
        if hasattr(tree, "viewport") and tree.viewport():
            tree.viewport().setStyle(tree._branch_style)
    except Exception:
        tree._branch_style = None
    
    # Apply MenuLikeTreeDelegate for row styling
    try:
        tree._row_delegate = MenuLikeTreeDelegate(tree)
        tree.setItemDelegate(tree._row_delegate)
    except Exception:
        tree._row_delegate = None

    # Hover/pressed tracking for MenuLikeTreeDelegate
    tree._hover_index = QModelIndex()
    tree._pressed_index = QModelIndex()
    try:
        if tree.viewport():
            tree.viewport().setAttribute(Qt.WA_Hover, True)
            tree.viewport().setMouseTracking(True)
    except Exception:
        pass

    class _DialogTreeHoverFilter(QObject):
        def __init__(self, w: QTreeWidget):
            super().__init__(w)
            self._w = w

        def eventFilter(self, obj, ev):
            try:
                if obj is not self._w.viewport():
                    return False
                t = ev.type()
                if t in (QEvent.MouseMove, QEvent.HoverMove):
                    idx = self._w.indexAt(ev.pos())
                    if idx != getattr(self._w, "_hover_index", QModelIndex()):
                        self._w._hover_index = idx
                        self._w.viewport().update()
                elif t in (QEvent.Leave, QEvent.HoverLeave):
                    self._w._hover_index = QModelIndex()
                    self._w._pressed_index = QModelIndex()
                    self._w.viewport().update()
                elif t == QEvent.MouseButtonPress:
                    self._w._pressed_index = self._w.indexAt(ev.pos())
                    self._w.viewport().update()
                elif t == QEvent.MouseButtonRelease:
                    self._w._pressed_index = QModelIndex()
                    self._w.viewport().update()
            except Exception:
                return False
            return False

    try:
        if tree.viewport():
            tree._hover_filter = _DialogTreeHoverFilter(tree)
            tree.viewport().installEventFilter(tree._hover_filter)
    except Exception:
        tree._hover_filter = None
    
    tree.setHeaderLabels(["Папки"])
    
    current_node = self.current_folder_node()
    current_folder_id = current_node.get("id") if current_node else None
    
    project_id = self.current_project_id()
    # Prefer already-built hierarchical tree from MainWindow if available
    folders = getattr(self, "full_tree", None)
    if not isinstance(folders, list) or not folders:
        folders = self.api.list_folders(project_id, force=True)
    
    root_item = QTreeWidgetItem(tree)
    root_item.setText(0, "Корень")
    root_item.setData(0, Qt.UserRole, 0)
    
    if current_folder_id is None or can_select_current:
        root_item.setFlags(root_item.flags() | Qt.ItemIsSelectable)
    else:
        root_item.setFlags(root_item.flags() & ~Qt.ItemIsSelectable)
        root_item.setForeground(0, QColor("#808080"))
    
    _populate_folder_tree_from_nodes(tree, root_item, folders, current_folder_id, can_select_current)
    root_item.setExpanded(True)
    
    layout.addWidget(tree)
    
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    
    result = dialog.exec()
    
    if result != QDialog.Accepted:
        return None
    
    selected = tree.currentItem()
    if not selected:
        return None
    
    folder_id = selected.data(0, Qt.UserRole)
    # Allow selecting root (0)
    if folder_id is None:
        return None
    
    path_parts = []
    item = selected
    while item:
        text = item.text(0)
        if text != "Корень":  # Skip root in path
            path_parts.insert(0, text)
        item = item.parent()
    
    return {"id": folder_id, "path": "/".join(path_parts) if path_parts else ""}
 

def _populate_folder_tree_from_nodes(tree: QTreeWidget, parent_item: QTreeWidgetItem, nodes: list, exclude_id=None, can_select_current=False):
    """Populate tree widget from hierarchical nodes (with `children`)."""
    if not isinstance(nodes, list):
        return

    for n in nodes:
        if not isinstance(n, dict) or n.get("type") != "folder":
            continue

        fid = n.get("id")
        item = QTreeWidgetItem(parent_item)
        item.setText(0, n.get("name") or n.get("title") or "Без названия")
        item.setData(0, Qt.UserRole, fid)

        if fid == exclude_id and not can_select_current:
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            item.setForeground(0, QColor("#808080"))

        children = n.get("children") or []
        if isinstance(children, list) and children:
            _populate_folder_tree_from_nodes(tree, item, children, exclude_id, can_select_current)


def _populate_folder_tree_from_list(tree: QTreeWidget, parent_item: QTreeWidgetItem, nodes: list, exclude_id=None, can_select_current=False):
    """Populate tree widget from flat list of nodes (compatibility wrapper).
    
    This is a compatibility wrapper that converts flat list to nodes format
    and calls _populate_folder_tree_from_nodes.
    """
    if not isinstance(nodes, list):
        return
    
    for n in nodes:
        if not isinstance(n, dict) or n.get("type") != "folder":
            continue
        
        fid = n.get("id")
        item = QTreeWidgetItem(parent_item)
        item.setText(0, n.get("name") or n.get("title") or "Без названия")
        item.setData(0, Qt.UserRole, fid)
        
        if fid == exclude_id and not can_select_current:
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            item.setForeground(0, QColor("#808080"))
        
        children = n.get("children") or []
        if isinstance(children, list) and children:
            _populate_folder_tree_from_nodes(tree, item, children, exclude_id, can_select_current)




def inject_folder_actions_to_main_window(MainWindowClass):
    """Inject folder copy/move actions into MainWindow class."""
    MainWindowClass._generate_unique_name = _generate_unique_name
    MainWindowClass.copy_folder_action = copy_folder_action
    MainWindowClass.copy_selected_action = copy_selected_action
    MainWindowClass._do_copy = _do_copy
    MainWindowClass._do_copy_folder = _do_copy_folder
    MainWindowClass.move_folder_action = move_folder_action
    MainWindowClass.move_selected_action = move_selected_action
    MainWindowClass._do_move = _do_move
    MainWindowClass._do_move_folder = _do_move_folder
    MainWindowClass._prompt_folder_select = _prompt_folder_select
    MainWindowClass._populate_folder_tree_from_list = _populate_folder_tree_from_list
