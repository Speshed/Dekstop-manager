# -*- coding: utf-8 -*-
"""Folder copy/move actions for Larix Nexus."""

import os
from PySide6.QtCore import Qt, QObject, QEvent, QModelIndex, Signal, QThread
from PySide6 import QtCore
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QInputDialog, QDialog, QVBoxLayout, QDialogButtonBox, QTreeWidget, QTreeWidgetItem, QMessageBox, QAbstractItemView, QPushButton
from PySide6.QtCore import QTimer
from .delegates import MenuLikeTreeDelegate
from ..utils.logging import sync_log
from ..utils.copy_logger import copy_log
from ..utils.i18n import t


def _current_file_name(item: dict) -> str:
    """Return the актуальное имя файла для операций (rename/move/copy).

    Prefer current fields; use originalName only as fallback.
    """
    if not isinstance(item, dict):
        return ""
    return (
        item.get("name")
        or item.get("fileName")
        or item.get("originalName")
        or ""
    )


def _format_move_conflict_names(names: list[str]) -> str:
    """Format a short user-facing list of conflicting file names."""
    visible = [name for name in names if name][:5]
    if not visible:
        return ""
    if len(names) > len(visible):
        return ", ".join(visible) + t("move.conflict_more_suffix", count=len(names) - len(visible))
    return ", ".join(visible)


class _CopyWorker(QObject):
    """Background worker for copy operation."""
    sig_started = Signal()
    sig_progress = Signal(int, int, str)  # current, total, message
    sig_finished = Signal(int, int, str, str)  # ok_count, error_count, source_path, dest_path
    sig_error = Signal(str)
    
    def __init__(self, api, items, dest_folder_id, dest_path, source_path, dest_files_set):
        super().__init__()
        self._api = api
        self._items = items
        self._dest_folder_id = dest_folder_id
        self._dest_path = dest_path
        self._source_path = source_path
        self._dest_files = dest_files_set
        self._cancelled = False
    
    @QtCore.Slot()
    def cancel(self):
        """Cancel the copy operation."""
        self._cancelled = True
    
    @QtCore.Slot()
    def run(self):
        """Execute copy operation in background thread."""
        copy_log("[COPY] Worker.run() STARTED", component="COPY")
        self.sig_started.emit()
        copy_log("[COPY] sig_started emitted", component="COPY")

        n_items = len(self._items)
        copy_log("[COPY] Total items to copy: {}", n_items, component="COPY")
        ok_count = 0
        error_count = 0
        
        for i, item in enumerate(self._items):
            if self._cancelled:
                copy_log("[COPY] Operation cancelled by user", component="COPY")
                break
            
            try:
                item_id = item.get("id")
                item_type = item.get("type")
                if (item_type or "").lower() == "file":
                    item_name = _current_file_name(item) or item.get("title") or t("common.no_name")
                else:
                    item_name = item.get("name") or item.get("title") or t("common.no_name")
                
                copy_log("[COPY] item: id={}, type={}, name={}", item_id, item_type, item_name, component="COPY")
                
                # Generate unique name based on existing files in destination
                new_name = _generate_unique_name(self._dest_files, item_name)
                while new_name.casefold() in self._dest_files:
                    new_name = _generate_unique_name(self._dest_files, new_name)
                copy_log("[COPY] using name: {} for destination {}", new_name, self._dest_folder_id, component="COPY")
                
                # Add the new name to the set to avoid conflicts for subsequent items
                self._dest_files.add(new_name.casefold())
                
                msg = t("status.copy_progress", current=i+1, total=n_items, src=self._source_path, dst=self._dest_path)
                self.sig_progress.emit(i + 1, n_items, msg)
                
                if item_type == "folder":
                    copy_log("[COPY] copying FOLDER {} to {}", item_name, self._dest_folder_id, component="COPY")
                    
                    new_name = new_name.strip()
                    new_id = self._api.copy_folder(item_id, self._dest_folder_id, new_name)
                    copy_log("[COPY] copy_folder returned: {}", new_id, component="COPY")
                    
                    if new_id:
                        ok_count += 1
                        copy_log("[COPY] folder copy SUCCESS", component="COPY")
                    else:
                        error_count += 1
                        copy_log("[COPY] folder copy FAILED - no ID returned", component="COPY")
                elif item_type == "file":
                    copy_log("[COPY] copying FILE {} to {}", item_name, self._dest_folder_id, component="COPY")
                    
                    new_name = new_name.strip()
                    item_document_type = (
                        item.get("documentTypeId")
                        or item.get("document_type_id")
                        or item.get("documentType")
                        or item.get("document_type")
                    )
                    result = self._api.copy_document(item_id, self._dest_folder_id, new_name, item_document_type)
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
        
        copy_log("[COPY] _CopyWorker: FINAL - ok={}, error={}", ok_count, error_count, component="COPY")
        self.sig_finished.emit(ok_count, error_count, self._source_path, self._dest_path)


