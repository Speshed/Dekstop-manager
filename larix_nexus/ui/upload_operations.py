# -*- coding: utf-8 -*-
"""Upload operations for Larix Nexus."""

import os
import threading
import logging
from pathlib import Path
from PySide6.QtWidgets import QFileDialog, QMessageBox, QMenu
from PySide6.QtCore import Qt, QObject, QThread, Signal, Slot
from ..constants import THEME_LIGHT, THEME_DARK
from ..utils.helpers import normalize_id
from ..utils.settings import load_settings, save_settings
from ..utils.i18n import t

logger = logging.getLogger(__name__)


def _select_upload_document_type(self):
    """Return a server-confirmed document type and persist the selection."""
    try:
        types_map = self.api.get_document_types() or {}
    except Exception:
        types_map = {}
    if isinstance(types_map, dict):
        raw_ids = list(types_map.keys())
    elif isinstance(types_map, (list, tuple)):
        raw_ids = list(types_map)
    else:
        raw_ids = []
    valid_ids = []
    for raw_id in raw_ids:
        try:
            value = int(str(raw_id).strip())
        except (TypeError, ValueError):
            continue
        if value > 0 and value not in valid_ids:
            valid_ids.append(value)
    if not valid_ids:
        if hasattr(self, "status"):
            self.status.showMessage("Не удалось получить доступные типы документов для загрузки.", 6000)
        return None
    selected = valid_ids[0]
    try:
        settings = load_settings()
        if not isinstance(settings, dict):
            settings = {}
        saved_value = settings.get("last_document_type_id")
        saved = int(str(saved_value).strip()) if saved_value not in (None, "") else None
        if saved is not None and saved in valid_ids:
            selected = saved
        settings["last_document_type_id"] = selected
        save_settings(settings)
    except Exception:
        logger.warning("Could not persist selected document type")
    return selected


def _upload_dir_recursive(
    self,
    project_id: int | str,
    parent_folder_id: int | str,
    local_dir: Path,
    document_type_id: int | None = None,
):
    """Recursively upload directory to server."""
    if document_type_id is None:
        document_type_id = _select_upload_document_type(self)
        if document_type_id is None:
            return

    base_id = self._ensure_subfolder(project_id, parent_folder_id, local_dir.name)
    if not base_id:
        return
    try:
        for entry in sorted(local_dir.iterdir()):
            if entry.is_dir():
                self._upload_dir_recursive(
                    project_id, base_id, entry, document_type_id
                )
            elif entry.is_file():
                ok = self.api.upload_file(
                    base_id,
                    str(entry),
                    entry.name,
                    document_type_id=document_type_id,
                )
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
    """Get existing filenames and foldernames in folder (case-insensitive)."""
    self._last_existing_names_error = None
    names: set[str] = set()
    fid_key = normalize_id(folder_id)
    project_id = None
    try:
        project_id = self.current_project_id()
    except Exception:
        project_id = None

    def _file_name(it: dict) -> str:
        return it.get("name") or it.get("fileName") or it.get("originalName") or ""

    def _folder_name(it: dict) -> str:
        return it.get("name") or it.get("title") or ""

    try:
        files_current = getattr(self, "files_current", [])
        matched_any = False
        for item in files_current:
            if not isinstance(item, dict):
                continue
            item_type = (item.get("type") or "").lower()
            if item_type not in ("file", "folder"):
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
            matched_any = True
            name = _folder_name(item) if item_type == "folder" else _file_name(item)
            if name:
                names.add(name.casefold())

        # If we couldn't find destination contents in current UI list, fetch from API.
        if not matched_any and hasattr(self, "api") and fid_key:
            try:
                result = self.api.list_files_result(fid_key, project_id=project_id)
                if not getattr(result, "ok", False):
                    self._last_existing_names_error = str(getattr(result, "error", "connection_lost"))
                    return names
                docs = getattr(result, "data", None) or []
                for d in docs:
                    if not isinstance(d, dict):
                        continue
                    item_type = (d.get("type") or "").lower()
                    nm = _folder_name(d) if item_type in ("folder", "dir", "directory", "папка") else _file_name(d)
                    if nm:
                        names.add(nm.casefold())
            except Exception as e:
                self._last_existing_names_error = str(e)
                return names
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
    
    parent_id = folder_cache.get(tuple())
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


