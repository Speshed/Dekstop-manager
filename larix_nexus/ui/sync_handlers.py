# -*- coding: utf-8 -*-
"""Sync-related UI handlers injected into MainWindow.

This keeps main_window.py smaller without changing runtime behavior.
"""

from __future__ import annotations

import os
from datetime import datetime

from PySide6 import QtCore
from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import QMessageBox

from larix_nexus.utils.helpers import normalize_id
from larix_nexus.utils.logging import sync_log
from larix_nexus.utils.i18n import t


_SYNC_TRANSFER_THROTTLE_SEC = 0.2

_CONN_RESET_UPLOAD_USER_MSG = (
    "Соединение было разорвано во время загрузки. Файл будет повторён при следующей синхронизации."
)


def _humanize_connection_reset_sync_error_text(text: str) -> str:
    """Avoid showing raw WinError / tuples for common upload connection resets."""
    if not text:
        return str(text)
    s = str(text)
    low = s.lower()
    compact = low.replace(" ", "")
    if "10054" in s or "connectionreseterror" in compact or "connectionreset" in compact:
        return _CONN_RESET_UPLOAD_USER_MSG
    if "connection aborted" in low:
        return _CONN_RESET_UPLOAD_USER_MSG
    if ("удаленный хост" in low or "удалённый хост" in low) and ("разорвал" in low or "10054" in s):
        return _CONN_RESET_UPLOAD_USER_MSG
    return s


_LOCAL_ROOT_UNAVAILABLE = frozenset({
    "local_path_not_found",
    "local_path_not_directory",
    "local_root_not_found",
    "local_root_not_directory",
})


def _local_root_unavailable_message(local_root: str) -> str:
    return t("sync.local_root_unavailable", path=local_root or "?")


def _is_local_root_unavailable(result: dict, mapping_errors: list | None = None) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("safety_abort"):
        return True
    errs = mapping_errors if mapping_errors is not None else (result.get("mapping_errors") or [])
    return any(e in _LOCAL_ROOT_UNAVAILABLE for e in errs)


def _format_sync_summary(
    *,
    title_key: str,
    folder_title: str = "",
    uploaded: int = 0,
    downloaded: int = 0,
    deleted_cloud: int = 0,
    deleted_local: int = 0,
    unavailable: int = 0,
    err_count: int = 0,
) -> str:
    parts = []
    if uploaded > 0:
        parts.append(t("sync.summary.uploaded", n=uploaded))
    if downloaded > 0:
        parts.append(t("sync.summary.downloaded", n=downloaded))
    if deleted_cloud > 0:
        parts.append(t("sync.summary.deleted_cloud", n=deleted_cloud))
    if deleted_local > 0:
        parts.append(t("sync.summary.deleted_local", n=deleted_local))
    if unavailable > 0:
        parts.append(t("sync.summary.unavailable", n=unavailable))
    if err_count > 0:
        parts.append(t("sync.summary.errors", n=err_count))

    if title_key == "sync.summary.manual_title":
        title = t(title_key, folder=folder_title or "?")
    else:
        title = t(title_key)

    if parts:
        return f"{title} · {' · '.join(parts)}"
    return title


@QtCore.Slot()
def _on_auto_sync_started(self):
    try:
        if hasattr(self, "_begin_sync_status"):
            self._begin_sync_status(t("status.sync_folders_running"))
        else:
            self.progress.setVisible(True)
            self.progress.setRange(0, 0)
            self.status.showMessage(t("status.sync_folders_running"))
    except Exception:
        pass


@QtCore.Slot()
def _on_auto_sync_finished(self):
    try:
        if hasattr(self, "_end_sync_status"):
            # Keep brief, do not clear immediately if another sync is running.
            self._end_sync_status(t("status.sync_finished") if hasattr(t, '__call__') else "Синхронизация завершена", 4000)
        else:
            self.progress.setVisible(False)
            self.progress.setRange(0, 0)
            self.status.clearMessage()
    except Exception:
        pass


