# -*- coding: utf-8 -*-
"""File download operations for Larix Nexus."""

import os
import shutil
import zipfile
from PySide6.QtCore import Qt, QModelIndex
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QTreeWidgetItem
from ..constants import DOWNLOAD_DIR
from ..utils.i18n import t
from ..utils.logging import sync_log
from .helpers import _sanitize_filename, get_title
from .widgets import WaitDialog


def _download_filename(item: dict) -> str:
    """Choose a filename for user-initiated downloads.

    Prefer current name, fall back to original name only if needed.
    """
    file_id = (item or {}).get("id")
    return (
        (item or {}).get("name")
        or (item or {}).get("fileName")
        or (item or {}).get("originalName")
        or f"file_{file_id}.bin"
    )


def ensure_downloaded(self, item: dict) -> str:
    """Ensure file is downloaded locally, return path or empty string."""
    if not item or item.get("type") != "file": 
        return ""
    file_id = item.get("id")
    name = _download_filename(item)
    
    safe = _sanitize_filename(name)
    try:
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        existing = os.path.join(DOWNLOAD_DIR, safe)
        if os.path.exists(existing):
            mode = self._ask_mode(
                title=t("dialog.file_exists", name=safe),
                a_text=t("dialog.replace"),
                b_text=t("dialog.save_copy"),
            )
            if mode == "B":
                safe = self._unique_name(DOWNLOAD_DIR, safe)
            elif mode == "":
                return ""
    except Exception:
        pass

    self._set_progress_visible(True)
    self.progress.setRange(0, 0)
    QApplication.processEvents()
    wait = WaitDialog(t("download.wait_for_download"), self)
    wait.show()
    QApplication.processEvents()

    def _cb(done, total):
        self.progress.setRange(0, 100)
        self.progress.setValue(int(done * 100 / max(1, total)))
        QApplication.processEvents()

    try:
        local_path = self.api.download_file(file_id, safe, progress_cb=_cb)
    except Exception as exc:
        sync_log(
            "Download preparation failed",
            component="download",
            op="ensure_downloaded",
            result="error",
            reason=f"{type(exc).__name__}: download operation failed",
        )
        local_path = ""
    finally:
        self._set_progress_visible(False)
    try:
        wait.set_done(t("download.complete" if local_path else "download.download_failed"))
    except Exception:
        pass
    if not local_path:
        try:
            self.status.showMessage(t("download.download_failed"), 5000)
        except Exception:
            pass
    return local_path or ""


