# -*- coding: utf-8 -*-
"""File and folder operations for Larix Nexus."""

from PySide6.QtCore import Qt, QModelIndex
from PySide6.QtWidgets import QMessageBox, QInputDialog, QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QHBoxLayout
from PySide6.QtGui import QPixmap
from .dialogs import FileDetailsDialog, FolderDetailsDialog
from .helpers import open_in_os
from ..utils.helpers import normalize_id
from ..utils.theme import WARNING_ICON_PATH


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
        try:
            self.status.showMessage("Удаление: выберите элементы.", 5000)
        except Exception:
            pass
        return

    # Copy items to local variable
    items_to_delete = list(items)

    count = len(items_to_delete)
    if count == 1:
        element_text = "1 элемент"
    elif 2 <= count <= 4:
        element_text = f"{count} элемента"
    else:
        element_text = f"{count} элементов"

    # Try to use safe dialogs module
    try:
        from larix_nexus.utils.safe_dialogs import show_confirmation
        from larix_nexus.utils.ui_trace import trace as ui_trace

        ui_trace("file_ops.delete_checked: showing safe confirmation items={}", count)

        def on_result(confirmed: bool):
            if ui_trace:
                ui_trace("file_ops.delete_checked: user confirmed={}", confirmed)

            if confirmed:
                _perform_delete_direct(self, items_to_delete)

        show_confirmation(
            self,
            "Удаление",
            f"Удалить {element_text}?",
            yes_text="Удалить",
            no_text="Отмена",
            on_result=on_result
        )
        return  # Dialog is non-blocking, return immediately

    except Exception as e:
        # Fallback: use simple QWidget dialog (no QMessageBox!)
        try:
            from larix_nexus.utils.ui_trace import trace as ui_trace
            ui_trace("file_ops.delete_checked: safe_dialogs failed, using QWidget fallback: {}", str(e))
        except Exception:
            ui_trace = None

        try:
            from PySide6.QtWidgets import QWidget, QLabel, QHBoxLayout, QPushButton, QVBoxLayout
            from PySide6.QtCore import Qt

            dlg = QWidget(self, Qt.WindowType.Dialog)
            dlg.setWindowTitle("Удаление")
            dlg.setMinimumWidth(360)
            dlg.setWindowModality(Qt.WindowModality.ApplicationModal)

            layout = QVBoxLayout(dlg)
            label = QLabel(f"Удалить {element_text}?")
            layout.addWidget(label)

            btn_layout = QHBoxLayout()
            btn_layout.addStretch()

            yes_btn = QPushButton("Удалить")
            no_btn = QPushButton("Отмена")

            result = [False]  # Use list to capture in nested scope

            def on_yes():
                result[0] = True
                dlg.close()

            def on_no():
                result[0] = False
                dlg.close()

            yes_btn.clicked.connect(on_yes)
            no_btn.clicked.connect(on_no)

            btn_layout.addWidget(no_btn)
            btn_layout.addWidget(yes_btn)
            layout.addLayout(btn_layout)

            dlg.show()

            # Wait for dialog to close (simple blocking loop)
            while dlg.isVisible():
                from PySide6.QtWidgets import QApplication
                QApplication.processEvents()

            if result[0]:
                _perform_delete_direct(self, items_to_delete)

            dlg.deleteLater()
            return

        except Exception as e2:
            # Last resort: just delete without confirmation
            if ui_trace:
                ui_trace("file_ops.delete_checked: QWidget dialog failed too, deleting directly: {}", str(e2))
            _perform_delete_direct(self, items_to_delete)


def _perform_delete_direct(self, items_to_delete):
    """Direct deletion without dialog."""
    try:
        from larix_nexus.utils.ui_trace import trace as ui_trace
    except Exception:
        ui_trace = None

    try:
        success = 0
        failed = 0
        error_messages = []

        for item in (items_to_delete or []):
            item_type = item.get("type", "")
            item_id = item.get("id")
            item_name = item.get("name", item.get("originalName", "Элемент"))

            if not item_id:
                error_messages.append(f"ID не указан для элемента '{item_name}'")
                failed += 1
                continue

            try:
                if item_type == "folder":
                    if ui_trace:
                        ui_trace("file_ops.delete: delete folder id={} name={}", item_id, item_name)
                    if self.api.delete_folder(item_id):
                        success += 1
                    else:
                        error_messages.append(f"Не удалось удалить папку '{item_name}'")
                        failed += 1
                else:
                    if ui_trace:
                        ui_trace("file_ops.delete: delete document id={} name={}", item_id, item_name)
                    if self.api.delete_document(item_id):
                        success += 1
                    else:
                        error_messages.append(f"Не удалось удалить файл '{item_name}'")
                        failed += 1
            except Exception as e:
                error_messages.append(f"Ошибка при удалении '{item_name}': {e}")
                failed += 1

        # Refresh UI
        try:
            self.soft_refresh_and_restore_view()
        except Exception as e:
            if ui_trace:
                ui_trace("file_ops.delete: error in refresh: {}", str(e))

        # Show result in status bar
        try:
            if failed:
                self.status.showMessage(f"Удаление: удалено {success}, ошибок {failed}.", 12000)
            else:
                self.status.showMessage(f"Удаление: удалено {success}.", 6000)
        except Exception as e:
            if ui_trace:
                ui_trace("file_ops.delete: error updating status: {}", str(e))
    except Exception as e:
        if ui_trace:
            ui_trace("file_ops.delete: unexpected error: {}", str(e))


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
    
    node = current_item.data(0, int(Qt.ItemDataRole.UserRole))
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