@QtCore.Slot(list)
def _on_auto_sync_result(self, results: list):
    """Structured summary for periodic auto sync."""
    try:
        if not isinstance(results, list):
            return
        uploaded = 0
        downloaded = 0
        deleted_cloud = 0
        deleted_local = 0
        err_count = 0
        ok_folders = 0
        unavailable = 0
        refresh_folder_ids: set[str] = set()
        for r in results:
            if not isinstance(r, dict):
                continue
            if r.get("success"):
                ok_folders += 1
            mapping_errors = r.get("mapping_errors") or []
            if _is_local_root_unavailable(r, mapping_errors):
                unavailable += 1
                try:
                    sync_log(
                        "AUTO_SYNC local root unavailable; cloud preserved",
                        component="UI",
                        op="auto_sync_result",
                        result="skip",
                        extra=f"folder_id={r.get('folder_id')} local_root={r.get('local_root')!r} mapping_errors={mapping_errors} reason={r.get('reason')}",
                    )
                except Exception:
                    pass
            stats = r.get("stats") if isinstance(r.get("stats"), dict) else {}
            uploaded += int((stats or {}).get("uploaded", 0) or 0)
            downloaded += int((stats or {}).get("downloaded", 0) or 0)
            deleted_cloud += int((stats or {}).get("deleted_cloud", 0) or 0)
            deleted_local += int((stats or {}).get("deleted_local", 0) or 0)
            try:
                changed = (
                    int((stats or {}).get("uploaded", 0) or 0)
                    + int((stats or {}).get("downloaded", 0) or 0)
                    + int((stats or {}).get("deleted_local", 0) or 0)
                    + int((stats or {}).get("deleted_cloud", 0) or 0)
                    + int((stats or {}).get("created_dirs_local", 0) or 0)
                    + int((stats or {}).get("created_dirs_cloud", 0) or 0)
                )
                if r.get("success") and changed > 0:
                    fid = normalize_id(r.get("folder_id"))
                    if fid:
                        refresh_folder_ids.add(fid)
            except Exception:
                pass
            try:
                errs = (stats or {}).get("errors")
                if isinstance(errs, list):
                    err_count += len(errs)
            except Exception:
                pass
            try:
                errs2 = r.get("errors")
                if isinstance(errs2, list):
                    err_count += 0  # avoid double-counting; stats.errors preferred
            except Exception:
                pass

        # Keep it quiet if nothing happened and no errors.
        if (uploaded + downloaded + deleted_cloud + deleted_local) <= 0 and err_count <= 0 and unavailable <= 0:
            return

        for fid in refresh_folder_ids:
            try:
                self._refresh_synced_folder(fid)
            except Exception:
                pass

        msg = _format_sync_summary(
            title_key="sync.summary.auto_title",
            uploaded=uploaded,
            downloaded=downloaded,
            deleted_cloud=deleted_cloud,
            deleted_local=deleted_local,
            unavailable=unavailable,
            err_count=err_count,
        )
        try:
            if hasattr(self, "_show_status_message"):
                self._show_status_message(msg, 6000 if not err_count else 8000, owner="sync", force=bool(err_count))
            else:
                self.status.showMessage(msg, 6000 if not err_count else 8000)
        except Exception:
            pass
    except Exception:
        pass


@QtCore.Slot(str, str, int)
def _on_sync_item(self, action: str, rel: str, folder_id: int | str):
    # Update status line with current file being synced; keep busy dots if visible
    try:
        try:
            setattr(self, "_sync_transfer_progress_last_ts", -1e9)
        except Exception:
            pass
        act_ru = "Загрузка" if action == "download" else ("Выгрузка" if action == "upload" else action)
        folder_title = ""
        try:
            it = getattr(self, "folder_item_by_id", {}).get(normalize_id(folder_id))
            if it is not None:
                try:
                    folder_title = str(it.text(0))
                except Exception:
                    folder_title = ""
        except Exception:
            folder_title = ""
        if not folder_title:
            folder_title = f"ID {normalize_id(folder_id)}"
        msg = f"{act_ru}: {rel} (папка {folder_title})"
        # ensure indicator is shown while items flow
        try:
            if hasattr(self, "_begin_sync_status") and int(getattr(self, "_active_sync_count", 0) or 0) <= 0:
                self._begin_sync_status(msg)
            else:
                try:
                    self.progress.setVisible(True)
                    self.progress.setRange(0, 0)
                except Exception:
                    pass
                if hasattr(self, "_update_sync_status"):
                    self._update_sync_status(msg)
                elif hasattr(self, "_show_status_message"):
                    self._show_status_message(msg, owner="sync")
                else:
                    self.status.showMessage(msg)
        except Exception:
            pass
    except Exception:
        pass