class _MoveWorker(QObject):
    """Background worker for move operation."""
    sig_started = Signal()
    sig_progress = Signal(int, int, str)  # current, total, message
    sig_finished = Signal(int, int, str, str)  # ok_count, error_count, source_path, dest_path
    sig_error = Signal(str)
    
    def __init__(self, api, items, dest_folder_id, dest_path, source_path, project_id):
        super().__init__()
        self._api = api
        self._items = items
        self._dest_folder_id = dest_folder_id
        self._dest_path = dest_path
        self._source_path = source_path
        self._project_id = project_id
        self._cancelled = False
    
    @QtCore.Slot()
    def cancel(self):
        """Cancel the move operation."""
        self._cancelled = True
    
    @QtCore.Slot()
    def run(self):
        """Execute move operation in background thread."""
        self.sig_started.emit()

        # Preload destination filenames for conflict check (files only).
        dest_names_cf: set[str] | None = None
        if self._dest_folder_id not in (None, ""):
            try:
                docs = self._api.list_documents_in_folder(self._dest_folder_id, force=True) or []
                if getattr(self._api, "_last_list_documents_error", None):
                    raise RuntimeError(str(getattr(self._api, "_last_list_documents_error", None)))
                dest_names_cf = {
                    _current_file_name(d).casefold()
                    for d in docs
                    if isinstance(d, dict) and _current_file_name(d)
                }
            except Exception:
                dest_names_cf = None
        
        n_items = len(self._items)
        ok_count = 0
        error_count = 0
        
        for i, item in enumerate(self._items):
            if self._cancelled:
                sync_log("[MOVE] Operation cancelled by user", component="MOVE")
                break
            
            try:
                item_id = item.get("id")
                item_type = (item.get("type") or "").lower()
                item_name = item.get("name") or item.get("title") or t("common.no_name")
                
                msg = t("status.move_progress", current=i+1, total=n_items, src=self._source_path, dst=self._dest_path)
                self.sig_progress.emit(i + 1, n_items, msg)
                
                if not item_id:
                    error_count += 1
                    continue
                
                if item_type in ("folder", "dir", "directory", "папка"):
                    try:
                        if self._dest_folder_id and str(item_id) == str(self._dest_folder_id):
                            error_count += 1
                            continue
                    except Exception:
                        pass
                    if self._api.update_folder(item_id, self._project_id, item_name, self._dest_folder_id):
                        ok_count += 1
                    else:
                        error_count += 1
                elif item_type in ("file", "document", "doc"):
                    moved = False
                    # Block move if destination already contains a file with the same актуальное имя.
                    cur_name = _current_file_name(item) or (item.get("title") or "")
                    if dest_names_cf is not None and cur_name and cur_name.casefold() in dest_names_cf:
                        error_count += 1
                        try:
                            self.sig_progress.emit(
                                i + 1,
                                n_items,
                                t("status.move_conflict_exists_single", name=cur_name)
                            )
                        except Exception:
                            pass
                        continue
                    try:
                        sync_log("[MOVE] Attempting move_document for id={} -> {}", item_id, self._dest_folder_id, component="MOVE")
                        moved = bool(self._api.move_document(item_id, self._dest_folder_id))
                        sync_log("[MOVE] move_document returned: {} for id={}", moved, item_id, component="MOVE")
                    except Exception as e:
                        sync_log("[MOVE] move_document exception for id={}: {}", item_id, str(e), component="MOVE")
                        import traceback
                        sync_log("[MOVE] Traceback: {}", traceback.format_exc(), component="MOVE")
                        moved = False
                    
                    if moved:
                        sync_log("[MOVE] Move SUCCESS for id={}, incrementing ok_count", item_id, component="MOVE")
                        ok_count += 1
                        try:
                            if dest_names_cf is not None and cur_name:
                                dest_names_cf.add(cur_name.casefold())
                        except Exception:
                            pass
                    else:
                        # Fallback copy+delete is unsafe for files (can create a new version on name conflicts).
                        sync_log("[MOVE] Move FAILED for id={}, not using fallback copy+delete", item_id, component="MOVE")
                        error_count += 1
                else:
                    error_count += 1
            except Exception as e:
                sync_log("[MOVE] ERROR moving item: {}", str(e), component="MOVE")
                import traceback
                traceback.print_exc()
                error_count += 1
        
        sync_log("[MOVE] _MoveWorker: FINAL - ok={}, error={}", ok_count, error_count, component="MOVE")
        self.sig_finished.emit(ok_count, error_count, self._source_path, self._dest_path)