def _copy_file_with_progress(self, src: str, dst: str, on_bytes) -> None:
    """Copy file with progress callback."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        while True:
            buf = fin.read(256 * 1024)
            if not buf:
                break
            fout.write(buf)
            on_bytes(len(buf))


def _unique_name(self, dest_dir: str, name: str) -> str:
    """Generate unique filename (file.txt -> file_копия.txt) if name is taken."""
    base, ext = os.path.splitext(name)
    base = (base or "").strip()
    if not base:
        base = name.strip()
        ext = ""
    if not base:
        base = "file"
    
    if not os.path.exists(os.path.join(dest_dir, name)):
        return name
    
    candidate = f"{base}_копия{ext}"
    idx = 2
    while os.path.exists(os.path.join(dest_dir, candidate)):
        candidate = f"{base}_копия{idx}{ext}"
        idx += 1
    return candidate


def _unique_name_for_batch(self, target_dir: str, name: str, used_names: set[str]) -> str:
    """Generate unique name for batch operations avoiding conflicts."""
    base, ext = os.path.splitext(name)
    base = (base or "").strip()
    if not base:
        base = name.strip()
        ext = ""
    if not base:
        base = "file"
    
    if name not in used_names and not os.path.exists(os.path.join(target_dir, name)):
        used_names.add(name)
        return name
    
    candidate = f"{base}_копия{ext}"
    idx = 2
    while candidate in used_names or os.path.exists(os.path.join(target_dir, candidate)):
        candidate = f"{base}_копия{idx}{ext}"
        idx += 1
    used_names.add(candidate)
    return candidate


def _check_file_conflicts(self, target_folder_id: int | str, filenames: list[str]) -> dict[str, bool]:
    """Check filename conflicts on server in target folder."""
    conflicts = {}
    try:
        existing_names = self._existing_names_for_folder(target_folder_id)
    except Exception:
        return {name: False for name in filenames}
    
    for name in filenames:
        conflicts[name] = name.casefold() in existing_names
    return conflicts


def _prompt_conflict_in_status(self, dest_dir: str, filename: str) -> str:
    """Ask user how to handle file conflict via status bar."""
    mode = self._ask_mode(
        title=t("dialog.file_exists", name=filename),
        a_text=t("dialog.replace"),
        b_text=t("dialog.save_copy"),
    )
    if mode == "B":
        return self._unique_name(dest_dir, filename)
    elif mode == "":
        return None
    return filename


def download_selected(self):
    """Download currently selected file to chosen location."""
    item = self.selected_item()
    if not item or item.get("type") != "file":
        print(f"[INFO] Выберите файл в таблице.")
        return
    _prev = getattr(self, "_force_mode", None)
    self._force_mode = "A"
    try:
        local_path = self.ensure_downloaded(item)
    finally:
        self._force_mode = _prev
    if not local_path:
        print(f"[WARNING] {t('download.download_failed')}")
        return
    save_path, _ = QFileDialog.getSaveFileName(self, t("download.save_as"), os.path.basename(local_path), t("download.all_files"))
    if save_path:
        try:
            shutil.copyfile(local_path, save_path)
            print(f"[INFO] Файл сохранен.")
        except Exception as e:
            print(f"[WARNING] Не удалось сохранить: {e}")


def download_file_plain(self, node: dict):
    """Download file to local directory."""
    if not node or node.get("type") != "file":
        return
    def_name = _sanitize_filename(_download_filename(node))
    save_path, _ = QFileDialog.getSaveFileName(self, t("download.save_as"), def_name, t("download.all_files"))
    if not save_path:
        return
    _prev = getattr(self, "_force_mode", None)
    self._force_mode = "A"
    try:
        local = self.ensure_downloaded(node)
    finally:
        self._force_mode = _prev
    if not local:
        print(f"[WARNING] {t('download.download_failed')}")
        return
    try:
        self.status.showMessage(t("download.loading_file"))
        self._set_progress_visible(True)
        self.progress.setRange(0, 0)
        QApplication.processEvents()
    except Exception:
        pass
    _wait = None
    try:
        _wait = WaitDialog(t("download.downloading_file"), self)
        _wait.show()
        QApplication.processEvents()
    except Exception:
        _wait = None
    ok_msg = False
    try:
        shutil.copyfile(local, save_path)
        ok_msg = True
    except Exception as e:
        try:
            if os.path.exists(save_path) and os.path.getsize(save_path) > 0:
                ok_msg = True
        except Exception:
            ok_msg = False
        if not ok_msg:
            print(f"[WARNING] Не удалось сохранить файл: {e}")
    try:
        self._set_progress_visible(False)
        self.status.clearMessage()
    except Exception:
        pass
    try:
        if _wait:
            _wait.set_done(t("common.done"))
    except Exception:
        pass
    if ok_msg:
        print(f"[INFO] Скачано файлов: 1")


def _download_file_plain_fixed(self, node: dict):
    """Download file with fixed save dialog handling."""
    if not node or node.get("type") != "file":
        return
    def_name = _sanitize_filename(_download_filename(node))
    save_path, _ = QFileDialog.getSaveFileName(self, t("download.save_file"), def_name, t("download.all_files"))
    if not save_path:
        return
    _prev = getattr(self, "_force_mode", None)
    self._force_mode = "A"
    try:
        local = self.ensure_downloaded(node)
    finally:
        self._force_mode = _prev
    if not local:
        print(f"[WARNING] {t('download.download_failed')}")
        return
    try:
        self.status.showMessage(t("common.saving_file_dots"))
        self._set_progress_visible(True)
        self.progress.setRange(0, 0)
        QApplication.processEvents()
    except Exception:
        pass
    _wait = None
    try:
        _wait = WaitDialog(t("common.saving_file"), self)
        _wait.show()
        QApplication.processEvents()
    except Exception:
        _wait = None
    try:
        shutil.copyfile(local, save_path)
        ok_msg = True
    except Exception as e:
        ok_msg = False
        print(f"[WARNING] Не удалось сохранить: {e}")
    finally:
        try:
            self._set_progress_visible(False)
            self.status.clearMessage()
        except Exception:
            pass
        try:
            if _wait:
                _wait.set_done(t("common.done"))
        except Exception:
            pass
    if ok_msg:
        print(f"[INFO] Файл сохранён.")


def download_file_as_zip(self, node: dict):
    """Download single file as ZIP archive."""
    if not node or node.get("type") != "file":
        return
    name = _download_filename(node)
    name = _sanitize_filename(name)
    base, _ = os.path.splitext(name)
    save_path, _ = QFileDialog.getSaveFileName(self, t("zip.save_title"), f"{base}.zip", f"{t('download.all_files')};;ZIP (*.zip)")
    if not save_path:
        return
    wait = None
    try:
        try:
            wait = WaitDialog(t("download.creating_zip"), self)
            wait.show()
            QApplication.processEvents()
        except Exception:
            wait = None
        with zipfile.ZipFile(save_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            with zf.open(name, 'w') as zentry:
                if not self.api.write_file_to(node.get('id'), zentry):
                    if wait:
                        wait.set_done(t("download.download_failed"))
                    else:
                        print(f"[WARNING] {t('download.download_failed')}")
                    return
        if wait:
            wait.set_done(t("download.zip_created"))
        else:
            print(f"[INFO] ZIP-архив сформирован.")
    except Exception as e:
        print(f"[WARNING] Не удалось собрать архив: {e}")


def download_folder_as_zip(self, node):
    """Download folder as ZIP archive."""
    if isinstance(node, QTreeWidgetItem):
        node = node.data(0, Qt.UserRole)
    if not isinstance(node, dict):
        node = self.current_folder_node()
    typ = str((node or {}).get("type", "")).lower()
    if typ not in ("folder", "dir", "directory", "папка"):
        print("[Dialog skipped]")
        return
    save_path, _ = QFileDialog.getSaveFileName(self, t("zip.save_title"), f"{get_title(node)}.zip", f"{t('download.all_files')};;ZIP (*.zip)")
    if not save_path:
        return
    try:
        self._zip_folder_to_path(node, save_path)
        print("[Dialog skipped]")
    except Exception as e:
        print("[Dialog skipped]")


def download_folder_plain(self, node):
    """Download folder as plain directory structure."""
    if isinstance(node, QTreeWidgetItem):
        node = node.data(0, Qt.UserRole)
    if not isinstance(node, dict):
        node = self.current_folder_node()
    typ = str((node or {}).get("type", "")).lower()
    if typ not in ("folder", "dir", "directory", "папка"):
        return
    dest_dir = self._pick_directory_showing_files(t("structure.where_save"))
    if not dest_dir:
        return
    self._set_progress_visible(True)
    self.progress.setRange(0, 0)
    QApplication.processEvents()
    try:
        self._copy_folder_into(node, dest_dir)
        print(f"[INFO] Копирование завершено.")
    finally:
        self._set_progress_visible(False)


def _zip_folder_into(self, node: dict, zf: zipfile.ZipFile, arc_prefix: str = ""):
    """Recursively add folder contents to ZIP archive."""
    def descend(n: dict, rel: str = ""):
        if not isinstance(n, dict):
            return
        typ = n.get("type", "")
        name = n.get("name") or n.get("title") or "untitled"
        safe_name = _sanitize_filename(name)
        new_rel = f"{rel}/{safe_name}" if rel else safe_name
        
        if typ == "file":
            try:
                arc_name = f"{arc_prefix}/{new_rel}" if arc_prefix else new_rel
                with zf.open(arc_name, 'w') as zentry:
                    self.api.write_file_to(n.get('id'), zentry)
            except Exception:
                pass
        elif typ in ("folder", "dir", "directory", "папка"):
            children = n.get("children") or []
            if not children:
                arc_name = f"{arc_prefix}/{new_rel}/" if arc_prefix else f"{new_rel}/"
                zf.writestr(arc_name, "")
            for ch in children:
                descend(ch, new_rel)
    
    descend(node)


def _copy_folder_into(self, node: dict, dest_dir: str, into_name: str | None = None):
    """Recursively copy folder contents to local directory."""
    def descend(n: dict, rel: str = ""):
        if not isinstance(n, dict):
            return
        typ = n.get("type", "")
        name = n.get("name") or n.get("title") or "untitled"
        safe_name = _sanitize_filename(name)
        new_rel = f"{rel}/{safe_name}" if rel else safe_name
        
        if typ == "file":
            here = dest_dir
            if rel:
                here = os.path.join(dest_dir, rel)
                os.makedirs(here, exist_ok=True)
            fname = safe_name
            local = self.ensure_downloaded(n)
            if local and os.path.exists(local):
                fname = self._unique_name(here, fname)
                try:
                    shutil.copyfile(local, os.path.join(here, fname))
                except Exception:
                    pass
        elif typ in ("folder", "dir", "directory", "папка"):
            children = n.get("children") or []
            for ch in children:
                descend(ch, new_rel)
    
    descend(node)
    return dest_dir


def _zip_add_empty_dir(self, zf: zipfile.ZipFile, arc_dir: str):
    """Add empty directory entry to ZIP."""
    arc_dir = arc_dir.rstrip("/")
    zf.writestr(f"{arc_dir}/", "")


def inject_download_operations_to_main_window(MainWindowClass):
    """Inject download operations into MainWindow class."""
    MainWindowClass.ensure_downloaded = ensure_downloaded
    MainWindowClass._copy_file_with_progress = _copy_file_with_progress
    MainWindowClass._unique_name = _unique_name
    MainWindowClass._unique_name_for_batch = _unique_name_for_batch
    MainWindowClass._check_file_conflicts = _check_file_conflicts
    MainWindowClass._prompt_conflict_in_status = _prompt_conflict_in_status
    MainWindowClass.download_selected = download_selected
    MainWindowClass.download_file_plain = download_file_plain
    MainWindowClass._download_file_plain_fixed = _download_file_plain_fixed
    MainWindowClass.download_file_as_zip = download_file_as_zip
    MainWindowClass.download_folder_as_zip = download_folder_as_zip
    MainWindowClass.download_folder_plain = download_folder_plain
    MainWindowClass._zip_folder_into = _zip_folder_into
    MainWindowClass._copy_folder_into = _copy_folder_into
    MainWindowClass._zip_add_empty_dir = _zip_add_empty_dir