class _BatchUploadWorker(QObject):
    item_started = Signal(str, int, int)
    item_finished = Signal(str, str, str, int, int, int)
    item_renamed = Signal(str, str)
    conflict_requested = Signal(str, str, int)
    finished = Signal(int, int, int, int, bool)

    def __init__(self, owner, project_id, folder_id, tasks, fallback_doc_type_id):
        super().__init__()
        self._owner = owner
        self._api = owner.api
        self._project_id = project_id
        self._folder_id = folder_id
        self._tasks = list(tasks)
        self._fallback_doc_type_id = fallback_doc_type_id
        self._cancelled = threading.Event()
        self._decision_condition = threading.Condition()
        self._decision = None

    def cancel(self) -> None:
        logger.info("Batch upload cancellation requested")
        self._cancelled.set()
        with self._decision_condition:
            self._decision = ("cancel", False)
            self._decision_condition.notify_all()

    def set_conflict_decision(self, decision: str, apply_all: bool) -> None:
        logger.info("Conflict decision received: %s apply_all=%s", decision, apply_all)
        with self._decision_condition:
            self._decision = (decision, apply_all)
            self._decision_condition.notify_all()

    def _wait_for_conflict(self, key: str, name: str, remaining: int):
        with self._decision_condition:
            self._decision = None
            logger.info("Conflict decision requested: %s", key)
            self.conflict_requested.emit(key, name, remaining)
            while self._decision is None and not self._cancelled.is_set():
                self._decision_condition.wait()
            logger.info("Conflict decision released: %s", key)
            return self._decision or ("cancel", False)

    @Slot()
    def run(self) -> None:
        folder_cache = {tuple(): self._folder_id}
        existing_map = {}
        ok_count = 0
        error_count = 0
        skipped_count = 0
        done = 0
        conflicts_left = 0
        apply_all_choice = None
        logger.info("Batch upload worker started: total=%d", len(self._tasks))
        try:
            for index, task in enumerate(self._tasks, start=1):
                if self._cancelled.is_set():
                    logger.info("Batch upload cancelled before task %s", task.get("key", ""))
                    break
                key = task["key"]
                self.item_started.emit(key, index, len(self._tasks))
                logger.info("Batch upload task started: %s", key)
                if self._cancelled.is_set():
                    break
                folder_parts = tuple(task.get("parts", ()))
                parent_id = folder_cache.get(folder_parts)
                if parent_id is None:
                    logger.info("Preparing remote folder for task %s", key)
                    parent_id = self._owner._ensure_remote_path_chain(
                        self._project_id, folder_cache, folder_parts
                    )
                    if self._cancelled.is_set():
                        break
                if parent_id is None:
                    error_count += 1
                    done += 1
                    self.item_finished.emit(key, "error", t("upload.folder_create_failed"), done, ok_count, error_count)
                    continue

                names_set = existing_map.get(folder_parts)
                if names_set is None:
                    logger.info("Checking conflicts for task %s", key)
                    names_set = self._owner._existing_names_for_folder(parent_id)
                    existing_map[folder_parts] = names_set
                    conflict_error = getattr(self._owner, "_last_existing_names_error", None)
                    if conflict_error:
                        logger.warning("Conflict check failed for task %s: %s", key, conflict_error)
                        names_set = set()
                    logger.info("Conflict check finished for task %s", key)
                if self._cancelled.is_set():
                    break
                is_conflict = bool(task.get("conflict")) or task["name"].casefold() in names_set
                if is_conflict:
                    decision = apply_all_choice
                    if decision is None:
                        # Conflicts are discovered lazily, so the exact total
                        # is unknown. Let the GUI use the unnumbered message.
                        remaining = 0
                        decision, apply_all = self._wait_for_conflict(
                            key, task["name"], remaining
                        )
                        if apply_all:
                            apply_all_choice = decision
                    conflicts_left = max(0, conflicts_left - 1)
                    if decision == "cancel":
                        self._cancelled.set()
                        break
                    if decision == "skip":
                        skipped_count += 1
                        done += 1
                        self.item_finished.emit(
                            key,
                            "skipped",
                            "Пропущено: файл с таким именем уже существует",
                            done,
                            ok_count,
                            error_count,
                        )
                        continue
                    if decision == "copy":
                        new_name = self._owner._unique_remote_name(names_set, task["name"])
                        task["name"] = new_name
                        self.item_renamed.emit(key, new_name)

                path = task.get("path")
                if not path or not path.exists():
                    error_count += 1
                    done += 1
                    self.item_finished.emit(key, "error", t("upload.file_not_found"), done, ok_count, error_count)
                    continue

                document_type = task.get("document_type_id")
                error_detail = ""
                if self._cancelled.is_set():
                    break
                logger.info("upload_file started: %s", key)
                try:
                    uploaded = self._api.upload_file(
                        parent_id, str(path), task["name"], document_type_id=document_type
                    )
                except Exception as exc:
                    uploaded = False
                    error_detail = str(exc)
                logger.info("upload_file finished: %s success=%s", key, bool(uploaded))
                if self._cancelled.is_set():
                    break

                if uploaded:
                    ok_count += 1
                    names_set.add(task["name"].casefold())
                    status_text = t("upload.updated") if is_conflict else t("upload.uploaded")
                    try:
                        self._owner._log_user_action(
                            "upload", file_id=None, file_name=task["name"], folder_id=parent_id
                        )
                    except Exception:
                        pass
                    status = "ok"
                else:
                    error_count += 1
                    status_text = t("upload.upload_error")
                    error_detail = error_detail or getattr(self._api, "_last_upload_error", "")
                    if error_detail:
                        status_text = f"{status_text}: {error_detail}"
                    status = "error"
                done += 1
                self.item_finished.emit(key, status, status_text, done, ok_count, error_count)
        except Exception as exc:
            error_count += 1
            try:
                self.item_finished.emit("", "error", str(exc), done, ok_count, error_count)
            except Exception:
                pass
        cancelled = self._cancelled.is_set()
        logger.info(
            "Batch upload finished: ok=%d error=%d skipped=%d cancelled=%s",
            ok_count,
            error_count,
            skipped_count,
            cancelled,
        )
        self.finished.emit(ok_count, error_count, skipped_count, done, cancelled)