def _generate_unique_name(existing_names: set[str], name: str) -> str:
    """Generate unique name (file.txt -> file_копия.txt) if name is taken.
    
    Args:
        existing_names: Set of existing filenames in destination folder
        name: Original filename
    
    Returns:
        Unique filename with suffix if needed
    """
    copy_suffix = t("copy.suffix")
    base, ext = os.path.splitext(name)
    base = (base or "").strip()
    if not base:
        base = name.strip()
        ext = ""
    if not base:
        base = "file"
    
    name_lower = name.casefold()
    existing_lower = {n.casefold() for n in existing_names}
    
    if name_lower not in existing_lower:
        return name
    
    candidate = f"{base}{copy_suffix}{ext}"
    idx = 2
    while candidate.lower() in existing_lower:
        candidate = f"{base}{copy_suffix}{idx}{ext}"
        idx += 1
    return candidate


def copy_folder_action(self):
    """Copy selected folder to another folder."""
    item = self.selected_item()
    if not item or item.get("type") != "folder":
        print(t("folder.select_folder_copy"))
        return
    
    src_folder_id = item.get("id")
    src_name = item.get("name") or item.get("title") or "Без названия"
    
    result = self._prompt_folder_select(t("folder.select_destination_copy"), can_select_current=False)
    if not result:
        return
    
    dest_folder_id = result.get("id")
    dest_path = result.get("path")
    
    if dest_folder_id == src_folder_id:
        print(t("folder.cannot_copy_to_self"))
        return
    
    new_name = f"{src_name}{t('copy.suffix')}"
    
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
        print(t("folder.select_items_copy"))
        return
    
    project_id = self.current_project_id()
    copy_log("[COPY] copy_selected_action: project_id = {}", project_id, component="COPY")
    if not project_id:
        copy_log("[COPY] copy_selected_action: NO PROJECT - no action", component="COPY")
        print(t("project.not_selected"))
        return
    
    # Get source folder info before opening destination dialog
    source_folder_node = self.current_folder_node()
    source_path = None
    if source_folder_node:
        source_name = source_folder_node.get("name") or source_folder_node.get("title") or "Без названия"
        source_path = f"\"{source_name}\""
    
    result = self._prompt_folder_select(t("folder.select_destination_copy"), can_select_current=True)
    copy_log("[COPY] copy_selected_action: folder select result = {}", str(result), component="COPY")
    if not result:
        copy_log("[COPY] copy_selected_action: CANCELLED - no folder selected", component="COPY")
        return
    
    # Add source path to result
    result["source_path"] = source_path
    
    # Use QTimer to delay execution and let dialog fully close
    QTimer.singleShot(500, lambda: self._do_copy(items, result))


def _do_copy(self, items, result):
    """Start copy operation in background thread."""
    try:
        copy_log("[COPY] _do_copy: START", component="COPY")
    except Exception:
        pass
    
    dest_folder_id = result.get("id")
    if dest_folder_id in (0, "0"):
        dest_folder_id = self.current_project_id()
    dest_path = result.get("path")
    source_path = result.get("source_path", "текущей папки")
    copy_log("[COPY] _do_copy: source_path={}, dest_folder_id = {}, dest_path = {}", source_path, dest_folder_id, dest_path, component="COPY")
    
    # Get files in destination folder to check for duplicates
    dest_files = set()
    try:
        dest_files = self._existing_names_for_folder(dest_folder_id)
        existing_names_error = getattr(self, "_last_existing_names_error", None)
        if existing_names_error:
            raise RuntimeError(str(existing_names_error))
        copy_log("[COPY] destination folder has {} files: {}", len(dest_files), list(dest_files), component="COPY")
    except Exception as e:
        copy_log("[COPY] ERROR getting destination folder list for folder {}: {}", dest_folder_id, str(e), component="COPY")
        warning_text = t("copy.cannot_verify_destination_conflicts")
        QMessageBox.warning(self, t("copy.conflict_warning_title"), warning_text)
        self.status.showMessage(warning_text, 6000)
        return
    
    # Build message string for final status
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
    copy_log("[COPY] _do_copy: msg = {}", msg, component="COPY")
    
    # Create background thread and worker
    try:
        th = QThread(self)
        worker = _CopyWorker(self.api, items, dest_folder_id, dest_path, source_path, dest_files)
        worker.moveToThread(th)
        
        # Keep references
        try:
            self._copy_threads.add(th)
        except Exception:
            self._copy_threads = {th}
        self._copy_thread = th
        self._copy_worker = worker
        
        # Show progress bar
        self._set_progress_visible(True)
        self.progress.setRange(0, n_items)
        self.progress.setValue(0)
        
        # Create cancel button (no parent to avoid cross-thread issues)
        try:
            btn_cancel = QPushButton(t("common.cancel"))
            btn_cancel.setObjectName("copyCancelBtn")
            btn_cancel.setProperty("secondary", True)
            self.status.addPermanentWidget(btn_cancel)
            self._copy_cancel_btn = btn_cancel
            btn_cancel.clicked.connect(worker.cancel)
        except Exception as e:
            copy_log("[COPY] ERROR creating cancel button: {}", str(e), component="COPY")
        
        # Connect signals - FORCE QueuedConnection for all worker signals to ensure GUI thread
        th.started.connect(worker.run)
        worker.sig_started.connect(lambda: copy_log("[COPY] Worker started", component="COPY"), QtCore.Qt.QueuedConnection)
        worker.sig_progress.connect(self._on_copy_progress, QtCore.Qt.QueuedConnection)
        worker.sig_finished.connect(self._on_copy_finished, QtCore.Qt.QueuedConnection)
        worker.sig_error.connect(lambda e: copy_log("[COPY] Error: {}", str(e), component="COPY"), QtCore.Qt.QueuedConnection)

        # Cleanup when finished - use QueuedConnection to ensure GUI thread
        worker.sig_finished.connect(
            lambda ok, err, src, dst: self._cleanup_copy_thread(th, worker, msg, ok, err, src, dst),
            QtCore.Qt.QueuedConnection
        )
        
        # Start thread
        th.start()
        copy_log("[COPY] Thread started", component="COPY")
    except Exception as e:
        copy_log("[COPY] ERROR starting thread: {}", str(e), component="COPY")
        import traceback
        traceback.print_exc()
        self._set_progress_visible(False)
        self.status.showMessage(t("status.copy_start_failed", error=str(e)), 5000)


