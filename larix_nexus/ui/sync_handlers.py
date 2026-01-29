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


@QtCore.Slot()
def _on_auto_sync_started(self):
    try:
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.status.showMessage("Синхронизация папок...")
    except Exception:
        pass


@QtCore.Slot()
def _on_auto_sync_finished(self):
    try:
        self.progress.setVisible(False)
        self.progress.setRange(0, 0)
        self.status.clearMessage()
    except Exception:
        pass


@QtCore.Slot(str, str, int)
def _on_sync_item(self, action: str, rel: str, folder_id: int | str):
    # Update status line with current file being synced; keep busy dots if visible
    try:
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
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.status.showMessage(msg)
    except Exception:
        pass


# --- Thread-safe UI slots for initial sync ---
@QtCore.Slot()
def _on_sync_started(self):
    try:
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        base = getattr(self, "_sync_path", "")
        prefix = f"Синхронизация: {base} — " if base else "Синхронизация: "
        self.status.showMessage(prefix + "подсчет файлов…")
    except Exception:
        pass


@QtCore.Slot(int)
def _on_sync_total(self, total: int):
    try:
        self.progress.setRange(0, max(1, int(total)))
        base = getattr(self, "_sync_path", "")
        prefix = f"Синхронизация: {base} — " if base else "Синхронизация: "
        self.status.showMessage(prefix + f"найдено файлов: {int(total)}")
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
        self.status.showMessage(prefix + f"{pct}% — {name} ({done}/{total})")
    except Exception:
        pass


@QtCore.Slot(str)
def _on_sync_error(self, msg: str):
    try:
        self.status.showMessage(f"Ошибка синхронизации: {msg}", 4000)
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

    # Remove cancel button
    try:
        if getattr(self, "_sync_cancel_btn", None):
            self.status.removeWidget(self._sync_cancel_btn)  # type: ignore[arg-type]
    except Exception:
        pass
    try:
        self._sync_cancel_btn = None
    except Exception:
        pass

    try:
        self.progress.setVisible(False)
        self.progress.setRange(0, 0)
    except Exception:
        pass

    try:
        if ok:
            base = getattr(self, "_sync_path", "")
            msg = f"Синхронизация завершена: {base}" if base else "Синхронизация завершена"
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
        else:
            base = getattr(self, "_sync_path", "")
            msg = f"Синхронизация прервана: {base}" if base else "Синхронизация прервана"
            self.status.showMessage(msg, 8000)
            # Show expanded error dialog with details, avoid truncation
            try:
                mb = QMessageBox(self)
                mb.setWindowTitle("Ошибка синхронизации")
                mb.setText(msg)
                if getattr(self, "_sync_worker", None) is not None:
                    errs = getattr(self._sync_worker, "_errors", []) or []
                    if errs:
                        mb.setInformativeText("\n".join([str(e) for e in errs[:5]]))
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
@QtCore.Slot()
def _on_sync_now_started(self):
    try:
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        base = getattr(self, "_sync_now_path", "")
        prefix = f"Синхронизация: {base} — " if base else "Синхронизация: "
        self.status.showMessage(prefix + "запуск…")
    except Exception:
        pass


@QtCore.Slot(bool, str)
def _on_sync_now_finished(self, ok: bool, folder_id: str = ""):
    try:
        self.progress.setVisible(False)
        self.progress.setRange(0, 0)
        base = getattr(self, "_sync_now_path", "")
        if ok:
            self.status.showMessage((f"Синхронизация завершена: {base}" if base else "Синхронизация завершена"), 4000)
            # Обновить только синхронизированную папку
            try:
                if folder_id:
                    self._refresh_synced_folder(folder_id)
                else:
                    self.soft_refresh_and_restore_view()
            except Exception:
                pass
        else:
            self.status.showMessage((f"Синхронизация завершилась с ошибкой: {base}" if base else "Синхронизация завершилась с ошибкой"), 5000)
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


@QtCore.Slot()
def _on_sync_all_clicked(self):
    try:
        mgr = getattr(self, "sync2", None)
        if not mgr or not getattr(mgr, "map", None):
            return
        try:
            self.status.showMessage("Синхронизация всех папок запущена", 3000)
        except Exception:
            pass
        # Run each folder's sync in its own worker to avoid blocking UI
        for fid, cfg in list(mgr.map.items()):
            # only those with configured local path
            try:
                lp = (cfg or {}).get("local_path") or ""
                if not lp:
                    continue
            except Exception:
                continue
            try:
                self._trigger_sync_now(fid)
            except Exception:
                continue
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


def inject_sync_handlers_to_main_window(MainWindowClass) -> None:
    """Inject sync handler methods into MainWindow class."""
    MainWindowClass._on_auto_sync_started = _on_auto_sync_started
    MainWindowClass._on_auto_sync_finished = _on_auto_sync_finished
    MainWindowClass._on_sync_item = _on_sync_item
    MainWindowClass._on_sync_started = _on_sync_started
    MainWindowClass._on_sync_total = _on_sync_total
    MainWindowClass._on_sync_progress = _on_sync_progress
    MainWindowClass._on_sync_error = _on_sync_error
    MainWindowClass._on_sync_finished = _on_sync_finished
    MainWindowClass._on_sync_now_started = _on_sync_now_started
    MainWindowClass._on_sync_now_finished = _on_sync_now_finished
    MainWindowClass._on_sync_all_clicked = _on_sync_all_clicked
    MainWindowClass._on_sync_cancel = _on_sync_cancel