def _upload_list_to_folder_legacy(self, target_folder: dict, paths: list[Path], display_prefix: tuple[str, ...] = ()):
    """Upload list of files/folders to target folder with batch dialog for conflicts."""
    if not target_folder or not paths:
        return
    
    project_id = self.current_project_id()
    if not project_id:
        try:
            if hasattr(self, 'status') and hasattr(self.status, 'showMessage'):
                self.status.showMessage(t("upload.no_project"), 5000)
        except Exception:
            pass
        return
    
    folder_id = normalize_id(target_folder.get("id") or target_folder.get("folderId"))
    if not folder_id:
        try:
            if hasattr(self, 'status') and hasattr(self.status, 'showMessage'):
                self.status.showMessage(t("folder.no_project"), 5000)
        except Exception:
            pass
        return
    
    tasks = self._collect_upload_tasks(paths, display_prefix)
    if not tasks:
        try:
            if hasattr(self, 'status') and hasattr(self.status, 'showMessage'):
                self.status.showMessage(t("upload.no_files"), 5000)
        except Exception:
            pass
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
    
    # Если все файлы - обновления, показываем диалог с выбором действий
    new_tasks = [t for t in tasks if not t.get("conflict", False)]
    if not new_tasks:
        pass
    
    # Получаем типы документов
    try:
        types_map = self.api.get_document_types() or {}
    except Exception:
        types_map = {}
    
    # Инициализируем document_type_id для всех задач
    for task in tasks:
        task["document_type_id"] = None

    fallback_doc_type_id: int | None = None
    
    try:
        settings = load_settings()
        last = settings.get("last_document_type_id")
        try:
            last_int = int(str(last).strip()) if last is not None else None
        except Exception:
            last_int = None
    except Exception:
        settings = {}
        last_int = None

    ids: list[int] = []
    if isinstance(types_map, dict):
        for k in types_map.keys():
            try:
                ids.append(int(str(k).strip()))
            except Exception:
                continue
    ids = sorted(set(ids))

    doc_type_id: int | None = None
    if last_int is not None and last_int in ids:
        doc_type_id = last_int
    elif ids:
        doc_type_id = ids[0]

    fallback_doc_type_id = doc_type_id
    
    # Устанавливаем document_type_id для задач без конфликтов
    for task in new_tasks:
        task["document_type_id"] = doc_type_id

    try:
        if isinstance(settings, dict) and doc_type_id is not None:
            settings["last_document_type_id"] = int(doc_type_id)
            save_settings(settings)
    except Exception:
        pass
    
    # Показываем BatchUploadDialog только для загрузки (без выбора типа документа)
    from ..ui.dialogs import BatchUploadDialog
    
    try:
        dlg = BatchUploadDialog(self, total, icon_provider)
    except Exception:
        return
    
    # Добавляем все файлы в диалог
    for task in tasks:
        pseudo = {"type": "file", "name": task["name"], "originalName": task["name"]}
        dlg.add_entry(task["key"], pseudo, task["display"])
        if task["conflict"]:
            dlg.set_status(task["key"], "queued", t("upload.file_exists"))
        else:
            dlg.set_status(task["key"], "queued", t("upload.ready"))
    
    dlg.set_total_conflicts(conflicts_total)
    dlg.show()
    dlg.update_progress(0, total)
    
    # Даем Qt время на отрисовку диалога перед началом загрузки
    from PySide6.QtCore import QTimer
    QTimer.singleShot(50, lambda: None)
    
    folder_cache: dict[tuple[str, ...], int | str] = {tuple(): folder_id}
    ok_count = 0
    fail_count = 0
    processed = 0
    cancelled = False

    apply_all_choice: str | None = None
    conflicts_left = conflicts_total
    
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
                dlg.set_status(task["key"], "error", t("upload.folder_create_failed"))
                processed += 1
                dlg.update_progress(processed, total)
                continue
        
        # Обновляем множество имен после создания каждого файла
        names_set = existing_map.setdefault(folder_parts, self._existing_names_for_folder(parent_id))

        if task.get("conflict", False):
            decision = apply_all_choice
            if decision is None:
                remaining = conflicts_left if conflicts_left > 0 else 1
                decision, apply_all = dlg.ask_conflict(task["key"], task["name"], remaining)
                if decision == "cancel":
                    cancelled = True
                    break
                if apply_all:
                    apply_all_choice = decision
            if decision == "copy":
                new_name = self._unique_remote_name(names_set, task["name"])
                try:
                    names_set.add(new_name.casefold())
                except Exception:
                    pass
                task["name"] = new_name
                task["conflict"] = False
                if task.get("document_type_id") is None and fallback_doc_type_id is not None:
                    task["document_type_id"] = fallback_doc_type_id
                try:
                    dlg.set_name(task["key"], new_name)
                except Exception:
                    pass
            conflicts_left = max(0, conflicts_left - 1)
            if conflicts_left == 0:
                try:
                    dlg.conflict_label.setText("")
                except Exception:
                    pass
        
        status_text = t("upload.updating") if task.get("conflict", False) else t("upload.uploading")
        dlg.set_status(task["key"], "process", status_text)
        dlg.set_current_file(task["display"], "uploading")
        error_detail = ""
        try:
            path = task.get("path")
            if not path or not path.exists():
                fail_count += 1
                dlg.set_status(task["key"], "error", t("upload.file_not_found"))
                processed += 1
                dlg.update_progress(processed, total)
                continue
            
            doc_type = task["document_type_id"] if not task.get("conflict", False) else fallback_doc_type_id
            ok = self.api.upload_file(parent_id, str(path), task["name"], document_type_id=doc_type)
        except Exception as exc:
            ok = False
            error_detail = str(exc)
        
        if ok:
            ok_count += 1
            names_set.add(task["name"].casefold())
            status_text = t("upload.updated") if task.get("conflict", False) else t("upload.uploaded")
            dlg.set_status(task["key"], "ok", status_text)
            
            # Log user action for notification filtering
            try:
                self._log_user_action("upload", file_id=None, file_name=task["name"], folder_id=parent_id)
            except Exception:
                pass
        else:
            fail_count += 1
            tooltip = t("upload.upload_error")
            if error_detail:
                tooltip = f"{tooltip}: {error_detail}"
            dlg.set_status(task["key"], "error", tooltip)
        
        processed += 1
        dlg.update_progress(processed, total)
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
            self.status.showMessage(t("upload.cancelled"), 5000)
        except Exception:
            pass
        return
    
    if fail_count:
        dlg.finish(t("upload.files_uploaded_of", ok=ok_count, total=total))
        try:
            self.status.showMessage(t("upload.files_uploaded_of", ok=ok_count, total=total), 6000)
        except Exception:
            pass
    else:
        dlg.finish(t("upload.files_uploaded", count=ok_count))
        try:
            self.status.showMessage(t("upload.files_uploaded", count=ok_count), 5000)
        except Exception:
            pass