def _on_copy_progress(self, current: int, total: int, message: str):
    """Handle progress update from copy worker. MUST run in GUI thread."""
    gui_thread = QtCore.QCoreApplication.instance().thread() if QtCore.QCoreApplication.instance() else None
    if gui_thread and QtCore.QThread.currentThread() is not gui_thread:
        copy_log("[COPY] ERROR: _on_copy_progress called from worker thread, deferring", component="COPY")
        QTimer.singleShot(0, self, lambda: self._on_copy_progress(current, total, message))
        return
    self.progress.setValue(current)
    self.status.showMessage(message)


def _on_copy_finished(self, ok_count: int, error_count: int, source_path: str, dest_path: str):
    """Handle copy completion."""
    # Will be called from cleanup function
    pass


def _cleanup_copy_thread(self, th: QThread, worker: QObject, msg: str, ok_count: int, error_count: int, source_path: str, dest_path: str):
    """Clean up copy thread and show final status. MUST run in GUI thread."""
    copy_log("[COPY] _cleanup_copy_thread STARTED - ok={}, error={}", ok_count, error_count, component="COPY")

    gui_thread = QtCore.QCoreApplication.instance().thread() if QtCore.QCoreApplication.instance() else None
    if gui_thread and QtCore.QThread.currentThread() is not gui_thread:
        copy_log("[COPY] ERROR: _cleanup_copy_thread called from worker thread, deferring", component="COPY")
        QTimer.singleShot(0, self, lambda: self._cleanup_copy_thread(th, worker, msg, ok_count, error_count, source_path, dest_path))
        return

    copy_log("[COPY] _cleanup_copy_thread in GUI thread, proceeding with cleanup", component="COPY")

    # Clean up cancel button
    try:
        btn = getattr(self, "_copy_cancel_btn", None)
        if btn:
            btn.hide()
            btn.setEnabled(False)
            btn.clicked.disconnect()
            self.status.removeWidget(btn)
            btn.deleteLater()
    except Exception as e:
        copy_log("[COPY] ERROR removing cancel button: {}", str(e), component="COPY")
    self._copy_cancel_btn = None
    try:
        self.status.update()
        self.status.repaint()
    except Exception:
        pass
    
    # Clean up thread
    try:
        if isinstance(th, QThread):
            try:
                if QtCore.QThread.currentThread() is not th:
                    th.quit()
                    th.wait(1500)
                else:
                    th.quit()
            except Exception:
                pass
            try:
                th.deleteLater()
            except Exception:
                pass
    except Exception:
        pass
    
    # Clean up references
    try:
        if hasattr(self, "_copy_threads") and isinstance(self._copy_threads, set):
            self._copy_threads.discard(th)
    except Exception:
        pass
    self._copy_thread = None
    self._copy_worker = None
    
    # Hide progress bar
    self._set_progress_visible(False)
    
    # Show final message
    if error_count == 0:
        self.status.showMessage(t("status.copy_result_success", items=msg, src=source_path, dst=dest_path), 4000)
    elif ok_count == 0:
        self.status.showMessage(t("status.copy_result_failed", items=msg, src=source_path), 4000)
    else:
        self.status.showMessage(t("status.copy_result_partial", ok=ok_count, errors=error_count, src=source_path, dst=dest_path), 4000)
    
    # Refresh UI
    try:
        QTimer.singleShot(0, self.soft_refresh_and_restore_view)
    except Exception:
        try:
            self.soft_refresh_and_restore_view()
        except Exception:
            pass

    # Force a full repaint of the table/header to clear occasional stale pixels
    # (seen as blue artefacts between columns on Win32 after copy/move).
    try:
        def _repaint_table():
            try:
                table = getattr(self, "table", None)
                if table is None:
                    return
                try:
                    table.viewport().update()
                except Exception:
                    pass
                try:
                    table.horizontalHeader().viewport().update()
                except Exception:
                    pass
            except Exception:
                pass

        QTimer.singleShot(0, _repaint_table)
    except Exception:
        pass
    
    copy_log("[COPY] _cleanup_copy_thread: DONE - ok={}, error={}", ok_count, error_count, component="COPY")