@QtCore.Slot(str, str, str, int, int)
def _on_sync_transfer_progress(self, action: str, rel: str, folder_id: str, done: int, total: int):
    import time

    try:
        now = time.monotonic()
        last = float(getattr(self, "_sync_transfer_progress_last_ts", -1e9))
        done_i = int(done or 0)
        total_i = int(total or 0)
        is_complete = total_i > 0 and done_i >= total_i
        if not is_complete:
            if total_i > 0:
                if done_i < total_i and (now - last) < _SYNC_TRANSFER_THROTTLE_SEC:
                    return
            elif (now - last) < _SYNC_TRANSFER_THROTTLE_SEC:
                return
        setattr(self, "_sync_transfer_progress_last_ts", now)
    except Exception:
        pass

    try:
        verb = t("status.sync_verb_upload") if action == "upload" else t("status.sync_verb_download")
    except Exception:
        verb = "upload" if action == "upload" else "download"

    def _fmt_mb(n: int) -> str:
        v = max(0, int(n)) / 1048576.0
        s = f"{v:.1f}"
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return s or "0"

    done_mb = _fmt_mb(done_i)
    try:
        if total_i > 0:
            total_mb = _fmt_mb(total_i)
            if action == "upload":
                prog = t("status.sync_mb_sent_pair", done=done_mb, total=total_mb)
            else:
                prog = t("status.sync_mb_received_pair", done=done_mb, total=total_mb)
        else:
            if action == "upload":
                prog = t("status.sync_mb_sent_only", done=done_mb)
            else:
                prog = t("status.sync_mb_received_only", done=done_mb)
    except Exception:
        prog = done_mb + (f" / {_fmt_mb(total_i)} МБ" if total_i > 0 else " МБ")

    msg = f"{verb}: {rel} — {prog}"

    try:
        if int(getattr(self, "_active_sync_count", 0) or 0) > 0 and hasattr(self, "_update_sync_status"):
            self._update_sync_status(msg)
        elif hasattr(self, "_show_status_message"):
            self._show_status_message(msg, owner="sync")
        else:
            self.status.showMessage(msg)
    except Exception:
        pass


# --- Thread-safe UI slots for initial sync ---
@QtCore.Slot()
def _on_sync_started(self):
    try:
        base = getattr(self, "_sync_path", "")
        prefix = f"Синхронизация: {base} — " if base else "Синхронизация: "
        msg = prefix + "подсчет файлов…"
        # initial sync is begun in _start_initial_sync to lock the status line early
        if hasattr(self, "_update_sync_status"):
            self._update_sync_status(msg)
        elif hasattr(self, "_show_status_message"):
            self._show_status_message(msg, owner="sync")
        else:
            self.progress.setVisible(True)
            self.progress.setRange(0, 0)
            self.status.showMessage(msg)
    except Exception:
        pass


@QtCore.Slot(int)
def _on_sync_total(self, total: int):
    try:
        self.progress.setRange(0, max(1, int(total)))
        base = getattr(self, "_sync_path", "")
        prefix = f"Синхронизация: {base} — " if base else "Синхронизация: "
        msg = prefix + f"найдено файлов: {int(total)}"
        if hasattr(self, "_update_sync_status"):
            self._update_sync_status(msg)
        elif hasattr(self, "_show_status_message"):
            self._show_status_message(msg, owner="sync")
        else:
            self.status.showMessage(msg)
    except Exception:
        pass


@QtCore.Slot(int, int, str)
def _on_sync_progress(self, done: int, total: int, cur: str):
    try:
        self.progress.setValue(int(done))
        pct = int(100 * done / max(1, total))
        name = cur or ""
        base = getattr(self, "_sync_path", "")
        prefix = f"Синхронизация: {base} — " if base else "Синхронизация: "
        msg = prefix + f"{pct}% — {name} ({done}/{total})"
        if hasattr(self, "_update_sync_status"):
            self._update_sync_status(msg)
        elif hasattr(self, "_show_status_message"):
            self._show_status_message(msg, owner="sync")
        else:
            self.status.showMessage(msg)
    except Exception:
        pass


@QtCore.Slot(str)
def _on_sync_error(self, msg: str):
    try:
        disp = _humanize_connection_reset_sync_error_text(str(msg))
        txt = t("status.sync_error", error=disp)
        if hasattr(self, "_show_status_message"):
            # Errors must be visible even during sync.
            self._show_status_message(txt, 8000, owner="sync", force=True)
        else:
            self.status.showMessage(txt, 8000)
    except Exception:
        pass