class _BatchUploadGuiController(QObject):
    """Long-lived GUI-thread receiver for batch upload worker signals."""

    def __init__(self, owner, dialog, target_folder, tasks, worker, thread):
        super().__init__(dialog)
        self.owner = owner
        self.dialog = dialog
        self.target_folder = target_folder
        self.tasks = tasks
        self.worker = worker
        self.thread = thread

    @Slot(str, int, int)
    def on_item_started(self, key: str, index: int, total: int) -> None:
        logger.info("GUI received item_started: %s", key)
        self.dialog.set_active(key, True)
        self.dialog.set_status(key, "process", t("upload.uploading"))
        task = next((item for item in self.tasks if item.get("key") == key), None)
        if task is not None:
            self.dialog.set_current_file(task.get("display") or task.get("name") or "", "uploading")

    @Slot(str, str, str, int, int, int)
    def on_item_finished(
        self, key: str, status: str, message: str, done: int, ok_count: int, error_count: int
    ) -> None:
        logger.info("GUI received item_finished: %s status=%s done=%d", key, status, done)
        if key:
            self.dialog.set_status(key, status, message)
            self.dialog.set_active(key, False)
        self.dialog.update_progress(done, len(self.tasks))

    @Slot(str, str)
    def on_item_renamed(self, key: str, name: str) -> None:
        self.dialog.set_name(key, name)

    @Slot(str, str, int)
    def on_conflict_requested(self, key: str, name: str, remaining: int) -> None:
        logger.info("GUI received conflict_requested: %s", key)
        self.dialog.set_total_conflicts(max(1, remaining))
        if self.dialog.was_cancelled():
            self.worker.set_conflict_decision("cancel", False)
            return
        decision, apply_all = self.dialog.ask_conflict(key, name, remaining)
        logger.info("GUI conflict decision: %s decision=%s apply_all=%s", key, decision, apply_all)
        self.worker.set_conflict_decision(decision, apply_all)

    @Slot(int, int, int, int, bool)
    def on_finished(
        self, ok_count: int, error_count: int, skipped_count: int, done: int, cancelled: bool
    ) -> None:
        if cancelled:
            for key, (_, row) in self.dialog._rows.items():
                if row.status in {"queued", "process"}:
                    self.dialog.set_status(key, "cancelled", t("upload.cancelled"))
            self.dialog.finish(t("upload.cancelled"))
        else:
            self.dialog.finish(
                f"Загружено: {ok_count} из {len(self.tasks)}. "
                f"Ошибок: {error_count}. Пропущено: {skipped_count}."
            )
        self.dialog._worker_running = False
        if not cancelled:
            try:
                self.owner.open_folder_node(self.target_folder)
                self.owner.refresh_tree()
            except Exception:
                pass
        self.owner._upload_ok, self.owner._upload_fail = ok_count, error_count
        if hasattr(self.owner, "status"):
            self.owner.status.showMessage(
                t("upload.cancelled")
                if cancelled
                else (
                    f"Загружено: {ok_count} из {len(self.tasks)}. "
                    f"Ошибок: {error_count}. Пропущено: {skipped_count}."
                ),
                5000,
            )