def _do_move(self, items, result, project_id):
    """Start move operation in background thread."""
    try:
        sync_log("[MOVE] _do_move: START", component="MOVE")
    except Exception:
        pass
    
    dest_folder_id = result.get("id")
    if dest_folder_id in (0, "0"):
        dest_folder_id = project_id
    dest_path = result.get("path")
    source_path = result.get("source_path", "текущей папки")
    self._move_items_backup = items

    dest_names_cf: set[str] | None = set()
    if dest_folder_id not in (None, ""):
        try:
            list_result = self.api.list_files_result(dest_folder_id, project_id=project_id)
            if not getattr(list_result, "ok", False):
                raise RuntimeError(str(getattr(list_result, "error", "connection_lost")))
            docs = getattr(list_result, "data", None) or []
            dest_names_cf = {
                _current_file_name(doc).casefold()
                for doc in docs
                if isinstance(doc, dict)
                and (doc.get("type") or "").lower() in ("file", "document", "doc")
                and _current_file_name(doc)
            }
        except Exception as e:
            sync_log(
                "[MOVE] Destination conflict preflight failed for folder {} project {}: {}",
                dest_folder_id,
                project_id,
                str(e),
                component="MOVE",
            )
            warning_text = t("move.cannot_verify_destination_conflicts")
            QMessageBox.warning(self, t("move.conflict_warning_title"), warning_text)
            self.status.showMessage(warning_text, 6000)
            return

    conflict_names: list[str] = []
    for item in items:
        if (item.get("type") or "").lower() not in ("file", "document", "doc"):
            continue
        cur_name = _current_file_name(item)
        if cur_name and dest_names_cf is not None and cur_name.casefold() in dest_names_cf:
            conflict_names.append(cur_name)

    if conflict_names:
        unique_conflict_names = list(dict.fromkeys(conflict_names))
        formatted_names = _format_move_conflict_names(unique_conflict_names)
        warning_text = t(
            "move.conflict_warning_text",
            count=len(conflict_names),
            names=formatted_names,
        )
        QMessageBox.warning(self, t("move.conflict_warning_title"), warning_text)
        self.status.showMessage(
            t("status.move_conflict_exists_multiple", count=len(conflict_names), names=formatted_names),
            6000,
        )
        return
    
    # Build message string for final status
    n_items = len(items)
    
    # Create background thread and worker
    try:
        th = QThread(self)
        worker = _MoveWorker(self.api, items, dest_folder_id, dest_path, source_path, project_id)
        worker.moveToThread(th)
        
        # Keep references
        try:
            self._move_threads.add(th)
        except Exception:
            self._move_threads = {th}
        self._move_thread = th
        self._move_worker = worker
        
        # Show progress bar
        self._set_progress_visible(True)
        self.progress.setRange(0, n_items)
        self.progress.setValue(0)
        
        # Create cancel button (no parent to avoid cross-thread issues)
        try:
            btn_cancel = QPushButton(t("common.cancel"))
            btn_cancel.setObjectName("moveCancelBtn")
            btn_cancel.setProperty("secondary", True)
            self.status.addPermanentWidget(btn_cancel)
            self._move_cancel_btn = btn_cancel
            btn_cancel.clicked.connect(worker.cancel)
        except Exception as e:
            sync_log("[MOVE] ERROR creating cancel button: {}", str(e), component="MOVE")
        
        # Connect signals - FORCE QueuedConnection for all worker signals to ensure GUI thread
        th.started.connect(worker.run)
        worker.sig_started.connect(lambda: sync_log("[MOVE] Worker started", component="MOVE"), QtCore.Qt.QueuedConnection)
        worker.sig_progress.connect(self._on_move_progress, QtCore.Qt.QueuedConnection)
        worker.sig_finished.connect(self._on_move_finished, QtCore.Qt.QueuedConnection)
        worker.sig_error.connect(lambda e: sync_log("[MOVE] Error: {}", str(e), component="MOVE"), QtCore.Qt.QueuedConnection)

        # Cleanup when finished - use QueuedConnection to ensure GUI thread
        worker.sig_finished.connect(
            lambda ok, err, src, dst: self._cleanup_move_thread(th, worker, ok, err, src, dst, n_items),
            QtCore.Qt.QueuedConnection
        )
        
        # Start thread
        th.start()
        sync_log("[MOVE] Thread started", component="MOVE")
    except Exception as e:
        sync_log("[MOVE] ERROR starting thread: {}", str(e), component="MOVE")
        import traceback
        traceback.print_exc()
        self._set_progress_visible(False)
        self.status.showMessage(t("status.move_start_failed", error=str(e)), 5000)


