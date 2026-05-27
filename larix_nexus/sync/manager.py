# -*- coding: utf-8 -*-
"""Sync manager module for Larix Nexus Desktop.

This module contains FolderSyncManager and _InitialSyncWorker classes
for managing sync operations between cloud and local folders.
"""

import os
import sys

# Import SSL patching from centralized module
from larix_nexus.utils.ssl_patch import *  # noqa: F401,F403

from PySide6.QtCore import (
    Qt, QSortFilterProxyModel, QAbstractTableModel, QModelIndex, QObject, QThread,
    Signal, Slot, QSize, QEvent, QRect, QPoint, QTimer, QTranslator, QLocale,
    QLibraryInfo, QPersistentModelIndex, QParallelAnimationGroup, QRectF,
    QPropertyAnimation, QVariantAnimation, QEasingCurve, QDate, QDateTime, QSettings, QEventLoop,
    Property
)
from PySide6.QtGui import (
    QIcon, QPixmap, QPainter, QColor, QPen, QPainterPath, QAction, QTransform, QCursor,
    QTextCharFormat, QBrush, QPalette
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QWidgetAction,
    QVBoxLayout, QHBoxLayout, QGridLayout, QLayout, QFormLayout,
    QLabel, QPushButton, QToolButton, QLineEdit, QComboBox, QCheckBox,
    QProgressBar, QPlainTextEdit, QInputDialog, QDialog, QDialogButtonBox, QMenu,
    QListView, QListWidget, QListWidgetItem,
    QStatusBar, QHeaderView, QTableView, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem,
    QSplitter, QFileDialog, QSizePolicy, QMessageBox,
    QStyledItemDelegate, QStyle, QStyleOptionButton, QStyleOptionViewItem, QStyleOptionHeader, QAbstractItemView, QProxyStyle,
    QGraphicsDropShadowEffect, QGraphicsOpacityEffect,
    QAbstractButton, QDateEdit, QCalendarWidget,
)
from PySide6 import QtCore, QtGui, QtWidgets

from larix_nexus.api import APIClient
from larix_nexus.utils.logging import sync_log, sync_exc
from larix_nexus.utils.ui_trace import trace
from larix_nexus.utils.settings import load_settings
from larix_nexus.utils.helpers import normalize_id, normalize_project_id, enrich_id_types
from larix_nexus.sync.engine import sync_files_new
from larix_nexus.constants import SETTINGS_ORG, SETTINGS_APP
from larix_nexus.utils.atomic_json import atomic_read_json, atomic_write_json
from larix_nexus.sync.state import (
    load_sync_state,
    clear_sync_state,
    purge_orphan_sync_state_files,
    purge_legacy_global_sync_state,
)

# ========================================================================
# CONSTANTS & HELPERS
# ========================================================================

def _app_settings() -> QSettings:
    """Legacy QSettings accessor. Use load_settings()/save_settings() for new code."""
    return QSettings(SETTINGS_ORG, SETTINGS_APP)

def _sync_mappings_path() -> str:
    """Get path to sync mappings JSON file (new location)."""
    from larix_nexus.utils.paths import sync_mappings_path
    return sync_mappings_path()


def _legacy_sync_mappings_path() -> str:
    import os
    from larix_nexus.utils.paths import app_data_dir
    return os.path.join(app_data_dir(), "sync_mappings.json")

def load_sync_mappings() -> dict:
    """Load sync mappings.

    IMPORTANT: если по какой-то причине не удаётся взять `.lock` (например,
    остался после аварийного закрытия), делаем best-effort чтение напрямую,
    чтобы синхронизации не «слетали» визуально после перезапуска.
    """
    import os
    import json
    new_path = _sync_mappings_path()
    legacy_path = _legacy_sync_mappings_path()
    path = new_path
    if not os.path.exists(path) and os.path.exists(legacy_path):
        path = legacy_path
        sync_log("LOAD_SYNC_MAPPINGS: legacy fallback read from {}", legacy_path)
    sync_log("LOAD_SYNC_MAPPINGS: Путь к файлу: {}", path)
    sync_log("LOAD_SYNC_MAPPINGS: Файл существует? {}", os.path.exists(path))
    if os.path.exists(path):
        try:
            sync_log("LOAD_SYNC_MAPPINGS: Размер файла: {} байт", os.path.getsize(path))
        except Exception:
            pass

    default = {"version": 1, "mappings": {}}
    result = atomic_read_json(path, default=default)

    # Fallback: direct read when lock acquisition failed
    try:
        if result == default and os.path.exists(path) and os.path.getsize(path) > 2:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    direct = json.load(f)
                if isinstance(direct, dict) and isinstance(direct.get("mappings"), dict):
                    result = direct
                    sync_log("LOAD_SYNC_MAPPINGS: Fallback direct read OK")
            except Exception as e:
                sync_log("LOAD_SYNC_MAPPINGS: Fallback direct read failed: {}", str(e))
    except Exception:
        pass

    return result

def save_sync_mappings(mappings: dict) -> bool:
    """Save sync mappings."""
    path = _sync_mappings_path()
    sync_log("SAVE: Сохраняем sync mappings в: {}", path)
    sync_log("SAVE: mappings: {}", repr(mappings))
    result = atomic_write_json(path, mappings, ensure_dir=True)
    sync_log("SAVE: Результат сохранения: {}", result)
    return result

# ========================================================================
# FolderSyncManager
# ========================================================================