@QtCore.Slot(bool, int)
def _on_sync_finished(self, ok: bool, errors: int):
    try:
        sync_log("_on_sync_finished: Called with ok={}, errors={}", ok, errors)
    except Exception:
        pass

    # Get synced folder_id for targeted refresh
    synced_folder_id = None
    if ok:
        try:
            worker = getattr(self, "_sync_worker", None)
            synced_folder_id = normalize_id(getattr(worker, "folder_id", "")) if worker else None
            sync_log("_on_sync_finished: synced_folder_id={}", synced_folder_id)
        except Exception:
            pass

    # Clear status-bar cancel handler (single shared cancel chip)
    try:
        if hasattr(self, "_set_progress_cancel_handler"):
            self._set_progress_cancel_handler(None)
    except Exception:
        pass

    try:
        if ok:
            base = getattr(self, "_sync_path", "")
            msg = f"Синхронизация завершена: {base}" if base else "Синхронизация завершена"
            if hasattr(self, "_end_sync_status"):
                self._end_sync_status(msg, 4000)
            elif hasattr(self, "_show_status_message"):
                self._show_status_message(msg, 4000, owner="sync")
            else:
                self.status.showMessage(msg, 4000)
            # Mark initial sync complete and start periodic polling now (30 min)
            try:
                worker = getattr(self, "_sync_worker", None)
                fid = normalize_id(getattr(worker, "folder_id", ""))
                if fid and hasattr(self, "sync2"):
                    self.sync2.set_initial_ok(fid, True)
                    # Save initial snapshot for safe deletion semantics
                    try:
                        fresh = self.api.get_folder_details(fid, force=True)
                        if isinstance(fresh, dict):
                            cur_cloud = self.sync2._collect_cloud_files(fresh, "", force_fresh=True)
                            self.sync2._save_last_cloud_set(fid, cur_cloud)
                    except Exception:
                        pass
            except Exception:
                pass
            if hasattr(self, "sync2") and not self.sync2.timer.isActive():
                self.sync2.schedule_next_half_hour()
            
            # Refresh files table after sync completes
            try:
                if synced_folder_id:
                    self._refresh_synced_folder(synced_folder_id)
                else:
                    self.soft_refresh_and_restore_view()
            except Exception:
                pass
        else:
            base = getattr(self, "_sync_path", "")
            msg = f"Синхронизация прервана: {base}" if base else "Синхронизация прервана"
            if hasattr(self, "_end_sync_status"):
                # Force visibility (also ends lock for this worker only).
                self._end_sync_status(msg, 8000)
                try:
                    if hasattr(self, "_show_status_message"):
                        self._show_status_message(msg, 8000, owner="sync", force=True)
                except Exception:
                    pass
            elif hasattr(self, "_show_status_message"):
                self._show_status_message(msg, 8000, owner="sync", force=True)
            else:
                self.status.showMessage(msg, 8000)
            # Show expanded error dialog with details, avoid truncation
            try:
                mb = QMessageBox(self)
                mb.setWindowTitle(t("sync.error_title"))
                mb.setText(msg)
                if getattr(self, "_sync_worker", None) is not None:
                    errs = getattr(self._sync_worker, "_errors", []) or []
                    if errs:
                        mb.setInformativeText(
                            "\n".join([_humanize_connection_reset_sync_error_text(str(e)) for e in errs[:5]])
                        )
                mb.setStandardButtons(QMessageBox.Ok)
                mb.setWordWrap(True)
                try:
                    fm = mb.fontMetrics()
                    longest = 0
                    for s in ((mb.text() or "") + "\n" + (mb.informativeText() or "")).split("\n"):
                        w = fm.horizontalAdvance(s)
                        if w > longest:
                            longest = w
                    mb.setMinimumWidth(max(320, min(800, longest + 180)))
                    mb.adjustSize()
                except Exception:
                    pass
                mb.exec()
            except Exception:
                pass
    except Exception:
        pass

    # Write error log if any
    try:
        worker = getattr(self, "_sync_worker", None)
        if errors > 0 and worker is not None and getattr(worker, "_errors", None):
            path = getattr(worker, "local_path", "")
            if path:
                log_path = os.path.join(path, "_sync_errors.log")
                with open(log_path, "a", encoding="utf-8", errors="ignore") as lf:
                    lf.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Ошибок: {errors}\n")
                    for line in worker._errors:
                        try:
                            lf.write(str(line) + "\n")
                        except Exception:
                            pass
    except Exception:
        pass

    # Tidy thread safely (from GUI thread)
    try:
        th = getattr(self, "_sync_thread", None)
        if isinstance(th, QThread):
            try:
                if QtCore.QThread.currentThread() is not th:
                    th.quit(); th.wait(1500)
                else:
                    th.quit()
            except Exception:
                pass
    except Exception:
        pass
    try:
        self._sync_thread = None
        self._sync_worker = None
    except Exception:
        pass