def _on_move_progress(self, current: int, total: int, message: str):
    """Handle progress update from move worker. MUST run in GUI thread."""
    gui_thread = QtCore.QCoreApplication.instance().thread() if QtCore.QCoreApplication.instance() else None
    if gui_thread and QtCore.QThread.currentThread() is not gui_thread:
        sync_log("[MOVE] ERROR: _on_move_progress called from worker thread, deferring", component="MOVE")
        QTimer.singleShot(0, self, lambda: self._on_move_progress(current, total, message))
        return
    self.progress.setValue(current)
    self.status.showMessage(message)


def _on_move_finished(self, ok_count: int, error_count: int, source_path: str, dest_path: str):
    """Handle move completion."""
    # Will be called from cleanup function
    pass


def _cleanup_move_thread(self, th: QThread, worker: QObject, ok_count: int, error_count: int, source_path: str, dest_path: str, n_items: int):
    """Clean up move thread and show final status. MUST run in GUI thread."""
    gui_thread = QtCore.QCoreApplication.instance().thread() if QtCore.QCoreApplication.instance() else None
    if gui_thread and QtCore.QThread.currentThread() is not gui_thread:
        sync_log("[MOVE] ERROR: _cleanup_move_thread called from worker thread, deferring", component="MOVE")
        QTimer.singleShot(0, self, lambda: self._cleanup_move_thread(th, worker, ok_count, error_count, source_path, dest_path, n_items))
        return

    # Build message string
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
    
    n_folders = sum(1 for it in getattr(self, "_move_items_backup", []) if it.get("type") == "folder")
    n_files = n_items - n_folders
    
    msg_parts = []
    if n_folders:
        folder_form = _plural_form(n_folders, ('папка', 'папки', 'папок'))
        msg_parts.append(f"{n_folders} {folder_form}")
    if n_files:
        file_form = _plural_form(n_files, ('файл', 'файла', 'файлов'))
        msg_parts.append(f"{n_files} {file_form}")
    msg = ", ".join(msg_parts)
    
    # Clean up cancel button
    try:
        btn = getattr(self, "_move_cancel_btn", None)
        if btn:
            btn.hide()
            btn.setEnabled(False)
            btn.clicked.disconnect()
            self.status.removeWidget(btn)
            btn.deleteLater()
    except Exception as e:
        sync_log("[MOVE] ERROR removing cancel button: {}", str(e), component="MOVE")
    self._move_cancel_btn = None
    try:
        self.status.update()
        self.status.repaint()
    except Exception:
        pass
    
    # Clean up thread
    try:
        if isinstance(th, QThread):
            try:
                if QtCore.QThread.currentThread() is not th:
                    th.quit()
                    th.wait(1500)
                else:
                    th.quit()
            except Exception:
                pass
            try:
                th.deleteLater()
            except Exception:
                pass
    except Exception:
        pass
    
    # Clean up references
    try:
        if hasattr(self, "_move_threads") and isinstance(self._move_threads, set):
            self._move_threads.discard(th)
    except Exception:
        pass
    self._move_thread = None
    self._move_worker = None
    
    # Hide progress bar
    self._set_progress_visible(False)
    
    # Show final message
    if error_count == 0:
        self.status.showMessage(t("status.move_result_success", items=msg, src=source_path, dst=dest_path), 4000)
    elif ok_count == 0:
        self.status.showMessage(t("status.move_result_failed", items=msg, src=source_path), 4000)
    else:
        if error_count == 1:
            warning = t("status.move_partial_warning_single")
        else:
            warning = t("status.move_partial_warning_multiple", count=error_count)
        self.status.showMessage(t("status.move_result_partial", ok=ok_count, total=ok_count + error_count, warning=warning), 6000)
    
    # Force refresh UI - clear API cache and reload
    try:
        # Clear API cache for this project
        project_id = self.current_project_id()
        if project_id:
            try:
                cache_key = f"tree:{project_id}"
                self.api.cache.pop(cache_key, None)
                print(f"[MOVE] Cleared cache for tree:{project_id}")
            except Exception as e:
                print(f"[MOVE] Error clearing cache: {e}")
        
        # Also clear folder_docs cache
        try:
            current_folder = self.current_folder_node()
            if current_folder:
                folder_id = current_folder.get("id")
                if folder_id:
                    cache_key = f"folder_docs:{folder_id}"
                    self.api.cache.pop(cache_key, None)
                    print(f"[MOVE] Cleared cache for folder_docs:{folder_id}")
        except Exception as e:
            print(f"[MOVE] Error clearing folder_docs cache: {e}")
        
        # Refresh UI
        QTimer.singleShot(0, self.soft_refresh_and_restore_view)
        print(f"[MOVE] Triggered UI refresh")
    except Exception:
        try:
            self.soft_refresh_and_restore_view()
        except Exception:
            pass

    # Force a full repaint of the table/header to clear occasional stale pixels
    # (seen as blue artefacts between columns on Win32 after copy/move).
    try:
        def _repaint_table():
            try:
                table = getattr(self, "table", None)
                if table is None:
                    return
                try:
                    table.viewport().update()
                except Exception:
                    pass
                try:
                    table.horizontalHeader().viewport().update()
                except Exception:
                    pass
            except Exception:
                pass

        QTimer.singleShot(0, _repaint_table)
    except Exception:
        pass
    
    sync_log("[MOVE] _cleanup_move_thread: DONE - ok={}, error={}", ok_count, error_count, component="MOVE")