class FolderSyncManager(QtCore.QObject):
    """Manages sync between a cloud folder and a local directory.
    - Persists mapping in JSON file at %APPDATA%/LarixNexus/sync/mappings.json
    - Every 30 minutes compares mtimes and downloads/uploads newer files.
    """
    refreshRequested = QtCore.Signal()
    # Signals to inform UI about background sync state
    autoSyncStarted = QtCore.Signal()
    autoSyncFinished = QtCore.Signal()
    syncItem = QtCore.Signal(str, str, int)  # action, rel_path, folder_id
    autoSyncResult = QtCore.Signal(list)  # structured per-folder results for the last auto run

    def __init__(self, api_client, parent=None):
        super().__init__(parent)
        self.api = api_client
        
        # Initialize QSettings for this manager
        self.settings = _app_settings()
        
        # map: folder_id -> { local_path, project_id, initial_ok }
        self.map: dict[str, dict] = {}
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._on_periodic_timeout)
        self.timer.setSingleShot(True)
        self.debug: bool = False
        
        # Migrate old QSettings data if present
        self._migrate_from_qsettings()
        
        # Load mappings from JSON
        self._load()
        self._purge_stale_sync_artifacts()

        # runtime sync guards (avoid concurrent syncs for the same folder)
        self._busy_folders: set[str] = set()

        # runtime state
        self._initial_sync_threads: dict[str, tuple[QtCore.QThread, QtCore.QObject]] = {}

        # Auto-sync runner state (periodic timer)
        self._auto_sync_thread: QtCore.QThread | None = None
        self._auto_sync_worker: QtCore.QObject | None = None
        self._auto_sync_running: bool = False
        try:
            self.refreshRequested.connect(self._refresh_ui)
        except Exception:
            pass
        # flag to show progress for the very first auto sync after app start
        self._first_auto_sync_pending: bool = True
        # cache for ensured subfolders within a single sync pass
        self._ensure_cache = {}
        
        # Tombstone system: initialize and migrate if needed
        self._migrate_to_tombstone_v1()
        self._migrate_to_tombstone_v2()  # Fix folder tracking bug
        self._migrate_to_tombstone_v3()  # Fix signature cache folder bug
        
        # Load retention settings
        self._retention_days = int(self.settings.value("sync/config/retention_days", 30) or 30)
        
        # Load sync interval from settings (default: 5 minutes = 300 seconds)
        try:
            from larix_nexus.utils.settings import load_settings
            app_settings = load_settings()
            self._sync_interval = int(app_settings.get("sync", {}).get("auto_sync_interval", 300))
        except Exception:
            self._sync_interval = 300
        
        # Periodic cleanup counter (run cleanup once per day)
        self._cleanup_counter = 0
        
        # Feature flags for safe deletion
        self._enable_folder_cleanup = bool(int(self.settings.value("sync/config/enable_folder_cleanup", 1) or 1))
        self._dry_run_mode = bool(int(self.settings.value("sync/config/dry_run", 0) or 0))
        
        # API retry configuration with exponential backoff
        self._max_retries = 3
        self._retry_delay_base = 2.0  # seconds
        
        # Mass deletion protection with hysteresis
        self._max_deletion_percent = 0.20  # Maximum 20% of files can be deleted in one sync
        self._protection_trigger_count: dict[str, int] = {}  # folder_id -> consecutive trigger count
        self._protection_hysteresis_threshold = 2  # Need 2 consecutive triggers to activate
        self._max_ops_per_cycle = 100  # Maximum operations to process in one cycle
        
        # Snapshot cache for conservative fallback
        self._last_valid_snapshot: dict[str, dict] = {}  # folder_id -> last valid snapshot

    def _fid_key(self, folder_id) -> str:
        """Return normalized folder ID string."""
        sync_log("_FID_KEY: folder_id={!r} type={}", folder_id, type(folder_id))
        key = normalize_id(folder_id)
        sync_log("_FID_KEY: normalized key={!r}", key)
        if not key:
            sync_log("_FID_KEY: ERROR - key is empty!")
            raise ValueError("folder_id is required")
        return key

    def _fid_group(self, folder_id) -> str:
        """Return QSettings group key for given folder id."""
        sync_log("_FID_GROUP: folder_id={!r} type={}", folder_id, type(folder_id))
        key = f"f{self._fid_key(folder_id)}"
        sync_log("_FID_GROUP: key={!r}", key)
        return key

    # --- signature helpers (unified format for rename detection) ---
    def _sig_string_from_cache(self, sig: dict | None) -> str:
        """Convert cached signature dict to a canonical string.
        Order of preference: hash/etag/version -> "size:mtime" ints -> "".
        """
        try:
            if not isinstance(sig, dict):
                return ""
            h = sig.get('hash') or sig.get('etag') or sig.get('version')
            if h:
                return str(h)
            try:
                size = int(float(sig.get('size', 0) or 0))
            except Exception:
                size = 0
            try:
                mtime = int(float(sig.get('mtime', 0) or 0))
            except Exception:
                mtime = 0
            return f"{size}:{mtime}"
        except Exception:
            return ""

    # --- config helpers ---
    def _defer_folder_deletions(self) -> bool:
        """When True, do not immediately delete/move folders; use tombstones+queue."""
        try:
            val = self.settings.value("sync/config/defer_folder_deletions", 1)
            return bool(int(val or 1))
        except Exception:
            return True

    # --- folder rename detection helpers ---
    def _detect_folder_renames_local(self,
                                     last_local_files: set[str],
                                     current_local_files: set[str],
                                     deleted_dirs: set[str],
                                     new_dirs: set[str]) -> dict[str, str]:
        """Detect local folder renames by matching moved file paths under old/new prefixes."""
        ren: dict[str, str] = {}
        try:
            old_map: dict[str, set[str]] = {}
            for d in deleted_dirs:
                pref = d + "/"
                files = {p for p in last_local_files if p.startswith(pref)}
                if files:
                    old_map[d] = files
            if not old_map or not new_dirs:
                return ren
            used_new: set[str] = set()
            for d, ofiles in old_map.items():
                best = None
                best_ratio = 0.0
                parent = d.rsplit('/', 1)[0] if '/' in d else ''
                for n in new_dirs:
                    if n in used_new:
                        continue
                    if (n.rsplit('/', 1)[0] if '/' in n else '') != parent:
                        continue
                    moved = 0
                    for f in ofiles:
                        suffix = f[len(d):]
                        cand = n + suffix
                        if cand in current_local_files:
                            moved += 1
                    ratio = moved / max(len(ofiles), 1)
                    if ratio > best_ratio:
                        best_ratio = ratio
                        best = n
                if best and best_ratio >= 0.8:
                    ren[d] = best
                    used_new.add(best)
        except Exception:
            pass
        return ren

    def _detect_folder_renames_cloud(self,
                                     last_cloud_files: set[str],
                                     current_cloud_files: set[str],
                                     deleted_dirs: set[str],
                                     new_dirs: set[str]) -> dict[str, str]:
        """Detect cloud folder renames by matching moved file paths under old/new prefixes."""
        ren: dict[str, str] = {}
        try:
            if not deleted_dirs or not new_dirs:
                return ren
            used_new: set[str] = set()
            for d in deleted_dirs:
                ofiles = {p for p in last_cloud_files if p.startswith(d + "/")}
                if not ofiles:
                    continue
                best = None
                best_ratio = 0.0
                parent = d.rsplit('/', 1)[0] if '/' in d else ''
                for n in new_dirs:
                    if n in used_new:
                        continue
                    if (n.rsplit('/', 1)[0] if '/' in n else '') != parent:
                        continue
                    moved = 0
                    for f in ofiles:
                        suffix = f[len(d):]
                        cand = n + suffix
                        if cand in current_cloud_files:
                            moved += 1
                    ratio = moved / max(len(ofiles), 1)
                    if ratio > best_ratio:
                        best_ratio = ratio
                        best = n
                if best and best_ratio >= 0.8:
                    ren[d] = best
                    used_new.add(best)
        except Exception:
            pass
        return ren

    # --- protection state helpers ---
    def _protection_key(self, folder_id: int | str) -> str:
        return f"sync/protection/f{normalize_id(folder_id)}"

    def _is_protection_active(self, folder_id: int | str) -> bool:
        try:
            key = self._protection_key(folder_id)
            return bool(int(self.settings.value(f"{key}/active", 0) or 0))
        except Exception:
            return False

    def _set_protection_state(self, folder_id: int | str, active: bool, *, reason: str = "", meta: dict | None = None) -> None:
        try:
            key = self._protection_key(folder_id)
            self.settings.setValue(f"{key}/active", 1 if active else 0)
            self.settings.setValue(f"{key}/reason", reason)
            self.settings.setValue(f"{key}/ts", time.time())
            if isinstance(meta, dict):
                # store compact meta
                for k, v in meta.items():
                    self.settings.setValue(f"{key}/{k}", v)
            self.settings.sync()
            sync_log("PROTECTION state: folder_id={} active={} reason='{}' meta={}", normalize_id(folder_id), bool(active), reason, meta or {})
        except Exception as e:
            sync_exc(f"Failed to set protection state: {e}")

    def _update_mass_delete_protection(self, folder_id: int | str, *, deleted_count: int, prev_total: int, current_total: int) -> bool:
        """Evaluate guard. Returns True if protection should be active.
        Uses robust baseline and ignores obviously broken snapshots.
        Side effect: updates protection state in settings.
        """
        try:
            baseline = max(int(prev_total or 0), int(current_total or 0))
            if baseline <= 0:
                # nothing to compare, keep protection off
                self._set_protection_state(folder_id, False, reason="no_baseline")
                return False

            # Suspicious snapshot if massive drop vs previous
            suspicious = False
            try:
                if prev_total >= 25:
                    # 90%+ drop or empty current -> suspicious
                    if current_total == 0 or (current_total / max(prev_total, 1)) <= 0.1:
                        suspicious = True
            except Exception:
                suspicious = False

            ratio = (deleted_count / baseline) if baseline else 0.0
            over_threshold = ratio > self._max_deletion_percent

            if suspicious:
                # Enter safe mode and trigger self-heal of caches
                self._set_protection_state(folder_id, True, reason="suspicious_snapshot",
                                           meta={"deleted": int(deleted_count), "baseline": int(baseline),
                                                 "prev_total": int(prev_total), "current_total": int(current_total),
                                                 "ratio": ratio})
                # Increment trigger count for hysteresis
                self._protection_trigger_count[folder_id] = self._protection_trigger_count.get(folder_id, 0) + 1
                try:
                    self._self_heal_caches(folder_id, reason="suspicious_snapshot")
                except Exception:
                    pass
                return True

            if over_threshold:
                # Increment trigger count
                current_triggers = self._protection_trigger_count.get(folder_id, 0) + 1
                self._protection_trigger_count[folder_id] = current_triggers
                
                # Activate protection only after hysteresis threshold
                if current_triggers >= self._protection_hysteresis_threshold:
                    self._set_protection_state(folder_id, True, reason="mass_deletion_ratio",
                                               meta={"deleted": int(deleted_count), "baseline": int(baseline),
                                                     "prev_total": int(prev_total), "current_total": int(current_total),
                                                     "ratio": ratio, "triggers": current_triggers})
                    sync_log("PROTECTION activated after {} consecutive triggers", current_triggers)
                    return True
                else:
                    # Register tombstones but don't activate protection yet
                    self._set_protection_state(folder_id, False, reason="mass_deletion_pending",
                                               meta={"deleted": int(deleted_count), "baseline": int(baseline),
                                                     "prev_total": int(prev_total), "current_total": int(current_total),
                                                     "ratio": ratio, "triggers": current_triggers,
                                                     "threshold": self._protection_hysteresis_threshold})
                    sync_log("PROTECTION pending: trigger {}/{}", current_triggers, self._protection_hysteresis_threshold)
                    return False

            # Reset trigger count if everything is OK
            self._protection_trigger_count[folder_id] = 0
            # Otherwise, make sure protection is off
            self._set_protection_state(folder_id, False, reason="ok",
                                       meta={"deleted": int(deleted_count), "baseline": int(baseline),
                                             "prev_total": int(prev_total), "current_total": int(current_total),
                                             "ratio": ratio})
            return False
        except Exception as e:
            sync_exc(f"Failed to update protection state: {e}")
            return False

    def _self_heal_caches(self, folder_id: int | str, *, reason: str = "") -> None:
        """Auto self-healing: clear and rebuild state/signature caches on desync.
        Clears: last_cloud snapshot, last_folders, signature cache (both sides).
        """
        try:
            sync_log("SELF_HEAL: start folder_id={} reason='{}'", normalize_id(folder_id), reason)
            # Clear cloud snapshots
            self.settings.beginGroup("sync2_state")
            try:
                self.settings.beginGroup(f"f{normalize_id(folder_id)}")
                try:
                    self.settings.setValue("last_cloud", "")
                    self.settings.setValue("last_folders", "")
                finally:
                    self.settings.endGroup()
            finally:
                self.settings.endGroup()
            # Clear signatures
            self.settings.remove(f"sync/signatures/{normalize_id(folder_id)}")
            self.settings.sync()
            sync_log("SELF_HEAL: done folder_id={}", normalize_id(folder_id))
        except Exception as e:
            sync_exc(f"SELF_HEAL failed: {e}")

    # --- cloud folder existence probe (safe, non-creating) ---
    def _cloud_folder_exists_by_path(self, root_folder_id: int | str, rel_path: str) -> int:
        """Probe if folder path exists in cloud by traversing names.
        Returns: 1 = exists, 0 = definitely missing, -1 = unknown (inconclusive).
        """
        try:
            current = normalize_id(root_folder_id)
        except Exception:
            return -1
        try:
            rel = str(rel_path or "").replace("\\", "/").strip("/")
            if not rel:
                return 1
            parts = [p for p in rel.split('/') if p]
            for seg in parts:
                name = _sanitize_filename(seg)
                try:
                    parent = self.api.get_folder_details(current, force=True)
                except Exception:
                    return -1
                if not isinstance(parent, dict):
                    return -1
                children = None
                for key in ("children", "folders", "subFolders", "subfolders"):
                    lst = parent.get(key)
                    if isinstance(lst, list):
                        children = lst
                        break
                if not isinstance(children, list):
                    # API didn't return children — try project-wide traversal as fallback
                    children = None
                found = None
                for ch in children:
                    try:
                        raw_title = (ch.get("name") or ch.get("title") or ch.get("folderName") or "").strip()
                        ctype = str(ch.get("type") or "").lower()
                        looks_folder = (ctype == "folder" or ctype == "" or isinstance(ch.get("children"), list) or bool(ch.get("children")))
                        if looks_folder and _sanitize_filename(raw_title) == name:
                            found = normalize_id(ch.get("id") or 0)
                            break
                    except Exception:
                        continue
                if not found:
                    # Fallback: traverse project tree if available
                    try:
                        proj_id = None
                        for fid, cfg in (self.map or {}).items():
                            try:
                                if normalize_id(fid) == normalize_id(root_folder_id):
                                    proj_id = cfg.get("project_id", 0)
                                    break
                            except Exception:
                                continue
                        if proj_id:
                            tree = self.api.list_folders(int(proj_id), force=True) or []
                            # Walk from root_folder_id through tree by names
                            cur = normalize_id(root_folder_id)
                            ok_all = True
                            for seg2 in parts:
                                nm = _sanitize_filename(seg2)
                                node = self._find_folder_in_tree(tree, cur) if hasattr(self, '_find_folder_in_tree') else None
                                # If we can't locate node in tree, break
                                if not isinstance(node, dict):
                                    ok_all = False
                                    break
                                # Find child by name
                                child_id = None
                                lst = node.get('children') or node.get('folders') or []
                                if isinstance(lst, list):
                                    for ch in lst:
                                        try:
                                            ttl = (ch.get('name') or ch.get('title') or ch.get('folderName') or '').strip()
                                            ctyp = str(ch.get('type') or '').lower()
                                            looks_folder = (ctyp == 'folder' or ctyp == '' or isinstance(ch.get('children'), list) or bool(ch.get('children')))
                                            if looks_folder and _sanitize_filename(ttl) == nm:
                                                raw_fid = ch.get('id') or 0

                                                try:
                                                    child_id = int(raw_fid)
                                                except (ValueError, TypeError):
                                                    child_id = raw_fid
                                                break
                                        except Exception:
                                            continue
                                if not child_id:
                                    ok_all = False
                                    break
                                cur = int(child_id)
                            if ok_all:
                                return 1
                            # Not found in project tree — consider missing
                            return 0
                    except Exception:
                        pass
                    return 0
                current = int(found)
            return 1
        except Exception:
            return -1

    # --- execution policy ---
    def _execute_queue_under_protection(self) -> bool:
        """Whether to execute pending delete operations even if protection is active.
        Default: True (allows running without blocking), can be turned off via settings.
        """
        try:
            val = self.settings.value("sync/config/execute_pending_under_protection", 1)
            return bool(int(val or 1))
        except Exception:
            return True
        
    # --- periodic scheduling (uses configurable interval) ---
    def _next_sync_datetime(self):
        """Next aligned auto-sync run time (local clock, no microseconds)."""
        from datetime import datetime, timedelta

        now = datetime.now()
        interval_seconds = max(1, int(self._sync_interval or 300))

        if interval_seconds >= 86400:
            today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
            if now.hour == 0 and now.minute == 0 and now.second == 0:
                return today_midnight + timedelta(days=1)
            return today_midnight + timedelta(days=1)

        seconds_since_midnight = now.hour * 3600 + now.minute * 60 + now.second
        remainder = seconds_since_midnight % interval_seconds
        remaining = interval_seconds - remainder
        if remaining <= 0:
            remaining = interval_seconds
        return (now + timedelta(seconds=remaining)).replace(microsecond=0)

    def _ms_until_next_sync(self) -> int:
        """Milliseconds until the next boundary-aligned auto-sync."""
        from datetime import datetime

        next_run = self._next_sync_datetime()
        now = datetime.now()
        ms = int((next_run - now).total_seconds() * 1000)
        return max(ms, 1000)

    @QtCore.Slot()
    def _on_periodic_timeout(self) -> None:
        # IMPORTANT: do not run sync_all() on GUI thread.
        try:
            interval_seconds = max(1, int(self._sync_interval or 300))
            mappings_n = len(self.map) if getattr(self, "map", None) else 0
            has_token = bool(getattr(self.api, "token", None))
            sync_log(
                "SYNC_TIMER: timeout fired interval={} mappings={} token={}",
                interval_seconds,
                mappings_n,
                "yes" if has_token else "no",
            )

            if not has_token:
                sync_log("SYNC_TIMER: skip reason=no_auth_token")
                try:
                    self._schedule_next_sync()
                except Exception:
                    pass
                return

            if not getattr(self, "map", None):
                sync_log("SYNC_TIMER: skip reason=no_mappings")
                try:
                    self._schedule_next_sync()
                except Exception:
                    pass
                return

            # Avoid overlapping periodic runs.
            if bool(getattr(self, "_auto_sync_running", False)):
                sync_log("SYNC_TIMER: skip reason=already_running")
                try:
                    self._schedule_next_sync()
                except Exception:
                    pass
                return

            # Start a single background runner thread.
            self._auto_sync_running = True
            try:
                th = QtCore.QThread(self)
                worker = _AutoSyncAllRunner(self)
                worker.moveToThread(th)

                # Track for cleanup.
                self._auto_sync_thread = th
                self._auto_sync_worker = worker

                th.started.connect(worker.run)

                # Cleanup and reschedule on both success and error.
                worker.sig_finished.connect(self._on_auto_sync_worker_finished, QtCore.Qt.QueuedConnection)
                worker.sig_error.connect(self._on_auto_sync_worker_error, QtCore.Qt.QueuedConnection)
                # Ensure we also handle thread finishing unexpectedly.
                try:
                    th.finished.connect(self._on_auto_sync_thread_finished, QtCore.Qt.QueuedConnection)
                except Exception:
                    pass

                sync_log("AUTO_SYNC: starting worker thread")
                th.start()
            except Exception as e:
                self._auto_sync_running = False
                sync_exc(f"AUTO_SYNC: failed to start worker: {e}")
                try:
                    self._schedule_next_sync()
                except Exception:
                    pass
        except Exception:
            # Best-effort reschedule
            try:
                self._auto_sync_running = False
            except Exception:
                pass
            try:
                self._schedule_next_sync()
            except Exception:
                pass

    @QtCore.Slot(list)
    def _on_auto_sync_worker_finished(self, results: list) -> None:
        # Worker completed; always reschedule next run.
        try:
            sync_log("AUTO_SYNC: finished results={}", len(results) if isinstance(results, list) else -1)
        except Exception:
            pass

        # Emit structured results for UI (queued across threads).
        try:
            if isinstance(results, list):
                self.autoSyncResult.emit(results)
        except Exception:
            pass

        try:
            self._auto_sync_running = False
        except Exception:
            pass

        try:
            self._cleanup_auto_sync_thread()
        except Exception:
            pass

        try:
            self._schedule_next_sync()
        except Exception:
            pass

    @QtCore.Slot(str)
    def _on_auto_sync_worker_error(self, err: str) -> None:
        try:
            sync_exc(f"AUTO_SYNC: worker error: {err}")
        except Exception:
            pass
        # Do not cleanup/reschedule here: the worker always emits sig_finished
        # from its finally block, and the finished handler owns lifecycle.

    @QtCore.Slot()
    def _on_auto_sync_thread_finished(self) -> None:
        # Defensive: if the thread ends without emitting finished/error.
        try:
            if bool(getattr(self, '_auto_sync_running', False)):
                sync_log("AUTO_SYNC: thread finished unexpectedly")
        except Exception:
            pass
        try:
            self._auto_sync_running = False
        except Exception:
            pass
        try:
            self._cleanup_auto_sync_thread()
        except Exception:
            pass

    def _cleanup_auto_sync_thread(self) -> None:
        th = getattr(self, '_auto_sync_thread', None)
        worker = getattr(self, '_auto_sync_worker', None)
        try:
            self._auto_sync_thread = None
            self._auto_sync_worker = None
        except Exception:
            pass

        try:
            if isinstance(worker, QtCore.QObject):
                try:
                    worker.deleteLater()
                except Exception:
                    pass
        except Exception:
            pass

        try:
            if isinstance(th, QtCore.QThread):
                try:
                    if th.isRunning():
                        th.quit()
                except Exception:
                    pass
                try:
                    # Don't block GUI; short wait best-effort.
                    if QtCore.QThread.currentThread() is not th:
                        th.wait(250)
                except Exception:
                    pass
                try:
                    th.deleteLater()
                except Exception:
                    pass
        except Exception:
            pass

    # public helper for external callers (MainWindow)
    def schedule_next_half_hour(self) -> None:
        self._schedule_next_sync()

    @QtCore.Slot()
    def _refresh_ui(self) -> None:
        try:
            owner = self.parent()
            # Refresh only from GUI thread.
            if owner is not None and hasattr(owner, 'soft_refresh_and_restore_view'):
                try:
                    trace("sync.manager._refresh_ui: queue soft_refresh")
                except Exception:
                    pass
                try:
                    QtCore.QMetaObject.invokeMethod(owner, 'soft_refresh_and_restore_view', QtCore.Qt.QueuedConnection)
                except Exception:
                    try:
                        owner.soft_refresh_and_restore_view()
                    except Exception:
                        pass
        except Exception:
            pass

    # --- tombstone migration ---
    def _migrate_to_tombstone_v1(self) -> None:
        """Legacy migration stub - no longer needed with JSON storage."""
        pass
    
    def _migrate_to_tombstone_v2(self):
        """Legacy migration stub - no longer needed with JSON storage."""
        pass
    
    def _migrate_to_tombstone_v3(self):
        """Legacy migration stub - no longer needed with JSON storage."""
        pass

    # --- persistence ---
    def _migrate_from_qsettings(self):
        """Migrate sync mappings from old QSettings to JSON."""
        try:
            settings = _app_settings()
            settings.beginGroup("sync2")
            size = int(settings.value("count", 0) or 0)
            
            if size > 0:
                sync_log("SYNC: migrating {} sync mappings from QSettings to JSON", size)
                
                for i in range(size):
                    settings.beginGroup(f"f{i}")
                    try:
                        fid = int(settings.value("folder_id", 0) or 0)
                        local_path = str(settings.value("local_path", "") or "")
                        project_id = int(settings.value("project_id", 0) or 0)
                        initial_ok = bool(int(settings.value("initial_ok", 0) or 0))
                        
                        if fid and local_path and project_id:
                            self.map[fid] = {
                                "local_path": local_path,
                                "project_id": project_id,
                                "initial_ok": initial_ok
                            }
                    finally:
                        settings.endGroup()
                
                # Save to JSON
                if self.map:
                    self._save()
                
                # Clear old QSettings
                settings.endGroup()
                settings.remove("sync2")
            else:
                settings.endGroup()
        except Exception as e:
            sync_exc(f"Failed to migrate sync mappings: {e}")

    def _load(self):
        """Load sync mappings from JSON."""
        try:
            data = load_sync_mappings()
            mappings = data.get("mappings", {})
            
            sync_log("=" * 60)
            sync_log("LOAD: Загружаем sync mappings из JSON")
            sync_log("LOAD: Путь: {}", _sync_mappings_path())
            sync_log("LOAD: Всего маппингов в файле: {}", len(mappings))
            for fid_str, cfg in mappings.items():
                sync_log("LOAD:   folder_id={!r} -> local_path={!r}, project_id={}", fid_str, cfg.get("local_path"), cfg.get("project_id"))

            self.map.clear()
            loaded_count = 0
            for fid_str, cfg in mappings.items():
                try:
                    fid = fid_str
                    if cfg.get("local_path") and cfg.get("project_id"):
                        # project_id может быть как числом, так и строковым идентификатором
                        # (нельзя принудительно приводить к int, иначе маппинг «теряется» при загрузке)
                        pid_raw = cfg.get("project_id")
                        try:
                            if isinstance(pid_raw, (int, float)):
                                pid = int(pid_raw)
                            else:
                                s_pid = str(pid_raw).strip()
                                pid = int(s_pid) if s_pid.isdigit() else s_pid
                        except Exception:
                            pid = str(pid_raw).strip() if pid_raw is not None else ""

                        if pid:
                            self.map[fid] = {
                                "local_path": str(cfg["local_path"]),
                                "project_id": pid,
                                "initial_ok": bool(cfg.get("initial_ok", False))
                            }
                            loaded_count += 1
                except Exception:
                    pass
            
            sync_log("LOAD: Успешно загружено маппингов: {}", loaded_count)
            sync_log("LOAD: Итоговый размер self.map: {}", len(self.map))
            sync_log("=" * 60)
        except Exception as e:
            sync_exc(f"Failed to load sync mappings: {e}")

    def _save(self):
        """Save sync mappings to JSON."""
        try:
            data = load_sync_mappings()
            
            # Convert map to JSON-serializable format
            mappings = {}
            sync_log("_SAVE: Сохраняем {} маппингов", len(self.map))
            for fid, cfg in self.map.items():
                mappings[str(fid)] = {
                    "local_path": cfg.get("local_path", ""),
                    "project_id": cfg.get("project_id", 0),
                    "initial_ok": cfg.get("initial_ok", False)
                }
                sync_log("_SAVE:   folder_id={!r} -> local_path={!r}, project_id={}", fid, cfg.get("local_path"), cfg.get("project_id"))
            
            data["mappings"] = mappings
            save_sync_mappings(data)
            sync_log("_SAVE: Маппинги сохранены успешно")
            self._purge_stale_sync_artifacts()
        except Exception as e:
            sync_exc(f"Failed to save sync mappings: {e}")

    def _purge_stale_sync_artifacts(self) -> None:
        """Drop state files (and legacy global state) not tied to active mappings."""
        try:
            active = {str(fid): cfg for fid, cfg in self.map.items() if isinstance(cfg, dict)}
            removed = purge_orphan_sync_state_files(active)
            if removed:
                sync_log("PURGE_STATE: removed {} orphan file(s)", removed)
            if not active:
                purge_legacy_global_sync_state()
        except Exception as e:
            sync_exc(f"Failed to purge stale sync artifacts: {e}")

    # --- public API ---
    def start_if_configured(self):
        try:
            if self.map:
                # Без немедленного запуска — просто планируем ближайшую синхронизацию
                if any(bool(cfg.get("initial_ok")) for cfg in self.map.values()):
                    self._schedule_next_sync()
        except Exception:
            pass

    def set_sync_interval(self, interval_seconds: int) -> None:
        """Set sync interval in seconds and reschedule timer."""
        try:
            self._sync_interval = interval_seconds
            
            # Save to settings
            try:
                from larix_nexus.utils.settings import update_settings
                update_settings(lambda s: {
                    **s,
                    "sync": {
                        **s.get("sync", {}),
                        "auto_sync_interval": interval_seconds
                    }
                })
            except Exception:
                pass
            
            # Reschedule timer with new interval
            self._schedule_next_sync()
            sync_log("SYNC: Interval updated to {} seconds", interval_seconds)
        except Exception as e:
            sync_exc(f"Failed to set sync interval: {e}")

    def _schedule_next_sync(self) -> None:
        """Schedule next sync based on configured interval."""
        try:
            interval_seconds = max(1, int(self._sync_interval or 300))
            next_run = self._next_sync_datetime()
            ms = self._ms_until_next_sync()
            self.timer.setSingleShot(True)
            self.timer.start(ms)
            timer_active = False
            try:
                timer_active = bool(self.timer.isActive())
            except Exception:
                pass
            sync_log(
                "SYNC_TIMER: scheduled interval={} next_run={} delay_ms={} active={}",
                interval_seconds,
                next_run.strftime("%Y-%m-%dT%H:%M:%S"),
                ms,
                timer_active,
            )
        except Exception:
            pass



    def _collect_cloud_folders(self, root_folder_node: dict, rel_path: str = "") -> dict:
        """
        Возвращает словарь {rel_path: folder_id} для всех папок в дереве,
        включая корень с rel_path == "".
        """
        out = {}

        def _name(d: dict) -> str:
            return (d.get("title") or d.get("folderName") or d.get("name") or "").strip()

        def _rel(base: str, name: str) -> str:
            parts = [p.strip("/\\") for p in (base, name) if str(p or "").strip()]
            return "/".join(parts)

        def _is_folder(d: dict) -> bool:
            t = str(d.get("type") or "").lower()
            if t == "folder":
                return True
            # эвристики
            if isinstance(d.get("children"), list) or isinstance(d.get("folders"), list):
                return True
            if d.get("documentTypeId") in (None, 0):  # у папок часто нет doc type
                return True
            return False

        def _walk(node: dict, base_rel: str):
            if not isinstance(node, dict):
                return
            try:
                enrich_id_types(node)
            except Exception:
                pass
            try:
                raw_fid = node.get("id") or 0
                try:
                    fid = int(raw_fid)
                except (ValueError, TypeError):
                    fid = raw_fid
            except Exception:
                fid = 0

            name = _name(node) if base_rel != "" else _name(node) or ""
            cur_rel = base_rel  # корень уже назначен извне

            # если это реальная папка - запишем
            if fid and _is_folder(node):
                out[cur_rel] = fid

            # если нет списков - дотянем детали папки
            has_lists = any(isinstance(node.get(k), list) for k in ("children", "folders"))
            if not has_lists and fid:
                try:
                    det = self.api.get_folder_details(fid, force=False)
                    if isinstance(det, dict):
                        node = det
                except Exception:
                    pass

            # рекурсия в подпапки
            children = node.get("children") or node.get("folders") or []
            if isinstance(children, list):
                for ch in children:
                    if not isinstance(ch, dict):
                        continue
                    try:
                        enrich_id_types(ch)
                    except Exception:
                        pass
                    if not _is_folder(ch):
                        continue
                    ch_name = _name(ch)
                    if not ch_name:
                        continue
                    ch_rel = _rel(cur_rel, ch_name)
                    # если нет контента - подтянем детали, чтобы получить id/children
                    try:
                        raw_fid = ch.get("id") or 0
                        try:
                            ch_id = int(raw_fid)
                        except (ValueError, TypeError):
                            ch_id = raw_fid
                    except Exception:
                        ch_id = 0
                    if ch_id and not any(isinstance(ch.get(k), list) for k in ("children", "folders")):
                        try:
                            det = self.api.get_folder_details(ch_id, force=False)
                            if isinstance(det, dict):
                                ch = det
                        except Exception:
                            pass
                    # запишем саму папку
                    try:
                        raw_fid = ch.get("id") or 0
                        try:
                            ch_id = int(raw_fid)
                        except (ValueError, TypeError):
                            ch_id = raw_fid
                        if ch_id:
                            out[ch_rel] = ch_id
                    except Exception:
                        pass
                    _walk(ch, ch_rel)

        _walk(root_folder_node, rel_path.strip("/\\"))
        # гарантируем наличие записи для корня
        if "" not in out:
            try:
                raw_fid = root_folder_node.get("id") or 0
                try:
                    rid = int(raw_fid)
                except (ValueError, TypeError):
                    rid = raw_fid
                if rid:
                    out[""] = rid
            except Exception:
                pass
        return out
    
    def _collect_cloud_dirs(self, folder_node: dict, rel_path: str = "") -> list[str]:
        """Собирает относительные пути папок в облаке (включая пустые)."""
        out: set[str] = set()

        def walk(node: dict, rel: str) -> None:
            try:
                children = (
                    node.get("children")
                    or node.get("folders")
                    or node.get("items")
                    or node.get("documents")
                    or node.get("content")
                )
                if (not isinstance(children, list)) or (not children):
                    children = node.get("folders") or node.get("files") or []
                if not isinstance(children, list):
                    try:
                        details = self.api.get_folder_details(node.get("id") or 0, force=True)
                    except Exception:
                        details = None
                    if isinstance(details, dict):
                        children = (
                            details.get("children")
                            or details.get("folders")
                            or details.get("items")
                            or details.get("documents")
                            or details.get("content")
                        )
                        if (not isinstance(children, list)) or (not children):
                            children = details.get("folders") or details.get("files") or []
                if not isinstance(children, list):
                    return
                for child in children:
                    if not isinstance(child, dict):
                        continue
                    ctype = str(child.get("type") or "").lower()
                    is_folder = (
                        ctype == "folder"
                        or bool(child.get("hasFolders"))
                        or any(
                            isinstance(child.get(key), list)
                            for key in ("children", "folders", "items", "documents", "content")
                        )
                        or (
                            not any(key in child for key in ("fileUid", "fileName", "originalName"))
                            and (child.get("title") or child.get("folderName") or child.get("name"))
                        )
                    )
                    if not is_folder:
                        continue
                    name = get_title(child)
                    if not name:
                        continue
                    sub_rel = "/".join([part for part in [rel.strip("/"), name] if part])
                    if sub_rel:
                        out.add(sub_rel)
                    walk(child, sub_rel)
            except Exception:
                pass

        walk(folder_node or {}, str(rel_path or ""))
        return sorted(out)

    def _collect_local_dirs(self, base: str) -> list[str]:
        """Собирает ОТНОСИТЕЛЬНЫЕ пути локальных папок (включая пустые)."""
        out = set()
        try:
            base_abs = os.path.abspath(base)
            for root, dirs, _files in os.walk(base_abs):
                for d in dirs:
                    rel = os.path.relpath(os.path.join(root, d), base_abs)
                    rel = rel.replace("\\", "/").strip("/")
                    if rel:
                        out.add(rel)
        except Exception:
            pass
        return sorted(out)
    
    def _sync_directories_first(self, cloud_root_node: dict, local_root: str, project_id: int | str = 0) -> None:
        """
        1) Создаёт недостающие локальные папки, которые есть в облаке.
        2) Создаёт недостающие облачные папки, которые есть локально.
        Делается без сравнения времени - только по именам/пути.
        """
        import os

        cloud_map = self._collect_cloud_folders(cloud_root_node, rel_path="")
        cloud_dirs = set(cloud_map.keys())  # rel_path -> id
        local_dirs = self._collect_local_dirs(local_root)

        # 1) добить локальные папки, которые есть в облаке
        missing_local = sorted(cloud_dirs - local_dirs - {""})
        for rel in missing_local:
            path = os.path.join(local_root, rel.replace("/", os.sep))
            try:
                os.makedirs(path, exist_ok=True)
                self.log.debug(f"DIR_DECISION rel='{rel}' reason='only_cloud_dir' -> mkdir_local")
            except Exception as e:
                self.log.debug(f"DIR_DECISION rel='{rel}' reason='only_cloud_dir' -> mkdir_local_fail err='{e}'")

        # 2) добить облачные папки, которые есть локально
        missing_cloud = sorted(local_dirs - cloud_dirs - {""})

        def ensure_cloud_path(rel: str) -> int | None:
            """
            Гарантированно создаёт путь rel в облаке.
            Возвращает id конечной папки или None.
            """
            parts = [p for p in rel.split("/") if p]
            # идём от корня
            cur_rel = ""
            cur_id = cloud_map.get("", None)
            if cur_id is None:
                return None
            for name in parts:
                nxt_rel = f"{cur_rel}/{name}" if cur_rel else name
                found_id = cloud_map.get(nxt_rel)
                if found_id:
                    cur_rel, cur_id = nxt_rel, found_id
                    continue
                # создать
                try:
                    new_id = self.api.create_folder(project_id, cur_id, name)
                except Exception:
                    new_id = None
                if not new_id:
                    self.log.debug(f"DIR_DECISION rel='{nxt_rel}' reason='only_local_dir' -> mkdir_cloud_fail")
                    return None
                new_id_norm = normalize_id(new_id)
                cloud_map[nxt_rel] = new_id_norm
                self.log.debug(f"DIR_DECISION rel='{nxt_rel}' reason='only_local_dir' -> mkdir_cloud")
                cur_rel, cur_id = nxt_rel, new_id_norm
            return cur_id

        for rel in missing_cloud:
            ensure_cloud_path(rel)

    # --- state persistence for safe deletions ---
    def _load_last_cloud_set(self, folder_id: int) -> set[str]:
        """Load last cloud FILES snapshot (legacy method for backward compatibility).
        
        Returns only files set. For full snapshot with folders, use _load_cloud_snapshot().
        """
        try:
            s = self.settings
            s.beginGroup("sync2_state")
            try:
                s.beginGroup(f"f{normalize_id(folder_id)}")
                try:
                    raw = s.value("last_cloud", "") or ""
                finally:
                    s.endGroup()
            finally: 
                s.endGroup()
            try:
                if raw and isinstance(raw, str):
                    # newline-separated list - normalize each path for consistency
                    paths = [p for p in raw.split("\n") if p]
                    sync_log("LOAD_CLOUD_SNAPSHOT: folder_id={} raw_count={} paths={}", 
                            folder_id, len(paths), paths[:10])  # Log first 10
                    # Apply normalization to handle legacy data saved without casefold
                    normalized = set()
                    for p in paths:
                        try:
                            # Try to normalize using _norm_rel_sanitized
                            norm = self._norm_rel_sanitized(p)
                            if norm:
                                normalized.add(norm)
                        except Exception:
                            # Fallback to simple normalization
                            normalized.add(p.replace("\\", "/").strip("/").casefold())
                    sync_log("LOAD_CLOUD_SNAPSHOT: folder_id={} normalized_count={}", 
                            folder_id, len(normalized))
                    return normalized
                else:
                    sync_log("LOAD_CLOUD_SNAPSHOT: folder_id={} empty or invalid raw='{}'", 
                            folder_id, raw)
            except Exception as e:
                sync_exc(f"Failed to parse cloud snapshot: {e}")
        except Exception as e:
            sync_exc(f"Failed to load cloud snapshot: {e}")
        return set()
    
    def _load_cloud_snapshot(self, folder_id: int) -> dict:
        """Load complete cloud snapshot with files AND folders.
        
        Returns:
            dict with keys:
                - files: set[str] - normalized file rel_paths
                - folders: dict[str, None] - normalized folder rel_paths (compatible with dict structure)
                - is_valid: bool - True if loaded successfully
        """
        try:
            s = self.settings
            s.beginGroup("sync2_state")
            try:
                s.beginGroup(f"f{normalize_id(folder_id)}")
                try:
                    files_raw = s.value("last_cloud", "") or ""
                    folders_raw = s.value("last_cloud_folders", "") or ""
                finally:
                    s.endGroup()
            finally:
                s.endGroup()
            
            files_set = set()
            folders_dict = {}
            # Parse files
            if files_raw and isinstance(files_raw, str):
                for p in files_raw.split("\n"):
                    if p:
                        try:
                            norm = self._norm_rel_sanitized(p)
                            if norm:
                                files_set.add(norm)
                        except Exception:
                            files_set.add(p.replace("\\", "/").strip("/").casefold())
            if folders_raw and isinstance(folders_raw, str):
                for p in folders_raw.split("\n"):
                    if p:
                        try:
                            norm = self._norm_rel_sanitized(p)
                            if norm:
                                folders_dict[norm] = None  # Use None as placeholder value
                        except Exception:
                            folders_dict[p.replace("\\", "/").strip("/").casefold()] = None
            
            sync_log("LOAD_SNAPSHOT_FULL: folder_id={} files={} folders={}", 
                    folder_id, len(files_set), len(folders_dict))
            
            return {
                "files": files_set,
                "folders": folders_dict,
                "is_valid": True
            }
        except Exception as e:
            sync_exc(f"Failed to load full snapshot: {e}")
            return {"files": set(), "folders": {}, "is_valid": False}

    def _save_last_cloud_set(self, folder_id: int, cloud_files: list[dict], cloud_folders: dict = None) -> None:
        """Save cloud snapshot with files AND folders.
        
        Args:
            folder_id: Folder ID
            cloud_files: List of cloud file entries
            cloud_folders: Dict of {rel_path: folder_id} for folders (optional)
        """
        try:
            file_vals = []
            folder_vals = []
            
            # Collect files
            for cf in (cloud_files or []):
                # Skip folders - only track files (same logic as current_cloud_rels)
                if str(cf.get("type", "")).lower() == "folder" or bool(cf.get("is_dir")):
                    continue
                try:
                    # Use same normalization as current_cloud_rels for consistency
                    rel = self._norm_rel_sanitized(cf.get("rel_path", "") or cf.get("name", ""))
                except Exception:
                    rel = ""
                if rel:
                    file_vals.append(rel)
            
            # Collect folders
            if cloud_folders:
                for rel_path in (cloud_folders.keys() if isinstance(cloud_folders, dict) else []):
                    if rel_path:
                        folder_vals.append(rel_path)
            
            files_raw = "\n".join(sorted(set(file_vals)))
            folders_raw = "\n".join(sorted(set(folder_vals)))
            
            sync_log("SAVE_CLOUD_SNAPSHOT: folder_id={} files={} folders={} file_samples={} folder_samples={}", 
                    folder_id, len(file_vals), len(folder_vals), 
                    sorted(set(file_vals))[:10], sorted(set(folder_vals))[:10])
            
            s = self.settings
            s.beginGroup("sync2_state")
            try:
                s.beginGroup(f"f{normalize_id(folder_id)}")
                try:
                    s.setValue("last_cloud", files_raw)  # Legacy files key
                    s.setValue("last_cloud_folders", folders_raw)  # NEW folders key
                finally:
                    s.endGroup()
            finally:
                s.endGroup()
            try:
                s.sync()
            except Exception:
                pass
        except Exception as e:
            sync_exc(f"Failed to save cloud snapshot: {e}")
            pass

    def is_synced(self, folder_id) -> bool:
        try:
            sync_log("IS_SYNCED: folder_id={!r} type={}", folder_id, type(folder_id))
            key = self._fid_key(folder_id)
            sync_log("IS_SYNCED: key={!r} in map? {}", key, key in self.map)
        except ValueError:
            sync_log("IS_SYNCED: ValueError raised")
            return False
        return key in self.map

    def get_sync_path(self, folder_id) -> str:
        try:
            cfg = self.map.get(self._fid_key(folder_id))
        except ValueError:
            cfg = None
        return str(cfg.get("local_path")) if cfg else ""

    def add_sync(self, folder_id, local_path: str, project_id: int | str):
        # mark as not completed initial sync yet
        sync_log("ADD_SYNC: folder_id={!r} type={}", folder_id, type(folder_id))
        sync_log("ADD_SYNC: project_id={!r} type={}", project_id, type(project_id))
        sync_log("ADD_SYNC: local_path={!r}", local_path)

        # Reset per-folder state for this mapping.
        # Otherwise, re-adding a mapping for the same cloud folder may reuse an old
        # snapshot and treat an empty local folder as deletions.
        try:
            cleared = clear_sync_state(str(project_id), folder_id)
            sync_log("ADD_SYNC: clear_sync_state project_id={!r} folder_id={!r} ok={}", project_id, folder_id, bool(cleared))
        except Exception:
            pass

        try:
            key = self._fid_key(folder_id)
            sync_log("ADD_SYNC: key={!r}", key)
        except Exception as e:
            sync_log("ADD_SYNC: ERROR in _fid_key: {}", str(e))
            sync_exc(f"ADD_SYNC failed: {e}")
            raise

        try:
            self.map[key] = {"local_path": local_path, "project_id": str(project_id), "initial_ok": False}
            sync_log("ADD_SYNC: map key set successfully")
        except Exception as e:
            sync_log("ADD_SYNC: ERROR setting map: {}", str(e))
            sync_exc(f"ADD_SYNC failed to set map: {e}")
            raise

        try:
            self._save()
            sync_log("ADD_SYNC: _save() succeeded")
        except Exception as e:
            sync_log("ADD_SYNC: ERROR in _save(): {}", str(e))
            sync_exc(f"ADD_SYNC failed in _save(): {e}")
            raise

    def remove_sync(self, folder_id):
        try:
            key = self._fid_key(folder_id)
        except ValueError:
            return
        cfg = self.map.get(key) or {}
        project_id = cfg.get("project_id")
        if project_id not in (None, "", 0):
            try:
                cleared = clear_sync_state(str(project_id), folder_id)
                sync_log(
                    "REMOVE_SYNC: clear_sync_state project_id={!r} folder_id={!r} ok={}",
                    project_id,
                    folder_id,
                    bool(cleared),
                )
            except Exception:
                pass
        try:
            self._self_heal_caches(folder_id, reason="remove_sync")
        except Exception:
            pass
        self.map.pop(key, None)
        self._save()
        if not self.map and self.timer.isActive():
            self.timer.stop()

    def shutdown(self):
        """Stop all timers and threads during application shutdown."""
        try:
            if self.timer.isActive():
                self.timer.stop()
        except Exception:
            pass

        # Stop any ongoing auto-sync runner
        try:
            self._auto_sync_running = False
        except Exception:
            pass
        try:
            self._cleanup_auto_sync_thread()
        except Exception:
            pass

        for key, (th, worker) in list(self._initial_sync_threads.items()):
            try:
                if th.isRunning():
                    th.quit()
                    if QtCore.QThread.currentThread() is not th:
                        th.wait(1000)
            except Exception:
                pass
            try:
                self._initial_sync_threads.pop(key, None)
            except Exception:
                pass

    def set_initial_ok(self, folder_id, ok: bool = True):
        try:
            fid = self._fid_key(folder_id)
        except ValueError:
            return
        cfg = self.map.get(fid)
        if not cfg:
            return
        cfg["initial_ok"] = bool(ok)
        self._save()
        timer_active = False
        try:
            timer_active = bool(self.timer.isActive())
        except Exception:
            pass
        sync_log(
            "SYNC: initial_ok updated folder_id={} ok={} timer_active={}",
            fid,
            bool(ok),
            timer_active,
        )
        if bool(ok):
            try:
                has_ready = any(bool(c.get("initial_ok")) for c in self.map.values())
                if has_ready and not timer_active:
                    self._schedule_next_sync()
            except Exception:
                pass

    # --- sync logic ---
    
    # === Helper functions for folder synchronization ===
    
    @staticmethod
    def _normalize_folder_rel(rel: str) -> str:
        """Normalize relative folder path: unified '/' separator, strip edges, preserve names like '13'."""
        if not rel:
            return ""
        # Replace backslashes, strip slashes from edges, but keep internal structure
        normalized = rel.replace("\\", "/").strip("/")
        return normalized
    
    def _save_folder_snapshot(self, folder_id, folders_rel_list: list[str], files_rel_list: list[str]) -> None:
        """Save separate snapshots for folders and files to avoid overwriting."""
        try:
            group = self._fid_group(folder_id)
            # Normalize all paths before saving
            norm_folders = sorted(set(self._normalize_folder_rel(r) for r in folders_rel_list if r))
            norm_files = sorted(set(self._normalize_folder_rel(r) for r in files_rel_list if r))

            # Save folders snapshot
            self.settings.setValue(f"sync2_state/{group}/folders_snapshot", "\n".join(norm_folders))
            # Save files snapshot separately
            self.settings.setValue(f"sync2_state/{group}/files_snapshot", "\n".join(norm_files))
            self.settings.sync()

            sync_log("SYNC_DIRS snapshot saved: fid={} folders={} files={}", group, len(norm_folders), len(norm_files))
        except Exception as e:
            sync_exc(f"Failed to save folder snapshot: {e}")

    def _load_folder_snapshot(self, folder_id) -> tuple[set[str], set[str]]:
        """Load previous folder and file snapshots. Returns (folders_set, files_set)."""
        try:
            group = self._fid_group(folder_id)

            # Load folders
            folders_raw = self.settings.value(f"sync2_state/{group}/folders_snapshot", "") or ""
            folders_set = set(line.strip() for line in str(folders_raw).split("\n") if line.strip())

            # Load files
            files_raw = self.settings.value(f"sync2_state/{group}/files_snapshot", "") or ""
            files_set = set(line.strip() for line in str(files_raw).split("\n") if line.strip())

            sync_log("SYNC_DIRS snapshot loaded: fid={} folders={} files={}", group, len(folders_set), len(files_set))
            return folders_set, files_set
        except Exception as e:
            sync_exc(f"Failed to load folder snapshot: {e}")
            return set(), set()
    
    def _build_cloud_folder_cache(self, folder_node: dict, rel_prefix: str = "") -> dict[str, str]:
        """Build cache: {normalized_rel_path: folder_id} for all cloud folders recursively."""
        cache = {}
        try:
            # Add root
            if not rel_prefix:
                root_id = folder_node.get("id") or folder_node.get("folderId")
                if root_id:
                    cache[""] = normalize_id(root_id)
            
            # Process children
            children = folder_node.get("children", []) or folder_node.get("subfolders", []) or []
            for child in children:
                if not isinstance(child, dict):
                    continue
                
                child_name = str(child.get("name", ""))
                if not child_name:
                    continue
                
                child_rel = f"{rel_prefix}/{child_name}".strip("/") if rel_prefix else child_name
                child_rel_norm = self._normalize_folder_rel(child_rel)
                
                child_id = child.get("id") or child.get("folderId")
                if child_id:
                    cache[child_rel_norm] = normalize_id(child_id)
                
                # Recurse
                child_cache = self._build_cloud_folder_cache(child, child_rel)
                cache.update(child_cache)
        except Exception as e:
            sync_exc(f"Failed to build cloud folder cache: {e}")
        
        return cache

    def _compose_cloud_folder_map(
        self,
        root_folder: dict,
        dirs_dict: dict[str, str] | None,
    ) -> tuple[dict[str, dict], dict[str, int | None]]:
        """Combine collected folder names with resolved cloud folder IDs.

        Returns:
            meta_map: dict mapping normalized rel_path to metadata `{id, rel_path}`
            id_map: dict mapping normalized rel_path to folder_id (or None if unknown)
        """

        meta: dict[str, dict] = {}
        id_map: dict[str, int | None] = {}

        try:
            raw_cache = self._build_cloud_folder_cache(root_folder, "")
        except Exception as e:
            sync_exc(f"Failed to compose cloud folder map (cache build): {e}")
            raw_cache = {}

        sanitized_cache: dict[str, tuple[int | None, str]] = {}

        for raw_rel, folder_id in (raw_cache or {}).items():
            try:
                norm_rel = self._norm_rel_sanitized(raw_rel)
            except Exception:
                norm_rel = str(raw_rel or "").replace("\\", "/").strip("/").casefold()
            try:
                fid = normalize_id(folder_id)
            except Exception:
                fid = None
            sanitized_cache[norm_rel] = (fid, raw_rel)

        if "" not in sanitized_cache:
            try:
                raw_fid = root_folder.get("id") or root_folder.get("folderId") or 0
                try:
                    root_id = int(raw_fid)
                except (ValueError, TypeError):
                    root_id = raw_fid
            except Exception:
                root_id = 0
            sanitized_cache[""] = (root_id or None, "")

        if isinstance(dirs_dict, dict):
            for norm_rel, original in dirs_dict.items():
                if norm_rel in sanitized_cache:
                    fid, raw_rel = sanitized_cache[norm_rel]
                    if not raw_rel:
                        sanitized_cache[norm_rel] = (fid, original)
                else:
                    sanitized_cache[norm_rel] = (None, original)

        for norm_rel, (fid, raw_rel) in sanitized_cache.items():
            original_rel = raw_rel
            if isinstance(dirs_dict, dict):
                original_rel = dirs_dict.get(norm_rel, raw_rel)
            if original_rel is None:
                original_rel = raw_rel or norm_rel
            meta[norm_rel] = {
                "id": fid,
                "rel_path": original_rel,
            }
            id_map[norm_rel] = fid

        return meta, id_map
    
    def _find_cloud_folder_id(self, rel_path: str, cloud_cache: dict[str, int], 
                              root_folder_id: int, project_id: int | str) -> int | None:
        """Find folder_id for rel_path. First check cache, then walk cloud tree step-by-step (find-only)."""
        try:
            norm_rel = self._normalize_folder_rel(rel_path)
            
            # Check cache first
            if norm_rel in cloud_cache:
                fid = cloud_cache[norm_rel]
                sync_log("SYNC_DIRS find_folder: rel='{}' -> id={} (from cache)", norm_rel, fid)
                return fid
            
            # Walk step-by-step through cloud API (find-only, no creation)
            parts = [p for p in norm_rel.split("/") if p]
            if not parts:
                sync_log("SYNC_DIRS find_folder: rel='{}' -> id={} (root)", norm_rel, root_folder_id)
                return root_folder_id
            
            current_id = root_folder_id
            current_path = ""
            
            for part in parts:
                # Try to find this part in current folder's children
                try:
                    folder_details = self.api.get_folder_details(int(current_id), force=True)
                    children = folder_details.get("children", []) or folder_details.get("subfolders", []) or []
                    
                    found = False
                    for child in children:
                        if str(child.get("name", "")) == part:
                            raw_fid = child.get("id") or child.get("folderId")
                            try:
                                current_id = int(raw_fid)
                            except (ValueError, TypeError):
                                current_id = raw_fid
                            current_path = f"{current_path}/{part}".strip("/")
                            found = True
                            break
                    
                    if not found:
                        sync_log("SYNC_DIRS find_folder: rel='{}' -> NOT FOUND (stopped at '{}')", norm_rel, current_path)
                        return None
                    
                except Exception as e:
                    sync_log("SYNC_DIRS find_folder: rel='{}' -> ERROR at '{}': {}", norm_rel, current_path, str(e))
                    return None
            
            # Update cache
            cloud_cache[norm_rel] = current_id
            sync_log("SYNC_DIRS find_folder: rel='{}' -> id={} (found via walk)", norm_rel, current_id)
            return current_id
            
        except Exception as e:
            sync_exc(f"Failed to find cloud folder: {e}")
            return None
    
    def _validate_mapping_for_sync(self, folder_id: int | str, cfg: dict | None, *, sync_mode: str = "auto") -> list[str]:
        """Return a list of mapping validation errors (empty if OK)."""
        errs: list[str] = []
        try:
            fid = normalize_id(folder_id)
        except Exception:
            fid = str(folder_id or "")
        if not isinstance(cfg, dict):
            return ["mapping_missing"]

        local_path = str(cfg.get("local_path") or "").strip()
        project_id = cfg.get("project_id")

        if not local_path:
            errs.append("local_path_missing")
        else:
            try:
                if not os.path.exists(local_path):
                    errs.append("local_path_not_found")
                elif not os.path.isdir(local_path):
                    errs.append("local_path_not_directory")
            except Exception:
                errs.append("local_path_probe_failed")

        try:
            if not project_id or str(project_id).strip() in ("", "0"):
                errs.append("project_id_missing")
        except Exception:
            errs.append("project_id_missing")

        # initial_ok is required for auto sync; manual can still run, but should be explicit.
        try:
            initial_ok = bool(cfg.get("initial_ok", False))
        except Exception:
            initial_ok = False
        if (str(sync_mode or "auto") == "auto") and (not initial_ok):
            errs.append("initial_ok_false")

        if fid and fid in getattr(self, "_busy_folders", set()):
            errs.append("folder_busy")

        return errs

    def sync_all(self, *, sync_mode: str = "auto") -> list[dict]:
        if not getattr(self.api, 'token', None):
            return []
        # Notify UI for each auto sync run (UI may decide how to present it).
        try:
            if str(sync_mode or "auto") == "auto":
                self.autoSyncStarted.emit()
        except Exception:
            pass
        results: list[dict] = []
        try:
            for fid, cfg in list(self.map.items()):
                fid_norm = ""
                try:
                    fid_norm = normalize_id(fid)
                except Exception:
                    fid_norm = str(fid or "")

                mapping_errors = self._validate_mapping_for_sync(fid_norm, cfg, sync_mode=sync_mode)
                if mapping_errors:
                    if any(e in ("local_path_not_found", "local_path_not_directory") for e in mapping_errors):
                        sync_log(
                            "SYNC SAFETY ABORT: local root unavailable; preserving cloud",
                            component="SYNC",
                            op="validate",
                            result="skip",
                            extra=f"folder_id={fid_norm} local_root={(cfg or {}).get('local_path', '')!r} errors={mapping_errors} sync_mode={sync_mode}",
                        )
                    # For auto sync: skip invalid mappings; for manual: caller decides.
                    sync_log(
                        "SYNC_ALL: mapping validation failed",
                        component="SYNC",
                        op="validate",
                        result="skip" if str(sync_mode or "auto") == "auto" else "fail",
                        extra=f"folder_id={fid_norm} errors={mapping_errors} cfg={cfg!r}",
                    )
                    results.append({
                        "success": False,
                        "folder_id": fid_norm,
                        "project_id": (cfg or {}).get("project_id", 0) if isinstance(cfg, dict) else 0,
                        "local_root": (cfg or {}).get("local_path", "") if isinstance(cfg, dict) else "",
                        "mapping_errors": mapping_errors,
                        "blocked_by_guard": False,
                        "guard": None,
                        "stats": {"downloaded": 0, "uploaded": 0, "deleted_local": 0, "deleted_cloud": 0, "errors": []},
                        "errors": ["Mapping invalid: " + ",".join(mapping_errors)],
                    })
                    # auto mode: skip attempting sync
                    if str(sync_mode or "auto") == "auto":
                        continue

                if fid_norm in self._busy_folders:
                    # already included in mapping_errors, but keep a structured result
                    results.append({
                        "success": False,
                        "folder_id": fid_norm,
                        "project_id": (cfg or {}).get("project_id", 0) if isinstance(cfg, dict) else 0,
                        "local_root": (cfg or {}).get("local_path", "") if isinstance(cfg, dict) else "",
                        "mapping_errors": ["folder_busy"],
                        "blocked_by_guard": False,
                        "guard": None,
                        "stats": {"downloaded": 0, "uploaded": 0, "deleted_local": 0, "deleted_cloud": 0, "errors": []},
                        "errors": ["Folder busy"],
                    })
                    continue

                try:
                    # Mark busy to avoid parallel syncs (auto vs manual) for the same folder.
                    try:
                        self._busy_folders.add(fid_norm)
                    except Exception:
                        pass
                    try:
                        res = self._sync_one(fid_norm, cfg, sync_mode=sync_mode)
                    finally:
                        try:
                            self._busy_folders.discard(fid_norm)
                        except Exception:
                            pass
                except Exception as e:
                    sync_exc(f"SYNC_ALL: _sync_one exception folder_id={fid_norm} project_id={(cfg or {}).get('project_id')} local_path={(cfg or {}).get('local_path')}: {e}")
                    res = {
                        "success": False,
                        "folder_id": fid_norm,
                        "project_id": (cfg or {}).get("project_id", 0) if isinstance(cfg, dict) else 0,
                        "local_root": (cfg or {}).get("local_path", "") if isinstance(cfg, dict) else "",
                        "mapping_errors": [],
                        "blocked_by_guard": False,
                        "guard": None,
                        "stats": {"downloaded": 0, "uploaded": 0, "deleted_local": 0, "deleted_cloud": 0, "errors": [str(e)]},
                        "errors": [str(e)],
                    }
                results.append(res if isinstance(res, dict) else {"success": False, "folder_id": fid_norm, "errors": ["invalid_result"]})
        finally:
            try:
                if str(sync_mode or "auto") == "auto":
                    self.autoSyncFinished.emit()
            except Exception:
                pass
            # Legacy flag kept for backward compatibility; no longer gates UI signals.
            try:
                self._first_auto_sync_pending = False
            except Exception:
                pass

        # Summary log for observability (do not swallow failures).
        try:
            ok_n = sum(1 for r in results if isinstance(r, dict) and r.get("success"))
            blocked_n = sum(1 for r in results if isinstance(r, dict) and r.get("blocked_by_guard"))
            invalid_n = sum(1 for r in results if isinstance(r, dict) and r.get("mapping_errors"))
            fail_n = len(results) - ok_n
            sync_log(
                "SYNC_ALL summary",
                component="SYNC",
                op="summary",
                result="ok" if fail_n == 0 else "warn",
                extra=f"mode={sync_mode} total={len(results)} ok={ok_n} failed={fail_n} blocked_by_guard={blocked_n} mapping_invalid={invalid_n}",
            )
        except Exception:
            pass

        return results

    def sync_now(self, folder_id: int | str, *, allow_mass_delete: bool = False, sync_mode: str = "manual") -> dict:
        """Immediately sync the specified folder using new execute_sync system.
        
        Performs bidirectional sync:
        - Scans cloud and local filesystems
        - Downloads new/modified cloud files
        - Uploads new/modified local files
        - Handles deletions with safety guards
        - Manages conflict resolution
        """
        try:
            if not getattr(self.api, 'token', None):
                sync_log("SYNC_NOW: skipped - no auth token")
                return {"success": False, "folder_id": normalize_id(folder_id), "errors": ["no_auth"], "stats": {"downloaded": 0, "uploaded": 0, "deleted_local": 0, "deleted_cloud": 0, "errors": ["no_auth"]}}
            
            fid = normalize_id(folder_id)
            if fid in self._busy_folders:
                sync_log("SYNC_NOW: skipped - folder {} is busy", fid)
                return {"success": False, "folder_id": fid, "mapping_errors": ["folder_busy"], "errors": ["folder_busy"], "stats": {"downloaded": 0, "uploaded": 0, "deleted_local": 0, "deleted_cloud": 0, "errors": ["folder_busy"]}}
            
            cfg = self.map.get(fid)
            if not cfg:
                sync_log("SYNC_NOW: skipped - no config for folder {}", fid)
                return {"success": False, "folder_id": fid, "mapping_errors": ["mapping_missing"], "errors": ["mapping_missing"], "stats": {"downloaded": 0, "uploaded": 0, "deleted_local": 0, "deleted_cloud": 0, "errors": ["mapping_missing"]}}
            
            local_path = cfg.get("local_path") or ""
            if not local_path:
                sync_log("SYNC_NOW: skipped - no local path for folder {}", fid)
                return {"success": False, "folder_id": fid, "project_id": cfg.get("project_id", 0), "local_root": local_path, "mapping_errors": ["local_path_missing"], "errors": ["local_path_missing"], "stats": {"downloaded": 0, "uploaded": 0, "deleted_local": 0, "deleted_cloud": 0, "errors": ["local_path_missing"]}}
            
            project_id = cfg.get("project_id", 0)

            if not project_id:
                sync_log("SYNC_NOW: skipped - no project_id for folder {}", fid)
                return {"success": False, "folder_id": fid, "project_id": project_id, "local_root": local_path, "mapping_errors": ["project_id_missing"], "errors": ["project_id_missing"], "stats": {"downloaded": 0, "uploaded": 0, "deleted_local": 0, "deleted_cloud": 0, "errors": ["project_id_missing"]}}

            mapping_errors = self._validate_mapping_for_sync(fid, cfg, sync_mode=sync_mode)
            # For manual sync, still allow running when initial_ok is false, but surface it.
            if mapping_errors and ("initial_ok_false" in mapping_errors) and str(sync_mode or "manual") == "manual":
                mapping_errors = [e for e in mapping_errors if e != "initial_ok_false"]
            if mapping_errors:
                if any(e in ("local_path_not_found", "local_path_not_directory") for e in mapping_errors):
                    sync_log(
                        "SYNC SAFETY ABORT: local root unavailable; preserving cloud",
                        component="SYNC",
                        op="validate",
                        result="fail",
                        extra=f"folder_id={fid} project_id={project_id} local_path={local_path!r} errors={mapping_errors}",
                    )
                sync_log("SYNC_NOW: mapping validation failed", component="SYNC", op="validate", result="fail", extra=f"folder_id={fid} project_id={project_id} local_path={local_path!r} errors={mapping_errors}")
                return {"success": False, "folder_id": fid, "project_id": project_id, "local_root": local_path, "mapping_errors": mapping_errors, "errors": ["Mapping invalid: " + ",".join(mapping_errors)], "stats": {"downloaded": 0, "uploaded": 0, "deleted_local": 0, "deleted_cloud": 0, "errors": ["Mapping invalid"]}}
            
            # Mark folder as busy
            self._busy_folders.add(fid)
            try:
                sync_log("SYNC_NOW: starting for folder {} -> '{}'", fid, local_path)
                
                # Use integrated sync module
                result = sync_files_new(
                    api=self.api,
                    project_id=project_id,
                    folder_id=fid,
                    local_root=local_path,
                    dry_run=False,
                    allow_mass_delete=bool(allow_mass_delete),
                    sync_mode=str(sync_mode or "manual"),
                )
                
                if result.get("success"):
                    stats = result.get("stats", {})
                    sync_log("SYNC_NOW: completed - uploaded={} downloaded={} deleted_local={} deleted_cloud={} errors={}",
                            stats.get("uploaded", 0),
                            stats.get("downloaded", 0),
                            stats.get("deleted_local", 0),
                            stats.get("deleted_cloud", 0),
                            len(stats.get("errors", [])))
                    
                    # Update stats for UI
                    self._stats_files_uploaded = stats.get("uploaded", 0)
                    self._stats_files_downloaded = stats.get("downloaded", 0)
                    self._stats_deletes_local = stats.get("deleted_local", 0)
                    self._stats_deletes_remote = stats.get("deleted_cloud", 0)
                else:
                    errors = result.get("errors", [])
                    sync_log("SYNC_NOW: failed - errors={}", errors)
                # Attach mapping meta for callers/UI
                try:
                    if isinstance(result, dict):
                        result.setdefault("folder_id", fid)
                        result.setdefault("project_id", project_id)
                        result.setdefault("local_root", local_path)
                        result.setdefault("mapping_errors", [])
                except Exception:
                    pass

                if isinstance(result, dict) and result.get("success"):
                    try:
                        self.set_initial_ok(fid, True)
                        sync_log("SYNC_NOW complete: fid={} initial_ok set to True", fid)
                    except Exception as e:
                        sync_exc(f"Failed to set initial_ok after sync_now: {e}")

                return result if isinstance(result, dict) else {"success": False, "folder_id": fid, "errors": ["invalid_result"], "stats": {"downloaded": 0, "uploaded": 0, "deleted_local": 0, "deleted_cloud": 0, "errors": ["invalid_result"]}}
            finally:
                # Unmark folder as busy
                self._busy_folders.discard(fid)
                
        except Exception as e:
            sync_exc(f"SYNC_NOW: exception - {e}")
            try:
                fid = normalize_id(folder_id)
            except Exception:
                fid = str(folder_id or "")
            return {"success": False, "folder_id": fid, "errors": [str(e)], "stats": {"downloaded": 0, "uploaded": 0, "deleted_local": 0, "deleted_cloud": 0, "errors": [str(e)]}}
    
    def _set_busy(self, folder_id: int | str, busy: bool):
        try:
            fid = normalize_id(folder_id)
        except Exception:
            return
        if busy:
            self._busy_folders.add(fid)
        else:
            self._busy_folders.discard(fid)

    def _norm_folder_key(self, name: str) -> str:
        """Return the folder name with surrounding spaces trimmed."""
        try:
            return str(name or "").strip()
        except Exception:
            return str(name or "")

        """LEGACY (disabled): old sync implementation left in file.

        This block used undefined variables and caused IDE type warnings.
        It is kept only for reference and never executed.
        

        cloud_files = self._collect_cloud_files(folder, "", force_fresh=True)
        if (not cloud_files) and cfg.get("project_id", 0):
            try:
                cloud_files = self._collect_cloud_files_via_project_tree(cfg.get("project_id", 0), normalize_id(folder_id))
            except Exception:
                cloud_files = []
        local_files = self._collect_local_files(local_path)
        
        # === FOLDERS SYNCHRONIZATION: New isolated module ===
        cloud_dirs_dict: dict[str, str] = {}
        cloud_folder_cache: dict[str, int | None] = {}
        try:
            cloud_dirs_list = self._collect_cloud_dirs(folder, "")
            cloud_dirs_dict = {self._norm_rel_sanitized(rel): rel for rel in (cloud_dirs_list or [])}
            cloud_dirs_dict.setdefault("", "")
        except Exception as e:
            sync_exc("BUILD cloud_dirs failed: {}".format(e))
            # Don't activate protection or save snapshots on collection failure
            self._skip_protection_update = True
            self._skip_snapshot_save = True
        try:
            local_dirs_list = self._collect_local_dirs(local_path)
            local_dirs_dict = {self._norm_rel_sanitized(rel): rel for rel in (local_dirs_list or [])}
            local_dirs_dict.setdefault("", "")
        except Exception as e:
            sync_exc("BUILD local_dirs failed: {}".format(e))
            local_dirs_dict = {}
        
        # Build maps for compatibility with existing code
        try:
            local_map = local_dirs_dict if local_dirs_dict else {}
        except Exception as e:
            sync_exc("BUILD local_map failed: {}".format(e))
            local_map = {}

        try:
            cloud_map_meta, cloud_folder_cache = self._compose_cloud_folder_map(folder, cloud_dirs_dict)
        except Exception as e:
            sync_exc("COMPOSE cloud_map failed: {}".format(e))
            cloud_map_meta, cloud_folder_cache = {}, {}

        # expose cache for other helpers
        try:
            self.cloud_folder_cache = dict(cloud_folder_cache)
        except Exception:
            pass

        cloud_map = cloud_map_meta
        cloud_dirs_norm = set(cloud_map.keys())
        local_dirs_norm = set(local_map.keys())
        
        # Log DIRSETS diagnostics with samples
        local_samples = sorted(list(local_map.keys()))[:3] if local_map else []
        cloud_samples = sorted(list(cloud_map.keys()))[:3] if cloud_map else []
        sync_log("DIRSETS: local_map={} cloud_map={} samples_local={} samples_cloud={}", 
                len(local_map), len(cloud_map), local_samples, cloud_samples)
        
        # Build cloud folder cache: {norm_rel: folder_id}
        try:
            cloud_folder_cache = self._build_cloud_folder_cache(folder, "")
        except Exception as e:
            sync_exc("BUILD cloud_folder_cache failed: {}".format(e))
            cloud_folder_cache = {}
        
        # Load previous snapshots
        prev_folders, prev_files = self._load_folder_snapshot(fid)
        
        # If no previous snapshot exists - initialize from current cloud state (one-time)
        if not prev_folders:
            prev_folders = cloud_dirs_norm.copy()
            sync_log("SYNC_DIRS first-time snapshot init from cloud: folders={}", len(prev_folders))
        
        # Log current snapshot state
        sync_log("SYNC_DIRS snapshot: local_folders={} cloud_folders={} prev_folders={}", 
                len(local_dirs_norm), len(cloud_dirs_norm), len(prev_folders))
        if cloud_dirs_norm:
            samples = sorted(list(cloud_dirs_norm))[:5]
            sync_log("SYNC_DIRS cloud_folders samples: {}", samples)
        if local_dirs_norm:
            samples = sorted(list(local_dirs_norm))[:5]
            sync_log("SYNC_DIRS local_folders samples: {}", samples)
        
        # Log cloud_folder_cache keys (without values to avoid clutter)
        if cloud_folder_cache:
            cache_keys = sorted(list(cloud_folder_cache.keys()))[:10]
            sync_log("SYNC_DIRS cloud_folder_cache keys (top 10): {}", cache_keys)
        
        proj_id = cfg.get("project_id", 0)
        
        # 1) Restore missing local folders from cloud (CRITICAL FIX: Create ALL cloud folders locally)
        missing_local_dirs = sorted(cloud_dirs_norm - local_dirs_norm)
        if missing_local_dirs:
            sync_log("SYNC_DIRS restore: {} folders missing locally", len(missing_local_dirs))
            for norm_rel in missing_local_dirs:
                try:
                    parts = [_sanitize_filename(p) for p in norm_rel.split("/") if p]
                    dst = os.path.join(local_path, *parts)
                    if not os.path.isdir(dst):
                        os.makedirs(dst, exist_ok=True)
                        self._stats_created_dirs_local += 1
                        sync_log("MKDIR local rel='{}' path='{}'", norm_rel, dst)
                    else:
                        sync_log("MKDIR local rel='{}' path='{}' SKIP (already exists)", norm_rel, dst)
                except Exception as e:
                    sync_log("DIR_LOCAL ensure rel='{}' -> ERROR: {}", norm_rel, str(e))
        else:
            sync_log("SYNC_DIRS restore: no folders missing locally (all {} cloud folders present)", len(cloud_dirs_norm))
        
        # 2) Create missing cloud folders from local
        missing_cloud_dirs = sorted(local_dirs_norm - cloud_dirs_norm)
        created_folders_in_cloud = False
        if missing_cloud_dirs:
            try:
                precreate = bool(int(self.settings.value("sync/config/precreate_remote_folders", 1) or 1))
            except Exception:
                precreate = True
            
            if precreate:
                sync_log("SYNC_DIRS create: {} folders missing in cloud", len(missing_cloud_dirs))
                for norm_rel in missing_cloud_dirs:
                    try:
                        parts = [p for p in norm_rel.split("/") if p]
                        parent_entry = cloud_map.get("", {}) if isinstance(cloud_map, dict) else {}
                        parent_id = None
                        if isinstance(parent_entry, dict):
                            parent_id = parent_entry.get("id")
                        if not parent_id:
                            parent_id = normalize_id(folder_id)
                        ok = True
                        created_path_parts: list[str] = []
                        
                        for part in parts:
                            sanitized_part = _sanitize_filename(part)
                            created_path_parts.append(sanitized_part)
                            created_path = "/".join(created_path_parts)
                            norm_created = self._norm_rel_sanitized(created_path)

                            child_id = cloud_folder_cache.get(norm_created)
                            if not child_id:
                                try:
                                    parent_details = self.api.get_folder_details(parent_id, force=True)
                                    children = parent_details.get("children", []) or parent_details.get("subfolders", []) or []
                                    for child in children:
                                        if str(child.get("name", "")) == sanitized_part:
                                            raw_fid = child.get("id") or child.get("folderId")
                                            try:
                                                child_id = int(raw_fid)
                                            except (ValueError, TypeError):
                                                child_id = raw_fid
                                            break
                                except Exception:
                                    child_id = None

                            if not child_id:
                                try:
                                    child_id = self._ensure_subfolder(proj_id, parent_id, sanitized_part)
                                    created_folders_in_cloud = True
                                    self._stats_created_dirs_cloud += 1
                                    sync_log("MKDIR cloud rel='{}' parent_id={} -> child_id={}", 
                                            created_path, parent_id, child_id)
                                except Exception:
                                    child_id = None

                            if child_id:
                                parent_id = int(child_id)
                                cloud_folder_cache[norm_created] = int(child_id)
                                cloud_map[norm_created] = {"id": int(child_id), "rel_path": created_path}
                                cloud_dirs_norm.add(norm_created)
                            else:
                                ok = False
                                break
                        
                        if ok:
                            sync_log("DIR_REMOTE ensure rel='{}' id={} -> ok", norm_rel, parent_id)
                        else:
                            sync_log("DIR_REMOTE ensure rel='{}' -> FAILED", norm_rel)
                    except Exception as e:
                        sync_log("DIR_REMOTE ensure rel='{}' -> ERROR: {}", norm_rel, str(e))
            else:
                sync_log("SYNC_DIRS create: precreate disabled, skipped {} folders", len(missing_cloud_dirs))
        
        # 3) Save current snapshot (folders and files separately)
        cloud_files_rels = [self._normalize_folder_rel(cf.get("rel_path", "") or cf.get("name", "")) 
                           for cf in cloud_files if not bool(cf.get("is_dir"))]
        self._save_folder_snapshot(fid, list(cloud_dirs_norm), cloud_files_rels)
        
        # === END FOLDERS SYNCHRONIZATION ===
        
        # === BUILD CLOUD SNAPSHOT for use in deletion detection and protection ===
        try:
            cloud_snapshot = {
                "is_valid": True,
                "folders": cloud_map,  # Dict {norm_rel: folder_id or metadata}
                "files": cloud_files,
                "total_folders": len(cloud_map),
                "total_files": len([f for f in cloud_files if not bool(f.get("is_dir"))]),
                "errors": [],
                "timestamp": time.time(),
                "source": "sync_now_build"
            }
            sync_log("SNAPSHOT_BUILD (sync_now): folders={} files={} is_valid={}", 
                    len(cloud_map), len(cloud_files), cloud_snapshot["is_valid"])
        except Exception as e:
            sync_exc(f"Failed to build cloud_snapshot: {e}")
            cloud_snapshot = {
                "is_valid": False,
                "folders": {},
                "files": [],
                "total_folders": 0,
                "total_files": 0,
                "errors": [str(e)],
                "timestamp": time.time(),
                "source": "sync_now_build_failed"
            }
        
        try:
            sync_log("SYNC_NOW collected counts: cloud={} local={}", len(cloud_files or []), len(local_files or []))
        except Exception:
            pass

        # === TOMBSTONE INTEGRATION ===
        # Using stub objects - old system disabled, new system uses execute_sync()
        # NOTE: folder_id is numeric here; passing `fid` (normalized string) triggers type-check warnings.
        tombstone_store = TombstoneStore(self.settings, folder_id)
        pending_queue = PendingQueue(self.settings, folder_id)
        sig_cache = SignatureCache(self.settings, folder_id)
        coordinator = DeletionCoordinator(
            self.api, tombstone_store, pending_queue, self.settings,
            folder_id, self._retention_days
        )

        
        # Build current state sets
                # Build normalized file maps (exclude directories)
        cloud_by_rel = {
            self._norm_rel_sanitized((cf.get("rel_path") or cf.get("rel_path") or cf.get("name") or "")):
            cf
            for cf in (cloud_files or [])
            if not (str(cf.get("type", "")).lower() == "folder" or bool(cf.get("is_dir")))
        }
        local_by_rel = {
            self._norm_rel_sanitized((lf.get("rel_path") or lf.get("name") or "")):
            lf
            for lf in (local_files or [])
            if not bool(lf.get("is_dir"))
        }

        # Drop tombstoned entries right away to keep counts sane
        cloud_by_rel = {k: v for k, v in cloud_by_rel.items() if not tombstone_store.is_tombstoned(k)}
        local_by_rel = {k: v for k, v in local_by_rel.items() if not tombstone_store.is_tombstoned(k)}

        # Auto-unmark stale tombstones if the item exists again on any side
        try:
            present = set(cloud_by_rel.keys()) | set(local_by_rel.keys())
            ts_all = tombstone_store.list_all_tombstones()
            stale = [t for t in ts_all if self._norm_rel_sanitized(t.get("relpath", "")) in present]
            for t in stale:
                tombstone_store.remove_tombstone(t.get("relpath", ""))
            if stale:
                sync_log("TOMBSTONES cleaned: {}", [t.get("relpath", "") for t in stale])
        except Exception as e:
            sync_exc(f"TOMBSTONE_CLEANUP error: {e}")

        # Derive sets for deletion detection
        current_cloud_rels = set(cloud_by_rel.keys())
        current_local_rels = set(local_by_rel.keys())

        current_cloud_rels = {
        self._norm_rel_sanitized(cf.get("rel_path", "") or cf.get("name", ""))
        for cf in cloud_files
        if not (str(cf.get("type", "")).lower() == "folder" or bool(cf.get("is_dir")))
        and not self._should_ignore_rel(self._norm_rel_sanitized(cf.get("rel_path", "") or cf.get("name", "")))
        }

        current_local_rels = {
        self._norm_rel_sanitized(lf.get("rel_path", "") or lf.get("name", ""))
        for lf in local_files
        if not bool(lf.get("is_dir"))
        and not self._should_ignore_rel(self._norm_rel_sanitized(lf.get("rel_path", "") or lf.get("name", "")))
        }
        # Load previous state for deletion detection
        last_cloud_snapshot = self._load_last_cloud_set(normalize_id(folder_id))
        # Симметрично чистим прошлый снапшот от игнорируемых путей
        last_cloud_snapshot = {r for r in (last_cloud_snapshot or set()) if not self._should_ignore_rel(r)}
        last_local_sigs = sig_cache.get_all_local()
        # И локальные подписи тоже фильтруем тем же правилом
        last_local_sigs = {
            k: v for k, v in (last_local_sigs or {}).items()
            if not self._should_ignore_rel(self._norm_rel_sanitized(k))
        }
        # CRITICAL: Build stable string signatures from cache for rename detection
        # Use SAME normalization as current_local_rels to avoid false deletions
        last_local_sigs_str = {self._norm_rel_sanitized(k): self._sig_string_from_cache(v) for k, v in (last_local_sigs or {}).items()}
        # CRITICAL: Normalize last_local_rels keys to match current_local_rels
        last_local_rels = set(self._norm_rel_sanitized(k) for k in (last_local_sigs or {}).keys())
        
        # Debug: log snapshots (sync_now)
        sync_log("SNAPSHOT DEBUG (sync_now): last_cloud={} current_cloud={}", 
                sorted(list(last_cloud_snapshot)[:20]), sorted(list(current_cloud_rels)[:20]))
        sync_log("SNAPSHOT DEBUG (sync_now): last_local={} current_local={}", 
                sorted(list(last_local_rels)[:20]), sorted(list(current_local_rels)[:20]))
        
        # Detect deletions
        deleted_cloud_rels = last_cloud_snapshot - current_cloud_rels
        deleted_local_rels = last_local_rels - current_local_rels
        new_cloud_rels = current_cloud_rels - last_cloud_snapshot
        new_local_rels = current_local_rels - last_local_rels
        
        # Log deletion detection for debugging (sync_now)
        if deleted_cloud_rels:
            sync_log("DELETION DETECTION (sync_now): {} files deleted from cloud: {}", 
                    len(deleted_cloud_rels), sorted(deleted_cloud_rels))
        if deleted_local_rels:
            sync_log("DELETION DETECTION (sync_now): {} files deleted locally: {}", 
                    len(deleted_local_rels), sorted(deleted_local_rels))
        
        # Build signature maps for rename detection
        local_sigs = {}
        cloud_sigs = {}
        renames_local = {}
        renames_cloud = {}
        
        try:
            for lf in local_files:
                try:
                    # Skip directories - only process files
                    if bool(lf.get("is_dir")):
                        continue
                    relpath = self._norm_rel_sanitized(lf.get("rel_path", "") or lf.get("name", ""))
                    sig = RenameDetector.compute_signature(lf)
                    if sig:
                        local_sigs[relpath] = sig
                except Exception as e:
                    sync_exc(f"Failed to compute signature for local file: {e}")
            
            for cf in cloud_files:
                try:
                    relpath = self._norm_rel_sanitized(cf.get("rel_path", "") or cf.get("name", ""))
                    if str(cf.get("type", "")).lower() == "folder" or bool(cf.get("is_dir")):
                        continue
                    # Use version/etag as signature for cloud files
                    sig = str(cf.get('version', '') or cf.get('etag', ''))
                    if sig:
                        cloud_sigs[relpath] = sig
                except Exception as e:
                    sync_exc(f"Failed to compute signature for cloud file: {e}")
            
            # Detect renames (local) using unified signature strings
            renames_local = RenameDetector.detect_renames(
                deleted_local_rels,
                new_local_rels,
                {**last_local_sigs_str, **local_sigs}
            )
        except Exception as e:
            sync_exc(f"Failed to detect renames: {e}")
            renames_local = {}
        
        # Detect renames (cloud) - harder without stored cloud signatures, skip for now
        renames_cloud = {}
        
        # Process renames (no tombstone needed)
        try:
            for old_path, new_path in renames_local.items():
                try:
                    coordinator.handle_local_rename(old_path, new_path)
                    # Also update signature cache
                    if old_path in last_local_sigs:
                        sig_cache.remove_signature(old_path, 'local')
                except Exception as e:
                    sync_exc(f"Failed to handle local rename {old_path} -> {new_path}: {e}")
            
            for old_path, new_path in renames_cloud.items():
                try:
                    coordinator.handle_remote_rename(old_path, new_path)
                except Exception as e:
                    sync_exc(f"Failed to handle remote rename {old_path} -> {new_path}: {e}")
        except Exception as e:
            sync_exc(f"Failed to process renames: {e}")
        
        # --- FOLDER deletions and renames detection (local/cloud) ---
        try:
            # Build previous and current directory sets (normalized)
            try:
                prev_folders_raw = self.settings.value(f"sync2_state/{self._fid_group(folder_id)}/last_folders", "") or ""
                prev_local_dirs = set(self._norm_rel_sanitized(p.strip()) for p in str(prev_folders_raw).split("\n") if p.strip())
            except Exception as e:
                sync_exc("BUILD prev_local_dirs from settings failed: {}".format(e))
                prev_local_dirs = set()
            if not prev_local_dirs:
                # Derive from previous local file set
                prev_local_dirs = set()
                for fp in (last_local_rels or set()):
                    parts = [p for p in str(fp).split('/') if p]
                    if parts[:-1]:
                        prev_local_dirs.add("/".join(parts[:-1]))
            current_local_dirs = set(local_map.keys())

            # Cloud dir sets - build from cloud_map instead of cloud_snapshot
            current_cloud_dirs = set(k for k in cloud_map.keys() if k)
            
            # Build prev_cloud_dirs from last_cloud_snapshot (file paths)
            try:
                prev_cloud_dirs = set()
                for fp in (last_cloud_snapshot or set()):
                    parts = [p for p in str(fp).split('/') if p]
                    if parts[:-1]:
                        prev_cloud_dirs.add("/".join(parts[:-1]))
            except Exception as e:
                sync_exc("BUILD prev_cloud_dirs from last_cloud_snapshot failed: {}".format(e))
                prev_cloud_dirs = set()

            # Deleted/new dir sets
            deleted_local_dirs = set(prev_local_dirs) - set(current_local_dirs)
            new_local_dirs = set(current_local_dirs) - set(prev_local_dirs)
            deleted_cloud_dirs = set(prev_cloud_dirs) - set(current_cloud_dirs)
            new_cloud_dirs = set(current_cloud_dirs) - set(prev_cloud_dirs)

            # Detect folder renames
            folder_renames_local = self._detect_folder_renames_local(
                set(self._norm_rel_sanitized(x) for x in (last_local_rels or set())),
                set(current_local_rels or set()),
                set(deleted_local_dirs),
                set(new_local_dirs),
            )
            folder_renames_cloud = self._detect_folder_renames_cloud(
                set(self._norm_rel_sanitized(x) for x in (last_cloud_snapshot or set())),
                set(current_cloud_rels or set()),
                set(deleted_cloud_dirs),
                set(new_cloud_dirs),
            )

            # Folder deletions excluding renames
            real_deleted_local_dirs = set(deleted_local_dirs) - set(folder_renames_local.keys())
            real_deleted_cloud_dirs = set(deleted_cloud_dirs) - set(folder_renames_cloud.keys())

            if real_deleted_local_dirs:
                sync_log("REAL DIR DELETIONS local: {} dirs: {}", len(real_deleted_local_dirs), sorted(real_deleted_local_dirs))
            if real_deleted_cloud_dirs:
                sync_log("REAL DIR DELETIONS cloud: {} dirs: {}", len(real_deleted_cloud_dirs), sorted(real_deleted_cloud_dirs))

            # Create folder tombstones
            for drel in real_deleted_local_dirs:
                try:
                    if not tombstone_store.is_tombstoned(drel):
                        coordinator.on_local_folder_deletion(drel)
                except Exception as e:
                    sync_exc(f"Failed to tombstone local folder deletion '{drel}': {e}")
            for drel in real_deleted_cloud_dirs:
                try:
                    if not tombstone_store.is_tombstoned(drel):
                        coordinator.on_remote_folder_deletion(drel)
                except Exception as e:
                    sync_exc(f"Failed to tombstone cloud folder deletion '{drel}': {e}")
        except Exception as e:
            sync_exc(f"Failed folder delete/rename detection (sync_now): {e}")

        # Process real deletions (not renames) -> create tombstones
        real_deleted_local = deleted_local_rels - set(renames_local.keys())
        real_deleted_cloud = deleted_cloud_rels - set(renames_cloud.keys())
        
        # Debug: log real deletions
        if real_deleted_cloud:
            sync_log("REAL DELETIONS cloud: {} files: {}", len(real_deleted_cloud), sorted(real_deleted_cloud))
        if real_deleted_local:
            sync_log("REAL DELETIONS local: {} files: {}", len(real_deleted_local), sorted(real_deleted_local))
        
        # Mass deletion guard with robust baseline and snapshot sanity
        prev_total_files = len(last_cloud_snapshot | last_local_rels)
        current_total_files = len(current_cloud_rels | current_local_rels)
        # Include folder deletions into protection calculus
        try:
            _fd_loc = len(real_deleted_local_dirs)
        except Exception:
            _fd_loc = 0
        try:
            _fd_cld = len(real_deleted_cloud_dirs)
        except Exception:
            _fd_cld = 0
        total_deletions = len(real_deleted_local) + len(real_deleted_cloud) + _fd_loc + _fd_cld
        
        # Enhanced logging BEFORE protection activation
        try:
            deletion_ratio = total_deletions / max(prev_total_files, 1)
            sync_log("PROTECTION basis: deleted={} (files_local={} files_cloud={} dirs_local={} dirs_cloud={}) prev_total={} current_total={} ratio={:.2%}", 
                    total_deletions, len(real_deleted_local), len(real_deleted_cloud), _fd_loc, _fd_cld,
                    prev_total_files, current_total_files, deletion_ratio)
        except Exception:
            pass
        
        protection_active = self._update_mass_delete_protection(
            fid,
            deleted_count=total_deletions,
            prev_total=prev_total_files,
            current_total=current_total_files,
        )
        
        try:
            for relpath in real_deleted_local:
                try:
                    if not tombstone_store.is_tombstoned(relpath):
                        last_sig = last_local_sigs.get(relpath, {})
                        # Find cloud version if exists
                        cloud_ver = None
                        for cf in cloud_files:
                            cf_rel = self._norm_rel_sanitized(cf.get("rel_path", "") or cf.get("name", ""))
                            if cf_rel == relpath:
                                cloud_ver = str(cf.get('version', '') or cf.get('etag', ''))
                                break
                        coordinator.on_local_deletion(relpath, last_sig, cloud_ver)
                except Exception as e:
                    sync_exc(f"Failed to process local deletion for '{relpath}': {e}")
        except Exception as e:
            sync_exc(f"Failed to process local deletions: {e}")
        
        try:
            for relpath in real_deleted_cloud:
                try:
                    if not tombstone_store.is_tombstoned(relpath):
                        last_ver = ""  # We don't store cloud versions yet
                        local_sig = last_local_sigs.get(relpath, {})
                        sync_log("CLOUD DELETION detected: rel='{}' creating tombstone for local deletion", relpath)
                        coordinator.on_remote_deletion(relpath, last_ver, local_sig)
                    else:
                        sync_log("CLOUD DELETION detected: rel='{}' already tombstoned, skipping", relpath)
                except Exception as e:
                    sync_exc(f"Failed to process cloud deletion for '{relpath}': {e}")
        except Exception as e:
            sync_exc(f"Failed to process cloud deletions: {e}")
        
        # Process pending operations BEFORE regular sync
        try:
            # Ensure cloud_snapshot is always initialized (fallback if not built earlier)
            if not isinstance(cloud_snapshot, dict):
                cloud_snapshot = {
                    "folders": cloud_map, 
                    "files": cloud_files or [],
                    "is_valid": False, 
                    "source": "fallback",
                    "errors": ["not_built_earlier"]
                }
                sync_log("SNAPSHOT fallback -> folders={} files={}", len(cloud_map), len(cloud_files or []))
            
            if (not self._is_protection_active(fid)) or self._execute_queue_under_protection():
                # Extract cloud folders map from snapshot
                cloud_folders_map = cloud_snapshot.get("folders", {}) if isinstance(cloud_snapshot, dict) else {}
                pending_ops = pending_queue.get_operations()
                sync_log("PENDING size={} protect={}", len(pending_ops), self._is_protection_active(fid))
                coordinator.process_pending_operations(local_path, cloud_files, local_files, cloud_folders_map)
            else:
                sync_log("PENDING_SKIP: protection active and execution disabled by setting for folder_id={}", fid)
        except Exception as e:
            sync_exc(f"Failed to process pending operations: {e}")
        
        # === NEW: Safe folder cleanup using validated cloud snapshot ===
        try:
            # If snapshot is valid but trivial (only root and no files), derive from collected cloud dirs
            cloud_snapshot_for_cleanup = cloud_snapshot
            try:
                folders_map = cloud_snapshot.get("folders", {}) if isinstance(cloud_snapshot, dict) else {}
                total_files_now = int(cloud_snapshot.get("total_files", 0) or 0) if isinstance(cloud_snapshot, dict) else 0
                only_root = (len([k for k in folders_map.keys() if k]) == 0)
                if cloud_snapshot.get("is_valid") and only_root and total_files_now == 0:
                    cloud_snapshot_for_cleanup = {
                        "is_valid": True,
                        "folders": cloud_map,
                        "files": [],
                        "errors": ["derived_from_cloud_dirs"],
                        "timestamp": time.time(),
                    }
                    sync_log("FOLDER_CLEANUP (periodic): using derived snapshot from cloud_map (valid but empty original)")
            except Exception:
                pass

            cleanup_stats = self._safe_cleanup_folders(
                local_path, 
                cloud_snapshot_for_cleanup, 
                dry_run=self._dry_run_mode
            )
            
            if cleanup_stats.get("skipped_reason"):
                sync_log("FOLDER_CLEANUP: SKIPPED - reason='{}'", cleanup_stats["skipped_reason"])
                # Fallback: derive snapshot from collected cloud dirs when validation failed
                if str(cleanup_stats.get("skipped_reason")) == "invalid_cloud_snapshot":
                    try:
                        derived_snapshot = {
                            "is_valid": True,
                            "folders": cloud_map,
                            "files": [],
                            "errors": ["derived_from_cloud_dirs"],
                            "timestamp": time.time()
                        }
                        stats2 = self._safe_cleanup_folders(local_path, derived_snapshot, dry_run=self._dry_run_mode)
                        if stats2.get("skipped_reason"):
                            sync_log("FOLDER_CLEANUP (derived): SKIPPED - reason='{}'", stats2.get("skipped_reason"))
                        else:
                            sync_log("FOLDER_CLEANUP (derived): completed - deleted={} skipped_nonempty={} skipped_errors={}",
                                    stats2.get("folders_deleted", 0), stats2.get("folders_skipped_nonempty", 0), stats2.get("folders_skipped_errors", 0))
                    except Exception as e:
                        sync_exc(f"Failed derived folder cleanup: {e}")
            else:
                sync_log("FOLDER_CLEANUP: completed - deleted={} skipped_nonempty={} skipped_errors={} dry_run={}", 
                        cleanup_stats.get("folders_deleted", 0),
                        cleanup_stats.get("folders_skipped_nonempty", 0),
                        cleanup_stats.get("folders_skipped_errors", 0),
                        cleanup_stats.get("dry_run", False))
        except Exception as e:
            sync_exc(f"Failed safe folder cleanup: {e}")

        # Persist latest folder snapshot (for robust folder delete/rename detection)
        try:
            current_folders_list = sorted(set(cloud_map.keys()) | set(local_map.keys()))
            self.settings.setValue(f"sync2_state/{self._fid_group(folder_id)}/last_folders", "\n".join(current_folders_list))
        except Exception:
            pass

        # 2/3) Smart per-file strategy based on comparison (skip tombstoned files)
        # Index (normalized and sanitized, case-insensitive)
        cloud_by_rel = {self._norm_rel_sanitized(cf.get("rel_path") or cf.get("name") or ""): cf for cf in cloud_files}
        
        # IMPROVED: Filter folders with better diagnostics
        cloud_by_rel_before_folder_filter = len(cloud_by_rel)
        cloud_by_rel = {
            k: v for k, v in cloud_by_rel.items()
            if not (str(v.get("type") or "").lower() == "folder" or bool(v.get("is_dir")))
        }
        sync_log("FILTER folders: before={} after={} filtered_out={}", 
                cloud_by_rel_before_folder_filter, len(cloud_by_rel), 
                cloud_by_rel_before_folder_filter - len(cloud_by_rel))
        
        # Filter out tombstoned files from cloud side BEFORE building all_rels
        cloud_by_rel_before_tombstone = len(cloud_by_rel)
        tombstoned_cloud = [k for k in cloud_by_rel.keys() if tombstone_store.is_tombstoned(k)]
        cloud_by_rel = {k: v for k, v in cloud_by_rel.items() if not tombstone_store.is_tombstoned(k)}
        if tombstoned_cloud:
            sync_log("FILTER tombstoned cloud files: {} items: {}", len(tombstoned_cloud), tombstoned_cloud[:10])
        
        # Files only: exclude directories from per-file decision loop
        local_by_rel = {self._norm_rel_sanitized(lf.get("rel_path") or lf.get("name") or ""): lf for lf in local_files if not bool(lf.get("is_dir"))}
        # --- Tombstone sanity: возвращаем элементы, ошибочно исключённые из облака,
        # если они присутствуют локально (stale tombstone), и чистим такие tombstone
        salvaged = 0
        for cf in (cloud_files or []):
            k = self._norm_rel_sanitized(cf.get("rel_path", "") or cf.get("name", ""))
            if (str(cf.get("type", "")).lower() == "folder") or bool(cf.get("is_dir")):
                continue
            if self._should_ignore_rel(k):
                continue
            if tombstone_store.is_tombstoned(k) and (k in local_by_rel):
                cloud_by_rel[k] = cf  # вернуть в сравнение
                try:
                    tombstone_store.remove_tombstone(k)  # устарел — чистим
                except Exception:
                    pass
                salvaged += 1
        if salvaged:
            sync_log("FILTER tombstones: cleared stale entries and salvaged {} item(s) present on the other side", salvaged)

        # Локальная сторона: исключаем tombstone ТОЛЬКО если этого файла нет в облаке
        tombstoned_local = []
        for k in list(local_by_rel.keys()):
            if tombstone_store.is_tombstoned(k) and k not in cloud_by_rel:
                tombstoned_local.append(k)
                local_by_rel.pop(k, None)
        if tombstoned_local:
            sync_log("FILTER tombstoned local files (no cloud counterpart): {} items: {}", len(tombstoned_local), tombstoned_local[:10])

        # Filter out tombstoned files from local side BEFORE building all_rels
        local_by_rel_before_tombstone = len(local_by_rel)
        tombstoned_local = [k for k in local_by_rel.keys() if tombstone_store.is_tombstoned(k)]
        local_by_rel = {k: v for k, v in local_by_rel.items() if not tombstone_store.is_tombstoned(k)}
        if tombstoned_local:
            sync_log("FILTER tombstoned local files: {} items: {}", len(tombstoned_local), tombstoned_local[:10])
        
        all_rels = set(cloud_by_rel.keys()) | set(local_by_rel.keys())
        sync_log("SYNC_FILES: cloud_files_map={} local_files_map={} all_rels={} samples={}",
                len(cloud_by_rel), len(local_by_rel), len(all_rels), sorted(list(all_rels))[:10])
        proj_id = cfg.get("project_id", 0)
        for rel in sorted(all_rels):
            # Double-check (should never happen now, but keep for safety)
            if tombstone_store.is_tombstoned(rel):
                sync_log("SYNC_NOW skip (tombstoned): rel='{}'", rel)
                continue
            
            lf = local_by_rel.get(rel)
            cf = cloud_by_rel.get(rel)
            sync_log("SYNC_FILE_COMPARE: rel='{}' has_local={} has_cloud={}", rel, lf is not None, cf is not None)
            try:
                self._log_time(rel, lf, cf)
            except Exception as e:
                sync_exc(f"TIME log failed for rel='{rel}': {e}")
            
            # SAFE: Wrap decision in try/except
            try:
                act, reason, lmt, cmt, csrc, craw = self._decide_action(lf, cf)
            except Exception as e:
                sync_exc(f"DECISION failed for rel='{rel}': {e}")
                continue  # Skip this file and proceed to next
            
            lct = self._local_creation_time(lf)
            try:
                from datetime import timedelta
                try:
                    tz_local = int((datetime.now().astimezone().utcoffset() or timedelta()).total_seconds() // 60)
                except Exception:
                    tz_local = 0
                try:
                    tz_cloud = int(_cloud_tz_offset_minutes())
                except Exception:
                    tz_cloud = 0
                try:
                    lmt_str = _user_display_datetime(float(lmt or 0)) if (lmt or 0) > 0 else ""
                except Exception:
                    lmt_str = ""
                sync_log(
                    "DECISION rel='{}' tz_local={} tz_cloud={} lmt={} cmt={} csrc='{}' created_raw='{}' lmt_str='{}' lct={} reason='{}' -> {}",
                    rel, int(tz_local), int(tz_cloud), float(lmt or 0), (None if cmt is None else float(cmt)), (csrc or ''), (craw or ''), lmt_str, (None if lct is None else float(lct)), reason, act,
                )
            except Exception:
                pass
            if act == 'download' and cf is not None:
                try:
                    self.syncItem.emit('download', rel, normalize_id(folder_id))
                except Exception:
                    pass
                # SAFE: Wrap download in try/except to prevent single file error from breaking entire sync
                try:
                    self._download_if_newer(cf, local_path, normalize_id(folder_id))
                except Exception as e:
                    sync_exc(f"DOWNLOAD_EXCEPTION: rel='{rel}' error={e}")
                try:
                    self._log_time(rel, os.path.join(local_path, *[p for p in (rel.split('/') if isinstance(rel, str) else []) if p]), cf)
                except Exception:
                    pass
            elif act == 'upload' and lf is not None:
                try:
                    self.syncItem.emit('upload', rel, normalize_id(folder_id))
                except Exception:
                    pass
                # SAFE: Wrap upload in try/except to prevent single file error from breaking entire sync
                try:
                    self._upload_if_newer(lf, local_path, normalize_id(folder_id), cloud_files, proj_id)
                except Exception as e:
                    sync_exc(f"UPLOAD_EXCEPTION: rel='{rel}' error={e}")
                try:
                    self._log_time(rel, lf.get('path') if isinstance(lf, dict) else None, cf)
                except Exception:
                    pass
        # 4) Save snapshot of cloud after sync - use EXISTING cloud_files, not fresh!
        try:
            # Don't fetch fresh - it doesn't contain file list! Use cloud_files we already have
            # CRITICAL: Also save cloud_map (folders) to enable folder deletion detection
            sync_log("SNAPSHOT SAVE (sync_now): cloud_files={} cloud_folders={}", 
                    len(cloud_files), len(cloud_map))
            self._save_last_cloud_set(normalize_id(folder_id), cloud_files, cloud_folders=cloud_map)
        except Exception as e:
            sync_exc(f"Failed to save cloud snapshot in sync_now: {e}")
        
        # Update signature cache for next cycle
        try:
            # Store local signatures (FILES ONLY - exclude directories)
            for lf in local_files:
                if bool(lf.get("is_dir")):
                    continue
                relpath = self._norm_rel_sanitized(lf.get("rel_path", "") or lf.get("name", ""))
                path = lf.get('path', '')
                if path and os.path.exists(path):
                    stat = os.stat(path)
                    sig_cache.store_signature(relpath, 'local', {
                        "mtime": stat.st_mtime,
                        "size": stat.st_size,
                        "last_seen": time.time()
                    })
            
            # Store cloud signatures
            for cf in cloud_files:
                if str(cf.get("type", "")).lower() == "folder" or bool(cf.get("is_dir")):
                    continue
                relpath = self._norm_rel_sanitized(cf.get("rel_path", "") or cf.get("name", ""))
                sig_cache.store_signature(relpath, 'remote', {
                    "version": str(cf.get('version', '') or cf.get('etag', '')),
                    "last_seen": time.time()
                })
        except Exception as e:
            sync_exc(f"Failed to update signature cache: {e}")
        
        # Periodic cleanup (once per ~48 sync cycles = ~1 day)
        try:
            self._cleanup_counter = getattr(self, '_cleanup_counter', 0) + 1
            if self._cleanup_counter >= 48:
                cleaned = coordinator.cleanup_expired_tombstones()
                if cleaned > 0:
                    sync_log("CLEANUP expired tombstones: count={}", cleaned)
                self._cleanup_counter = 0
        except Exception:
            pass
        
        # === SYNC SUMMARY ===
        try:
            summary_stats = {
                "created_dirs_local": getattr(self, '_stats_created_dirs_local', 0),
                "created_dirs_cloud": getattr(self, '_stats_created_dirs_cloud', 0),
                "files_uploaded": getattr(self, '_stats_files_uploaded', 0),
                "files_downloaded": getattr(self, '_stats_files_downloaded', 0),
                "deletes_local": getattr(self, '_stats_deletes_local', 0),
                "deletes_remote": getattr(self, '_stats_deletes_remote', 0),
            }
            sync_log("SYNC_SUMMARY: created_dirs_local={} created_dirs_cloud={} files_uploaded={} files_downloaded={} deletes_local={} deletes_remote={}",
                    summary_stats["created_dirs_local"], summary_stats["created_dirs_cloud"],
                    summary_stats["files_uploaded"], summary_stats["files_downloaded"],
                    summary_stats["deletes_local"], summary_stats["deletes_remote"])
            # Reset stats counters
            self._stats_created_dirs_local = 0
            self._stats_created_dirs_cloud = 0
            self._stats_files_uploaded = 0
            self._stats_files_downloaded = 0
            self._stats_deletes_local = 0
            self._stats_deletes_remote = 0
        except Exception:
            pass
        
        # FIXED: Set initial_ok flag after successful sync_now to enable periodic sync
        try:
            self.set_initial_ok(normalize_id(folder_id), True)
            sync_log("SYNC_NOW complete: fid={} initial_ok set to True", normalize_id(folder_id))
        except Exception as e:
            sync_exc(f"Failed to set initial_ok after sync_now: {e}")

        """

    # --- busy guards API ---

    def _set_busy(self, folder_id: int | str, busy: bool):
        try:
            fid = normalize_id(folder_id)
        except Exception:
            return
        if busy:
            self._busy_folders.add(fid)
        else:
            self._busy_folders.discard(fid)

    def _sync_one(self, folder_id: int | str, cfg: dict, *, sync_mode: str = "auto") -> dict:
        """Sync one folder for sync_all(auto) runner.

        Important: structured return is consumed by UI (autoSyncResult) and sync_all summary.
        """
        try:
            from larix_nexus.utils.logging import new_trace_id, is_dry_run

            trace_id = new_trace_id()
            folder_id_norm = normalize_id(folder_id)
            local_path = (cfg or {}).get("local_path") or ""
            project_id = (cfg or {}).get("project_id", 0)

            sync_log(
                "Sync started",
                component="SYNC",
                op="start",
                trace_id=trace_id,
                result="ok",
                extra=f"folder_id={folder_id_norm} project_id={project_id} sync_mode={sync_mode}",
            )

            if is_dry_run():
                sync_log(
                    "AUTO_SYNC: DRY_RUN=1 - sync operations will not be executed",
                    component="SYNC",
                    op="dry_run",
                    trace_id=trace_id,
                    result="skip",
                    extra=f"folder_id={folder_id_norm} sync_mode={sync_mode}",
                )

            result = sync_files_new(
                api=self.api,
                project_id=project_id,
                folder_id=folder_id_norm,
                local_root=local_path,
                dry_run=is_dry_run(),
                sync_mode=str(sync_mode or "auto"),
            )

            # If something changed, ask UI to refresh current view.
            try:
                if isinstance(result, dict) and result.get("success"):
                    stats = result.get("stats", {}) if isinstance(result.get("stats"), dict) else {}
                    changed = (
                        int(stats.get("uploaded", 0) or 0)
                        + int(stats.get("downloaded", 0) or 0)
                        + int(stats.get("deleted_local", 0) or 0)
                        + int(stats.get("deleted_cloud", 0) or 0)
                        + int(stats.get("created_dirs_local", 0) or 0)
                        + int(stats.get("created_dirs_cloud", 0) or 0)
                    )
                    if changed > 0:
                        try:
                            self.refreshRequested.emit()
                        except Exception:
                            pass
            except Exception:
                pass

            # Attach mapping meta for upstream summary/UI.
            try:
                if isinstance(result, dict):
                    result.setdefault("folder_id", folder_id_norm)
                    result.setdefault("project_id", project_id)
                    result.setdefault("local_root", local_path)
                    result.setdefault("mapping_errors", [])
            except Exception:
                pass

            if not isinstance(result, dict):
                result = {
                    "success": False,
                    "folder_id": folder_id_norm,
                    "project_id": project_id,
                    "local_root": local_path,
                    "mapping_errors": [],
                    "blocked_by_guard": False,
                    "guard": None,
                    "stats": {"downloaded": 0, "uploaded": 0, "deleted_local": 0, "deleted_cloud": 0, "errors": ["invalid_result"]},
                    "errors": ["invalid_result"],
                }

            sync_log(
                "Sync finished",
                component="SYNC",
                op="finish",
                trace_id=trace_id,
                result="ok" if result.get("success") else "fail",
                extra=f"folder_id={folder_id_norm} sync_mode={sync_mode} errors={len(result.get('errors', []) or [])}",
            )
            try:
                if str(sync_mode or "auto") == "auto":
                    if result.get("blocked_by_guard"):
                        guard = result.get("guard") if isinstance(result.get("guard"), dict) else {}
                        sync_log(
                            "AUTO_SYNC: folder_id={} blocked_by_guard reason={} actions_by_type={}",
                            folder_id_norm,
                            guard.get("reason") or result.get("errors"),
                            guard.get("actions_by_type"),
                        )
                    elif not result.get("success"):
                        sync_log(
                            "AUTO_SYNC: folder_id={} failed errors={}",
                            folder_id_norm,
                            (result.get("errors") or [])[:5],
                        )
                    else:
                        stats = result.get("stats", {}) if isinstance(result.get("stats"), dict) else {}
                        changed = (
                            int(stats.get("uploaded", 0) or 0)
                            + int(stats.get("downloaded", 0) or 0)
                            + int(stats.get("deleted_local", 0) or 0)
                            + int(stats.get("deleted_cloud", 0) or 0)
                        )
                        if changed <= 0:
                            sync_log(
                                "AUTO_SYNC: folder_id={} completed with no file changes",
                                folder_id_norm,
                            )
            except Exception:
                pass
            return result
        except Exception as e:
            sync_exc(f"_sync_one failed for folder_id={folder_id}: {e}")
            try:
                fid_norm = normalize_id(folder_id)
            except Exception:
                fid_norm = str(folder_id or "")
            return {
                "success": False,
                "folder_id": fid_norm,
                "project_id": (cfg or {}).get("project_id", 0) if isinstance(cfg, dict) else 0,
                "local_root": (cfg or {}).get("local_path", "") if isinstance(cfg, dict) else "",
                "mapping_errors": [],
                "blocked_by_guard": False,
                "guard": None,
                "stats": {"downloaded": 0, "uploaded": 0, "deleted_local": 0, "deleted_cloud": 0, "errors": [str(e)]},
                "errors": [str(e)],
            }

    def _norm_folder_key(self, name: str) -> str:
        """Return the folder name as-is with only surrounding spaces trimmed.
        Used for exact, case-sensitive matching against server names.
        """
        try:
            return str(name or "").strip()
        except Exception:
            return str(name or "")

    # --- helpers for remote subfolders (used by uploads) ---
    def _child_folder_id_by_name(self, tree: list, parent_folder_id: int | None, name: str) -> int | None:
        try:
            want_name = self._norm_folder_key(name or "")
            if not want_name:
                return None
            # Try from provided tree first
            children = None
            try:
                parent_node = self._find_folder_in_tree(tree or [], int(parent_folder_id or 0))
                children = (parent_node or {}).get("children") if isinstance(parent_node, dict) else None
            except Exception:
                children = None
            # If missing, load details for the parent folder directly
            if not isinstance(children, list) or not children:
                try:
                    det = self.api.get_folder_details(int(parent_folder_id or 0), force=True)
                except Exception:
                    det = None
                possible_keys = ("children", "items", "documents", "content", "folders")
                children = None
                if isinstance(det, dict):
                    for k in possible_keys:
                        lst = det.get(k)
                        if isinstance(lst, list):
                            children = lst
                            break
            if not isinstance(children, list):
                return None
            try:
                sync_log("FIND_CHILD under parent={} looking='{}' children_count={}", parent_folder_id, name, len(children))
            except Exception:
                pass
            for ch in children:
                try:
                    raw_title = (ch.get("name") or ch.get("title") or ch.get("folderName") or "").strip()
                    ctype = str(ch.get("type") or "").lower()
                    looks_like_folder = (ctype == "folder" or ctype == "" or isinstance(ch.get("children"), list) or bool(ch.get("children")))
                    if raw_title == want_name and looks_like_folder:
                        raw_fid = ch.get("id")

                        try:

                            fid = int(raw_fid)

                        except (ValueError, TypeError):

                            fid = raw_fid
                        try:
                            sync_log("FIND_CHILD matched parent={} name='{}' -> id={}", parent_folder_id, name, fid)
                        except Exception:
                            pass
                        return fid
                except Exception:
                    continue
            return None
        except Exception:
            return None

    def _find_folder_in_tree(self, nodes: list, folder_id: int) -> dict | None:
        try:
            fid = normalize_id(folder_id)
        except Exception:
            fid = 0
        if not isinstance(nodes, list):
            return None
        for n in nodes:
            if not isinstance(n, dict):
                continue
            try:
                if normalize_id(n.get("id")) == fid:
                    return n
            except Exception:
                pass
            child_nodes = (
                n.get("children")
                or n.get("folders")
                or n.get("subFolders")
                or n.get("subfolders")
                or []
            )
            child = self._find_folder_in_tree(child_nodes, fid)
            if child is not None:
                return child
        return None

    def _collect_cloud_files_via_project_tree_LEGACY(self, project_id: int | str, folder_id: int | str) -> list:
        """Collect cloud files via project tree.
        
        This is a legacy method stub - new sync uses execute_sync() with JSON state.
        Returns empty list as new sync doesn't need this.
        """
        return []
    
    # === NEW: Robust Cloud Snapshot System ===
    
    def _api_call_with_retry(self, func, *args, **kwargs):
        """Execute an API call with exponential backoff retry logic.
        
        Args:
            func: API function to call
            *args, **kwargs: Arguments to pass to the function
            
        Returns:
            Result from the API call
            
        Raises:
            Exception: If all retries exhausted
        """
        import time
        
        last_exception = None
        for attempt in range(self._max_retries):
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                last_exception = e
                if attempt < self._max_retries - 1:
                    delay = self._retry_delay_base ** attempt
                    sync_log("API_RETRY: attempt={}/{} func='{}' error='{}' delay={}s", 
                            attempt + 1, self._max_retries, func.__name__, str(e), delay)
                    time.sleep(delay)
                else:
                    sync_log("API_RETRY: exhausted retries for func='{}' error='{}'", 
                            func.__name__, str(e))
        
        raise last_exception or Exception("API call failed")
    
    def _build_cloud_snapshot(self, folder_id: int, project_id: int | str) -> dict:
        """Build a comprehensive, validated snapshot of cloud folder structure.
        
        Features:
        - Recursive tree traversal with safe child loading by ID
        - Handles None/empty data gracefully
        - Includes validation flags and metrics
        - Retry logic for API calls
        - Timeout protection
        
        Returns:
            Dict with keys:
                - is_valid: bool - whether snapshot is trustworthy
                - folders: dict[str, int] - rel_path -> folder_id mapping
                - files: list[dict] - file metadata
                - total_folders: int
                - total_files: int
                - errors: list[str] - any errors encountered
                - timestamp: float - when snapshot was taken
        """
        import time
        
        snapshot = {
            "is_valid": False,
            "folders": {},  # rel_path -> folder_id
            "files": [],
            "total_folders": 0,
            "total_files": 0,
            "errors": [],
            "timestamp": time.time()
        }
        
        try:
            sync_log("SNAPSHOT_BUILD: starting for folder_id={} project_id={}", folder_id, project_id)
            
            # Load root folder with retry
            try:
                root = self._api_call_with_retry(
                    self.api.get_folder_details,
                    normalize_id(folder_id),
                    force=True
                )
            except Exception as e:
                snapshot["errors"].append(f"Failed to load root folder: {e}")
                sync_exc(f"SNAPSHOT_BUILD: root folder load failed: {e}")
                return snapshot
            
            if not isinstance(root, dict):
                snapshot["errors"].append("Root folder is not a dict")
                return snapshot
            
            # Collect folders and files recursively
            try:
                folders = self._collect_cloud_folders(root, "", safe_mode=True)
                snapshot["folders"] = folders
                snapshot["total_folders"] = len(folders)
                sync_log("SNAPSHOT_BUILD: collected {} folders", len(folders))
            except Exception as e:
                snapshot["errors"].append(f"Folder collection failed: {e}")
                sync_exc(f"SNAPSHOT_BUILD: folder collection error: {e}")
            
            try:
                files = self._collect_cloud_files(root, "", force_fresh=True)
                # Filter out directories from files list
                files = [f for f in files if not (str(f.get("type", "")).lower() == "folder" or bool(f.get("is_dir")))]
                snapshot["files"] = files
                snapshot["total_files"] = len(files)
                sync_log("SNAPSHOT_BUILD: collected {} files", len(files))
            except Exception as e:
                snapshot["errors"].append(f"File collection failed: {e}")
                sync_exc(f"SNAPSHOT_BUILD: file collection error: {e}")
            
            # Validate snapshot
            snapshot["is_valid"] = self._validate_cloud_snapshot(snapshot, folder_id)
            
            if snapshot["is_valid"]:
                sync_log("SNAPSHOT_BUILD: VALID snapshot created - folders={} files={}", 
                        snapshot["total_folders"], snapshot["total_files"])
            else:
                sync_log("SNAPSHOT_BUILD: INVALID snapshot - errors={}", snapshot["errors"])
            
            return snapshot
            
        except Exception as e:
            snapshot["errors"].append(f"Unexpected error: {e}")
            sync_exc(f"SNAPSHOT_BUILD: unexpected error: {e}")
            return snapshot
    
    def _collect_cloud_folders(self, root_node: dict, rel_path: str = "", safe_mode: bool = True) -> dict[str, int]:
        """Recursively collect all cloud folders with safe child loading.
        
        Args:
            root_node: Root folder node from API
            rel_path: Current relative path
            safe_mode: If True, handle errors gracefully and continue
            
        Returns:
            Dict mapping normalized rel_path -> folder_id
        """
        folders = {}
        
        def _name(d: dict) -> str:
            return (d.get("title") or d.get("folderName") or d.get("name") or "").strip()
        
        def _is_folder(d: dict) -> bool:
            t = str(d.get("type") or "").lower()
            if t == "folder":
                return True
            if isinstance(d.get("children"), list) or isinstance(d.get("folders"), list):
                return True
            if d.get("documentTypeId") in (None, 0):
                return True
            return False
        
        def _walk(node: dict, current_path: str):
            if not isinstance(node, dict):
                return

            try:
                raw_fid = node.get("id") or 0
                try:
                    fid = int(raw_fid)
                except (ValueError, TypeError):
                    fid = raw_fid
            except Exception:
                fid = 0

            # Register current folder
            if fid and _is_folder(node):
                norm_path = self._norm_rel_sanitized(current_path)
                folders[norm_path] = fid
                sync_log("SNAPSHOT_FOLDER: rel='{}' id={}", current_path, fid)

            # Get children - try multiple possible keys
            children = None
            for key in ("children", "folders", "subFolders", "subfolders"):
                lst = node.get(key)
                if isinstance(lst, list):
                    children = lst
                    break

            # If no children in node, try loading details
            if not children and fid:
                try:
                    if safe_mode:
                        details = self._api_call_with_retry(
                            self.api.get_folder_details,
                            fid,
                            force=False
                        )
                    else:
                        details = self.api.get_folder_details(fid, force=False)

                    if isinstance(details, dict):
                        for key in ("children", "folders", "subFolders", "subfolders"):
                            lst = details.get(key)
                            if isinstance(lst, list):
                                children = lst
                                break
                except Exception as e:
                    if not safe_mode:
                        raise
                    sync_log("SNAPSHOT_FOLDER: failed to load children for id={} error='{}'", fid, str(e))

            if not isinstance(children, list):
                return

            # Process each child
            for child in children:
                if not isinstance(child, dict):
                    continue
                
                if not _is_folder(child):
                    continue
                
                child_name = _name(child)
                if not child_name:
                    continue
                
                # Build child path
                if current_path:
                    child_path = f"{current_path}/{child_name}"
                else:
                    child_path = child_name
                
                # Recursively walk child
                _walk(child, child_path)
        
        # Start walking from root
        _walk(root_node, rel_path.strip("/\\"))
        
        # Ensure root is registered
        if "" not in folders:
            try:
                raw_fid = root_node.get("id") or 0
                try:
                    root_id = int(raw_fid)
                except (ValueError, TypeError):
                    root_id = raw_fid
                if root_id:
                    folders[""] = root_id
            except Exception:
                pass
        
        return folders
    
    def _validate_cloud_snapshot(self, snapshot: dict, folder_id: int) -> bool:
        """Validate that a cloud snapshot is trustworthy.
        
        Checks:
        - No critical errors during collection
        - Reasonable folder/file counts
        - Root folder present
        - If previous snapshot exists, new count not suspiciously low
        
        Returns:
            True if snapshot is valid and safe to use
        """
        try:
            # Check for critical errors
            errors = snapshot.get("errors", [])
            if errors:
                sync_log("SNAPSHOT_VALIDATE: has errors: {}", errors)
                return False
            
            # Check root folder exists
            folders = snapshot.get("folders", {})
            if "" not in folders:
                sync_log("SNAPSHOT_VALIDATE: root folder missing")
                return False
            
            # Get counts
            folder_count = snapshot.get("total_folders", 0)
            file_count = snapshot.get("total_files", 0)
            
            # Check minimum reasonable counts (at least root folder)
            if folder_count < 1:
                sync_log("SNAPSHOT_VALIDATE: folder_count too low: {}", folder_count)
                return False
            
            # Load previous snapshot if exists
            try:
                prev_files = self._load_last_cloud_set(normalize_id(folder_id))
                prev_count = len(prev_files)
                
                if prev_count > 0:
                    # Check for suspicious drops (more than 50% loss)
                    if file_count < prev_count * 0.5:
                        # Log warning but don't invalidate snapshot - might be legitimate folder operations
                        sync_log("SNAPSHOT_VALIDATE: WARNING file count drop: prev={} new={} (accepting as valid)", 
                                prev_count, file_count)
            except Exception:
                pass
            
            # All checks passed
            sync_log("SNAPSHOT_VALIDATE: snapshot is VALID - folders={} files={}", 
                    folder_count, file_count)
            return True
            
        except Exception as e:
            sync_exc(f"SNAPSHOT_VALIDATE: validation error: {e}")
            return False
    
    def _safe_cleanup_folders(self, local_root: str, cloud_snapshot: dict, dry_run: bool = False) -> dict:
        """Safely cleanup local folders that were deleted from cloud.
        
        Only executes if cloud_snapshot is valid.
        Never touches non-empty directories.
        Moves folders to recycle bin (soft delete).
        
        Args:
            local_root: Local sync folder root
            cloud_snapshot: Validated cloud snapshot from _build_cloud_snapshot
            dry_run: If True, only log actions without executing
            
        Returns:
            Dict with cleanup statistics
        """
        import os
        
        stats = {
            "skipped_reason": None,
            "folders_deleted": 0,
            "folders_skipped_nonempty": 0,
            "folders_skipped_errors": 0,
            "dry_run": dry_run
        }
        
        try:
            # Feature flag check
            if not self._enable_folder_cleanup:
                stats["skipped_reason"] = "feature_disabled"
                sync_log("CLEANUP_FOLDERS: SKIPPED - feature disabled in settings")
                return stats
            
            # Validate snapshot
            if not cloud_snapshot.get("is_valid"):
                stats["skipped_reason"] = "invalid_cloud_snapshot"
                errors = cloud_snapshot.get("errors", [])
                sync_log("CLEANUP_FOLDERS: SKIPPED - invalid cloud snapshot errors={}", errors)
                return stats
            
            # CRITICAL: Check if we have a previous snapshot to compare with
            # Without a previous snapshot, we can't know what was deleted vs what was never synced
            try:
                # Try to determine folder_id from local_root path
                folder_id = None
                for fid, cfg in self.map.items():
                    if cfg.get("local_path") == local_root:
                        try:
                            try:
                                folder_id = int(fid)
                            except (ValueError, TypeError):
                                folder_id = fid
                        except (ValueError, TypeError):
                            folder_id = fid
                        break
                
                if folder_id is None:
                    stats["skipped_reason"] = "no_folder_id"
                    sync_log("CLEANUP_FOLDERS: SKIPPED - cannot determine folder_id from local_root")
                    return stats
                
                # Load previous cloud snapshot
                prev_cloud_files = self._load_last_cloud_set(folder_id)
                
                # If no previous snapshot exists, only proceed when current cloud snapshot is meaningful
                if not prev_cloud_files:
                    has_files_now = bool(cloud_snapshot.get("total_files", 0))
                    cloud_folders_now = set((cloud_snapshot.get("folders") or {}).keys())
                    has_non_root_folder = any(p for p in cloud_folders_now)
                    if not (has_files_now or has_non_root_folder):
                        stats["skipped_reason"] = "no_previous_snapshot"
                        sync_log("CLEANUP_FOLDERS: SKIPPED - no previous snapshot and no meaningful current snapshot")
                        return stats
                    sync_log("CLEANUP_FOLDERS: no previous snapshot; using local folders as baseline for empty-folder cleanup")
                
                # Load previous folder snapshot from settings
                # CRITICAL: Use dedicated folder snapshot, NOT derived from file paths!
                prev_folders_raw = self.settings.value(f"sync2_state/{self._fid_group(folder_id)}/last_cloud_folders_snapshot", "")
                
                if not prev_folders_raw:
                    # No previous folder snapshot - very conservative approach
                    # Skip cleanup to avoid deleting folders that might not have been synced yet
                    stats["skipped_reason"] = "no_previous_folder_snapshot"
                    sync_log("CLEANUP_FOLDERS: SKIPPED - no previous folder snapshot (first sync or reset)")
                    # Save current snapshot for next time
                    current_folders_list = sorted(cloud_snapshot.get("folders", {}).keys())
                    self.settings.setValue(f"sync2_state/{self._fid_group(folder_id)}/last_cloud_folders_snapshot", "\n".join(current_folders_list))
                    self.settings.sync()
                    return stats
                
                # Parse previous folders
                prev_folders = set(line.strip() for line in prev_folders_raw.split("\n") if line.strip())
                sync_log("CLEANUP_FOLDERS: previous snapshot had {} folders", len(prev_folders))
                
            except Exception as e:
                stats["skipped_reason"] = f"snapshot_check_error: {e}"
                sync_exc(f"CLEANUP_FOLDERS: failed to check previous snapshot: {e}")
                return stats
            
            # Get current state
            cloud_folders = set(cloud_snapshot.get("folders", {}).keys())
            local_folders = self._collect_local_dirs(local_root)
            
            # Normalize local folders for comparison
            local_folders_norm = {self._norm_rel_sanitized(d): d for d in local_folders}
            
            # Find folders that were in previous snapshot but NOT in current
            # Conservative baseline: use local folders only if current snapshot is meaningful
            if prev_folders:
                base_prev = prev_folders
            else:
                has_files_now = bool(cloud_snapshot.get("total_files", 0))
                cloud_folders_now = set((cloud_snapshot.get("folders") or {}).keys())
                has_non_root_folder = any(p for p in cloud_folders_now)
                if has_files_now or has_non_root_folder:
                    base_prev = set(local_folders_norm.keys())
                else:
                    stats["skipped_reason"] = "no_baseline_and_no_cloud_state"
                    sync_log("CLEANUP_FOLDERS: SKIPPED - no baseline and no meaningful cloud state")
                    return stats
            deleted_from_cloud = base_prev - cloud_folders
            
            # Only delete local folders that:
            # 1. Were in previous cloud snapshot (known to sync)
            # 2. Are NOT in current cloud snapshot (deleted from cloud)
            # 3. Still exist locally
            to_delete = deleted_from_cloud & set(local_folders_norm.keys())
            
            if not to_delete:
                sync_log("CLEANUP_FOLDERS: no folders to delete (prev={} current={} local={} deleted_from_cloud={})", 
                        len(prev_folders), len(cloud_folders), len(local_folders_norm), len(deleted_from_cloud))
                # Save current snapshot for next comparison
                current_folders_list = sorted(cloud_folders)
                self.settings.setValue(f"sync2_state/{self._fid_group(folder_id)}/last_cloud_folders_snapshot", "\n".join(current_folders_list))
                self.settings.sync()
                return stats
            
            sync_log("CLEANUP_FOLDERS: found {} candidate folders for deletion (were in prev snapshot, deleted from cloud)", len(to_delete))
            
            sync_log("CLEANUP_FOLDERS: found {} candidate folders for deletion", len(to_delete))
            
            # Sort by depth (deepest first) to delete children before parents
            to_delete_sorted = sorted(to_delete, key=lambda x: x.count('/'), reverse=True)
            
            for norm_rel in to_delete_sorted:
                try:
                    # Get original path
                    orig_rel = local_folders_norm.get(norm_rel, "")
                    if not orig_rel:
                        continue
                    
                    # Build full path
                    parts = [_sanitize_filename(p) for p in orig_rel.replace("\\", "/").split("/") if p]
                    folder_path = os.path.normpath(os.path.join(local_root, *parts))
                    
                    if not os.path.exists(folder_path) or not os.path.isdir(folder_path):
                        continue
                    
                    # Check if empty
                    try:
                        contents = os.listdir(folder_path)
                        if contents:
                            stats["folders_skipped_nonempty"] += 1
                            sync_log("CLEANUP_FOLDERS: SKIP non-empty folder rel='{}'", orig_rel)
                            continue
                    except Exception:
                        stats["folders_skipped_errors"] += 1
                        continue
                    
                    # Execute deletion
                    if dry_run:
                        sync_log("CLEANUP_FOLDERS: DRY_RUN would delete rel='{}' path='{}'", 
                                orig_rel, folder_path)
                        stats["folders_deleted"] += 1
                    else:
                        # Try to move to recycle bin
                        try:
                            from send2trash import send2trash
                            send2trash(folder_path)
                            sync_log("CLEANUP_FOLDERS: deleted to recycle bin rel='{}' path='{}'", 
                                    orig_rel, folder_path)
                            stats["folders_deleted"] += 1
                        except ImportError:
                            # Fallback: only delete if truly empty
                            try:
                                os.rmdir(folder_path)
                                sync_log("CLEANUP_FOLDERS: removed empty folder rel='{}' path='{}'", 
                                        orig_rel, folder_path)
                                stats["folders_deleted"] += 1
                            except OSError:
                                stats["folders_skipped_nonempty"] += 1
                                sync_log("CLEANUP_FOLDERS: SKIP (rmdir failed) rel='{}'", orig_rel)
                        except Exception as e:
                            stats["folders_skipped_errors"] += 1
                            sync_log("CLEANUP_FOLDERS: ERROR deleting rel='{}' error='{}'", orig_rel, str(e))
                
                except Exception as e:
                    stats["folders_skipped_errors"] += 1
                    sync_exc(f"CLEANUP_FOLDERS: error processing folder: {e}")
            
            sync_log("CLEANUP_FOLDERS: completed - deleted={} skipped_nonempty={} skipped_errors={}", 
                    stats["folders_deleted"], stats["folders_skipped_nonempty"], stats["folders_skipped_errors"])

            # Save current folders snapshot for next comparison
            try:
                current_folders_list = sorted(cloud_folders)
                self.settings.setValue(f"sync2_state/{self._fid_group(folder_id)}/last_cloud_folders_snapshot", "\n".join(current_folders_list))
                self.settings.sync()
            except Exception:
                pass

            return stats
            
        except Exception as e:
            stats["skipped_reason"] = f"unexpected_error: {e}"
            sync_exc(f"CLEANUP_FOLDERS: unexpected error: {e}")
            return stats
    
    def _check_mass_deletion_protection(self, deleted_count: int, total_count: int) -> bool:
        """Deprecated simple check (kept for backward compatibility).
        New logic uses _update_mass_delete_protection with prev/current totals.
        """
        if total_count <= 0:
            return True
        deletion_ratio = deleted_count / total_count
        return deletion_ratio <= self._max_deletion_percent

    def _collect_cloud_files(self, folder_node: dict, rel_path: str = "", force_fresh: bool = False) -> list[dict]:
        """Collect file metadata from a folder node recursively.

        Returns list of dicts with: id, name, size, rel_path, createTime, modifTime, updatedAt, is_dir, type

        Args:
            folder_node: Folder node dict from API
            rel_path: Relative path from root folder
            force_fresh: Force fresh API calls, bypass cache
        """
        import os

        out: list[dict] = []

        # -------- локальные хелперы (внутри функции, чтобы не плодить методы класса) --------
        def _is_file_entry(d: dict) -> bool:
            t = str(d.get("type") or "").lower()
            if t in ("file", "document", "doc"):
                return True
            if d.get("documentTypeId") == 100:
                return True
            if any(k in d for k in ("fileUid", "fileName", "originalName")):
                return True
            # эвристика: есть расширение и нет children
            nm = str(d.get("name") or "").strip()
            if nm and "." in nm and not isinstance(d.get("children"), list):
                return True
            return False

        def _is_deleted_entry(d: dict) -> bool:
            """Best-effort: treat soft-deleted items as absent.

            Larix API often returns "deleteTime"/"deletedAt" for items moved to trash.
            If we keep those in scans, we won't detect deletions (sync + notifications).
            """
            try:
                if not isinstance(d, dict):
                    return False

                # Common boolean flags
                for k in ("isDeleted", "deleted", "removed", "trashed"):
                    v = d.get(k)
                    if v is True:
                        return True

                # Common timestamp markers
                for k in (
                    "deleteTime",
                    "deletedAt",
                    "deletedTime",
                    "deleteAt",
                    "delete_date",
                ):
                    v = d.get(k)
                    if v not in (None, "", 0, "0", False):
                        return True

                # Common status markers
                st = str(d.get("status") or "").strip().lower()
                if st in ("deleted", "removed", "trashed", "trash"):
                    return True

                return False
            except Exception:
                return False

        def _is_folder_entry(d: dict) -> bool:
            t = str(d.get("type") or "").lower()
            if t == "folder":
                return True
            if isinstance(d.get("children"), list) or isinstance(d.get("folders"), list):
                return True
            # у некоторых папок нет типа, но есть признак наличия подпапок
            if d.get("hasFolders"):
                return True
            # эвристика: нет признаков файла, но есть имя - считаем папкой
            if not _is_file_entry(d) and (d.get("title") or d.get("folderName") or d.get("name")):
                return True
            return False

        def _norm_name(d: dict) -> str:
            return (d.get("originalName")
                    or d.get("fileName")
                    or d.get("name")
                    or d.get("title")
                    or d.get("folderName")
                    or "").strip()

        def _norm_rel(base: str, *parts: str) -> str:
            segs = [str(p or "").strip("/\\") for p in (base,) + parts if str(p or "").strip()]
            return "/".join(segs)

        def _norm_size(d: dict) -> int:
            # если у класса есть normalize_size - используем
            try:
                return int(self.normalize_size(d))  # noqa: attribute-defined-outside-init
            except Exception:
                pass
            # иначе пробуем стандартные ключи
            for k in ("size", "fileSize", "length", "bytes"):
                v = d.get(k)
                try:
                    if v is not None:
                        return int(v)
                except Exception:
                    pass
            return 0

        def _pick_id(d: dict, kind: str = "file"):
            """Pick a stable id from inconsistent API payloads."""
            if not isinstance(d, dict):
                return None
            if kind == "folder":
                keys = ("id", "folderId", "folder_id", "folderUid", "uid", "itemId")
            else:
                keys = ("id", "documentId", "docId", "fileId", "fileUid", "documentUid", "uid", "itemId")
            for k in keys:
                v = d.get(k)
                if v not in (None, "", 0, "0", False):
                    return v
            return d.get("id")

        def _ensure_create_time(file_obj: dict) -> str:
            """Вернёт createTime. Если нет - подтянет детали документа и закеширует."""
            s = str(file_obj.get("createTime") or "").strip()
            if s:
                return s
            fid = file_obj.get("id")
            if not fid:
                return ""
            try:
                # Best-effort: bust API cache to avoid stale metadata
                try:
                    doc_id = self.api._stringify_id(fid)
                    if doc_id:
                        self.api.cache.pop(f"doc:{doc_id}", None)
                except Exception:
                    pass
                details = self.api.get_document_details(fid)
                if isinstance(details, dict):
                    ct = str(details.get("createTime") or "").strip()
                    if ct:
                        file_obj["createTime"] = ct  # кешируем
                        return ct
            except Exception:
                pass
            return ""

        def _ensure_modif_time(file_obj: dict) -> str:
            """Вернёт modifTime/updatedAt. Если нет - подтянет детали документа и закеширует."""
            s = str(file_obj.get("modifTime") or file_obj.get("updatedAt") or "").strip()
            if s:
                return s
            fid = file_obj.get("id")
            if not fid:
                return ""
            try:
                # Best-effort: bust API cache to avoid stale metadata
                try:
                    doc_id = self.api._stringify_id(fid)
                    if doc_id:
                        self.api.cache.pop(f"doc:{doc_id}", None)
                except Exception:
                    pass
                details = self.api.get_document_details(fid)
                if isinstance(details, dict):
                    mt = str(details.get("modifTime") or details.get("updatedAt") or details.get("createTime") or "").strip()
                    if mt:
                        file_obj["modifTime"] = mt
                        return mt
            except Exception:
                pass
            return ""

        # -------- подготовим узел: если контента нет - дотянем детали папки --------
        node = folder_node if isinstance(folder_node, dict) else {}
        try:
            has_lists = any(isinstance(node.get(k), list) for k in ("children", "folders", "files", "items", "documents", "content"))
            if not has_lists:
                try:
                    raw_fid = _pick_id(node, "folder") or 0
                    try:
                        fid = int(raw_fid)
                    except (ValueError, TypeError):
                        fid = raw_fid
                except Exception:
                    fid = 0
                if fid:
                    try:
                        det = self.api.get_folder_details(fid, force=bool(force_fresh))
                        if isinstance(det, dict):
                            node = det
                    except Exception:
                        pass
        except Exception:
            pass

        # -------- соберём файлы из "плоских" ключей (если такие есть у этого API) --------
        # "items"/"content" often contain mixed entries (folders + files), so we
        # handle them in generic children traversal below.
        files_keys_found = []
        for key in ("files", "documents"):
            lst = node.get(key)
            if isinstance(lst, list):
                files_keys_found.append(key)
            if not (isinstance(lst, list) and lst):
                continue
            for f in lst:
                if not isinstance(f, dict) or not _is_file_entry(f) or _is_deleted_entry(f):
                    continue
                try:
                    enrich_id_types(f)
                except Exception:
                    pass
                try:
                    raw_fid = _pick_id(f, "file") or 0
                    try:
                        fid = int(raw_fid)
                    except (ValueError, TypeError):
                        fid = raw_fid
                except Exception:
                    fid = 0
                name = _norm_name(f)
                if not name:
                    continue
                rel = _norm_rel(rel_path, name)
                size = _norm_size(f)
                create_time = _ensure_create_time(f)  # только createTime
                modif_time = _ensure_modif_time(f)
                updated_at = str(f.get("updatedAt") or "").strip() or modif_time or create_time

                out.append({
                    "id": fid,
                    "name": name,
                    "size": size,
                    "rel_path": rel,
                    "createTime": create_time,
                    "modifTime": modif_time,
                    "updatedAt": updated_at,
                    "is_dir": False,
                    "type": "file",
                    "createdBy": str(f.get("createdBy") or "").strip(),
                    "modifiedBy": str(f.get("modifiedBy") or "").strip(),
                    "version": int(f.get("version") or 0),
                    "_id_str": str(fid) if fid else "",
                    "_id_int": fid if isinstance(fid, int) else None,
                })

        # -------- обойдём дочерние коллекции: там могут быть и папки, и файлы --------
        children: list = []
        for k in ("children", "folders", "subFolders", "subfolders", "items", "content"):
            v = node.get(k)
            if isinstance(v, list) and v:
                children.extend(v)
        if isinstance(children, list):
            for ch in children:
                if not isinstance(ch, dict):
                    continue
                try:
                    enrich_id_types(ch)
                except Exception:
                    pass

                if _is_deleted_entry(ch):
                    continue

                # имя/путь для следующего шага
                ch_name = _norm_name(ch)
                if not ch_name:
                    # без имени не сможем построить rel_path - пропустим
                    continue
                next_rel = _norm_rel(rel_path, ch_name)

                # файл?
                if _is_file_entry(ch):
                    try:
                        raw_fid = _pick_id(ch, "file") or 0
                        try:
                            fid = int(raw_fid)
                        except (ValueError, TypeError):
                            fid = raw_fid
                    except Exception:
                        fid = 0
                    size = _norm_size(ch)
                    create_time = _ensure_create_time(ch)
                    modif_time = _ensure_modif_time(ch)
                    updated_at = str(ch.get("updatedAt") or "").strip() or modif_time or create_time

                    out.append({
                        "id": fid,
                        "name": ch_name,
                        "size": size,
                        "rel_path": next_rel,
                        "createTime": create_time,
                        "modifTime": modif_time,
                        "updatedAt": updated_at,
                        "is_dir": False,
                        "type": "file",
                        "createdBy": str(ch.get("createdBy") or "").strip(),
                        "modifiedBy": str(ch.get("modifiedBy") or "").strip(),
                        "version": int(ch.get("version") or 0),
                        "_id_str": str(fid) if fid else "",
                        "_id_int": fid if isinstance(fid, int) else None,
                    })
                    continue

                # папка?
                if _is_folder_entry(ch):
                    # добавляем запись-директорий без рекурсивной загрузки содержимого
                    try:
                        raw_fid = _pick_id(ch, "folder") or 0
                        try:
                            fid = int(raw_fid)
                        except (ValueError, TypeError):
                            fid = raw_fid
                    except Exception:
                        fid = 0
                    out.append({
                        "id": fid,
                        "name": ch_name,
                        "rel_path": next_rel,
                        "is_dir": True,
                        "type": "folder",
                        "_id_str": str(fid) if fid else "",
                        "_id_int": fid if isinstance(fid, int) else None,
                    })
                    continue

                # если не распознали - пропустим узел
                continue

        return out



    def _find_folder_in_tree(self, nodes: list, folder_id: int | str) -> dict | None:
        """Locate a folder node in an arbitrary tree payload.

        API payloads are inconsistent: nested nodes can be under different keys.
        We traverse a superset of known keys to reliably find a folder by id.
        """
        try:
            want_id = normalize_id(folder_id)
        except Exception:
            want_id = str(folder_id).strip()
        
        if not isinstance(nodes, list):
            return None

        child_keys = (
            "children",
            "folders",
            "items",
            "subFolders",
            "subfolders",
            "content",
            "documents",
        )

        for n in nodes:
            if not isinstance(n, dict):
                continue 
            
            try:
                node_id = n.get("id")
                if normalize_id(node_id) == want_id:
                    return n
            except Exception:
                pass

            for k in child_keys:
                ch = n.get(k)
                if isinstance(ch, list) and ch:
                    child = self._find_folder_in_tree(ch, want_id)
                    if child is not None:
                        return child

        return None

    def _collect_cloud_files_via_project_tree(self, project_id: int | str, folder_id: int | str) -> list:
        """Fallback: traverse project folders tree to locate folder_id and
        then collect files by recursing with _collect_cloud_files.
        This helps when get_folder_details for root folder doesn't expose children.
        """
        try:
            tree = self.api.list_folders(project_id, force=True) or []
        except Exception:
            tree = []

        node = self._find_folder_in_tree(tree, normalize_id(folder_id))
        if not isinstance(node, dict):
            return []

        result = self._collect_cloud_files(node, "", force_fresh=True)
        return result
    def _create_empty_local_dirs_from_cloud(self, folder_dict: dict, local_base: str, rel_prefix: str = "") -> None:
        import os
        if not isinstance(folder_dict, dict):
            return

        # где могут лежать подпапки в ответе API
        children_keys = ("folders", "children", "subFolders", "subfolders")
        subfolders = None
        for k in children_keys:
            v = folder_dict.get(k)
            if isinstance(v, list):
                subfolders = v
                break
        if not subfolders:
            return

        for ch in subfolders:
            try:
                if not isinstance(ch, dict):
                    continue
                is_folder = (ch.get("type") == "folder") or bool(ch.get("hasFolders"))
                if not is_folder:
                    continue
                name = ch.get("name") or ch.get("folderName") or ch.get("title") or ""
                name = _sanitize_filename(name or "")
                if not name:
                    continue

                rel = f"{rel_prefix}/{name}" if rel_prefix else name
                dst = os.path.join(local_base, *[p for p in rel.split("/") if p])
                os.makedirs(dst, exist_ok=True)

                # рекурсивно углубляемся
                self._create_empty_local_dirs_from_cloud(ch, local_base, rel)
            except Exception:
                pass
    def _ensure_remote_dirs_from_local(self, local_base: str, root_folder_id: int) -> None:
        import os
        for dirpath, dirnames, _ in os.walk(local_base):
            try:
                rel = os.path.relpath(dirpath, local_base).replace("\\", "/")
                if rel in (".", "", None):
                    continue
                parts = [_sanitize_filename(p) for p in rel.split("/") if p and p not in (".", "..")]
                if parts:
                    # создаём цепочку подпапок на облаке
                    try:
                        self._ensure_subfolder(normalize_id(root_folder_id), parts)
                    except Exception:
                        pass
            except Exception:
                pass

    # --- helpers for remote subfolders (used by uploads) ---
    def _child_folder_id_by_name(self, tree: list, parent_folder_id: int | None, name: str) -> int | None:
        try:
            want_name = self._norm_folder_key(name or "")
            if not want_name:
                return None
            # Try from provided tree first
            children = None
            try:
                parent_node = self._find_folder_in_tree(tree or [], int(parent_folder_id or 0))
                children = (parent_node or {}).get("children") if isinstance(parent_node, dict) else None
            except Exception:
                children = None
            # If missing, load details for the parent folder directly
            if not isinstance(children, list) or not children:
                try:
                    det = self.api.get_folder_details(int(parent_folder_id or 0), force=True)
                except Exception:
                    det = None
                possible_keys = ("children", "items", "documents", "content", "folders")
                children = None
                if isinstance(det, dict):
                    for k in possible_keys:
                        lst = det.get(k)
                        if isinstance(lst, list):
                            children = lst
                            break
            if not isinstance(children, list):
                return None
            try:
                sync_log("FIND_CHILD under parent={} looking='{}' children_count={}", parent_folder_id, name, len(children))
            except Exception:
                pass
            for ch in children:
                try:
                    raw_title = (ch.get("name") or ch.get("title") or ch.get("folderName") or "").strip()
                    ctype = str(ch.get("type") or "").lower()
                    looks_like_folder = (ctype == "folder" or ctype == "" or isinstance(ch.get("children"), list) or bool(ch.get("children")))
                    if raw_title == want_name and looks_like_folder:
                        raw_fid = ch.get("id")

                        try:

                            fid = int(raw_fid)

                        except (ValueError, TypeError):

                            fid = raw_fid
                        try:
                            sync_log("FIND_CHILD matched parent={} name='{}' -> id={}", parent_folder_id, name, fid)
                        except Exception:
                            pass
                        return fid
                except Exception:
                    continue
            return None
        except Exception:
            return None

    def _ensure_subfolder(self, project_id: int | str, parent_folder_id: int | str, name: str) -> int | str | None:
        try:
            nm = str(name or "").strip()
            if not nm:
                return normalize_id(parent_folder_id)
            # Cache lookup to avoid recreating same subfolder for each file
            try:
                key = (int(project_id or 0), normalize_id(parent_folder_id or 0), self._norm_folder_key(nm))
                cached = self._ensure_cache.get(key)
                if cached and cached != "0":
                    return normalize_id(cached)
            except Exception:
                pass
            try:
                sync_log("ENSURE_SUBFOLDER start parent={} name='{}' proj={}", parent_folder_id, nm, project_id)
            except Exception:
                pass
            # 1) Try via parent details directly
            fid = self._child_folder_id_by_name([], parent_folder_id, nm)
            if fid:
                try:
                    sync_log("ENSURE_SUBFOLDER exists parent={} name='{}' id={}", parent_folder_id, nm, fid)
                except Exception:
                    pass
                try:
                    try:
                        self._ensure_cache[key] = int(fid)
                    except (ValueError, TypeError):
                        self._ensure_cache[key] = fid
                except Exception:
                    pass
                return fid
            # 1b) Try via project tree traversal (fresh)
            try:
                tree = self.api.list_folders(int(project_id), force=True) or []
                fid = self._child_folder_id_by_name(tree, parent_folder_id, nm)
                if fid:
                    try:
                        try:
                            self._ensure_cache[key] = int(fid)
                        except (ValueError, TypeError):
                            self._ensure_cache[key] = fid
                    except Exception:
                        pass
                    return fid
            except Exception:
                pass
            # 2) Create folder directly under parent
            created = self.api.create_folder(int(project_id), parent_folder_id, nm)
            if not created:
                try:
                    sync_log("ENSURE_SUBFOLDER create failed parent={} name='{}'", parent_folder_id, nm)
                except Exception:
                    pass
                return None
            # If API returned id (int or str), use it directly
            try:
                if isinstance(created, (int, str)) and created not in (True, False, 0, ""):
                    fid = normalize_id(created)
                    if fid:
                        try:
                            sync_log("ENSURE_SUBFOLDER created parent={} name='{}' direct_id={}", parent_folder_id, nm, fid)
                        except Exception:
                            pass
                        try:
                            try:
                                self._ensure_cache[key] = int(fid) if isinstance(fid, (int, float)) else fid
                            except (ValueError, TypeError):
                                self._ensure_cache[key] = fid
                        except Exception:
                            pass
                        return fid
            except Exception:
                pass
            # 3) Read parent details again and find it
            fid = self._child_folder_id_by_name([], parent_folder_id, nm)
            try:
                sync_log("ENSURE_SUBFOLDER created parent={} name='{}' id={}", parent_folder_id, nm, fid)
            except Exception:
                pass
            try:
                if fid:
                    try:
                        self._ensure_cache[key] = int(fid)
                    except (ValueError, TypeError):
                        self._ensure_cache[key] = fid
            except Exception:
                pass
            return fid
        except Exception:
            sync_exc("ENSURE_SUBFOLDER exception")
            return None

    def _collect_local_files(self, base: str) -> list:
        """Собрать и файлы, и каталоги (включая пустые)."""
        out = []
        base = os.path.abspath(base)
        for root, dirs, files in os.walk(base):
            # каталоги
            for d in dirs:
                abs_dir = os.path.join(root, d)
                rel = os.path.relpath(abs_dir, base).replace("\\", "/").strip("/")
                out.append({
                    "name": d,
                    "path": abs_dir,
                    "rel_path": rel,
                    "is_dir": True,
                })
            # файлы
            for fn in files:
                if fn.startswith("~$") or fn.endswith(".part"):
                    continue
                abs_fp = os.path.join(root, fn)
                rel = os.path.relpath(abs_fp, base).replace("\\", "/").strip("/")
                try:
                    mt = os.path.getmtime(abs_fp)
                except Exception:
                    mt = 0.0
                out.append({
                    "name": fn,
                    "path": abs_fp,
                    "rel_path": rel,
                    "is_dir": False,
                    "mtime": mt,
                })
        return out

    # --- compare helpers ---
    def _norm_rel(self, s: str) -> str:
        try:
            return str(s or "").replace("\\", "/").strip("/")
        except Exception:
            return str(s or "")

    def _norm_rel_sanitized(self, rel: str) -> str:
        try:
            base = self._norm_rel(rel)
            parts = [p for p in base.split('/') if p]
            safe_parts = []
            for p in parts:
                try:
                    safe_parts.append(_sanitize_filename(p))
                except Exception:
                    safe_parts.append(p)
            return "/".join(safe_parts).casefold()
        except Exception:
            return str(rel or "").replace('\\','/').strip('/').casefold()
        
        
    def _should_ignore_rel(self, rel: str) -> bool:
        """Единый фильтр служебных путей/расширений для снапшотов и сравнения."""
        try:
            r = (rel or "").replace("\\", "/").strip("/")
            base = r.rsplit("/", 1)[-1].casefold()
            # Явные служебные имена
            if base in {"_sync_debug.log"}:
                return True
            # Системные/кодовые расширения
            ext = os.path.splitext(base)[1].casefold()
            if ext in {".py", ".pyc", ".pyo", ".db", ".log"}:
                return True
            return False
        except Exception:
            return False


    def _cloud_created_raw(self, cf: dict | None) -> tuple[str | None, str | None]:
        """Для логов: возвращает (ключ, сырое значение) времени создания из облака.
        Берём только createTime. Если его нет в cf — вернём (None, None)."""
        try:
            if not isinstance(cf, dict):
                return None, None
            raw = cf.get("createTime")
            if raw not in (None, "", 0, 0.0):
                return "createTime", str(raw)
            return None, None
        except Exception:
            return None, None


    def _cloud_mtime(self, doc: dict) -> float | None:
        """Epoch-секунды по полю createTime.
        Если в doc нет createTime — подгружаем детали документа и кешируем.
        Учитываем сдвиг 'часового пояса облака' из настроек."""
        from datetime import datetime, timezone, timedelta

        try:
            if not isinstance(doc, dict):
                sync_log("_cloud_mtime: doc is not dict", component="API", op="mtime")
                return None

            s = str(doc.get("createTime") or "").strip()

            if not s:
                s = str(doc.get("created_ts") or "").strip()

            if not s:
                fid = doc.get("id")
                sync_log(f"_cloud_mtime: no createTime/created_ts in doc, doc_id={fid}, doc_keys={list(doc.keys())}", component="API", op="mtime")
                if fid:
                    details = self.api.get_document_details(fid)  # /api/document/{id}
                    if details and isinstance(details, dict):
                        s = str(details.get("createTime") or details.get("created_ts") or "").strip()
                        sync_log(f"_cloud_mtime: fetched from API, createTime={s} created_ts={details.get('created_ts')}", component="API", op="mtime")
                        if s:
                            doc["createTime"] = s  # кеш в текущем объектe

            if not s:
                sync_log(f"_cloud_mtime: no createTime/created_ts after API fetch, returning None", component="API", op="mtime")
                return None

            # поддерживаем возможный 'Z'
            s_fixed = s[:-1] + "+00:00" if s.endswith("Z") else s
            try:
                dt = datetime.fromisoformat(s_fixed)
            except Exception:
                try:
                    dt = datetime.strptime(s_fixed, "%Y-%m-%dT%H:%M:%S")
                    dt = dt.replace(tzinfo=timezone.utc)
                except Exception:
                    sync_log(f"_cloud_mtime: failed to parse datetime: {s_fixed}", component="API", op="mtime")
                    return None

            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            try:
                tz_min = int(_cloud_tz_offset_minutes())
            except Exception:
                tz_min = 0

            dt_utc = dt - timedelta(minutes=tz_min)
            result = float(dt_utc.timestamp())
            sync_log(f"_cloud_mtime: returning {result} (createTime={s}, tz_min={tz_min}, dt_utc={dt_utc})", component="API", op="mtime")
            return result
        except Exception as e:
            sync_log(f"_cloud_mtime: exception: {e}", component="API", op="mtime")
            return None


    def _decide_action(self, lf: dict | None, cf: dict | None) -> tuple[str, str, float, float | None, str | None, str | None]:
        """
        Возвращает (action, reason, lmt, cmt, csrc, craw)
        action: 'download' | 'upload' | 'skip'
        reason: 'only_cloud' | 'only_local' | 'time cloud>local' | 'time local>cloud' | 'equal' | 'no cloud time' | 'both_missing'
        """
        # Нет ни там, ни тут
        if lf is None and cf is None:
            return 'skip', 'both_missing', 0.0, None, None, None

        # Есть только облако -> всегда скачать
        if lf is None and cf is not None:
            csrc, craw = self._cloud_created_raw(cf)
            cmt = self._cloud_mtime(cf)
            if cmt is None:
                # времени нет, но файл есть в облаке -> всё равно скачиваем
                return 'download', 'only_cloud_no_time', 0.0, None, csrc, craw
            return 'download', 'only_cloud', 0.0, cmt, csrc, craw

        # Есть только локально -> всегда загрузить
        if cf is None and lf is not None:
            try:
                lmt_only = float(lf.get("mtime") or 0.0)
            except Exception:
                lmt_only = 0.0
            return 'upload', 'only_local', lmt_only, None, None, None

        # Обе стороны есть -> сравнить времена
        try:
            lmt = float(lf.get("mtime") or 0.0)
        except Exception:
            lmt = 0.0

        csrc, craw = self._cloud_created_raw(cf)
        cmt = self._cloud_mtime(cf)

        if cmt is None:
            return 'skip', 'no cloud time', lmt, None, csrc, craw

        tol = 2.0
        if lmt > cmt + tol:
            return 'upload', 'time local>cloud', lmt, cmt, csrc, craw
        if cmt > lmt + tol:
            return 'download', 'time cloud>local', lmt, cmt, csrc, craw
        return 'skip', 'equal', lmt, cmt, csrc, craw


    def _cloud_size(self, cf: dict) -> int:
        try:
            return int(normalize_size(cf) or 0)
        except Exception:
            return 0

    def _log_time(self, rel: str, lf: dict | str | None, cf: dict | None) -> None:
        try:
            # local values
            lf_path = None
            if isinstance(lf, dict):
                lf_path = lf.get("path") or None
            elif isinstance(lf, str):
                lf_path = lf
            lmt_ts = None
            if lf_path and os.path.exists(lf_path):
                try:
                    lmt_ts = float(os.path.getmtime(lf_path))
                except Exception:
                    lmt_ts = None
            try:
                lmt_str = _user_display_datetime(float(lmt_ts)) if lmt_ts is not None else "-"
            except Exception:
                lmt_str = "-"

            # cloud values
            cmt_ts = None
            created_raw = "-"
            if isinstance(cf, dict):
                try:
                    cmt_ts = self._cloud_mtime(cf)
                except Exception:
                    cmt_ts = None
                try:
                    _src, _raw = self._cloud_created_raw(cf)
                    if _raw:
                        created_raw = _raw
                except Exception:
                    pass
            try:
                cmt_str = _user_display_datetime(float(cmt_ts)) if cmt_ts is not None else "-"
            except Exception:
                cmt_str = "-"

            # timezones offsets in minutes
            try:
                from datetime import timedelta
                tz_local = int((datetime.now().astimezone().utcoffset() or timedelta()).total_seconds() // 60)
            except Exception:
                tz_local = 0
            try:
                tz_cloud = int(_cloud_tz_offset_minutes())
            except Exception:
                tz_cloud = 0

            sync_log(
                "TIME rel='{}' lmt_ts={} lmt='{}' cmt_ts={} cmt='{}' created_raw='{}' tz_local={} tz_cloud={}",
                rel,
                ("-" if lmt_ts is None else float(lmt_ts)),
                lmt_str or "-",
                ("-" if cmt_ts is None else float(cmt_ts)),
                cmt_str or "-",
                created_raw or "-",
                int(tz_local),
                int(tz_cloud),
            )
        except Exception:
            pass

    def _smart_sync(self, folder_id: int | str, cfg: dict) -> None:
        local_path = cfg.get("local_path") or ""
        if not local_path:
            return
        try:
            os.makedirs(local_path, exist_ok=True)
        except Exception:
            return
        # reset ensure cache before batch operations
        try:
            self._ensure_cache.clear()
        except Exception:
            pass
        try:
            folder = self.api.get_folder_details(normalize_id(folder_id), force=True)
        except Exception:
            folder = None
        if not isinstance(folder, dict):
            return
        # collect fresh cloud and local
        cloud_files = self._collect_cloud_files(folder, "", force_fresh=True)
        proj_id = cfg.get("project_id", 0)
        if (not cloud_files) and proj_id:
            try:
                cloud_files = self._collect_cloud_files_via_project_tree(proj_id, normalize_id(folder_id))
            except Exception:
                cloud_files = []
        local_files = self._collect_local_files(local_path)
                # --- Создание недостающих ПАПОК в обе стороны (учитываем пустые) ---
        try:
            cloud_dirs = self._collect_cloud_dirs(folder, "")
        except Exception:
            cloud_dirs = []
        try:
            local_dirs = self._collect_local_dirs(local_path)
        except Exception:
            local_dirs = []
        cloud_map = { self._norm_rel_sanitized(d): d for d in cloud_dirs }
        local_map  = { self._norm_rel_sanitized(d): d for d in local_dirs }
        proj_id = cfg.get("project_id", 0)

        # 1) Локальные папки, которых нет в облаке -> создать в облаке
        try:
            missing_remote = sorted(set(local_map.keys()) - set(cloud_map.keys()))
            for key in missing_remote:
                raw = local_map.get(key) or ""
                parent = normalize_id(folder_id)
                ok = True
                for part in [p for p in (raw.replace("\\","/").split("/")) if p]:
                    try:
                        parent2 = self._ensure_subfolder(int(proj_id), int(parent), _sanitize_filename(part))
                    except Exception:
                        parent2 = None
                    if parent2:
                        parent = int(parent2)
                    else:
                        ok = False
                        break
                try:
                    sync_log("DIR_REMOTE ensure rel='{}' ok={}", raw, ok)
                except Exception:
                    pass
        except Exception:
            pass

        # 2) Облачные папки, которых нет локально -> создать локально
        try:
            missing_local = sorted(set(cloud_map.keys()) - set(local_map.keys()))
            for key in missing_local:
                raw = cloud_map.get(key) or ""
                parts = [ _sanitize_filename(p) for p in raw.replace("\\","/").split("/") if p ]
                dst = os.path.join(local_path, *parts)
                try:
                    os.makedirs(dst, exist_ok=True)
                    sync_log("DIR_LOCAL ensure path='{}'", dst)
                except Exception:
                    pass
        except Exception:
            pass

                # A) локально создаём все папки из облака (включая пустые)
        try:
            for cf in cloud_files or []:
                if bool(cf.get("is_dir")):
                    rel_dir = self._norm_rel_sanitized(cf.get("rel_path") or cf.get("name") or "")
                    if rel_dir:
                        dst_dir = os.path.join(local_path, *[p for p in rel_dir.split("/") if p])
                        try:
                            os.makedirs(dst_dir, exist_ok=True)
                        except Exception:
                            pass
        except Exception:
            pass
        # B) в облаке создаём все локальные папки
        try:
            proj_id = cfg.get("project_id", 0)
        except Exception:
            proj_id = 0
        if proj_id:
            local_dirs = set()
            for it in local_files or []:
                try:
                    if bool(it.get("is_dir")):
                        rel_dir = self._norm_rel_sanitized(it.get("rel_path") or it.get("name") or "")
                        if rel_dir:
                            local_dirs.add(rel_dir)
                except Exception:
                    pass
            for drel in sorted(local_dirs):
                parent_id = normalize_id(folder_id)
                for part in [p for p in drel.split("/") if p]:
                    nid = self._ensure_subfolder(proj_id, parent_id, part)
                    if not nid:
                        break
                    parent_id = int(nid)

        # --- A) Создать локальные папки, которые есть в облаке (включая пустые) ---
        try:
            def _walk_folders(node: dict, prefix: str = ""):
                # children могут называться по-разному, но в деталях папки у тебя это 'children'
                ch = node.get("children") or []
                if not isinstance(ch, list):
                    ch = []
                for it in ch:
                    try:
                        name = (it.get("name") or it.get("title") or it.get("folderName") or "").strip()
                        if not name:
                            continue
                        ctype = str(it.get("type") or "").lower()
                        is_dir = (ctype == "folder") or isinstance(it.get("children"), list)
                        if not is_dir:
                            # пропускаем файлы
                            continue
                        rel = (prefix + "/" + name).strip("/")
                        # создаём локальную директорию
                        parts = [_sanitize_filename(p) for p in rel.split("/") if p]
                        dst_dir = os.path.join(local_path, *parts) if parts else local_path
                        try:
                            os.makedirs(dst_dir, exist_ok=True)
                        except Exception:
                            pass
                        # если у узла нет поддерева - дотянем детали и продолжим
                        sub = it
                        if not isinstance(it.get("children"), list):
                            try:
                                raw_fid = it.get("id") or 0
                                try:
                                    fid = int(raw_fid)
                                except (ValueError, TypeError):
                                    fid = raw_fid
                                if fid:
                                    sub = self.api.get_folder_details(fid, force=False) or it
                            except Exception:
                                sub = it
                        _walk_folders(sub, rel)
                    except Exception:
                        continue
            _walk_folders(folder, "")
        except Exception:
            pass

        # --- B) Создать папки в облаке, которые есть локально (включая пустые) ---
        try:
            proj_id = cfg.get("project_id", 0)
            if proj_id:
                local_dirs = set()
                for root, dirnames, _ in os.walk(local_path):
                    rel_root = os.path.relpath(root, local_path).replace("\\", "/")
                    if rel_root == "." or not rel_root:
                        continue
                    rel_norm = self._norm_rel_sanitized(rel_root)
                    if rel_norm:
                        local_dirs.add(rel_norm)
                for drel in sorted(local_dirs):
                    parent_id = normalize_id(folder_id)
                    for part in [p for p in drel.split("/") if p]:
                        nid = self._ensure_subfolder(proj_id, parent_id, part)
                        if not nid:
                            break
                        parent_id = int(nid)
        except Exception:
            pass

        # index by rel path (sanitized for consistent compare)
        cloud_by_rel: dict[str, dict] = {}
        for cf in cloud_files or []:
            rel = self._norm_rel_sanitized(cf.get("rel_path") or cf.get("name") or "")
            if rel:
                cloud_by_rel[rel] = cf
        local_by_rel: dict[str, dict] = {}
        for lf in local_files or []:
            rel = self._norm_rel_sanitized(lf.get("rel_path") or lf.get("name") or "")
            if rel:
                local_by_rel[rel] = lf

        # pre-delete: only those that existed before and are now missing locally
        try:
            last_cloud = self._load_last_cloud_set(normalize_id(folder_id))
            self._delete_remote_missing(local_files, cloud_files, last_cloud)
        except Exception:
            pass

        # decide per rel
        all_rels = set(cloud_by_rel.keys()) | set(local_by_rel.keys())
        for rel in sorted(all_rels):
            lf = local_by_rel.get(rel)
            cf = cloud_by_rel.get(rel)
            act, reason, lmt, cmt, csrc, craw = self._decide_action(lf, cf)
            lct = self._local_creation_time(lf)
            try:
                from datetime import timedelta
                try:
                    tz_local = int((datetime.now().astimezone().utcoffset() or timedelta()).total_seconds() // 60)
                except Exception:
                    tz_local = 0
                try:
                    tz_cloud = int(_cloud_tz_offset_minutes())
                except Exception:
                    tz_cloud = 0
                sync_log("DECISION rel='{}' tz_local={} tz_cloud={} lmt={} cmt={} csrc='{}' created_raw='{}' reason='{}' -> {}",
                         rel, int(tz_local), int(tz_cloud), float(lmt or 0), (None if cmt is None else float(cmt)), (csrc or ''), (craw or ''), reason, act)
            except Exception:
                pass
            if act == 'download' and cf is not None:
                try:
                    self.syncItem.emit('download', rel, normalize_id(folder_id))
                except Exception:
                    pass
                self._download_if_newer(cf, local_path, normalize_id(folder_id))
            elif act == 'upload' and lf is not None:
                try:
                    self.syncItem.emit('upload', rel, normalize_id(folder_id))
                except Exception:
                    pass
                self._upload_if_newer(lf, local_path, normalize_id(folder_id), cloud_files, proj_id)

        # save new snapshot after sync
        try:
            fresh = self.api.get_folder_details(normalize_id(folder_id), force=True)
            if isinstance(fresh, dict):
                cur_cloud = self._collect_cloud_files(fresh, "", force_fresh=True)
                self._save_last_cloud_set(normalize_id(folder_id), cur_cloud)
        except Exception:
            pass

    def _finalize_or_cleanup_part(self, final_path: str) -> None:
        """
        Promote '<final>.part' to the target if it's complete,
        or remove zero-byte/stale partial files.
        """
        try:
            tmp = f"{final_path}.part"
            if os.path.exists(tmp):
                try:
                    if (not os.path.exists(final_path)) and os.path.getsize(tmp) > 0:
                        os.replace(tmp, final_path)
                    elif os.path.getsize(tmp) == 0:
                        os.remove(tmp)
                except Exception:
                    # best effort: delete zero-size temp if anything goes wrong
                    try:
                        if os.path.getsize(tmp) == 0:
                            os.remove(tmp)
                    except Exception:
                        pass
        except Exception:
            pass

    def _download_if_newer(self, cloud_file: dict, local_base: str, folder_id: int | str) -> bool:
        try:
            # pick a robust filename
            name = str(
                (cloud_file.get("originalName") or cloud_file.get("fileName") or cloud_file.get("name") or "").strip()
            )
            if not name:
                sync_log("DOWNLOAD_SKIP: no name in cloud_file")
                return False
            # Prefer 'rel_path' if provided to keep directory structure
            rel = cloud_file.get("rel_path") or name
            rel_norm = str(rel).replace("\\", "/").strip("/")
            sync_log("DOWNLOAD_START: rel='{}' fid={}", rel_norm, cloud_file.get("id"))
            # sanitize each segment for filesystem
            parts = [p for p in rel_norm.split("/") if p]
            # _sanitize_filename is defined above in this file
            safe_parts = []
            for i, part in enumerate(parts):
                try:
                    safe = _sanitize_filename(part)
                except Exception:
                    safe = part
                safe_parts.append(safe)
            # build full local path and ensure its parent dir exists
            lf = os.path.join(local_base, *safe_parts)
            # если облачный элемент - папка, создаём локальную папку и выходим
            if str(cloud_file.get("type") or "").lower() == "folder" or bool(cloud_file.get("is_dir")):
                try:
                    os.makedirs(lf, exist_ok=True)
                    try:
                        sync_log("DIR_LOCAL ensure path='{}'", lf)
                    except Exception:
                        pass
                except Exception:
                    pass
                return True

            parent_dir = os.path.dirname(lf)
            if parent_dir and not os.path.exists(parent_dir):
                try:
                    os.makedirs(parent_dir, exist_ok=True)
                    tmp_stale = lf + ".part"
                    if os.path.isfile(tmp_stale):
                        try:
                            os.remove(tmp_stale)
                        except Exception:
                            pass
                except Exception:
                    return False
            cloud_mtime = self._cloud_mtime(cloud_file)
            fid = cloud_file.get("id")
            if not fid:
                return False
            # Download via authenticated API (same as ordinary download), not public link
            # Use temp file + atomic rename to avoid partially written files
            ok = False
            self._finalize_or_cleanup_part(lf)
            tmp_path = lf + ".part"
            try:
                with open(tmp_path, "wb") as f:
                    ok = bool(self.api.write_file_to(fid, f))
            except Exception:
                ok = False
            if ok:
                try:
                    os.replace(tmp_path, lf)
                except Exception:
                    # fallback: try copy-over
                    try:
                        if os.path.exists(tmp_path):
                            with open(tmp_path, 'rb') as _src, open(lf, 'wb') as _dst:
                                while True:
                                    b = _src.read(1024*256)
                                    if not b:
                                        break
                                    _dst.write(b)
                        ok = True
                    except Exception:
                        ok = False
                    finally:
                        try:
                            if os.path.exists(tmp_path):
                                os.remove(tmp_path)
                        except Exception:
                            pass
            if ok:
                sync_log("About to set mtime", component="FS", op="utime", extra=f"lf={lf} cloud_mtime={cloud_mtime} type={type(cloud_mtime)}")
                try:
                    if cloud_mtime is not None and cloud_mtime > 0:
                        mtime_float = float(cloud_mtime)
                        sync_log("Setting mtime", component="FS", op="utime", extra=f"to={mtime_float}")
                        os.utime(lf, (mtime_float, mtime_float))
                        actual_mtime = os.path.getmtime(lf)
                        diff = abs(actual_mtime - mtime_float)
                        sync_log("mtime set successfully", component="FS", op="utime", extra=f"requested={mtime_float} actual={actual_mtime} diff={diff}")
                    else:
                        sync_log("Skipping mtime set - cloud_mtime is None or 0", component="FS", op="utime", extra=f"cloud_mtime={cloud_mtime}")
                except Exception as e:
                    sync_log("Failed to set mtime", component="FS", op="utime", extra=f"error={e}")
                    import traceback
                    sync_log("UTime exception traceback", component="FS", op="utime", extra=f"traceback={traceback.format_exc()}")
                # invalidate folder cache so UI sees fresh list
                try:
                    self.api.cache.pop(f"folder:{normalize_id(folder_id)}", None)
                except Exception:
                    pass
                sync_log("DOWNLOAD_SUCCESS: rel='{}' path='{}'", rel_norm, lf)
                # Increment stats counter
                try:
                    self._stats_files_downloaded = getattr(self, '_stats_files_downloaded', 0) + 1
                except Exception:
                    pass
                return True
        except Exception as e:
            sync_exc(f"DOWNLOAD_FAILED: rel='{rel_norm}' error={e}")
            return False
        return False


    def _upload_if_newer(self, lf: dict, local_path: str, folder_id: int | str, cloud_files: list, project_id: int | str):
        """Upload local file if considered newer than cloud counterpart.
        - Adds 1s tolerance when comparing mtimes to avoid skipping fresh local edits.
        - Ensures remote subfolders exist before upload.
        - Ignores temp files: names starting with '~$' and extension '.part'.
        - Logs before and after: 'UPLOAD rel=<path> parent=<id> ok=<bool> status=<code>'.
        - On success, invalidates folder cache (handled by API) and refreshes UI list.
        """
        name = str(lf.get("name") or "").strip()
        if not name:
            sync_log("UPLOAD_SKIP: no name in local_file")
            return
        low = name.lower()
        if low.startswith("~$") or low.endswith(".part"):
            sync_log("UPLOAD_SKIP: temp file name='{}'", name)
            return
        # find match on cloud by relative path
        rel = str(lf.get("rel_path") or name).replace("\\", "/").strip("/")
        sync_log("UPLOAD_START: rel='{}' path='{}'", rel, lf.get("path"))
        cloud = None
        for cf in cloud_files or []:
            try:
                c_rel = str(cf.get("rel_path") or cf.get("name") or "").replace("\\", "/").strip("/")
            except Exception:
                c_rel = ""
            if c_rel == rel:
                cloud = cf
                break
        lmt = 0.0
        try:
            lmt = float(lf.get("mtime") or 0)
        except Exception:
            pass
        # Decision to upload is made by caller; avoid duplicating time logic
        fp = str(lf.get("path") or "")
        if not (fp and os.path.exists(fp)):
            return
        # ensure remote subfolders for the relative path (excluding filename)
        parts = [p for p in rel.split("/") if p]
        target_parent = normalize_id(folder_id)
        ensured_all = True
        for part in parts[:-1]:
            try:
                new_id = self._ensure_subfolder(int(project_id), int(target_parent), part)
            except Exception:
                new_id = None
            if new_id:
                target_parent = int(new_id)
            else:
                ensured_all = False
                break
        if parts[:-1] and not ensured_all:
            # Don't misplace into parent if subfolder chain couldn't be ensured
            try:
                sync_log("UPLOAD skip ensure_failed rel={} parent={}", rel, int(target_parent))
            except Exception:
                pass
            return
        # если это локальная папка - создаём её целиком в облаке и выходим
        if bool(lf.get("is_dir")):
            try:
                for part in parts:
                    new_id = self._ensure_subfolder(int(project_id), int(target_parent), part)
                    if not new_id:
                        raise RuntimeError("ensure_subfolder failed")
                    target_parent = int(new_id)
                try:
                    sync_log("DIR_REMOTE ensure rel='{}' ok=True parent={}", rel, int(target_parent))
                except Exception:
                    pass
            except Exception:
                try:
                    sync_log("DIR_REMOTE ensure rel='{}' ok=False parent={}", rel, int(target_parent))
                except Exception:
                    pass
            return

        # sanitize filename for upload
        try:
            safe_name = _sanitize_filename(name)
        except Exception:
            safe_name = name
        ok = False
        status = 0
        try:
            sync_log("UPLOAD API call: rel='{}' parent={} file='{}'", rel, int(target_parent), fp)
            ok = bool(self.api.upload_file(int(target_parent), fp, safe_name))
            try:
                status = int(getattr(self.api, "_last_upload_status", 0) or 0)
            except Exception:
                status = 0
            sync_log("UPLOAD API result: rel='{}' parent={} ok={} status={}", rel, int(target_parent), bool(ok), int(status))
        except Exception as e:
            sync_exc(f"UPLOAD API exception: rel='{rel}' parent={int(target_parent)} error={e}")
            ok = False
            status = 0
        finally:
            try:
                sync_log("UPLOAD complete: rel={} parent={} ok={} status={}", rel, int(target_parent), bool(ok), int(status))
            except Exception:
                pass
        # refresh UI list on success (queued to GUI thread)
        if ok:
            sync_log("UPLOAD_SUCCESS: rel='{}' parent={}", rel, normalize_id(target_parent))
            # Log user action for notification filtering
            try:
                self._log_user_action("sync", file_name=safe_name, folder_id=normalize_id(target_parent))
            except Exception:
                pass
            # Increment stats counter
            try:
                self._stats_files_uploaded = getattr(self, '_stats_files_uploaded', 0) + 1
            except Exception:
                pass
            try:
                self.refreshRequested.emit()
            except Exception:
                pass
            # align local mtime to cloud and invalidate cache for parent
            try:
                fresh = self.api.get_folder_details(int(target_parent), force=True)
                if isinstance(fresh, dict):
                    files = self._collect_cloud_files(fresh, "", force_fresh=True)
                    # try to find same rel (sanitized)
                    wanted = rel
                    chosen_cf = None
                    for cf2 in files or []:
                        try:
                            if self._norm_rel_sanitized(cf2.get("rel_path") or cf2.get("name") or "") == wanted:
                                cmt2 = self._cloud_mtime(cf2)
                                if cmt2 is not None:
                                    os.utime(fp, (float(cmt2), float(cmt2)))
                                chosen_cf = cf2
                                break
                        except Exception:
                            continue
                    try:
                        self._log_time(rel, fp, chosen_cf)
                    except Exception:
                        pass
                self.api.cache.pop(f"folder:{int(target_parent)}", None)
            except Exception:
                pass
            try:
                self.api.cache.pop(f"folder:{int(target_parent)}", None)
            except Exception:
                pass


    def _delete_remote_missing(self, local_files: list, cloud_files: list, last_cloud: set[str] | None = None) -> None:
        """Delete files in cloud that are absent locally (mirror local -> cloud).
        Uses relative path match. Ignores folders (only documents are handled).
        Only deletes if file existed in last known cloud snapshot
        (to avoid removing newly added cloud files).
        """
        try:
            local_set = set()
            for lf in local_files:
                try:
                    rel = str(lf.get("rel_path") or lf.get("name") or "").replace("\\", "/").strip("/")
                except Exception:
                    rel = ""
                if rel:
                    local_set.add(rel)
            last_cloud = last_cloud or set()
            for cf in cloud_files:
                try:
                    c_rel = str(cf.get("rel_path") or cf.get("name") or "").replace("\\", "/").strip("/")
                    raw_fid = cf.get("id") or 0
                    try:
                        fid = int(raw_fid)
                    except (ValueError, TypeError):
                        fid = raw_fid
                except Exception:
                    c_rel = ""; fid = 0
                if not c_rel or not fid:
                    continue
                # delete only if file was present in previous snapshot and is missing locally now
                if (c_rel in last_cloud) and (c_rel not in local_set):
                    try:
                        self.api.delete_document(fid)
                        # Log user action for notification filtering (delete via sync)
                        try:
                            fname = cf.get("name") or os.path.basename(c_rel) or ""
                            self._log_user_action("sync", file_id=fid, file_name=fname)
                        except Exception:
                            pass
                        try:
                            sync_log("DELETE_REMOTE missing='{}' id={}", c_rel, fid)
                        except Exception:
                            pass
                    except Exception:
                        sync_exc("DELETE_REMOTE exception")
                        pass
        except Exception:
            pass

    def _local_creation_time(self, lf: dict) -> float:
        """Get local file creation time for logging."""
        try:
            return float(lf.get("createTime") or lf.get("mtime") or 0)
        except Exception:
            return 0.0


class _InitialSyncWorker(QtCore.QObject):
    """Background worker for the initial full download sync.
    Signals drive the UI: total files, per-file progress, errors, and finish/cancel.
    """
    sig_started = QtCore.Signal()
    sig_total = QtCore.Signal(int)
    sig_progress = QtCore.Signal(int, int, str)  # processed, total, current file
    sig_error = QtCore.Signal(str)
    sig_finished = QtCore.Signal(bool, int)  # ok, errors_count

    def __init__(self, api: APIClient, folder_id, local_path: str, project_id: int | str, owner: 'FolderSyncManager'):
        super().__init__()
        self.api = api
        self.folder_id = normalize_id(folder_id)
        self.local_path = str(local_path)
        self.project_id = normalize_id(project_id)
        self._cancelled = False
        self._errors: list[str] = []
        self._owner = owner

    @QtCore.Slot()
    def run(self):
        """Run initial sync using sync_files_new() function."""
        sync_log("=" * 60)
        sync_log("!!! ВОРКЕР ЗАПУЩЕН !!!")
        sync_log("_InitialSyncWorker.run() начал выполнение")
        sync_log("folder_id={}, local_path='{}', project_id={}", self.folder_id, self.local_path, self.project_id)
        sync_log("=" * 60)
        
        self.sig_started.emit()
        sync_log("✓ sig_started отправлен")
        
        ok = True
        try:
            try:
                sync_log("Установка busy флага...")
                self._owner._set_busy(self.folder_id, True)
                sync_log("✓ Busy флаг установлен")
            except Exception as e:
                sync_log("WARNING: не удалось установить busy флаг: {}", str(e))
            
            # Use new sync module for initial sync
            sync_log("=" * 60)
            sync_log("ВЫЗОВ sync_files_new()...")
            sync_log("  api: {}", type(self.api).__name__)
            sync_log("  project_id: {}", self.project_id)
            sync_log("  folder_id: {}", self.folder_id)
            sync_log("  local_root: '{}'", self.local_path)

            # Check if initial sync was already done for this specific folder
            _, initial_sync_done = load_sync_state(self.project_id, self.folder_id)
            use_initial_sync = not initial_sync_done
            sync_log("  is_initial_sync: {} ({} {})", use_initial_sync, "первая синхронизация" if use_initial_sync else "продолжение", "начальная синхронизация была выполнена" if initial_sync_done else "")
            sync_log("=" * 60)
            
            result = sync_files_new(
                api=self.api,
                project_id=self.project_id,
                folder_id=self.folder_id,
                local_root=self.local_path,
                dry_run=False,
                is_initial_sync=use_initial_sync
            )
            
            sync_log("=" * 60)
            sync_log("sync_files_new() ЗАВЕРШЁН")
            sync_log("result keys: {}", list(result.keys()) if isinstance(result, dict) else "НЕ СЛОВАРЬ!")
            sync_log("=" * 60)
            
            if result.get("success"):
                stats = result.get("stats", {})
                total = stats.get("downloaded", 0) + stats.get("uploaded", 0)
                sync_log("INITIAL_SYNC: Success - downloaded={} uploaded={} errors={}", 
                        stats.get("downloaded", 0), stats.get("uploaded", 0), len(stats.get("errors", [])))
                self.sig_total.emit(total)
                self.sig_progress.emit(total, total, "Готово")
                self.sig_finished.emit(True, len(stats.get("errors", [])))
            else:
                errors = result.get("errors", [])
                sync_log("INITIAL_SYNC: Failed - errors={}", errors)
                self.sig_error.emit(f"Ошибки синхронизации: {len(errors)}")
                self.sig_finished.emit(False, len(errors))
            
            # OLD CODE BELOW - REMOVED
            
        except Exception as e:
            ok = False
            sync_log("=" * 60)
            sync_log("!!! КРИТИЧЕСКАЯ ОШИБКА В ВОРКЕРЕ !!!")
            sync_log("Exception: {}", str(e))
            import traceback
            sync_log("TRACEBACK:\n{}", traceback.format_exc())
            sync_log("=" * 60)
            self.sig_error.emit(str(e))
            self.sig_finished.emit(False, 1)
        finally:
            # Cleanup - ВСЕГДА снимаем busy флаг
            try:
                sync_log("Снятие busy флага...")
                self._owner._set_busy(self.folder_id, False)
                sync_log("✓ Busy флаг снят")
            except Exception as e:
                sync_log("WARNING: не удалось снять busy флаг: {}", str(e))

            pass

    @QtCore.Slot()
    def cancel(self):
        self._cancelled = True



class _ImmediateSyncRunner(QtCore.QObject):
    """Background runner to execute a full sync pass (download/upload/delete)
    for an already configured mapping without blocking the UI.
    """
    sig_started = QtCore.Signal()
    sig_finished = QtCore.Signal(bool, str)  # ok, folder_id (legacy)
    sig_result = QtCore.Signal(dict)  # structured per-folder result

    def __init__(self, sync_mgr: 'FolderSyncManager', folder_id: int):
        super().__init__()
        self._mgr = sync_mgr
        self._fid = normalize_id(folder_id)
        self.folder_id = self._fid
        self.allow_mass_delete: bool = False
        self.sync_mode: str = "manual"

    @QtCore.Slot()
    def run(self):
        self.sig_started.emit()
        ok = True
        result: dict | None = None
        try:
            result = self._mgr.sync_now(self._fid, allow_mass_delete=bool(self.allow_mass_delete), sync_mode=str(self.sync_mode or "manual"))
            ok = bool(isinstance(result, dict) and result.get("success"))
        except Exception:
            ok = False
        # Always emit structured result if available.
        try:
            if isinstance(result, dict):
                self.sig_result.emit(result)
        except Exception:
            pass
        self.sig_finished.emit(ok, self._fid)


class _AutoSyncAllRunner(QtCore.QObject):
    """Background runner for periodic auto sync.

    Runs FolderSyncManager.sync_all(sync_mode='auto') in a worker thread so the
    GUI thread remains responsive.
    """

    sig_started = QtCore.Signal()
    sig_finished = QtCore.Signal(list)  # list of per-folder structured results
    sig_error = QtCore.Signal(str)

    def __init__(self, sync_mgr: 'FolderSyncManager'):
        super().__init__()
        self._mgr = sync_mgr

    @QtCore.Slot()
    def run(self):
        sync_log("AUTO_SYNC: worker run started")
        try:
            self.sig_started.emit()
        except Exception:
            pass

        results: list[dict] = []
        t0 = None
        try:
            import time as _time
            t0 = float(_time.time())
        except Exception:
            t0 = None

        try:
            results = self._mgr.sync_all(sync_mode="auto") or []
        except Exception as e:
            try:
                import traceback
                sync_exc(f"AUTO_SYNC worker exception: {e}\n{traceback.format_exc()}")
            except Exception:
                pass
            try:
                self.sig_error.emit(str(e))
            except Exception:
                pass
            results = []
        finally:
            try:
                if t0 is not None:
                    import time as _time
                    dur = float(_time.time()) - float(t0)
                    sync_log("AUTO_SYNC: duration {:.2f}s results={}", dur, len(results) if isinstance(results, list) else -1)
            except Exception:
                pass
            try:
                # Always emit finished so manager can reschedule.
                self.sig_finished.emit(list(results) if isinstance(results, list) else [])
            except Exception:
                pass