def _upload_list_to_folder(self, target_folder: dict, paths: list[Path], display_prefix: tuple[str, ...] = ()):
    """Start a non-blocking batch upload and keep all widget work in the GUI thread."""
    if not target_folder or not paths:
        return
    project_id = self.current_project_id()
    if not project_id:
        if hasattr(self, "status"):
            self.status.showMessage(t("upload.no_project"), 5000)
        return
    folder_id = normalize_id(target_folder.get("id") or target_folder.get("folderId"))
    if not folder_id:
        if hasattr(self, "status"):
            self.status.showMessage(t("folder.no_project"), 5000)
        return
    selected_document_type_id = _select_upload_document_type(self)
    if selected_document_type_id is None:
        return

    tasks = self._collect_upload_tasks(paths, display_prefix)
    if not tasks:
        if hasattr(self, "status"):
            self.status.showMessage(t("upload.no_files"), 5000)
        return
    for task in tasks:
        task["document_type_id"] = selected_document_type_id

    try:
        from ..ui.dialogs import BatchUploadDialog
        icon_provider = getattr(self, "icon_provider", None)
        dlg = BatchUploadDialog(self, len(tasks), icon_provider)
    except Exception:
        return

    for task in tasks:
        dlg.add_entry(task["key"], {"type": "file", "name": task["name"]}, task["display"])
        dlg.set_status(task["key"], "queued", t("upload.ready"))
    dlg.set_total_conflicts(0)
    dlg.update_progress(0, len(tasks))
    dlg._worker_running = True
    dlg.show()

    thread = QThread(self)
    worker = _BatchUploadWorker(
        self, project_id, folder_id, tasks, selected_document_type_id
    )
    worker.moveToThread(thread)
    dlg._cancel_callback = worker.cancel
    self._batch_upload_thread = thread
    self._batch_upload_worker = worker

    controller = _BatchUploadGuiController(self, dlg, target_folder, tasks, worker, thread)
    dlg._batch_upload_controller = controller
    worker.item_started.connect(controller.on_item_started, Qt.QueuedConnection)
    worker.item_finished.connect(controller.on_item_finished, Qt.QueuedConnection)
    worker.item_renamed.connect(controller.on_item_renamed, Qt.QueuedConnection)
    worker.conflict_requested.connect(controller.on_conflict_requested, Qt.QueuedConnection)
    worker.finished.connect(controller.on_finished, Qt.QueuedConnection)
    worker.finished.connect(thread.quit, Qt.QueuedConnection)
    thread.started.connect(worker.run, Qt.QueuedConnection)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    dlg.open()