def _do_copy_folder(self, src_folder_id, dest_folder_id, new_name, dest_path):
    """Actually perform folder copy operation."""
    try:
        new_id = self.api.copy_folder(src_folder_id, dest_folder_id, new_name)
        if new_id:
            print(f"Папка \"{new_name}\" успешно скопирована в \"{dest_path}\".")
            try:
                # Refresh view so the copied folder appears.
                QTimer.singleShot(0, self.soft_refresh_and_restore_view)
            except Exception:
                try:
                    self.soft_refresh_and_restore_view()
                except Exception:
                    pass
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
        print(t("folder.select_folder_move"))
        return
    
    folder_id = item.get("id")
    name = item.get("name") or item.get("title") or "Без названия"
    project_id = self.current_project_id()
    
    result = self._prompt_folder_select(t("folder.select_destination_move"), can_select_current=False)
    if not result:
        return
    
    dest_folder_id = result.get("id")
    dest_path = result.get("path")
    
    if dest_folder_id == folder_id:
        print(t("folder.cannot_move_to_self"))
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
        print(t("folder.select_items_move"))
        return
    
    project_id = self.current_project_id()
    
    # Get source folder info before opening destination dialog
    source_folder_node = self.current_folder_node()
    source_path = None
    if source_folder_node:
        source_name = source_folder_node.get("name") or source_folder_node.get("title") or "Без названия"
        source_path = f"\"{source_name}\""
    
    result = self._prompt_folder_select(t("folder.select_destination_move"), can_select_current=True)
    if not result:
        return
    
    # Add source path to result
    result["source_path"] = source_path
    
    # Save items for move worker (to build message later)
    self._move_items_backup = items
    
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
    try:
        dialog.setAttribute(Qt.WA_QuitOnClose, False)
    except Exception:
        pass

    layout = QVBoxLayout(dialog)
    
    tree = QTreeWidget(dialog)
    tree.setObjectName("folderSelectTree")
    tree.setHeaderLabels([t("folder.folders_header")])
    tree.setSelectionBehavior(QAbstractItemView.SelectRows)
    tree.setAlternatingRowColors(False)
    tree.setRootIsDecorated(True)
    tree.setItemsExpandable(True)
    tree.setExpandsOnDoubleClick(True)
    tree.setMouseTracking(True)
    tree.viewport().setAttribute(Qt.WA_Hover, True)
    tree.viewport().setMouseTracking(True)
    tree._hover_index = QModelIndex()
    tree._pressed_index = QModelIndex()
    try:
        tree.setItemDelegate(MenuLikeTreeDelegate(tree))
    except Exception:
        pass
    tree.setStyleSheet("""
        QTreeWidget#folderSelectTree {
            background: #FFFFFF;
            selection-background-color: transparent;
            show-decoration-selected: 0;
            outline: 0;
        }
        QTreeWidget#folderSelectTree::item,
        QTreeWidget#folderSelectTree::item:selected,
        QTreeWidget#folderSelectTree::item:selected:active,
        QTreeWidget#folderSelectTree::item:selected:!active,
        QTreeWidget#folderSelectTree::item:focus,
        QTreeWidget#folderSelectTree::item:hover,
        QTreeWidget#folderSelectTree::item:selected:hover {
            background: transparent;
            border: none;
            outline: none;
            color: #000000;
        }
        QTreeWidget#folderSelectTree::branch,
        QTreeWidget#folderSelectTree::branch:hover,
        QTreeWidget#folderSelectTree::branch:selected,
        QTreeWidget#folderSelectTree::branch:selected:hover {
            background: transparent;
            border: none;
        }
    """)

    def _set_hover_index(index):
        try:
            tree._hover_index = index if index.isValid() else QModelIndex()
            tree.viewport().update()
        except Exception:
            pass

    def _set_pressed_index(index):
        try:
            tree._pressed_index = index if index.isValid() else QModelIndex()
            tree.viewport().update()
        except Exception:
            pass

    class _FolderSelectHoverFilter(QObject):
        def eventFilter(self, obj, event):
            try:
                if event.type() == QEvent.Type.Leave:
                    _set_hover_index(QModelIndex())
                elif event.type() == QEvent.Type.MouseButtonRelease:
                    _set_pressed_index(QModelIndex())
            except Exception:
                pass
            return False

    hover_filter = _FolderSelectHoverFilter(tree)
    tree.viewport().installEventFilter(hover_filter)
    tree._hover_filter = hover_filter
    try:
        tree.entered.connect(_set_hover_index)
    except Exception:
        pass
    try:
        tree.pressed.connect(_set_pressed_index)
    except Exception:
        pass
    try:
        tree.viewportEntered.connect(lambda: _set_hover_index(QModelIndex()))
    except Exception:
        pass
    
    current_node = self.current_folder_node()
    current_folder_id = current_node.get("id") if current_node else None
    
    project_id = self.current_project_id()
    folders = getattr(self, "full_tree", None)
    if not isinstance(folders, list) or not folders:
        folders = self.api.list_folders(project_id, force=True)
    
    root_item = QTreeWidgetItem(tree)
    root_item.setText(0, t("folder.root"))
    root_item.setData(0, Qt.UserRole, project_id)
    
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
    if folder_id is None:
        return None
    
    path_parts = []
    item = selected
    while item:
        fid = item.data(0, Qt.UserRole)
        if str(fid) != str(project_id):
            path_parts.insert(0, item.text(0))
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
    # Store original closeEvent
    _original_close = getattr(MainWindowClass, "closeEvent", None)
    
    # Define new closeEvent that calls original + cleans up copy/move threads
    def _new_close_event(self, event):
        """Ensure all worker threads are cleanly stopped before window closes."""
        try:
            # Stop any ongoing copy threads
            for th in list(getattr(self, "_copy_threads", set())):
                try:
                    if isinstance(th, QThread):
                        try:
                            if QtCore.QThread.currentThread() is not th:
                                th.quit(); th.wait(1500)
                            else:
                                th.quit()
                        except Exception:
                            pass
                    try:
                        self._copy_threads.discard(th)
                    except Exception:
                        pass
                except Exception:
                    pass
        except Exception:
            pass
        try:
            # Stop any ongoing move threads
            for th in list(getattr(self, "_move_threads", set())):
                try:
                    if isinstance(th, QThread):
                        try:
                            if QtCore.QThread.currentThread() is not th:
                                th.quit(); th.wait(1500)
                            else:
                                th.quit()
                        except Exception:
                            pass
                    try:
                        self._move_threads.discard(th)
                    except Exception:
                        pass
                except Exception:
                    pass
        except Exception:
            pass
        try:
            # Clean up cancel buttons
            for btn_name in ("_copy_cancel_btn", "_move_cancel_btn"):
                try:
                    btn = getattr(self, btn_name, None)
                    if btn:
                        btn.clicked.disconnect()
                        try:
                            self.status.removeWidget(btn)
                        except Exception:
                            pass
                        btn.deleteLater()
                        setattr(self, btn_name, None)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if _original_close is not None:
                _original_close(self, event)
            else:
                super(type(self), self).closeEvent(event)
        except Exception:
            pass
    
    MainWindowClass._generate_unique_name = _generate_unique_name
    MainWindowClass.copy_folder_action = copy_folder_action
    MainWindowClass.copy_selected_action = copy_selected_action
    MainWindowClass._do_copy = _do_copy
    MainWindowClass._do_copy_folder = _do_copy_folder
    MainWindowClass._on_copy_progress = _on_copy_progress
    MainWindowClass._on_copy_finished = _on_copy_finished
    MainWindowClass._cleanup_copy_thread = _cleanup_copy_thread
    MainWindowClass.move_folder_action = move_folder_action
    MainWindowClass.move_selected_action = move_selected_action
    MainWindowClass._do_move = _do_move
    MainWindowClass._do_move_folder = _do_move_folder
    MainWindowClass._on_move_progress = _on_move_progress
    MainWindowClass._on_move_finished = _on_move_finished
    MainWindowClass._cleanup_move_thread = _cleanup_move_thread
    MainWindowClass._prompt_folder_select = _prompt_folder_select
    MainWindowClass._populate_folder_tree_from_list = _populate_folder_tree_from_list
