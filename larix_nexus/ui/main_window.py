# -*- coding: utf-8 -*-

import os
import json
import sys
import time
import zipfile
import math
import re
import tempfile
import shutil
import hashlib
import uuid
import logging
import threading
import platform
from typing import Optional, Dict, Any, Callable
from pathlib import Path
import subprocess
import keyring
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- Qt imports: PySide6 only ---
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
    # base
    QApplication, QMainWindow, QWidget, QFrame, QWidgetAction,
    # layouts
    QVBoxLayout, QHBoxLayout, QGridLayout, QLayout, QFormLayout,
    # controls
    QLabel, QPushButton, QToolButton, QLineEdit, QComboBox, QCheckBox,
    QProgressBar, QPlainTextEdit, QInputDialog, QDialog, QDialogButtonBox, QMenu,
    QListView, QListWidget, QListWidgetItem,
    QStatusBar, QHeaderView, QTableView, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem,
    QSplitter, QFileDialog, QSizePolicy, QMessageBox,
    # delegates/styles
    QStyledItemDelegate, QStyle, QStyleOptionButton, QStyleOptionViewItem, QStyleOptionHeader, QAbstractItemView, QProxyStyle,
    # gfx effects
    QGraphicsDropShadowEffect, QGraphicsOpacityEffect,
    # misc
    QAbstractButton, QDateEdit, QCalendarWidget,
)


from PySide6 import QtCore, QtGui, QtWidgets

import requests
from zoneinfo import ZoneInfo, available_timezones
import ctypes
from ctypes import wintypes
import uuid
try:
    from requests_toolbelt.multipart.encoder import MultipartEncoder  # type: ignore
except Exception:
    MultipartEncoder = None  # type: ignore 

# Imports from larix_nexus modules
from larix_nexus.api import APIClient
from larix_nexus.sync import sync_files_new

# Import sync manager from larix_nexus.sync module
import sys
import os
try:
    from larix_nexus.sync.manager import FolderSyncManager, _InitialSyncWorker, _ImmediateSyncRunner
    print(f"[IMPORT] Successfully imported FolderSyncManager from larix_nexus.sync.manager")
except Exception as e:
    print(f"[IMPORT ERROR] Failed to import FolderSyncManager from larix_nexus.sync.manager: {e}")
    import traceback
    traceback.print_exc()
    FolderSyncManager = None
    _InitialSyncWorker = None
    _ImmediateSyncRunner = None
from larix_nexus.constants import (
    APP_TITLE, BASE_URL, DOWNLOAD_DIR, CACHE_TTL_SEC,
    CHECKBOX_COLUMN_WIDTH, NOTIFY_DB_PATH, NOTIFY_SETTINGS_GROUP,
    SETTINGS_ORG, SETTINGS_APP, SETTINGS_THEME_KEY,
    THEME_LIGHT, THEME_DARK, LIGHT_THEME_QSS, DARK_THEME_QSS, EXTRA_QSS,
    _COLOR_REPLACEMENTS, ICON_BOX, SYNC_ROLE, NOTIFY_ROLE,
    ALARM_ICON_PATH, ALARM1_ICON_PATH, LOGIN_ICON_PATH, CHOICE_ICON_PATH, EYE_OPEN_ICON_PATH, EYE_CLOSED_ICON_PATH,
    SORT_ICON_UP_PATH, SORT_ICON_DOWN_PATH, ARROW_LEFT_PATH, ARROW_RIGHT_PATH,
    FILTER_ICON_PATH, REFRESH_ICON_PATH, INSERT_ICON_PATH, EDIT_ICON_PATH, DELETE_ICON_PATH,
    STRUCTURE_ICON_PATH, SYNC_ICON_PATH, COMPARISON_ICON_PATH, MOVE_FOLDER_ICON_PATH,
    COPY_FOLDER_ICON_PATH, BACK_ICON_PATH, CUSTOM_FOLDER_ICON_PATH, NO_FOLDER_ICON_PATH,
    CUSTOM_SAVE_ICON_PATH, CUSTOM_PLUS_ICON_PATH, DOWN_ARROW_ICON_PATH, FLASH_ICON_PATH,
    CAD_ICON_PATH, GEAR_ICON_NAME, CHECK_ICON_OFF_PATH, CHECK_ICON_ON_PATH, CHECK_ICON_MID_PATH
)
from larix_nexus.utils.paths import rsrc_path, program_dir, ICON_PATH
from larix_nexus.utils.logging import sync_log, sync_exc, _cleanup_sync_log_file, _sync_log_path
from larix_nexus.utils.copy_logger import copy_log
from larix_nexus.utils.keyring import (
    save_credential, get_credential, delete_credential, clear_all_credentials
)
from larix_nexus.utils.settings import load_settings, save_settings
from larix_nexus.utils.theme import (
    apply_light_theme, apply_dark_theme, _is_dark_mode, load_saved_theme,
    save_theme,
    load_white_icon, white_tinted_icon, themed_icon
)
from larix_nexus.utils.helpers import normalize_id, normalize_project_id, _set_window_theme_dark, compare_file_states
from larix_nexus.utils.atomic_json import atomic_read_json, atomic_write_json, atomic_update_json
from larix_nexus.utils.i18n import t, get_language_manager, is_russian, is_english, LANGUAGE_RU, LANGUAGE_EN
from larix_nexus.notifications import (
    init_notifications_db,
    load_pending_notifications,
    save_pending_notifications,
    load_folder_notifications,
    is_folder_notification_enabled,
    save_folder_notification,
    remove_folder_notification,
    save_user_actions_log,
    load_user_actions_log,
)
from larix_nexus.models.files_table import FilesTableModel, IconProvider, file_ext
from larix_nexus.models.tombstone_table import TombstoneTableModel

# Imports from ui modules
from .widgets import (
    NikCheckBoxStyle, ThemeToggle, StickyMenu, HeaderCheckButton,
    SortHeader, BusyDots, WaitDialog, ItemViewNoNativeHighlightStyle,
    CHECK_ICON_OFF_PATH, CHECK_ICON_ON_PATH
)
from .delegates import CheckBoxDelegate, CheckBoxDelegateBg
from .delegates import RowHoverDelegate, MenuLikeTreeDelegate, install_viewport_row_highlighter
from ..api.client import PopupComboBox
from .dialogs import BatchUploadDialog, parse_date_like, _user_display_datetime

# Imports from utils
from larix_nexus.utils.theme import (
    white_tinted_icon, _app_settings, _cloud_tz_offset_minutes
)

# Helper functions
import re
def _sanitize_filename(name: str) -> str:
    """Sanitize filename by removing/replacing invalid characters."""
    return re.sub(r"[\\/:*?\"<>|]+", "_", str(name or ""))


def normalize_size(item: dict) -> int:
    """Extract size from item dict."""
    for key in ("size", "fileSize", "sizeBytes", "length", "contentLength"):
        if key in item and item.get(key) not in (None, ""):
            try:
                return int(float(item.get(key)))
            except (ValueError, TypeError):
                try:
                    return int(item.get(key))
                except (ValueError, TypeError):
                    pass
    return 0


