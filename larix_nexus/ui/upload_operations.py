# -*- coding: utf-8 -*-
"""Upload operations for Larix Nexus."""

import os
from pathlib import Path
from PySide6.QtWidgets import QFileDialog, QMessageBox, QMenu, QApplication
from PySide6.QtCore import Qt
from ..constants import THEME_LIGHT, THEME_DARK
from ..utils.helpers import normalize_id


def _upload_dir_recursive(self, project_id: int | str, parent_folder_id: int | str, local_dir: Path):
    """Recursively upload directory to server."""
    base_id = self._ensure_subfolder(project_id, parent_folder_id, local_dir.name)
    if not base_id:
        return
    try:
        for entry in sorted(local_dir.iterdir()):
            if entry.is_dir():
                self._upload_dir_recursive(project_id, base_id, entry)
            elif entry.is_file():
                ok = self.api.upload_file(base_id, str(entry), entry.name)
                try:
                    if ok:
                        self._log_user_action("upload", file_name=entry.name, folder_id=base_id)
                        self._upload_ok = getattr(self, "_upload_ok", 0) + 1
                    else:
                        self._upload_fail = getattr(self, "_upload_fail", 0) + 1
                except Exception:
                    pass
    except Exception:
        pass


def _collect_upload_tasks(self, paths: list[Path], display_prefix: tuple[str, ...] = ()) -> list[dict]:
    """Collect upload tasks from file/folder paths."""
    tasks: list[dict] = []
    seen: set[str] = set()

    def canonical(p: Path) -> str:
        try:
            return str(p.resolve())
        except Exception:
            return str(p)

    def add_file(local_path: Path, folder_parts: tuple[str, ...], display_parts: tuple[str, ...]) -> None:
        key = canonical(local_path)
        if key in seen:
            return
        seen.add(key)
        display = display_prefix + display_parts + (local_path.name,)
        tasks.append(
            {
                "key": f"task_{len(tasks)}",
                "path": local_path,
                "parts": folder_parts,
                "display_parts": display,
                "display": " / ".join(display) if display else local_path.name,
                "name": local_path.name,
                "conflict": False,
            }
        )

    def walk_dir(base: Path, folder_parts: tuple[str, ...], display_parts: tuple[str, ...]) -> None:
        try:
            entries = sorted(base.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except Exception:
            return
        for entry in entries:
            if entry.is_file():
                add_file(entry, folder_parts, display_parts)
            elif entry.is_dir():
                walk_dir(entry, folder_parts + (entry.name,), display_parts + (entry.name,))

    for source in paths:
        p = Path(source)
        if not p.exists():
            continue
        if p.is_file():
            add_file(p, tuple(), tuple())
        elif p.is_dir():
            walk_dir(p, (p.name,), (p.name,))
    return tasks


def _existing_names_for_folder(self, folder_id) -> set[str]:
    """Get existing filenames in folder (case-insensitive)."""
    names: set[str] = set()
    fid_key = normalize_id(folder_id)
    try:
        files_current = getattr(self, "files_current", [])
        for item in files_current:
            if not isinstance(item, dict):
                continue
            item_type = (item.get("type") or "").lower()
            if item_type != "file":
                continue
            parent_fields = ["folderId", "parentId", "parent_id", "folder_id", "parent", "folder"]
            parent = None
            for field in parent_fields:
                if field in item and item[field] is not None:
                    parent = item[field]
                    break
            parent_key = normalize_id(parent)
            if not parent_key or parent_key != fid_key:
                continue
            name = item.get("originalName") or item.get("name")
            if name:
                names.add(name.casefold())
    except Exception:
        pass
    return names


def _ensure_remote_path_chain(self, project_id: int | str, folder_cache: dict[tuple[str, ...], int], parts: tuple[str, ...]) -> int | None:
    """Ensure remote path exists, return folder id."""
    if not parts:
        return None
    cache_key = parts
    if cache_key in folder_cache:
        return folder_cache[cache_key]
    
    parent_id = None
    current_parts = tuple()
    
    for i, part in enumerate(parts):
        current_parts = parts[:i+1]
        if current_parts in folder_cache:
            parent_id = folder_cache[current_parts]
            continue
        
        folder_id = self._ensure_subfolder(project_id, parent_id, part)
        if not folder_id:
            return None
        folder_cache[current_parts] = folder_id
        parent_id = folder_id
    
    return parent_id


def _unique_remote_name(self, taken: set[str], name: str) -> str:
    """Generate unique name avoiding conflicts."""
    base, ext = os.path.splitext(name)
    base = (base or name or "file").strip() or "file"
    candidate = f"{base}_копия{ext}"
    idx = 2
    while candidate.casefold() in taken:
        candidate = f"{base}_копия{idx}{ext}"
        idx += 1
    return candidate


def _upload_list_to_folder(self, target_folder: dict, paths: list[Path], display_prefix: tuple[str, ...] = ()):
    """Upload list of files/folders to target folder with batch dialog for conflicts."""
    if not target_folder or not paths:
        return
    
    project_id = self.current_project_id()
    if not project_id:
        QMessageBox.warning(self, "Ошибка", "Не выбран проект.")
        return
    
    folder_id = normalize_id(target_folder.get("id") or target_folder.get("folderId"))
    if not folder_id:
        QMessageBox.warning(self, "Ошибка", "Не определена целевая папка.")
        return
    
    tasks = self._collect_upload_tasks(paths, display_prefix)
    if not tasks:
        QMessageBox.information(self, "Загрузка", "Нет файлов для загрузки.")
        return
    
    # Проверяем конфликты имен файлов на сервере для всех папок
    existing_map: dict[tuple[str, ...], set[str]] = {tuple(): self._existing_names_for_folder(folder_id)}
    conflicts_total = 0
    
    for task in tasks:
        folder_parts = tuple(task["parts"])
        # Получаем существующие файлы для нужной папки
        if folder_parts not in existing_map:
            # Для подпапок пока считаем, что конфликтов нет (они будут проверены при создании)
            existing_map[folder_parts] = set()
        
        task["conflict"] = task["name"].casefold() in existing_map[folder_parts]
        if task["conflict"]:
            conflicts_total += 1
    
    icon_provider = getattr(self, "icon_provider", None)
    total = len(tasks)
    self._upload_ok = 0
    self._upload_fail = 0
    
    from ..ui.dialogs import BatchUploadDialog
    dlg = BatchUploadDialog(self, total, icon_provider)
    
    # Добавляем все файлы в диалог
    for task in tasks:
        pseudo = {"type": "file", "name": task["name"], "originalName": task["name"]}
        dlg.add_entry(task["key"], pseudo, task["display"])
        if task["conflict"]:
            dlg.set_status(task["key"], "none", "Файл уже существует")
        else:
            dlg.set_status(task["key"], "ok", "Готов к загрузке")
    
    dlg.set_total_conflicts(conflicts_total)
    dlg.show()
    QApplication.processEvents()
    dlg.update_progress(0, total)
    
    # Даем Qt время на отрисовку диалога перед началом загрузки
    from PySide6.QtCore import QTimer
    QTimer.singleShot(50, lambda: None)
    QApplication.processEvents()
    
    folder_cache: dict[tuple[str, ...], int] = {tuple(): folder_id}
    ok_count = 0
    fail_count = 0
    processed = 0
    cancelled = False
    
    for task in tasks:
        if dlg.was_cancelled():
            cancelled = True
            break
        
        folder_parts = tuple(task["parts"])
        parent_id = folder_cache.get(folder_parts)
        if parent_id is None:
            parent_id = self._ensure_remote_path_chain(project_id, folder_cache, folder_parts)
            if parent_id is None:
                fail_count += 1
                dlg.set_status(task["key"], "none", "Не удалось создать папку на сервере.")
                processed += 1
                dlg.update_progress(processed, total)
                QApplication.processEvents()
                continue
        
        # Обновляем множество имен после создания каждого файла
        names_set = existing_map.setdefault(folder_parts, self._existing_names_for_folder(parent_id))
        
        # Обрабатываем конфликт, если он есть
        if task.get("conflict", False):
            remaining_conflicts = sum(1 for t in tasks[tasks.index(task):] if t.get("conflict", False))
            decision, apply_all = dlg.ask_conflict(task["key"], task["name"], remaining_conflicts)
            
            if decision == "cancel":
                fail_count += 1
                dlg.set_status(task["key"], "none", "Загрузка отменена пользователем.")
                processed += 1
                dlg.update_progress(processed, total)
                QApplication.processEvents()
                continue
            elif decision == "copy":
                # Создаем уникальное имя
                new_name = self._unique_remote_name(names_set, task["name"])
                task["name"] = new_name
                names_set.add(new_name.casefold())
                dlg.set_name(task["key"], new_name)
            
            # Если apply_all, применяем решение ко всем остальным конфликтам
            if apply_all:
                for future_task in tasks[tasks.index(task) + 1:]:
                    if future_task.get("conflict", False):
                        if decision == "copy":
                            future_folder_parts = tuple(future_task["parts"])
                            future_names_set = existing_map.setdefault(future_folder_parts, self._existing_names_for_folder(folder_cache.get(future_folder_parts, folder_id)))
                            new_name = self._unique_remote_name(future_names_set, future_task["name"])
                            future_task["name"] = new_name
                            future_names_set.add(new_name.casefold())
                            dlg.set_name(future_task["key"], new_name)
                        # Убираем флаг конфликта, чтобы не показывать диалог повторно
                        future_task["conflict"] = False
        
        dlg.set_status(task["key"], "process", "Загрузка...")
        QApplication.processEvents()
        error_detail = ""
        try:
            path = task.get("path")
            if not path or not path.exists():
                fail_count += 1
                dlg.set_status(task["key"], "none", "Файл не найден")
                processed += 1
                dlg.update_progress(processed, total)
                continue
            
            ok = self.api.upload_file(parent_id, str(path), task["name"])
        except Exception as exc:
            ok = False
            error_detail = str(exc)
        
        if ok:
            ok_count += 1
            names_set.add(task["name"].casefold())
            dlg.set_status(task["key"], "ok", "Загружено.")
            
            # Log user action for notification filtering
            try:
                self._log_user_action("upload", file_id=None, file_name=task["name"], folder_id=parent_id)
            except Exception:
                pass
        else:
            fail_count += 1
            tooltip = "Ошибка загрузки"
            if error_detail:
                tooltip = f"{tooltip}: {error_detail}"
            dlg.set_status(task["key"], "none", tooltip)
        
        processed += 1
        dlg.update_progress(processed, total)
        QApplication.processEvents()
        if dlg.was_cancelled():
            cancelled = True
            break
    
    self._upload_ok, self._upload_fail = ok_count, fail_count
    try:
        self.open_folder_node(target_folder)
        self.refresh_tree()
    except Exception:
        pass
    
    cancelled = cancelled or dlg.was_cancelled()
    if cancelled:
        try:
            self.status.showMessage("Загрузка отменена пользователем.", 5000)
        except Exception:
            pass
        return
    
    if fail_count:
        dlg.finish(f"Загружено файлов: {ok_count} из {total}.")
        dlg.exec()
        try:
            self.status.showMessage(f"Загружено файлов: {ok_count} из {total}.", 6000)
        except Exception:
            pass
    else:
        dlg.finish(f"Загружено файлов: {ok_count}.")
        dlg.exec()
        try:
            self.status.showMessage(f"Загружено файлов: {ok_count}.", 5000)
        except Exception:
            pass


def upload_file(self):
    """Upload single file dialog."""
    project_id = self.current_project_id()
    if not project_id:
        QMessageBox.warning(self, "Загрузка", "Не выбран проект.")
        return
    
    folder = self.current_folder_node()
    if not folder:
        QMessageBox.warning(self, "Загрузка", "Не выбрана папка.")
        return
    
    folder_id = normalize_id(folder.get("id") or folder.get("folderId"))
    if not folder_id:
        return
    
    file_path, _ = QFileDialog.getOpenFileName(self, "Выберите файл для загрузки")
    if not file_path:
        return
    
    path = Path(file_path)
    
    # Загружаем через _upload_list_to_folder для показа диалога конфликтов
    self._upload_list_to_folder(folder, [path])
    
    # Show progress bar
    self._set_progress_visible(True)
    self.progress.setRange(0, 0)
    QApplication.processEvents()
    
    try:
        ok = self.api.upload_file(folder_id, file_path, name)
        if ok:
            self._log_user_action("upload", file_name=name, folder_id=folder_id)
            # Refresh current folder
            self.open_folder_node(folder)
            QMessageBox.information(self, "Загрузка", "Файл успешно загружен.")
            self.refresh_tree()
        else:
            QMessageBox.warning(self, "Загрузка", "Не удалось загрузить файл.")
    finally:
        self._set_progress_visible(False)


def _build_upload_menu(self) -> QMenu:
    """Build upload submenu."""
    menu = QMenu("Загрузить", self)
    
    act_file = menu.addAction("Загрузить файлы...")
    act_file.triggered.connect(self._action_upload_file)
    
    act_folder = menu.addAction("Загрузить папку...")
    act_folder.triggered.connect(self._action_upload_folder)
    
    return menu


def _action_upload_file(self):
    """Handle upload file action."""
    project_id = self.current_project_id()
    if not project_id:
        return
    
    folder = self.current_folder_node()
    if not folder:
        return
    
    file_paths, _ = QFileDialog.getOpenFileNames(self, "Выберите файлы")
    if not file_paths:
        return
    
    paths = [Path(p) for p in file_paths]
    self._upload_list_to_folder(folder, paths)


def _pick_directory_showing_files(self, title: str = "Выберите папку") -> str:
    """Pick directory with file dialog showing files."""
    dlg = QFileDialog(self, title)
    dlg.setFileMode(QFileDialog.Directory)
    dlg.setOption(QFileDialog.ShowDirsOnly, False)
    if dlg.exec():
        return dlg.selectedFiles()[0]
    return ""


def _pick_directory_native(self, title: str) -> str:
    """Pick directory using native dialog."""
    return QFileDialog.getExistingDirectory(self, title)


def _action_upload_folder(self):
    """Handle upload folder action."""
    project_id = self.current_project_id()
    if not project_id:
        return
    
    folder = self.current_folder_node()
    if not folder:
        return
    
    dir_path = self._pick_directory_showing_files("Выберите папку для загрузки")
    if not dir_path:
        return
    
    self._upload_list_to_folder(folder, [Path(dir_path)])


def _update_upload_menu_visibility(self):
    """Update upload menu visibility based on current state."""
    if not hasattr(self, '_upload_menu'):
        return
    
    has_project = self.current_project_id() is not None
    has_folder = self.current_folder_node() is not None
    self._upload_menu.setEnabled(has_project and has_folder)


def _upload_dir_to_root(self, project_id: int | str, local_dir: "Path"):
    """Upload directory to project root."""
    project_id = normalize_id(project_id)
    if not project_id:
        return
    
    folder_id = project_id
    self._upload_dir_recursive(project_id, folder_id, local_dir)
    self.refresh_tree()


def inject_upload_operations_to_main_window(MainWindowClass):
    """Inject upload operations into MainWindow class."""
    MainWindowClass._upload_dir_recursive = _upload_dir_recursive
    MainWindowClass._collect_upload_tasks = _collect_upload_tasks
    MainWindowClass._existing_names_for_folder = _existing_names_for_folder
    MainWindowClass._ensure_remote_path_chain = _ensure_remote_path_chain
    MainWindowClass._unique_remote_name = _unique_remote_name
    MainWindowClass._upload_list_to_folder = _upload_list_to_folder
    MainWindowClass.upload_file = upload_file
    MainWindowClass._build_upload_menu = _build_upload_menu
    MainWindowClass._action_upload_file = _action_upload_file
    MainWindowClass._pick_directory_showing_files = _pick_directory_showing_files
    MainWindowClass._pick_directory_native = _pick_directory_native
    MainWindowClass._action_upload_folder = _action_upload_folder
    MainWindowClass._update_upload_menu_visibility = _update_upload_menu_visibility
    MainWindowClass._upload_dir_to_root = _upload_dir_to_root