# --- Immediate sync (on-demand) ---
    try:
        self._release_file_operation("sync")
    except Exception:
        pass


@QtCore.Slot()
def _on_sync_now_started(self):
    try:
        base = getattr(self, "_sync_now_path", "")
        prefix = f"Синхронизация: {base} — " if base else "Синхронизация: "
        msg = prefix + "запуск…"
        if hasattr(self, "_begin_sync_status"):
            self._begin_sync_status(msg)
        elif hasattr(self, "_show_status_message"):
            try:
                self.progress.setVisible(True)
                self.progress.setRange(0, 0)
            except Exception:
                pass
            self._show_status_message(msg, owner="sync")
        else:
            self.progress.setVisible(True)
            self.progress.setRange(0, 0)
            self.status.showMessage(msg)
    except Exception:
        pass


@QtCore.Slot(bool, str)
def _on_sync_now_finished(self, ok: bool, folder_id: str = ""):
    try:
        base = getattr(self, "_sync_now_path", "")
        if ok:
            msg = (f"Синхронизация завершена: {base}" if base else "Синхронизация завершена")
            if hasattr(self, "_end_sync_status"):
                self._end_sync_status(msg, 4000)
            elif hasattr(self, "_show_status_message"):
                self._show_status_message(msg, 4000, owner="sync")
            else:
                self.status.showMessage(msg, 4000)
            # Обновить только синхронизированную папку
            try:
                if folder_id:
                    self._refresh_synced_folder(folder_id)
                else:
                    self.soft_refresh_and_restore_view()
            except Exception:
                pass
        else:
            msg = (f"Синхронизация завершилась с ошибкой: {base}" if base else "Синхронизация завершилась с ошибкой")
            if hasattr(self, "_end_sync_status"):
                self._end_sync_status(msg, 8000)
                try:
                    if hasattr(self, "_show_status_message"):
                        self._show_status_message(msg, 8000, owner="sync", force=True)
                except Exception:
                    pass
            elif hasattr(self, "_show_status_message"):
                self._show_status_message(msg, 8000, owner="sync", force=True)
            else:
                self.status.showMessage(msg, 8000)
    except Exception:
        pass

    # cleanup most recent thread (legacy); per-thread cleanup is also attached
    try:
        th = getattr(self, "_sync_now_thread", None)
        tracked = getattr(self, "_sync_now_threads", set())
        if isinstance(th, QThread) and th not in tracked:
            try:
                if QtCore.QThread.currentThread() is not th:
                    th.quit(); th.wait(1500)
                else:
                    th.quit()
            except Exception:
                pass
    except Exception:
        pass
    try:
        self._sync_now_thread = None
        self._sync_now_worker = None
    except Exception:
        pass


    try:
        self._release_file_operation("sync")
    except Exception:
        pass