def upload_file(self):
    """Upload single file dialog."""
    project_id = self.current_project_id()
    if not project_id:
        try:
            if hasattr(self, 'status') and hasattr(self.status, 'showMessage'):
                self.status.showMessage(t("project.no_project"), 5000)
        except Exception:
            pass
        return
    
    folder = self.current_folder_node()
    if not folder:
        try:
            if hasattr(self, 'status') and hasattr(self.status, 'showMessage'):
                self.status.showMessage(t("upload.no_folder"), 5000)
        except Exception:
            pass
        return
    
    file_path, _ = QFileDialog.getOpenFileName(self, t("upload.select_file"))
    if not file_path:
        return
    
    path = Path(file_path)
    
    # Загружаем через _upload_list_to_folder для показа диалога конфликтов
    self._upload_list_to_folder(folder, [path])


def _build_upload_menu(self) -> QMenu:
    """Build upload submenu."""
    menu = QMenu(t("upload.title"), self)
    
    act_file = menu.addAction(t("upload.files"))
    act_file.triggered.connect(self._action_upload_file)
    
    act_folder = menu.addAction(t("upload.folder"))
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
    
    file_paths, _ = QFileDialog.getOpenFileNames(self, t("upload.select_files"))
    if not file_paths:
        return
    
    paths = [Path(p) for p in file_paths]
    self._upload_list_to_folder(folder, paths)


def _pick_directory_showing_files(self, title: str = "") -> str:
    """Pick directory with file dialog showing files."""
    if not title:
        title = t("upload.select_folder")
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
    
    dir_path = self._pick_directory_showing_files(t("upload.select_folder_to_upload"))
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