def open_in_os(path: str) -> bool:
    """Open file/folder in OS default application."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False


def _is_file(item) -> bool:
    """Check if item is a file."""
    if not isinstance(item, dict):
        return False
    t = str(item.get("type", "")).lower()
    is_file = t in ("file", "файл", "document")
    return is_file


def _is_folder(item) -> bool:
    """Check if item is a folder."""
    if not isinstance(item, dict):
        return False
    t = str(item.get("type", "")).lower()
    is_folder = t in ("folder", "dir", "directory", "папка")
    return is_folder


# Local icon path constants
CUSTOM_ICONS_DIR = rsrc_path("icon")
ARROW_ICON_PATHS = {
    "left": ARROW_LEFT_PATH,
    "right": ARROW_RIGHT_PATH,
    "up": SORT_ICON_UP_PATH,
    "down": SORT_ICON_DOWN_PATH,
}

# Local helper functions
def get_title(node: dict) -> str:
    return (node or {}).get("name") or (node or {}).get("title") or t("untitled")

def cleanup_removed(view):
    try:
        model = view.model()
        if model is None:
            return

        valid_ids: set[int] = set()

        def _walk(parent=QtCore.QModelIndex()):
            try:
                rows = model.rowCount(parent)
            except Exception:
                rows = 0
            for r in range(rows):
                idx = model.index(r, 0, parent)
                try:
                    if model.hasChildren(idx):
                        _walk(idx)
                except Exception:
                    pass

        _walk()
    except Exception:
        valid_ids = set()

    try:
        delegate = (
            view.itemDelegateForColumn(0)
            if hasattr(view, "itemDelegateForColumn") else view.itemDelegate()
        )
    except Exception:
        delegate = None

    if delegate is not None and hasattr(delegate, "_anim_start"):
        try:
            keys = list(getattr(delegate, "_anim_start") or {})
            stale = [k for k in keys if isinstance(k, tuple) and (k and k[0] not in valid_ids)]
            for k in stale:
                try:
                    del delegate._anim_start[k]
                except Exception:
                    pass
            if (not getattr(delegate, "_anim_start", {})) and hasattr(delegate, "_tick"):
                try:
                    delegate._tick.stop()
                except Exception:
                    pass
        except Exception:
            pass

    try:
        view.viewport().update()
    except Exception:
        pass


class WorkspaceDialog(QDialog):
    def __init__(self, workspaces: list, parent=None):
        super().__init__(parent)
        try:
            _is_dark = _is_dark_mode()
        except Exception:
            _is_dark = False
        try:
            if _is_dark:
                _set_window_theme_dark(self, dark=True)
        except Exception:
            pass
        try:
            self.setWindowIcon(load_white_icon(CHOICE_ICON_PATH) if _is_dark else QIcon(CHOICE_ICON_PATH))
        except Exception:
            pass
        self.setWindowTitle(t("workspace.title"))
        self.setMinimumWidth(400)

        print(f"[WORKSPACE] Initializing dialog with {len(workspaces)} workspaces")

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(t("workspace.select")))

        self.cb_workspaces = QComboBox()
        self.cb_workspaces.setObjectName("workspacesCombo")
        try:
            view = self.cb_workspaces.view()
            if view is not None:
                view.setMouseTracking(True)
                view.viewport().setMouseTracking(True)
                view.setAttribute(Qt.WA_Hover, True)
                view.viewport().setAttribute(Qt.WA_Hover, True)
        except Exception:
            pass

        self.cb_workspaces.addItem(t("workspace.placeholder"), userData=None)
        try:
            m = self.cb_workspaces.model()
            it0 = m.item(0) if m is not None and hasattr(m, "item") else None
            if it0 is not None:
                it0.setEnabled(False)
        except Exception:
            pass

        for ws in workspaces:
            ws_id = ws.get("id") or ws.get("workspace_id")
            name = ws.get("name") or ws.get("title") or str(ws_id or "")
            print(f"[WORKSPACE] Adding workspace: id={ws_id} name={name}")
            self.cb_workspaces.addItem(name, userData=ws_id)
        self.cb_workspaces.setCurrentIndex(0)
        layout.addWidget(self.cb_workspaces)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        try:
            ok_btn = btns.button(QDialogButtonBox.Ok)
            if ok_btn is not None:
                ok_btn.setEnabled(False)

            def _sync_ok_state(_idx: int):
                try:
                    b = btns.button(QDialogButtonBox.Ok)
                    if b is not None:
                        b.setEnabled(int(self.cb_workspaces.currentIndex()) > 0)
                except Exception:
                    pass

            self.cb_workspaces.currentIndexChanged.connect(_sync_ok_state)
        except Exception:
            pass
        layout.addWidget(btns)

    def selected_workspace_id(self):
        try:
            idx = self.cb_workspaces.currentIndex()
            ws_id = self.cb_workspaces.itemData(idx) if idx >= 0 else None
            print(f"[WORKSPACE] Selected workspace id={ws_id}")
            return ws_id
        except Exception as e:
            print(f"[WORKSPACE DIALOG ERROR] selected_workspace_id failed: {e}")
            return None


class LoginDialog(QDialog):
    def __init__(self, api: APIClient, parent=None):
        super().__init__(parent)
        try:
            _is_dark = _is_dark_mode()
        except Exception:
            _is_dark = False
        try:
            if _is_dark:
                _set_window_theme_dark(self, dark=True)
        except Exception:
            pass
        self.setWindowIcon(load_white_icon(LOGIN_ICON_PATH) if _is_dark else QIcon(LOGIN_ICON_PATH))
        self.api = api
        self.setWindowTitle(t("auth.title"))
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        form_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        settings = load_settings()
        saved_username = settings.get("last_username", "")

        self.le_username = QLineEdit(saved_username)
        form_layout.addRow(QLabel(t("auth.login")), self.le_username)

        self.le_password = QLineEdit()
        self.le_password.setEchoMode(QLineEdit.Password)
        self.le_username.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.le_password.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self._eye_btn = QToolButton(self.le_password)
        self._eye_btn.setObjectName("pw_eye")
        self._eye_btn.setAutoRaise(True)
        self._eye_btn.setIconSize(QSize(16, 16))
        self._eye_btn.setCheckable(True); self._eye_btn.setCursor(Qt.PointingHandCursor)
        self._eye_btn.setAutoRaise(True); self._eye_btn.setFocusPolicy(Qt.NoFocus)
        self._eye_btn.setFixedSize(18, 18)
        if EYE_CLOSED_ICON_PATH and os.path.exists(EYE_CLOSED_ICON_PATH):
            try:
                _is_dark = _is_dark_mode()
            except Exception:
                _is_dark = False
            self._eye_btn.setIcon(load_white_icon(EYE_CLOSED_ICON_PATH) if _is_dark else QIcon(EYE_CLOSED_ICON_PATH))
        else:
            self._eye_btn.setText("??")

        self.le_password.setTextMargins(0, 0, 30, 0)
        def _pos_eye():
            r = self.le_password.rect()
            self._eye_btn.move(r.right() - 26, r.center().y() - 10)

        def _wrap_resize(e):
            try: QLineEdit.resizeEvent(self.le_password, e)
            finally: _pos_eye()
        self.le_password.resizeEvent = _wrap_resize
        _pos_eye()

        def _sync_eye(on: bool):
            self.le_password.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password)
            path = EYE_OPEN_ICON_PATH if on else EYE_CLOSED_ICON_PATH
            if path and os.path.exists(path):
                try:
                    _is_dark = _is_dark_mode()
                except Exception:
                    _is_dark = False
                self._eye_btn.setIcon(load_white_icon(path) if _is_dark else QIcon(path))
                self._eye_btn.setText("")
            else:
                self._eye_btn.setIcon(QIcon())
                self._eye_btn.setText(t("auth.show_password") if not on else t("auth.hide_password"))
        self.le_password.setTextMargins(0, 0, 24, 0)
        self._eye_btn.toggled.connect(_sync_eye)
        _sync_eye(False)

        form_layout.addRow(QLabel(t("auth.password")), self.le_password)

        layout.addLayout(form_layout)

        self.cb_remember = QCheckBox(t("auth.remember_me"))
        self.cb_remember.setChecked(settings.get("remember_me", True))
        layout.addWidget(self.cb_remember)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        btns.accepted.connect(self._try_login); btns.rejected.connect(self.reject)
        layout.addWidget(btns)
        w = QApplication.focusWidget()
        if w:
            w.clearFocus()

        self.le_username.setFocusPolicy(Qt.ClickFocus)
        self.le_password.setFocusPolicy(Qt.ClickFocus)

        ok_btn = btns.button(QDialogButtonBox.Ok)
        cancel_btn = btns.button(QDialogButtonBox.Cancel)
        if ok_btn:
            ok_btn.setAutoDefault(False)
            ok_btn.setDefault(False)
        if cancel_btn:
            cancel_btn.setAutoDefault(False)
            cancel_btn.setDefault(False)

    def _try_login(self):
        u = self.le_username.text().strip()
        p = self.le_password.text().strip()
        remember = self.cb_remember.isChecked()

        if not u or not p:
            QMessageBox.warning(self, t("common.error"), t("auth.login_empty"))
            return

        if self.api.login(u, p, remember_me=remember):
            settings = load_settings()
            settings["remember_me"] = remember
            save_settings(settings)
            self.accept()
            return

        QMessageBox.critical(self, t("common.error"), t("auth.login_failed"))


# --- Import PDF_Compare window for integrated PDF comparison ---
try:
    from larix_nexus.pdf.PDF_Compare import (
        PDFCompareWindow,
        apply_dekstop_style as pdf_apply_style,
        _set_window_theme as pdf_set_window_theme,
    )
except Exception:
    PDFCompareWindow = None  # type: ignore
    pdf_apply_style = None  # type: ignore
    pdf_set_window_theme = None  # type: ignore


class MainWindow(QMainWindow):
    def eventFilter(self, obj, ev):
        try:
            # Отслеживание активности пользователя для автообновления
            event_type = ev.type()
            if event_type in (
                QtCore.QEvent.MouseButtonPress,
                QtCore.QEvent.MouseButtonRelease, 
                QtCore.QEvent.MouseMove,
                QtCore.QEvent.KeyPress,
                QtCore.QEvent.KeyRelease,
                QtCore.QEvent.Wheel,
            ):
                try:
                    self._last_user_activity = time.time()
                    # Сбросить таймер автообновления
                    if hasattr(self, '_auto_refresh_timer') and self._auto_refresh_timer:
                        self._auto_refresh_timer.stop()
                        self._auto_refresh_timer.start()
                except Exception:
                    pass
            
            # Перенаправляем клики по области чекбокса заголовка на сам чекбокс
            if hasattr(self, "hdr") and self.hdr and obj is self.hdr.viewport():
                t = ev.type()
                if t in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease):
                    cb = getattr(self, "hdrcb", None)
                    if cb is None:
                        return super().eventFilter(obj, ev)
                    # Avoid native crash if the underlying QObject was deleted.
                    try:
                        from shiboken6 import isValid  # type: ignore
                        if not isValid(cb):
                            return super().eventFilter(obj, ev)
                    except Exception:
                        pass

                    if cb and cb.isVisible():
                        g = cb.geometry()
                        if g.contains(ev.pos()):
                            print(f"[eventFilter] Click on header checkbox area, button={ev.button()}")
                            pos = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
                            local = pos - g.topLeft()
                            qev = QtGui.QMouseEvent(t, local, ev.button(), ev.buttons(), ev.modifiers())
                            QtWidgets.QApplication.sendEvent(cb, qev)
                            if t == QtCore.QEvent.MouseButtonRelease and ev.button() == Qt.LeftButton:
                                print(f"[eventFilter] Calling nextCheckState()")
                                try:
                                    cb.nextCheckState()
                                except Exception:
                                    pass
                            return True
            return super().eventFilter(obj, ev)
        except Exception:
            return False

    def _resolve_icon_path(self, name: str) -> str:
        candidates = [
            os.path.join(CUSTOM_ICONS_DIR, name),
            os.path.join(os.path.dirname(__file__), name),
            name
        ]
        for p in candidates:
            try:
                if p and os.path.exists(p):
                    return p
            except Exception:
                pass
        return ""

    def _set_progress_cancel_handler(self, handler):
        """Install/clear cancel handler for the status-bar progress UI."""
        try:
            self._progress_cancel_handler = handler
        except Exception:
            pass

        try:
            btn = getattr(self, "_progress_cancel_btn", None)
            if btn is not None:
                btn.setText(t("common.cancel"))
                btn.setEnabled(handler is not None)
                # Show the cancel chip only when progress is visible and cancel is supported.
                btn.setVisible(bool(handler) and bool(getattr(self, "progress", None) and self.progress.isVisible()))
        except Exception:
            pass

    def _set_progress_visible(self, visible: bool):
        """Set visibility of progress UI (busy dots + optional cancel)."""
        self.progress.setVisible(visible)

        # When progress hides, also clear any previous cancel handler to avoid
        # accidentally canceling the wrong operation next time.
        if not visible:
            try:
                self._progress_cancel_handler = None
            except Exception:
                pass

        # Cancel chip is shown only when a handler is installed.
        try:
            btn = getattr(self, "_progress_cancel_btn", None)
            handler = getattr(self, "_progress_cancel_handler", None)
            if btn is not None:
                btn.setVisible(bool(visible) and callable(handler))
                btn.setEnabled(callable(handler))
                if visible and callable(handler):
                    btn.setText(t("common.cancel"))
        except Exception:
            pass

        if visible:
            self._progress_cancelled = False

    def _on_progress_cancel(self):
        """Handle progress cancel button click."""
        self._progress_cancelled = True
        try:
            btn = getattr(self, "_progress_cancel_btn", None)
            if btn is not None:
                btn.setEnabled(False)
                btn.setText(t("status.cancelling"))
        except Exception:
            pass

        try:
            handler = getattr(self, "_progress_cancel_handler", None)
            if callable(handler):
                handler()
        except Exception:
            pass

    # --- persist UI preferences ---
    # Sync UI handlers are injected from larix_nexus.ui.sync_handlers

    class _HoverIconFilter(QtCore.QObject):
        """Hover helper: do not recolor icons on hover (keep original/themed)."""
        def __init__(self, btn: QAbstractButton):
            super().__init__(btn)
            self._btn = btn
            self._normal = btn.icon() if hasattr(btn, 'icon') else QIcon()
            size = btn.iconSize() if hasattr(btn, 'iconSize') else QSize(16, 16)
            try:
                base = str(btn.property('baseIconPath') or '')
            except Exception:
                base = ''
            pm = QPixmap(base) if base and os.path.exists(base) else self._normal.pixmap(size)
            if not pm.isNull():
                pm = pm.scaled(max(8, size.width()), max(8, size.height()), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            # Do not tint to black on hover; keep the same icon
            self._hover = self._normal

        def eventFilter(self, obj, ev):
            t = ev.type()
            if t in (QEvent.Enter, QEvent.HoverEnter, QEvent.FocusIn, QEvent.MouseMove):
                if isinstance(self._btn, QAbstractButton) and getattr(self._btn, 'isEnabled', lambda: True)():
                    # Keep original/themed icon on hover
                    self._btn.setIcon(self._hover)
            elif t in (QEvent.Leave, QEvent.HoverLeave, QEvent.FocusOut, QEvent.EnabledChange):
                if isinstance(self._btn, QAbstractButton):
                    self._btn.setIcon(self._normal)
            return False

    def __init__(self):
        super().__init__()
        
        # Очистка логов sync при запуске приложения
        try:
            sync_log_path = _sync_log_path()
            if sync_log_path and os.path.exists(sync_log_path):
                with open(sync_log_path, 'w', encoding='utf-8') as f:
                    f.write('')
                print(f"[STARTUP] Cleared sync log: {sync_log_path}")
        except Exception as e:
            print(f"[STARTUP] Error clearing sync log: {e}")
        
        self.setWindowTitle(APP_TITLE)
        # УБРАНО: setWindowIcon - иконка окна не нужна внутри интерфейса
        # if ICON_PATH and os.path.exists(ICON_PATH):
        #     self.setWindowIcon(QIcon(ICON_PATH))
        self.resize(1280, 780)

        self.api = APIClient(BASE_URL)
        
        # Initialize FolderSyncManager if available
        if FolderSyncManager is not None:
            try:
                sync_log("=" * 60)
                sync_log("Инициализация FolderSyncManager...")
                self.sync2 = FolderSyncManager(self.api, self)
                sync_log("✓ FolderSyncManager создан успешно")
                
                # Connect signals for UI updates
                try:
                    self.sync2.autoSyncStarted.connect(self._on_auto_sync_started, QtCore.Qt.QueuedConnection)
                    self.sync2.autoSyncFinished.connect(self._on_auto_sync_finished, QtCore.Qt.QueuedConnection)
                    self.sync2.syncItem.connect(self._on_sync_item, QtCore.Qt.QueuedConnection)
                    sync_log("✓ Сигналы FolderSyncManager подключены")
                except Exception as e:
                    sync_log("WARNING: не удалось подключить сигналы FolderSyncManager: {}", str(e))
                
                self.sync2.start_if_configured()
                sync_log("✓ start_if_configured() выполнен")
                sync_log("=" * 60)
            except Exception as e:
                sync_log("!!! КРИТИЧЕСКАЯ ОШИБКА при создании FolderSyncManager !!!")
                sync_log("Exception: {}", str(e))
                import traceback
                sync_log("TRACEBACK:\n{}", traceback.format_exc())
                sync_log("=" * 60)
                print(f"ERROR: Failed to create FolderSyncManager: {e}")
                traceback.print_exc()
                self.sync2 = None
        else:
            print("WARNING: FolderSyncManager not available from larix_nexus.sync.manager")
            self.sync2 = None
        
        self.icon_provider = IconProvider(self.style())
        self._checkbox_style = NikCheckBoxStyle(self.style())
        # Stable ordering: keep visible order during metadata enrichment
        self._freeze_visible_order = False
        self._frozen_order = {}
        # Track all running ad-hoc sync threads to prevent premature destruction
        self._sync_now_threads: set[QtCore.QThread] = set()
        self.chips = {}  # словарь чипов форматов (DOC/PDF/JPG/CAD); может быть пустым на старте
        self._current_theme = THEME_LIGHT  # Всегда начинаем со светлой темы


        # Верхняя панель
        top = QWidget(self); top_l = QHBoxLayout(top); top_l.setContentsMargins(0,0,0,0); top_l.setSpacing(8)
        # self.lbl_docs = QLabel("Документы", self); self.lbl_docs.setObjectName("Header")
        self.cb_projects = PopupComboBox(self)
        # стиль выпадающего списка проектов
        # после: self.cb_projects = PopupComboBox(self)  # или QComboBox(self)
        self.cb_projects.setObjectName("projectsCombo")

        try:
            projects_view = self.cb_projects.view()
            if projects_view is not None:
                projects_view.setMouseTracking(True)
                projects_view.viewport().setMouseTracking(True)
                projects_view.setAttribute(Qt.WA_Hover, True)
                projects_view.viewport().setAttribute(Qt.WA_Hover, True)
        except Exception:
            pass

        self.cb_projects.setMinimumWidth(420); self.cb_projects.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        try:
            self.cb_projects.aboutToPopup.connect(self.ensure_projects_loaded)
            self.cb_projects.aboutToPopup.connect(self.adjust_projects_popup)
        except Exception:
            pass

        # Ensure project dropdown hover highlight is always visible.
        try:
            self.cb_projects.aboutToPopup.connect(self._style_projects_combo_popup)
        except Exception:
            pass
        try:
            self._style_projects_combo_popup()
        except Exception:
            pass
       # Обновить
        self.btn_refresh = QToolButton(self)
        self.btn_refresh.setObjectName("btnRefresh")
        self.btn_refresh.setProperty("secondary", True)                # как у скачивания/загрузки — белая «таблетка»
        self._refresh_secondary_style(self.btn_refresh)
        self.btn_refresh.setToolButtonStyle(Qt.ToolButtonIconOnly)     # только иконка
        self.btn_refresh.setIcon(self._themed_icon(REFRESH_ICON_PATH, tint_allowed=False))
        self.btn_refresh.setText("")                                   # убираем текст
        self.btn_refresh.setToolTip(t("toolbar.refresh"))

        # чтобы размер совпадал с другими (например, со «Скачать»)
        if hasattr(self, "btn_download"):
            self.btn_refresh.setIconSize(self.btn_download.iconSize())
        else:
            # запасной вариант — системный малый размер
            size_px = self.style().pixelMetric(QStyle.PM_SmallIconSize)
            self.btn_refresh.setIconSize(QSize(size_px, size_px))

        # Back button (previous folder)
        self.btn_back = QToolButton(self)
        self.btn_back.setProperty("secondary", True)
        self._refresh_secondary_style(self.btn_back)
        self.btn_back.setToolButtonStyle(Qt.ToolButtonIconOnly)
        try:
            if BACK_ICON_PATH and os.path.exists(BACK_ICON_PATH):
                self.btn_back.setIcon(self._themed_icon(BACK_ICON_PATH))
        except Exception:
            pass
        self.btn_back.setText("")
        self.btn_back.setToolTip(t("toolbar.back"))
        try:
            self.btn_back.setIconSize(self.btn_refresh.iconSize())
        except Exception:
            pass
        self.btn_back.setEnabled(False)

        # Sync-all button (to the right of Back)
        self.btn_sync_all = QToolButton(self)
        self.btn_sync_all.setProperty("secondary", True)
        self._refresh_secondary_style(self.btn_sync_all)
        self.btn_sync_all.setToolButtonStyle(Qt.ToolButtonIconOnly)
        try:
            if SYNC_ICON_PATH and os.path.exists(SYNC_ICON_PATH):
                self.btn_sync_all.setIcon(self._themed_icon(SYNC_ICON_PATH))
        except Exception:
            pass
        self.btn_sync_all.setText("")
        self.btn_sync_all.setToolTip(t("toolbar.sync_all"))
        try:
            self.btn_sync_all.setIconSize(self.btn_refresh.iconSize())
        except Exception:
            pass
        try:
            self.btn_sync_all.clicked.connect(self._on_sync_all_clicked)
        except Exception:
            pass

        self.btn_go_to_root = QToolButton(self); self.btn_go_to_root.setText(t("common.go_to_root")); self.btn_go_to_root.setProperty("secondary", True)
        self._refresh_secondary_style(self.btn_go_to_root)
        self.btn_login = QToolButton(self); self.btn_login.setText(t("toolbar.login")); self.btn_login.setProperty("secondary", False)
        self.btn_login.setEnabled(True); self.btn_login.setCursor(Qt.PointingHandCursor); self.btn_login.setObjectName("accent")

        self.btn_plus = QToolButton(self); self.btn_plus.setText("+")
        self.btn_plus.setObjectName("btnPlus")
        self.btn_plus.setPopupMode(QToolButton.InstantPopup)
        self.btn_plus.setProperty("secondary", True)
        self._refresh_secondary_style(self.btn_plus)
        if hasattr(self, "btn_download"):
            self.btn_plus.setIconSize(self.btn_download.iconSize())
        self.btn_plus.setToolTip(t("toolbar.add"))

        try:
            if CUSTOM_PLUS_ICON_PATH and os.path.exists(CUSTOM_PLUS_ICON_PATH):
                self.btn_plus.setIcon(self._themed_icon(CUSTOM_PLUS_ICON_PATH)); self.btn_plus.setText("")
        except Exception:
            pass

        menu_plus = QMenu(self.btn_plus)
        menu_plus.setObjectName("plusMenu")
        try:
            menu_plus.triggered.connect(lambda a: sync_log("UI: plusMenu triggered action={}", getattr(a, 'text', lambda: str(a))()))
        except Exception:
            pass
        try:
            menu_plus.setMinimumWidth(160)
            menu_plus.setMaximumWidth(220)
        except Exception:
            pass

        self.act_upload_file = QAction(t("menu.upload_file"), self)
        self.act_upload_file.triggered.connect(self._action_upload_file)

        try:
            self.act_upload_file.triggered.connect(lambda: sync_log("UI: act_upload_file triggered"))
        except Exception:
            pass

        self.act_create_folder = QAction(t("menu.create_folder"), self)
        self.act_create_folder.triggered.connect(self._action_create_folder)

        self.act_upload_folder = QAction(t("menu.upload_folder"), self)
        self.act_upload_folder.triggered.connect(self._action_upload_folder)

        menu_plus.addAction(self.act_upload_file)
        menu_plus.addAction(self.act_create_folder)
        menu_plus.addAction(self.act_upload_folder)

        self.btn_plus.setMenu(menu_plus)
        self.btn_plus.setPopupMode(QToolButton.InstantPopup)

        menu_plus.aboutToShow.connect(self._update_upload_menu_visibility)

        self.btn_login.setEnabled(True); self.btn_login.setCursor(Qt.PointingHandCursor); self.btn_login.setObjectName("accent")
        self.btn_user = QToolButton(self); self.btn_user.setVisible(False); self.btn_user.setPopupMode(QToolButton.InstantPopup)
        self.btn_user.setObjectName("btnUser")
        self.btn_user_menu = QMenu(self.btn_user); self.btn_user.setMenu(self.btn_user_menu)
        self.btn_user_menu.setObjectName("userMenu")

        self.btn_user_menu.clear()
        self.act_switch_user = self.btn_user_menu.addAction(t("menu.switch_user"))
        self.act_switch_user.triggered.connect(self.logout_and_relogin)

        self.act_select_workspace = self.btn_user_menu.addAction(t("menu.select_workspace"))
        self.act_select_workspace.triggered.connect(self.choose_workspace)


        self.btn_download = QToolButton(self)
        self.btn_download.setProperty("secondary", True)
        self._refresh_secondary_style(self.btn_download)
        self.btn_download.setObjectName("btnDownload")
        self.btn_download.setIcon(white_tinted_icon(self.style().standardIcon(QStyle.SP_DialogSaveButton))); 
        self.btn_download.setToolTip(t("toolbar.download_checked"))
        try:
            if CUSTOM_SAVE_ICON_PATH and os.path.exists(CUSTOM_SAVE_ICON_PATH):
                self.btn_download.setIcon(self._themed_icon(CUSTOM_SAVE_ICON_PATH))
        except Exception:
            pass
        # --- Выпадающее меню у кнопки "Скачать" ---
        try:
            self.btn_download.setPopupMode(QToolButton.InstantPopup)
        except Exception:
            pass
        self.menu_download = QMenu(self.btn_download)   # < есть в конструкторе
        self.menu_download.setObjectName("downloadMenu")  # < добавь сразу после строки выше
        self.btn_download.setMenu(self.menu_download)
        self.btn_download.setPopupMode(QToolButton.InstantPopup)  # оставь так, без стрелки
        # белая тема, как у остальных списков
        try:
            self.menu_download.setStyleSheet

        except Exception:
            pass
        try:
            self.menu_download.aboutToShow.connect(self._refresh_download_menu)
        except Exception:
            pass
        self.btn_download.setMenu(self.menu_download)
        # Не подключаем click->download_checked для режима InstantPopup,
        # чтобы меню определяло единственное действие.

        # CRUD кнопки справа от '+' в фильтрах (создаются здесь, добавляются в фильтры ниже)
        # Переименовать
        self.btn_rename = QToolButton(self)
        self.btn_rename.setProperty("secondary", True)
        self._refresh_secondary_style(self.btn_rename)
        self.btn_rename.setToolButtonStyle(Qt.ToolButtonIconOnly)     # только иконка
        self.btn_rename.setIcon(self._themed_icon(EDIT_ICON_PATH))
        self.btn_rename.setText("")                                   # убираем текст
        self.btn_rename.setToolTip(t("toolbar.rename"))
        # Сравнить версии
        self.btn_compare = QToolButton(self)
        self.btn_compare.setProperty("secondary", True)
        self._refresh_secondary_style(self.btn_compare)
        self.btn_compare.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.btn_compare.setIcon(self._themed_icon(COMPARISON_ICON_PATH))
        self.btn_compare.setIcon(self._themed_icon(COMPARISON_ICON_PATH, tint_allowed=True))
        self.btn_compare.setText("")
        self.btn_compare.setToolTip(t("toolbar.compare_versions"))
        self.btn_compare.setEnabled(False)
 

        # Переместить
        self.btn_move = QToolButton(self)
        self.btn_move.setProperty("secondary", True)
        self._refresh_secondary_style(self.btn_move)
        self.btn_move.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.btn_move.setIcon(self._themed_icon(MOVE_FOLDER_ICON_PATH))
        self.btn_move.setText("")
        self.btn_move.setToolTip(t("toolbar.move"))
        self.btn_move.setEnabled(False)

        # Копировать
        self.btn_copy = QToolButton(self)
        self.btn_copy.setProperty("secondary", True)
        self._refresh_secondary_style(self.btn_copy)
        self.btn_copy.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.btn_copy.setIcon(self._themed_icon(COPY_FOLDER_ICON_PATH))
        self.btn_copy.setText("")
        self.btn_copy.setToolTip(t("toolbar.copy"))
        self.btn_copy.setEnabled(False)

 

        # Удалить
        self.btn_delete = QToolButton(self)
        self.btn_delete.setProperty("secondary", True)
        self._refresh_secondary_style(self.btn_delete)
        self.btn_delete.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.btn_delete.setIcon(self._themed_icon(DELETE_ICON_PATH))
        self.btn_delete.setText("")
        self.btn_delete.setToolTip(t("toolbar.delete"))

        # чтобы размер иконок совпал с кнопкой «скачать»
        same = self.btn_download.iconSize()
        self.btn_rename.setIconSize(same)
        self.btn_delete.setIconSize(same)
        self.btn_compare.setIconSize(same)
        self.btn_move.setIconSize(same)
        self.btn_copy.setIconSize(same)
        for b in (self.btn_download, self.btn_delete, self.btn_rename, self.btn_move, self.btn_copy):
            b.setEnabled(False)

        # Порядок: Документы — Проект: [combo] — Обновить — В корень — Диаграмма — [справа: Войти/Пользователь]
        self.lbl_proj = QLabel(t("common.project_label"), self)
        for w in (self.lbl_proj, self.cb_projects, self.btn_refresh, self.btn_go_to_root, self.btn_back, self.btn_sync_all):
            top_l.addWidget(w)
        top_l.addStretch(1)
        self.theme_toggle = ThemeToggle(parent=self)
        self.theme_toggle.setToolTip(t("toolbar.theme_toggle"))
        self.theme_toggle.blockSignals(True)
        self.theme_toggle.setChecked(False)
        self.theme_toggle.blockSignals(False)
        self.theme_toggle.toggled.connect(self._on_theme_toggled)
        self.themeToggle = self.theme_toggle
        top_l.addWidget(self.theme_toggle)
        
        LANGUAGE_ICON_PATH = rsrc_path("icon", "language.png")
        
        class LanguageButton(QToolButton):
            def __init__(self, parent=None):
                super().__init__(parent)
                self._lang_icon = QIcon()
                self._lang_text = "EN"
                self.setMinimumWidth(70)
                self.setIconSize(QSize(16, 16))
            def setLanguageIcon(self, icon):
                self._lang_icon = icon
                self.update()
            def setLanguageText(self, text):
                self._lang_text = text
                self.update()
            def paintEvent(self, event):
                super().paintEvent(event)
                painter = QPainter(self)
                painter.setRenderHint(QPainter.Antialiasing)
                rect = self.rect()
                margin = 12
                if not self._lang_icon.isNull():
                    icon_x = margin
                    icon_y = (rect.height() - 16) // 2
                    self._lang_icon.paint(painter, icon_x, icon_y, 16, 16)
                font = self.font()
                font.setBold(True)
                painter.setFont(font)
                fm = painter.fontMetrics()
                text_width = fm.horizontalAdvance(self._lang_text)
                text_x = rect.width() - text_width - margin
                text_y = (rect.height() + fm.ascent() - fm.descent()) // 2 - 1
                painter.setClipRect(rect)
                painter.drawText(text_x, text_y, self._lang_text)
        
        self.btn_language = LanguageButton(self)
        self.btn_language.setObjectName("btnLanguage")
        self.btn_language.setProperty("secondary", True)
        self.btn_language.setCursor(Qt.PointingHandCursor)
        self.btn_language.setAutoRaise(False)
        self._refresh_secondary_style(self.btn_language)
        if LANGUAGE_ICON_PATH and os.path.exists(LANGUAGE_ICON_PATH):
            self.btn_language.setLanguageIcon(self._themed_icon(LANGUAGE_ICON_PATH))
        self.btn_language.setLanguageText(self._get_language_code())
        self.btn_language.setToolTip(t("toolbar.language_toggle"))
        self.btn_language.clicked.connect(self._on_language_toggle)
        top_l.addWidget(self.btn_language)
        
        # Notifications button (alarm icon) near theme switch - СПРАВА
        self.btn_notify = QToolButton(self)
        self.btn_notify.setObjectName("btnNotify")
        self.btn_notify.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.btn_notify.setAutoRaise(False)
        self.btn_notify.setCursor(Qt.PointingHandCursor)
        # Use themed icon so it turns white in dark theme
        self.btn_notify.setIcon(self._themed_icon(ALARM_ICON_PATH))
        self.btn_notify.setToolTip(t("toolbar.notifications"))
        # Slightly smaller to make the button look lighter
        self.btn_notify.setIconSize(QSize(16, 16))
        self.menu_notify = QMenu(self.btn_notify)
        self.menu_notify.setObjectName("notifyMenu")
        try:
            # Rebuild menu right before showing to reflect latest pending items
            self.menu_notify.aboutToShow.connect(self._build_notify_menu)
        except Exception:
            pass
        self.btn_notify.setMenu(self.menu_notify)
        self.btn_notify.setPopupMode(QToolButton.InstantPopup)
        top_l.addWidget(self.btn_notify)
        
        
        # Notifications button (alarm icon) near theme switch
        try:
            self._notifications: list[dict] = []  # list of {folder_id, title, path, ts, changes}
            self._subscriptions: dict[int, dict] = {}  # folder_id -> {path, snapshot, pending, title}
        except Exception:
            self._notifications = []
            self._subscriptions = {}
        try:
            self._init_notifications_ui()
        except Exception:
            pass
        try:
            self.tree._dark_theme = False  # светлая тема
            vp = getattr(self.tree, "viewport", None)
            if callable(vp):
                vp = self.tree.viewport()
            if vp is not None:
                setattr(vp, "_dark_theme", False)  # светлая тема
                vp.update()
        except Exception:
            pass
        for w in (self.btn_login, self.btn_user):  # Include btn_login here
            top_l.addWidget(w)

        # Фильтры

        filt = QWidget(self); 
        fl = QHBoxLayout(filt); 
        fl.setContentsMargins(0,0,0,0); 
        fl.setSpacing(8)
        self.search = QLineEdit(self); self.search.setPlaceholderText(t("search.placeholder"))
        # флаг логики (если где-то выше не задан)
        self._search_recursive = getattr(self, "_search_recursive", False)

        # кнопка внутри поля поиска (справа)
        self.btn_search_deep = QToolButton(self.search)
        self.btn_search_deep.setObjectName("searchDeepBtn")
        self.btn_search_deep.setCheckable(True)
        self.btn_search_deep.setChecked(self._search_recursive)
        self.btn_search_deep.setCursor(Qt.PointingHandCursor)
        self.btn_search_deep.setIcon(self._themed_icon(INSERT_ICON_PATH))
        self.btn_search_deep.setToolTip(t("search.recursive"))
        self.btn_search_deep.setAutoRaise(True)
        self.btn_search_deep.setIconSize(self.search.fontMetrics().boundingRect("M").size())
        self.btn_search_deep.setToolButtonStyle(Qt.ToolButtonIconOnly)  # показываем только иконку
        self.btn_search_deep.setIconSize(QSize(16, 16))     
        self.search.setTextMargins(0, 0, 24, 0)

        # обёртка, чтобы добавить кнопку в QLineEdit справа
        self._act_search_recursive = QWidgetAction(self)
        self._act_search_recursive.setDefaultWidget(self.btn_search_deep)
        self.search.addAction(self._act_search_recursive, QLineEdit.TrailingPosition)

        # логика переключения
        self.btn_search_deep.toggled.connect(self._on_search_recursive_toggled)
        self.search.textChanged.connect(lambda _t: self._update_name_search_icon())
        self.cb_flat = QCheckBox("без папок", self)
        try:
            self.cb_flat.setStyle(self._checkbox_style)
        except Exception:
            pass
        self.cb_flat.setVisible(False)  # скрываем старый, но оставляем для логики

        # Кнопка "без папок" — как "Скачать": белая таблетка с иконкой
        self.btn_no_folders = QToolButton(self)
        self.btn_no_folders.setObjectName("btnNoFolders")
        self.btn_no_folders.setProperty("secondary", True)
        self._refresh_secondary_style(self.btn_no_folders)
        self.btn_no_folders.setProperty("chip", True)       # белая «таблетка», как у btn_download
        self.btn_no_folders.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.btn_no_folders.setCheckable(True)
        self.btn_no_folders.setProperty("checked", False)
        self.btn_no_folders.setToolTip(t("filter.no_folders_tooltip"))

        try:
            if os.path.exists(NO_FOLDER_ICON_PATH):
                self.btn_no_folders.setIcon(self._themed_icon(NO_FOLDER_ICON_PATH))
                # иконка ровно как у "Скачать"
                if hasattr(self, "btn_download"):
                    self.btn_no_folders.setIconSize(self.btn_download.iconSize())
            else:
                # запасной вариант, если иконки нет
                self.btn_no_folders.setToolButtonStyle(Qt.ToolButtonTextOnly)
                self.btn_no_folders.setText(t("filter.no_folders"))
        except Exception:
            self.btn_no_folders.setToolButtonStyle(Qt.ToolButtonTextOnly)
            self.btn_no_folders.setText(t("filter.no_folders_short"))

        # Ensure consistent size: force icon-only and icon size same as Download
        try:
            self.btn_no_folders.setToolButtonStyle(Qt.ToolButtonIconOnly)
            if os.path.exists(NO_FOLDER_ICON_PATH):
                self.btn_no_folders.setIcon(self._themed_icon(NO_FOLDER_ICON_PATH))
            if hasattr(self, "btn_download"):
                self.btn_no_folders.setIconSize(self.btn_download.iconSize())
        except Exception:
            pass
        
        def _no_folders_toggled(on: bool):
            self.btn_no_folders.setProperty("checked", on)
            self.btn_no_folders.style().unpolish(self.btn_no_folders)
            self.btn_no_folders.style().polish(self.btn_no_folders)
            self.btn_no_folders.update()
            try:
                self.cb_flat.blockSignals(True)
                self.cb_flat.setChecked(on)
            finally:
                self.cb_flat.blockSignals(False)
            self.on_flat_toggled(on)
        

        fl.addWidget(self.btn_plus)
        fl.addWidget(self.btn_download)
        fl.addWidget(self.btn_rename)
        fl.addWidget(self.btn_compare)
        fl.addWidget(self.btn_move)
        fl.addWidget(self.btn_copy)
        fl.addWidget(self.btn_delete)
        fl.addStretch(1)
        fl.addWidget(self.search)
        fl.addWidget(self.btn_no_folders)
        # - фиксируем высоту всей верхней строки, чтобы таблица не подпрыгивала
        _row_h = self.btn_download.sizeHint().height() + 10
        # filt - это тот QWidget, на котором висит fl = QHBoxLayout(filt)
        filt.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        filt.setFixedHeight(_row_h)


        
        # Кнопка настроек столбцов (шестерёнка)
        self.btn_columns = QToolButton(self)
        self.btn_columns.setObjectName("btnColumns")
        self.btn_columns.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.btn_columns.setPopupMode(QToolButton.InstantPopup)
        self.btn_columns.setToolTip(t("toolbar.column_settings"))
        self.btn_columns.setCursor(Qt.PointingHandCursor)

        # ВАЖНО: тот же «вторичный» стиль, что у btn_download
        self.btn_columns.setProperty("secondary", True)
        self._refresh_secondary_style(self.btn_columns)

        # фиксируем высоту правых кнопок под базовый размер как у "Скачать"
        base_h = min(self.btn_delete.sizeHint().height(), self.btn_rename.sizeHint().height())

        # 1) большие кнопки - как было
        # стало
        for b in [self.btn_plus, self.btn_download, self.btn_rename, self.btn_delete, self.btn_columns, self.btn_no_folders]:
            try:
                b.setFixedHeight(base_h)
            except Exception:
                pass

        # Match icon sizes for settings and no-folders buttons to Download button
        try:
            self.btn_columns.setIconSize(self.btn_download.iconSize())
            self.btn_no_folders.setIconSize(self.btn_download.iconSize())
        except Exception:
            pass


        # конка шестерёнки
        _gear_path = self._resolve_icon_path(GEAR_ICON_NAME)
        if _gear_path:
            self.btn_columns.setIcon(self._themed_icon(_gear_path, tint_allowed=False))
            self.btn_columns.setText("")

        # Меню столбцов - QMenu с галочками
        self.menu_columns = StickyMenu(self.btn_columns)
        self.menu_columns.setObjectName("columnsMenu")
        self.btn_columns.setMenu(self.menu_columns)
        self.menu_columns.aboutToShow.connect(self._populate_columns_menu)

        # Debug print for settings button
        print(f"[DEBUG] btn_columns created, menu set: {self.menu_columns is not None}, popupMode: {self.btn_columns.popupMode()}")

        fl.addWidget(self.btn_columns)

        split = QSplitter(self)
        split.setHandleWidth(2)
        try:
            self._enhance_splitter_handles(split)
        except Exception:
            pass
        split.setContentsMargins(0,0,0,0)  # без внешних отступов

        self.tree = QTreeWidget(self); self.tree.setHeaderLabels([t("tree.project_files")]); self.tree.header().setStretchLastSection(True)
        try:
            prox = TreeBranchProxyStyle(self.style())
            self.tree.setStyle(prox)
            # Ensure viewport also uses proxy style (Qt paints branches on viewport)
            if hasattr(self.tree, "viewport") and self.tree.viewport():
                self.tree.viewport().setStyle(prox)
        except Exception:
            pass
        self.tree.setMouseTracking(True)
        try:
            self.tree.setUniformRowHeights(True)
        except Exception:
            pass
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setAllColumnsShowFocus(False)
        try:
            self.tree.setFocusPolicy(Qt.NoFocus)
        except Exception:
            pass

        self.tree._hover_index = QModelIndex()
        self.tree._pressed_index = QModelIndex()
        self.tree.viewport().setAttribute(Qt.WA_Hover, True)
        self.tree.viewport().setMouseTracking(True)
        self.tree.viewport().installEventFilter(self)  # оставить один раз
        # Чистим анимации и временные состояния, когда строки удаляются/перестраиваются
        try:
            self.tree.model().rowsRemoved.connect(lambda *_: cleanup_removed(self.tree))
            self.tree.model().modelReset.connect(lambda *_: cleanup_removed(self.tree))
        except Exception:
            pass

        self.tree.setAlternatingRowColors(False)
        self.tree.setObjectName("docsTree")
        self.tree.setStyleSheet("""
            QTreeWidget, QTreeView {
                selection-background-color: transparent;
                show-decoration-selected: 0;
                outline: 0;
            }
            QTreeWidget::branch, QTreeView::branch,
            QTreeWidget::branch:selected, QTreeView::branch:selected,
            QTreeWidget::branch:hover, QTreeView::branch:hover,
            QTreeWidget::branch:selected:hover, QTreeView::branch:selected:hover {
                background: transparent;
                border: none;
            }
            QTreeWidget::item, QTreeView::item {
                border: none;
                outline: none;
            }
            QTreeWidget::item:selected, QTreeView::item:selected {
                background: transparent;
                border: none;
                outline: none;
            }
            QTreeWidget::item:selected:active, QTreeView::item:selected:active,
            QTreeWidget::item:selected:!active, QTreeView::item:selected:!active,
            QTreeWidget::item:focus, QTreeView::item:focus {
                background: transparent;
                border: none;
                outline: none;
            }
        """)

        # Drag & drop: accept drops onto tree folders (move from table).
        # DnD filters
        from .drag_drop import TreeDropFilter, TableDropFilter, DragEventFilter
        
        try:
            self.tree.setAcceptDrops(True)
            self.tree.viewport().setAcceptDrops(True)
            self.tree.setDropIndicatorShown(False)
            self.tree.setDragDropMode(QAbstractItemView.DropOnly)
            self.tree.setDefaultDropAction(Qt.MoveAction)
        except Exception as e:
            print(f"[DND] ERROR importing drag_drop: {e}")
            import traceback
            traceback.print_exc()
            raise  # Re-raise to show error
        
        try:
            self._tree_drop_filter = TreeDropFilter(self)
            self.tree.installEventFilter(self._tree_drop_filter)
            print("[DND] TreeDropFilter installed on tree widget")
        except Exception as e:
            print(f"[DND] ERROR installing TreeDropFilter: {e}")
            import traceback
            traceback.print_exc()
        # Unify tree row hover/selection width and keep selection color on hover
        try:
            # IMPORTANT: keep a strong reference, otherwise the delegate can be
            # GC'ed and Qt may crash later.
            self._tree_row_delegate = MenuLikeTreeDelegate(self.tree)
            self.tree.setItemDelegate(self._tree_row_delegate)
        except Exception:
            pass
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu); self.tree.customContextMenuRequested.connect(self.tree_context_menu)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)  # выделять всю строку
        self.tree.setAllColumnsShowFocus(False)
        try:
            self.tree.setFocusPolicy(Qt.NoFocus)
        except Exception:
            pass

        right = QWidget(self)
        r_l = QVBoxLayout(right)
        r_l.setContentsMargins(0,0,0,0)
        r_l.setSpacing(0)   # чтобы полоса прокрутки была ближе к низу

        self.table = QTableView(self)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.table_context_menu)

        # скролл по X, если не влезает
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        try:
            # чтобы Qt считал ширину по всем строкам, а не по первым 100
            self.table.setResizeContentsPrecision(100000)
        except Exception:
            pass

        hh = self.table.horizontalHeader()
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)  # заголовки — влево
        # хотим ховер всей строки - включаем трекинг мыши и делегат
        self.table.setMouseTracking(True)
        # IMPORTANT: keep a strong reference to the delegate.
        self._table_row_delegate = RowHoverDelegate(
            parent=self.table,
            icon_size=ICON_BOX,
            # Match hover/pressed visuals of buttons (see QSS in utils/theme.py)
            hover_color=QtGui.QColor(247, 146, 30, int(255 * 0.10)),
            # Selected row should be more prominent than hover
            selected_color=QtGui.QColor(247, 146, 30, int(255 * 0.28)),
            pressed_color=QtGui.QColor(247, 146, 30, int(255 * 0.20)),
        )
        self.table.setItemDelegate(self._table_row_delegate)
        
        # Install viewport row highlighter to draw seamless row backgrounds
        install_viewport_row_highlighter(self.table)

        # NOTE: row hover/selection is painted by delegates; avoid per-widget overrides here.
        self.table._hover_row = -1
        self.table._pressed_row = -1
        self.table.viewport().setAttribute(Qt.WA_Hover, True)
        self.table.viewport().setMouseTracking(True)
        self.table.viewport().installEventFilter(self)
        # debounce heavy column recalculation on resize
        try:
            self._resize_timer = QTimer(self)
            self._resize_timer.setSingleShot(True)
            self._resize_timer.setInterval(120)
            self._resize_timer.timeout.connect(self._resize_columns_to_contents_and_fill)
        except Exception:
            pass
        try:
            self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        except Exception:
            pass
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)  # выбор целой строкой
        self.table.setMouseTracking(True)
        self.table.setAlternatingRowColors(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        try:
            self.table.setShowGrid(False)          # убираем клетку
        except Exception:
            pass
        try:
            self.table.setGridStyle(Qt.NoPen)
        except Exception:
            pass
        # Убираем все границы и линии между ячейками
        self.table.setStyleSheet("""
            QTableView {
                border: none;
                gridline-mode: None;
                outline: none;
                selection-background-color: transparent;
            }
            QTableView::item {
                border: none;
                outline: none;
                padding: 2px;
            }
            QTableView::item:selected {
                border: none;
                outline: none;
                background: transparent;
            }
            QTableView::item:focus {
                border: none;
                outline: none;
            }
            QTableView:focus {
                border: none;
                outline: none;
            }
        """)
        try:
            self.table.setTextElideMode(Qt.ElideNone)
        except Exception:
            pass
        try:
            self.table.setWordWrap(False)
        except Exception:
            pass

        vh = self.table.verticalHeader()
        vh.setVisible(False)              # прячем нумерацию строк
        self.table.setCornerButtonEnabled(False)  # убираем «угловую» пимпочку
        # [SortHeader] подменяем системный хедер на кастомный с PNG-стрелками
    
        sort_hdr = SortHeader(Qt.Horizontal, self.table, SORT_ICON_UP_PATH, SORT_ICON_DOWN_PATH)
        
        sort_hdr.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.setHorizontalHeader(sort_hdr)
        hdr = self.table.horizontalHeader()

        # Сортировка отключена по умолчанию - стрелка не показывается до первого клика
        self.table.setSortingEnabled(False)
        hdr.setSortIndicatorShown(False)
        self._sorting_armed = False

        # — при первом нажатии по заголовку включим сортировку и вернём стрелку
        hdr = self.table.horizontalHeader()
        try:
            hdr.sectionClicked.disconnect(self._arm_sorting)
        except Exception:
            pass



        try:
            # колонка по умолчанию - индекс 1 всегда колонка "Название"/"Name"
            name_col = 1
        except Exception:
            name_col = 1

        default_order = Qt.AscendingOrder
        self._last_sort_section = name_col
        self._last_sort_order = default_order

        # Обработчик клика по заголовку: управляет только видимостью стрелки.
        # Реальная сортировка выполняется штатно через QTableView.setSortingEnabled(True).
        def _on_first_header_click(logical_index):
            _hdr = self.table.horizontalHeader()
            if logical_index == 0:
                try:
                    _hdr.setSortIndicatorShown(False)
                except Exception:
                    pass
                return

            try:
                self._sorting_armed = True
                _hdr.setSortIndicatorShown(True)
                self._last_sort_section = _hdr.sortIndicatorSection()
                self._last_sort_order = _hdr.sortIndicatorOrder()
            except Exception:
                pass

        try:
            self._on_first_header_click = _on_first_header_click
            try:
                hdr.sectionClicked.disconnect(self._on_first_header_click)
            except Exception:
                pass
            try:
                hdr.sectionPressed.disconnect(self._on_first_header_click)
            except Exception:
                pass
            # sectionPressed is more reliable here because header click can be
            # partially consumed by overlays (filter icons / header checkbox).
            hdr.sectionPressed.connect(self._on_first_header_click)
        except Exception:
            pass

        # если нужен хук на смену сортировки - оставь
        try:
            hdr.sortIndicatorChanged.connect(self.on_sort_changed, Qt.UniqueConnection)
        except Exception:
            pass

        hdr.setSectionResizeMode(0, QHeaderView.Fixed)  # 0-я колонка фикс
        hdr.resizeSection(0, CHECKBOX_COLUMN_WIDTH)
        # Distribute remaining space evenly among all visible columns
        self.table.horizontalHeader().setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.Fixed)
        
        # Радикальная защита: переопределяем resizeSection чтобы принудительно фиксировать столбец 0
        _original_resize = hdr.resizeSection
        def _locked_resize(section, size):
            if section == 0:
                size = CHECKBOX_COLUMN_WIDTH  # Принудительно фиксированная ширина
                _original_resize(section, size)
                # После изменения размера восстанавливаем режим Fixed
                if hdr.sectionResizeMode(0) != QHeaderView.Fixed:
                    hdr.setSectionResizeMode(0, QHeaderView.Fixed)
            else:
                _original_resize(section, size)
        hdr.resizeSection = _locked_resize
        self._original_hdr_resize = _original_resize  # Сохраняем для использования в других методах
        
        self.table.setSelectionBehavior(QTableView.SelectRows); self.table.setSelectionMode(QTableView.ExtendedSelection)
        self.table.doubleClicked.connect(self.on_table_double_clicked); 
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu); self.table.customContextMenuRequested.connect(self.table_context_menu)
        self.table.viewport().installEventFilter(self)
        self.table.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        # DISABLED: Автоскрытие 0-й колонки при горизонтальной прокрутке - всегда показываем чекбоксы
        # self.table.horizontalScrollBar().valueChanged.connect(self._toggle_first_col_on_scroll)
        self.table.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.horizontalHeader().customContextMenuRequested.connect(self.header_context_menu)
        hdr = self.table.horizontalHeader()
        hdr.setSectionsClickable(True)
        
        # hdr.sectionClicked.connect(self._on_header_clicked_sort, Qt.UniqueConnection)

        self.table.setIconSize(QSize(24, 24))
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.verticalHeader().setMinimumSectionSize(24)

        # --- Чекбокс в заголовке первой колонки (мастер-выбор) ---
        self.hdr = self.table.horizontalHeader()


        # Header filter icon overlay (theme-aware)
        self._update_filter_icon_pm()

        # Лейблы-иконки по колонкам
        self._hdr_filter_labels = {}  # col -> QLabel

        self.hdr.sectionResized.connect(self.header_filter_icons_update)
        self.hdr.sectionMoved.connect(self.header_filter_icons_update)
        self.hdr.geometriesChanged.connect(self.header_filter_icons_update)
        self.table.horizontalScrollBar().valueChanged.connect(lambda _:
            self.header_filter_icons_update())

        try:
            self.hdr.setHighlightSections(False)
        except Exception:
            pass
        
        self.hdrcb = HeaderCheckButton(self.hdr.viewport())
        # Гарантируем, что клики попадают именно в кнопку, даже поверх накладок иконок фильтров
        self.hdrcb.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.hdrcb.setMouseTracking(True)
        self.hdrcb.setStyleSheet("background: transparent; border: 0; margin: 0; padding: 0;")
        # Явно устанавливаем Unchecked при старте
        self.hdrcb._visual_checked = False
        self.hdrcb._partial = False
        try:
            self.hdrcb.raise_()
        except Exception:
            pass

        self.hdrcb.setToolTip(t("table.checkbox_tooltip"))
        self.hdr.viewport().installEventFilter(self)
        
        try:
            self.hdr.sectionResized.connect(self._update_header_checkbox_pos)
            self.hdr.sectionMoved.connect(self._update_header_checkbox_pos)
            self.hdr.geometriesChanged.connect(self._update_header_checkbox_pos)
        except Exception:
            pass
 

        self.hdrcb.clicked.connect(self.on_header_cb_clicked)
        self.hdrcb.toggled.connect(self.on_header_cb_state_changed)
        # stateChanged для совместимости
        self.hdrcb.stateChanged.connect(self.on_header_cb_state_changed)
        self.hdrcb.stateChanged.connect(lambda *_: self._update_actions_enabled())

        self._update_header_checkbox_pos()
        try:
            # Make sure the header checkbox sits above any overlay labels/icons
            self.hdrcb.raise_()
        except Exception:
            pass
        # Delayed positioning to ensure all elements are rendered
        QTimer.singleShot(50, self._update_header_checkbox_pos)



        # Панель действий
        actions = QWidget(self); act_l = QHBoxLayout(actions); act_l.setContentsMargins(0,0,0,0); act_l.setSpacing(8)
        self.btn_download.setProperty("secondary", True);        
        act_l.addStretch(1)
        r_l.addWidget(filt, 0); r_l.addWidget(self.table, 1); r_l.addWidget(actions, 0)
        split.addWidget(self.tree); split.addWidget(right); split.setSizes([320, 960])
        try:
            self._enhance_splitter_handles(split)
        except Exception:
            pass

        root = QWidget(self); root_l = QVBoxLayout(root); root_l.setContentsMargins(10,10,10,0); root_l.setSpacing(8)
        root_l.addWidget(top); root_l.addWidget(split, 1)
        self.setCentralWidget(root)
        try:
            self.header_filter_icons_update()
        except Exception:
            pass

        
        
        self.status = QStatusBar(self); self.setStatusBar(self.status)
        # компактный индикатор из точек (оранжевый фирменный)
        self.progress = BusyDots(self, color="#F7921E", dots=5, r_min=2, r_max=4, spacing=6, interval_ms=80)
        self._set_progress_visible(False)
        self.status.addPermanentWidget(self.progress)
        
        # Флаг отмены для прогресс-бара
        self._progress_cancelled = False

        # Current cancel handler for progress UI (callable or None)
        self._progress_cancel_handler = None
        
        # Кнопка отмены для прогресс-бара
        self._progress_cancel_btn = QPushButton("Отмена", self)
        self._progress_cancel_btn.setObjectName("progressCancelBtn")
        self._progress_cancel_btn.setProperty("secondary", True)
        self._progress_cancel_btn.setVisible(False)
        self.status.addPermanentWidget(self._progress_cancel_btn)
        self._progress_cancel_btn.clicked.connect(self._on_progress_cancel)
        
        # Глобальная кнопка уведомлений (колокольчик) справа в status bar
        self.global_notify_btn = QPushButton(self)
        self.global_notify_btn.setFlat(True)
        self.global_notify_btn.setFixedSize(32, 28)
        self.global_notify_btn.setIconSize(QSize(20, 20))
        self.global_notify_btn.setIcon(QIcon(ALARM1_ICON_PATH))  # Set initial icon
        self.global_notify_btn.setToolTip(t("toolbar.notifications"))
        self.global_notify_btn.setVisible(False)  # Скрыт по умолчанию, показывается при наличии уведомлений
        self.global_notify_btn.clicked.connect(self._show_notifications_menu)
        # УБРАНО: self.status.addPermanentWidget(self.global_notify_btn) - не нужна кнопка в трее снизу
        print(f"[INIT] Global notification button created, icon path: {ALARM1_ICON_PATH}")
        
        # Счётчик непрочитанных уведомлений (для отслеживания)
        self._pending_notifications = {}  # {folder_id: {"project_id": int, "folder_path": str, "changes": list, "current_files": dict}}
        
        # User actions log for filtering "external only" changes
        # Format: [{"timestamp": float, "action": str, "file_id": int, "file_name": str, "folder_id": int}, ...]
        self._user_actions_log = []
        self._user_actions_max_size = 100  # Keep last N actions
        self._user_actions_ttl = 3600  # TTL in seconds (1 hour)
        
        # Load persisted pending notifications from previous session
        try:
            self._pending_notifications = load_pending_notifications()
            print(f"[INIT] Loaded {len(self._pending_notifications)} pending notifications from storage")
            if self._pending_notifications:
                # Update global badge immediately if we have pending notifications
                self._update_global_notification_badge()
                # Also reflect in top-bar notify button and menu
                try:
                    self._update_notify_icon()
                    self._build_notify_menu()
                except Exception:
                    pass
        except Exception as e:
            print(f"[INIT] Failed to load pending notifications: {e}")
        
        # Load persisted user actions log
        try:
            self._user_actions_log = self._load_user_actions_log()
            self._cleanup_expired_user_actions()
            print(f"[INIT] Loaded {len(self._user_actions_log)} user actions from storage")
        except Exception as e:
            print(f"[INIT] Failed to load user actions log: {e}")


        # Данные
        self.full_tree = []; self.current_path_nodes = []; self.files_current = []; self.folder_item_by_id = {}
        # Сигналы
        self.btn_login.clicked.connect(self.do_login)
        self.cb_projects.currentIndexChanged.connect(self.on_project_changed)
        self.btn_refresh.clicked.connect(self.refresh_tree)
        self.btn_go_to_root.clicked.connect(self.go_to_project_root)
        try:
            self.btn_back.clicked.connect(self.go_back)
        except Exception:
            pass
        # charts removed
        pass
        #
        pass
        self.tree.itemClicked.connect(self.on_tree_click)
        self.btn_rename.clicked.connect(self.rename_selected_action)
        try:
            self.btn_compare.clicked.connect(self._on_compare_clicked)
        except Exception:
            pass
        self.btn_move.clicked.connect(self.move_selected_action)
        # Copy operation sometimes triggers hard-to-debug Qt crashes when an exception
        # escapes a slot; route through a safe wrapper if available.
        try:
            self.btn_copy.clicked.connect(self._safe_copy_selected_action)
        except Exception:
            self.btn_copy.clicked.connect(self.copy_selected_action)
        self.btn_delete.setToolTip(t("toolbar.delete_checked"))
        # Подключение без UniqueConnection, чтобы избежать предупреждений Qt
        self.btn_delete.clicked.connect(self.delete_checked)
        try:
            if self.btn_download.popupMode() != QToolButton.InstantPopup:
                self.btn_download.clicked.connect(self.download_checked)
        except Exception:
            # В режиме InstantPopup не вешаем click->download_checked, чтобы избежать дублирования
            pass        
        self.search.textChanged.connect(self.apply_table_filters)
        self.btn_no_folders.setChecked(self.cb_flat.isChecked())
        self.btn_no_folders.toggled.connect(_no_folders_toggled)

        self._apply_icon_theme(self._current_theme)
        # Install hover retinting so icons turn black on hover in dark theme
        self._install_hover_black_icons()
        # Модель
        self.checked = set()
        self.files_model = FilesTableModel(self.files_current, self.icon_provider, self.checked)
        self.proxy = QSortFilterProxyModel(self); self.proxy.setSourceModel(self.files_model); self.proxy.setSortRole(FilesTableModel.SORT_ROLE)
        self.table.setModel(self.proxy)

        try:
            self._table_no_native_style = ItemViewNoNativeHighlightStyle(self.table.style())
            self.table.setStyle(self._table_no_native_style)
        except Exception:
            pass
        try:
            self._table_viewport_no_native_style = ItemViewNoNativeHighlightStyle(self.table.viewport().style())
            self.table.viewport().setStyle(self._table_viewport_no_native_style)
        except Exception:
            pass
        
        self.table.setObjectName("filesTable")
        self.table.setProperty("dropHoverEmpty", False)
        self.table.viewport().setAcceptDrops(True)  # ВКЛЮЧАЕМ DRAG DROP
        self.table.viewport().setAttribute(Qt.WA_StyledBackground, True)
        self.table.viewport().setAutoFillBackground(True)
        # DnD только для центральной таблицы (правая область)
        self.table.setObjectName("filesTable")
        self.table.setProperty("dropHover", False)
        # Allow both: drop from OS (upload) and drag to tree (move)
        try:
            self.table.setDragEnabled(True)
            self.table.setAcceptDrops(True)
            self.table.setDropIndicatorShown(False)
            self.table.setDragDropMode(QAbstractItemView.DragDrop)
        except Exception:
            self.table.setDragDropMode(QAbstractItemView.DropOnly)
        self.table.setDefaultDropAction(Qt.CopyAction)
        # Keep native sorting enabled (reliable sorting behavior),
        # but hide sort arrow until first header click.
        self.table.setSortingEnabled(True)
        self.hdr.setSortIndicator(self._last_sort_section, self._last_sort_order)
        self.hdr.setSortIndicatorShown(False)
        try:
            self.hdr.setSortIndicator(-1, Qt.AscendingOrder)
        except Exception:
            pass
        self._sorting_armed = False
        # Table DnD filters - installed AFTER table is created and configured
        self._table_drop_filter = TableDropFilter(self)
        self.table.viewport().installEventFilter(self._table_drop_filter)

        # DragEventFilter - enables drag from table with custom preview
        self._drag_filter = DragEventFilter(self.table, self)
        self.table.viewport().installEventFilter(self._drag_filter)
        print("[DND] DragEventFilter installed on table viewport")
        
        self._tune_columns()
        self._bind_table_selection_signals()
        self._update_actions_enabled()
        # Ensure checkbox background uses the same hover/selected colors and the inner delegate draws the checkbox.
        # IMPORTANT: keep strong references to delegates to avoid Qt crashes.
        try:
            self._table_checkbox_delegate = CheckBoxDelegate(self.table)
            self._table_checkbox_bg_delegate = CheckBoxDelegateBg(self.table, self._table_checkbox_delegate)
            self.table.setItemDelegateForColumn(0, self._table_checkbox_bg_delegate)
        except Exception:
            pass
        # Клик на чекбокс обрабатывается в CheckBoxDelegate.editorEvent
        # Обновляем состояние заголовочного чекбокса при любых изменениях данных
        try:
            # Сигналы прокси
            def _hdr_sched():
                try:
                    fn = getattr(self, "schedule_update_header_checkbox", None)
                    if callable(fn):
                        fn()
                    else:
                        self.update_header_checkbox()
                except Exception:
                    pass
            self.proxy.dataChanged.connect(lambda *_: _hdr_sched())
            self.proxy.rowsInserted.connect(lambda *_: _hdr_sched())
            self.proxy.rowsRemoved.connect(lambda *_: _hdr_sched())
            self.proxy.modelReset.connect(lambda *_: _hdr_sched())
            # И одновременно пересчитываем доступность кнопок
            self.files_model.dataChanged.connect(lambda *_: self._update_actions_enabled())
        except Exception:
            pass
        self.update_header_checkbox()
        self.table.horizontalHeader().sortIndicatorChanged.connect(self.on_sort_changed)

        self.set_initial_view()

        try:
            from ..utils.i18n import get_language_manager
            lang_mgr = get_language_manager()
            lang_mgr.languageChanged.connect(self._retranslate_ui)
        except Exception:
            pass

        env_user, env_pass = os.environ.get("LARIX_USER"), os.environ.get("LARIX_PASS")
        if env_user and env_pass and self.api.login(env_user, env_pass, remember_me=True):
            self.on_logged_in()
        else:
            # Не авторизованы на старте; пользователь сам жмёт 'Войти'
            self.status.showMessage(t("auth.not_authorized"))

    def _get_language_code(self):
        from ..utils.i18n import is_russian
        return "RU" if is_russian() else "EN"
             
    def update_user_display(self):
        if self.api.current_username:
            # Предполагаем, что имя отображается в QToolButton #userButton (из стилей в коде)
            # Если у вас другое имя элемента (например, self.user_label или self.btnUser), замените
            try:
                self.userButton.setText(self.api.current_username)  # ли self.user_label.setText(...)
            except AttributeError:
                # Если кнопка не найдена, добавьте отладку или пропустите
                print("Не удалось обновить имя пользователя: элемент UI не найден")
        else:
            try:
                self.userButton.setText(t("common.guest"))  # ли пустая строка/иконка
            except AttributeError:
                pass
    def _choose_directory(self, title: str) -> str:
        """Choose a directory.

        Default: native OS dialog.
        Escape hatch: set env `LARIX_FORCE_QT_DIALOG=1` to use Qt (non-native)
        dialog if native one crashes on a specific machine.
        """
        # We want the standard Windows folder picker, but Qt's native dialog can
        # hard-crash on some setups. Use Windows IFileDialog (FOS_PICKFOLDERS)
        # which looks like the standard dialog.
        try:
            start_dir = os.getcwd()
        except Exception:
            try:
                start_dir = program_dir()
            except Exception:
                start_dir = ""

        try:
            sync_log("SYNC_MENU: opening dir dialog title={!r} start_dir={!r}", title, start_dir)
        except Exception:
            pass

        if sys.platform == "win32" and not os.environ.get("LARIX_FORCE_QT_DIALOG"):
            try:
                picked = self._win_ifiledialog_pick_folder(title=title, start_dir=start_dir)
                if picked:
                    return picked
            except Exception as e:
                import traceback
                try:
                    sync_log("SYNC_MENU: Windows IFileDialog crashed: {}", str(e))
                    sync_log("SYNC_MENU: TRACEBACK:\n{}", traceback.format_exc())
                except Exception:
                    pass
                try:
                    print(f"[DIR_DIALOG] Windows IFileDialog crashed: {e}")
                except Exception:
                    pass

        # Fallback (non-Windows): Qt native directory dialog.
        try:
            return QFileDialog.getExistingDirectory(self, title, start_dir) or ""
        except Exception:
            return ""

    def _sync_add_mapping(self, folder_id, folder_title: str, project_id):
        """Run add-sync flow after the context menu is closed."""
        try:
            try:
                sync_log("SYNC_MENU: _sync_add_mapping start folder_id={} project_id={}", folder_id, project_id)
            except Exception:
                pass
            if not self.api.is_available():
                try:
                    self.status.showMessage(t("sync.server_unavailable_status"), 5000)
                except Exception:
                    pass
                return

            path = self._choose_directory("Выберите локальную папку для синхронизации")
            if not path:
                return

            # Create a subfolder named after the cloud folder inside selected path
            try:
                safe_name = _sanitize_filename(folder_title or "") or f"folder_{folder_id}"
                target_dir = os.path.join(path, safe_name)
                os.makedirs(target_dir, exist_ok=True)
                path = target_dir
            except Exception:
                pass

            # Diagnostics
            sync_log("SYNC_MENU: folder_id={} path='{}' project_id={}", folder_id, path, project_id)

            if not hasattr(self, 'sync2') or self.sync2 is None:
                QMessageBox.critical(self, t("common.error"), t("sync.manager_not_initialized"))
                return

            try:
                sync_log("SYNC_MENU: Вызов self.sync2.add_sync...")
                self.sync2.add_sync(folder_id, path, project_id)
                sync_log("SYNC_MENU: add_sync успешно выполнен")
            except Exception as e:
                import traceback
                full_traceback = traceback.format_exc()
                sync_log("SYNC_MENU: ERROR в add_sync - {}", str(e))
                sync_log("SYNC_MENU: TRACEBACK:\n{}", full_traceback)
                QMessageBox.critical(self, t("common.error"), t("sync.add_folder_error", error=e, traceback=full_traceback))
                return

            # Update badge (re-find item by id, not captured pointer)
            try:
                it = getattr(self, 'folder_item_by_id', {}).get(normalize_id(folder_id))
                if it is not None:
                    it.setData(0, SYNC_ROLE, True)
                    self.tree.viewport().update()
            except Exception:
                pass

            try:
                sync_log("SYNC_MENU: Запуск _start_initial_sync...")
                self._start_initial_sync(folder_id, path, project_id)
                sync_log("SYNC_MENU: _start_initial_sync запущен успешно")
            except Exception as e:
                import traceback
                sync_log("SYNC_MENU: CRITICAL ERROR в _start_initial_sync - {}", str(e))
                sync_log("TRACEBACK:\n{}", traceback.format_exc())
                try:
                    self._set_progress_visible(False)
                except Exception:
                    pass
                QMessageBox.critical(
                    self,
                    t("sync.error"),
                    t("sync.start_failed", error=e),
                )
                return

            QMessageBox.information(
                self,
                t("sync.title"),
                t("sync.enabled", path=path),
            )
        except Exception:
            # Don't let an unexpected error crash the UI event loop
            try:
                sync_exc("SYNC_MENU: unhandled exception in _sync_add_mapping")
            except Exception:
                pass

    # Unified tree context menu (with sync actions)
    def _ctx_menu_sync(self, pos):
        item = self.tree.itemAt(pos)
        if not item:
            return
        node = item.data(0, Qt.UserRole)
        try:
            typ = str((node or {}).get("type") or "").lower()
        except Exception:
            typ = ""
        if typ != "folder":
            return

        menu = QMenu(self)
        menu.setObjectName("treeMenu")
        act_zip = menu.addAction(t("context.download_as_zip"))
        act_folder = menu.addAction(t("context.download_structure"))
        menu.addSeparator()
        
        act_copy_folder = menu.addAction(t("context.copy_folder"))
        act_move_folder = menu.addAction(t("context.move_folder"))
        menu.addSeparator()

        folder_id = (node or {}).get("id")
        fid_key = normalize_id(folder_id)
        is_synced = bool(getattr(self, 'sync2', None) and self.sync2.is_synced(folder_id))
        
        act_path_open = None
        act_eta = None
        act_unsync = None
        act_sync = None
        act_sync_now = None
        
        if is_synced:
            try:
                pth = self.sync2.get_sync_path(folder_id)
                act_path_open = menu.addAction(t("context.sync_path"))
                act_path_open.setToolTip(pth)
            except Exception:
                pth = ""
            try:
                eta_ms = -1
                cfg = self.sync2.map.get(fid_key) if hasattr(self, 'sync2') else None
                if cfg and bool(cfg.get('initial_ok')) and self.sync2.timer.isActive():
                    eta_ms = int(self.sync2.timer.remainingTime())
                def _fmt_eta(ms: int) -> str:
                    try:
                        if ms is None or ms < 0:
                            return "—"
                        s = int(ms // 1000)
                        m, s = divmod(max(0, s), 60)
                        if m > 0:
                            return t("time.min_sec", m=m, s=s)
                        return t("time.sec", n=s)
                    except Exception:
                        return "—"
                eta_text = _fmt_eta(eta_ms)
                act_eta = menu.addAction(t("context.sync_next", eta=eta_text))
                act_eta.setEnabled(False)
            except Exception:
                pass
            act_unsync = menu.addAction(t("context.sync_disable"))
        else:
            act_sync = menu.addAction(t("context.sync"))
            try:
                act_sync.setEnabled(bool(self.api.is_available()))
            except Exception:
                pass

        if is_synced:
            try:
                act_sync_now = menu.addAction(t("context.sync_now"))
            except Exception:
                act_sync_now = None

        # Notifications subscription item in context menu
        try:
            menu.addSeparator()
            subscribed = False
            has_changes = False
            title = item.text(0)
            folder_id_int = fid_key
            
            try:
                subscribed = folder_id_int in getattr(self, '_subscriptions', {})
            except Exception:
                subscribed = False

            # Check if there are pending changes for this folder
            try:
                has_changes = folder_id_int in self._pending_notifications
            except Exception:
                has_changes = False
            
            act_view_notif = None
            act_sub = None

            # Пункт "Уведомления" - показывается только если есть изменения
            if subscribed and has_changes:
                act_view_notif = menu.addAction(t("context.notifications"))

            try:
                if subscribed:
                    act_sub = menu.addAction(t("context.unsubscribe_notifications"))
                else:
                    act_sub = menu.addAction(t("context.subscribe_notifications"))
            except Exception:
                act_sub = None

        except Exception:
            act_view_notif = None
            act_sub = None

        chosen = self._menu_exec(menu, self.tree.mapToGlobal(pos))
        try:
            sync_log("SYNC_MENU: chosen action {}", (getattr(chosen, "text", lambda: None)() if chosen else None))
        except Exception:
            pass
        if chosen == act_zip:
            self.download_folder_as_zip(node)
            return
        if chosen == act_folder:
            self.download_folder_plain(node)
            return
        if is_synced and chosen == locals().get('act_sync_now'):
            try:
                self._trigger_sync_now(folder_id)
            except Exception:
                pass
            return
        if is_synced and chosen == locals().get('act_path_open'):
            if pth:
                try:
                    open_in_os(pth)
                except Exception:
                    pass
            return

        if is_synced and chosen == locals().get('act_unsync'):
            try:
                self.sync2.remove_sync(folder_id)
                item.setData(0, SYNC_ROLE, False)
                self.tree.viewport().update()
                try:
                    cleanup_removed(self.tree)
                except Exception:
                    pass

                QMessageBox.information(self, t("sync.title"), t("sync.disabled"))
            except Exception:
                pass
            return
        if (not is_synced) and chosen == locals().get('act_sync'):
            # Defer opening the native file dialog until after the context menu closes.
            try:
                proj = self.current_project_id()
            except Exception:
                proj = None
            if not proj:
                QMessageBox.warning(self, t("sync.title"), t("sync.no_project"))
                return
            try:
                folder_title = item.text(0)
            except Exception:
                try:
                    folder_title = (node or {}).get("name") or ""
                except Exception:
                    folder_title = ""
            
            def add_mapping():
                try:
                    self._sync_add_mapping(folder_id, folder_title, proj)
                except Exception:
                    pass
            
            QtCore.QTimer.singleShot(0, add_mapping)
            return

 

        # Обработка копирования и перемещения папки
        if chosen == locals().get('act_copy_folder'):
            try:
                self.copy_folder_action()
            except Exception:
                pass
            return

        if chosen == locals().get('act_move_folder'):
            try:
                self.move_folder_action()
            except Exception:
                pass
            return

 

        # Handle "View Notifications" action
        if chosen == locals().get('act_view_notif'):
            if node:
                try:
                    folder_id_check = normalize_id((node or {}).get("id"))
                    if folder_id_check:
                        self._show_changes_dialog(folder_id_check)
                except Exception as e:
                    QMessageBox.warning(self, t("common.error"), t("sync.notifications_error", error=e))
            return

        # Notifications subscribe/unsubscribe handling
        if (chosen == locals().get('act_sub')) or (chosen and chosen.text() in (t("context.subscribe_notifications"), t("context.unsubscribe_notifications"))):
            # Используем централизованную функцию для обработки подписки
            if node:
                self.toggle_folder_notifications(node)
            return

    def _refresh_synced_folder(self, folder_id: str) -> None:
        """Refresh UI after a sync.

        Historically this method tried to update the table from cached tree
        node data (`children`). That does not reliably reflect file changes
        (uploads/downloads) because the table is backed by `api.list_files()`.

        We now:
        - refresh the currently opened folder view (if it is the synced folder
          or a descendant in the tree) by calling `open_folder_node()` which
          re-fetches files from API;
        - keep the lightweight folder-node enrichment for the synced folder.
        """
        try:
            synced_folder_id = normalize_id(folder_id)
            if not synced_folder_id:
                return

            # Current selection (folder being viewed)
            current_item = None
            try:
                current_item = self.tree.currentItem()
            except Exception:
                current_item = None

            current_fid = ""
            try:
                if current_item is not None:
                    current_fid = normalize_id(current_item.data(0, Qt.UserRole + 1) or "")
            except Exception:
                current_fid = ""

            # Get folder item from tree
            folder_item = self.folder_item_by_id.get(synced_folder_id)
            if not folder_item:
                # Folder not in tree, do full refresh
                self.soft_refresh_and_restore_view()
                return

            # Get folder node data
            folder_node = folder_item.data(0, Qt.UserRole) or {}
            if not folder_node:
                return

            # Re-enrich the folder node data from API
            try:
                details = self.api.get_folder_details(synced_folder_id, force=True)
                if details:
                    # Update node data
                    folder_node.update(details)
                    # Update item in tree
                    folder_item.setData(0, Qt.UserRole, folder_node)
            except Exception:
                pass

            # If current view is the synced folder OR a descendant, refresh the
            # currently opened folder via API so new files appear immediately.
            try:
                is_descendant_or_self = False
                it = current_item
                while it is not None:
                    try:
                        fid = normalize_id(it.data(0, Qt.UserRole + 1) or "")
                    except Exception:
                        fid = ""
                    if fid and fid == synced_folder_id:
                        is_descendant_or_self = True
                        break
                    try:
                        it = it.parent()
                    except Exception:
                        it = None

                if is_descendant_or_self and current_fid:
                    try:
                        name = ""
                        try:
                            name = current_item.text(0) if current_item is not None else ""
                        except Exception:
                            name = ""
                        node = {
                            "type": "folder",
                            "id": current_fid,
                            "name": name,
                            "projectId": self.current_project_id(),
                        }
                        self.open_folder_node(node, save_to_history=False)
                    except Exception:
                        # If something goes wrong, fall back to safe full refresh.
                        self.soft_refresh_and_restore_view()
            except Exception:
                pass

            # Update viewport
            self.tree.viewport().update()
        except Exception as e:
            try:
                sync_log("_refresh_synced_folder: ERROR - {}", str(e))
            except Exception:
                pass

    def _trigger_sync_now(self, folder_id: int | str) -> None:
        sync_log("_TRIGGER_SYNC_NOW: Starting for folder_id={}", folder_id)
        try:
            path = self.sync2.get_sync_path(folder_id) if hasattr(self, 'sync2') else ""
        except Exception as e:
            path = ""
            sync_log("_TRIGGER_SYNC_NOW: Error getting sync_path: {}", str(e))
        sync_log("_TRIGGER_SYNC_NOW: path='{}'", path)
        self._sync_now_path = path
        
        if _ImmediateSyncRunner is None:
            sync_log("_TRIGGER_SYNC_NOW: ERROR - _ImmediateSyncRunner is None!")
            QMessageBox.critical(self, t("common.error"), t("sync.module_unavailable"))
            return
            
        sync_log("_TRIGGER_SYNC_NOW: Creating thread and worker...")
        th = QtCore.QThread(self)
        worker = _ImmediateSyncRunner(self.sync2, folder_id)
        worker.moveToThread(th)
        # keep references so threads aren't GC'd; allow multiple parallel sync-now
        try:
            self._sync_now_threads.add(th)
        except Exception:
            self._sync_now_threads = {th}
        self._sync_now_thread = th
        self._sync_now_worker = worker
        
        sync_log("_TRIGGER_SYNC_NOW: Connecting signals...")
        th.started.connect(worker.run)
        worker.sig_started.connect(self._on_sync_now_started, QtCore.Qt.QueuedConnection)
        worker.sig_finished.connect(self._on_sync_now_finished, QtCore.Qt.QueuedConnection)
        # Per-thread cleanup when worker finishes
        try:
            worker.sig_finished.connect(lambda _ok, _th=th, _w=worker: self._cleanup_worker_thread(_th, _w), QtCore.Qt.QueuedConnection)
        except Exception:
            pass
        
        sync_log("_TRIGGER_SYNC_NOW: Starting thread...")
        th.start()
        sync_log("_TRIGGER_SYNC_NOW: Thread started successfully")

    def _cleanup_worker_thread(self, th: QtCore.QThread, worker: QtCore.QObject | None) -> None:
        try:
            if isinstance(worker, QtCore.QObject):
                try:
                    worker.deleteLater()
                except Exception:
                    pass
            if isinstance(th, QtCore.QThread):
                try:
                    if QtCore.QThread.currentThread() is not th:
                        th.quit(); th.wait(1500)
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
        # Drop from tracking set
        try:
            if hasattr(self, "_sync_now_threads") and isinstance(self._sync_now_threads, set):
                self._sync_now_threads.discard(th)
        except Exception:
            pass

    def closeEvent(self, event):
        """Ensure all worker threads are cleanly stopped before window closes."""
        try:
            # Shutdown FolderSyncManager
            if hasattr(self, 'sync2') and self.sync2 is not None:
                self.sync2.shutdown()
        except Exception:
            pass
        try:
            # Stop any ongoing initial sync thread
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
            # Stop all ad-hoc sync-now threads
            for th in list(getattr(self, "_sync_now_threads", set())):
                try:
                    if isinstance(th, QThread):
                        try:
                            if QtCore.QThread.currentThread() is not th:
                                th.quit(); th.wait(1500)
                            else:
                                th.quit()
                        except Exception:
                            pass
                finally:
                    try:
                        self._sync_now_threads.discard(th)
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            super().closeEvent(event)
        except Exception:
            pass
        try:
            QtCore.QCoreApplication.quit()
        except Exception:
            pass

    def _start_initial_sync(self, folder_id, path: str, proj: int | str) -> None:
        """Start initial sync in background thread with full diagnostics."""
        sync_log("=" * 60)
        sync_log("_START_INITIAL_SYNC вызвана!")
        fid_key = normalize_id(folder_id)
        sync_log("folder_id={}, path='{}', project_id={}", fid_key, path, proj)
        sync_log("=" * 60)
        
        # Build worker + thread and connect signals to QObject methods (queued to GUI thread)
        # Create Cancel button in GUI thread
        try:
            sync_log("Создание QThread...")
            th = QtCore.QThread(self)
            sync_log("✓ QThread создан")
        except Exception as e:
            sync_log("ОШИБКА создания QThread: {}", str(e))
            raise
        
        try:
            sync_log("Создание _InitialSyncWorker...")
            sync_log("  api={}", type(self.api).__name__)
            sync_log("  folder_id={}", fid_key)
            sync_log("  path='{}'", path)
            sync_log("  project_id={}", proj)
            sync_log("  owner={}", type(self.sync2).__name__ if hasattr(self, 'sync2') else 'НЕТ!')
            
            if not hasattr(self, 'sync2'):
                raise AttributeError("self.sync2 не инициализирован!")
             
            if _InitialSyncWorker is None:
                raise ImportError("_InitialSyncWorker недоступен - проверьте импорт из larix_nexus.sync.manager")
             
            worker = _InitialSyncWorker(self.api, fid_key, path, proj, self.sync2)
            sync_log("✓ _InitialSyncWorker создан")
        except Exception as e:
            sync_log("ОШИБКА создания _InitialSyncWorker: {}", str(e))
            raise
        
        try:
            sync_log("Перемещение воркера в поток...")
            worker.moveToThread(th)
            sync_log("✓ Воркер перемещён в поток")
        except Exception as e:
            sync_log("ОШИБКА moveToThread: {}", str(e))
            raise

        # store for cleanup/cancel
        self._sync_thread = th
        self._sync_worker = worker
        self._sync_path = path

        try:
            self._set_progress_visible(True)
            self.progress.setRange(0, 0)
            self.status.showMessage(t("sync.counting_files", path=path))
            sync_log("✓ UI обновлён (прогресс-бар показан)")
        except Exception as e:
            sync_log("WARNING: не удалось обновить UI: {}", str(e))

        # Use MainWindow's single status-bar cancel chip.
        try:
            if hasattr(self, "_set_progress_cancel_handler"):
                self._set_progress_cancel_handler(self._on_sync_cancel)
            sync_log("✓ Отмена синхронизации подключена")
        except Exception as e:
            sync_log("WARNING: не удалось подключить отмену синхронизации: {}", str(e))

        # Use queued connections to ensure all UI is updated on main thread
        try:
            sync_log("Подключение сигналов...")
            th.started.connect(worker.run)
            worker.sig_started.connect(self._on_sync_started, QtCore.Qt.QueuedConnection)
            worker.sig_total.connect(self._on_sync_total, QtCore.Qt.QueuedConnection)
            worker.sig_progress.connect(self._on_sync_progress, QtCore.Qt.QueuedConnection)
            worker.sig_error.connect(self._on_sync_error, QtCore.Qt.QueuedConnection)
            worker.sig_finished.connect(self._on_sync_finished, QtCore.Qt.QueuedConnection)
            sync_log("✓ Все сигналы подключены")
        except Exception as e:
            sync_log("ОШИБКА подключения сигналов: {}", str(e))
            raise
        
        try:
            sync_log("Запуск потока...")
            th.start()
            sync_log("✓✓✓ ПОТОК ЗАПУЩЕН! Воркер должен начать работу...")
        except Exception as e:
            sync_log("КРИТИЧЕСКАЯ ОШИБКА запуска потока: {}", str(e))
            raise

    def _collect_files_and_dirs_for_zip(self, node: dict):
        """Собирает список (файл, относительный путь) и набор относительных путей папок для ZIP."""
        files_to_pack = []
        dir_paths = set()

        def collect(n, rel=""):
            for c in (n.get("children") or []):
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "file":
                    fname = c.get("originalName") or c.get("name") or f"file_{c.get('id')}.bin"
                    files_to_pack.append((c, os.path.join(rel, fname)))
                elif c.get("type") == "folder":
                    sub_rel = os.path.join(rel, get_title(c))
                    # сохраняем путь папки, чтобы добавить её в ZIP даже если она пустая
                    dir_paths.add(sub_rel.replace("\\", "/"))
                    collect(c, sub_rel)

        collect(node)
        return files_to_pack, dir_paths

    
    def _zip_folder_to_path(self, node: dict, save_path: str):
        if not node or node.get("type") != "folder":
            return

        files_to_pack, dir_paths = self._collect_files_and_dirs_for_zip(node)

        # Пишем ZIP напрямую, без промежуточного сохранения файлов на диск
        try:
            self._set_progress_visible(True)
            self.progress.setRange(0, 0)
            QApplication.processEvents()
        except Exception:
            pass
        wait = None
        try:
            wait = WaitDialog(t("common.archiving_folder"), self)
            try:
                wait.show(); QApplication.processEvents()
            except Exception:
                wait = None
        except Exception:
            wait = None

        try:
            with zipfile.ZipFile(save_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                # Пустые директории явно
                for d in sorted(dir_paths):
                    arc = d.rstrip("/").replace("\\", "/") + "/"
                    try:
                        zf.writestr(zipfile.ZipInfo(arc), b"")
                    except Exception:
                        pass

                # Файлы — потоково из API
                for fobj, rel in files_to_pack:
                    try:
                        with zf.open(rel.replace("\\", "/"), 'w') as zentry:
                            self.api.write_file_to(fobj.get('id'), zentry)
                    except Exception:
                        pass
        finally:
            try:
                self._set_progress_visible(False)
            except Exception:
                pass
            try:
                if wait:
                    wait.set_done(t("common.done"))
            except Exception:
                pass

    def _populate_columns_menu(self):
        try:
            self.menu_columns.clear()
            
            settings = load_settings()
            current_notification_interval = settings.get("sync", {}).get("notification_refresh_interval", 300)
            current_sync_interval = settings.get("sync", {}).get("auto_sync_interval", 300)
            
            notification_intervals = [
                (300, t("interval.5_minutes")),
                (600, t("interval.10_minutes")),
                (900, t("interval.15_minutes")),
                (1800, t("interval.30_minutes")),
                (2700, t("interval.45_minutes")),
                (3600, t("interval.60_minutes")),
                (86400, t("interval.once_per_day"))
            ]
            
            sync_intervals = notification_intervals.copy()
            
            act_notification = self.menu_columns.addAction(t("settings.notifications_frequency"))
            menu_notification = QMenu(self)
            for interval, label in notification_intervals:
                act = menu_notification.addAction(label)
                act.setData(interval)
                if interval == current_notification_interval:
                    act.setCheckable(True)
                    act.setChecked(True)
                    act.blockSignals(True)
                    act.blockSignals(False)
                act.triggered.connect(lambda checked, i=interval: self._set_notification_interval(i))
            act_notification.setMenu(menu_notification)
            
            act_sync = self.menu_columns.addAction(t("settings.sync_frequency"))
            menu_sync = QMenu(self)
            for interval, label in sync_intervals:
                act = menu_sync.addAction(label)
                act.setData(interval)
                if interval == current_sync_interval:
                    act.setCheckable(True)
                    act.setChecked(True)
                    act.blockSignals(True)
                    act.blockSignals(False)
                act.triggered.connect(lambda checked, i=interval: self._set_sync_interval(i))
            act_sync.setMenu(menu_sync)
            
            self.menu_columns.addSeparator()
            
            act_columns = self.menu_columns.addAction(t("settings.columns"))
            menu_columns_submenu = QMenu(self)
            model = self.table.model()
            if model:
                cols = model.columnCount()
                for col in range(1, cols):
                    title = str(model.headerData(col, Qt.Horizontal) or f"Столбец {col}")
                    checkbox = QCheckBox(title)
                    checkbox.setChecked(not self.table.isColumnHidden(col))

                    wrapper = QWidget()
                    layout = QHBoxLayout(wrapper)
                    layout.setContentsMargins(2, 1, 2, 1)
                    layout.addWidget(checkbox)
                    layout.addStretch()
                    
                    def on_toggled(checked, col=col):
                        self.table.setColumnHidden(col, not checked)
                    
                    checkbox.toggled.connect(on_toggled)
                    
                    action = QWidgetAction(menu_columns_submenu)
                    action.setDefaultWidget(wrapper)
                    menu_columns_submenu.addAction(action)
            act_columns.setMenu(menu_columns_submenu)
        except Exception:
            pass

    def _set_notification_interval(self, interval_seconds: int):
        try:
            settings = load_settings()
            if "sync" not in settings:
                settings["sync"] = {}
            settings["sync"]["notification_refresh_interval"] = interval_seconds
            save_settings(settings)
            
            if hasattr(self, '_notifications_timer') and self._notifications_timer:
                self._notifications_timer.setInterval(interval_seconds * 1000)
                self._notifications_timer.start()
        except Exception:
            pass

    def _set_sync_interval(self, interval_seconds: int):
        try:
            settings = load_settings()
            if "sync" not in settings:
                settings["sync"] = {}
            settings["sync"]["auto_sync_interval"] = interval_seconds
            save_settings(settings)
            
            if hasattr(self, 'sync2') and self.sync2 and hasattr(self.sync2, 'set_sync_interval'):
                self.sync2.set_sync_interval(interval_seconds)
        except Exception:
            pass


    def _header_filter_icon_label(self, col: int):
        """Создаёт/возвращает QLabel-иконку фильтра для колонки col.
        - Родитель: viewport заголовка, чтобы координаты совпадали со скроллом.
        - Прозрачный фон, не перехватывает клики.
        """
        # если уже есть - возвращаем и гарантируем нужные флаги
        lbl = self._hdr_filter_labels.get(col)
        if lbl is not None:
            try:
                lbl.setAutoFillBackground(False)
                lbl.setAttribute(Qt.WA_TranslucentBackground, True)
                lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                lbl.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")
            except Exception:
                pass
            # Always refresh pixmap to reflect current theme (e.g., dark -> white icon)
            try:
                if self._filter_icon_pm:
                    lbl.setPixmap(self._filter_icon_pm)
            except Exception:
                pass
            return lbl

        # создаём новый ярлык-иконку на viewport хедера
        try:
            parent = self.hdr.viewport()   # важно: именно viewport, а не self.hdr
            lbl = QLabel(parent)
            lbl.setVisible(False)
            if self._filter_icon_pm:
                lbl.setPixmap(self._filter_icon_pm)
            # прозрачный фон, не блокирует клики по заголовку
            try:
                lbl.setAutoFillBackground(False)
                lbl.setAttribute(Qt.WA_TranslucentBackground, True)
                lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            except Exception:
                pass
            lbl.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")

            # фикс-ап размеров под нашу геометрию в _header_filter_icons_repos
            try:
                lbl.setFixedSize(self.FILTER_W, self.FILTER_W)
            except Exception:
                pass

            self._hdr_filter_labels[col] = lbl
            return lbl
        except Exception:
            return None


        
    RIGHT_PAD = 22   # как в QSS
    FILTER_W   = 14
    FILTER_GAP = 4
    def _header_filter_icons_repos(self, *args):
        """Расставляет иконки фильтра справа в секции заголовка с учётом стрелки сортировки."""
        try:
            size = self.FILTER_W
            y = (self.hdr.height() - size) // 2

            model = self.table.model()
            cols = model.columnCount() if model else 0

            # ширина стрелки сортировки из SortHeader (или запасная)
            try:
                arrow_w = max(self.hdr._pm_up.width(), self.hdr._pm_dn.width())
            except Exception:
                arrow_w = getattr(self.hdr, "_icon_px", 12)

            arrow_gap_right = 12                  # зазор справа от стрелки (как в QSS)
            right_pad = getattr(self, "RIGHT_PAD", 40)  # общий правый отступ секции
            gap = getattr(self, "FILTER_GAP", 2)        # зазор между стрелкой и фильтром

            # какая колонка сейчас отсортирована
            try:
                sorted_col = self.hdr.sortIndicatorSection() if self.hdr.isSortIndicatorShown() else -1
            except Exception:
                sorted_col = -1

            for col in range(cols):
                lbl = self._hdr_filter_labels.get(col)
                if not lbl or not lbl.isVisible():
                    continue

                # координаты секции в viewport хедера
                sec_vx = self.hdr.sectionViewportPosition(col)
                sec_w  = self.hdr.sectionSize(col)
                right  = sec_vx + sec_w

                if col == sorted_col:
                    # ставим иконку левее стрелки сортировки
                    x = right - (arrow_w + arrow_gap_right + gap + size)
                else:
                    # обычное положение с общим правым паддингом
                    x = right - (right_pad + size)

                x = max(x, sec_vx + 4)  # не заезжать на текст при узкой колонке
                lbl.setGeometry(x, y, size, size)
                try:
                    lbl.raise_()
                except Exception:
                    pass
        except Exception:
            pass


    def _handle_os_drop(self, paths: list[Path], target_folder: dict):
        pid = self.current_project_id()
        if not pid:
            try:
                if hasattr(self, 'status') and hasattr(self.status, 'showMessage'):
                    self.status.showMessage(t("auth.not_logged_in"), 5000)
            except Exception:
                pass
            return
        raw_fid = target_folder.get("id") or 0
        try:
            target_id = int(raw_fid)
        except (ValueError, TypeError):
            target_id = raw_fid
        # Check for invalid ID (both numeric and string)
        if (isinstance(target_id, (int, float)) and target_id <= 0) or (isinstance(target_id, str) and not target_id.strip()):
            try:
                if hasattr(self, 'status') and hasattr(self.status, 'showMessage'):
                    self.status.showMessage(t("sync.target_folder_error"), 5000)
            except Exception:
                pass
            return

        normalized: list[Path] = []
        for p in paths or []:
            normalized.append(p if isinstance(p, Path) else Path(p))
        self._upload_list_to_folder(target_folder, normalized)

    def _process_pending_drop(self):
        from PySide6.QtCore import QCoreApplication
        
        try:
            QCoreApplication.processEvents()
            
            paths = getattr(self, '_pending_drop_paths', None)
            target = getattr(self, '_pending_drop_target', None)
            
            if not paths or not target:
                return
            
            self._pending_drop_paths = None
            self._pending_drop_target = None
            
            QCoreApplication.processEvents()
            
            if isinstance(target, dict):
                self._handle_os_drop(paths, target)
            else:
                self._upload_list_to_folder(target, paths)
        except Exception as e:
            import traceback
            traceback.print_exc()

    def header_filter_icons_update(self):
        try:
            hdr = self.table.horizontalHeader()
            model = self.table.model()
            if not model:
                return

            # какие колонки сейчас «активны» (фильтруются)
            active = set()

            headers = [str(h).strip().lower() for h in getattr(FilesTableModel, "HEADERS", [])]
            def find_idx(names, default=None):
                for i, h in enumerate(headers):
                    if h in names:
                        return i
                return default

            idx_type     = find_idx({"тип","type"})
            idx_format   = find_idx({"формат","format"})
            idx_created  = find_idx({"создано","дата создания","created"})
            idx_modified = find_idx({"изменено","дата изменения","modified"})
            idx_name     = find_idx({"наименование","название","имя","имя файла"}, 1)
            # после вычисления idx_name
            try:
                global_query = (self.search.text() or "").strip()
            except Exception:
                global_query = ""

            if global_query and idx_name is not None:
                active.add(idx_name)
                # гарантируем, что ярлык создан
                self._header_filter_icon_label(idx_name)

            # текстовые фильтры (ПКМ -> ввод текста)
            for c, pat in getattr(self, "column_text_filters", {}).items():
                if pat:
                    active.add(int(c))
            # фильтры по наборам значений (ПКМ -> выпадающий список)
            for c, allowed in getattr(self, "column_filters", {}).items():
                if allowed:
                    c = int(c)
                    active.add(c)
                    # гарантируем, что ярлык создан - как и для глобального поиска
                    try:
                        self._header_filter_icon_label(c)
                    except Exception:
                        pass

            # тип
            if idx_type is not None and getattr(self, "_flt_type", None) not in (None, set(), {"file","folder"}):
                active.add(idx_type)

            # формат
            if idx_format is not None and getattr(self, "_flt_formats", set()):
                active.add(idx_format)

            # даты
            if idx_created is not None and any(getattr(self, "_flt_created", (None, None))):
                active.add(idx_created)
            if idx_modified is not None and any(getattr(self, "_flt_modified", (None, None))):
                active.add(idx_modified)

            # показать/спрятать иконки
            cols = model.columnCount()
            for col in range(cols):
                lbl = self._header_filter_icon_label(col)  # создает QLabel-накладку при необходимости
                if not lbl:
                    continue
                if self.table.isColumnHidden(col) or col not in active:
                    lbl.hide()
                else:
                    lbl.show()

            # переставить иконки — без sectionRect
            size = getattr(self, "FILTER_W", 14)
            y = (hdr.height() - size) // 2

            # ширина стрелки и правые паддинги, чтобы не налезть
            try:
                arrow_w = getattr(hdr, "_icon_px", 12)  # твой SortHeader рисует стрелку ~12px
            except Exception:
                arrow_w = 12
            arrow_gap_right = 18  # margin-right стрелки из твоего QSS
            gap = getattr(self, "FILTER_GAP", 4)
            right_pad = getattr(self, "RIGHT_PAD", 22)

            sorted_col = hdr.sortIndicatorSection() if getattr(hdr, "sortIndicatorShown", lambda: False)() else -1

            for col in range(cols):
                lbl = self._hdr_filter_labels.get(col)
                if not lbl or not lbl.isVisible():
                    continue

                sec_vx = hdr.sectionViewportPosition(col)
                sec_w  = hdr.sectionSize(col)
                right  = sec_vx + sec_w

                # если на колонке стрелка — уходим левее неё
                if col == sorted_col:
                    x = right - (arrow_w + arrow_gap_right + gap + size)
                else:
                    x = right - (right_pad + size)

                x = max(x, sec_vx + 4)  # страховка от налезания на текст
                lbl.setGeometry(x, y, size, size)
                try:
                    lbl.raise_()
                except Exception:
                    pass

            # Ensure the header checkbox stays above overlay labels/icons
            try:
                cb = getattr(self, "hdrcb", None)
                if cb is not None:
                    try:
                        from shiboken6 import isValid  # type: ignore
                        if isValid(cb):
                            cb.raise_()
                    except Exception:
                        try:
                            cb.raise_()
                        except Exception:
                            pass
            except Exception:
                pass

        except Exception:
            pass



    # Выпадающий список проектов
    def ensure_projects_loaded(self):
        """Best-effort lazy load for the projects combobox."""
        try:
            if getattr(self, "api", None) is None:
                return
            cb = getattr(self, "cb_projects", None)
            if cb is None:
                return
            # If only placeholder item exists, try to refresh list.
            if int(cb.count() or 0) > 1:
                return
            try:
                projects = self.api.list_projects()
            except Exception:
                return
            cb.blockSignals(True)
            cb.clear()
            cb.addItem(t("common.select_project"), userData=None)
            for p in (projects or []):
                try:
                    cb.addItem(get_title(p), userData=p.get("id"))
                except Exception:
                    pass
            cb.blockSignals(False)
        except Exception:
            pass

    def adjust_projects_popup(self):
        """Keep popup width reasonable and re-apply popup styling."""
        try:
            self._style_projects_combo_popup()
        except Exception:
            pass
        try:
            cb = getattr(self, "cb_projects", None)
            if cb is None:
                return
            view = cb.view()
            if view is None:
                return
            view.setMinimumWidth(max(int(cb.width()), int(view.sizeHintForColumn(0) or 0)))
        except Exception:
            pass


    # Вход/выход
    def do_login(self):
        dlg = LoginDialog(self.api, self)
        ret = dlg.exec()
        if ret:
            self.on_logged_in()

    def open_login_dialog(self):
        dlg = LoginDialog(self.api, self)
        if dlg.exec() == QDialog.Accepted:
            try:
                self.on_logged_in()
            except Exception:
                pass
        else:
            try:
                QMessageBox.warning(self, t("auth.title"), t("auth.login_failed_exit"))
            except Exception:
                pass
            sys.exit(0)

    def _capture_visible_order(self):
        """Capture current proxy-visible order to keep it stable during refresh."""
        try:
            proxy = getattr(self, "proxy", None)
            fm = getattr(self, "files_model", None)
            if proxy is None or fm is None:
                self._frozen_order = {}
                return
            mapping = {}
            rows = int(proxy.rowCount())
            for r in range(rows):
                idx = proxy.index(r, 0)
                sidx = proxy.mapToSource(idx)
                it = fm.item_at(sidx.row())
                if isinstance(it, dict):
                    key = ((it.get("type") or None), it.get("id"))
                    mapping[key] = r
            self._frozen_order = mapping
        except Exception:
            self._frozen_order = {}

    def on_logged_in(self):
        self.btn_login.setVisible(False)
        username = self.api.current_username or "Пользователь"
        self.btn_user.setText(username); self.btn_user.setVisible(True)

        # Require workspace selection before loading projects.
        try:
            settings = load_settings()
            ws_id = settings.get("workspace_id")
            if ws_id:
                self.api.selected_workspace_id = ws_id
                try:
                    self.status.showMessage(t("project.activating"))
                    QApplication.processEvents()
                    self.api.change_workspace(ws_id)
                except Exception:
                    pass
            else:
                self.cb_projects.blockSignals(True)
                self.cb_projects.clear()
                self.cb_projects.addItem(t("common.select_workspace_first"), userData=None)
                self.cb_projects.setCurrentIndex(0)
                self.cb_projects.blockSignals(False)
                self.cb_projects.setEnabled(False)
                self.status.showMessage(t("project.select_to_load"), 5000)
                return
        except Exception:
            pass

        self.cb_projects.setEnabled(True)
        self.status.showMessage(t("project.loading"))
        projects = self.api.list_projects()
        self.cb_projects.blockSignals(True); self.cb_projects.clear(); self.cb_projects.addItem(t("common.select_project"), userData=None)
        for p in projects:
            p_id = p.get("id") or p.get("project_id") or p.get("projectId")
            self.cb_projects.addItem(get_title(p), userData=p_id)
        self.cb_projects.setCurrentIndex(0)
        self.cb_projects.blockSignals(False)
        self.status.showMessage(t("common.projects_loaded", count=len(projects)), 3000)

    def logout_and_relogin(self):
        self.api.logout()
        self.cb_projects.clear()
        self.btn_user.setVisible(False); self.btn_login.setVisible(True)
        self.status.showMessage(t("project.logged_out"), 3000)
        self.set_initial_view()
        self.do_login()

    def choose_workspace(self):
        if not hasattr(self, 'api') or not self.api:
            print("[WORKSPACE ERROR] API client not available")
            return
        
        print("[WORKSPACE] Starting choose_workspace")
        
        try:
            workspaces = self.api.list_workspaces()
            print(f"[WORKSPACE] Got {len(workspaces) if workspaces else 0} workspaces")
        except Exception as e:
            print(f"[WORKSPACE ERROR] Failed to list workspaces: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.warning(self, t("common.error"), t("workspace.load_error", error=e))
            return
        
        if not workspaces or not isinstance(workspaces, list):
            print("[WORKSPACE] No workspaces or not a list")
            QMessageBox.warning(self, t("common.error"), t("workspace.none_available"))
            return
        
        print(f"[WORKSPACE] Opening dialog with {len(workspaces)} workspaces")
        
        settings = load_settings()
        saved_workspace_id = settings.get("workspace_id")
        print(f"[WORKSPACE] Current workspace_id={saved_workspace_id}")
        
        try:
            dlg = WorkspaceDialog(workspaces, self)
            result = dlg.exec()
            print(f"[WORKSPACE] Dialog result: {result}")
            
            if result == QDialog.DialogCode.Accepted:
                new_ws_id = dlg.selected_workspace_id()
                if new_ws_id:
                    print(f"[WORKSPACE] Selected new workspace id={new_ws_id}")

                    self.status.showMessage(t("project.changing"))
                    QApplication.processEvents()

                    try:
                        changed = self.api.change_workspace(new_ws_id)
                        print(f"[WORKSPACE] change_workspace returned: {changed}")
                        
                        if changed:
                            settings["workspace_id"] = new_ws_id
                            save_settings(settings)
                            self.api.selected_workspace_id = new_ws_id

                            self.status.showMessage(t("project.reloading"))
                            QApplication.processEvents()
                            
                            try:
                                projects = self.api.list_projects()
                                print(f"[WORKSPACE] Loaded {len(projects)} projects")
                                
                                self.cb_projects.blockSignals(True)
                                self.cb_projects.clear()
                                self.cb_projects.addItem(t("common.select_project"), userData=None)
                                for p in projects:
                                    p_id = p.get("id") or p.get("project_id") or p.get("projectId")
                                    self.cb_projects.addItem(get_title(p), userData=p_id)
                                self.cb_projects.setCurrentIndex(0)
                                self.cb_projects.blockSignals(False)
                                try:
                                    self.cb_projects.setEnabled(True)
                                except Exception:
                                    pass
                                self.status.showMessage(t("project.loaded_count", count=len(projects)), 3000)
                                self.set_initial_view()
                            except Exception as e:
                                print(f"[WORKSPACE ERROR] Failed to reload projects: {e}")
                                import traceback
                                traceback.print_exc()
                                self.status.showMessage(t("workspace.project_load_status_error"), 3000)
                                QMessageBox.warning(self, t("common.error"), t("workspace.project_load_error", error=e))
                        else:
                            print(f"[WORKSPACE] change_workspace returned False")
                            self.status.showMessage(t("workspace.switch_failed"), 3000)
                    except Exception as e:
                        print(f"[WORKSPACE ERROR] Failed to change workspace: {e}")
                        import traceback
                        traceback.print_exc()
                        self.status.showMessage(t("workspace.switch_status_error"), 3000)
                        QMessageBox.warning(self, t("common.error"), t("workspace.switch_error", error=e))
                else:
                    print(f"[WORKSPACE] No workspace selected")
            else:
                print(f"[WORKSPACE] Workspace selection cancelled")
        except Exception as e:
            print(f"[WORKSPACE ERROR] Error in dialog: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.warning(self, t("common.error"), t("workspace.select_error", error=e))


    def current_project_id(self):
        idx = self.cb_projects.currentIndex()
        return self.cb_projects.itemData(idx) if idx >= 0 else None

    def on_project_changed(self, _index: int):
        pid = self.current_project_id()
        if pid:
            for i in range(self.files_model.columnCount()):
                self.table.setColumnHidden(i, False)
            self.load_tree_for_project(pid)
        else:
            self.set_initial_view()

    # Дерево
    def enrich_all_tree(self, nodes: list):  # не вызывается при загрузке проекта (убрали долгую загрузку)
        # Показать индикатор занятости в статус-баре
        self.status.showMessage(t("project.getting_metadata"))
        self._set_progress_visible(True); self.progress.setRange(0, 0)
        QApplication.processEvents()
        items = []
        def collect(n):
            for c in n:
                if isinstance(c, dict):
                    items.append(c)
                    if "children" in c:
                        collect(c["children"])
        collect(nodes)
        def fetch_details(item):
            try:
                d = None
                if item.get("type") == "folder":
                    d = self.api.get_folder_details(item.get("id"))
                elif item.get("type") == "file":
                    d = self.api.get_document_details(item.get("id"))
                if d:
                    if "createdBy" in d: item["createdBy"] = d["createdBy"]
                    if "createTime" in d: item["createTime"] = d["createTime"]
                    if "createdAt" in d and not item.get("createTime"): item["createTime"] = d["createdAt"]
                    if "modifiedBy" in d: item["modifiedBy"] = d["modifiedBy"]
                    if "modifTime" in d: item["modifTime"] = d["modifTime"]
                    if "updatedAt" in d and not item.get("modifTime"): item["modifTime"] = d["updatedAt"]
            except Exception:
                pass
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(fetch_details, it) for it in items if it.get("id")]
            for _ in as_completed(futures):
                # поддерживаем отзывчивость интерфейса и анимацию
                QApplication.processEvents()
        self._set_progress_visible(False)
        self.status.clearMessage()

    # Notification handlers are injected from larix_nexus.ui.notification_handlers
 
    def _log_user_action(self, action: str, file_id: int | str = None, file_name: str = "", folder_id: int | str = None):
        """Log user action for filtering external changes in notifications"""
        try:
            action_entry = {
                "timestamp": time.time(),
                "action": action,  # "upload", "delete", "rename", "sync"
                "file_id": file_id,
                "file_name": file_name,
                "folder_id": folder_id
            }
            
            self._user_actions_log.append(action_entry)
            
            # Keep only last N actions
            if len(self._user_actions_log) > self._user_actions_max_size:
                self._user_actions_log = self._user_actions_log[-self._user_actions_max_size:]
            
            # Save to persistent storage
            save_user_actions_log(self._user_actions_log)
            
            print(f"[USER_ACTION] Logged: {action} file_id={file_id} name={file_name} folder_id={folder_id}")
        except Exception as e:
            print(f"[USER_ACTION] Error logging action: {e}")

    def _cleanup_expired_user_actions(self):
        """Remove user actions older than TTL"""
        try:
            current_time = time.time()
            self._user_actions_log = [
                action for action in self._user_actions_log
                if (current_time - action.get("timestamp", 0)) < self._user_actions_ttl
            ]
            print(f"[USER_ACTION] Cleaned up expired actions, remaining: {len(self._user_actions_log)}")
        except Exception as e:
            print(f"[USER_ACTION] Error cleaning up actions: {e}")

    def _load_user_actions_log(self) -> list:
        """Load user actions log from persistent storage"""
        return load_user_actions_log()
    
    def _trigger_sync_after_operation(self, folder_id: int | str, operation: str, file_name: str = ""):
        """Trigger immediate sync after file upload/delete operation.
        
        Args:
            folder_id: Folder ID where operation occurred (may be subfolder)
            operation: Operation type (upload/delete)
            file_name: Name of the file (for logging)
        """
        try:
            if not hasattr(self, 'sync2') or not self.sync2:
                return
            
            from larix_nexus.utils.logging import sync_log, new_trace_id
            from larix_nexus.utils.helpers import normalize_id
            
            target_fid = normalize_id(folder_id)
            
            # Strategy 1: Try CURRENT folder
            current_node = self.current_folder_node()
            if current_node:
                fid = normalize_id(current_node.get("id"))
                cfg = self.sync2.map.get(str(fid))
                
                if cfg:
                    sync_log(f"Triggering sync for current folder {fid} after {operation}", 
                              component="SYNC", 
                              op="trigger", 
                              path=file_name,
                              extra=f"folder_id={fid} operation={operation} target_folder={folder_id}")
                    
                    def sync_current():
                        try:
                            self.sync2._sync_one(fid, cfg)
                        except Exception:
                            pass
                    
                    QTimer.singleShot(100, sync_current)
                    return
            
            # Strategy 2: Search for PARENT folder in tree
            # Find the tree item for the target folder
            target_item = self.folder_item_by_id.get(target_fid)
            
            if target_item:
                # Walk up the tree to find first syncable parent
                parent_item = target_item.parent()
                checked_fids = []
                
                while parent_item is not None:
                    parent_id = parent_item.data(0, Qt.UserRole)
                    if parent_id:
                        parent_fid = normalize_id(parent_id)
                        parent_cfg = self.sync2.map.get(str(parent_fid))
                        
                        if parent_cfg:
                            sync_log(f"Found syncable parent folder {parent_fid} after {operation}", 
                                      component="SYNC", 
                                      op="trigger", 
                                      path=file_name,
                                      extra=f"folder_id={parent_fid} operation={operation} target_folder={folder_id} checked_parents={checked_fids}")
                            
                            def sync_parent():
                                try:
                                    self.sync2._sync_one(parent_fid, parent_cfg)
                                except Exception:
                                    pass
                            
                            QTimer.singleShot(100, sync_parent)
                            return
                        
                        checked_fids.append(parent_fid)
                    
                    parent_item = parent_item.parent()
                
                sync_log(f"No syncable parent found (checked {len(checked_fids)} folders)", 
                         component="SYNC", 
                         op="skip", 
                         path=file_name,
                         extra=f"folder_id={target_fid} operation={operation} reason=no_synced_parents checked={checked_fids}")
                return
            
            # Strategy 3: Try folder_id directly (last resort)
            cfg = self.sync2.map.get(str(target_fid))
            
            if not cfg:
                sync_log(f"No sync config for folder {target_fid} (no tree item, no direct sync)", 
                         component="SYNC", 
                         op="skip", 
                         path=file_name,
                         extra=f"folder_id={target_fid} operation={operation} reason=not_synced")
                return
            
            sync_log(f"Triggering sync for folder {target_fid} after {operation}", 
                     component="SYNC", 
                     op="trigger", 
                     path=file_name,
                     extra=f"folder_id={target_fid} operation={operation}")
            
            def sync_target():
                try:
                    self.sync2._sync_one(target_fid, cfg)
                except Exception:
                    pass
            
            QTimer.singleShot(100, sync_target)
            
        except Exception as e:
            try:
                from larix_nexus.utils.logging import sync_exc
                sync_exc(f"Failed to trigger sync after {operation}: {e}")
            except Exception:
                pass

    def _is_user_initiated_change(self, change_type: str, file_id: int = None, file_name: str = "", folder_id: int | str = None) -> bool:
        """Check if a change matches recent user actions (to filter out from notifications)
        
        Returns True if change should be FILTERED OUT (was user-initiated).
        Returns False if change should be SHOWN (came from external source/API).
        """
        try:
            current_time = time.time()
            
            # Map change types to action types
            action_map = {
                "new": ["upload", "sync"],       # New files can come from upload or sync
                "modified": ["upload", "sync"],  # Modified files can come from upload or sync
                "deleted": ["delete"],            # Deleted files from delete action
                "renamed": ["rename"]             # Renamed files
            }
            
            expected_actions = action_map.get(change_type, [])
            if not expected_actions:
                return False
            
            folder_id_norm = normalize_id(folder_id) if folder_id is not None else ""

            # Check if this change matches any recent user action
            for action in reversed(self._user_actions_log):  # Check newest first
                # Skip expired actions
                action_timestamp = action.get("timestamp", 0)
                if (current_time - action_timestamp) >= self._user_actions_ttl:
                    continue

                # If folder_id is known for this subscription, require folder match.
                # Otherwise name-based matching can incorrectly filter out external changes.
                try:
                    action_folder_id = action.get("folder_id")
                    if folder_id_norm and action_folder_id is not None and normalize_id(action_folder_id) != folder_id_norm:
                        continue
                except Exception:
                    pass
                
                # Check if action type matches
                action_type = action.get("action")
                if action_type not in expected_actions:
                    continue
                
                # Match by file_id (most reliable) - exact match
                action_file_id = action.get("file_id")
                if file_id and action_file_id and normalize_id(action_file_id) == normalize_id(file_id):
                    age_seconds = current_time - action_timestamp
                    print(f"[FILTER] ✓ Matched user action by file_id: {file_id}, action={action_type}, age={age_seconds:.1f}s")
                    return True
                
                # Match by file_name (fallback) - case-insensitive comparison
                action_file_name = action.get("file_name", "")
                if file_name and action_file_name:
                    # Normalize for comparison (case-insensitive, strip whitespace)
                    normalized_file_name = file_name.strip().lower()
                    normalized_action_name = action_file_name.strip().lower()
                    
                    if normalized_file_name == normalized_action_name:
                        age_seconds = current_time - action_timestamp
                        print(f"[FILTER] ✓ Matched user action by file_name: '{file_name}', action={action_type}, age={age_seconds:.1f}s")
                        return True
            
            # No match found - this is an external change
            print(f"[FILTER] ✗ No match found for {change_type}: file_id={file_id}, file_name='{file_name}' - EXTERNAL change")
            return False
        except Exception as e:
            print(f"[FILTER] Error checking user action: {e}")
            # On error, assume external change (don't filter)
            return False

    def _build_notification_file_state(self, project_id: int | str, folder_id: int | str, folder_path: str, force_fresh: bool = False) -> list[dict]:
        """Get current file state for notifications using cloud API.

        Returns list of {id, name, updatedAt, path, type} entries compatible with compare_file_states.

        Args:
            force_fresh: If True, bypass API cache to get fresh data.
        """
        files = []
        try:
            fid_norm = normalize_id(folder_id)
            pid_norm = normalize_project_id(project_id)
            
            print(f"[BUILD_FILE_STATE START] project_id={project_id} -> pid_norm={pid_norm}, folder_id={folder_id} -> fid_norm={fid_norm}")
            print(f"[BUILD_FILE_STATE START] fid_norm == pid_norm: {fid_norm == pid_norm}, force_fresh={force_fresh}")
            
            # Clear cache for project and folder if force_fresh is True
            if force_fresh:
                try:
                    key = f"tree:{pid_norm}"
                    self.api.cache.pop(key, None)
                    print(f"[BUILD_FILE_STATE START] Cleared cache for key: {key}")
                except Exception:
                    pass
            
            if fid_norm == pid_norm:
                print(f"[BUILD_FILE_STATE START] Using _collect_cloud_files_via_project_tree (root folder)")
                if hasattr(self, 'sync2') and self.sync2:
                    files = self.sync2._collect_cloud_files_via_project_tree(project_id, folder_id)
                else:
                    files = []
                print(f"[BUILD_FILE_STATE START] _collect_cloud_files_via_project_tree returned {len(files)} items")
            else:
                folder_details = None
                try:
                    print(f"[BUILD_FILE_STATE START] Calling get_folder_details for folder_id={folder_id}")
                    folder_details = self.api.get_folder_details(folder_id, force=True)
                    print(f"[BUILD_FILE_STATE START] get_folder_details returned: {type(folder_details)}, has keys={list(folder_details.keys()) if isinstance(folder_details, dict) else 'N/A'}")
                except Exception as e:
                    print(f"[BUILD_FILE_STATE START] ERROR get_folder_details: {e}")
                    folder_details = None
                if isinstance(folder_details, dict):
                    if hasattr(self, 'sync2') and self.sync2:
                        files = self.sync2._collect_cloud_files(folder_details, "", force_fresh=True)
                    else:
                        files = []
                    print(f"[BUILD_FILE_STATE START] _collect_cloud_files returned {len(files)} items")
                    # Some API responses return only folder metadata (no children/documents).
                    # If we got an empty result, fall back to traversing the project tree.
                    if not files:
                        print(f"[BUILD_FILE_STATE START] Empty result, trying _collect_cloud_files_via_project_tree")
                        try:
                            if hasattr(self, 'sync2') and self.sync2:
                                files = self.sync2._collect_cloud_files_via_project_tree(project_id, folder_id)
                            else:
                                files = []
                            print(f"[BUILD_FILE_STATE START] Fallback _collect_cloud_files_via_project_tree returned {len(files)} items")
                        except Exception as e:
                            print(f"[BUILD_FILE_STATE START] ERROR in fallback: {e}")
                            pass
                else:
                    print(f"[BUILD_FILE_STATE START] folder_details not a dict, using _collect_cloud_files_via_project_tree")
                    if hasattr(self, 'sync2') and self.sync2:
                        files = self.sync2._collect_cloud_files_via_project_tree(project_id, folder_id)
                    else:
                        files = []
                    print(f"[BUILD_FILE_STATE START] _collect_cloud_files_via_project_tree returned {len(files)} items")
        except Exception as e:
            print(f"[BUILD_FILE_STATE START] ERROR: {e}")
            import traceback
            traceback.print_exc()
            files = []

        file_state = []
        print(f"[BUILD_FILE_STATE] Processing {len(files)} items from API for folder_path={folder_path}")
        for item in files:
            try:
                if item.get("type") == "folder" or item.get("is_dir"):
                    print(f"[BUILD_FILE_STATE] Skipping folder: {item.get('name')}")
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                rel_path = str(item.get("rel_path") or "").replace("\\", "/").strip("/")
                parent_rel = ""
                if rel_path:
                    if rel_path == name:
                        parent_rel = ""
                    elif rel_path.endswith("/" + name):
                        parent_rel = rel_path[:-(len(name) + 1)]
                    else:
                        parent_rel = os.path.dirname(rel_path)

                base_path = str(folder_path or "")
                if parent_rel:
                    path = f"{base_path}/{parent_rel}" if base_path else parent_rel
                else:
                    path = base_path

                updated_at = item.get("updatedAt") or item.get("modifTime") or item.get("createTime")
                file_id = item.get("id")
                if file_id in (None, "", 0, "0", False):
                    file_id = rel_path or name
                file_entry = {
                    "id": file_id,
                    "name": name,
                    "updatedAt": updated_at,
                    "path": path,
                    "type": "file",
                }
                file_state.append(file_entry)
                print(f"[BUILD_FILE_STATE] Added file: name={name}, id={file_id}, path={path}")
            except Exception as e:
                print(f"[BUILD_FILE_STATE] Error processing item: {e}")
                continue

        print(f"[BUILD_FILE_STATE] Returning {len(file_state)} files")
        return file_state

    def _check_notifications(self):
        # Notification handlers are injected from larix_nexus.ui.notification_handlers
        return

    def _update_global_notification_badge(self):
        """Disabled per UX: hide the floating bell in the window corner."""
        try:
            self.global_notify_btn.setVisible(False)
            return
        except Exception as e:
            print(f"[GLOBAL BADGE] EXCEPTION while hiding: {e}")
            import traceback
            traceback.print_exc()

    def _show_notifications_menu(self):
        """Show dropdown menu with list of folders that have changes"""
        try:
            print(f"[NOTIFICATIONS MENU] Called, pending notifications: {len(self._pending_notifications)}")
            if not self._pending_notifications:
                print(f"[NOTIFICATIONS MENU] No pending notifications, exiting")
                return
            
            menu = QMenu(self)
            is_dark = _is_dark_mode()
            bg_color = "#1e1e1e" if is_dark else "white"
            border_color = "#505050" if is_dark else "#ddd"
            text_color = "#e0e0e0" if is_dark else "#222"
            hover_bg = "rgba(247, 146, 30, 0.15)" if is_dark else "#FFE3C2"
            menu.setStyleSheet(f"""
                QMenu {{
                    background-color: {bg_color};
                    border:1px solid {border_color};
                    border-radius:6px;
                    padding:4px;
                    color: {text_color};
                }}
                QMenu::item {{
                    padding: 8px 24px 8px 12px;
                    border-radius:4px;
                }}
                QMenu::item:selected {{
                    background-color: {hover_bg};
                }}
            """)
            
            for folder_id, notif_data in self._pending_notifications.items():
                folder_path = notif_data["folder_path"]
                changes_count = len(notif_data["changes"])
                print(f"[NOTIFICATIONS MENU] Adding folder: {folder_path}, changes: {changes_count}")
                
                action = menu.addAction(f"📁 {folder_path} ({changes_count})")
                # Store folder_id in action data for later retrieval
                action.setData(folder_id)
                action.triggered.connect(lambda checked=False, fid=folder_id: self._show_changes_dialog(fid))
            
            # Show menu below the button
            print(f"[NOTIFICATIONS MENU] Showing menu at button position")
            menu.exec_(self.global_notify_btn.mapToGlobal(self.global_notify_btn.rect().bottomLeft()))
            print(f"[NOTIFICATIONS MENU] Menu closed")
        
        except Exception as e:
            print(f"[NOTIFICATIONS MENU] EXCEPTION: {e}")
            import traceback
            traceback.print_exc()

    def _show_changes_dialog(self, folder_id):
        """Show detailed changes dialog for a specific folder with navigation"""
        try:
            print(f"[CHANGES DIALOG] Called for folder_id: {folder_id}")
            if folder_id not in self._pending_notifications:
                print(f"[CHANGES DIALOG] folder_id {folder_id} not in pending notifications")
                return
            
            notif_data = self._pending_notifications[folder_id]
            folder_path = notif_data["folder_path"]
            changes = notif_data["changes"]
            current_files = notif_data["current_files"]
            project_id = notif_data["project_id"]
            print(f"[CHANGES DIALOG] Showing changes for {folder_path}, {len(changes)} changes")
            
            # Create dialog with table of changes
            dialog = QDialog(self)
            dialog.setWindowTitle(f"Изменения в папке: {folder_path}")
            dialog.setMinimumSize(400, 250)
            dialog.resize(480, 350)
            is_dark = _is_dark_mode()
            if is_dark:
                dialog.setStyleSheet("""
                    QDialog {
                        background-color: #121212;
                        color: #e0e0e0;
                    }
                    QLabel {
                        color: #e0e0e0;
                    }
                    QTableWidget {
                        background-color: #1e1e1e;
                        color: #e0e0e0;
                    }
                    QTableWidget::item {
                        color: #e0e0e0;
                        padding: 6px 8px;
                    }
                    QTableWidget::item:selected {
                        background-color: rgba(247, 146, 30, 0.22);
                        color: #e0e0e0;
                    }
                    QHeaderView::section {
                        background-color: #1e1e1e;
                        color: #e0e0e0;
                        border: none;
                        padding: 6px 8px;
                    }
                    QTableWidget::viewport {
                        background-color: #1e1e1e;
                    }
                """)
            
            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(12, 12, 12, 12)
            layout.setSpacing(8)
            
            # Top bar with label and search
            top_layout = QHBoxLayout()
            
            label = QLabel(f"Обнаружено изменений: {len(changes)}")
            is_dark = _is_dark_mode()
            text_color = "#e0e0e0" if is_dark else "#000000"
            label.setStyleSheet(f"font-weight: bold; font-size: 12px; padding: 4px; color: {text_color};")
            top_layout.addWidget(label)
            
            top_layout.addStretch()
            
            # Search box with rounded style matching main menu
            search_box = QLineEdit()
            search_box.setPlaceholderText(t("notifications.search_placeholder"))
            search_box.setMaximumWidth(200)
            is_dark = _is_dark_mode()
            bg_color = "#1e1e1e" if is_dark else "white"
            border_color = "#505050" if is_dark else "#dcdcdc"
            text_color = "#e0e0e0" if is_dark else "#222"
            search_box.setStyleSheet(f"""
                QLineEdit {{
                    padding: 6px 12px;
                    border: 1px solid {border_color};
                    border-radius: 14px;
                    background: {bg_color};
                    color: {text_color};
                }}
            """)
            top_layout.addWidget(search_box)
            
            layout.addLayout(top_layout)
            
            # Table with changes - using QTableWidget for simpler sorting/filtering
            table = QTableWidget()
            table.setObjectName("changesTable")
            table.setColumnCount(3)
            table.setHorizontalHeaderLabels([t("notifications.operation"), t("notifications.type"), t("notifications.name")])
            table.setRowCount(len(changes))
            table.setSelectionBehavior(QAbstractItemView.SelectRows)
            table.setSelectionMode(QAbstractItemView.SingleSelection)
            table.setAlternatingRowColors(False)  # Отключаем чередующиеся цвета - все строки белые
            table.verticalHeader().setVisible(False)
            table.setSortingEnabled(True)
            table.setShowGrid(False)  # Убираем границы между ячейками
            
            # Set header alignment to left and context menu
            header = table.horizontalHeader()
            header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            header.setContextMenuPolicy(Qt.CustomContextMenu)
            
            # Enable mouse tracking for row-level hover
            table.setMouseTracking(True)
            
            # Use the same hover delegate as in the main table - единый делегат для всех ячеек
            table._hover_row = -1
            table._pressed_row = -1
            
            # Создаем единый делегат, который рисует фон всей строки
            class UnifiedRowDelegate(QStyledItemDelegate):
                """Рисует подсветку всей строки для окна изменений"""
                def paint(self, painter, option, index):
                    view = option.widget
                    row = index.row()
                    col = index.column()

                    opt = QStyleOptionViewItem(option)
                    opt.state &= ~QStyle.State_HasFocus
                    opt.state &= ~QStyle.State_Selected
                    opt.state &= ~QStyle.State_MouseOver

                    is_selected = bool(option.state & QStyle.State_Selected)
                    hover_row = getattr(view, "_hover_row", -1)
                    pressed_row = getattr(view, "_pressed_row", -1)
                    is_hovered = (row == hover_row)
                    is_pressed = (row == pressed_row)

                    is_dark = _is_dark_mode()

                    # Цвета подложки
                    if is_dark:
                        hover_color = QColor(247, 146, 30, int(255 * 0.15))
                        selected_color = QColor(247, 146, 30, int(255 * 0.22))
                        pressed_color = QColor(247, 146, 30, int(255 * 0.28))
                        text_color = QColor("#e0e0e0")
                    else:
                        hover_color = QColor("#FFE3C2")
                        selected_color = QColor("#FFC37A")
                        pressed_color = QColor("#FFCA91")
                        text_color = QColor("#000000")

                    bg = None
                    if is_selected:
                        bg = selected_color
                    elif is_pressed:
                        bg = pressed_color
                    elif is_hovered and not is_selected:
                        bg = hover_color

                    # Рисуем фон для всей строки
                    if bg is not None:
                        painter.save()
                        painter.setRenderHint(QPainter.Antialiasing, True)
                        painter.setPen(Qt.NoPen)
                        painter.setBrush(QBrush(bg))

                        # Для первой колонки - закругляем левые углы
                        if col == 0:
                            rect = QRectF(option.rect)
                            path = QPainterPath()
                            path.moveTo(rect.left() + 8, rect.top())
                            path.lineTo(rect.right(), rect.top())
                            path.lineTo(rect.right(), rect.bottom())
                            path.lineTo(rect.left() + 8, rect.bottom())
                            path.arcTo(rect.left(), rect.bottom() - 16, 16, 16, 270, -90)
                            path.lineTo(rect.left(), rect.top() + 8)
                            path.arcTo(rect.left(), rect.top(), 16, 16, 180, -90)
                            path.closeSubpath()
                            painter.drawPath(path)
                        # Для последней колонки - закругляем правые углы
                        elif col == view.columnCount() - 1:
                            rect = QRectF(option.rect)
                            path = QPainterPath()
                            path.moveTo(rect.left(), rect.top())
                            path.lineTo(rect.right() - 8, rect.top())
                            path.arcTo(rect.right() - 16, rect.top(), 16, 16, 90, -90)
                            path.lineTo(rect.right(), rect.bottom() - 8)
                            path.arcTo(rect.right() - 16, rect.bottom() - 16, 16, 16, 0, -90)
                            path.lineTo(rect.left(), rect.bottom())
                            path.closeSubpath()
                            painter.drawPath(path)
                        else:
                            # Средние колонки - обычный прямоугольник
                            painter.drawRect(option.rect)

                        painter.restore()

                    # Устанавливаем цвет текста в зависимости от темы
                    if bg is not None:
                        for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
                            opt.palette.setColor(group, QPalette.Text, text_color)
                            opt.palette.setColor(group, QPalette.HighlightedText, text_color)
                            opt.palette.setColor(group, QPalette.WindowText, text_color)

                    # Рисуем содержимое ячейки
                    super().paint(painter, opt, index)
            
            delegate = UnifiedRowDelegate(table)
            table.setItemDelegate(delegate)
            
            # Add event filter for mouse press/release to track pressed state
            class TableEventFilter(QObject):
                def eventFilter(self, obj, event):
                    if obj != table.viewport():
                        return False
                    
                    t = event.type()
                    if t == QEvent.MouseButtonPress:
                        idx = table.indexAt(event.pos())
                        if idx.isValid():
                            table._pressed_row = idx.row()
                            table.viewport().update()
                        return False
                    
                    if t == QEvent.MouseButtonRelease:
                        if getattr(table, "_pressed_row", -1) != -1:
                            table._pressed_row = -1
                            table.viewport().update()
                        return False
                    
                    return False
            
            event_filter = TableEventFilter(table)
            table.viewport().installEventFilter(event_filter)

            # Apply custom style matching folder tree
            is_dark = _is_dark_mode()
            if is_dark:
                table.setStyleSheet("""
                    QTableWidget {
                        border: 1px solid #505050;
                        border-radius:4px;
                        background-color: #1e1e1e;
                        gridline-color: transparent;
                    }
                    QTableWidget::item {
                        padding: 6px 8px;
                        border: none;
                        background: transparent;
                        color: #e0e0e0;
                    }
                    QTableWidget::item:selected {
                        background: transparent;
                        color: #e0e0e0;
                    }
                    QHeaderView::section {
                        background-color: #1e1e1e;
                        padding: 8px;
                        border: none;
                        font-weight: 600;
                        font-size: 12px;
                        text-align: left;
                        color: #e0e0e0;
                    }
                    QHeaderView::section:hover {
                        background-color: rgba(247, 146, 30, 0.15);
                    }
                """)
            else:
                table.setStyleSheet("""
                    QTableWidget {
                        border: 1px solid #dcdcdc;
                        border-radius:4px;
                        background-color: white;
                        gridline-color: transparent;
                    }
                    QTableWidget::item {
                        padding: 6px 8px;
                        border: none;
                        background: transparent;
                    }
                    QTableWidget::item:selected {
                        background: transparent;
                        color: #000000;
                    }
                    QHeaderView::section {
                        background-color: transparent;
                        padding: 8px;
                        border: none;
                        font-weight: 600;
                        font-size: 12px;
                        text-align: left;
                    }
                    QHeaderView::section:hover {
                        background-color: #FFE3C2;
                    }
                """)
            
            # Populate table with changes
            for row, change in enumerate(changes):
                # Store full change data in row for later retrieval
                op_type = change["type"]
                file_data = change["file"]
                
                # Column 0: Operation with icon
                op_item = QTableWidgetItem()
                if op_type == "new":
                    op_item.setIcon(themed_icon(CUSTOM_PLUS_ICON_PATH))
                    op_item.setText(t("notifications.op_new"))
                elif op_type == "modified":
                    op_item.setIcon(themed_icon(EDIT_ICON_PATH))
                    if change.get("version_update"):
                        op_item.setText(t("notifications.op_version_update"))
                    else:
                        op_item.setText(t("notifications.op_modified"))
                elif op_type == "renamed":
                    op_item.setIcon(themed_icon(EDIT_ICON_PATH))
                    op_item.setText(t("notifications.op_renamed"))
                elif op_type == "deleted":
                    op_item.setIcon(themed_icon(DELETE_ICON_PATH))
                    op_item.setText(t("notifications.op_deleted"))
                op_item.setFlags(op_item.flags() & ~Qt.ItemIsEditable)
                
                # Column 1: Type with icon
                type_item = QTableWidgetItem()
                item_type = file_data.get("type", "file")
                if item_type == "folder":
                    type_item.setIcon(themed_icon(CUSTOM_FOLDER_ICON_PATH))
                    type_item.setText(t("filter.folder"))
                else:
                    # Get file extension icon using IconProvider
                    file_name = file_data.get("name", "")
                    # Create a temporary item dict for IconProvider
                    temp_item = {"name": file_name, "type": "file"}
                    try:
                        # Use the main window's icon provider if available
                        if hasattr(self, 'icon_prov') and self.icon_prov:
                            icon = self.icon_prov.get_icon(temp_item)
                        else:
                            # Fallback: create temporary IconProvider
                            temp_prov = IconProvider(QApplication.style())
                            icon = temp_prov.get_icon(temp_item)
                    except Exception:
                        # Ultimate fallback: generic file icon
                        icon = QApplication.style().standardIcon(QStyle.SP_FileIcon)
                    type_item.setIcon(icon)
                    type_item.setText(t("filter.file"))
                type_item.setFlags(type_item.flags() & ~Qt.ItemIsEditable)
                
                # Column 2: Name (with old name for renamed files)
                name_item = QTableWidgetItem()
                file_name = file_data.get("name", t("common.unknown"))
                if op_type == "renamed" and "old_name" in change:
                    name_item.setText(f"{change['old_name']} → {file_name}")
                else:
                    name_item.setText(file_name)
                name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
                
                # Store change data for navigation
                name_item.setData(Qt.UserRole, change)
                
                table.setItem(row, 0, op_item)
                table.setItem(row, 1, type_item)
                table.setItem(row, 2, name_item)
            
            # Resize columns to fit content (по самому длинному слову)
            table.resizeColumnsToContents()
            # Add some padding to make it look better
            for col in range(3):
                current_width = table.columnWidth(col)
                table.setColumnWidth(col, current_width + 20)
            
            # Row-level hover highlighting using delegate
            def on_cell_entered(row, col):
                try:
                    table._hover_row = row
                except Exception:
                    pass
                table.viewport().update()
            
            def on_leave():
                try:
                    table._hover_row = -1
                except Exception:
                    pass
                table.viewport().update()
            
            table.cellEntered.connect(on_cell_entered)
            
            # Store leave handler for cleanup
            original_leave_event = table.leaveEvent
            def leave_event_wrapper(event):
                on_leave()
                if original_leave_event:
                    original_leave_event(event)
            table.leaveEvent = leave_event_wrapper
            
            # Search functionality with filter icon update
            def search_by_name(text):
                search_text = text.lower()
                is_filtering = bool(text.strip())
                
                # Show/hide rows based on search
                for row in range(table.rowCount()):
                    name_item = table.item(row, 2)
                    if name_item:
                        should_show = search_text in name_item.text().lower()
                        table.setRowHidden(row, not should_show)
                
                # Update filter icon for "Имя" column (column 2)
                if is_filtering:
                    active_filter["column"] = 2
                    active_filter["value"] = text
                elif active_filter["column"] == 2:  # Only clear if search was active
                    active_filter["column"] = -1
                    active_filter["value"] = ""
                
                update_header_icon()
            
            search_box.textChanged.connect(search_by_name)
            
            # Double-click handler for navigation
            def on_double_click(item):
                if not item:
                    return
                row = item.row()
                name_item = table.item(row, 2)
                if not name_item:
                    return
                change = name_item.data(Qt.UserRole)
                if not change:
                    return
                
                # Navigate only for new/modified files (not deleted)
                op_type = change.get("type")
                if op_type in ("new", "modified", "renamed"):
                    file_data = change.get("file", {})
                    file_id = file_data.get("id")
                    file_name = file_data.get("name", "")
                    
                    if file_id and file_name:
                        print(f"[CHANGES DIALOG] Navigating to file: {file_name} (id={file_id})")
                        # Close dialog and navigate
                        dialog.accept()
                        # Navigate to file in main window
                        self._navigate_to_file(project_id, folder_id, file_id, file_name)
            
            table.itemDoubleClicked.connect(on_double_click)
            
            # Context menu for header (filtering)
            active_filter = {"column": -1, "value": ""}  # Track active filter
            
            def update_header_icon():
                # Update filter icon in header based on active filter
                for col in range(table.columnCount()):
                    header_item = table.horizontalHeaderItem(col)
                    if header_item:
                        if col == active_filter["column"]:
                            # Show filter icon
                            header_item.setIcon(themed_icon(FILTER_ICON_PATH))
                        else:
                            # Clear icon
                            header_item.setIcon(QIcon())
            
            def show_header_context_menu(pos):
                col = header.logicalIndexAt(pos)
                if col < 0:
                    return
                
                menu = QMenu(table)
                menu.setObjectName("changesHeaderMenu")
                
                # Collect unique values from this column
                values = set()
                for row in range(table.rowCount()):
                    item = table.item(row, col)
                    if item:
                        text = item.text()
                        # Only add non-empty values
                        if text and text.strip():
                            values.add(text)
                
                # Add filter options
                for value in sorted(values):
                    def make_filter_action(column, val):
                        def apply_filter():
                            filter_by_column(column, val)
                        return apply_filter
                    
                    action = menu.addAction(f"Показать только: {value}")
                    action.triggered.connect(make_filter_action(col, value))
                
                if values:  # Only add separator if there are filter options
                    menu.addSeparator()
                
                # Reset filter
                act_reset = menu.addAction("Показать всё")
                act_reset.triggered.connect(reset_filter)
                
                menu.exec_(header.mapToGlobal(pos))
            
            header.customContextMenuRequested.connect(show_header_context_menu)
            
            def filter_by_column(col, text):
                # Clear search box when filtering by column
                search_box.clear()
                
                # Update active filter
                active_filter["column"] = col
                active_filter["value"] = text
                
                # Apply filter
                for row in range(table.rowCount()):
                    item = table.item(row, col)
                    if item:
                        should_show = (item.text() == text)
                        table.setRowHidden(row, not should_show)
                
                # Update header icons
                update_header_icon()
            
            def reset_filter():
                search_box.clear()
                
                # Clear active filter
                active_filter["column"] = -1
                active_filter["value"] = ""
                
                # Show all rows
                for row in range(table.rowCount()):
                    table.setRowHidden(row, False)
                
                # Update header icons
                update_header_icon()
            
            layout.addWidget(table, 1)

            # OK and Cancel buttons
            btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            btn_box.accepted.connect(dialog.accept)
            btn_box.rejected.connect(dialog.reject)
            layout.addWidget(btn_box)

            if is_dark:
                btn_box.setStyleSheet("""
                    QDialogButtonBox QPushButton {
                        background: transparent;
                        color: #e0e0e0;
                        border: 1px solid #505050;
                        border-radius: 14px;
                        padding: 6px 12px;
                        font-weight: 600;
                    }
                    QDialogButtonBox QPushButton:hover {
                        background: rgba(247, 146, 30, 0.15);
                        border-color: #FFA74B;
                        color: #e0e0e0;
                    }
                    QDialogButtonBox QPushButton:pressed {
                        background: rgba(247, 146, 30, 0.25);
                        border-color: #E07E12;
                        color: #e0e0e0;
                    }
                """)
            
            # When dialog closes with OK - mark folder as read
            # When closed with Cancel or X - keep notifications
            if dialog.exec_() == QDialog.Accepted:
                # Get fresh current state from cloud API to avoid stale data from pending notifications
                fresh_current_files = self._build_notification_file_state(project_id, folder_id, folder_path, force_fresh=True)
                
                # Update saved state with fresh data
                save_folder_notification(project_id, folder_id, folder_path, fresh_current_files)
                
                # Remove from pending notifications
                self._pending_notifications.pop(folder_id, None)
                
                # Save to persistent storage
                save_pending_notifications(self._pending_notifications)
                # Refresh top-bar notify button and menu
                try:
                    self._update_notify_icon()
                    self._build_notify_menu()
                except Exception:
                    pass
                
                # Update tree badge to subscribed (no changes)
                try:
                    it = self.folder_item_by_id.get(normalize_id(folder_id))
                    if it is not None:
                        it.setData(0, NOTIFY_ROLE, False)  # False = subscribed, no changes
                        self.tree.viewport().update()
                except Exception:
                    pass
                
                # Update global badge
                self._update_global_notification_badge()
        
        except Exception as e:
            QMessageBox.warning(self, t("common.error"), t("changes.show_error", error=e))

    def _navigate_to_file(self, project_id: int | str, folder_id: int | str, file_id: int | str, file_name: str):
        """Navigate to a specific file in the main window after notification click.
        
        Args:
            project_id: Project containing the file
            folder_id: Folder containing the file
            file_id: ID of the file to navigate to
            file_name: Name of the file (for searching if ID not found)
        """
        try:
            print(f"[NAVIGATE] Navigating to file: {file_name} (id={file_id}) in folder {folder_id}")
            
            # Step 1: Switch to correct project if needed
            current_pid = self.current_project_id()
            if normalize_project_id(current_pid) != normalize_project_id(project_id):
                print(f"[NAVIGATE] Switching project from {current_pid} to {project_id}")
                # Find project in combo box
                for i in range(self.cb_projects.count()):
                    p = self.cb_projects.itemData(i)
                    if isinstance(p, dict) and normalize_project_id(p.get("id")) == normalize_project_id(project_id):
                        self.cb_projects.setCurrentIndex(i)
                        # Wait for tree to load
                        QApplication.processEvents()
                        break
            
            # Step 2: Find and navigate to the folder in tree
            folder_item = self.folder_item_by_id.get(normalize_id(folder_id))
            if not folder_item:
                print(f"[NAVIGATE] Folder item not found for id {folder_id}")
                QMessageBox.warning(self, t("navigation.title"), t("navigation.folder_not_found", file=file_name))
                return
            
            # Step 3: Select folder in tree and open it
            print(f"[NAVIGATE] Selecting folder in tree")
            self.tree.setCurrentItem(folder_item)
            folder_node = folder_item.data(0, Qt.UserRole)
            if folder_node:
                self.open_folder_node(folder_node)
                QApplication.processEvents()
            
            # Step 4: Find and select the file in table
            print(f"[NAVIGATE] Searching for file in table: {file_name}")
            found = False
            model = self.table.model()
            rows = model.rowCount() if model else 0
            for row in range(rows):
                # Get item data
                try:
                    if not model:
                        break
                    index = model.index(row, 0)
                    item_data = model.data(index, Qt.UserRole)
                    
                    if not isinstance(item_data, dict):
                        continue
                    
                    # Match by ID (most reliable) or name
                    item_id = item_data.get("id")
                    item_name = item_data.get("name") or item_data.get("originalName") or ""
                    
                    if (item_id and item_id == file_id) or (item_name.lower() == file_name.lower()):
                        print(f"[NAVIGATE] Found file at row {row}")
                        # Select and scroll to row
                        self.table.selectRow(row)
                        self.table.scrollTo(index, QAbstractItemView.PositionAtCenter)
                        found = True
                        break
                except Exception as e:
                    print(f"[NAVIGATE] Error checking row {row}: {e}")
                    continue
            
            if not found:
                print(f"[NAVIGATE] File not found in table")
                QMessageBox.information(self, t("navigation.title"), 
                    t("navigation.file_not_found", file=file_name))
        
        except Exception as e:
            print(f"[NAVIGATE] Error: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.warning(self, t("navigation.title"), t("navigation.error", error=e))


    def collect_all_files_recursive(self, node: dict):
        out = []
        def walk(n):
            for c in (n.get("children") or []):
                if not isinstance(c, dict): continue
                if c.get("type") == "file": out.append(c)
                elif c.get("type") == "folder": walk(c)
        walk(node); return out

    # Таблица/фильтры/сортировка
    def _node_from_index(self, idx):
        """Пытаемся получить dict узла из модели/прокси."""
        if not idx.isValid():
            return None
        # если прокси - в исходную
        try:
            if idx.model() is self.proxy:
                idx = self.proxy.mapToSource(idx)
        except Exception:
            pass
        m = idx.model()
        # пробуем по всем колонкам UserRole
        try:
            for c in range(m.columnCount()):
                v = m.index(idx.row(), c).data(Qt.UserRole)
                if isinstance(v, dict):
                    return v
        except Exception:
            pass
        return None

    def table_context_menu(self, pos):
        # Context menus are injected from larix_nexus.ui.context_menus
        return

    def _context_file_items(self, pivot_node):
        """Return unique file items relevant to context menu selection."""
        items = []
        try:
            items = self.get_selected_items()
        except Exception:
            items = []

        pivot_doc_id = None
        if isinstance(pivot_node, dict):
            try:
                pivot_doc_id = pivot_node.get("id")
            except Exception:
                pivot_doc_id = None

        if not items and isinstance(pivot_node, dict):
            items = [pivot_node]
        elif isinstance(pivot_node, dict) and pivot_doc_id is not None:
            exists = any(isinstance(it, dict) and it.get("id") == pivot_doc_id for it in items)
            if not exists:
                items.append(pivot_node)

        files = []
        seen = set()
        for it in items:
            if not isinstance(it, dict):
                continue
            doc_id = it.get("id")
            if doc_id is None:
                continue
            t = str(it.get("type") or "").lower()
            if not any(token in t for token in ("file", "файл", "document")):
                continue
            key = ("file", doc_id)
            if key in seen:
                continue
            seen.add(key)
            files.append(it)

        if pivot_doc_id is not None:
            for idx, it in enumerate(list(files)):
                try:
                    if it.get("id") == pivot_doc_id:
                        files.insert(0, files.pop(idx))
                        break
                except Exception:
                    continue
        return files

    def _show_document_link_dialog(self, pivot_node):
        from PySide6.QtWidgets import QComboBox, QGroupBox, QFormLayout
        try:
            candidates = self._context_file_items(pivot_node)
        except Exception:
            candidates = []
        if not candidates:
            QMessageBox.information(self, t("link.copy_title"), t("link.select_file"))
            return

        file_ids = []
        for c in candidates:
            fid = c.get("id")
            if fid:
                file_ids.append(fid)
        
        if not file_ids:
            QMessageBox.warning(self, t("link.copy_title"), t("link.id_not_defined"))
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(t("link.create_title"))
        dlg.setModal(True)
        layout = QVBoxLayout(dlg)

        info = QLabel(t("link.files_selected", count=len(file_ids)))
        layout.addWidget(info)

        settings_group = QGroupBox(t("link.settings_title"))
        form = QFormLayout(settings_group)

        combo_validity = QComboBox()
        combo_validity.addItem(t("link.validity_always"), "NeverExpires")
        combo_validity.addItem(t("link.validity_day"), "Day")
        combo_validity.addItem(t("link.validity_week"), "Week")
        combo_validity.addItem(t("link.validity_month"), "Month")
        form.addRow(t("link.validity_label"), combo_validity)

        combo_access = QComboBox()
        combo_access.addItem(t("link.access_download"), "Download")
        combo_access.addItem(t("link.access_view"), "View")
        form.addRow(t("link.access_label"), combo_access)

        combo_version = QComboBox()
        combo_version.addItem(t("link.version_current"), "Current")
        form.addRow(t("link.version_label"), combo_version)

        layout.addWidget(settings_group)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dlg)
        btn_box.accepted.connect(dlg.accept)
        btn_box.rejected.connect(dlg.reject)
        layout.addWidget(btn_box)

        dlg.resize(400, dlg.sizeHint().height())

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        validity = combo_validity.currentData()
        access = combo_access.currentData()
        version = combo_version.currentData()

        result = self.api.generate_public_link(
            file_ids=file_ids,
            folder_ids=None,
            validity_period=validity,
            granted_access=access,
            file_version=version
        )

        if not isinstance(result, dict):
            QMessageBox.warning(self, t("link.copy_title"), t("link.get_failed"))
            return

        if result.get("ok"):
            link = (result.get("url") or "").strip()
            if link:
                self._present_link_dialog(link, file_ids)
                return
            QMessageBox.warning(self, t("link.copy_title"), t("link.no_link_in_response"))
            return

        err_code = (result.get("error") or "").lower()
        detail = result.get("detail")
        if err_code == "unauthorized":
            QMessageBox.warning(self, t("auth.title"), t("link.session_expired"))
            try:
                self.logout_and_relogin()
            except Exception:
                try:
                    self.api.logout()
                except Exception:
                    pass
            return

        if err_code == "network":
            msg = t("link.network_error")
        elif err_code == "invalid_json":
            msg = t("link.invalid_response")
        elif err_code == "missing_token":
            msg = t("link.no_link_in_response")
        else:
            msg = t("link.get_failed")
        if detail:
            msg = f"{msg}\n{detail}"
        QMessageBox.warning(self, t("link.copy_title"), msg)

    def _present_link_dialog(self, url: str, file_ids: list = None):
        file_ids = file_ids or []
        dlg = QDialog(self)
        dlg.setWindowTitle(t("link.public_title"))
        dlg.setModal(True)

        layout = QVBoxLayout(dlg)

        info = QLabel(t("link.created_label"))
        layout.addWidget(info)

        text = QPlainTextEdit(dlg)
        text.setPlainText(url)
        text.setReadOnly(True)
        text.setLineWrapMode(QPlainTextEdit.NoWrap)
        try:
            text.document().setMaximumBlockCount(1)
        except Exception:
            pass
        text.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        text.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        text.setMinimumHeight(48)
        text.setMaximumHeight(64)
        text.setFocusPolicy(Qt.StrongFocus)
        text.setStyleSheet("""
            QPlainTextEdit {
                background: #f5f5f5;
                border: 1px solid #dcdcdc;
                border-radius: 6px;
                padding: 8px;
            }
            QPlainTextEdit:focus {
                border: 1px solid #FFA74B;
            }
            QPlainTextEdit::selection {
                background: rgba(247, 146, 30, 0.25);
                color: #000000;
            }
        """)
        layout.addWidget(text)
        text.selectAll()

        controls = QHBoxLayout()
        copy_btn = QPushButton(t("link.copy_button"), dlg)
        copy_btn.setObjectName("accent")
        try:
            copy_icon = self._themed_icon(rsrc_path("icon", "copy.png"))
            if not copy_icon.isNull():
                copy_btn.setIcon(copy_icon)
        except Exception:
            pass
        copy_btn.setToolTip(t("link.copy_tooltip"))
        copy_btn.setCursor(Qt.PointingHandCursor)
        controls.addWidget(copy_btn)
        controls.addStretch()

        close_box = QDialogButtonBox(QDialogButtonBox.Close, parent=dlg)
        close_box.rejected.connect(dlg.reject)
        close_box.accepted.connect(dlg.accept)
        controls.addWidget(close_box)

        layout.addLayout(controls)

        def _copy():
            try:
                QApplication.clipboard().setText(url)
                self.status.showMessage(t("link.copied"), 4000)
            except Exception as e:
                QMessageBox.warning(self, t("link.copy_title"), t("link.copy_failed", error=e))

        copy_btn.clicked.connect(_copy)

        dlg.resize(520, dlg.sizeHint().height())
        dlg.exec()

    def apply_table_filters(self):
        # Table filtering is injected from larix_nexus.ui.table_filters
        return

        
    def get_checked_visible_items(self):
        items = []
        fm = getattr(self, "files_model", None)
        if fm is None:
            return items
        
        rows = self.proxy.rowCount()
        for r in range(rows):
            pidx = self.proxy.index(r, 0)
            if not pidx.isValid():
                continue
            try:
                src_idx = self.proxy.mapToSource(pidx)
                if not src_idx.isValid():
                    continue
                src_row = src_idx.row()
            except Exception:
                continue
                
            try:
                it = fm._data[src_row]
                if not it:
                    continue
                # Проверяем по ключу в множестве checked
                key = fm._cb_key(it)
                if key in fm.checked:
                    items.append(it)
            except Exception:
                continue
        return items

    def get_selected_items(self):
        """Return list of items for all currently selected rows in the files table."""
        items = []
        try:
            sm = self.table.selectionModel()
            if sm:
                for r in sm.selectedRows():
                    try:
                        src_row = self.proxy.mapToSource(r).row()
                        it = self.files_model.item_at(src_row)
                        if isinstance(it, dict):
                            items.append(it)
                    except Exception:
                        continue
        except Exception:
            pass
        return items

    def download_checked(self):
        # приоритет - галочки, иначе одиночное выделение (и файлы, и папки)
        # Глобальная защита от двойного запуска
        # ensure menu actions handle any reentrancy; no global guard here
        try:
            items = self.get_checked_visible_items()
        except Exception:
            items = []
        if not items:
            it = self.selected_item()
            if it:
                items = [it]
            else:
                QMessageBox.information(self, t("download.title_plural"),
                                        t("download.select_items"))
                return

        files = [it for it in items if it.get("type") == "file"]
        # Уберём дубли по (type,id), сохраняя порядок
        if files:
            seen = set(); uniq = []
            for it in files:
                key = (it.get("type"), it.get("id"))
                if key in seen:
                    continue
                seen.add(key); uniq.append(it)
            files = uniq
        folders = [it for it in items if it.get("type") == "folder"]

        # только файлы
        if files and not folders:
            if len(files) == 1:
                it = files[0]
                mode = self._ask_mode(t("download.title"), t("download.save_file"), t("download.save_as_zip"))
                if mode == "":
                    return
                if mode == "B":
                    self.download_file_as_zip(it)
                    return
                def_name = _sanitize_filename(it.get("originalName") or it.get("name") or f"file_{it.get('id')}.bin")
                save_path, _ = QFileDialog.getSaveFileName(self, t("download.save_as"), def_name, t("download.all_files"))
                if not save_path:
                    return
                _prev = getattr(self, "_force_mode", None); self._force_mode = "A"
                try:
                    local = self.ensure_downloaded(it)
                finally:
                    self._force_mode = _prev
                if not local:
                    QMessageBox.warning(self, t("download.title"), t("download.download_failed"))
                    return
                import shutil
                try:
                    shutil.copyfile(local, save_path)
                    QMessageBox.information(self, t("download.title"), t("download.file_saved"))
                except Exception as e:
                    QMessageBox.warning(self, t("download.title"), t("download.save_failed", error=e))
                return

            mode = self._ask_mode(t("download.title_plural"), t("download.title_plural"), t("download.save_as_zip"))
            if mode == "":
                return
            if mode == "A":
                dest_dir = self._pick_directory_showing_files(t("download.where_save"))
                if not dest_dir:
                    return
                import shutil
                ok = 0
                self._set_progress_visible(True); self.progress.setRange(0, len(files)); self.progress.setValue(0); QApplication.processEvents()
                try:
                    for i, it in enumerate(files):
                        self.progress.setValue(i + 1)
                        _prev = getattr(self, "_force_mode", None); self._force_mode = "A"
                        try:
                            local = self.ensure_downloaded(it)
                        finally:
                            self._force_mode = _prev
                        if not local:
                            continue
                        fname = it.get("originalName") or it.get("name") or f"file_{it.get('id')}.bin"
                        fname = _sanitize_filename(fname)
                        dst = os.path.join(dest_dir, self._unique_name(dest_dir, fname))
                        try:
                            shutil.copyfile(local, dst)
                            ok += 1
                        except Exception:
                            pass
                finally:
                    self._set_progress_visible(False)
                QMessageBox.information(self, t("download.title_plural"), t("download.files_saved", count=ok))
                return

            default = t("download.default_zip_name", date=datetime.now().strftime('%Y%m%d_%H%M'))
            save_path, _ = QFileDialog.getSaveFileName(self, t("zip.save_title"), default, f"{t('download.all_files')};;ZIP (*.zip)")
            if not save_path:
                return
            self._set_progress_visible(True); self.progress.setRange(0, 0); QApplication.processEvents()
            try:
                with zipfile.ZipFile(save_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    used = set()
                    for it in files:
                        _prev = getattr(self, "_force_mode", None); self._force_mode = "A"
                        try:
                            local = self.ensure_downloaded(it)
                        finally:
                            self._force_mode = _prev
                        if not local:
                            continue
                        fname = it.get("originalName") or it.get("name") or f"file_{it.get('id')}.bin"
                        arc = fname
                        if arc in used:
                            base, ext = os.path.splitext(fname); k = 1
                            while f"{base} ({k}){ext}" in used:
                                k += 1
                            arc = f"{base} ({k}){ext}"
                        used.add(arc)
                        zf.write(local, arcname=arc)
                QMessageBox.information(self, t("zip.title"), t("zip.created"))
            except Exception as e:
                QMessageBox.warning(self, t("zip.title"), t("zip.failed", error=e))
            finally:
                self._set_progress_visible(False)
            return
        # только папки
        if folders and not files:
            mode = getattr(self, "_force_mode", None) or self._ask_mode(t("folder.download_title"), t("structure.title"), t("zip.title"))
            if mode == "":
                return
            if mode == "A":
                dest_dir = self._pick_directory_showing_files(t("structure.where_save"))
                if not dest_dir:
                    return
                self._set_progress_visible(True); self.progress.setRange(0, len(folders)); self.progress.setValue(0); QApplication.processEvents()
                try:
                    for i, fd in enumerate(folders):
                        self.progress.setValue(i+1)
                        self._copy_folder_into(fd, dest_dir)  # без верхней «Выбранное_...»
                    QMessageBox.information(self, t("structure.title"), t("structure.done"))
                finally:
                    self._set_progress_visible(False)
                return
            else:
                default = t("zip.folder_prefix", date=datetime.now().strftime('%Y%m%d_%H%M'))
                save_path, _ = QFileDialog.getSaveFileName(self, t("zip.save_title"), default, t("download.all_files") + ";;ZIP (*.zip)")
                if not save_path:
                    return
                self._set_progress_visible(True); self.progress.setRange(0, 0); QApplication.processEvents()
                try:
                    with zipfile.ZipFile(save_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                        for fd in folders:
                            self._zip_folder_into(fd, zf, arc_prefix="")
                    QMessageBox.information(self, t("zip.title"), t("zip.created"))
                except Exception as e:
                    QMessageBox.warning(self, t("zip.title"), t("zip.failed", error=e))
                finally:
                    self._set_progress_visible(False)
                return

        # смешанный набор
        mode = getattr(self, "_force_mode", None) or self._ask_mode(t("download.title_plural"), t("structure.title"), t("zip.title"))
        if mode == "":
            return

        if mode == "A":
            # Custom: pick destination folder with visible contents, then copy files and folders and return
            base_dir = self._pick_directory_showing_files(t("download.where_save"))
            if not base_dir:
                return
            import shutil
            self._set_progress_visible(True); self.progress.setRange(0, len(items)); self.progress.setValue(0); QApplication.processEvents()
            try:
                for i, it in enumerate(items):
                    self.progress.setValue(i+1)
                    if it.get("type") == "file":
                        _prev = getattr(self, "_force_mode", None); self._force_mode = "A"
                        try:
                            local = self.ensure_downloaded(it)
                        finally:
                            self._force_mode = _prev
                        if not local:
                            continue
                        fname = it.get("originalName") or it.get("name") or f"file_{it.get('id')}.bin"
                        dst = os.path.join(base_dir, self._unique_name(base_dir, fname))
                        try:
                            shutil.copyfile(local, dst)
                        except Exception:
                            pass
                    else:
                        self._copy_folder_into(it, base_dir)
                QMessageBox.information(self, t("structure.title"), t("structure.done"))
            finally:
                self._set_progress_visible(False)
            return
            # Предупреждения о дубликатах проверяются после выбора папки назначения
            base_dir = self._pick_directory_showing_files(t("download.where_save"))
            if not base_dir:
                return
            import shutil
            self._set_progress_visible(True); self.progress.setRange(0, len(items)); self.progress.setValue(0); QApplication.processEvents()
            try:
                for i, it in enumerate(items):
                    self.progress.setValue(i+1)
                    if it.get("type") == "file":
                        _prev = getattr(self, "_force_mode", None); self._force_mode = "A"
                        try:
                            local = self.ensure_downloaded(it)
                        finally:
                            self._force_mode = _prev
                        if not local:
                            continue
                        fname = it.get("originalName") or it.get("name") or f"file_{it.get('id')}.bin"
                        dst = os.path.join(base_dir, self._unique_name(base_dir, fname))
                        try:
                            shutil.copyfile(local, dst)
                        except Exception:
                            pass
                    else:
                        self._copy_folder_into(it, base_dir)
                QMessageBox.information(self, t("structure.title"), t("structure.done"))
            finally:
                self._set_progress_visible(False)
        else:
            default = t("download.default_zip_name", date=datetime.now().strftime('%Y%m%d_%H%M'))
            save_path, _ = QFileDialog.getSaveFileName(self, t("zip.save_title"), default, f"{t('download.all_files')};;ZIP (*.zip)")
            if not save_path:
                return
            self._set_progress_visible(True); self.progress.setRange(0, 0); QApplication.processEvents()
            try:
                with zipfile.ZipFile(save_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    used = set()
                    for it in items:
                        if it.get("type") == "file":
                            _prev = getattr(self, "_force_mode", None); self._force_mode = "A"
                            try:
                                local = self.ensure_downloaded(it)
                            finally:
                                self._force_mode = _prev
                            if not local:
                                continue
                            fname = it.get("originalName") or it.get("name") or f"file_{it.get('id')}.bin"
                            arc = fname
                            if arc in used:
                                base, ext = os.path.splitext(fname); k = 1
                                while f"{base} ({k}){ext}" in used: k += 1
                                arc = f"{base} ({k}){ext}"
                            used.add(arc)
                            zf.write(local, arcname=arc)
                        else:
                            self._zip_folder_into(it, zf, arc_prefix="")
                QMessageBox.information(self, t("zip.title"), t("zip.created"))
            except Exception as e:
                QMessageBox.warning(self, t("zip.title"), t("zip.failed", error=e))
            finally:
                self._set_progress_visible(False)

    # --- Контекст для меню "Скачать": приоритет галочки, иначе одиночное выделение ---
    def _chosen_items_for_download(self):
        """
        Возвращает список элементов для скачивания/удаления:
        - приоритет: отмеченные галочками;
        - если галочек нет — одиночный выделенный элемент ЛКМ;
        - если ничего не выбрано — пустой список.
        """
        # 1) приоритет — галочки
        try:
            items = self.get_checked_visible_items()
        except Exception:
            items = []

        # Удаляем возможные дубликаты по (type,id), сохраняя порядок
        if items:
            seen = set()
            uniq = []
            for it in items:
                try:
                    key = (it.get("type"), it.get("id"))
                except Exception:
                    key = (None, None)
                if key in seen:
                    continue
                seen.add(key)
                uniq.append(it)
            return uniq

        # 2) фолбэк — одиночное выделение
        it = self.selected_item()
        return [it] if it else []

    def _refresh_download_menu(self):
        """Пересобирает меню у кнопки 'Скачать' под текущий выбор."""
        try:
            menu = getattr(self, "menu_download", None)
            if menu is None:
                return
            menu.clear()
            items = self._chosen_items_for_download()
            files = [it for it in items if _is_file(it)]
            folders = [it for it in items if _is_folder(it)]

            # Добавляем пункты всегда, управляя доступностью
            text = t("download.file") if (len(files) == 1 and not folders) else t("download.files")
            act_files = menu.addAction(text)
            act_files.setEnabled(bool(files) and not folders)
            act_files.triggered.connect(self.action_download_files)

            act_zip = menu.addAction(t("context.download_as_zip"))
            act_zip.setEnabled(bool(items))
            act_zip.triggered.connect(self.action_download_zip)

            act_folder = menu.addAction(t("context.download_structure"))
            act_folder.setEnabled(bool(folders))
            act_folder.triggered.connect(self.action_download_folder)
        except Exception as e:
            print(f"[REFRESH_DOWNLOAD_MENU] ERROR: {e}")

    # --- Действия из выпадающего меню "Скачать" ---
    def action_download_files(self):
        """Сохраняет только файлы (каждый отдельно). Папки игнорируются."""
        items = self._chosen_items_for_download()
        files = [it for it in items if _is_file(it)]
        # Перестраховка: уберём дубли по id
        seen = set(); _files = []
        for it in files:
            key = (it.get("type"), it.get("id"))
            if key in seen:
                continue
            seen.add(key); _files.append(it)
        files = _files

        if len(files) > 1:
            dest_dir = self._pick_directory_showing_files(t("download.where_save"))
            if not dest_dir:
                self._dl_busy = False
                return
            import shutil
            total = len(files)

            icon_provider = getattr(self, "icon_provider", None)
            dlg = BatchDownloadDialog(self, total, icon_provider)

            tasks: list[dict] = []
            conflicts = 0
            for idx, it in enumerate(files):
                base_name = _sanitize_filename(it.get("originalName") or it.get("name") or f"file_{it.get('id')}.bin")
                key = f"{it.get('id') or 'file'}_{idx}"
                target_path = os.path.join(dest_dir, base_name)
                conflict = os.path.exists(target_path)
                task = {
                    "key": key,
                    "item": it,
                    "base_name": base_name,
                    "target_name": base_name,
                    "conflict": conflict,
                }
                tasks.append(task)
                dlg.add_entry(key, it, base_name)
                if conflict:
                    conflicts += 1
                    dlg.set_status(key, "none", t("download.file_exists"))
                else:
                    dlg.set_status(key, "process", t("download.in_queue"))

            dlg.set_total_conflicts(conflicts)
            dlg.show()
            QApplication.processEvents()
            dlg.update_progress(0, total)

            ok_count = 0
            processed = 0
            errors: list[str] = []
            cancelled = False
            apply_all_choice: str | None = None
            conflicts_left = conflicts
            try:
                for task in tasks:
                    if dlg.was_cancelled():
                        cancelled = True
                        break

                    if task["conflict"]:
                        decision = apply_all_choice
                        if decision is None:
                            remaining = conflicts_left if conflicts_left > 0 else 1
                            decision, apply_all = dlg.ask_conflict(task["key"], task["target_name"], remaining)
                            if decision == "cancel":
                                cancelled = True
                                break
                            if apply_all:
                                apply_all_choice = decision
                        if decision == "copy":
                            new_name = self._unique_name(dest_dir, task["target_name"])
                            task["target_name"] = new_name
                            dlg.set_name(task["key"], new_name)
                        conflicts_left = max(0, conflicts_left - 1)
                        if conflicts_left == 0:
                            dlg.conflict_label.setText("")

                    if dlg.was_cancelled():
                        cancelled = True
                        break

                    dlg.set_status(task["key"], "process", t("dialog.downloading", current=0, total=0))
                    QApplication.processEvents()
                    # Show in-progress count including current file
                    try:
                        dlg.update_progress(processed + 1, total)
                    except Exception:
                        pass

                    prev_mode = getattr(self, "_force_mode", None)
                    self._force_mode = "A"
                    try:
                        file_id = task["item"].get("id")
                        if not file_id:
                            local = None
                        else:
                            base_name = task.get("base_name") or (_sanitize_filename(task["item"].get("originalName") or task["item"].get("name") or f"file_{file_id}.bin"))
                            local = self.api.download_file(file_id, base_name)
                    finally:
                        self._force_mode = prev_mode

                    if dlg.was_cancelled():
                        cancelled = True
                        break

                    if not local:
                        errors.append(task["target_name"])
                        dlg.set_status(task["key"], "none", t("download.download_failed"))
                    else:
                        target_path = os.path.join(dest_dir, task["target_name"])
                        # If source and destination are the same path, skip copy and treat as success
                        try:
                            same = os.path.normcase(os.path.abspath(local)) == os.path.normcase(os.path.abspath(target_path))
                        except Exception:
                            same = False
                        if same:
                            ok_count += 1
                            dlg.set_status(task["key"], "ok", t("download.already_exists"))
                            processed += 1
                            try:
                                dlg.update_progress(processed, total)
                            except Exception:
                                pass
                            QApplication.processEvents()
                            continue
                        try:
                            shutil.copyfile(local, target_path)
                            ok_count += 1
                            dlg.set_status(task["key"], "ok", t("download.status_saved"))
                        except Exception as e:
                            errors.append(task["target_name"])
                            dlg.set_status(task["key"], "none", t("download.copy_error", error=e))

                    processed += 1
                    dlg.update_progress(processed, total)
                    QApplication.processEvents()

                if cancelled or dlg.was_cancelled():
                    self.status.showMessage(t("download.cancelled"), 5000)
                else:
                    if errors:
                        dlg.finish(t("download.partial", ok=ok_count, total=total))
                        dlg.exec()
                        self.status.showMessage(t("download.done", count=f"{ok_count} из {total}"), 6000)
                    else:
                        dlg.finish(t("download.done", count=ok_count))
                        dlg.exec()
                        self.status.showMessage(t("download.done", count=ok_count), 5000)
            finally:
                self._dl_busy = False
            return
        if len(files) == 1:
            it = files[0]
            def_name = _sanitize_filename(it.get("originalName") or it.get("name") or f"file_{it.get('id')}.bin")
            save_path, _ = QFileDialog.getSaveFileName(self, t("download.save_as"), def_name, t("download.all_files"))
            if not save_path:
                self._dl_busy = False
                return
            _prev = getattr(self, "_force_mode", None); self._force_mode = "A"
            # show status and wait dialog for single download
            try:
                local = self.ensure_downloaded(it)
            finally:
                self._force_mode = _prev
            if not local:
                QMessageBox.warning(self, t("download.title"), t("download.download_failed"))
                self._dl_busy = False
                return
            try:
                self.status.showMessage(t("download.title") + "...")
                self._set_progress_visible(True)
                self.progress.setRange(0, 0)
                QApplication.processEvents()
            except Exception:
                pass
            try:
                import shutil
                shutil.copyfile(local, save_path)
                ok_msg = True
            except Exception as e:
                ok_msg = False
                try:
                    if os.path.exists(save_path) and os.path.getsize(save_path) > 0:
                        ok_msg = True
                except Exception:
                    ok_msg = False
                if not ok_msg:
                    QMessageBox.warning(self, t("download.downloading_file"), t("download.file_save_failed", error=e))
            try:
                self._set_progress_visible(False)
                self.status.clearMessage()
            except Exception:
                pass
            if ok_msg:
                QMessageBox.information(self, t("download.complete"), t("download.done", count=1))
            self._dl_busy = False
            return

        QMessageBox.information(self, t("download.files"), t("download.no_files"))
        self._dl_busy = False
        return

    def action_download_zip(self):
        """Собирает ZIP из всего выбранного (файлы и/или папки) через диалог "Сохранить как".
        Исключает параллельное копирование отдельных файлов.
        """
        items = self._chosen_items_for_download()
        if not items:
            return
        default = t("download.default_zip_name", date=datetime.now().strftime('%Y%m%d_%H%M'))
        save_path, _ = QFileDialog.getSaveFileName(self, t("zip.save_title"), default, f"{t('download.all_files')};;ZIP (*.zip)")
        if not save_path:
            return
        self._set_progress_visible(True); self.progress.setRange(0, 0); QApplication.processEvents()
        try:
            with zipfile.ZipFile(save_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                used = set()
                for it in items:
                    if it.get("type") == "file":
                        _prev = getattr(self, "_force_mode", None); self._force_mode = "A"
                        try:
                            local = self.ensure_downloaded(it)
                        finally:
                            self._force_mode = _prev
                        if not local:
                            continue
                        fname = it.get("originalName") or it.get("name") or f"file_{it.get('id')}.bin"
                        arc = fname
                        if arc in used:
                            base, ext = os.path.splitext(fname); k = 1
                            while f"{base} ({k}){ext}" in used: k += 1
                            arc = f"{base} ({k}){ext}"
                        used.add(arc)
                        zf.write(local, arcname=arc)
                    else:
                        self._zip_folder_into(it, zf, arc_prefix="")
            QMessageBox.information(self, t("zip.title"), t("zip.created"))
        except Exception as e:
            QMessageBox.warning(self, t("zip.title"), t("zip.failed", error=e))
        finally:
            self._set_progress_visible(False)

    def action_download_folder(self):
        items = self._chosen_items_for_download()
        if not any(isinstance(it, dict) and it.get("type") == "folder" for it in items):
            return
        self._force_mode = "A"
        try:
            self.download_checked()
        finally:
            self._force_mode = None

    
    # вверху файла (если ещё нет)
    def eventFilter(self, obj, ev):

        def _pt(e):
            try:
                return e.position().toPoint()  # PySide6
            except Exception:
                return e.pos()

        def _has_local_urls(e):
            md = getattr(e, "mimeData", lambda: None)()
            try:
                return bool(md and md.hasUrls() and any(u.isLocalFile() for u in md.urls()))
            except Exception:
                return False

        t = ev.type()

        # ----- ЛЕВОЕ ДЕРЕВО: только мышь/hover, DnD не трогаем -----
        tree = getattr(self, "tree", None)
        if tree is not None and obj is tree.viewport():
            if t in (QEvent.Enter, QEvent.HoverEnter):
                # гасим состояния таблицы
                if getattr(self, "table", None):
                    if getattr(self.table, "_hover_row", -1) != -1:
                        self.table._hover_row = -1
                        self.table.viewport().update()
                    if getattr(self.table, "_pressed_row", -1) != -1:
                        self.table._pressed_row = -1
                        self.table.viewport().update()

            elif t in (QEvent.MouseMove, QEvent.HoverMove):
                idx = self.tree.indexAt(_pt(ev))
                new_idx = idx if idx.isValid() else QModelIndex()
                cur_idx = getattr(self.tree, "_hover_index", QModelIndex())
                self.tree._hover_index = new_idx
                # Always update viewport to ensure branch indicators respond to any mouse movement
                self.tree.viewport().update()

            elif t == QEvent.MouseButtonPress:
                idx = self.tree.indexAt(_pt(ev))
                # клик по пустому месту - снимаем выделение в дереве
                if not idx.isValid():
                    try:
                        self.tree.clearSelection()
                        try:
                            self.tree.setCurrentItem(None)  # если это QTreeWidget
                        except Exception:
                            self.tree.setCurrentIndex(QModelIndex())
                    except Exception:
                        pass
                    try:
                        self._update_actions_enabled()
                    except Exception:
                        pass
                self.tree._pressed_index = idx if idx.isValid() else QModelIndex()
                self.tree.viewport().update()
                return False  # важно - не перехватываем событие, чтобы одиночный клик работал

            elif t == QEvent.MouseButtonRelease:
                if getattr(self.tree, "_pressed_index", QModelIndex()).isValid():
                    self.tree._pressed_index = QModelIndex()
                    self.tree.viewport().update()
                return False

            elif t in (QEvent.Leave, QEvent.HoverLeave):
                if getattr(self.tree, "_hover_index", QModelIndex()).isValid():
                    self.tree._hover_index = QModelIndex()
                    self.tree.viewport().update()
                if getattr(self.tree, "_pressed_index", QModelIndex()).isValid():
                    self.tree._pressed_index = QModelIndex()
                    self.tree.viewport().update()
                return False

            return False

        # ----- ПРАВАЯ ТАБЛЦА: мышь + DnD + клавиатура -----
        table = getattr(self, "table", None)
        if table is not None and obj is table.viewport():
            # Обработка клавиш Delete, Ctrl+C, Ctrl+X
            if t == QEvent.KeyPress:
                try:
                    key = ev.key()
                    mods = ev.modifiers()
                    
                    # Delete - удаление выбранного элемента
                    if key == Qt.Key_Delete:
                        try:
                            self.delete_selected_action()
                        except Exception:
                            pass
                        return True
                    
                    # Ctrl+X - вырезание (перемещение)
                    if key == Qt.Key_X and mods == Qt.ControlModifier:
                        try:
                            self.move_selected_action()
                        except Exception:
                            pass
                        return True
                    
                    # Ctrl+C - копирование (Qt обрабатывает стандартно для таблиц)
                    if key == Qt.Key_C and mods == Qt.ControlModifier:
                        return False  # Позволить стандартной обработке
                    
                    # Ctrl+V - вставка (Qt обрабатывает стандартно)
                    if key == Qt.Key_V and mods == Qt.ControlModifier:
                        return False  # Позволить стандартной обработке
                except Exception:
                    pass
            
            # hover по строкам
            # Подгон ширины при ресайзе вьюпорта таблицы
            if t == QEvent.Resize:
                try:
                    # debounce recalculation to improve responsiveness
                    self._resize_timer.start(120)
                except Exception:
                    pass
                return False
            # Block drag-selection with plain LMB (allow only Ctrl/Shift multi-select)
            if t == QEvent.MouseMove:
                try:
                    if hasattr(ev, 'buttons') and (ev.buttons() & Qt.LeftButton):
                        mods = getattr(ev, 'modifiers', lambda: Qt.NoModifier)()
                        if not (mods & (Qt.ControlModifier | Qt.ShiftModifier)):
                            return True
                except Exception:
                    pass
            if t in (QEvent.MouseMove, QEvent.HoverMove):
                idx = self.table.indexAt(_pt(ev))
                # спец-зона чекбокса в первой колонке - пропускаем
                try:
                    if idx.isValid() and idx.column() == 0:
                        r = self.table.visualRect(idx)
                        size = min(18, r.height() - 6)  # Исправлено: 18 вместо 14 - совпадает с CheckBoxDelegate.BOX
                        x = r.x() + (r.width() - size) // 2
                        y = r.y() + (r.height() - size) // 2
                        pt = _pt(ev)
                        if pt and (x <= pt.x() <= x + size) and (y <= pt.y() <= y + size):
                            return False
                except Exception:
                    pass

                row = idx.row() if idx.isValid() else -1
                if row != getattr(self.table, "_hover_row", -1):
                    self.table._hover_row = row
                    self.table.viewport().update()
                return False

            # одиночный клик: снимаем выделение, если клик в пустоту
            if t == QEvent.MouseButtonPress:
                idx = self.table.indexAt(_pt(ev))
                # если попали в чекбокс - пропустим стандартной логике
                try:
                    if idx.isValid() and idx.column() == 0:
                        r = self.table.visualRect(idx)
                        size = min(18, r.height() - 6)  # Исправлено: 18 вместо 14 - совпадает с CheckBoxDelegate.BOX
                        x = r.x() + (r.width() - size) // 2
                        y = r.y() + (r.height() - size) // 2
                        pt = _pt(ev)
                        if pt and (x <= pt.x() <= x + size) and (y <= pt.y() <= y + size):
                            # If user has multi-selection (Ctrl/Shift), clicking a checkbox
                            # may collapse selection. Cache selected rows for bulk toggling.
                            try:
                                sm = self.table.selectionModel()
                                rows = [i.row() for i in (sm.selectedRows() if sm else [])]
                                self.table._bulk_check_rows = rows if len(rows) > 1 else None
                            except Exception:
                                self.table._bulk_check_rows = None
                            return False
                except Exception:
                    pass

                if not idx.isValid():
                    try:
                        sm = self.table.selectionModel()
                        if sm:
                            sm.clearSelection()
                    except Exception:
                        pass
                    try:
                        self.table.clearSelection()
                        self.table.setCurrentIndex(QModelIndex())
                    except Exception:
                        pass
                    # сброс внутренних флагов делегата
                    self.table._hover_row = -1
                    self.table._pressed_row = -1
                    self.table.viewport().update()
                    ev.accept()
                    return True  # перехватываем, чтобы Qt не «возвращал» выделение

                # обычный клик по строке
                self.table._pressed_row = idx.row()
                self.table.viewport().update()
                return False

            if t == QEvent.MouseButtonRelease:
                if getattr(self.table, "_pressed_row", -1) != -1:
                    self.table._pressed_row = -1
                    self.table.viewport().update()
                return False

            # DnD - пустая зона подсвечивает весь viewport, папка - только строку
            if t == QEvent.DragEnter:
                if _has_local_urls(ev):
                    ev.acceptProposedAction()
                    try:
                        self.table.setProperty("dropHoverEmpty", True)
                        self.table._hover_row = -1
                        self.table.style().unpolish(self.table); self.table.style().polish(self.table)
                        self.table.viewport().update()
                    except Exception:
                        pass
                    return True
                ev.ignore(); return True

            if t == QEvent.DragMove:
                if not _has_local_urls(ev):
                    ev.ignore(); return True

                pos = _pt(ev)
                idx = self.table.indexAt(pos)
                is_folder = False
                if idx.isValid():
                    try:
                        node = self._node_from_index(idx)
                        is_folder = isinstance(node, dict) and str(node.get("type","")).lower() in ("folder","dir","directory","папка")
                    except Exception:
                        is_folder = False

                if is_folder:
                    self.table.setProperty("dropHoverEmpty", False)
                    self.table._hover_row = idx.row()
                else:
                    self.table.setProperty("dropHoverEmpty", True)
                    self.table._hover_row = -1

                try:
                    self.table.style().unpolish(self.table); self.table.style().polish(self.table)
                    self.table.viewport().update()
                except Exception:
                    pass

                ev.acceptProposedAction()
                return True

            if t == QEvent.DragLeave:
                try:
                    self.table.setProperty("dropHoverEmpty", False)
                    self.table._hover_row = -1
                    self.table.style().unpolish(self.table); self.table.style().polish(self.table)
                    self.table.viewport().update()
                except Exception:
                    pass
                return True

            if t == QEvent.Drop:
                # снять общую подсветку области
                try:
                    self.table.setProperty("dropHoverEmpty", False)
                    self.table.style().unpolish(self.table); self.table.style().polish(self.table)
                    self.table.viewport().update()
                except Exception:
                    pass

                # принимаем только локальные файлы/папки
                if not _has_local_urls(ev):
                    ev.ignore()
                    return True

                 # собрать локальные пути
                md = getattr(ev, "mimeData", lambda: None)()
                urls = []
                try:
                    urls = [u for u in (md.urls() or []) if u.isLocalFile()]
                except Exception:
                    urls = []
                
                # DEBUG: Log drop event
                try:
                    from larix_nexus.utils.logging import sync_log
                    sync_log(f"Drop event detected", 
                             component="FS", 
                             op="drop_event", 
                             extra=f"urls_count={len(urls)} has_mimeData={md is not None}")
                except Exception:
                    pass
                
                paths = []
                if urls:
                    try:
                        paths = [Path(u.toLocalFile()) for u in urls if u.isLocalFile()]
                    except Exception as e:
                        # DEBUG: Log path extraction error
                        try:
                            from larix_nexus.utils.logging import sync_exc
                            sync_exc(f"Failed to extract paths from drop: {e}")
                        except Exception:
                            pass
                        paths = []
                
                # DEBUG: Log extracted paths
                try:
                    from larix_nexus.utils.logging import sync_log
                    sync_log(f"Extracted paths from drop", 
                             component="FS", 
                             op="drop_paths", 
                             extra=f"paths_count={len(paths)} paths={str([str(p) for p in paths[:3]])}...")
                except Exception:
                    pass
                
                if not paths:
                    # DEBUG: Log early return
                    try:
                        from larix_nexus.utils.logging import sync_log
                        sync_log(f"Drop event ignored - no paths extracted", 
                                 component="FS", 
                                 op="drop_skip", 
                                 reason="no_paths")
                    except Exception:
                        pass
                    ev.acceptProposedAction()
                    return True

                pid = self.current_project_id()

                # - РЕЖМ КОРНЯ: если открыт корень, то принимаем ТОЛЬКО ПАПК и грузим их структуру в корень
                is_root = self._is_root_open()
                if is_root:
                    dirs = [p for p in paths if p.is_dir()]
                    files = [p for p in paths if p.is_file()]

                    if files:
                        # запрет загрузки одиночных файлов в корень
                        try:
                            if hasattr(self, 'status') and hasattr(self.status, 'showMessage'):
                                self.status.showMessage(t("upload.root_folders_only"), 5000)
                        except Exception:
                            pass

                    if pid and dirs:
                        # спиннер
                        try:
                            self.status.showMessage(t("status.loading_to_root"))
                            self._set_progress_visible(True)
                            self.progress.setRange(0, 0)
                            QApplication.processEvents()
                        except Exception:
                            pass
                        try:
                            for d in dirs:
                                self._upload_dir_to_root(pid, d)
                        finally:
                            try:
                                self._set_progress_visible(False)
                                self.status.clearMessage()
                            except Exception:
                                pass
                            try:
                                self.soft_refresh_and_restore_view()
                            except Exception:
                                pass

                    ev.acceptProposedAction()
                    # финальный сброс строкового ховера
                    self.table._hover_row = -1
                    self.table.viewport().update()
                    return True

                # - Обычный режим (не корень): в папку под курсором или в открытую справа
                pos = _pt(ev)
                idx = self.table.indexAt(pos)
                target_node = None
                if idx.isValid():
                    try:
                        cand = self._node_from_index(idx)
                        if isinstance(cand, dict) and str(cand.get("type","")).lower() in ("folder","dir","directory","папка"):
                            target_node = cand
                    except Exception:
                        target_node = None
                if not target_node:
                    target_node = self.current_folder_node()

                if isinstance(target_node, dict) and paths:
                    from PySide6.QtCore import QTimer
                    
                    self._pending_drop_paths = paths
                    self._pending_drop_target = target_node
                    
                    QTimer.singleShot(150, self._process_pending_drop)

                ev.acceptProposedAction()
                self.table._hover_row = -1
                self.table.viewport().update()
                return True


            return False

        # по умолчанию - стандартная обработка
        return super().eventFilter(obj, ev)


    # --- Меню "Загрузить" и слоты ---

    def _action_create_folder(self):
        """Создать папку: в корне - в корень, иначе - в текущую папку."""

        from .dialogs import InputDialog
        
        dlg = InputDialog(self, t("folder.create_title"), t("folder.name_label"))
        if dlg.exec() != QDialog.Accepted:
            return
        name = dlg.get_text()
        if not name:
            return
        pid = self.current_project_id()
        if not pid:
            QMessageBox.information(self, t("folder.create_title"), t("folder.no_project"))
            return

        try:
            if self._is_root_open():
                # создать в КОРНЕ
                rid = self._ensure_subfolder(pid, None, name)
                if not rid:
                    QMessageBox.information(self, t("folder.create_title"), t("folder.root_failed"))
            else:
                # создать внутри текущей папки
                node = self.current_folder_node()
                if not isinstance(node, dict):
                    QMessageBox.information(self, t("folder.create_title"), t("folder.current_failed"))
                else:
                    self.api.create_folder(pid, node.get("id") or 0, name)
        finally:
            # мягкий рефреш
            try:
                self.soft_refresh_and_restore_view()
            except Exception:
                pass

    # CRUD действия
    def create_new_folder(self):
        parent = self.current_folder_node()
        if not self.current_project_id():
                QMessageBox.information(self, t("folder.new_title"), t("folder.select_project_first")); return
        if not parent or parent.get("type") != "folder":
                parent = {} # Create in root
        from .dialogs import InputDialog
        dlg = InputDialog(self, t("folder.new_title"), t("folder.name_label"))
        if dlg.exec() != QDialog.Accepted:
            return
        name = dlg.get_text()
        if not name:
            return
        pid = self.current_project_id(); parent_id = parent.get("id")
        if self.api.create_folder(pid, parent_id, name):
            QMessageBox.information(self, t("folder.new_title"), t("folder.created"))
            self.soft_refresh_and_restore_view()
        else:
            QMessageBox.warning(self, t("folder.new_title"), t("folder.create_failed"))
    def delete_selected_action(self):
        """
        Немедленное удаление выделенного элемента из облака через API.
        """
        item = self.selected_item()
        if not item:
            QMessageBox.information(self, t("delete.title"), t("delete.select_item"))
            return
        
        # Получаем путь синхронизации для текущей папки
        sync_path = None
        folder_id = self.current_folder_node().get("id") if self.current_folder_node() else None
        try:
            if hasattr(self, 'sync2') and folder_id:
                sync_path = self.sync2.get_sync_path(folder_id)
        except Exception:
            pass
        
        if item.get("type") == "folder":
            if QMessageBox.question(
                self, 
                t("folder.delete_title"), 
                t("folder.delete_confirm"), 
                QMessageBox.Yes | QMessageBox.No
            ) != QMessageBox.Yes: 
                return
            
            # Прямое удаление папки через API
            if self.api.delete_folder(item.get("id")):
                # Удаляем локальную папку, если настроена синхронизация
                if sync_path:
                    try:
                        rel_path = self._get_item_relative_path(item)
                        if rel_path:
                            local_folder = os.path.join(sync_path, rel_path.replace("/", os.sep))
                            if os.path.exists(local_folder) and os.path.isdir(local_folder):
                                import shutil
                                shutil.rmtree(local_folder)
                                sync_log("Локальная папка удалена: {}", local_folder)
                    except Exception as e:
                        sync_log("Ошибка удаления локальной папки: {}", str(e))
                
                self.soft_refresh_and_restore_view()
                QMessageBox.information(self, t("delete.title"), t("folder.deleted"))
            else: 
                QMessageBox.warning(self, t("delete.title"), t("folder.delete_failed"))
        else:
            if QMessageBox.question(
                self, 
                t("file.delete_title"), 
                t("file.delete_confirm"), 
                QMessageBox.Yes | QMessageBox.No
            ) != QMessageBox.Yes: 
                return
            
            # Прямое удаление файла через API
            if self.api.delete_document(item.get("id")):
                # Log user action to filter from notifications
                try:
                    self._log_user_action("delete", file_id=item.get("id"), file_name=item.get("name", ""))
                except Exception:
                    pass
                
                # Fast refresh: only update current folder, not entire tree
                try:
                    current_node = self.current_folder_node()
                    if current_node:
                        self.open_folder_node(current_node)
                except Exception:
                    pass
                QMessageBox.information(self, t("delete.title"), t("file.deleted"))
            else: 
                QMessageBox.warning(self, t("delete.title"), t("file.delete_failed"))

    def _show_versions_for_node(self, node: dict):
        """Открыть диалог со списком версий выбранного файла."""
        try:
            if not isinstance(node, dict) or str(node.get("type", "")).lower() != "file":
                QMessageBox.information(self, t("version.title"), t("version.select_file")); 
                return
            doc_id = node.get("id")
            if not doc_id:
                QMessageBox.information(self, t("version.title"), t("version.id_not_defined")); 
                return

            name = node.get("originalName") or node.get("name") or f"Документ {doc_id}"
            self.status.showMessage(t("version.loading"))
            versions = self.api.get_document_versions(doc_id, force=True)
            self.status.clearMessage()
            # Нормализуем ответ: поддержка dict {'file_name','versions'} и простого list
            base_file_name = name
            if isinstance(versions, dict):
                base_file_name = versions.get("file_name") or versions.get("fileName") or name
                versions = list(versions.get("versions") or [])
            else:
                versions = list(versions or [])

            if not versions:
                QMessageBox.information(self, t("version.title"), t("version.not_found"))
                return

            dlg = QDialog(self)
            dlg.setWindowTitle(t("version.dialog_title", name=name))
            current_theme = getattr(self, "_current_theme", THEME_LIGHT)
            is_dark = current_theme == THEME_DARK
            _set_window_theme_dark(dlg, dark=is_dark)
            lay = QVBoxLayout(dlg)

            lst = QListWidget(dlg)
            for i, v in enumerate(versions, 1):
                try:
                    ver_no = v.get("version") or v.get("versionNumber") or v.get("versionId") or i
                    when_raw = v.get("createTime") or v.get("createdAt") or v.get("modifTime") or v.get("updatedAt")
                    if not when_raw:
                        when_raw = v.get("created_ts") or v.get("createdTs")
                    when = ""
                    if when_raw:
                        ts = parse_date_like(str(when_raw))
                        if ts > 0:
                            when = _user_display_datetime(ts)
                    who = v.get("createdBy") or v.get("modifiedBy") or ""
                    size = normalize_size(v)
                    extra = " · ".join([t for t in [when, str(who) if who else "", f"{size} {t('common.bytes')}" if size else ""] if t])
                    text = t("version.number", n=ver_no) + (f" - {extra}" if extra else "")
                    lst.addItem(text)
                except Exception:
                    lst.addItem(t("version.number", n=i))
            lay.addWidget(lst)
            # Разрешим мультивыбор для сравнения
            lst.setSelectionMode(QAbstractItemView.ExtendedSelection)
            lst.setStyleSheet("""
                QListWidget {
                    background: transparent;
                    border: none;
                    outline: none;
                }
                QListWidget::item {
                    border-radius: 8px;
                    padding: 6px 10px;
                    margin: 2px 4px;
                }
                QListWidget::item:hover {
                    background: #FFE3C2;
                }
                QListWidget::item:selected {
                    background: #FFC37A;
                }
            """)

            # Сохраним исходные dict каждой версии в QListWidgetItem
            for i in range(lst.count()):
                it = lst.item(i)
                it.setData(Qt.UserRole, versions[i])

            def _safe_ver_filename(base_name: str, ver: dict) -> str:
                base = _sanitize_filename(base_name or name)
                stem, ext = os.path.splitext(base)
                ver_no = ver.get("version") or ver.get("versionNumber") or ver.get("versionId") or ""
                when_raw = ver.get("created_ts") or ver.get("createTime") or ver.get("createdAt") or ver.get("modifTime") or ver.get("updatedAt")
                ts = 0.0
                if when_raw:
                    ts = parse_date_like(str(when_raw))
                parts = [stem]
                if ver_no != "":
                    parts.append(f"v{ver_no}")
                if ts > 0:
                    parts.append(datetime.fromtimestamp(ts).strftime("%Y%m%d_%H%M%S"))
                fname = " - ".join(parts) + ext
                try:
                    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
                    full = os.path.join(DOWNLOAD_DIR, fname)
                    if os.path.exists(full):
                        fname = self._unique_name(DOWNLOAD_DIR, fname)
                except Exception:
                    pass
                return fname

            def _download_version_local(ver: dict) -> str:
                file_id = ver.get("document_id") or ver.get("id")
                if not file_id:
                    return ""
                fname = _safe_ver_filename(base_file_name, ver)

                self._set_progress_visible(True)
                self.progress.setRange(0, 0)
                QApplication.processEvents()
                wait = WaitDialog(t("version.wait_download"), self)
                try:
                    wait.show(); QApplication.processEvents()
                except Exception:
                    pass

                def _cb(done, total):
                    self.progress.setRange(0, 100)
                    self.progress.setValue(int(done * 100 / max(1, total)))
                    QApplication.processEvents()

                try:
                    local_path = self.api.download_file(file_id, fname, progress_cb=_cb)
                finally:
                    self._set_progress_visible(False)
                    try:
                        wait.set_done(t("version.download_complete"))
                    except Exception:
                        pass
                return local_path or ""

            def _open_selected_local():
                it = lst.currentItem()
                if not it:
                    return
                ver = it.data(Qt.UserRole) or {}
                local = _download_version_local(ver)
                if local:
                    open_in_os(local)
                else:
                    QMessageBox.warning(dlg, t("version.open_on_pc"), t("version.download_failed"))

            def _compare_selected_pdf():
                dlg.accept()
                from PySide6.QtCore import QTimer, QCoreApplication
                
                def show_compare_dialog():
                    try:
                        QCoreApplication.processEvents()
                        self._show_compare_versions_for_node(node)
                    except Exception as e:
                        import traceback
                        traceback.print_exc()
                
                QTimer.singleShot(300, show_compare_dialog)

            # Двойной клик по версии - открыть локально
            def on_item_double_clicked(_item):
                _open_selected_local()
            lst.itemDoubleClicked.connect(on_item_double_clicked)

            btns = QDialogButtonBox(QDialogButtonBox.Close, parent=dlg)
            btns.rejected.connect(dlg.reject)
            btns.accepted.connect(dlg.accept)
            lay.addWidget(btns)

            btn_open_pc = QPushButton(t("version.open_on_pc"), dlg)
            btn_open_pc.clicked.connect(_open_selected_local)
            btns.addButton(btn_open_pc, QDialogButtonBox.ActionRole)

            if name.lower().endswith('.pdf'):
                btn_compare = QPushButton(t("version.compare_pdf"), dlg)
                btn_compare.clicked.connect(_compare_selected_pdf)
                btns.addButton(btn_compare, QDialogButtonBox.ActionRole)

            dlg.resize(400, 380)
            dlg.exec()
        except Exception:
            QMessageBox.warning(self, t("version.title"), t("version.open_failed"))


    def _has_at_least_two_versions(self, node: dict) -> bool:
        """True, если у файла есть минимум 2 версии."""
        try:
            if not isinstance(node, dict) or str(node.get("type", "")).lower() != "file":
                return False
            doc_id = node.get("id")
            if not doc_id:
                return False
            self.status.showMessage(t("version.checking"))
            versions = self.api.get_document_versions(doc_id)
        finally:
            try:
                self.status.clearMessage()
            except Exception:
                pass
        if isinstance(versions, dict):
            versions = versions.get("versions") or []
        return len(list(versions or [])) >= 2

    def _on_compare_clicked(self):
        """Выбор файла-источника и открытие окна выбора двух версий."""
        # приоритет - отмеченные галочками, затем одиночное выделение
        try:
            items = self.get_checked_visible_items()
        except Exception:
            items = []
        if not items:
            sel = self.selected_item()
            if sel:
                items = [sel]
        # Быстро: без лишних API-запросов берём первый файл из набора
        target = next((it for it in items
                       if isinstance(it, dict) and str(it.get("type", "")).lower() == "file"),
                      None)
        if not target:
            from PySide6.QtCore import QTimer
            
            def show_select_file_error():
                try:
                    parent = self
                    if parent and hasattr(parent, 'window'):
                        parent = parent.window()
                    if parent:
                        QMessageBox.information(parent, t("version.compare"), t("version.select_file"))
                except Exception:
                    pass
            
            QTimer.singleShot(200, show_select_file_error)
            return
        self._show_compare_versions_for_node(target)


    def _show_compare_versions_for_node(self, node: dict):
        """Диалог: слева версия 1, справа версия 2, внизу - Сравнить/Отмена."""
        if not isinstance(node, dict) or str(node.get("type", "")).lower() != "file":
            from PySide6.QtCore import QTimer
            
            def show_select_file_error():
                try:
                    parent = self
                    if parent and hasattr(parent, 'window'):
                        parent = parent.window()
                    if parent:
                        QMessageBox.information(parent, t("version.compare"), t("version.select_file"))
                except Exception:
                    pass
            
            QTimer.singleShot(200, show_select_file_error)
            return

        doc_id = node.get("id")
        name   = node.get("fileName") or node.get("name") or node.get("title") or "файл"
        if not doc_id:
            from PySide6.QtCore import QTimer
            
            def show_id_error():
                try:
                    parent = self
                    if parent and hasattr(parent, 'window'):
                        parent = parent.window()
                    if parent:
                        QMessageBox.information(parent, t("version.compare"), t("version.id_not_defined"))
                except Exception:
                    pass
            
            QTimer.singleShot(200, show_id_error)
            return

        # 1) получаем версии и нормализуем список
        self.status.showMessage(t("common.loading"))
        versions = self.api.get_document_versions(doc_id, force=True)
        self.status.clearMessage()

        base_file_name = name
        if isinstance(versions, dict):
            base_file_name = versions.get("file_name") or versions.get("fileName") or name
            versions = list(versions.get("versions") or [])
        else:
            versions = list(versions or [])

        if len(versions) < 2:
            from PySide6.QtCore import QTimer
            
            version_count = len(versions)
            if version_count > 0:
                form = t("version.only_one_form") if version_count == 1 else t("version.only_two_form")
                error_msg = t("version.only_one", name=name, count=version_count, form=form)
            else:
                error_msg = t("version.none", name=name)
            
            def show_versions_error():
                try:
                    parent = self
                    if parent and hasattr(parent, 'window'):
                        parent = parent.window()
                    if parent:
                        QMessageBox.information(parent, t("version.compare_title"), error_msg)
                except Exception:
                    pass
            
            QTimer.singleShot(200, show_versions_error)
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(f"{t('version.compare_title')} - {name}")
        # Set title bar theme based on current theme
        current_theme = getattr(self, "_current_theme", THEME_LIGHT)
        is_dark = current_theme == THEME_DARK
        _set_window_theme_dark(dlg, dark=is_dark)
        root = QVBoxLayout(dlg)

        # 2) сплиттер: слева список v1, справа список v2
        split = QSplitter(Qt.Horizontal, dlg)

        def _make_side(title_text: str):
            w   = QWidget(dlg)
            lay = QVBoxLayout(w); lay.setContentsMargins(0,0,0,0)
            title = QLabel(title_text, w)
            lst   = QListWidget(w)
            lst.setSelectionMode(QAbstractItemView.SingleSelection)
            lay.addWidget(title)
            lay.addWidget(lst, 1)
            return w, lst

        left_w,  lst1 = _make_side(t("version.select_v1"))
        right_w, lst2 = _make_side(t("version.select_v2"))
        for _lst in (lst1, lst2):
            _lst.setUniformItemSizes(True)
            _lst.setAlternatingRowColors(False)
            _lst.setMouseTracking(True)
            _lst.viewport().setMouseTracking(True)
            _lst.setFrameShape(QFrame.NoFrame)
            _lst.setStyleSheet("""
                QListWidget {
                    background: transparent;
                    border: none;
                    outline: none;
                }
                QListWidget::item {
                    border-radius: 8px;
                    padding: 6px 10px;
                    margin: 2px 4px;
                }
                QListWidget::item:hover {
                    background: #FFE3C2;
                    color: #000000;
                }
                QListWidget::item:selected {
                    background: #FFC37A;
                    color: #000000;
                }
                QListWidget::item:selected:hover {
                    background: #FFCA91;
                    color: #000000;
                }
            """)
            _lst.setViewportMargins(4, 4, 4, 4)


        # наполнение обоих списков одинаковыми элементами
        def _add_items(lst_widget: QListWidget):
            for i, v in enumerate(versions, 1):
                try:
                    ver_no = v.get("version") or v.get("versionNumber") or v.get("versionId") or i + 1
                    when_raw = v.get("created_ts") or v.get("createdTs") or v.get("createTime") or v.get("createdAt") or v.get("modifTime") or v.get("updatedAt")
                    ts = 0.0
                    if when_raw:
                        ts = parse_date_like(str(when_raw))
                    if ts > 0:
                        when = _user_display_datetime(ts)
                    who  = v.get("createdBy") or v.get("modifiedBy") or ""
                    label = f"v{ver_no}  {when}  {who}".strip()
                except Exception:
                    label = f"v{i}"
                it = QListWidgetItem(label)
                it.setData(Qt.UserRole, v)
                lst_widget.addItem(it)

        lst1.setUpdatesEnabled(False); lst2.setUpdatesEnabled(False)
        _add_items(lst1); _add_items(lst2)
        lst1.setUpdatesEnabled(True);  lst2.setUpdatesEnabled(True)


        split.addWidget(left_w)
        split.addWidget(right_w)
        split.setSizes([1, 1])
        root.addWidget(split, 1)

        # 3) нижняя панель кнопок: [Сравнить] ......... [Отмена]
        row = QHBoxLayout()
        btn_compare = QPushButton(t("version.compare_button"), dlg)
        btn_cancel  = QPushButton(t("common.cancel"), dlg)
        btn_compare.setEnabled(False)
        btn_compare.setProperty("chip", False)
        btn_compare.setProperty("secondary", True)
        btn_cancel.setProperty("chip", False)
        row.addWidget(btn_compare)
        row.addStretch(1)
        row.addWidget(btn_cancel)
        root.addLayout(row)

        # включаем «Сравнить», когда есть выбор в обоих списках
        def _update_ok():
            btn_compare.setEnabled(bool(lst1.selectedItems()) and bool(lst2.selectedItems()))
        lst1.itemSelectionChanged.connect(_update_ok)
        lst2.itemSelectionChanged.connect(_update_ok)

        # вспомогательные функции для скачивания и запуска сравнения
        def _safe_ver_filename(base_name: str, ver: dict) -> str:
            base = _sanitize_filename(base_name or name)
            stem, ext = os.path.splitext(base)
            ver_no = ver.get("version") or ver.get("versionNumber") or ver.get("versionId") or ""
            when_raw = ver.get("created_ts") or ver.get("createdTs") or ver.get("createTime") or ver.get("createdAt") or ver.get("modifTime") or ver.get("updatedAt")
            ts = 0.0
            if when_raw:
                ts = parse_date_like(str(when_raw))
            parts = [stem]
            if ver_no != "":
                parts.append(f"v{ver_no}")
            if ts > 0:
                parts.append(datetime.fromtimestamp(ts).strftime("%Y%m%d_%H%M%S"))
            fname = " - ".join(parts) + ext
            try:
                os.makedirs(DOWNLOAD_DIR, exist_ok=True)
                full = os.path.join(DOWNLOAD_DIR, fname)
                if os.path.exists(full):
                    fname = self._unique_name(DOWNLOAD_DIR, fname)
            except Exception:
                pass
            return fname

        def _download_version_local(ver: dict) -> str:
            file_id = ver.get("document_id") or ver.get("id")
            if not file_id:
                return ""
            fname = _safe_ver_filename(base_file_name, ver)

            self._set_progress_visible(True)
            self.progress.setRange(0, 0)
            QApplication.processEvents()
            wait = WaitDialog(t("version.wait_download"), self)
            try:
                wait.show(); QApplication.processEvents()
            except Exception:
                wait = None

            def _cb(done: int, total: int):
                try:
                    self.progress.setRange(0, 100)
                    self.progress.setValue(int(done * 100 / max(1, total)))
                    QApplication.processEvents()
                except Exception:
                    pass

            try:
                local_path = self.api.download_file(file_id, fname, progress_cb=_cb)
            finally:
                self._set_progress_visible(False)
                try:
                    if wait:
                        wait.set_done(t("version.download_complete"))
                except Exception:
                    pass
            return local_path or ""
        

        def _download_pair(verA: dict, verB: dict) -> tuple[str, str]:
            """Скачивает обе версии параллельно - одно окно прогресса - быстрее открываем сравнение."""
            # Готовим имена файлов
            fnameA = _safe_ver_filename(name, verA)
            fnameB = _safe_ver_filename(name, verB)
            if fnameA == fnameB:
                stem, ext = os.path.splitext(fnameB)
                fnameB = f"{stem}_B{ext}"

            file_id_a = verA.get("document_id") or verA.get("id")
            file_id_b = verB.get("document_id") or verB.get("id")

            pathA, pathB = "", ""

            import threading, time
            wait = WaitDialog(t("version.downloading_two"), self)
            try:
                wait.show(); QApplication.processEvents()
            except Exception:
                wait = None

            def _dl_a():
                nonlocal pathA
                try:
                    pathA = self.api.download_file(file_id_a, fnameA)
                except Exception:
                    pathA = ""

            def _dl_b():
                nonlocal pathB
                try:
                    pathB = self.api.download_file(file_id_b, fnameB)
                except Exception:
                    pathB = ""

            t1 = threading.Thread(target=_dl_a, daemon=True)
            t2 = threading.Thread(target=_dl_b, daemon=True)
            t1.start(); t2.start()
            while t1.is_alive() or t2.is_alive():
                QApplication.processEvents()
                time.sleep(0.01)

            try:
                if wait:
                    wait.set_done(t("common.done"))
            except Exception:
                pass

            return (pathA or ""), (pathB or "")

        def _do_compare():
            a_it = lst1.selectedItems()
            b_it = lst2.selectedItems()
            if not a_it or not b_it:
                return
            verA = a_it[0].data(Qt.UserRole) or {}
            verB = b_it[0].data(Qt.UserRole) or {}
            pathA, pathB = _download_pair(verA, verB)
            if not pathA or not pathB:
                from PySide6.QtCore import QTimer
                
                def show_download_error():
                    try:
                        QMessageBox.warning(dlg, t("version.compare"), t("version.compare_failed"))
                    except Exception:
                        pass
                
                QTimer.singleShot(200, show_download_error)
                return
            extA = os.path.splitext(pathA)[1].lower()
            extB = os.path.splitext(pathB)[1].lower()
            if extA != ".pdf" or extB != ".pdf":
                from PySide6.QtCore import QTimer
                def show_info_and_open():
                    try:
                        QMessageBox.information(dlg, t("version.compare"), t("version.pdf_only"))
                        open_in_os(pathA); open_in_os(pathB)
                    except Exception:
                        pass
                QTimer.singleShot(200, show_info_and_open)
                return
            # Use integrated PDF_Compare window - defer to avoid Qt conflicts
            from PySide6.QtCore import QTimer
            def open_compare():
                try:
                    dlg.accept()
                    self.open_pdf_compare_window(pathA, pathB)
                except Exception as e:
                    import traceback
                    traceback.print_exc()
            QTimer.singleShot(200, open_compare)

        btn_compare.clicked.connect(_do_compare)
        btn_cancel.clicked.connect(dlg.reject)

        dlg.resize(900, 520)
        dlg.exec()

    def open_pdf_compare_window(self, pdf1_path: str = "", pdf2_path: str = ""):
        """Open integrated PDF_Compare window for comparing two PDF files.
        
        Args:
            pdf1_path: Path to first PDF file (optional)
            pdf2_path: Path to second PDF file (optional)
        """
        if PDFCompareWindow is None:
            from PySide6.QtCore import QTimer
            
            def show_pdf_module_error():
                try:
                    QMessageBox.warning(
                        self, 
                        t("pdf.title"), 
                        t("pdf.module_not_available")
                    )
                except Exception:
                    pass
            
            QTimer.singleShot(200, show_pdf_module_error)
            return
        
        try:
            # Get current theme from main app
            current_theme = getattr(self, "_current_theme", THEME_LIGHT)
            is_dark = current_theme == THEME_DARK
            
            # Create PDF comparison window as child of main window
            pdf_win = PDFCompareWindow()
            pdf_win.setWindowModality(Qt.NonModal)  # Allow interaction with main window
            # Keep window on top of other windows
            pdf_win.setWindowFlags(pdf_win.windowFlags() | Qt.WindowStaysOnTopHint)
            
            # Apply theme to PDF window if functions available
            if pdf_apply_style is not None:
                pdf_apply_style(QApplication.instance(), dark=is_dark, target=pdf_win)
            if pdf_set_window_theme is not None:
                pdf_set_window_theme(pdf_win, dark=is_dark)

            # Connect theme toggled signal from PDF_Compare to main window theme handler
            if hasattr(pdf_win, 'theme_switch') and hasattr(pdf_win.theme_switch, 'toggledTheme'):
                pdf_win.theme_switch.toggledTheme.connect(
                    lambda theme: self._on_theme_toggled(dark=(theme == THEME_DARK))
                )
            
            # Load PDFs if paths provided
            if pdf1_path and os.path.exists(pdf1_path):
                pdf_win.open_pdf_path(1, pdf1_path)
                # Mark as temp file for cleanup if it's in downloads dir
                if pdf1_path.startswith(DOWNLOAD_DIR):
                    pdf_win._temp_files_to_cleanup.append(pdf1_path)
            if pdf2_path and os.path.exists(pdf2_path):
                pdf_win.open_pdf_path(2, pdf2_path)
                # Mark as temp file for cleanup if it's in downloads dir
                if pdf2_path.startswith(DOWNLOAD_DIR):
                    pdf_win._temp_files_to_cleanup.append(pdf2_path)
            
            # If both PDFs loaded, switch to comparison mode
            if pdf1_path and pdf2_path:
                idx = pdf_win.cmb_mode.findText(t("pdf.compare"))
                if idx >= 0:
                    pdf_win.cmb_mode.setCurrentIndex(idx)
            
            # Apply icons after window is fully initialized
            QtCore.QTimer.singleShot(50, pdf_win._apply_toolbar_icons)
            
            # Show window
            pdf_win.show()
            
            # Keep reference to prevent garbage collection
            if not hasattr(self, '_pdf_compare_windows'):
                self._pdf_compare_windows = []
            self._pdf_compare_windows.append(pdf_win)
            
            # Clean up closed windows
            def _is_widget_visible(widget):
                try:
                    return widget.isVisible()
                except RuntimeError:
                    return False

            def cleanup_closed():
                if hasattr(self, '_pdf_compare_windows'):
                    self._pdf_compare_windows = [w for w in self._pdf_compare_windows if _is_widget_visible(w)]
            
            pdf_win.destroyed.connect(cleanup_closed)
            
        except Exception as e:
            from PySide6.QtCore import QTimer
            
            def show_error():
                try:
                    QMessageBox.critical(
                        self, 
                        t("common.error"), 
                        t("pdf.cannot_open", error=str(e))
                    )
                except Exception:
                    pass
            
            QTimer.singleShot(200, show_error)

    # Upload / Download / Open
    # --- Notifications: UI + subscriptions ---
    def _init_notifications_ui(self) -> None:
        try:
            # УБРАНО: Глобальная кнопка уведомлений сверху
            # Оставляем только уведомления рядом с папками (в контекстном меню)
            
            # Просто инициализируем структуры данных без создания UI-элементов
            self._notifications = []
            self._subscriptions = {}

            # Disable legacy per-folder polling: it can overwrite baseline states and it
            # does not reliably track deletions.
            try:
                if hasattr(self, "_notify_timer") and self._notify_timer:
                    self._notify_timer.stop()
            except Exception:
                pass

            # Main notifications checker (cloud-based: add/modify/delete)
            # Initialize notifications timer with configurable interval
            try:
                # Load notification interval from settings (default: 5 minutes = 300 seconds)
                try:
                    settings = load_settings()
                    notification_interval = settings.get("sync", {}).get("notification_refresh_interval", 300)
                except Exception:
                    notification_interval = 300
                
                if not hasattr(self, "_notifications_timer") or self._notifications_timer is None:
                    self._notifications_timer = QTimer(self)
                    self._notifications_timer.timeout.connect(self._check_notifications)
                self._notifications_timer.setInterval(notification_interval * 1000)
                if not self._notifications_timer.isActive():
                    self._notifications_timer.start()
                # Kick off an early check so users don't have to wait a full interval
                # (also helps initialize legacy empty baselines).
                try:
                    QTimer.singleShot(2000, self._check_notifications)
                except Exception:
                    pass
            except Exception:
                pass


            # System tray notifications (Windows/macOS/Linux where supported)
            try:
                from PySide6.QtWidgets import QSystemTrayIcon
                if not hasattr(self, "_notify_tray") or getattr(self, "_notify_tray") is None:
                    self._notify_tray = QSystemTrayIcon(self)
                    try:
                        self._notify_tray.setIcon(self._themed_icon(ALARM_ICON_PATH))
                    except Exception:
                        self._notify_tray.setIcon(QIcon(ALARM_ICON_PATH))
                    self._notify_tray.setToolTip(APP_TITLE)
                    if QSystemTrayIcon.isSystemTrayAvailable():
                        self._notify_tray.show()
            except Exception:
                pass
            
            # Auto-refresh timer при неактивности (использует настройку auto_sync_interval)
            self._auto_refresh_timer = QTimer(self)
            try:
                settings = load_settings()
                sync_interval = settings.get("sync", {}).get("auto_sync_interval", 300)
            except Exception:
                sync_interval = 300
            self._auto_refresh_timer.setInterval(sync_interval * 1000)
            self._auto_refresh_timer.timeout.connect(self._on_auto_refresh_timeout)
            self._auto_refresh_timer.start()
            
            # Отслеживание последней активности пользователя
            self._last_user_activity = time.time()
            
            # Установить event filter для отслеживания активности
            self.installEventFilter(self)
        except Exception:
            pass

    # Notification handlers are injected from larix_nexus.ui.notification_handlers

    def _on_auto_refresh_timeout(self) -> None:
        """Автоматическое обновление при неактивности пользователя (5 минут)."""
        try:
            # Проверяем, прошло ли действительно 5 минут без активности
            current_time = time.time()
            last_activity = getattr(self, '_last_user_activity', current_time)
            time_since_activity = current_time - last_activity
            
            # Если с последней активности прошло менее 5 минут, пропускаем
            if time_since_activity < 5 * 60:
                return
            
            # Проверяем, есть ли загруженный проект
            pid = self.current_project_id()
            if not pid:
                return
            
            # Сохраняем текущее состояние файлов перед обновлением
            old_files_current = getattr(self, 'files_current', [])
            
            # Выполняем обновление
            try:
                self.status.showMessage(t("status.auto_refresh"), 2000)
                self.soft_refresh_and_restore_view()
                
                # Если после обновления список файлов стал пустым, а раньше был не пуст - восстанавливаем
                new_files_current = getattr(self, 'files_current', [])
                if old_files_current and not new_files_current:
                    self.files_current = old_files_current
                    self.update_table()
            except Exception as e:
                pass
        except Exception:
            pass

        

    def _on_search_recursive_toggled(self, on: bool) -> None:
        """Триггер/логика: переключить `глубокий поиск` и обновить UI/фильтры."""
        self._search_recursive = bool(on)

        # UI
        try:
            # 1) Обновить иконку у действия в поле поиска
            if on:
                self._act_search_recursive.setIcon(self._tinted_icon(INSERT_ICON_PATH, QColor("#F7921E")))
            else:
                self._act_search_recursive.setIcon(self._themed_icon(INSERT_ICON_PATH))

            # 2) Обновить property у виджета поиска (для стилей)
            self.search.setProperty("searchDeep", on)
            self.search.style().unpolish(self.search)
            self.search.style().polish(self.search)
        except Exception:
            pass

        # Пересчитать фильтры таблицы, чтобы учесть новый режим
        try:
            self.apply_table_filters()
        except Exception:
            pass

    # Диаграмма
        pass
     # --- Notifications: cloud polling ---
    def _cloud_state_for_folder(self, project_id: int | str, folder_id: int | str) -> dict[str, str]:
        """Собирает состояние папки в облаке: key -> timestamp (modifTime|createTime)."""
        try:
            tree = self.api.list_folders(project_id, force=True) or []
        except Exception:
            tree = []
        try:
            if normalize_id(folder_id) == normalize_id(project_id):
                node = {"type": "folder", "id": normalize_id(project_id), "children": tree, "name": "Корень"}
            else:
                node = self._find_folder_in_tree(tree or [], normalize_id(folder_id))
        except Exception:
            node = None
        if not isinstance(node, dict):
            return {}
        files = []
        try:
            files = self._collect_cloud_files(node, "", True) or []
        except Exception:
            files = []
        out: dict[str, str] = {}
        for f in files:
            try:
                rel = str(f.get("rel_path") or "").strip("/")
                name = str(f.get("name") or "").strip()
                key = f"{rel}/{name}".strip("/")
                raw = f.get("modifTime") or f.get("createTime") or ""
                out[key] = str(raw)
            except Exception:
                continue
        return out

    def _poll_subscriptions(self) -> None:
        """Проверяет подписанные папки только по облаку и включает колокольчик при изменениях."""
        try:
            subs = getattr(self, "_subscriptions", {}) or {}
            if not subs:
                return
            any_changed = False
            total_changes = 0
            changed_folders = []
            
            for fid, cfg in list(subs.items()):
                try:
                    try:
                        pf = int(fid)
                    except (ValueError, TypeError):
                        pf = fid
                except Exception:
                    continue
                try:
                    proj_id = cfg.get("project_id" or self.current_project_id() or 0)
                except Exception:
                    proj_id = 0
                if not proj_id:
                    continue

                # Новое состояние из облака
                new_state = self._cloud_state_for_folder(proj_id, pf) or {}
                old_state = cfg.get("state") or {}

                # Сравнение
                added = [k for k in new_state.keys() if k not in old_state]
                modified = [k for k in new_state.keys() if k in old_state and str(new_state[k]) != str(old_state[k])]
                changed = added + modified

                # Обновляем baseline в любом случае
                cfg["state"] = new_state

                if changed:
                    any_changed = True
                    total_changes += len(changed)
                    cfg["pending"] = True
                    folder_title = str(cfg.get("title") or t("folder.title", name=pf))
                    changed_folders.append(folder_title)
                    
                    # Бейдж на дереве
                    try:
                        it = self.folder_item_by_id.get(normalize_id(pf))
                        if it is not None:
                            it.setData(0, NOTIFY_ROLE, True)
                    except Exception:
                        pass
                    try:
                        self.tree.viewport().update()
                    except Exception:
                        pass

                    # Запись в список уведомлений (для меню колокольчика)
                    try:
                        import os
                        names = [os.path.basename(k) for k in changed[:5]]
                        more = len(changed) - 5
                        suffix = "…" if more > 0 else ""
                        text = ", ".join(names) + suffix if names else t("notifications.changes_found", count=0)
                        self._notifications.append({
                            "title": folder_title,
                            "text": text,
                            "path": "",
                        })
                    except Exception:
                        pass
                    
                    # Обновить persistent storage с новым состоянием
                    try:
                        folder_path = cfg.get("title", "")
                        # Преобразуем state обратно в формат file_state для сохранения
                        files_for_storage = []
                        for file_key, timestamp in new_state.items():
                            file_name = os.path.basename(file_key)
                            rel_dir = os.path.dirname(file_key).replace("\\", "/").strip("/")
                            base_path = str(folder_path or "")
                            if rel_dir:
                                path = f"{base_path}/{rel_dir}" if base_path else rel_dir
                            else:
                                path = base_path
                            files_for_storage.append({
                                "name": file_name,
                                "path": path,
                                "updatedAt": timestamp,
                                "id": file_key
                            })
                        save_folder_notification(proj_id, pf, folder_path, files_for_storage)
                    except Exception:
                        pass

            if any_changed:
                try:
                    self._update_notify_icon()
                except Exception:
                    pass
                try:
                    self._build_notify_menu()
                except Exception:
                    pass
                # Показать сообщение в статус-баре
                try:
                    if len(changed_folders) == 1:
                        msg = f"🔔 Обнаружены изменения в папке «{changed_folders[0]}»: {total_changes} файл(ов)"
                    else:
                        msg = f"🔔 Обнаружены изменения в {len(changed_folders)} папках: {total_changes} файл(ов)"
                    self.status.showMessage(msg, 5000)
                except Exception:
                    pass
        except Exception:
            pass

    # --- Диалог логина ---

def enable_msgbox_autosize(app: QApplication) -> None:
    """Installs a single event filter that:
    - включает перенос строк у текстов QMessageBox;
    - подбирает минимальную ширину по самой длинной строке;
    - ограничивает ширину 70% экрана и растягивает окно по высоте.
    Работает для information/warning/critical/question и для любых вручную созданных QMessageBox.
    """
    from PySide6 import QtCore, QtWidgets

    class _MsgBoxAutosizer(QtCore.QObject):
        def eventFilter(self, obj, ev):
            try:
                if isinstance(obj, QtWidgets.QMessageBox) and ev.type() in (QtCore.QEvent.Show, QtCore.QEvent.ShowToParent):
                    mb = obj
                    # 1) перенос и селект для основных лейблов
                    labels = []
                    for name in ("qt_msgbox_label", "qt_msgbox_informativelabel"):
                        lbl = mb.findChild(QtWidgets.QLabel, name)
                        if lbl is not None:
                            try:
                                lbl.setWordWrap(True)
                                lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
                                sp = lbl.sizePolicy()
                                sp.setHorizontalPolicy(QSizePolicy.Preferred)
                                lbl.setSizePolicy(sp)
                            except Exception:
                                pass
                            labels.append(lbl)
                    # 2) расчёт нужной ширины
                    minw = 360
                    try:
                        fm = mb.fontMetrics()
                        parts = []
                        for s in (mb.text(), mb.informativeText()):
                            if s:
                                parts.extend(str(s).replace("\r", "").split("\n"))
                        longest = 0
                        for s in parts or [""]:
                            w = fm.horizontalAdvance(s)
                            if w > longest:
                                longest = w
                        icon_w = QApplication.style().pixelMetric(QStyle.PM_MessageBoxIconSize)
                        padding = 160  # поля + кнопки
                        scr = QApplication.primaryScreen()
                        cap = int((scr.availableGeometry().width() if scr else 1920) * 0.7)
                        minw = max(360, min(longest + icon_w + padding, cap))
                        mb.setMinimumWidth(minw)
                        # чтобы перенос действительно сработал
                        for lbl in labels:
                            try:
                                lbl.setMaximumWidth(minw - 120)
                            except Exception:
                                pass
                    except Exception:
                        pass

                    # 3) сдвиг текста к верху (если helper есть)
                    try:
                        move_messagebox_text_to_top(mb, TEXT_TOP_Y)  # type: ignore[name-defined]
                    except Exception:
                        pass

                    # 4) финальная подгонка размеров
                    try:
                        mb.layout().setSizeConstraint(QLayout.SetMinimumSize)
                        mb.adjustSize()
                        hint = mb.sizeHint()
                        mb.resize(max(hint.width(), minw), max(hint.height(), 140))
                    except Exception:
                        pass
            except Exception:
                pass
            return super().eventFilter(obj, ev)

    try:
        filt = _MsgBoxAutosizer(app)
        app.installEventFilter(filt)
        setattr(app, "_msgbox_autosizer", filt)  # держим ссылку
    except Exception:
        pass


# ============================================================================
# SYNC BADGE DELEGATE - Draws sync and notification badges on tree items
# ============================================================================

def nik_icon(name: str) -> QtGui.QIcon:
    """Load themed icon for the sync badge (white in dark theme)."""
    if name != "sync":
        return QtGui.QIcon()
    p = rsrc_path("icon", "sync.png")
    if not os.path.exists(p):
        return QtGui.QIcon()
    try:
        if _is_dark_mode():
            return load_white_icon(p)
    except Exception:
        pass
    return QtGui.QIcon(p)


def _tint_pixmap(pix: QPixmap, color: QColor) -> QPixmap:
    """Tint a pixmap with the given color."""
    if pix.isNull():
        return pix
    tinted = QPixmap(pix.size())
    tinted.fill(Qt.transparent)
    painter = QPainter(tinted)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.drawPixmap(0, 0, pix)
    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    painter.fillRect(tinted.rect(), color)
    painter.end()
    return tinted


class _SyncBadgeRightDelegate(MenuLikeTreeDelegate):
    """Tree delegate that draws notification and sync badges to right of text
    with a small slide/fade animation when badge state changes.

    The delegate listens to model dataChanged and animates indexes where
    NOTIFY_ROLE or SYNC_ROLE toggled. Animation progress is stored per
    persistent index and used in paint() to shift badges from inside the
    text to their final tabbed position to the right.
    """
    def __init__(self, parent=None, inner_delegate=None):
        super().__init__(parent, inner_delegate)
        self._duration_ms = 220
        self._progress: dict[QtCore.QPersistentModelIndex, float] = {}
        self._anims: dict[QtCore.QPersistentModelIndex, QtCore.QVariantAnimation] = {}
        self._last_has_badge: dict[QtCore.QPersistentModelIndex, bool] = {}

        # Try to connect to model signals to detect toggles
        try:
            view: QtWidgets.QTreeView | None = parent if isinstance(parent, QtWidgets.QTreeView) else None
            model = view.model() if view else None
            if model is not None:
                model.dataChanged.connect(self._on_data_changed)
                model.rowsRemoved.connect(self._cleanup_removed)
                model.modelReset.connect(self._clear_anims)
        except Exception:
            pass

    def _clear_anims(self) -> None:
        try:
            for a in list(self._anims.values()):
                try:
                    a.stop()
                except Exception:
                    pass
            self._anims.clear()
            self._progress.clear()
            self._last_has_badge.clear()
        except Exception:
            pass

    def _cleanup_removed(self, *args, **kwargs) -> None:
        """Wrapper to call global cleanup_removed function."""
        try:
            view = self.parent()
            if view:
                cleanup_removed(view)
        except Exception:
            pass

    def _start_anim(self, idx: QtCore.QModelIndex, show: bool) -> None:
        try:
            pidx = QtCore.QPersistentModelIndex(idx)
            # Reuse existing animation when possible
            old = self._anims.get(pidx)
            if old is not None:
                try:
                    old.stop()
                except Exception:
                    pass
            # Create new animation 0->1 for show, 1->0 for hide
            anim = QtCore.QVariantAnimation(self)
            anim.setStartValue(0.0 if show else 1.0)
            anim.setEndValue(1.0 if show else 0.0)
            anim.setDuration(self._duration_ms)
            anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)
            def _on_val(val):
                self._progress[pidx] = float(val)
                view = self.parent()
                if isinstance(view, QtWidgets.QAbstractItemView):
                    r = view.visualRect(idx)
                    if r.isValid():
                        view.viewport().update(r)
                    else:
                        view.viewport().update()
            anim.valueChanged.connect(_on_val)
            def _on_fin():
                self._progress[pidx] = float(anim.endValue()) if hasattr(anim, 'endValue') else (1.0 if show else 0.0)
                # keep final value but drop animation object
                self._anims.pop(pidx, None)
            anim.finished.connect(_on_fin)
            self._anims[pidx] = anim
            anim.start()
        except Exception:
            pass

    def _on_data_changed(self, topLeft: QtCore.QModelIndex, bottomRight: QtCore.QModelIndex, roles: list[int] | None = None) -> None:
        try:
            if roles is not None and not any(r in roles for r in (NOTIFY_ROLE, SYNC_ROLE)):
                return
            model = topLeft.model()
            view = self.parent()
            if not isinstance(view, QtWidgets.QAbstractItemView):
                return
            for r in range(topLeft.row(), bottomRight.row() + 1):
                idx = model.index(r, topLeft.column(), topLeft.parent())
                if not idx.isValid():
                    continue
                pidx = QtCore.QPersistentModelIndex(idx)
                
                # Check current badge state (ANY badge counts)
                # ВАЖНО: проверяем на `is not None`, так как False - валидное значение для NOTIFY_ROLE
                sync_val = idx.data(SYNC_ROLE)
                notify_val = idx.data(NOTIFY_ROLE)
                has_badge = (sync_val is not None and sync_val) or (notify_val is not None)
                
                # Get previous state (default to False if first time seeing this index)
                last = self._last_has_badge.get(pidx, False)
                
                # Only animate when badge state CHANGES (appears or disappears)
                if has_badge != last:
                    self._last_has_badge[pidx] = has_badge
                    self._start_anim(idx, show=has_badge)
                else:
                    # State unchanged - just update stored value without animation
                    self._last_has_badge[pidx] = has_badge
        except Exception:
            pass

    def paint(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex) -> None:
        # MenuLikeTreeDelegate (base class) handles hover/selected/pressed background
        # So we just call super().paint() first, then draw badges on top
        super().paint(painter, option, index)
        
        # Check which badges to draw: sync and notifications (INDEPENDENT)
        try:
            # Notifications badge (do not tint) - INDEPENDENT
            notify_pixmap = None
            try:
                notify_state = index.data(NOTIFY_ROLE)
                is_dark = False
                try:
                    is_dark = _is_dark_mode()
                except Exception:
                    is_dark = False
                
                # None - не подписан - не показываем; False - подписан, изменений нет - alarm.png; True - есть изменения - alarm(1).png
                if notify_state is True:
                    _notify_icon = load_white_icon(ALARM1_ICON_PATH) if is_dark else QtGui.QIcon(ALARM1_ICON_PATH)
                    notify_pixmap = _notify_icon.pixmap(16, 16) if _notify_icon else None
                elif notify_state is False:
                    _notify_icon = load_white_icon(ALARM_ICON_PATH) if is_dark else QtGui.QIcon(ALARM_ICON_PATH)
                    notify_pixmap = _notify_icon.pixmap(16, 16) if _notify_icon else None
            except Exception:
                pass

            # Sync badge (theme-aware via nik_icon) - INDEPENDENT
            sync_pixmap = None
            try:
                if bool(index.data(SYNC_ROLE)):
                    _sync_icon = nik_icon("sync")
                    if not _sync_icon.isNull():
                        pm = _sync_icon.pixmap(16, 16)
                        try:
                            if _is_dark_mode() and not pm.isNull():
                                pm = _tint_pixmap(pm, QColor(Qt.white))
                        except Exception:
                            pass
                        sync_pixmap = pm
            except Exception:
                pass
            
            # Normalize null pixmaps
            try:
                if isinstance(notify_pixmap, QPixmap) and notify_pixmap.isNull():
                    notify_pixmap = None
            except Exception:
                pass
            try:
                if isinstance(sync_pixmap, QPixmap) and sync_pixmap.isNull():
                    sync_pixmap = None
            except Exception:
                pass

            # If no badges to draw, return early
            if notify_pixmap is None and sync_pixmap is None:
                return
            
            # Prepare option copy and compute text rect
            opt = QtWidgets.QStyleOptionViewItem(option)
            # Ensure same style metrics/contents as default delegate (text, icon, etc.)
            try:
                self.inner.initStyleOption(opt, index)  # type: ignore[attr-defined]
            except Exception:
                pass
            widget = getattr(option, 'widget', None)
            style = widget.style() if widget else QtWidgets.QApplication.style()
            text_rect = style.subElementRect(QtWidgets.QStyle.SE_ItemViewItemText, opt, widget)
            try:
                deco_rect = style.subElementRect(QtWidgets.QStyle.SE_ItemViewItemDecoration, opt, widget)
            except Exception:
                deco_rect = QtCore.QRect()
            # Figure out text that was drawn (elided)
            try:
                fm = QtGui.QFontMetrics(opt.font)
            except Exception:
                fm = painter.fontMetrics()
            elide_mode = getattr(opt, 'textElideMode', QtCore.Qt.ElideRight)
            drawn_text = fm.elidedText(opt.text, elide_mode, max(0, text_rect.width()))
            text_width = fm.horizontalAdvance(drawn_text)
            
            # Badge size relative to row height
            original_rect = QtCore.QRect(opt.rect)
            badge_size = min(max(12, original_rect.height() - 4), 20)

            # Make the notification bell slightly smaller than the sync badge
            # while keeping the same layout slots/spacing.
            notify_draw_size = max(10, min(badge_size, int(badge_size * 0.85)))
            
            # Tab spacing: один таб между текстом и первым значком, один таб между значками
            tab_px = 8
            
            # Calculate positions for INDEPENDENT badges
            # Layout: Text [TAB] Sync(if exists) [TAB] Notify(if exists)
            
            # Start position after text
            base_x = text_rect.x() + text_width + tab_px
            
            # Do not go left of decoration (folder) to avoid overlap in edge cases
            if deco_rect.isValid():
                base_x = max(base_x, deco_rect.right() + 4)
            
            # Calculate total width needed for badges
            total_badge_width = 0
            if sync_pixmap:
                total_badge_width += badge_size + tab_px
            if notify_pixmap:
                total_badge_width += badge_size
            
            # Ensure badges stay within the visible item rect (avoid clipping)
            if total_badge_width > 0:
                try:
                    right_pad = 4
                    max_right = original_rect.right() - right_pad
                    base_x = min(base_x, max_right - total_badge_width + 1)
                except Exception:
                    pass

                # Do not go left of the decoration (folder icon)
                if deco_rect.isValid():
                    base_x = max(base_x, deco_rect.right() + 4)
            
            # Draw sync badge (leftmost if present)
            current_x = base_x
            if sync_pixmap:
                try:
                    y = original_rect.top() + (original_rect.height() - badge_size) // 2
                    painter.drawPixmap(int(current_x), int(y), sync_pixmap.scaled(badge_size, badge_size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                    current_x += badge_size + tab_px
                except Exception:
                    pass
            
            # Draw notify badge (rightmost if present)
            if notify_pixmap:
                try:
                    y = original_rect.top() + (original_rect.height() - notify_draw_size) // 2
                    # Draw smaller, but keep the same horizontal slot
                    x = int(current_x + (badge_size - notify_draw_size) // 2)
                    painter.drawPixmap(x, int(y), notify_pixmap.scaled(notify_draw_size, notify_draw_size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                except Exception:
                    pass
        except Exception:
            pass


# ============================================================================
# PATCH: Install sync badge delegate on tree widget
# ============================================================================

def _install_sync_badge_delegate():
    """Patch MainWindow to install sync badge delegate on tree widget."""
    try:
        if not hasattr(MainWindow, '__init__'):
            return
        
        _orig_init = MainWindow.__init__
        
        def _new_init(self, *args, **kwargs):
            _orig_init(self, *args, **kwargs)
            # Install a sync badge delegate for column 0
            if hasattr(self, 'tree') and self.tree is not None:
                try:
                    # IMPORTANT: keep a strong reference; otherwise the Python
                    # QObject wrapper can be GC'ed and Qt will later crash.
                    delegate = _SyncBadgeRightDelegate(self.tree)
                    self._sync_badge_delegate = delegate
                    self.tree.setItemDelegateForColumn(0, delegate)
                    print(f"[INSTALL_DELEGATE] Sync badge delegate installed on tree widget")
                except Exception as e:
                    print(f"[INSTALL_DELEGATE] Error installing delegate: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                print(f"[INSTALL_DELEGATE] Tree not available yet")
        
        MainWindow.__init__ = _new_init
        print(f"[INSTALL_DELEGATE] MainWindow.__init__ patched successfully")
    except Exception as e:
        print(f"[INSTALL_DELEGATE] Failed to patch MainWindow: {e}")
        import traceback
        traceback.print_exc()

_install_sync_badge_delegate()