@QtCore.Slot(dict)
def _on_sync_now_result(self, result: dict):
    """Structured per-folder sync result (manual sync-now / sync-all)."""
    try:
        if not isinstance(result, dict):
            return

        fid = normalize_id(result.get("folder_id") or "")
        project_id = result.get("project_id")
        local_root = str(result.get("local_root") or "")

        # Folder title for user-facing messages
        folder_title = ""
        try:
            it = getattr(self, "folder_item_by_id", {}).get(fid)
            if it is not None:
                folder_title = str(it.text(0) or "")
        except Exception:
            folder_title = ""
        if not folder_title:
            folder_title = f"ID {fid}" if fid else "(неизвестная папка)"

        # Mapping validation errors / safety abort for missing local root
        mapping_errors = result.get("mapping_errors") or []
        if _is_local_root_unavailable(result, mapping_errors):
            msg = _local_root_unavailable_message(local_root)
            try:
                if hasattr(self, "_show_status_message"):
                    self._show_status_message(msg, 8000, owner="sync", force=True)
                else:
                    self.status.showMessage(msg, 8000)
            except Exception:
                pass
            try:
                sync_log(
                    "MANUAL_SYNC local root unavailable; cloud preserved",
                    component="UI",
                    op="sync_result",
                    result="skip",
                    extra=f"folder_id={fid} project_id={project_id} local_root={local_root!r} mapping_errors={mapping_errors} safety_abort={result.get('safety_abort')} reason={result.get('reason')}",
                )
            except Exception:
                pass
            try:
                QMessageBox.warning(self, t("common.error"), msg)
            except Exception:
                pass
            return

        if mapping_errors:
            msg = f"Синхронизация не выполнена для {folder_title}: некорректная настройка ({', '.join([str(e) for e in mapping_errors])})."
            try:
                if hasattr(self, "_show_status_message"):
                    self._show_status_message(msg, 8000, owner="sync", force=True)
                else:
                    self.status.showMessage(msg, 8000)
            except Exception:
                pass
            try:
                sync_log("MANUAL_SYNC mapping invalid", component="UI", op="sync_result", result="fail", extra=f"folder_id={fid} project_id={project_id} local_root={local_root!r} mapping_errors={mapping_errors}")
            except Exception:
                pass
            try:
                QMessageBox.warning(self, t("common.error"), msg)
            except Exception:
                pass
            return

        # Guard-blocked flow (manual only): ask for confirmation then rerun with allow_mass_delete=True
        if result.get("blocked_by_guard"):
            guard = result.get("guard") or {}
            delete_count = int(guard.get("delete_count") or 0)
            total_files = int(guard.get("total_files") or 0)
            delete_percent = float(guard.get("delete_percent") or 0.0)
            sample_paths = guard.get("sample_paths") or []

            warn = (
                f"Массовое удаление заблокировано защитой для {folder_title}.\n\n"
                f"Планируется удалить {delete_count} из {total_files} файлов ({delete_percent:.1f}%).\n\n"
                f"Чтобы продолжить, подтвердите массовое удаление."
            )
            details = "\n".join([str(p) for p in sample_paths if p])
            if details:
                details = "Примеры путей:\n" + details

            try:
                sync_log(
                    "MANUAL_SYNC blocked_by_guard",
                    component="UI",
                    op="sync_result",
                    result="block",
                    extra=f"folder_id={fid} project_id={project_id} local_root={local_root!r} delete_count={delete_count} total_files={total_files} delete_percent={delete_percent:.1f} sample={sample_paths}",
                )
            except Exception:
                pass

            mb = QMessageBox(self)
            mb.setIcon(QMessageBox.Warning)
            mb.setWindowTitle(t("sync.mass_delete_title") if hasattr(t, '__call__') else "Массовое удаление")
            mb.setText(warn)
            if details:
                mb.setInformativeText(details)
            mb.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            mb.setDefaultButton(QMessageBox.No)

            confirmed = False
            try:
                confirmed = (mb.exec() == QMessageBox.Yes)
            except Exception:
                confirmed = False

            if not confirmed:
                try:
                    txt = f"Удаление {delete_count} файлов в облаке заблокировано защитой для {folder_title}"
                    if hasattr(self, "_show_status_message"):
                        self._show_status_message(txt, 8000, owner="sync", force=True)
                    else:
                        self.status.showMessage(txt, 8000)
                except Exception:
                    pass
                return

            # Rerun this folder sync once with guard bypass
            try:
                txt = f"Подтверждено. Выполняю массовое удаление для {folder_title}…"
                if hasattr(self, "_show_status_message"):
                    self._show_status_message(txt, 5000, owner="sync", force=True)
                else:
                    self.status.showMessage(txt, 5000)
            except Exception:
                pass
            try:
                self._trigger_sync_now(fid, allow_mass_delete=True, sync_mode="manual")
            except Exception as e:
                try:
                    sync_log("Failed to re-run sync with allow_mass_delete", component="UI", op="sync_result", result="fail", extra=f"folder_id={fid} err={e}")
                except Exception:
                    pass
            return

        # Normal success/failure messaging
        stats = result.get("stats") if isinstance(result.get("stats"), dict) else {}
        uploaded = int((stats or {}).get("uploaded", 0) or 0)
        downloaded = int((stats or {}).get("downloaded", 0) or 0)
        deleted_cloud = int((stats or {}).get("deleted_cloud", 0) or 0)
        deleted_local = int((stats or {}).get("deleted_local", 0) or 0)

        if result.get("success"):
            msg = _format_sync_summary(
                title_key="sync.summary.manual_title",
                folder_title=folder_title,
                uploaded=uploaded,
                downloaded=downloaded,
                deleted_cloud=deleted_cloud,
                deleted_local=deleted_local,
            )
            try:
                if hasattr(self, "_show_status_message"):
                    self._show_status_message(msg, 6000, owner="sync")
                else:
                    self.status.showMessage(msg, 6000)
            except Exception:
                pass
            return

        # Failed (non-guard)
        errors = result.get("errors") or []
        if result.get("safety_abort"):
            msg = _local_root_unavailable_message(local_root)
            try:
                if hasattr(self, "_show_status_message"):
                    self._show_status_message(msg, 8000, owner="sync", force=True)
                else:
                    self.status.showMessage(msg, 8000)
            except Exception:
                pass
            try:
                sync_log(
                    "MANUAL_SYNC safety abort; cloud preserved",
                    component="UI",
                    op="sync_result",
                    result="skip",
                    extra=f"folder_id={fid} project_id={project_id} local_root={local_root!r} reason={result.get('reason')}",
                )
            except Exception:
                pass
            try:
                QMessageBox.warning(self, t("common.error"), msg)
            except Exception:
                pass
            return

        err_raw = str(errors[0]) if isinstance(errors, list) and errors else "Ошибка синхронизации"
        err_txt = _humanize_connection_reset_sync_error_text(err_raw)
        msg = f"Синхронизация завершилась с ошибкой для {folder_title}: {err_txt}"
        try:
            if hasattr(self, "_show_status_message"):
                self._show_status_message(msg, 8000, owner="sync", force=True)
            else:
                self.status.showMessage(msg, 8000)
        except Exception:
            pass
        try:
            sync_log("MANUAL_SYNC failed", component="UI", op="sync_result", result="fail", extra=f"folder_id={fid} project_id={project_id} local_root={local_root!r} err={err_txt}")
        except Exception:
            pass
        try:
            QMessageBox.warning(self, t("common.error"), msg)
        except Exception:
            pass
    except Exception:
        pass


