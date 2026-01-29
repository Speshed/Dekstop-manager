# -*- coding: utf-8 -*-
"""File and folder operations for Larix Nexus."""

from PySide6.QtCore import Qt, QModelIndex
from PySide6.QtWidgets import QMessageBox, QInputDialog
from .dialogs import FileDetailsDialog, FolderDetailsDialog
from .helpers import open_in_os
from ..utils.helpers import normalize_id


def selected_item(self) -> dict:
    """Get currently selected item."""
    sel = self.table.selectionModel().selectedRows()
    if not sel:
        return {}
    row = self.proxy.mapToSource(sel[0]).row()
    return self.files_model.item_at(row)


def on_table_double_clicked(self, index: QModelIndex):
    """Handle table double click."""
    if index.column() == 0:
        return
    if not index.isValid():
        return
    
    item = self.selected_item()
    if not item:
        return
    
    if item.get("type") == "folder":
        fid = item.get("id")
        if fid in self.folder_item_by_id:
            self.tree.setCurrentItem(self.folder_item_by_id[fid])
        self.open_folder_node(item)
        return
    
    # Open file
    _prev = getattr(self, "_force_mode", None)
    self._force_mode = "A"
    try:
        local_path = self.ensure_downloaded(item)
    finally:
        self._force_mode = _prev
    
    if not local_path:
        QMessageBox.warning(self, "Открытие", "Не удалось скачать файл для открытия.")
        return
    
    if not open_in_os(local_path):
        QMessageBox.warning(self, "Открытие", "ОС не смогла открыть файл. Сохраните его и откройте вручную.")


def open_selected_item(self):
    """Open selected item."""
    item = self.selected_item()
    if not item:
        return
    
    if item.get("type") == "folder":
        fid = item.get("id")
        try:
            if fid in self.folder_item_by_id:
                self.tree.setCurrentItem(self.folder_item_by_id[fid])
        except Exception:
            pass
        self.open_folder_node(item)
        return
    
    # Open file
    _prev = getattr(self, "_force_mode", None)
    self._force_mode = "A"
    try:
        local_path = self.ensure_downloaded(item)
    finally:
        self._force_mode = _prev
    
    if not local_path:
        QMessageBox.warning(self, "Открытие", "Не удалось скачать файл для открытия.")
        return
    
    if not open_in_os(local_path):
        QMessageBox.warning(self, "Открытие", "ОС не смогла открыть файл. Сохраните его и откройте вручную.")


def rename_selected_action(self):
    """Rename selected item."""
    item = self.selected_item()
    if not item:
        QMessageBox.information(self, "Переименование", "Выберите элемент.")
        return
    
    old_name = item.get("name") or item.get("title") or ""
    item_type = item.get("type", "")
    item_id = item.get("id")
    
    if not item_id:
        return
    
    new_name, ok = QInputDialog.getText(self, "Переименование", "Новое имя:", text=old_name)
    if not ok or not new_name.strip():
        return
    
    new_name = new_name.strip()
    
    try:
        if item_type == "folder":
            success = self.api.rename_folder(item_id, new_name)
        else:
            success = self.api.rename_file(item_id, new_name)
        
        if success:
            self.soft_refresh_and_restore_view()
        else:
            QMessageBox.warning(self, "Переименование", "Не удалось переименовать.")
    except Exception as e:
        QMessageBox.warning(self, "Переименование", f"Ошибка: {e}")


def delete_checked(self):
    """Delete checked items."""
    items = self.get_checked_visible_items()
    if not items:
        items = self.get_selected_items()
    if not items:
        QMessageBox.information(self, "Удаление", "Выберите элементы для удаления.")
        return
    
    reply = QMessageBox.question(
        self,
        "Удаление",
        f"Удалить {len(items)} элементов?",
        QMessageBox.Yes | QMessageBox.No
    )
    
    if reply != QMessageBox.Yes:
        return
    
    success = 0
    failed = 0
    error_messages = []
    
    for item in items:
        item_type = item.get("type", "")
        item_id = item.get("id")
        item_name = item.get("name", item.get("originalName", "Элемент"))
        
        if not item_id:
            error_messages.append(f"ID не указан для элемента '{item_name}'")
            failed += 1
            continue
        
        try:
            if item_type == "folder":
                if self.api.delete_folder(item_id):
                    success += 1
                else:
                    error_messages.append(f"Не удалось удалить папку '{item_name}'")
                    failed += 1
            else:
                if self.api.delete_document(item_id):
                    success += 1
                else:
                    error_messages.append(f"Не удалось удалить файл '{item_name}'")
                    failed += 1
        except Exception as e:
            error_messages.append(f"Ошибка при удалении '{item_name}': {e}")
            failed += 1
    
    self.soft_refresh_and_restore_view()
    
    if failed > 0:
        msg = f"Удалено: {success}, Ошибок: {failed}"
        if error_messages:
            msg += "\n\nДетали:\n" + "\n".join(error_messages[:10])
            if len(error_messages) > 10:
                msg += f"\n...и ещё {len(error_messages) - 10}"
        QMessageBox.warning(self, "Удаление", msg)
    else:
        QMessageBox.information(self, "Удаление", f"Удалено {success} элементов.")


def show_details_for_selected(self):
    """Show details for selected item."""
    item = self.selected_item()
    if not item:
        return
    
    item_type = item.get("type", "")
    
    if item_type == "folder":
        self.show_folder_details(item)
    else:
        dlg = FileDetailsDialog(item, self)
        dlg.exec()


def show_folder_details(self, folder_obj: dict):
    """Show folder details dialog."""
    fid = folder_obj.get("id")
    if not fid:
        QMessageBox.information(self, "Свойства папки", "ID папки не определен.")
        return
    
    try:
        self.status.showMessage("Загрузка информации о папке")
        details = self.api.get_folder_details(fid)
        self.status.clearMessage()
    except Exception as e:
        self.status.clearMessage()
        QMessageBox.warning(self, "Свойства папки", f"Не удалось получить информацию: {e}")
        return
    
    if not details:
        QMessageBox.warning(self, "Свойства папки", "Не удалось получить информацию о папке.")
        return
    
    dlg = FolderDetailsDialog(details, self)
    dlg.exec()


def _safe_copy_selected_action(self):
    """Safely execute copy_selected_action."""
    try:
        self.copy_selected_action()
    except Exception as e:
        print(f"Error in copy_selected_action: {e}")


def _is_root_open(self) -> bool:
    """Check if root folder is currently open."""
    current_item = self.tree.currentItem()
    if not current_item:
        return True  # No selection = root
    
    node = current_item.data(0, Qt.UserRole)
    if not isinstance(node, dict):
        return True
    
    fid = node.get("id")
    project_id = self.current_project_id()
    
    return normalize_id(fid) == normalize_id(project_id)


def inject_file_ops_to_main_window(MainWindowClass):
    """Inject file operations into MainWindow class."""
    MainWindowClass.selected_item = selected_item
    MainWindowClass.on_table_double_clicked = on_table_double_clicked
    MainWindowClass.open_selected_item = open_selected_item
    MainWindowClass.rename_selected_action = rename_selected_action
    MainWindowClass.delete_checked = delete_checked
    MainWindowClass.show_details_for_selected = show_details_for_selected
    MainWindowClass.show_folder_details = show_folder_details
    MainWindowClass._safe_copy_selected_action = _safe_copy_selected_action
    MainWindowClass._is_root_open = _is_root_open