@QtCore.Slot()
def _on_sync_all_clicked(self):
    try:
        mgr = getattr(self, "sync2", None)
        if not mgr or not getattr(mgr, "map", None):
            return
        try:
            # Don't overwrite sync status if workers are already running.
            if hasattr(self, "_show_status_message"):
                self._show_status_message(t("status.sync_all_started"), 3000, owner="sync")
            else:
                self.status.showMessage(t("status.sync_all_started"), 3000)
        except Exception:
            pass
        # Run each folder's sync in its own worker to avoid blocking UI
        started = 0
        skipped = 0
        for fid, cfg in list(mgr.map.items()):
            try:
                fid_norm = normalize_id(fid)
            except Exception:
                fid_norm = str(fid or "")

            lp = ""
            pid = None
            initial_ok = False
            try:
                lp = str((cfg or {}).get("local_path") or "").strip()
                pid = (cfg or {}).get("project_id")
                initial_ok = bool((cfg or {}).get("initial_ok", False))
            except Exception:
                lp = ""

            mapping_errors = []
            if not lp:
                mapping_errors.append("local_path_missing")
            else:
                try:
                    if not os.path.exists(lp):
                        mapping_errors.append("local_path_not_found")
                    elif not os.path.isdir(lp):
                        mapping_errors.append("local_path_not_directory")
                except Exception:
                    mapping_errors.append("local_path_probe_failed")
            try:
                if not pid or str(pid).strip() in ("", "0"):
                    mapping_errors.append("project_id_missing")
            except Exception:
                mapping_errors.append("project_id_missing")
            if not initial_ok:
                mapping_errors.append("initial_ok_false")
            try:
                if fid_norm in getattr(mgr, "_busy_folders", set()):
                    mapping_errors.append("folder_busy")
            except Exception:
                pass

            if mapping_errors:
                skipped += 1
                try:
                    if any(e in _LOCAL_ROOT_UNAVAILABLE for e in mapping_errors):
                        msg = _local_root_unavailable_message(lp)
                    else:
                        msg = f"Пропущена синхронизация для ID {fid_norm}: {', '.join(mapping_errors)}"
                    # Must be visible even during sync-all.
                    if hasattr(self, "_show_status_message"):
                        self._show_status_message(msg, 8000, owner="sync", force=True)
                    else:
                        self.status.showMessage(msg, 8000)
                except Exception:
                    pass
                try:
                    sync_log("MANUAL_SYNC_ALL mapping invalid", component="UI", op="sync_all", result="skip", extra=f"folder_id={fid_norm} project_id={pid} local_root={lp!r} errors={mapping_errors}")
                except Exception:
                    pass
                continue

            try:
                self._trigger_sync_now(fid_norm, sync_mode="manual")
                started += 1
            except Exception:
                skipped += 1
                continue

        try:
            # Keep sync line owned by sync; do not clear/override per-folder progress.
            msg = f"Ручная синхронизация запущена: {started}, пропущено: {skipped}"
            if hasattr(self, "_update_sync_status"):
                self._update_sync_status(msg)
            elif hasattr(self, "_show_status_message"):
                self._show_status_message(msg, 4000, owner="sync")
            else:
                self.status.showMessage(msg, 4000)
        except Exception:
            pass
    except Exception:
        pass


@QtCore.Slot()
def _on_sync_cancel(self):
    # invoke worker.cancel() in its own thread
    try:
        worker = getattr(self, "_sync_worker", None)
        if worker is not None:
            QtCore.QMetaObject.invokeMethod(worker, "cancel", QtCore.Qt.QueuedConnection)
    except Exception:
        pass


@QtCore.Slot()
def _confirm_disable_all_syncs(self):
    """Ask for confirmation before disabling all sync mappings."""
    try:
        mgr = getattr(self, "sync2", None)
        if not mgr or not getattr(mgr, "map", None):
            return
        ans = QMessageBox.question(
            self,
            t("sync.title"),
            t("sync.disable_all_syncs_confirm"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            try:
                sync_log("Disable all syncs cancelled", component="UI", op="disable_all_syncs", result="cancel")
            except Exception:
                pass
            return
        try:
            sync_log("Disable all syncs confirmed", component="UI", op="disable_all_syncs", result="ok")
        except Exception:
            pass
        self._on_disable_all_syncs()
    except Exception:
        pass


@QtCore.Slot()
def _on_disable_all_syncs(self):
    """Disable all active synchronizations."""
    try:
        mgr = getattr(self, "sync2", None)
        if not mgr or not hasattr(mgr, "map"):
            return
        
        folder_ids = list(mgr.map.keys())
        for fid in folder_ids:
            try:
                mgr.remove_sync(fid)
            except Exception:
                continue
        
        try:
            from larix_nexus.constants import SYNC_ROLE
        except Exception:
            SYNC_ROLE = None

        for fid, it in (getattr(self, 'folder_item_by_id', {}) or {}).items():
            try:
                if it is not None and SYNC_ROLE is not None:
                    it.setData(0, SYNC_ROLE, False)
            except Exception:
                pass

        try:
            if hasattr(self, '_restore_tree_badges'):
                self._restore_tree_badges(self.current_project_id())
        except Exception:
            pass
        
        try:
            self.tree.viewport().update()
        except Exception:
            pass
        
        try:
            from larix_nexus.ui.main_window import cleanup_removed
            cleanup_removed(self.tree)
        except Exception:
            pass
        
        try:
            self.status.showMessage(t("status.sync_all_disabled"), 3000)
        except Exception:
            pass
        try:
            self._update_sync_menu_visibility()
        except Exception:
            pass
    except Exception:
        pass


@QtCore.Slot()
def _update_sync_menu_visibility(self):
    """Update sync menu items visibility based on current state."""
    try:
        mgr = getattr(self, "sync2", None)
        has_syncs = bool(mgr and getattr(mgr, "map", None))
        if hasattr(self, 'act_sync_all'):
            self.act_sync_all.setEnabled(has_syncs)
        if hasattr(self, 'act_disable_all_syncs'):
            self.act_disable_all_syncs.setEnabled(has_syncs)
    except Exception:
        pass


def inject_sync_handlers_to_main_window(MainWindowClass) -> None:
    """Inject sync handler methods into MainWindow class."""
    MainWindowClass._on_auto_sync_started = _on_auto_sync_started
    MainWindowClass._on_auto_sync_finished = _on_auto_sync_finished
    MainWindowClass._on_auto_sync_result = _on_auto_sync_result
    MainWindowClass._on_sync_item = _on_sync_item
    MainWindowClass._on_sync_transfer_progress = _on_sync_transfer_progress
    MainWindowClass._on_sync_started = _on_sync_started
    MainWindowClass._on_sync_total = _on_sync_total
    MainWindowClass._on_sync_progress = _on_sync_progress
    MainWindowClass._on_sync_error = _on_sync_error
    MainWindowClass._on_sync_finished = _on_sync_finished
    MainWindowClass._on_sync_now_started = _on_sync_now_started
    MainWindowClass._on_sync_now_finished = _on_sync_now_finished
    MainWindowClass._on_sync_now_result = _on_sync_now_result
    MainWindowClass._on_sync_all_clicked = _on_sync_all_clicked
    MainWindowClass._on_sync_cancel = _on_sync_cancel
    MainWindowClass._confirm_disable_all_syncs = _confirm_disable_all_syncs
    MainWindowClass._on_disable_all_syncs = _on_disable_all_syncs
    MainWindowClass._update_sync_menu_visibility = _update_sync_menu_visibility
