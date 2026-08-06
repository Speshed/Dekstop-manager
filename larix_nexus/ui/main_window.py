# -*- coding: utf-8 -*-

import os
import io
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
    Signal, Slot, QSize, QEvent, QRect, QPoint, QTimer, QTranslator, QLocale, QUrl,
    QLibraryInfo, QPersistentModelIndex, QParallelAnimationGroup, QRectF,
    QPropertyAnimation, QVariantAnimation, QEasingCurve, QDate, QDateTime, QSettings, QEventLoop,
    Property
)

from PySide6.QtGui import (
    QIcon, QPixmap, QPainter, QColor, QPen, QPainterPath, QAction, QTransform, QCursor,
    QDesktopServices,
    QTextCharFormat, QBrush, QPalette, QFontMetrics
)

from PySide6.QtWidgets import (
    # base
    QApplication, QMainWindow, QWidget, QFrame, QWidgetAction,
    # layouts
    QVBoxLayout, QHBoxLayout, QGridLayout, QLayout, QFormLayout,
    # controls
    QLabel, QPushButton, QToolButton, QLineEdit, QComboBox, QCheckBox,
    QProgressBar, QInputDialog, QDialog, QDialogButtonBox, QMenu,
    QListView, QListWidget, QListWidgetItem,
    QStatusBar, QHeaderView, QTableView, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem,
    QSplitter, QFileDialog, QSizePolicy, QMessageBox,
    # delegates/styles
    QStyledItemDelegate, QStyle, QStyleOptionButton, QStyleOptionViewItem, QStyleOptionHeader, QAbstractItemView, QProxyStyle,
    # gfx effects
    QGraphicsDropShadowEffect, QGraphicsOpacityEffect,
    # misc
    QAbstractButton, QDateEdit, QCalendarWidget, QToolTip,
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
from larix_nexus.constants import PUBLIC_LINK_ICON_PATH
from larix_nexus.models.tombstone_table import TombstoneTableModel

# Imports from ui modules
from .widgets import (
    NikCheckBoxStyle, TreeBranchProxyStyle, ThemeToggle, StickyMenu, HeaderCheckButton,
    SortHeader, BusyDots, RainbowStatusProgress, UnifiedStatusCard, STATUS_CARD_OUTER_GAP, WaitDialog, ItemViewNoNativeHighlightStyle,
    CHECK_ICON_OFF_PATH, CHECK_ICON_ON_PATH, navigation_pixmap
)
from .public_link_dialog import PublicLinkDialog, PublicLinkLookupWorker
from .delegates import CheckBoxDelegate, CheckBoxDelegateBg
from .delegates import RowHoverDelegate, MenuLikeTreeDelegate, install_viewport_row_highlighter
from ..api.client import PopupComboBox
from .ui_helpers import _style_combo_popup_view
from .dialogs import BatchUploadDialog, BatchDownloadDialog, parse_date_like, _user_display_datetime
from .operation_coordinator import FileOperationCoordinator

# Imports from utils
from larix_nexus.utils.theme import (
    white_tinted_icon, _app_settings, _cloud_tz_offset_minutes
)

# Helper functions
import re
def _sanitize_filename(name: str) -> str:
    """Sanitize filename by removing/replacing invalid characters."""
    return re.sub(r"[\\/:*?\"<>|]+", "_", str(name or ""))


class _FileVersionPublicLinkDelegate(QStyledItemDelegate):
    """Draw the current file-level link indicator after version text."""

    _ICON_SIZE = 12
    _TEXT_GAP = 5

    def paint(self, painter, option, index):
        item = index.data(Qt.UserRole)
        has_link = (
            isinstance(item, dict)
            and item.get("has_public_link")
            and item.get("public_link_state") == "exists"
        )
        if not has_link:
            super().paint(painter, option, index)
            return

        icon = themed_icon(PUBLIC_LINK_ICON_PATH)
        if icon.isNull():
            super().paint(painter, option, index)
            return

        # Keep normal text/background rendering, then place the indicator
        # immediately after the displayed version text.
        super().paint(painter, option, index)

        text = index.data(Qt.DisplayRole)
        text = "" if text is None else str(text)
        text_width = QFontMetrics(option.font).horizontalAdvance(text)
        content_left = option.rect.left() + 4
        icon_x = content_left + text_width + self._TEXT_GAP

        icon_rect = QRect(
            icon_x,
            option.rect.top() + max(0, (option.rect.height() - self._ICON_SIZE) // 2),
            self._ICON_SIZE,
            self._ICON_SIZE,
        )
        if icon_rect.right() > option.rect.right():
            return
        icon.paint(painter, icon_rect, Qt.AlignCenter, QIcon.Normal, QIcon.Off)


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


def _configure_version_compare_button(button, version_count: int, disabled_tooltip: str) -> bool:
    """Apply the version-count availability rule and return whether comparison is allowed."""
    can_compare = version_count >= 2
    button.setEnabled(can_compare)
    button.setToolTip("" if can_compare else disabled_tooltip)
    return can_compare


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


def _project_display_name(node: dict) -> str:
    """Return a selectable project's non-blank display name."""
    value = (node or {}).get("name") or (node or {}).get("title")
    return "" if value is None else str(value).strip()

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

        self.cb_workspaces = PopupComboBox()
        self.cb_workspaces.setObjectName("workspacesCombo")
        _style_combo_popup_view(
            self.cb_workspaces,
            "workspacesComboView",
            dark=_is_dark,
        )
        def _restyle_workspaces_popup():
            _style_combo_popup_view(
                self.cb_workspaces,
                "workspacesComboView",
                dark=_is_dark_mode(),
            )
        self.cb_workspaces.aboutToPopup.connect(_restyle_workspaces_popup)
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
    def __init__(self, api: APIClient, parent=None, preset_username: str = ""):
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
        saved_username = str(preset_username or settings.get("last_username", "") or "")

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


class _StartupProjectLoadWorker(QObject):
    """Fetch the project list without blocking the GUI after login."""

    finished = Signal(int, object)

    def __init__(self, api, workspace_id, generation):
        super().__init__()
        self._api = api
        self._workspace_id = workspace_id
        self._generation = generation

    @Slot()
    def run(self):
        try:
            changed = self._api.change_workspace(self._workspace_id)
        except Exception as exc:
            self.finished.emit(
                self._generation,
                {
                    "workspace_id": self._workspace_id,
                    "projects": None,
                    "error": "workspace_activation",
                    "exception": exc,
                },
            )
            return
        if not changed:
            self.finished.emit(
                self._generation,
                {
                    "workspace_id": self._workspace_id,
                    "projects": None,
                    "error": "workspace_activation",
                },
            )
            return
        try:
            projects = self._api.list_projects()
            error = None if projects is not None else "project_load"
        except Exception as exc:
            projects = None
            error = "project_load"
            load_exception = exc
        result = {
            "workspace_id": self._workspace_id,
            "projects": projects,
            "error": error,
        }
        if error == "project_load" and "load_exception" in locals():
            result["exception"] = load_exception
        self.finished.emit(self._generation, result)


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

    def _set_status_shell_theme(self, dark: bool) -> None:
        """Keep the bottom status shell visible and visually separated."""
        status = getattr(self, "status", None)
        if status is None:
            return
        text = "#ffffff" if dark else "#222222"
        status.setStyleSheet(
            f"QStatusBar#operationStatusBar {{ background: transparent; "
            f"border: none; margin: 0; padding: 0; color: {text}; }}"
            f"QStatusBar#operationStatusBar::item {{ border: none; margin: 0; padding: 0; }}"
        )
        shell = getattr(self, "file_operation_shell", None)
        if shell is not None:
            shell.set_dark_theme(dark)

    def _fit_status_shell_height(self) -> None:
        """Leave the QStatusBar's own vertical inset around the status card."""
        status = getattr(self, "status", None)
        shell = getattr(self, "file_operation_shell", None)
        if status is None or shell is None:
            return

        # QStatusBar may reserve a small style/layout inset even with zero
        # stylesheet margins.  Measure it from the installed widget instead
        # of assuming a platform- or DPI-specific number.
        for _ in range(2):
            status.layout().activate()
            inset = max(0, shell.geometry().top())
            desired_height = shell.sizeHint().height() + 2 * inset
            if status.height() == desired_height:
                break
            status.setFixedHeight(desired_height)

    def _on_progress_range_changed(self, minimum: int, maximum: int):
        panel = getattr(self, "file_operation_status", None)
        if panel is not None and getattr(panel, "progress", None) is getattr(self, "progress", None):
            return
        if panel is not None and getattr(panel, "_mode", None) == "generic":
            panel.progress_bar.setRange(minimum, maximum)

    def _on_progress_value_changed(self, value: int):
        panel = getattr(self, "file_operation_status", None)
        if panel is not None and getattr(panel, "progress", None) is getattr(self, "progress", None):
            return
        if panel is not None and getattr(panel, "_mode", None) == "generic":
            panel.progress_bar.setValue(value)

    def _clear_finished_generic_status(self) -> None:
        """Clear only the loading text owned by the generic progress UI."""
        panel = getattr(self, "file_operation_status", None)
        if panel is None or getattr(panel, "_mode", None) != "generic":
            return
        if not bool(getattr(self, "_generic_status_active", False)):
            return
        if bool(getattr(self, "_sync_status_lock", False)):
            return
        status = getattr(self, "status", None)
        if status is None:
            return
        current = status.currentMessage()
        loading_text = getattr(self, "_generic_status_text", "")
        if current and loading_text and current != loading_text:
            return
        if current:
            status.clearMessage()
        panel.set_status_text("")
        self._generic_status_text = ""
        self._generic_status_active = False

    @staticmethod
    def _looks_like_loading_status(message: str) -> bool:
        value = str(message or "").lower()
        return any(token in value for token in ("загруз", "loading", "синхрон", "sync", "upload", "download"))

    def _set_progress_cancel_handler(self, handler):
        """Install/clear cancel handler for the status-bar progress UI."""
        try:
            self._progress_cancel_handler = handler
        except Exception:
            pass

        try:
            btn = None
            if btn is not None:
                btn.setText(t("common.cancel"))
                btn.setEnabled(handler is not None)
                # Show the cancel chip only when progress is visible and cancel is supported.
                btn.setVisible(bool(handler) and bool(getattr(self, "progress", None) and self.progress.isVisible()))
        except Exception:
            pass

        try:
            panel = getattr(self, "file_operation_status", None)
            if panel is not None:
                panel.set_cancel_callback(handler)
        except Exception:
            pass

    def _set_progress_visible(self, visible: bool):
        """Set visibility of progress UI (status bar progress + optional cancel)."""
        panel = getattr(self, "file_operation_status", None)
        transfer_active = panel is not None and getattr(panel, "_mode", None) == "transfer" and panel.isVisible()
        if visible:
            if panel is not None:
                if not transfer_active:
                    title = self.status.currentMessage() or t("status.loading")
                    self._generic_status_text = title
                    self._generic_status_active = True
                    if getattr(panel, "_mode", None) != "generic" or not panel.isVisible():
                        maximum = self.progress.maximum()
                        panel.start_generic(
                            title,
                            total=maximum if maximum > 0 else None,
                            cancel_callback=getattr(self, "_progress_cancel_handler", None),
                        )
                        panel.set_progress(self.progress.value(), maximum if maximum > 0 else None)
                    else:
                        panel.set_generic_title(title)
                self.progress.setVisible(True)
            else:
                self.progress.setVisible(True)
        else:
            if panel is not None and getattr(panel, "_mode", None) == "generic":
                clear_finished = getattr(self, "_clear_finished_generic_status", None)
                if callable(clear_finished):
                    clear_finished()
                else:
                    current = self.status.currentMessage()
                    if not current or current == getattr(self, "_generic_status_text", ""):
                        panel.set_status_text("")
                panel.finish()
            if not transfer_active:
                self.progress.setVisible(False)

        # When progress hides, also clear any previous cancel handler to avoid
        # accidentally canceling the wrong operation next time.
        if not visible:
            try:
                self._progress_cancel_handler = None
            except Exception:
                pass

        # Cancel chip is shown only when a handler is installed.
        try:
            btn = None
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
            btn = None
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

    # --- Status bar message locking for sync UX ---
    def _show_status_message(self, message: str, timeout: int = 0, *, owner: str = "ui", force: bool = False) -> None:
        """Unified status line writer with sync lock.

        While sync is active, normal UI messages should not overwrite sync status.
        Use owner="sync" for sync updates. Use force=True for high-priority
        messages (errors, confirmations) that must be visible.
        """
        try:
            if getattr(self, "_sync_status_lock", False) and (owner != "sync") and (not force):
                # Optionally remember the last UI message to show after sync.
                try:
                    self._pending_status_message = (str(message or ""), int(timeout or 0))
                except Exception:
                    pass
                return
        except Exception:
            # If something goes wrong, fall back to direct write.
            pass

        try:
            if hasattr(self, "status") and self.status is not None:
                if timeout and int(timeout) > 0:
                    self.status.showMessage(str(message or ""), int(timeout))
                else:
                    self.status.showMessage(str(message or ""))

        except Exception:
            pass

    def _on_status_message_changed(self, message: str):
        """Keep the generic operation panel title in sync with QStatusBar."""
        try:
            shell = getattr(self, "file_operation_shell", None)
            for label in self.status.findChildren(QLabel):
                if shell is None or not shell.isAncestorOf(label):
                    label.hide()
            panel = getattr(self, "file_operation_status", None)
            if panel is not None and getattr(panel, "_mode", None) != "transfer":
                panel.set_status_text(message or "")
                if getattr(panel, "_mode", None) == "generic" and getattr(self, "_generic_status_active", False):
                    if message == getattr(self, "_generic_status_text", ""):
                        pass
                    elif (
                        getattr(self, "_generic_status_text", "") == t("status.loading")
                        and self._looks_like_loading_status(message)
                    ):
                        self._generic_status_text = message
                    else:
                        self._generic_status_active = False
        except Exception:
            pass

    def _show_file_operation_busy_warning(self) -> None:
        message = "Дождитесь завершения текущей операции"
        try:
            QMessageBox.information(self, t("common.information"), message)
            return
        except Exception:
            try:
                active = self._file_operations.is_busy()
            except Exception:
                active = False
            if active:
                sync_log("File operation warning could not be shown while another operation is active")
                return
            try:
                self.status.showMessage(message, 5000)
            except Exception:
                pass

    def _try_acquire_file_operation(self, operation: str, source: str | None = None) -> bool:
        source = source or str(operation)
        if self._file_operations.try_acquire_user(operation, source=source):
            return True
        self._log_file_operation_conflict(operation, source)
        self._show_file_operation_busy_warning()
        return False

    def _release_file_operation(self, operation: str, source: str | None = None) -> None:
        self._file_operations.release(operation, source=source or str(operation))

    def _try_acquire_auto_sync(self) -> bool:
        return self._file_operations.try_acquire_auto(source="auto_sync")

    def _release_sync_operation(self) -> None:
        self._release_file_operation("sync", source="auto_sync")

    def _log_file_operation_conflict(self, operation: str, source: str) -> None:
        """Record a blocked start without changing coordinator state."""
        try:
            live = {}
            for name in ("copy", "move", "upload", "download", "sync"):
                value = getattr(self, f"_{name}_threads", None)
                if value is None:
                    value = getattr(self, f"_{name}_thread", None)
                if isinstance(value, (list, tuple, set, dict)):
                    items = value.values() if isinstance(value, dict) else value
                    live[name] = sum(
                        1 for item in items
                        if item is not None and (
                            not hasattr(item, "isRunning") or item.isRunning()
                        )
                    )
                else:
                    live[name] = bool(
                        value is not None
                        and (not hasattr(value, "isRunning") or value.isRunning())
                    )
            sync_log(
                "FILE_OPERATION conflict operation={} source={} active_operation={!r} "
                "live_threads={!r} auto_sync_running={!r} sync_all_active={!r} "
                "sync_all_pending={!r}",
                operation,
                source,
                self._file_operations.active_operation,
                live,
                getattr(getattr(self, "sync2", None), "_auto_sync_running", False),
                getattr(self, "_sync_all_operation_active", False),
                getattr(self, "_sync_all_pending", 0),
                component="UI",
                op="file_operation",
                result="blocked",
            )
        except Exception:
            pass

    def _on_file_operation_released(self) -> None:
        manager = getattr(self, "sync2", None)
        if manager is not None and hasattr(manager, "run_deferred_auto_sync"):
            manager.run_deferred_auto_sync()

    def _begin_sync_status(self, message: str = "") -> None:
        try:
            self._active_sync_count = int(getattr(self, "_active_sync_count", 0) or 0) + 1
        except Exception:
            self._active_sync_count = 1

        try:
            self._sync_status_lock = True
            self._status_lock_owner = "sync"
        except Exception:
            pass

        try:
            if hasattr(self, "_set_progress_visible"):
                self._set_progress_visible(True)
            else:
                self.progress.setVisible(True)
            try:
                self.progress.setRange(0, 0)
            except Exception:
                pass
        except Exception:
            pass

        if message:
            self._show_status_message(message, owner="sync")

    def _update_sync_status(self, message: str) -> None:
        try:
            self._show_status_message(message, owner="sync")
        except Exception:
            pass

    def _end_sync_status(self, message: str = "", timeout: int = 4000) -> None:
        # Decrement active counter; keep lock while any sync is running.
        try:
            cur = int(getattr(self, "_active_sync_count", 0) or 0)
            cur = max(0, cur - 1)
            self._active_sync_count = cur
        except Exception:
            self._active_sync_count = 0

        if int(getattr(self, "_active_sync_count", 0) or 0) > 0:
            # Still syncing elsewhere; do not unlock/hide progress.
            if message:
                try:
                    self._show_status_message(message, owner="sync")
                except Exception:
                    pass
            return

        # Last sync finished: show final message, hide progress, unlock.
        if message:
            try:
                self._show_status_message(message, int(timeout or 0), owner="sync")
            except Exception:
                pass

        try:
            if hasattr(self, "_set_progress_visible"):
                self._set_progress_visible(False)
            else:
                self.progress.setVisible(False)
            try:
                self.progress.setRange(0, 0)
            except Exception:
                pass
        except Exception:
            pass

        try:
            self._sync_status_lock = False
            self._status_lock_owner = ""
        except Exception:
            pass

        # If a UI message tried to show during sync, allow it to show now.
        try:
            pending = getattr(self, "_pending_status_message", None)
        except Exception:
            pending = None
        try:
            self._pending_status_message = None
        except Exception:
            pass
        if pending and isinstance(pending, tuple) and len(pending) >= 1:
            try:
                pmsg = str(pending[0] or "")
                pto = int(pending[1] or 0) if len(pending) > 1 else 0
                if pmsg:
                    self._show_status_message(pmsg, pto, owner="ui")
            except Exception:
                pass

    def _begin_busy_status(self, message: str = "") -> None:
        """Show non-sync busy progress (ref-counted)."""
        try:
            self._active_busy_count = int(getattr(self, "_active_busy_count", 0) or 0) + 1
        except Exception:
            self._active_busy_count = 1

        if int(getattr(self, "_active_busy_count", 0) or 0) == 1:
            try:
                if hasattr(self, "_set_progress_visible"):
                    self._set_progress_visible(True)
                else:
                    self.progress.setVisible(True)
                try:
                    self.progress.setRange(0, 0)
                except Exception:
                    pass
            except Exception:
                pass
            try:
                QApplication.processEvents()
            except Exception:
                pass

        if message:
            try:
                self._show_status_message(message, owner="ui", force=True)
            except Exception:
                pass

    def _update_busy_status(self, message: str = "") -> None:
        if message:
            try:
                self._show_status_message(message, owner="ui", force=True)
            except Exception:
                pass

    def _end_busy_status(self, message: str = "", timeout: int = 0) -> None:
        try:
            cur = int(getattr(self, "_active_busy_count", 0) or 0)
            cur = max(0, cur - 1)
            self._active_busy_count = cur
        except Exception:
            self._active_busy_count = 0

        if int(getattr(self, "_active_busy_count", 0) or 0) > 0:
            # Nested busy: keep spinner; do not show completion message here or it pairs
            # misleadingly with a still-active progress bar (outer scope owns the UX).
            return

        sync_active = int(getattr(self, "_active_sync_count", 0) or 0) > 0
        if not sync_active:
            try:
                if hasattr(self, "_set_progress_visible"):
                    self._set_progress_visible(False)
                else:
                    self.progress.setVisible(False)
                try:
                    self.progress.setRange(0, 0)
                except Exception:
                    pass
            except Exception:
                pass

        if message:
            try:
                self._show_status_message(message, int(timeout or 0), owner="ui", force=True)
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
        self._file_operations = FileOperationCoordinator(self._on_file_operation_released)
        # Session-owned group state must not be inherited from a previous
        # FolderSyncManager or from status-bar widgets.
        self._sync_all_operation_active = False
        self._sync_all_pending = 0
        self._sync_all_release_done = False
        
        # Initialize FolderSyncManager if available
        if FolderSyncManager is not None:
            try:
                sync_log("=" * 60)
                sync_log("Инициализация FolderSyncManager...")
                self.sync2 = FolderSyncManager(
                self.api,
                self,
                auto_operation_guard=self._try_acquire_auto_sync,
                operation_finished=self._release_sync_operation,
                )
                sync_log("✓ FolderSyncManager создан успешно")
                
                # Connect signals for UI updates
                try:
                    self.sync2.autoSyncStarted.connect(self._on_auto_sync_started, QtCore.Qt.QueuedConnection)
                    self.sync2.autoSyncFinished.connect(self._on_auto_sync_finished, QtCore.Qt.QueuedConnection)
                    self.sync2.syncItem.connect(self._on_sync_item, QtCore.Qt.QueuedConnection)
                    self.sync2.syncTransferProgress.connect(
                        self._on_sync_transfer_progress, QtCore.Qt.QueuedConnection
                    )
                    try:
                        if hasattr(self.sync2, "autoSyncResult") and hasattr(self, "_on_auto_sync_result"):
                            self.sync2.autoSyncResult.connect(self._on_auto_sync_result, QtCore.Qt.QueuedConnection)
                    except Exception:
                        pass
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
        self._checkbox_style = NikCheckBoxStyle()
        self._syncing_connector_columns = False
        # Stable ordering: keep visible order during metadata enrichment
        self._freeze_visible_order = False
        self._frozen_order = {}
        # Track all running ad-hoc sync threads to prevent premature destruction
        self._sync_now_threads: set[QtCore.QThread] = set()
        self.chips = {}  # словарь чипов форматов (DOC/PDF/JPG/CAD); может быть пустым на старте
        # QApplication property is the theme already applied by main.py.
        # Fall back to persisted settings for direct MainWindow construction.
        self._current_theme = THEME_LIGHT
        try:
            app = QApplication.instance()
            applied_theme = app.property("nik_theme") if app is not None else None
            if applied_theme in (THEME_LIGHT, THEME_DARK):
                self._current_theme = applied_theme
            else:
                saved_theme = load_saved_theme()
                if saved_theme in (THEME_LIGHT, THEME_DARK):
                    self._current_theme = saved_theme
        except Exception:
            pass


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
                # The combobox popup view lives in a separate popup container;
                # give it a stable objectName so theme QSS can target it reliably.
                projects_view.setObjectName("projectsComboView")
                try:
                    projects_view.viewport().setObjectName("projectsComboViewport")
                except Exception:
                    pass
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
            self.cb_projects.aboutToPopup.connect(self._apply_projects_combo_popup_style)
        except Exception:
            pass

        try:
            self._apply_projects_combo_popup_style()
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
        menu_sync_all = QMenu(self.btn_sync_all)
        self.act_sync_all = menu_sync_all.addAction(t("sync.sync_all_folders"))
        self.act_disable_all_syncs = menu_sync_all.addAction(t("sync.disable_all_syncs"))
        try:
            self.act_sync_all.triggered.connect(self._on_sync_all_clicked)
            self.act_disable_all_syncs.triggered.connect(self._confirm_disable_all_syncs)
        except Exception:
            pass
        self.btn_sync_all.setMenu(menu_sync_all)
        self.btn_sync_all.setPopupMode(QToolButton.InstantPopup)

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
        self.theme_toggle.setChecked(self._current_theme == THEME_DARK)
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
        self._search_recursive = bool(getattr(self, "cb_flat", None) is not None and self.cb_flat.isChecked()) if hasattr(self, "cb_flat") else getattr(self, "_search_recursive", False)
        self.search.setTextMargins(0, 0, 0, 0)
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
            self._search_recursive = bool(on)
            self.on_flat_toggled(on)
        

        fl.addWidget(self.btn_plus)
        fl.addWidget(self.btn_download)
        fl.addWidget(self.btn_rename)
        fl.addWidget(self.btn_compare)
        fl.addWidget(self.btn_move)
        fl.addWidget(self.btn_copy)
        fl.addWidget(self.btn_delete)
        self.selection_mode_indicator = QToolButton(self)
        self.selection_mode_indicator.setObjectName("selectionModeIndicator")
        self.selection_mode_indicator.setProperty("secondary", True)
        self._refresh_secondary_style(self.selection_mode_indicator)
        self.selection_mode_indicator.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.selection_mode_indicator.setCheckable(True)
        self.selection_mode_indicator.setIconSize(self.btn_delete.iconSize())
        self.selection_mode_indicator.setStyleSheet(
            "QToolButton#selectionModeIndicator:checked { "
            "background: rgba(247, 146, 30, 0.20); "
            "border: 1px solid #FFA74B; border-radius: 14px; }"
        )
        self.selection_mode_indicator.setToolTip(t("selection_mode.hint"))
        try:
            self.selection_mode_indicator.setIcon(self._themed_icon(CHOICE_ICON_PATH))
        except Exception:
            pass
        self.selection_mode_indicator.setVisible(False)
        fl.addWidget(self.selection_mode_indicator)
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
        self.selection_mode_indicator.setFixedHeight(base_h)

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
        try:
            split.setChildrenCollapsible(False)
        except Exception:
            pass

        # Keep splitter accessible (used by tree panel toggle)
        self.main_splitter = split

        self.tree = QTreeWidget(self); self.tree.setHeaderLabels([t("tree.project_files")]); self.tree.header().setStretchLastSection(True)
        try:
            prox = TreeBranchProxyStyle()
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

        # Adaptive: elide long folder names instead of drawing under badges.
        try:
            self.tree.setTextElideMode(Qt.ElideRight)
        except Exception:
            pass
        try:
            # Prefer elide; allow horizontal scrollbar only when needed.
            self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        except Exception:
            pass
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

        # --- Left tree panel with collapse/expand toggle (minimal wrapper) ---
        self.tree_panel = QWidget(self)
        self.tree_panel.setObjectName("treePanel")
        tree_panel_l = QHBoxLayout(self.tree_panel)
        tree_panel_l.setContentsMargins(0, 0, 0, 0)
        tree_panel_l.setSpacing(0)

        self.tree_panel_toggle = QToolButton(self.tree_panel)
        self.tree_panel_toggle.setObjectName("treePanelToggle")
        self.tree_panel_toggle.setProperty("secondary", True)
        try:
            self._refresh_secondary_style(self.tree_panel_toggle)
        except Exception:
            pass
        self.tree_panel_toggle.setCursor(Qt.PointingHandCursor)
        self.tree_panel_toggle.setFocusPolicy(Qt.NoFocus)
        self.tree_panel_toggle.setFixedWidth(34)
        self.tree_panel_toggle.setIconSize(QSize(20, 20))
        try:
            self.tree_panel_toggle.setToolButtonStyle(Qt.ToolButtonIconOnly)
        except Exception:
            pass
        self.tree_panel_toggle.clicked.connect(self._toggle_tree_panel)

        tree_panel_l.addWidget(self.tree_panel_toggle, 0)
        tree_panel_l.addWidget(self.tree, 1)

        # Panel width state
        self._tree_panel_toggle_w = int(self.tree_panel_toggle.width())
        self._tree_panel_min_expanded_w = 260 + self._tree_panel_toggle_w
        self._tree_panel_saved_width = 320
        try:
            self.tree_panel.setMinimumWidth(self._tree_panel_min_expanded_w)
        except Exception:
            pass
        self._set_tree_panel_arrow(collapsed=False)

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
            self.table.setWordWrap(True)
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

        hdr.setMinimumSectionSize(CHECKBOX_COLUMN_WIDTH)

        # Column widths 1..N are set from content in table_operations._recalc_columns (Fixed, no Stretch).

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
            self.table.horizontalScrollBar().valueChanged.disconnect(self._update_header_checkbox_pos)
        except Exception:
            pass
        self.table.horizontalScrollBar().valueChanged.connect(self._update_header_checkbox_pos)

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



        self.selection_mode_panel = QFrame(self)
        self.selection_mode_panel.setObjectName("selectionModePanel")
        self.selection_mode_panel.setFrameShape(QFrame.StyledPanel)
        self.selection_mode_panel.setVisible(False)
        self.selection_mode_panel.setStyleSheet(
            "QFrame#selectionModePanel { border: 1px solid rgba(247, 146, 30, 0.22); border-radius: 6px; background: rgba(247, 146, 30, 0.04); }"
            "QFrame#selectionModePanel QLabel { background: transparent; }"
        )
        smp_l = QHBoxLayout(self.selection_mode_panel)
        smp_l.setContentsMargins(10, 5, 10, 5)
        smp_l.setSpacing(0)
        self.selection_mode_label = QLabel(self.selection_mode_panel)
        self.selection_mode_label.setObjectName("selectionModeLabel")
        self.selection_mode_label.setWordWrap(True)
        try:
            _font = self.selection_mode_label.font()
            _font.setPointSize(max(8, _font.pointSize() - 1))
            self.selection_mode_label.setFont(_font)
        except Exception:
            pass
        smp_l.addWidget(self.selection_mode_label, 0)

        # Панель действий
        actions = QWidget(self); act_l = QHBoxLayout(actions); act_l.setContentsMargins(0,0,0,0); act_l.setSpacing(8)
        self.btn_download.setProperty("secondary", True);        
        act_l.addStretch(1)
        r_l.addWidget(filt, 0); r_l.addWidget(self.table, 1); r_l.addWidget(actions, 0)
        split.addWidget(self.tree_panel); split.addWidget(right); split.setSizes([320, 960])
        try:
            self._enhance_splitter_handles(split)
        except Exception:
            pass

        # Remember user-resized panel width (for restore on expand)
        try:
            split.splitterMoved.connect(self._remember_tree_panel_width)
        except Exception:
            pass

        root = QWidget(self); root_l = QVBoxLayout(root); root_l.setContentsMargins(10,10,10,0); root_l.setSpacing(8)
        root_l.addWidget(top)

        # --- Connection recovery panel (hidden by default) ---
        self._connection_error_code = ""
        self._connection_retry_context = {}
        self._reconnect_in_progress = False
        self._current_folder_context = {}

        self.connection_panel = QFrame(self)
        self.connection_panel.setFrameShape(QFrame.StyledPanel)
        self.connection_panel.setStyleSheet(
            "QFrame { background: #FFF3E0; border: 1px solid #F7921E; border-radius: 4px; }"
            "QLabel { background: transparent; }"
            "QPushButton { background: #F7921E; color: white; border: none; border-radius: 3px; padding: 5px 14px; font-weight: bold; }"
            "QPushButton:hover { background: #E8820D; }"
            "QPushButton:disabled { background: #ccc; color: #666; }"
        )
        cp_l = QHBoxLayout(self.connection_panel)
        cp_l.setContentsMargins(12, 8, 12, 8)
        cp_l.setSpacing(10)

        self.connection_title = QLabel(t("connection.title"), self.connection_panel)
        self.connection_title.setStyleSheet("font-weight: bold; font-size: 13px;")
        self.connection_text = QLabel("", self.connection_panel)
        self.connection_text.setWordWrap(True)
        self.connection_text.setStyleSheet("font-size: 12px;")
        cp_l.addWidget(self.connection_title)
        cp_l.addWidget(self.connection_text, 1)

        self.btn_connection_retry = QPushButton(t("connection.retry"), self.connection_panel)
        self.btn_connection_retry.clicked.connect(self._on_connection_retry_clicked)
        cp_l.addWidget(self.btn_connection_retry)
        self.btn_connection_login = QPushButton(t("connection.login_again"), self.connection_panel)
        self.btn_connection_login.setVisible(False)
        self.btn_connection_login.clicked.connect(self._on_connection_login_clicked)
        cp_l.addWidget(self.btn_connection_login)
        self.btn_connection_hide = QPushButton(t("connection.hide"), self.connection_panel)
        self.btn_connection_hide.setStyleSheet(
            "QPushButton { background: transparent; color: #888; border: 1px solid #ccc; border-radius: 3px; padding: 5px 10px; font-weight: normal; }"
            "QPushButton:hover { background: #eee; }"
        )
        self.btn_connection_hide.clicked.connect(self._hide_connection_panel)
        cp_l.addWidget(self.btn_connection_hide)

        self.connection_panel.setVisible(False)
        root_l.addWidget(self.connection_panel)

        root_l.addWidget(split, 1)
        self.setCentralWidget(root)
        try:
            self.header_filter_icons_update()
        except Exception:
            pass

        
        
        self.status = QStatusBar(self); self.status.setObjectName("operationStatusBar"); self.setStatusBar(self.status); self.status.setSizeGripEnabled(False)
        self.status.setFixedHeight(36 + 2 * STATUS_CARD_OUTER_GAP)
        self._set_status_shell_theme(self._current_theme == THEME_DARK)
        self.file_operation_shell = UnifiedStatusCard(self)
        self.file_operation_status = self.file_operation_shell.operation_widget
        self.progress = self.file_operation_status.progress
        self.file_operation_shell.set_dark_theme(self._current_theme == THEME_DARK)
        self.file_operation_status.set_dark_theme(self._current_theme == THEME_DARK)
        # Keep the card visible while QStatusBar displays its native message.
        self.status.addPermanentWidget(self.file_operation_shell, 1)
        self.file_operation_shell.show()
        self.file_operation_shell.setVisible(True)
        self.status.show()
        self._fit_status_shell_height()
        self.status.messageChanged.connect(self._on_status_message_changed)
        self.progress.rangeChanged.connect(self._on_progress_range_changed)
        self.progress.valueChanged.connect(self._on_progress_value_changed)
        self._set_progress_visible(False)

        # Sync status lock: prevent normal UI statuses from overwriting sync messages.
        self._sync_status_lock = False
        self._active_sync_count = 0
        self._active_busy_count = 0
        self._status_lock_owner = ""
        self._pending_status_message = None
        self._generic_status_text = ""
        self._generic_status_active = False
        
        # Флаг отмены для прогресс-бара
        self._progress_cancelled = False

        # Current cancel handler for progress UI (callable or None)
        self._progress_cancel_handler = None
        
        # Кнопка отмены для прогресс-бара
        # Cancellation is rendered by the unified status card.
        
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
                self.btn_download.clicked.connect(self.action_download)
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
        self._selection_mode_anchor_row = None
        self.files_model = FilesTableModel(self.files_current, self.icon_provider, self.checked)
        self.proxy = QSortFilterProxyModel(self); self.proxy.setSourceModel(self.files_model); self.proxy.setSortRole(FilesTableModel.SORT_ROLE)
        self.table.setModel(self.proxy)
        self._file_version_public_link_delegate = _FileVersionPublicLinkDelegate(self.table)
        self.table.setItemDelegateForColumn(2, self._file_version_public_link_delegate)

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
            self.proxy.rowsInserted.connect(lambda *_: self._update_selection_mode_panel())
            self.proxy.rowsRemoved.connect(lambda *_: self._update_selection_mode_panel())
            self.proxy.modelReset.connect(lambda *_: self._update_selection_mode_panel())
            # И одновременно пересчитываем доступность кнопок
            self.files_model.dataChanged.connect(lambda *_: self._update_actions_enabled())
            self.files_model.dataChanged.connect(lambda *_: self._update_selection_mode_panel())
            self.files_model.modelReset.connect(self._schedule_public_link_checks)
            self.files_model.layoutChanged.connect(self._schedule_public_link_checks)
            QTimer.singleShot(0, self._schedule_public_link_checks)
        except Exception:
            pass
        self.update_header_checkbox()
        lang_mgr = get_language_manager()
        try:
            lang_mgr.languageChanged.connect(self._update_selection_mode_panel)
        except Exception:
            pass
        self._update_selection_mode_panel()
        self.table.horizontalHeader().sortIndicatorChanged.connect(self.on_sort_changed)

        self.set_initial_view()

        try:
            if hasattr(self, '_ensure_default_column_visibility') and callable(self._ensure_default_column_visibility):
                self._ensure_default_column_visibility()
        except Exception:
            pass

        try:
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

            settings = load_settings()
            interval_seconds = int(settings.get("sync", {}).get("auto_sync_interval", 300) or 300)
            interval_labels = {
                300: t("interval.5_minutes"),
                600: t("interval.10_minutes"),
                900: t("interval.15_minutes"),
                1800: t("interval.30_minutes"),
                2700: t("interval.45_minutes"),
                3600: t("interval.60_minutes"),
                86400: t("interval.once_per_day"),
            }
            interval_label = interval_labels.get(interval_seconds)
            if interval_label is None:
                if interval_seconds % 86400 == 0:
                    days = interval_seconds // 86400
                    interval_label = f"{days} {'день' if days == 1 else 'дня' if 1 < days < 5 else 'дней'}" if is_russian() else f"{days} day" + ("" if days == 1 else "s")
                elif interval_seconds % 3600 == 0:
                    hours = interval_seconds // 3600
                    interval_label = f"{hours} ч" if is_russian() else f"{hours} hr"
                elif interval_seconds % 60 == 0:
                    minutes = interval_seconds // 60
                    interval_label = f"{minutes} мин" if is_russian() else f"{minutes} min"
                else:
                    interval_label = f"{interval_seconds} сек" if is_russian() else f"{interval_seconds} sec"

            QMessageBox.information(
                self,
                t("sync.title"),
                t("sync.enabled", path=path, interval=interval_label),
            )
        except Exception:
            # Don't let an unexpected error crash the UI event loop
            try:
                sync_exc("SYNC_MENU: unhandled exception in _sync_add_mapping")
            except Exception:
                pass

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

            try:
                project_id = self.current_project_id()
                if project_id:
                    pid = normalize_id(project_id)
                    if pid:
                        self.api.cache.pop(f"tree:{pid}", None)
                self.api.cache.pop(f"folder:{synced_folder_id}", None)
            except Exception:
                pass

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
                        self.open_folder_node(node, save_to_history=False, force_refresh=True)
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

    def _trigger_sync_now(self, folder_id: int | str, *, allow_mass_delete: bool = False, sync_mode: str = "manual") -> bool:
        group_owned = bool(getattr(self, "_sync_all_operation_active", False))
        acquire_source = "sync_all" if group_owned else "manual_sync"
        if not group_owned and not self._try_acquire_file_operation("sync", source=acquire_source):
            return False
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
            if not group_owned:
                self._release_file_operation("sync", source=acquire_source)
            return False
            
        sync_log("_TRIGGER_SYNC_NOW: Creating thread and worker...")
        th = QtCore.QThread(self)
        worker = _ImmediateSyncRunner(self.sync2, folder_id)
        try:
            worker.allow_mass_delete = bool(allow_mass_delete)
            worker.sync_mode = str(sync_mode or "manual")
        except Exception:
            pass
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
        try:
            if hasattr(worker, "sig_result") and hasattr(self, "_on_sync_now_result"):
                worker.sig_result.connect(self._on_sync_now_result, QtCore.Qt.QueuedConnection)
        except Exception:
            pass
        # Per-thread cleanup when worker finishes
        try:
            worker.sig_finished.connect(lambda _ok, _th=th, _w=worker: self._cleanup_worker_thread(_th, _w), QtCore.Qt.QueuedConnection)
        except Exception:
            pass
        
        sync_log("_TRIGGER_SYNC_NOW: Starting thread...")
        th.start()
        sync_log("_TRIGGER_SYNC_NOW: Thread started successfully")
        return True

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
        if (
            not getattr(self, "_sync_all_operation_active", False)
            and not getattr(self, "_sync_all_release_done", False)
        ):
            self._release_file_operation("sync", source="sync_all" if getattr(self, "_sync_all_operation_active", False) else "manual_sync")

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
        if not self._try_acquire_file_operation("sync", source="initial_sync"):
            return
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
            # Start sync status lock early so folder/table statuses won't overwrite it.
            if hasattr(self, "_begin_sync_status"):
                self._begin_sync_status(t("sync.counting_files", path=path))
            else:
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

    def _report_download_result(self, result: dict, title_key: str, success_key: str, artifact: str | None = None):
        failed = int(result.get("failed", 0))
        succeeded = int(result.get("succeeded", 0))
        total = int(result.get("total", 0))
        if failed or (total == 0 and artifact):
            if succeeded == 0 and artifact:
                try:
                    os.remove(artifact)
                except OSError:
                    pass
            if succeeded:
                QMessageBox.warning(self, t(title_key), f"{t('download.partial', ok=succeeded, total=total)} Ошибок: {failed}.")
            else:
                QMessageBox.warning(self, t(title_key), t("download.download_failed"))
            return False
        QMessageBox.information(self, t(title_key), t(success_key))
        return True

    
    def _zip_folder_to_path(self, node: dict, save_path: str):
        if not node or node.get("type") != "folder":
            return self._new_download_result()

        files_to_pack, dir_paths = self._collect_files_and_dirs_for_zip(node)
        result = self._new_download_result()
        target_dir = os.path.dirname(os.path.abspath(save_path)) or os.getcwd()
        fd, temp_zip = tempfile.mkstemp(prefix=".larix_zip_", suffix=".zip", dir=target_dir)
        os.close(fd)

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
            with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                # Пустые директории явно
                for d in sorted(dir_paths):
                    arc = d.rstrip("/").replace("\\", "/") + "/"
                    try:
                        zf.writestr(zipfile.ZipInfo(arc), b"")
                    except Exception:
                        pass

                # Файлы — потоково из API
                for fobj, rel in files_to_pack:
                    result["total"] += 1
                    try:
                        buffer = io.BytesIO()
                        if self.api.write_file_to(fobj.get("id"), buffer) is not True:
                            self._download_failure(result, rel, "download_failed")
                            continue
                        zf.writestr(rel.replace("\\", "/"), buffer.getvalue())
                        result["succeeded"] += 1
                    except Exception as exc:
                        self._download_failure(result, rel, type(exc).__name__)
            if result["succeeded"] <= 0:
                return result
            os.replace(temp_zip, save_path)
            temp_zip = None
            return result
        finally:
            if temp_zip:
                try:
                    os.remove(temp_zip)
                except OSError:
                    pass
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
            menu_notification.setObjectName("frequencyMenu")
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
            menu_sync.setObjectName("frequencyMenu")
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
                        try:
                            if hasattr(self, '_save_columns_visibility') and callable(self._save_columns_visibility):
                                self._save_columns_visibility()
                        except Exception:
                            pass
                        try:
                            if hasattr(self, '_apply_connector_column_width_policy') and callable(self._apply_connector_column_width_policy):
                                self._apply_connector_column_width_policy(preserve_user_widths=True)
                        except Exception:
                            pass
                    
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
                self._schedule_next_notification_timer()
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
            if hasattr(self, '_auto_refresh_timer') and self._auto_refresh_timer:
                self._auto_refresh_timer.setInterval(max(1, int(interval_seconds)) * 1000)
                self._auto_refresh_timer.start()
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



    # --- Tree panel (left) collapse/expand helpers ---
    def _set_tree_panel_arrow(self, collapsed: bool) -> None:
        try:
            btn = getattr(self, "tree_panel_toggle", None)
            if btn is None:
                return
            # Collapsed: show "expand" arrow (pointing right). Expanded: show "collapse" arrow (pointing left).
            pm = navigation_pixmap(
                mirrored=not collapsed,
                size=max(20, int(btn.iconSize().height() or 20)),
                dark=_is_dark_mode(),
            )
            if not pm.isNull():
                btn.setIcon(QIcon(pm))
                btn.setText("")
            else:
                btn.setIcon(QIcon())
                btn.setText(">" if collapsed else "<")
        except Exception:
            pass

    def _remember_tree_panel_width(self, pos=None, index=None) -> None:
        del pos, index
        try:
            if not hasattr(self, "main_splitter"):
                return
            if getattr(self.tree, "isVisible", lambda: True)() is not True:
                return
            sizes = self.main_splitter.sizes()
            if not sizes:
                return
            w = int(sizes[0])
            min_w = int(getattr(self, "_tree_panel_min_expanded_w", 0) or 0)
            if w >= max(1, min_w):
                self._tree_panel_saved_width = w
        except Exception:
            pass

    def _toggle_tree_panel(self) -> None:
        try:
            split = getattr(self, "main_splitter", None)
            panel = getattr(self, "tree_panel", None)
            tree = getattr(self, "tree", None)
            btn = getattr(self, "tree_panel_toggle", None)
            if split is None or panel is None or tree is None or btn is None:
                return

            toggle_w = int(getattr(self, "_tree_panel_toggle_w", 34) or 34)
            min_expanded = int(getattr(self, "_tree_panel_min_expanded_w", 0) or (260 + toggle_w))
            saved = int(getattr(self, "_tree_panel_saved_width", 320) or 320)

            is_collapsing = bool(tree.isVisible())
            if is_collapsing:
                # Remember width before collapsing (only if it's a sensible expanded width)
                try:
                    self._remember_tree_panel_width()
                except Exception:
                    pass

                try:
                    tree.setVisible(False)
                except Exception:
                    pass
                try:
                    panel.setMinimumWidth(toggle_w)
                except Exception:
                    pass

                total = sum((split.sizes() or [0, 0]))
                right = max(0, int(total) - toggle_w)
                split.setSizes([toggle_w, right])
                self._set_tree_panel_arrow(collapsed=True)
                return

            # Expanding
            try:
                tree.setVisible(True)
            except Exception:
                pass
            try:
                panel.setMinimumWidth(min_expanded)
            except Exception:
                pass

            restore_w = max(min_expanded, saved)
            total = sum((split.sizes() or [restore_w, 0]))
            right = max(0, int(total) - restore_w)
            split.setSizes([restore_w, right])
            self._set_tree_panel_arrow(collapsed=False)
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
                if projects is None:
                    return
            except Exception:
                return
            cb.blockSignals(True)
            cb.clear()
            cb.addItem(t("common.select_project"), userData=None)
            for p in (projects or []):
                try:
                    project_name = _project_display_name(p)
                    if not project_name:
                        continue
                    cb.addItem(project_name, userData=p.get("id"))
                except Exception:
                    pass
            cb.blockSignals(False)
        except Exception:
            pass

    def adjust_projects_popup(self):
        """Keep popup width reasonable and re-apply popup styling."""
        try:
            self._apply_projects_combo_popup_style()
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

    def _apply_projects_combo_popup_style(self):
        try:
            if hasattr(self, "_prepare_projects_combo_popup"):
                self._prepare_projects_combo_popup()
                return
        except Exception:
            pass

        try:
            cb = getattr(self, "cb_projects", None)
            if cb is None:
                return
            view = cb.view()
            if view is None:
                return
        except Exception:
            return

        try:
            view.setObjectName("projectsComboView")
        except Exception:
            pass
        try:
            vp = view.viewport()
            if vp is not None:
                vp.setObjectName("projectsComboViewport")
        except Exception:
            vp = None

        dark = getattr(self, "_current_theme", THEME_LIGHT) == THEME_DARK
        if dark:
            bg = "#1e1e1e"
            fg = "#e0e0e0"
            hover_bg = "rgba(247, 146, 30, 0.15)"
            sel_bg = "rgba(247, 146, 30, 0.22)"
            sel_hover_bg = "rgba(247, 146, 30, 0.28)"
        else:
            bg = "#FFFFFF"
            fg = "#000000"
            hover_bg = "#FFE3C2"
            sel_bg = "rgba(247, 146, 30, 0.20)"
            sel_hover_bg = "rgba(247, 146, 30, 0.28)"

        qss = f"""
        QListView#projectsComboView::item {{
            margin: 0px;
            padding: 8px 10px;
            background: transparent;
            color: {fg};
            border: 0px;
            border-top: 0px;
            border-bottom: 0px;
            outline: 0;
        }}
        QListView#projectsComboView::item:hover {{
            background: {hover_bg};
            color: {fg};
            border: 0px;
            border-top: 0px;
            border-bottom: 0px;
            outline: 0;
        }}
        QListView#projectsComboView::item:selected {{
            background: {sel_bg};
            color: {fg};
            border: 0px;
            border-top: 0px;
            border-bottom: 0px;
            outline: 0;
        }}
        QListView#projectsComboView::item:selected:hover {{
            background: {sel_hover_bg};
            color: {fg};
            border: 0px;
            border-top: 0px;
            border-bottom: 0px;
            outline: 0;
        }}
        QListView#projectsComboView::item:focus {{
            border: 0px;
            border-top: 0px;
            border-bottom: 0px;
            outline: 0;
        }}
        QListView#projectsComboView::item:selected:active {{
            background: {sel_bg};
            color: {fg};
            border: 0px;
            border-top: 0px;
            border-bottom: 0px;
            outline: 0;
        }}
        QListView#projectsComboView::item:selected:!active {{
            background: {sel_bg};
            color: {fg};
            border: 0px;
            border-top: 0px;
            border-bottom: 0px;
            outline: 0;
        }}
        """.strip()

        try:
            return
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

    def _load_startup_projects_async(self, workspace_id, restore_context=None):
        """Load projects after login while leaving the main window responsive."""
        generation = getattr(self, "_startup_project_load_generation", 0) + 1
        self._startup_project_load_generation = generation
        self._startup_project_load_workspace_id = workspace_id
        self._startup_project_restore_context = (
            dict(restore_context) if isinstance(restore_context, dict) else None
        )

        thread = QThread(self)
        worker = _StartupProjectLoadWorker(self.api, workspace_id, generation)
        worker.moveToThread(thread)
        self._startup_project_load_thread = thread
        self._startup_project_load_worker = worker

        def _cleanup():
            if getattr(self, "_startup_project_load_thread", None) is thread:
                self._startup_project_load_thread = None
                self._startup_project_load_worker = None
            worker.deleteLater()
            thread.deleteLater()

        thread.started.connect(worker.run)
        worker.finished.connect(self._finish_startup_projects_load, Qt.QueuedConnection)
        worker.finished.connect(thread.quit)
        thread.finished.connect(_cleanup)
        thread.start()

    def _finish_startup_projects_load(self, generation, projects, workspace_id=None):
        result = projects if isinstance(projects, dict) and "projects" in projects else None
        if result is not None:
            workspace_id = result.get("workspace_id")
            projects = result.get("projects")
            load_error = result.get("error")
        else:
            load_error = None
        if generation != getattr(self, "_startup_project_load_generation", 0):
            return
        expected_workspace_id = getattr(self, "_startup_project_load_workspace_id", None)
        if (
            workspace_id is not None
            and expected_workspace_id is not None
            and str(workspace_id) != str(expected_workspace_id)
        ):
            return
        if load_error == "workspace_activation":
            self.cb_projects.blockSignals(True)
            self.cb_projects.clear()
            self.cb_projects.addItem(t("common.select_project"), userData=None)
            self.cb_projects.setCurrentIndex(0)
            self.cb_projects.blockSignals(False)
            self.cb_projects.setEnabled(True)
            try:
                self.set_initial_view()
            except Exception:
                pass
            self._end_busy_status(t("workspace.switch_failed"), 5000)
            if isinstance(getattr(self, "_startup_project_restore_context", None), dict):
                self._startup_project_restore_context = None
                self._complete_reconnect_restore(False, t("workspace.switch_failed"))
            return
        confirmed_workspace_id = getattr(getattr(self, "api", None), "selected_workspace_id", None)
        if (
            workspace_id is not None
            and confirmed_workspace_id is not None
            and str(workspace_id) != str(confirmed_workspace_id)
        ):
            return
        if projects is None:
            self.cb_projects.blockSignals(True)
            self.cb_projects.clear()
            self.cb_projects.addItem(t("common.select_project"), userData=None)
            self.cb_projects.setCurrentIndex(0)
            self.cb_projects.blockSignals(False)
            self.cb_projects.setEnabled(True)
            self._end_busy_status(t("status.connection_lost"), 5000)
            if isinstance(getattr(self, "_startup_project_restore_context", None), dict):
                self._startup_project_restore_context = None
                self._complete_reconnect_restore(False, t("status.connection_lost"))
            return

        self.cb_projects.blockSignals(True)
        self.cb_projects.clear()
        self.cb_projects.addItem(t("common.select_project"), userData=None)
        for p in projects:
            p_id = p.get("id") or p.get("project_id") or p.get("projectId")
            project_name = _project_display_name(p)
            if not project_name:
                continue
            self.cb_projects.addItem(project_name, userData=p_id)
        restore_context = getattr(self, "_startup_project_restore_context", None)
        restore_project_id = (
            restore_context.get("project_id") if isinstance(restore_context, dict) else None
        )
        restore_index = -1
        if restore_project_id:
            wanted = normalize_id(restore_project_id)
            for index in range(self.cb_projects.count()):
                if normalize_id(self.cb_projects.itemData(index)) == wanted:
                    restore_index = index
                    break
        self.cb_projects.setCurrentIndex(restore_index if restore_index >= 0 else 0)
        self.cb_projects.blockSignals(False)
        self.cb_projects.setEnabled(True)
        self._end_busy_status(t("common.projects_loaded", count=len(projects)), 3000)

        if not isinstance(restore_context, dict):
            return
        self._startup_project_restore_context = None
        if restore_index < 0:
            try:
                self.set_initial_view()
            except Exception:
                pass
            self._complete_reconnect_restore(False, t("connection.project_unavailable"))
            return

        project_id = self.cb_projects.itemData(restore_index)
        try:
            ok = bool(self.load_tree_for_project(
                project_id,
                hide_connection_panel_on_success=False,
                expanded_folder_ids=restore_context.get("expanded_folder_ids") or set(),
            ))
            if ok:
                folder_context = restore_context.get("folder_context") or {}
                folder_id = folder_context.get("folder_id")
                if folder_id:
                    ok = bool(self.open_folder_node({
                        "type": "folder", "id": folder_id,
                        "name": folder_context.get("name", ""),
                        "projectId": project_id,
                    }, save_to_history=False))
        except Exception:
            ok = False
        self._complete_reconnect_restore(ok, None if ok else t("connection.retry_failed"))

    def _complete_reconnect_restore(self, ok, error_text=None):
        """Finish reconnect only after project and tree restoration completes."""
        dlg = getattr(self, "_connection_dialog", None)
        if ok:
            try:
                self._hide_connection_dialog()
                self.status.showMessage(t("connection.restored"), 3000)
            except Exception:
                pass
        elif dlg is not None:
            try:
                dlg.show_retry_error(error_text or t("connection.retry_failed"))
            except Exception:
                pass
        try:
            if dlg is not None:
                dlg.set_retry_enabled(True, t("connection.retry_button"))
        except Exception:
            pass
        self._reconnect_projects_load_pending = False
        self._reconnect_restore_context = None

    def on_logged_in(self):
        self.btn_login.setVisible(False)
        username = self.api.current_username or "Пользователь"
        self.btn_user.setText(username); self.btn_user.setVisible(True)

        try:
            # Require workspace selection before loading projects.
            settings = load_settings()
            ws_id = settings.get("workspace_id")
            if not ws_id:
                self.cb_projects.blockSignals(True)
                self.cb_projects.clear()
                self.cb_projects.addItem(t("common.select_workspace_first"), userData=None)
                self.cb_projects.setCurrentIndex(0)
                self.cb_projects.blockSignals(False)
                self.cb_projects.setEnabled(False)
                self.status.showMessage(t("project.select_to_load"), 5000)
                return

            self.api.selected_workspace_id = ws_id
            self._begin_busy_status(t("project.activating"))
            self._update_busy_status(t("project.loading"))
            self.cb_projects.setEnabled(False)
            restore_context = getattr(self, "_reconnect_restore_context", None)
            self._reconnect_projects_load_pending = isinstance(restore_context, dict)
            self._load_startup_projects_async(ws_id, restore_context=restore_context)
        except Exception:
            self.cb_projects.setEnabled(True)
            self._end_busy_status(t("status.connection_lost"), 5000)

    def logout_and_relogin(self):
        self.api.logout()
        self.cb_projects.clear()
        self.btn_user.setVisible(False); self.btn_login.setVisible(True)
        self.status.showMessage(t("project.logged_out"), 3000)
        self.set_initial_view()
        try:
            if hasattr(self, '_ensure_default_column_visibility') and callable(self._ensure_default_column_visibility):
                self._ensure_default_column_visibility()
        except Exception:
            pass
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

                    busy_started = False
                    final_msg = ""
                    final_timeout = 0
                    try:
                        self._begin_busy_status(t("project.changing"))
                        busy_started = True

                        # Invalidate any startup response for the previous workspace.
                        self._startup_project_load_generation = getattr(
                            self, "_startup_project_load_generation", 0
                        ) + 1
                        self._startup_project_load_workspace_id = None

                        changed = self.api.change_workspace(new_ws_id)
                        print(f"[WORKSPACE] change_workspace returned: {changed}")

                        if changed:
                            settings["workspace_id"] = new_ws_id
                            save_settings(settings)
                            self.api.selected_workspace_id = new_ws_id
                            self._startup_project_load_workspace_id = new_ws_id

                            self.cb_projects.blockSignals(True)
                            self.cb_projects.clear()
                            self.cb_projects.addItem(t("common.select_project"), userData=None)
                            self.cb_projects.setCurrentIndex(0)
                            self.cb_projects.blockSignals(False)
                            self.cb_projects.setEnabled(False)
                            self.set_initial_view()

                            self._update_busy_status(t("project.reloading"))

                            try:
                                projects = self.api.list_projects()
                                if projects is None:
                                    self.cb_projects.setEnabled(True)
                                    QMessageBox.warning(self, t("common.error"), t("status.connection_lost"))
                                    return
                                print(f"[WORKSPACE] Loaded {len(projects)} projects")

                                self.cb_projects.blockSignals(True)
                                for p in projects:
                                    p_id = p.get("id") or p.get("project_id") or p.get("projectId")
                                    project_name = _project_display_name(p)
                                    if not project_name:
                                        continue
                                    self.cb_projects.addItem(project_name, userData=p_id)
                                self.cb_projects.setCurrentIndex(0)
                                self.cb_projects.blockSignals(False)
                                try:
                                    self.cb_projects.setEnabled(True)
                                except Exception:
                                    pass
                                final_msg = (
                                    t("workspace.no_projects")
                                    if not projects
                                    else t("project.loaded_count", count=len(projects))
                                )
                                final_timeout = 3000
                                self.set_initial_view()
                                try:
                                    if hasattr(self, '_ensure_default_column_visibility') and callable(self._ensure_default_column_visibility):
                                        self._ensure_default_column_visibility()
                                except Exception:
                                    pass
                            except Exception as e:
                                print(f"[WORKSPACE ERROR] Failed to reload projects: {e}")
                                import traceback
                                traceback.print_exc()
                                self.cb_projects.setEnabled(True)
                                final_msg = t("workspace.project_load_status_error")
                                final_timeout = 3000
                                QMessageBox.warning(self, t("common.error"), t("workspace.project_load_error", error=e))
                        else:
                            print(f"[WORKSPACE] change_workspace returned False")
                            final_msg = t("workspace.switch_failed")
                            final_timeout = 3000
                    except Exception as e:
                        print(f"[WORKSPACE ERROR] Failed to change workspace: {e}")
                        import traceback
                        traceback.print_exc()
                        final_msg = t("workspace.switch_status_error")
                        final_timeout = 3000
                        QMessageBox.warning(self, t("common.error"), t("workspace.switch_error", error=e))
                    finally:
                        if busy_started:
                            self._end_busy_status(final_msg, final_timeout)
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
        prev_idx = getattr(self, '_prev_project_idx', -1)
        pid = self.current_project_id()
        if pid:
            try:
                if hasattr(self, '_ensure_default_column_visibility') and callable(self._ensure_default_column_visibility):
                    self._ensure_default_column_visibility()
                else:
                    visible_by_default = {0, 1, 2, 3, 4, 5, 6, 9}
                    for i in range(self.files_model.columnCount()):
                        self.table.setColumnHidden(i, i not in visible_by_default)
            except Exception:
                try:
                    visible_by_default = {0, 1, 2, 3, 4, 5, 6, 9}
                    for i in range(self.files_model.columnCount()):
                        self.table.setColumnHidden(i, i not in visible_by_default)
                except Exception:
                    pass
            ok = self.load_tree_for_project(pid)
            if ok:
                self._prev_project_idx = self.cb_projects.currentIndex()
            else:
                if prev_idx >= 0 and prev_idx < self.cb_projects.count():
                    cb = self.cb_projects
                    cb.blockSignals(True)
                    cb.setCurrentIndex(prev_idx)
                    cb.blockSignals(False)
        else:
            self._prev_project_idx = -1
            self.set_initial_view()
            try:
                if hasattr(self, '_ensure_default_column_visibility') and callable(self._ensure_default_column_visibility):
                    self._ensure_default_column_visibility()
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    # Connection recovery panel
    # ------------------------------------------------------------------ #
    _CONNECTION_MSG = {
        'session_expired': 'connection.session_expired',
        'no_auth': 'connection.session_expired',
        'connection_lost': 'connection.connection_lost',
        'forbidden': 'connection.access_denied',
        'server_error': 'connection.server_error',
        'invalid_response': 'connection.invalid_response',
    }

    def _connection_message_for_error(self, error_code: str) -> str:
        key = self._CONNECTION_MSG.get(error_code, 'connection.connection_lost')
        return t(key)

    # ------------------------------------------------------------------ #
    # Connection error modal dialog (replaces inline panel UX)
    # ------------------------------------------------------------------ #
    class _ConnectionErrorDialog(QDialog):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setModal(True)
            try:
                self.setWindowModality(Qt.ApplicationModal)
            except Exception:
                pass
            self.setAttribute(Qt.WA_QuitOnClose, False)
            self.setWindowTitle(t("connection.dialog_title"))
            self.setMinimumWidth(420)
            try:
                if _is_dark_mode():
                    _set_window_theme_dark(self, dark=True)
            except Exception:
                pass

            self._error_code = None
            self._context = {}

            outer = QVBoxLayout(self)
            outer.setContentsMargins(18, 16, 18, 14)
            outer.setSpacing(10)

            self.lbl_title = QLabel(t("connection.dialog_title"), self)
            f = self.lbl_title.font();
            try:
                f.setPointSize(max(int(f.pointSize()), 11))
                f.setBold(True)
            except Exception:
                pass
            self.lbl_title.setFont(f)
            outer.addWidget(self.lbl_title)

            self.lbl_body = QLabel("", self)
            self.lbl_body.setWordWrap(True)
            self.lbl_body.setTextInteractionFlags(Qt.TextSelectableByMouse)
            outer.addWidget(self.lbl_body)

            self.lbl_error = QLabel("", self)
            self.lbl_error.setWordWrap(True)
            self.lbl_error.setObjectName("connectionDialogError")
            self.lbl_error.hide()
            outer.addWidget(self.lbl_error)

            btn_row = QHBoxLayout()
            btn_row.addStretch(1)
            self.btn_cancel = QPushButton(t("common.cancel"), self)
            self.btn_cancel.setAutoDefault(False)
            self.btn_cancel.setDefault(False)
            self.btn_cancel.setProperty("secondary", True)
            self.btn_retry = QPushButton(t("connection.retry_button"), self)
            self.btn_retry.setAutoDefault(False)
            self.btn_retry.setDefault(True)
            self.btn_retry.setProperty("secondary", True)
            for btn in (self.btn_cancel, self.btn_retry):
                try:
                    btn.style().unpolish(btn)
                    btn.style().polish(btn)
                except Exception:
                    pass
            btn_row.addWidget(self.btn_cancel)
            btn_row.addWidget(self.btn_retry)
            outer.addLayout(btn_row)

            self.btn_cancel.clicked.connect(self.reject)

        def set_error(self, error_code: str, body_text: str, context: dict | None = None) -> None:
            self._error_code = error_code
            self._context = dict(context) if isinstance(context, dict) else {}
            self.lbl_body.setText(body_text or "")
            self.lbl_error.hide()
            self.lbl_error.setText("")

        def set_retry_enabled(self, enabled: bool, text: str | None = None) -> None:
            try:
                self.btn_retry.setEnabled(bool(enabled))
            except Exception:
                pass
            if text is not None:
                try:
                    self.btn_retry.setText(text)
                except Exception:
                    pass

        def show_retry_error(self, text: str) -> None:
            self.lbl_error.setText(text or "")
            self.lbl_error.show() if (text or "").strip() else self.lbl_error.hide()

        def error_code(self) -> str:
            return str(self._error_code or "")

        def context(self) -> dict:
            return dict(self._context or {})

    def _ensure_connection_dialog(self) -> "MainWindow._ConnectionErrorDialog":
        dlg = getattr(self, "_connection_dialog", None)
        try:
            from shiboken6 import isValid  # type: ignore
            if dlg is None or not isValid(dlg):
                dlg = None
        except Exception:
            pass
        if dlg is None:
            dlg = MainWindow._ConnectionErrorDialog(self)
            dlg.btn_retry.clicked.connect(self._on_connection_dialog_retry_clicked)
            self._connection_dialog = dlg
        return dlg

    def _connection_dialog_message_for_error(self, error_code: str) -> str:
        # Prefer new i18n keys; fallback to the existing inline panel keys.
        mapping = {
            'session_expired': 'connection.session_expired',
            'no_auth': 'connection.session_expired',
            'connection_lost': 'connection.connection_lost',
            'server_error': 'connection.server_error',
            'forbidden': 'connection.forbidden',
            'invalid_response': 'connection.invalid_response',
        }
        key = mapping.get(error_code, 'connection.connection_lost')
        return t(key)

    def _show_connection_dialog(self, error_code: str, context: dict = None) -> None:
        try:
            ctx = dict(context) if isinstance(context, dict) else {}
            account_username = (
                str(ctx.get("account_username") or "").strip()
                or str(getattr(getattr(self, "api", None), "current_username", "") or "").strip()
                or str((load_settings() or {}).get("last_username", "") or "").strip()
            )
            if account_username:
                ctx["account_username"] = account_username
        except Exception:
            ctx = dict(context) if context else {}

        # During an explicit reconnect attempt we control the dialog state ourselves.
        if getattr(self, "_reconnect_in_progress", False):
            try:
                self._connection_error_code = error_code
                self._connection_retry_context = dict(ctx) if ctx else {}
            except Exception:
                pass
            return

        try:
            self._connection_error_code = error_code
            self._connection_retry_context = dict(ctx) if ctx else {}
        except Exception:
            self._connection_error_code = error_code
            self._connection_retry_context = {}

        dlg = self._ensure_connection_dialog()
        dlg.setWindowTitle(t("connection.dialog_title"))
        dlg.lbl_title.setText(t("connection.dialog_title"))
        dlg.set_error(error_code, self._connection_dialog_message_for_error(error_code), context=ctx)
        dlg.set_retry_enabled(True, t("connection.retry_button"))
        try:
            # If the old inline panel exists in the UI, ensure it stays hidden.
            if hasattr(self, "connection_panel") and self.connection_panel is not None:
                self.connection_panel.setVisible(False)
        except Exception:
            pass

        # Avoid stacking multiple dialogs.
        try:
            if not dlg.isVisible():
                dlg.show()
                dlg.raise_()
                dlg.activateWindow()
        except Exception:
            try:
                dlg.exec()
            except Exception:
                pass

    def _hide_connection_dialog(self) -> None:
        dlg = getattr(self, "_connection_dialog", None)
        try:
            if dlg is not None and dlg.isVisible():
                dlg.hide()
        except Exception:
            pass

    def _attempt_restore_auth_state(self) -> bool:
        """Best-effort restore auth without clearing UI state.

        IMPORTANT: For session_expired/no_auth we must NOT treat `api._load_auth()` as a valid restore,
        because it may return True after loading an expired access token ("may be expired").
        """
        api = getattr(self, "api", None)
        if api is None:
            return False

        retry_ctx = getattr(self, "_connection_retry_context", {})
        try:
            settings = load_settings()
        except Exception:
            settings = {}

        username = (
            str(getattr(getattr(self, "_connection_dialog", None), "context", lambda: {})().get("account_username", "") or "").strip()
            or str((retry_ctx or {}).get("account_username", "") or "").strip()
            or str(getattr(api, "current_username", "") or "").strip()
            or str((settings or {}).get("last_username", "") or "").strip()
        )
        if not username:
            return False

        # 1) Try refresh token if available (this is the only acceptable auto-restore signal).
        try:
            if str(getattr(api, "current_username", "") or "").strip() == username and getattr(api, "refresh_token", None) and hasattr(api, "_refresh_access_token"):
                if api._refresh_access_token():
                    self.on_logged_in()
                    return True
        except Exception:
            pass

        # 2) Try saved refresh token for the same account.
        try:
            refresh_token = get_credential(username, "refresh_token")
            if refresh_token and hasattr(api, "_refresh_access_token"):
                api.current_username = username
                api.refresh_token = refresh_token
                if api._refresh_access_token():
                    self.on_logged_in()
                    return True
        except Exception:
            pass

        # 3) Do not fallback to `_load_auth()` here: it can report success with an expired access token.
        #    Instead, try a silent re-login using saved password for the same username.
        try:
            password = get_credential(username, "password")
            if not password:
                return False

            if hasattr(api, "login") and api.login(username, password, remember_me=True):
                try:
                    self.on_logged_in()
                except Exception:
                    pass
                return True
        except Exception:
            pass

        return False

    def _attempt_interactive_login(self) -> bool:
        """Open the existing login dialog. Returns True if accepted and session is usable."""
        try:
            retry_ctx = getattr(self, "_connection_retry_context", {}) or {}
            preset_username = str(retry_ctx.get("account_username", "") or getattr(self.api, "current_username", "") or (load_settings() or {}).get("last_username", "") or "").strip()
            dlg = LoginDialog(self.api, self, preset_username=preset_username)
            ret = dlg.exec()
            if ret != QDialog.Accepted:
                return False
            try:
                self.on_logged_in()
            except Exception:
                pass
            return True
        except Exception:
            return False

    def _refresh_after_reconnect(self) -> bool:
        """Reload current project/folder using the saved retry context."""
        try:
            # Reuse the existing retry context logic (tree/folder restore).
            return bool(self._retry_current_connection_context())
        except Exception:
            return False

    def _on_connection_dialog_retry_clicked(self) -> None:
        if getattr(self, '_reconnect_in_progress', False):
            return

        dlg = getattr(self, "_connection_dialog", None)
        if dlg is None:
            return

        self._reconnect_in_progress = True
        try:
            from larix_nexus.ui.tree_operations import _capture_tree_expanded_folder_ids
            expanded = _capture_tree_expanded_folder_ids(getattr(self, "tree", None))
        except Exception:
            expanded = set()
        try:
            settings = load_settings() or {}
            workspace_id = getattr(self.api, "selected_workspace_id", None) or settings.get("workspace_id")
        except Exception:
            workspace_id = getattr(self.api, "selected_workspace_id", None)
        self._reconnect_restore_context = {
            "workspace_id": workspace_id,
            "project_id": self.current_project_id(),
            "folder_context": dict(getattr(self, "_current_folder_context", {}) or {}),
            "expanded_folder_ids": expanded,
        }
        dlg.set_retry_enabled(False, t("connection.reconnecting"))
        try:
            QApplication.processEvents()
        except Exception:
            pass

        ok = False
        try:
            err = str(getattr(self, "_connection_error_code", "") or "")

            # For expired/no_auth we must restore auth first.
            if err in ("session_expired", "no_auth"):
                if not self._attempt_restore_auth_state():
                    if not self._attempt_interactive_login():
                        dlg.show_retry_error(t("connection.login_required"))
                        return

            # Auth restoration starts the project worker. Its callback owns the
            # rest of reconnect, so do not race it with a tree refresh here.
            if getattr(self, "_reconnect_projects_load_pending", False):
                ok = None
            else:
                ok = self._refresh_after_reconnect()
        finally:
            if ok is None:
                pass
            elif ok:
                try:
                    self._hide_connection_dialog()
                except Exception:
                    pass
                try:
                    self.status.showMessage(t("connection.restored"), 3000)
                except Exception:
                    pass
            elif ok is False:
                try:
                    # Keep dialog open and show a specific failure message.
                    err_now = str(getattr(self, "_connection_error_code", "") or "")
                    if err_now in ("session_expired", "no_auth"):
                        dlg.set_error(err_now, self._connection_dialog_message_for_error(err_now), context=dlg.context())
                        dlg.show_retry_error(t("connection.login_required"))
                    else:
                        dlg.show_retry_error(t("connection.retry_failed"))
                except Exception:
                    pass
            try:
                dlg.set_retry_enabled(True, t("connection.retry_button"))
            except Exception:
                pass
            self._reconnect_in_progress = False

    def _show_connection_panel(self, error_code: str, context: dict = None):
        # Legacy inline panel is replaced by a modal dialog.
        try:
            self._show_connection_dialog(error_code, context=context)
        except Exception:
            pass

    def _hide_connection_panel(self):
        try:
            self.connection_panel.setVisible(False)
            self._connection_error_code = None
            self._connection_retry_context = None
            self._reconnect_in_progress = False
            try:
                self._hide_connection_dialog()
            except Exception:
                pass
        except Exception:
            pass

    def _set_connection_reconnecting(self, on: bool):
        try:
            self._reconnect_in_progress = on
            self.btn_connection_retry.setEnabled(not on)
            self.btn_connection_login.setEnabled(not on)
            if on:
                self.btn_connection_retry.setText(t("connection.reconnecting"))
            else:
                self.btn_connection_retry.setText(t("connection.retry"))
        except Exception:
            pass

    def _on_connection_retry_clicked(self):
        if getattr(self, '_reconnect_in_progress', False):
            return
        self._set_connection_reconnecting(True)
        try:
            ok = self._retry_current_connection_context()
        except Exception:
            ok = False
        self._set_connection_reconnecting(False)
        if ok:
            self._hide_connection_panel()
            try:
                self.status.showMessage(t("connection.restored"), 3000)
            except Exception:
                pass
        else:
            msg = t("connection.retry_failed")
            self.connection_text.setText(msg)

    def _on_connection_login_clicked(self):
        if getattr(self, '_reconnect_in_progress', False):
            return
        try:
            self._hide_connection_panel()
            self.logout_and_relogin()
        except Exception:
            pass

    def _retry_current_connection_context(self) -> bool:
        ctx = getattr(self, '_connection_retry_context', {})
        if not isinstance(ctx, dict):
            ctx = {}
        kind = ctx.get('kind', '')
        pid = ctx.get('project_id')
        if not pid:
            current_pid = self.current_project_id()
            if current_pid:
                pid = current_pid
                kind = 'tree'
            else:
                return False

        if kind == 'tree' and pid:
            ok = self.load_tree_for_project(pid, hide_connection_panel_on_success=False)
            if not ok:
                return False
            folder_ctx = getattr(self, '_current_folder_context', {})
            fid = folder_ctx.get('folder_id') if folder_ctx else None
            if fid:
                ctx_pid = str(folder_ctx.get('project_id', '')) if folder_ctx else ''
                if str(pid) == ctx_pid or normalize_id(pid) == normalize_id(ctx_pid):
                    try:
                        node = {"type": "folder", "id": fid,
                                "name": folder_ctx.get('name', ''),
                                "projectId": pid}
                        folder_ok = self.open_folder_node(node, save_to_history=False)
                    except Exception:
                        folder_ok = False
                    if not folder_ok:
                        return False
            try:
                self._hide_connection_panel()
            except Exception:
                pass
            return True

        if kind == 'folder' and pid:
            ok = self.load_tree_for_project(pid, hide_connection_panel_on_success=False)
            if not ok:
                return False
            folder_ctx = ctx.get('folder_context') or {}
            fid = folder_ctx.get('folder_id') or folder_ctx.get('id')
            if fid:
                ctx_pid = str(folder_ctx.get('project_id', '')) if folder_ctx else ''
                if str(pid) == ctx_pid or normalize_id(pid) == normalize_id(ctx_pid):
                    try:
                        node = {"type": "folder", "id": fid,
                                "name": folder_ctx.get('name', ''),
                                "projectId": pid}
                        folder_ok = self.open_folder_node(node, save_to_history=False)
                    except Exception:
                        folder_ok = False
                    if not folder_ok:
                        return False
            try:
                self._hide_connection_panel()
            except Exception:
                pass
            return True

        current_pid = self.current_project_id()
        if current_pid:
            return self.load_tree_for_project(current_pid, hide_connection_panel_on_success=False)
        return False

    def _save_current_folder_context(self, node: dict = None, project_id=None):
        try:
            if node and isinstance(node, dict):
                self._current_folder_context = {
                    'folder_id': node.get('id') or node.get('folderId'),
                    'name': node.get('name') or node.get('title') or '',
                    'project_id': project_id or node.get('projectId') or node.get('project_id') or self.current_project_id(),
                }
            else:
                try:
                    item = self.tree.currentItem()
                except Exception:
                    item = None
                if item:
                    fid = None
                    try:
                        from ..utils.helpers import normalize_id
                        fid = normalize_id(item.data(0, Qt.UserRole + 1))
                    except Exception:
                        fid = None
                    ndata = item.data(0, Qt.UserRole) if item else None
                    pname = item.text(0) if item else ''
                    self._current_folder_context = {
                        'folder_id': fid,
                        'name': pname or (ndata.get('name') if isinstance(ndata, dict) else ''),
                        'project_id': project_id or self.current_project_id(),
                    }
                else:
                    self._current_folder_context = {
                        'folder_id': None,
                        'name': '',
                        'project_id': project_id or self.current_project_id(),
                    }
        except Exception:
            self._current_folder_context = {}

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

    def _build_notification_file_state(
        self,
        project_id: int | str,
        folder_id: int | str,
        folder_path: str,
        force_fresh: bool = False,
        strict: bool = False,
    ) -> list[dict]:
        """Get current file state for notifications using cloud API.

        Returns list of {id, name, updatedAt, path, type} entries compatible with compare_file_states.

        Args:
            force_fresh: If True, bypass API cache to get fresh data.
        """
        files = []
        build_error = None
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
            build_error = e

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
        if strict and build_error is not None:
            raise RuntimeError("Unable to refresh notification baseline") from build_error
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

    def _selection_mode_active(self) -> bool:
        return bool(getattr(self, "checked", None))

    def _clear_row_selection_for_selection_mode(self):
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

    def _toggle_checked_from_checkbox_click(self, proxy_index):
        if not proxy_index or not proxy_index.isValid():
            return False

        clicked_row = proxy_index.row()
        if clicked_row < 0:
            return False

        active_before = self._selection_mode_active()
        handled = False

        if not active_before:
            try:
                sm = self.table.selectionModel()
                selected_rows = [idx.row() for idx in (sm.selectedRows() if sm else []) if idx.isValid()]
            except Exception:
                selected_rows = []

            if len(selected_rows) > 1 and clicked_row in selected_rows:
                for row in sorted(set(selected_rows)):
                    self._toggle_checked_for_proxy_row(row, True)
                handled = True

        if not handled:
            handled = self._toggle_checked_for_proxy_row(clicked_row)

        if handled and self._selection_mode_active():
            self._selection_mode_anchor_row = clicked_row
            self._clear_row_selection_for_selection_mode()
        return handled

    def _toggle_checked_for_proxy_row(self, proxy_row, checked=None):
        if proxy_row is None or proxy_row < 0:
            return False
        idx = self.proxy.index(proxy_row, 0)
        if not idx.isValid():
            return False
        current = self.proxy.data(idx, Qt.CheckStateRole)
        if checked is None:
            new_state = Qt.Unchecked if current == Qt.Checked else Qt.Checked
        else:
            new_state = Qt.Checked if checked else Qt.Unchecked
        changed = self.proxy.setData(idx, new_state, Qt.CheckStateRole)
        if changed:
            try:
                self.update_header_checkbox()
            except Exception:
                pass
            try:
                self._update_actions_enabled()
            except Exception:
                pass
            try:
                self._update_selection_mode_panel()
            except Exception:
                pass
        return bool(changed)

    def _clear_checked_selection(self):
        try:
            self.set_all_visible_checked(False)
        except Exception:
            try:
                self.checked.clear()
            except Exception:
                pass
        self._selection_mode_anchor_row = None
        self._clear_row_selection_for_selection_mode()
        try:
            self.update_header_checkbox()
        except Exception:
            pass
        try:
            self._update_actions_enabled()
        except Exception:
            pass
        self._update_selection_mode_panel()

    def _update_selection_mode_panel(self):
        panel = getattr(self, "selection_mode_panel", None)
        active = self._selection_mode_active()
        indicator = getattr(self, "selection_mode_indicator", None)
        if indicator is not None:
            indicator.setToolTip(t("selection_mode.hint"))
            indicator.setVisible(active)
            indicator.setChecked(active)
            indicator.style().unpolish(indicator)
            indicator.style().polish(indicator)
            indicator.update()
        if panel is not None:
            # Kept as a compatibility object for callers, but never part of
            # the right-side layout and never allowed to reserve a row.
            self.selection_mode_label.setText(t("selection_mode.hint"))
            panel.setVisible(False)

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

    def get_action_selected_items(self):
        """Return the items used by file actions: checks first, then rows."""
        try:
            checked = self.get_checked_visible_items() or []
        except Exception:
            checked = []
        if checked:
            return checked
        try:
            return self.get_selected_items() or []
        except Exception:
            return []

    def download_checked(self):
        items = self._chosen_items_for_download()
        if items and hasattr(self, "_build_structure_download_tasks") and hasattr(self, "_start_zip_batch"):
            mode = getattr(self, "_force_mode", None)
            if mode is None:
                mode = self._ask_mode(
                    t("download.title_plural"),
                    t("structure.title"),
                    t("zip.title"),
                )
            if mode == "B":
                return self._start_zip_batch(items)
            if mode == "A":
                dest_dir = self._pick_directory_showing_files(t("structure.where_save"))
                if not dest_dir:
                    return
                tasks = self._build_structure_download_tasks(items, dest_dir)
                if not tasks:
                    return QMessageBox.information(self, t("structure.title"), t("download.no_files"))
                return self._start_structure_download_batch(tasks, dest_dir)

        # Глобальная защита от двойного запуска
        # ensure menu actions handle any reentrancy; no global guard here
        try:
            items = self.get_checked_visible_items()
        except Exception:
            items = []
        if not items:
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
                def_name = _sanitize_filename(it.get("name") or it.get("fileName") or it.get("originalName") or f"file_{it.get('id')}.bin")
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
                    self._copy_file_atomically(local, save_path)
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
                            self._download_failure(result, it.get("name") or it.get("fileName") or "file", "download_failed")
                            continue
                        fname = it.get("name") or it.get("fileName") or it.get("originalName") or f"file_{it.get('id')}.bin"
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
                    result = self._new_download_result()
                    for it in files:
                        result["total"] += 1
                        _prev = getattr(self, "_force_mode", None); self._force_mode = "A"
                        try:
                            local = self.ensure_downloaded(it)
                        finally:
                            self._force_mode = _prev
                        if not local:
                            self._download_failure(result, it.get("name") or it.get("fileName") or "file", "download_failed")
                            continue
                        fname = it.get("name") or it.get("fileName") or it.get("originalName") or f"file_{it.get('id')}.bin"
                        arc = fname
                        if arc in used:
                            base, ext = os.path.splitext(fname); k = 1
                            while f"{base} ({k}){ext}" in used:
                                k += 1
                            arc = f"{base} ({k}){ext}"
                        used.add(arc)
                        zf.write(local, arcname=arc)
                        result["succeeded"] += 1
                    self._report_download_result(result, "zip.title", "zip.created", save_path)
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
                result = self._new_download_result()
                try:
                    for i, fd in enumerate(folders):
                        self.progress.setValue(i+1)
                        self._merge_download_result(result, self._copy_folder_into(fd, dest_dir))
                    self._report_download_result(result, "structure.title", "structure.done")
                finally:
                    self._set_progress_visible(False)
                return
            else:
                default = t("zip.folder_prefix", date=datetime.now().strftime('%Y%m%d_%H%M'))
                save_path, _ = QFileDialog.getSaveFileName(self, t("zip.save_title"), default, t("download.all_files") + ";;ZIP (*.zip)")
                if not save_path:
                    return
                self._set_progress_visible(True); self.progress.setRange(0, 0); QApplication.processEvents()
                result = self._new_download_result()
                try:
                    with zipfile.ZipFile(save_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                        for fd in folders:
                            self._merge_download_result(result, self._zip_folder_into(fd, zf, arc_prefix=""))
                    self._report_download_result(result, "zip.title", "zip.created", save_path)
                except Exception as e:
                    QMessageBox.warning(self, t("zip.title"), t("zip.failed", error=e))
                finally:
                    self._set_progress_visible(False)
                return

        # смешанный набор
        mode = getattr(self, "_force_mode", None) or self._ask_mode(t("download.title_plural"), t("structure.title"), t("zip.title"))
        result = self._new_download_result()
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
                        result["total"] += 1
                        _prev = getattr(self, "_force_mode", None); self._force_mode = "A"
                        try:
                            local = self.ensure_downloaded(it)
                        finally:
                            self._force_mode = _prev
                        if not local:
                            self._download_failure(result, it.get("name") or it.get("fileName") or "file", "download_failed")
                            continue
                        fname = it.get("name") or it.get("fileName") or it.get("originalName") or f"file_{it.get('id')}.bin"
                        dst = os.path.join(base_dir, self._unique_name(base_dir, fname))
                        try:
                            shutil.copyfile(local, dst)
                            result["succeeded"] += 1
                        except Exception as exc:
                            self._download_failure(result, fname, type(exc).__name__)
                    else:
                        self._merge_download_result(result, self._copy_folder_into(it, base_dir))
                self._report_download_result(result, "structure.title", "structure.done")
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
                        result["total"] += 1
                        _prev = getattr(self, "_force_mode", None); self._force_mode = "A"
                        try:
                            local = self.ensure_downloaded(it)
                        finally:
                            self._force_mode = _prev
                        if not local:
                            self._download_failure(result, it.get("name") or it.get("fileName") or "file", "download_failed")
                            continue
                        fname = it.get("name") or it.get("fileName") or it.get("originalName") or f"file_{it.get('id')}.bin"
                        dst = os.path.join(base_dir, self._unique_name(base_dir, fname))
                        try:
                            shutil.copyfile(local, dst)
                            result["succeeded"] += 1
                        except Exception as exc:
                            self._download_failure(result, it.get("name") or it.get("fileName") or "file", type(exc).__name__)
                    else:
                        self._merge_download_result(result, self._copy_folder_into(it, base_dir))
                self._report_download_result(result, "structure.title", "structure.done")
            finally:
                self._set_progress_visible(False)
        else:
            default = t("download.default_zip_name", date=datetime.now().strftime('%Y%m%d_%H%M'))
            save_path, _ = QFileDialog.getSaveFileName(self, t("zip.save_title"), default, f"{t('download.all_files')};;ZIP (*.zip)")
            if not save_path:
                return
            self._set_progress_visible(True); self.progress.setRange(0, 0); QApplication.processEvents()
            result = self._new_download_result()
            try:
                with zipfile.ZipFile(save_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    used = set()
                    for it in items:
                        if it.get("type") == "file":
                            result["total"] += 1
                            fname = it.get("name") or it.get("fileName") or it.get("originalName") or f"file_{it.get('id')}.bin"
                            _prev = getattr(self, "_force_mode", None); self._force_mode = "A"
                            try:
                                local = self.ensure_downloaded(it)
                            finally:
                                self._force_mode = _prev
                            if not local:
                                self._download_failure(result, fname, "download_failed")
                                continue
                            arc = fname
                            if arc in used:
                                base, ext = os.path.splitext(fname); k = 1
                                while f"{base} ({k}){ext}" in used: k += 1
                                arc = f"{base} ({k}){ext}"
                            used.add(arc)
                            zf.write(local, arcname=arc)
                            result["succeeded"] += 1
                        else:
                            self._merge_download_result(result, self._zip_folder_into(it, zf, arc_prefix=""))
                self._report_download_result(result, "zip.title", "zip.created", save_path)
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
                    # In flat view some items may not have a stable `id` field.
                    # Do not collapse distinct rows into one when id is missing.
                    _id = it.get("id")
                    key = (it.get("type"), _id if _id not in (None, "") else ("__noid__", id(it)))
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
            text = t("common.download")
            act_files = menu.addAction(text)
            act_files.setEnabled(bool(items))
            act_files.triggered.connect(self.action_download)

            act_zip = menu.addAction(t("context.download_as_zip"))
            act_zip.setEnabled(bool(items))
            act_zip.triggered.connect(self.action_download_zip)

        except Exception as e:
            print(f"[REFRESH_DOWNLOAD_MENU] ERROR: {e}")

    # --- Действия из выпадающего меню "Скачать" ---

    class _BatchDownloadWorker(QtCore.QObject):
        sig_started = QtCore.Signal(int)  # total
        sig_item_started = QtCore.Signal(str, int, int)  # key, index, total
        sig_item_done = QtCore.Signal(str, str)  # key, target_name
        sig_item_failed = QtCore.Signal(str, str, str)  # key, target_name, error
        sig_progress = QtCore.Signal(int, int)  # done, total
        sig_finished = QtCore.Signal(int, int, list, bool)  # ok_count, total, errors, cancelled

        def __init__(self, api: APIClient, tasks: list[dict], dest_dir: str):
            super().__init__()
            self._api = api
            self._tasks = list(tasks or [])
            self._dest_dir = str(dest_dir or "")
            self._cancelled = False
            self._cancel_event = threading.Event()

        @QtCore.Slot()
        def cancel(self):
            self._cancelled = True
            self._cancel_event.set()

        @QtCore.Slot()
        def run(self):
            total = len(self._tasks)
            ok_count = 0
            done = 0
            errors: list[str] = []
            try:
                self.sig_started.emit(total)
            except Exception:
                pass

            for idx, task in enumerate(self._tasks, start=1):
                if self._cancel_event.is_set():
                    break
                key = str(task.get("key") or f"task_{idx}")
                file_id = task.get("file_id")
                target_name = str(task.get("target_name") or "")
                target_path = str(task.get("target_path") or "")

                if self._cancel_event.is_set():
                    break

                try:
                    self.sig_item_started.emit(key, idx, total)
                except Exception:
                    pass

                if not file_id:
                    err = "missing file id"
                    errors.append(target_name or key)
                    try:
                        self.sig_item_failed.emit(key, target_name, err)
                    except Exception:
                        pass
                    done += 1
                    try:
                        self.sig_progress.emit(done, total)
                    except Exception:
                        pass
                    continue

                if not target_path:
                    err = "missing target path"
                    errors.append(target_name or key)
                    try:
                        self.sig_item_failed.emit(key, target_name, err)
                    except Exception:
                        pass
                    done += 1
                    try:
                        self.sig_progress.emit(done, total)
                    except Exception:
                        pass
                    continue

                part_path = target_path + ".part"
                try:
                    os.makedirs(os.path.dirname(target_path) or self._dest_dir or ".", exist_ok=True)
                except Exception:
                    pass

                try:
                    # Stream directly into final destination via .part + atomic replace.
                    with open(part_path, "wb") as fp:
                        ok = bool(
                        self._api.write_file_to(
                            file_id, fp, cancel_event=self._cancel_event
                        )
                    )
                        if self._cancel_event.is_set():
                            raise RuntimeError("cancelled")
                        if not ok:
                            raise RuntimeError("download failed")
                    try:
                        os.replace(part_path, target_path)
                    except Exception:
                        # Fallback for cross-volume or locked cases.
                        if os.path.exists(target_path):
                            os.remove(target_path)
                        os.rename(part_path, target_path)
                    ok_count += 1
                    try:
                        self.sig_item_done.emit(key, target_name)
                    except Exception:
                        pass
                except Exception as e:
                    errors.append(target_name or key)
                    try:
                        self.sig_item_failed.emit(key, target_name, str(e))
                    except Exception:
                        pass
                    try:
                        if os.path.exists(part_path):
                            os.remove(part_path)
                    except Exception:
                        pass

                done += 1
                try:
                    self.sig_progress.emit(done, total)
                except Exception:
                    pass

            try:
                self.sig_finished.emit(ok_count, total, errors, self._cancel_event.is_set())
            except Exception:
                pass

    def action_download(self):
        """Download the current selection flat, or preserve folder structure."""
        items = self._chosen_items_for_download()
        if not any(_is_folder(item) for item in items):
            return self.action_download_files()

        dest_dir = self._pick_directory_showing_files(t("structure.where_save"))
        if not dest_dir:
            return
        tasks = self._build_structure_download_tasks(items, dest_dir)
        if not tasks:
            return QMessageBox.information(
                self, t("structure.title"), t("download.no_files")
            )
        return self._start_structure_download_batch(tasks, dest_dir)

    def action_download_files(self):
        """Сохраняет только файлы (каждый отдельно). Папки игнорируются."""
        if bool(getattr(self, "_dl_busy", False)):
            QMessageBox.information(self, t("download.title"), t("common.loading"))
            return
        self._dl_busy = True
        release_operation = getattr(self, "_release_file_operation", None)

        def _release_download_slot():
            if release_operation is not None:
                release_operation("download")

        acquire_operation = getattr(self, "_try_acquire_file_operation", None)
        if acquire_operation is not None and not acquire_operation("download"):
            self._dl_busy = False
            _release_download_slot()
            return

        def _file_id(it: dict) -> str:
            try:
                return normalize_id(it.get("id") or it.get("documentId") or it.get("document_id"))
            except Exception:
                try:
                    return str(it.get("id") or it.get("documentId") or "").strip()
                except Exception:
                    return ""

        def _file_name(it: dict) -> str:
            try:
                return str(it.get("name") or it.get("fileName") or it.get("originalName") or "").strip()
            except Exception:
                return ""

        try:
            items = self._chosen_items_for_download()
            files = [it for it in items if _is_file(it)]

            # Flat-view compatibility: some API payloads use documentId/document_id instead of id.
            for it in files:
                try:
                    if isinstance(it, dict) and not it.get("id"):
                        it["id"] = it.get("documentId") or it.get("document_id")
                except Exception:
                    pass

            # De-dupe only when we have a stable id; otherwise keep distinct rows.
            seen = set(); _files = []
            for it in files:
                fid = _file_id(it)
                key = (it.get("type"), fid if fid else ("__noid__", id(it)))
                if key in seen:
                    continue
                seen.add(key); _files.append(it)
            files = _files

            try:
                sample = [( _file_id(it), _file_name(it)) for it in files[:5]]
                sync_log(
                    "DL_FILES: chosen_items={} files_after_is_file={} sample={}",
                    len(items) if isinstance(items, list) else -1,
                    len(files),
                    sample,
                    component="UI",
                    op="download_files",
                )
            except Exception:
                pass
        except Exception as e:
            try:
                sync_log("DL_FILES: error building file list: {}", str(e), component="UI", op="download_files", result="error")
            except Exception:
                pass
            QMessageBox.warning(self, t("download.title"), t("common.error") + f": {e}")
            self._dl_busy = False
            _release_download_slot()
            return

        if len(files) > 1:
            release_busy = True
            try:
                dest_dir = self._pick_directory_showing_files(t("download.where_save"))
                try:
                    sync_log("DL_FILES: dest_dir={!r}", dest_dir, component="UI", op="download_files")
                except Exception:
                    pass

                if not dest_dir:
                    self._dl_busy = False
                    return

                total = len(files)
                icon_provider = getattr(self, "icon_provider", None)
                dlg = BatchDownloadDialog(
                    self, total, icon_provider, operation_mode="download_to_folder"
                )

                tasks: list[dict] = []
                conflicts = 0
                immediate_errors = 0
                for idx, it in enumerate(files):
                    fid = _file_id(it)
                    raw_name = _file_name(it) or (f"file_{fid}.bin" if fid else f"file_{idx + 1}.bin")
                    base_name = _sanitize_filename(raw_name)
                    key = f"{fid or 'noid'}_{idx}"
                    target_path = os.path.join(dest_dir, base_name)
                    conflict = bool(fid) and os.path.exists(target_path)
                    task = {
                        "key": key,
                        "item": it,
                        "file_id": fid,
                        "base_name": base_name,
                        "target_name": base_name,
                        "target_path": target_path,
                        "conflict": conflict,
                    }
                    tasks.append(task)
                    dlg.add_entry(key, it, base_name)

                    if not fid:
                        immediate_errors += 1
                        dlg.set_status(key, "error", "missing file id")
                    elif conflict:
                        conflicts += 1
                        dlg.set_status(key, "queued", t("download.file_exists"))
                    else:
                        dlg.set_status(key, "queued", t("download.status_queued"))

                dlg.set_total_conflicts(conflicts)
                dlg.show()
                QApplication.processEvents()
                dlg.update_progress(0, total)

                # Resolve name conflicts on the GUI thread before starting the worker.
                apply_all_choice: str | None = None
                conflicts_left = conflicts
                cancelled = False
                for task in tasks:
                    if dlg.was_cancelled():
                        cancelled = True
                        break
                    if not task.get("file_id"):
                        continue
                    if not task.get("conflict"):
                        continue

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
                        task["target_path"] = os.path.join(dest_dir, new_name)
                        dlg.set_name(task["key"], new_name)
                    else:
                        # replace: keep the same name/path
                        pass

                    conflicts_left = max(0, conflicts_left - 1)
                    if conflicts_left == 0:
                        try:
                            dlg.conflict_label.setText("")
                        except Exception:
                            pass

                if cancelled or dlg.was_cancelled():
                    dlg.finish(t("download.cancelled"))
                    try:
                        self.status.showMessage(t("download.cancelled"), 5000)
                    except Exception:
                        pass
                    return

                # Run the actual downloads off the GUI thread.
                download_tasks = [t for t in tasks if t.get("file_id")]
                thread = QtCore.QThread(self)
                worker = MainWindow._BatchDownloadWorker(self.api, download_tasks, dest_dir)
                worker.moveToThread(thread)

                def _on_cancel():
                    try:
                        dlg.btn_cancel.setEnabled(False)
                        dlg.btn_cancel.setText(t("status.cancelling"))
                    except Exception:
                        pass
                    try:
                        dlg._cancel()
                    except Exception:
                        pass

                def _wrap_close_event(orig):
                    def _ce(ev):
                        # While batch is running, treat window-close as cancel.
                        try:
                            if bool(getattr(dlg, "_allow_close", False)):
                                return orig(ev)
                            _on_cancel()
                            ev.ignore()
                            return
                        except Exception:
                            try:
                                return orig(ev)
                            except Exception:
                                return
                    return _ce

                try:
                    dlg.closeEvent = _wrap_close_event(dlg.closeEvent)
                except Exception:
                    pass

                try:
                    dlg.btn_cancel.clicked.disconnect()
                except Exception:
                    pass
                try:
                    dlg.btn_cancel.clicked.connect(_on_cancel)
                except Exception:
                    pass

                class _FilesGuiReceiver(QtCore.QObject):
                    """Deliver ordinary batch download updates in the GUI thread."""

                    def __init__(self, window, dialog, batch_tasks, batch_thread, immediate_error_count):
                        super().__init__(window)
                        self._window = window
                        self._dialog = dialog
                        self._tasks = batch_tasks
                        self._thread = batch_thread
                        self._immediate_error_count = immediate_error_count

                    @QtCore.Slot(str, int, int)
                    def on_item_started(self, key, index, total):
                        self._dialog.set_active(key, True)
                        self._dialog.set_status(
                            key, "process", t("download.status_downloading")
                        )
                        self._dialog.set_current_file(
                            self._tasks[index - 1]["target_name"]
                            if 0 < index <= len(self._tasks)
                            else "",
                            "downloading",
                        )
                        self._dialog.update_progress(index - 1, total)

                    @QtCore.Slot(str, str)
                    def on_item_done(self, key, target_name):
                        self._dialog.set_status(
                            key, "ok", t("download.status_downloaded")
                        )
                        self._dialog.set_active("", False)

                    @QtCore.Slot(str, str, str)
                    def on_item_failed(self, key, target_name, error):
                        self._dialog.set_status(
                            key, "error", error or t("download.download_failed")
                        )
                        self._dialog.set_active("", False)

                    @QtCore.Slot(int, int)
                    def on_progress(self, done, total):
                        self._dialog.update_progress(done, total)

                    @QtCore.Slot(int, int, list, bool)
                    def on_finished(self, ok_count, total, errors, was_cancelled):
                        if was_cancelled:
                            text = t("download.cancelled")
                        elif errors or self._immediate_error_count:
                            text = t("download.partial", ok=ok_count, total=total)
                        else:
                            text = t("download.done", count=ok_count)
                        self._dialog.finish(text)
                        try:
                            if was_cancelled:
                                self._window.status.showMessage(
                                    t("download.cancelled"), 5000
                                )
                            else:
                                self._window.status.showMessage(
                                    t("download.done", count=f"{ok_count} / {total}"),
                                    6000,
                                )
                        except Exception:
                            pass
                        self._thread.quit()

                controller = _FilesGuiReceiver(
                    self, dlg, tasks, thread, immediate_errors
                )
                dlg.cancel_requested.connect(worker.cancel, QtCore.Qt.DirectConnection)
                self._download_files_controller = controller
                self._download_files_thread = thread
                self._download_files_worker = worker

                worker.sig_item_started.connect(controller.on_item_started, QtCore.Qt.QueuedConnection)
                worker.sig_item_done.connect(controller.on_item_done, QtCore.Qt.QueuedConnection)
                worker.sig_item_failed.connect(controller.on_item_failed, QtCore.Qt.QueuedConnection)
                worker.sig_progress.connect(controller.on_progress, QtCore.Qt.QueuedConnection)
                worker.sig_finished.connect(controller.on_finished, QtCore.Qt.QueuedConnection)

                thread.started.connect(worker.run)
                thread.finished.connect(worker.deleteLater)
                thread.finished.connect(controller.deleteLater)
                thread.finished.connect(thread.deleteLater)

                def _clear_download_files_refs():
                    self._download_files_controller = None
                    self._download_files_worker = None
                    self._download_files_thread = None
                    self._dl_busy = False
                    _release_download_slot()

                thread.finished.connect(_clear_download_files_refs)
                release_busy = False
                thread.start()

                return
            except Exception as e:
                try:
                    sync_log("DL_FILES: batch download failed before start: {}", str(e), component="UI", op="download_files", result="error")
                except Exception:
                    pass
                QMessageBox.warning(self, t("download.title"), t("common.error") + f": {e}")
            finally:
                if release_busy:
                    self._dl_busy = False

        if len(files) == 1:
            it = files[0]
            def_name = _sanitize_filename(it.get("name") or it.get("fileName") or it.get("originalName") or f"file_{it.get('id')}.bin")
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
            ok_msg = False
            try:
                self._copy_file_atomically(local, save_path)
                ok_msg = True
            except Exception as e:
                QMessageBox.warning(self, t("download.downloading_file"), t("download.file_save_failed", error=e))
            try:
                self._set_progress_visible(False)
                self.status.clearMessage()
            except Exception:
                pass
        if ok_msg:
            QMessageBox.information(self, t("download.complete"), t("download.done", count=1))
        self._dl_busy = False
        _release_download_slot()
        return

        QMessageBox.information(self, t("download.files"), t("download.no_files"))
        self._dl_busy = False
        return

    def _build_structure_download_tasks(self, items, dest_dir):
        """Flatten files/folders into unique relative download targets."""
        tasks = []
        used_paths = set()

        def unique_path(relative_path):
            relative_path = relative_path.replace("\\", "/")
            if relative_path not in used_paths:
                used_paths.add(relative_path)
                return relative_path
            base, ext = os.path.splitext(relative_path)
            suffix = 2
            candidate = f"{base} ({suffix}){ext}"
            while candidate in used_paths:
                suffix += 1
                candidate = f"{base} ({suffix}){ext}"
            used_paths.add(candidate)
            return candidate

        def visit(node, relative=""):
            if not isinstance(node, dict):
                return
            if node.get("type") == "file":
                name = _sanitize_filename(
                    node.get("originalName") or node.get("name") or node.get("title") or "untitled"
                )
                relative_path = unique_path(os.path.join(relative, name) if relative else name)
                tasks.append(
                    {
                        "key": f"structure-{len(tasks)}",
                        "item": node,
                        "file_id": node.get("id"),
                        "target_name": relative_path,
                        "target_path": os.path.join(dest_dir, relative_path),
                    }
                )
                return
            for child in node.get("children") or []:
                if not isinstance(child, dict):
                    continue
                if child.get("type") == "folder":
                    folder_name = _sanitize_filename(
                        child.get("name") or child.get("title") or "untitled"
                    )
                    folder_path = unique_path(os.path.join(relative, folder_name) if relative else folder_name)
                    # The folder marker is reserved only to make duplicate roots unique;
                    # files themselves remain the units shown in the progress dialog.
                    visit(child, folder_path)
                else:
                    visit(child, relative)

        for item in items:
            if isinstance(item, dict) and item.get("type") == "folder":
                folder_name = _sanitize_filename(
                    item.get("name") or item.get("title") or "untitled"
                )
                root = unique_path(folder_name)
                visit(item, root)
            else:
                visit(item)
        return tasks

    def _start_structure_download_batch(self, tasks, dest_dir):
        """Download a folder tree through the same detailed batch dialog."""
        from larix_nexus.ui.dialogs import BatchDownloadDialog

        if getattr(self, "_structure_download_busy", False):
            return
        if not self._try_acquire_file_operation("download", source="download"):
            return
        self._structure_download_busy = True
        icon_provider = getattr(self, "icon_provider", None)
        dlg = BatchDownloadDialog(
            self, len(tasks), icon_provider, operation_mode="download_to_folder"
        )
        conflicts = 0
        for task in tasks:
            target_path = task["target_path"]
            task["conflict"] = os.path.exists(target_path)
            dlg.add_entry(task["key"], task["item"], task["target_name"])
            if task["conflict"]:
                conflicts += 1
            dlg.set_status(task["key"], "queued", t("download.status_queued"))
        dlg.set_total_conflicts(conflicts)
        dlg.show()
        QApplication.processEvents()

        apply_all_choice = None
        conflicts_left = conflicts
        for task in tasks:
            if not task.get("conflict"):
                continue
            decision = apply_all_choice
            if decision is None:
                decision, apply_all = dlg.ask_conflict(
                    task["key"], task["target_name"], conflicts_left
                )
                if apply_all:
                    apply_all_choice = decision
            if decision == "cancel":
                dlg.finish(t("download.cancelled"))
                self._structure_download_busy = False
                _release_download_slot()
                return
            if decision == "copy":
                folder = os.path.dirname(task["target_path"])
                new_name = self._unique_name(folder, os.path.basename(task["target_path"]))
                task["target_path"] = os.path.join(folder, new_name)
                rel_folder = os.path.dirname(task["target_name"])
                task["target_name"] = os.path.join(rel_folder, new_name) if rel_folder else new_name
                dlg.set_name(task["key"], task["target_name"])
            conflicts_left = max(0, conflicts_left - 1)

        thread = QtCore.QThread(self)
        worker = self._BatchDownloadWorker(self.api, tasks, dest_dir)
        worker.moveToThread(thread)
        dlg.cancel_requested.connect(worker.cancel, QtCore.Qt.DirectConnection)

        class _StructureGuiReceiver(QtCore.QObject):
            """QObject receiver that keeps all structure UI work in the GUI thread."""

            def __init__(self, window, dialog, batch_tasks, batch_thread):
                super().__init__(window)
                self._window = window
                self._dialog = dialog
                self._tasks = {task["key"]: task for task in batch_tasks}
                self._thread = batch_thread
                self.errors = []

            @QtCore.Slot(str, int, int)
            def on_item_started(self, key, index, total):
                task = self._tasks.get(key)
                self._dialog.set_active(key, True)
                self._dialog.set_status(key, "process", t("download.status_downloading"))
                self._dialog.set_current_file(
                    task["target_name"] if task else "", "downloading"
                )
                self._dialog.update_progress(index - 1, total)

            @QtCore.Slot(str, str)
            def on_item_done(self, key, target_name):
                self._dialog.set_status(key, "ok", t("download.status_downloaded"))
                self._dialog.set_active("", False)

            @QtCore.Slot(str, str, str)
            def on_item_failed(self, key, target_name, error):
                message = error or t("download.download_failed")
                self.errors.append((target_name or key, message))
                self._dialog.set_status(key, "error", message)
                self._dialog.set_active("", False)

            @QtCore.Slot(int, int)
            def on_progress(self, done, total):
                self._dialog.update_progress(done, total)

            @QtCore.Slot(int, int, list, bool)
            def on_finished(self, ok_count, total, errors, was_cancelled):
                if was_cancelled:
                    text = t("download.cancelled")
                elif errors:
                    text = t("download.partial")
                else:
                    text = t("download.done", count=ok_count)
                self._dialog.finish(text)
                # This dialog was shown modelessly; never start a second event loop.
                self._thread.quit()

        controller = _StructureGuiReceiver(self, dlg, tasks, thread)
        self._structure_download_controller = controller
        self._structure_download_thread = thread
        self._structure_download_worker = worker

        worker.sig_item_started.connect(controller.on_item_started, QtCore.Qt.QueuedConnection)
        worker.sig_item_done.connect(controller.on_item_done, QtCore.Qt.QueuedConnection)
        worker.sig_item_failed.connect(controller.on_item_failed, QtCore.Qt.QueuedConnection)
        worker.sig_progress.connect(controller.on_progress, QtCore.Qt.QueuedConnection)
        worker.sig_finished.connect(controller.on_finished, QtCore.Qt.QueuedConnection)

        thread.started.connect(worker.run)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(controller.deleteLater)
        thread.finished.connect(thread.deleteLater)

        def _clear_structure_batch_refs():
            self._structure_download_controller = None
            self._structure_download_worker = None
            self._structure_download_thread = None
            self._structure_download_busy = False
            self._release_file_operation("download", source="download")

        thread.finished.connect(_clear_structure_batch_refs)
        thread.start()

    class _BatchZipDownloadWorker(QtCore.QObject):
        """Stream each API file directly into a temporary ZIP entry."""

        sig_started = QtCore.Signal(int)
        sig_item_started = QtCore.Signal(str, int, int)
        sig_item_packed = QtCore.Signal(str)
        sig_item_failed = QtCore.Signal(str, str)
        sig_progress = QtCore.Signal(int, int)
        sig_finished = QtCore.Signal(int, int, list, bool, bool)

        def __init__(self, api, tasks, save_path, directory_entries=()):
            super().__init__()
            self._api = api
            self._tasks = list(tasks)
            self._save_path = save_path
            self._directory_entries = tuple(directory_entries)
            self._cancel_requested = False
            self._cancel_event = threading.Event()

        @QtCore.Slot()
        def cancel(self):
            self._cancel_requested = True
            self._cancel_event.set()

        @QtCore.Slot()
        def run(self):
            total = len(self._tasks)
            done = 0
            succeeded = 0
            errors = []
            cancelled = False
            part_path = f"{self._save_path}.part"
            self.sig_started.emit(total)
            try:
                os.makedirs(os.path.dirname(os.path.abspath(self._save_path)), exist_ok=True)
                try:
                    os.remove(part_path)
                except FileNotFoundError:
                    pass
                with zipfile.ZipFile(part_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    for directory in sorted(set(self._directory_entries)):
                        zf.writestr(directory.rstrip("/") + "/", b"")
                    for index, task in enumerate(self._tasks, 1):
                        if self._cancel_event.is_set():
                            cancelled = True
                            break
                        key = task["key"]
                        name = task["archive_name"]
                        if self._cancel_event.is_set():
                            cancelled = True
                            break
                        self.sig_item_started.emit(key, index, total)
                        try:
                            file_id = task.get("file_id")
                            if not file_id:
                                raise RuntimeError("missing file id")
                            with zf.open(name, "w") as target:
                                if self._api.write_file_to(
                                    file_id, target, cancel_event=self._cancel_event
                                ) is not True:
                                    raise RuntimeError("download failed")
                            succeeded += 1
                            self.sig_item_packed.emit(key)
                        except Exception as exc:
                            errors.append((name, str(exc)))
                            self.sig_item_failed.emit(key, str(exc))
                        done += 1
                        self.sig_progress.emit(done, total)
                    if self._cancel_event.is_set():
                        cancelled = True
                if cancelled:
                    return
                os.replace(part_path, self._save_path)
                self.sig_finished.emit(succeeded, total, errors, False, True)
            except Exception as exc:
                errors.append(("ZIP", str(exc)))
                try:
                    os.remove(part_path)
                except OSError:
                    pass
                self.sig_finished.emit(succeeded, total, errors, cancelled, False)
                return
            finally:
                if cancelled:
                    try:
                        os.remove(part_path)
                    except OSError:
                        pass
                    self.sig_finished.emit(succeeded, total, errors, True, False)

    def _start_zip_batch(self, items):
        from larix_nexus.ui.dialogs import BatchDownloadDialog

        default = t("download.default_zip_name", date=datetime.now().strftime("%Y%m%d_%H%M"))
        save_path, _ = QFileDialog.getSaveFileName(
            self, t("zip.save_title"), default, f"{t('download.all_files')};;ZIP (*.zip)"
        )
        if not save_path:
            return

        tasks = []
        directories = set()
        used = set()
        for item_index, item in enumerate(items):
            if item.get("type") == "file":
                name = item.get("originalName") or item.get("name") or f"file_{item.get('id')}.bin"
                candidates = [name]
                file_entries = [(item, name)]
            else:
                files, dirs = self._collect_files_and_dirs_for_zip(item)
                root = get_title(item) or "folder"
                directories.update(f"{root}/{entry}" for entry in dirs)
                candidates = []
                file_entries = [(fobj, f"{root}/{rel}") for fobj, rel in files]
            for file_obj, archive_name in file_entries:
                base, ext = os.path.splitext(archive_name)
                candidate = archive_name
                suffix = 2
                while candidate.replace("\\", "/") in used:
                    candidate = f"{base} ({suffix}){ext}"
                    suffix += 1
                candidate = candidate.replace("\\", "/")
                used.add(candidate)
                tasks.append({
                    "key": f"zip-{item_index}-{len(tasks)}",
                    "item": file_obj,
                    "file_id": file_obj.get("id"),
                    "archive_name": candidate,
                })

        dlg = BatchDownloadDialog(
            self,
            len(tasks),
            getattr(self, "icon_provider", None),
            operation_mode="download_to_zip",
        )
        dlg.set_conflicts_enabled(False)
        for task in tasks:
            display = task["archive_name"]
            dlg.add_entry(task["key"], task["item"], display)
            dlg.set_status(task["key"], "queued", t("download.status_queued"))
        dlg.set_stage(t("download.zip_stage"))
        dlg.show()
        QApplication.processEvents()

        thread = QtCore.QThread(self)
        worker = self._BatchZipDownloadWorker(self.api, tasks, save_path, directories)
        worker.moveToThread(thread)
        self._zip_download_thread = thread
        self._zip_download_worker = worker
        dlg.cancel_requested.connect(worker.cancel, QtCore.Qt.DirectConnection)
        dlg.btn_cancel.clicked.connect(lambda: dlg.set_current_file("", ""))

        def item_started(key, index, total):
            task = next((x for x in tasks if x["key"] == key), None)
            dlg.set_active(key, True)
            dlg.set_status(key, "process", t("download.status_downloading"))
            dlg.set_current_file(task["archive_name"] if task else "", "downloading")
            dlg.update_progress(index - 1, total)

        def item_packed(key):
            dlg.set_status(key, "packed", t("download.status_packed"))
            dlg.set_active("", False)

        def item_failed(key, error):
            dlg.set_status(key, "error", error or t("download.download_failed"))
            dlg.set_active("", False)

        def progress(done, total):
            dlg.update_progress(done, total)

        def finished(ok_count, total, errors, was_cancelled, archive_saved):
            if was_cancelled:
                text = t("download.cancelled")
            elif errors:
                text = t("download.partial")
            else:
                text = t("download.done", count=ok_count)
            dlg.finish(text)
            dlg.exec()
            thread.quit()

        class _ZipGuiReceiver(QtCore.QObject):
            def __init__(self, parent=None):
                super().__init__(parent)

            @QtCore.Slot(str, int, int)
            def on_item_started(self, key, index, total):
                item_started(key, index, total)

            @QtCore.Slot(str)
            def on_item_packed(self, key):
                item_packed(key)

            @QtCore.Slot(str, str)
            def on_item_failed(self, key, error):
                item_failed(key, error)

            @QtCore.Slot(int, int)
            def on_progress(self, done, total):
                progress(done, total)

            @QtCore.Slot(int, int, list, bool, bool)
            def on_finished(self, ok_count, total, errors, was_cancelled, archive_saved):
                finished(ok_count, total, errors, was_cancelled, archive_saved)

        receiver = _ZipGuiReceiver(self)
        self._zip_download_controller = receiver
        try:
            thread.started.connect(worker.run)
            worker.sig_item_started.connect(receiver.on_item_started, QtCore.Qt.QueuedConnection)
            worker.sig_item_packed.connect(receiver.on_item_packed, QtCore.Qt.QueuedConnection)
            worker.sig_item_failed.connect(receiver.on_item_failed, QtCore.Qt.QueuedConnection)
            worker.sig_progress.connect(receiver.on_progress, QtCore.Qt.QueuedConnection)
            worker.sig_finished.connect(receiver.on_finished, QtCore.Qt.QueuedConnection)
        except Exception:
            logging.exception("Failed to connect ZIP download progress signals")
            raise
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def action_download_zip(self):
        items = self._chosen_items_for_download()
        if not items:
            return QMessageBox.information(self, t("download.files"), t("download.no_files"))
        if hasattr(self, "_start_zip_batch"):
            self._start_zip_batch(items)
            return
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
        result = self._new_download_result()
        try:
            with zipfile.ZipFile(save_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                used = set()
                for it in items:
                    if it.get("type") == "file":
                        result["total"] += 1
                        fname = it.get("name") or it.get("fileName") or it.get("originalName") or f"file_{it.get('id')}.bin"
                        _prev = getattr(self, "_force_mode", None); self._force_mode = "A"
                        try:
                            local = self.ensure_downloaded(it)
                        finally:
                            self._force_mode = _prev
                        if not local:
                            self._download_failure(result, fname, "download_failed")
                            continue
                        arc = fname
                        if arc in used:
                            base, ext = os.path.splitext(fname); k = 1
                            while f"{base} ({k}){ext}" in used: k += 1
                            arc = f"{base} ({k}){ext}"
                        used.add(arc)
                        zf.write(local, arcname=arc)
                        result["succeeded"] += 1
                    else:
                        self._merge_download_result(result, self._zip_folder_into(it, zf, arc_prefix=""))
            self._report_download_result(result, "zip.title", "zip.created", save_path)
        except Exception as e:
            QMessageBox.warning(self, t("zip.title"), t("zip.failed", error=e))
        finally:
            self._set_progress_visible(False)

    def action_download_folder(self):
        items = self._chosen_items_for_download()
        folders = [item for item in items if isinstance(item, dict) and item.get("type") == "folder"]
        if not folders:
            return QMessageBox.information(self, t("download.files"), t("download.no_files"))
        dest_dir = self._pick_directory_showing_files(t("structure.where_save"))
        if not dest_dir:
            return
        tasks = self._build_structure_download_tasks(items, dest_dir)
        if not tasks:
            return QMessageBox.information(self, t("structure.title"), t("download.no_files"))
        self._start_structure_download_batch(tasks, dest_dir)

    
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
                    if key == Qt.Key_Escape and self._selection_mode_active():
                        self._clear_checked_selection()
                        return True
                    
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
                mods = getattr(ev, "modifiers", lambda: Qt.NoModifier)()
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
                                self._selection_mode_anchor_row = idx.row()
                            except Exception:
                                self._selection_mode_anchor_row = None
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
                if self._selection_mode_active():
                    if mods & Qt.ShiftModifier and self._selection_mode_anchor_row is not None:
                        start = min(self._selection_mode_anchor_row, idx.row())
                        end = max(self._selection_mode_anchor_row, idx.row())
                        for row in range(start, end + 1):
                            self._toggle_checked_for_proxy_row(row, True)
                        self._selection_mode_anchor_row = idx.row()
                    else:
                        self._toggle_checked_for_proxy_row(idx.row())
                        self._selection_mode_anchor_row = idx.row()
                    self.table._pressed_row = idx.row()
                    self._clear_row_selection_for_selection_mode()
                    self.table.viewport().update()
                    ev.accept()
                    return True
                self.table._pressed_row = idx.row()
                self.table.viewport().update()
                return False

            if t == QEvent.MouseButtonDblClick and self._selection_mode_active():
                try:
                    idx = self.table.indexAt(_pt(ev))
                    if idx.isValid():
                        self.status.showMessage(t("selection_mode.open_blocked"), 4000)
                        ev.accept()
                        return True
                except Exception:
                    pass

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

    def _show_public_link_dialog(self, node: dict, *, is_version=False, version_number=None):
        """Open public-link management for one confirmed target ID."""
        if getattr(self, "_active_public_link_dialog", None) is not None:
            return
        try:
            target_id = node.get("version_id") if is_version else node.get("id")
            if not target_id and is_version:
                target_id = (node.get("_raw") or {}).get("versionId")
            if target_id is None or not str(target_id).strip().isdigit():
                return
            link_state = node.get("public_link_state")
            if link_state is None and node.get("public_link_url"):
                link_state = "exists"
            if link_state not in ("absent", "exists"):
                return
            dlg = PublicLinkDialog(
                self.api, target_id, is_version=is_version,
                version_number=version_number,
                existing_url=(node.get("public_link_url")
                              if node.get("public_link_state") == "exists"
                              else None),
                parent_file_id=(node.get("parent_file_id") if is_version else None),
                version_item=(node.get("_table_item") if is_version else None),
                parent=self,
                on_changed=lambda cid, state, url=None, parent_id=None, version_item=None: self._refresh_public_link_state(
                    node, cid, is_version=is_version, state=state, url=url,
                    parent_file_id=parent_id, version_item=version_item
                ),
            )
            self._active_public_link_dialog = dlg
            dlg.finished.connect(self._on_public_link_dialog_finished)
            dlg.destroyed.connect(self._on_public_link_dialog_destroyed)
            dlg.setWindowModality(Qt.WindowModal)
            dlg.open()
            dlg.raise_()
            dlg.activateWindow()

        except Exception:
            self._active_public_link_lookup = None
            self._public_link_lookup_context = None
            return

    @Slot(object, object)
    def _on_public_link_lookup_finished(self, target_id, result):
        if self._active_public_link_lookup is None:
            return
        context = getattr(self, "_public_link_lookup_context", None)
        if context is None:
            return
        dlg, node, is_version, version_number = context
        if result.status not in ("ok", "not_found"):
            # The create dialog is already visible; an initial lookup error is non-fatal.
            if dlg is self._active_public_link_dialog:
                dlg.finish_existing_lookup_without_link()
            return
        if result.status == "not_found":
            if dlg is self._active_public_link_dialog:
                dlg.finish_existing_lookup_without_link()
            return
        if result.status == "ok" and dlg is self._active_public_link_dialog:
            dlg.apply_existing_link(result.value)

    @Slot()
    def _on_public_link_lookup_thread_finished(self):
        self._active_public_link_lookup = None
        self._public_link_lookup_context = None

    @Slot(int)
    def _on_public_link_dialog_finished(self, _result):
        dlg = self.sender()
        if dlg is self._active_public_link_dialog:
            self._active_public_link_dialog = None
        if isinstance(dlg, QDialog) and QApplication.activeModalWidget() is dlg:
            dlg.setWindowModality(Qt.NonModal)

    @Slot()
    def _on_public_link_dialog_destroyed(self):
        self._active_public_link_dialog = None

    def _public_link_entries_for_file(self, file_id):
        result = []
        for target_id, entry in getattr(self, "_public_links_by_target", {}).items():
            parent_id = entry.get("parent_file_id")
            if str(parent_id or target_id) == str(file_id) and entry.get("url"):
                result.append({"target_id": target_id, **entry})
        return result

    def _sync_public_link_file_state(self, parent_file_id):
        if parent_file_id is None:
            return
        registry = getattr(self, "_public_links_by_target", {})
        parent_key = str(parent_file_id)
        direct = registry.get(parent_key)
        if not isinstance(direct, dict) or direct.get("scope") != "file":
            direct = None
        for row, item in enumerate(getattr(self.files_model, "_data", [])):
            if not isinstance(item, dict) or str(item.get("id")) != parent_key:
                continue
            item["has_public_link"] = bool(direct and direct.get("url"))
            item["public_link_state"] = "exists" if direct and direct.get("url") else "absent"
            if direct and direct.get("url"):
                item["public_link_url"] = direct["url"]
            elif not direct:
                item.pop("public_link_url", None)
            try:
                self.files_model.dataChanged.emit(
                    self.files_model.index(row, 1), self.files_model.index(row, 2), [Qt.DecorationRole]
                )
            except (RuntimeError, AttributeError):
                pass
            break

    def _update_public_link_registry(self, target_id, *, state, url=None,
                                     is_version=False, parent_file_id=None,
                                     version_number=None):
        registry = getattr(self, "_public_links_by_target", None)
        if registry is None:
            registry = {}
            self._public_links_by_target = registry
        key = str(target_id)
        if state and url:
            registry[key] = {
                "url": url,
                "scope": "version" if is_version else "file",
                "parent_file_id": parent_file_id if is_version else target_id,
                "version_id": target_id if is_version else None,
                "version_number": version_number,
                "checked_at": time.monotonic(),
            }
        else:
            old = registry.pop(key, None)
            if parent_file_id is None and old:
                parent_file_id = old.get("parent_file_id")
        if is_version or parent_file_id is not None:
            self._sync_public_link_file_state(parent_file_id)

    def _refresh_public_link_state(self, node, target_id, *, is_version=False, state=None, url=None,
                                   parent_file_id=None, version_item=None):
        self._public_link_check_generation = getattr(self, "_public_link_check_generation", 0) + 1
        link_state = "exists" if state else "absent"
        has_link = link_state == "exists"
        self._update_public_link_registry(
            target_id, state=has_link, url=url, is_version=is_version,
            parent_file_id=parent_file_id or (node.get("parent_file_id") if is_version else None),
            version_number=node.get("version_number") if isinstance(node, dict) else None,
        )
        if isinstance(node, dict):
            node["public_link_state"] = link_state
            node["has_public_link"] = has_link
            if has_link and url:
                node["public_link_url"] = url
            elif not has_link:
                node.pop("public_link_url", None)
        if is_version:
            item = version_item or (node.get("_table_item") if isinstance(node, dict) else None)
            if item is not None:
                version = item.data(Qt.UserRole)
                if not isinstance(version, dict):
                    version = dict(node) if isinstance(node, dict) else {}
                version["public_link_state"] = link_state
                version["has_public_link"] = has_link
                version["parent_file_id"] = parent_file_id or version.get("parent_file_id")
                version["version_id"] = version.get("version_id") or target_id
                if has_link and url:
                    version["public_link_url"] = url
                else:
                    version.pop("public_link_url", None)
                item.setData(Qt.UserRole, version)
                item.setIcon(self._themed_icon(PUBLIC_LINK_ICON_PATH, tint_allowed=True)
                             if has_link else QIcon())
                try:
                    table = item.tableWidget()
                    if table is not None:
                        table.viewport().update()
                except RuntimeError:
                    pass
            return has_link
        try:
            model = self.table.model()
            for row in range(model.rowCount()):
                item = model.index(row, 1).data(Qt.UserRole)
                if isinstance(item, dict) and str(item.get("id")) == str(target_id):
                    item["public_link_state"] = link_state
                    item["has_public_link"] = has_link
                    if has_link and url:
                        item["public_link_url"] = url
                    elif not has_link:
                        item.pop("public_link_url", None)
                model.dataChanged.emit(model.index(row, 1), model.index(row, 2), [Qt.DecorationRole])
                break
        except Exception:
            pass
        return has_link

    def _invalidate_public_link_checks(self):
        """Invalidate in-flight file checks without leaving rows stuck in checking."""
        self._public_link_check_generation = getattr(self, "_public_link_check_generation", 0) + 1
        for entry in getattr(self, "_public_link_check_items", {}).values():
            item = entry.get("item")
            if isinstance(item, dict) and item.get("public_link_state") == "checking":
                item["public_link_state"] = "unknown"
                item.pop("public_link_check_started_at", None)
            entry["abandoned"] = True
        QTimer.singleShot(0, self._schedule_public_link_checks)

    def _queue_public_link_menu_check(self, node, pos):
        """Resolve one file link before displaying its business actions."""
        if getattr(self, "_pending_public_link_menu_lookup", None) is not None:
            return
        target_id = node.get("id") if isinstance(node, dict) else None
        if target_id is None or not str(target_id).strip().isdigit():
            return
        thread = QThread(self)
        worker = PublicLinkLookupWorker(self.api, target_id)
        worker.moveToThread(thread)
        self._pending_public_link_menu_lookup = {
            "node": node, "pos": pos, "thread": thread, "worker": worker,
        }
        worker.finished.connect(self._on_public_link_menu_lookup_finished, Qt.QueuedConnection)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_public_link_menu_lookup_thread_finished)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    @Slot(object, object)
    def _on_public_link_menu_lookup_finished(self, target_id, result):
        pending = getattr(self, "_pending_public_link_menu_lookup", None)
        if not pending or str(target_id) != str(pending["node"].get("id")):
            return
        node = pending["node"]
        if result.status == "ok" and result.value:
            node["public_link_state"] = "exists"
            node["has_public_link"] = True
            node["public_link_url"] = result.value
        elif result.status == "not_found":
            node["public_link_state"] = "absent"
            node["has_public_link"] = False
            node.pop("public_link_url", None)
        else:
            node["public_link_state"] = "error"
            node["has_public_link"] = False
            self._show_status_message(t("public_link.state_error"), 3500)
            return

    @Slot()
    def _reopen_public_link_menu_after_lookup(self):
        pending = getattr(self, "_pending_public_link_menu_lookup", None)
        if pending is None:
            return
        self.table_context_menu(pending["pos"])

    @Slot()
    def _on_public_link_menu_lookup_thread_finished(self):
        pending = getattr(self, "_pending_public_link_menu_lookup", None)
        thread = self.sender()
        if pending and pending.get("thread") is thread:
            self._pending_public_link_menu_lookup = None

    def _queue_public_link_version_menu_check(self, table, pos, version, version_id):
        if getattr(self, "_pending_public_link_version_lookup", None) is not None:
            return
        thread = QThread(self)
        worker = PublicLinkLookupWorker(self.api, version_id)
        worker.moveToThread(thread)
        self._pending_public_link_version_lookup = {
            "table": table, "pos": pos, "version": version,
            "version_id": version_id, "thread": thread, "worker": worker,
        }
        worker.finished.connect(self._on_public_link_version_menu_lookup_finished, Qt.QueuedConnection)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_public_link_version_menu_lookup_thread_finished)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    @Slot(object, object)
    def _on_public_link_version_menu_lookup_finished(self, target_id, result):
        pending = getattr(self, "_pending_public_link_version_lookup", None)
        if not pending or str(target_id) != str(pending["version_id"]):
            return
        version = pending["version"]
        if result.status == "ok" and result.value:
            version["public_link_state"] = "exists"
            version["has_public_link"] = True
            version["public_link_url"] = result.value
        elif result.status == "not_found":
            version["public_link_state"] = "absent"
            version["has_public_link"] = False
            version.pop("public_link_url", None)
        else:
            version["public_link_state"] = "error"
            self._show_status_message(t("public_link.state_error"), 3500)
            return

    @Slot()
    def _reopen_public_link_version_menu_after_lookup(self):
        pending = getattr(self, "_pending_public_link_version_lookup", None)
        if pending is not None:
            pending["table"].customContextMenuRequested.emit(pending["pos"])

    @Slot()
    def _on_public_link_version_menu_lookup_thread_finished(self):
        pending = getattr(self, "_pending_public_link_version_lookup", None)
        if pending and pending.get("thread") is self.sender():
            self._pending_public_link_version_lookup = None

    def _resolve_pending_version_link_action(self):
        pending = getattr(self, "_pending_version_link_action", None)
        if pending is None or getattr(self, "_active_public_link_dialog", None) is not None:
            return
        version, item, parent_dialog = pending
        try:
            if not parent_dialog.isVisible():
                self._pending_version_link_action = None
                return
        except RuntimeError:
            self._pending_version_link_action = None
            return
        state = version.get("public_link_state")
        url = version.get("public_link_url")
        if state == "exists" and url:
            version["_table_item"] = item
            self._pending_version_link_action = None
            self._show_public_link_dialog(
                version, is_version=True, version_number=version.get("version_number")
            )
            return
        if state == "absent":
            version["_table_item"] = item
            self._pending_version_link_action = None
            self._show_public_link_dialog(
                version, is_version=True, version_number=version.get("version_number")
            )
            return
        if getattr(self, "_pending_version_link_action_lookup", None) is not None:
            return
        version_id = version.get("version_id") or (version.get("_raw") or {}).get("versionId")
        if version_id is None or not str(version_id).strip().isdigit():
            self._pending_version_link_action = None
            return
        thread = QThread(self)
        worker = PublicLinkLookupWorker(self.api, version_id)
        worker.moveToThread(thread)
        self._pending_version_link_action_lookup = (thread, worker, version_id)
        worker.finished.connect(self._on_pending_version_link_action_lookup_finished, Qt.QueuedConnection)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_pending_version_link_action_lookup_thread_finished)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    @Slot(object, object)
    def _on_pending_version_link_action_lookup_finished(self, target_id, result):
        pending = getattr(self, "_pending_version_link_action", None)
        lookup = getattr(self, "_pending_version_link_action_lookup", None)
        if pending is None or lookup is None or str(target_id) != str(lookup[2]):
            return
        version, _item, _parent_dialog = pending
        if result.status == "ok" and result.value:
            version["public_link_state"] = "exists"
            version["has_public_link"] = True
            version["public_link_url"] = result.value
        elif result.status == "not_found":
            version["public_link_state"] = "absent"
            version["has_public_link"] = False
            version.pop("public_link_url", None)
        else:
            version["public_link_state"] = "error"
            self._pending_version_link_action = None
            self._show_status_message(t("public_link.state_error"), 3500)
            return
        QTimer.singleShot(0, self._resolve_pending_version_link_action)

    @Slot()
    def _on_pending_version_link_action_lookup_thread_finished(self):
        lookup = getattr(self, "_pending_version_link_action_lookup", None)
        if lookup is not None and lookup[0] is self.sender():
            self._pending_version_link_action_lookup = None

    def _schedule_public_link_checks(self):
        """Confirm visible file-link states off the GUI thread, bounded to visible requests."""
        if not hasattr(self.api, "get_public_link_info_result"):
            return
        generation = getattr(self, "_public_link_check_generation", 0)
        if not hasattr(self, "_public_link_check_generation"):
            self._public_link_check_generation = generation
        threads = getattr(self, "_public_link_check_threads", set())
        self._public_link_check_threads = threads
        checks = getattr(self, "_public_link_check_items", {})
        self._public_link_check_items = checks
        candidates = list(getattr(self.files_model, "_data", []))
        try:
            if not getattr(self, "_public_link_scroll_bound", False):
                self.table.verticalScrollBar().valueChanged.connect(self._schedule_public_link_checks)
                self._public_link_scroll_bound = True
            first_row = self.table.rowAt(0)
            last_row = self.table.rowAt(max(0, self.table.viewport().height() - 1))
            if first_row >= 0 and last_row >= first_row:
                visible_ids = set()
                for row in range(first_row, last_row + 1):
                    value = self.table.model().index(row, 1).data(Qt.UserRole)
                    if isinstance(value, dict):
                        visible_ids.add(str(value.get("id")))
                candidates = [item for item in candidates if str(item.get("id")) in visible_ids]
        except Exception:
            pass
        for item in candidates:
            if not isinstance(item, dict) or str(item.get("type", "")).lower() in ("folder", "папка"):
                continue
            file_id = item.get("id")
            if not str(file_id or "").strip().isdigit():
                continue
            if item.get("public_link_state") == "checking":
                started = item.get("public_link_check_started_at")
                if started and time.monotonic() - started <= 20:
                    continue
                item["public_link_state"] = "error"
                item["has_public_link"] = False
                item.pop("public_link_check_started_at", None)
                for pending in checks.values():
                    if pending.get("item") is item:
                        pending["abandoned"] = True
            if item.get("public_link_state") in ("exists", "absent"):
                continue
            item["public_link_state"] = "checking"
            thread = QThread(self)
            worker = PublicLinkLookupWorker(self.api, file_id)
            worker.moveToThread(thread)
            threads.add(thread)
            request_id = uuid.uuid4().hex
            item["public_link_check_started_at"] = time.monotonic()
            checks[request_id] = {
                "target_id": str(file_id),
                "item": item,
                "generation": generation,
                "thread": thread,
                "worker": worker,
                "applied": False,
            }
            worker.finished.connect(self._on_public_link_state_check_finished, Qt.QueuedConnection)
            thread.started.connect(worker.run)
            worker.finished.connect(thread.quit)
            thread.finished.connect(worker.deleteLater)
            thread.finished.connect(self._on_public_link_state_check_thread_finished)
            thread.finished.connect(thread.deleteLater)
            thread.start()

    @Slot(object, object)
    def _on_public_link_state_check_finished(self, target_id, result):
        worker = self.sender()
        entry = next(
            (value for value in getattr(self, "_public_link_check_items", {}).values()
             if value.get("worker") is worker and str(value.get("target_id")) == str(target_id)),
            None,
        )
        if entry is None:
            return
        item = entry["item"]
        generation = entry["generation"]
        entry["applied"] = True
        if entry.get("abandoned"):
            if item.get("public_link_state") == "checking":
                item["public_link_state"] = "unknown"
            return
        if generation != getattr(self, "_public_link_check_generation", 0):
            item["public_link_state"] = "unknown"
            item.pop("public_link_check_started_at", None)
            QTimer.singleShot(0, self._schedule_public_link_checks)
            return
        try:
            if result.status == "ok" and result.value:
                item["public_link_state"] = "exists"
                item["has_public_link"] = True
                item["public_link_url"] = result.value
                self._update_public_link_registry(target_id, state=True, url=result.value)
            elif result.status == "not_found":
                item["public_link_state"] = "absent"
                item["has_public_link"] = False
                item.pop("public_link_url", None)
                self._update_public_link_registry(target_id, state=False)
            else:
                item["public_link_state"] = "error"
                item["has_public_link"] = False
            self._sync_public_link_file_state(target_id)
            item.pop("public_link_check_started_at", None)
            row = self.files_model._data.index(item)
            self.files_model.dataChanged.emit(
                self.files_model.index(row, 1), self.files_model.index(row, 2), [Qt.DecorationRole]
            )
        except (RuntimeError, ValueError, AttributeError):
            pass

    @Slot()
    def _on_public_link_state_check_thread_finished(self):
        thread = self.sender()
        self._public_link_check_threads.discard(thread)
        for key, entry in list(getattr(self, "_public_link_check_items", {}).items()):
            if entry.get("thread") is thread:
                if not entry.get("applied"):
                    item = entry.get("item")
                    if isinstance(item, dict):
                        item["public_link_state"] = "error"
                        item["has_public_link"] = False
                        item.pop("public_link_check_started_at", None)
                        try:
                            row = self.files_model._data.index(item)
                            self.files_model.dataChanged.emit(
                            self.files_model.index(row, 1), self.files_model.index(row, 2),
                                [Qt.DecorationRole]
                            )
                        except (RuntimeError, ValueError, AttributeError):
                            pass
                self._public_link_check_items.pop(key, None)

    @Slot(object, object)
    def _on_version_link_check_finished(self, target_id, result):
        entry = next(
            (value for value in getattr(self, "_version_link_checks", {}).values()
             if str(value[0]) == str(target_id)),
            None,
        )
        if entry is None:
            return
        _target, dlg, item, _thread, scope = entry
        try:
            if dlg is None or not dlg.isVisible():
                return
        except RuntimeError:
            # The versions dialog may have been closed while the worker was
            # still finishing.  Its table is no longer a valid UI target.
            return
        try:
            if result.status == "ok" and result.value:
                item.setIcon(self._themed_icon(PUBLIC_LINK_ICON_PATH, tint_allowed=True))
                try:
                    item.tableWidget().viewport().update()
                except RuntimeError:
                    pass
                version = item.data(Qt.UserRole)
                if isinstance(version, dict):
                    version["public_link_state"] = "exists"
                    version["has_public_link"] = True
                    version["public_link_url"] = result.value
                    self._update_public_link_registry(
                        target_id, state=True, url=result.value,
                        is_version=(scope == "version"),
                        parent_file_id=version.get("parent_file_id"),
                        version_number=version.get("version_number"),
                    )
                    if scope == "current_file":
                        version["public_link_scope"] = "current_file"
            else:
                version = item.data(Qt.UserRole)
                if isinstance(version, dict) and not version.get("public_link_url"):
                    version["public_link_state"] = "absent" if result.status == "not_found" else "error"
                    version["has_public_link"] = False
                if result.status == "not_found":
                    self._update_public_link_registry(
                        target_id, state=False, is_version=(scope == "version"),
                        parent_file_id=(version or {}).get("parent_file_id") if isinstance(version, dict) else None,
                    )
            # A negative result must not erase a confirmed URL from another scope.
            item.setData(Qt.UserRole + 1, bool((item.data(Qt.UserRole) or {}).get("public_link_url")))
        except RuntimeError:
            pass

    @Slot()
    def _on_version_link_check_thread_finished(self):
        thread = self.sender()
        for key, entry in list(getattr(self, "_version_link_checks", {}).items()):
            if entry[3] is thread:
                self._version_link_checks.pop(key, None)

    def _show_versions_for_node(self, node: dict):
        """Открыть диалог со списком версий выбранного файла."""
        try:
            from larix_nexus.utils.i18n import get_status_translation

            if not isinstance(node, dict) or str(node.get("type", "")).lower() != "file":
                QMessageBox.information(self, t("version.title"), t("version.select_file"))
                return
            file_id = node.get("id")
            if not file_id:
                QMessageBox.information(self, t("version.title"), t("version.id_not_defined"))
                return

            name = node.get("originalName") or node.get("name") or f"Документ {file_id}"
            self.status.showMessage(t("version.loading"))
            versions = self.api.list_file_versions(file_id, force=True)
            self.status.clearMessage()

            if versions is None:
                QMessageBox.warning(self, t("version.title"), t("version.load_error"))
                return

            base_file_name = name
            for _v in versions:
                fn = _v.get("file_name") or (_v.get("_raw") or {}).get("fileName")
                if fn:
                    base_file_name = fn
                    break

            if not versions:
                QMessageBox.information(self, t("version.title"), t("version.not_found"))
                return

            dlg = QDialog(self)
            dlg.setWindowTitle(t("version.dialog_title", name=name))
            current_theme = getattr(self, "_current_theme", THEME_LIGHT)
            is_dark = current_theme == THEME_DARK
            _set_window_theme_dark(dlg, dark=is_dark)
            lay = QVBoxLayout(dlg)

            table = QTableWidget(dlg)
            table.setObjectName("versionsTable")
            table.setColumnCount(4)
            table.setHorizontalHeaderLabels([
                t("version.header_version"),
                t("version.header_date"),
                t("version.header_author"),
                t("version.header_status"),
            ])
            try:
                hh = table.horizontalHeader()
                hh.setHighlightSections(False)
                hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                table.verticalHeader().setHighlightSections(False)
            except Exception:
                pass
            table.setRowCount(len(versions))
            # Versions dialog: match main-table selection visuals (no native blue selection/focus).
            table.setFocusPolicy(Qt.NoFocus)
            table.setMouseTracking(True)
            try:
                table.viewport().setAttribute(Qt.WA_Hover, True)
                table.viewport().setMouseTracking(True)
            except Exception:
                pass
            table.setSelectionBehavior(QAbstractItemView.SelectRows)
            table.setSelectionMode(QAbstractItemView.ExtendedSelection)
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            table.setSortingEnabled(False)
            table.setShowGrid(False)
            table.setAlternatingRowColors(False)
            table.setFrameShape(QFrame.NoFrame)
            table.setWordWrap(False)
            try:
                table.verticalHeader().setVisible(False)
            except Exception:
                pass
            try:
                table.clearSelection()
            except Exception:
                pass
            try:
                table.setCurrentCell(-1, -1)
            except Exception:
                pass

            def _version_item(text, version=None):
                item = QTableWidgetItem(str(text or ""))
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                if version is not None:
                    item.setData(Qt.UserRole, version)
                return item

            def _resize_version_columns():
                """Fit columns to dialog width without stretching a single column."""
                try:
                    hh = table.horizontalHeader()
                    hh.setStretchLastSection(False)
                    for col in range(4):
                        hh.setSectionResizeMode(col, QHeaderView.Fixed)

                    base = [70, 140, 140, 130]  # version, date, author, status
                    available = int(table.viewport().width() or 0)
                    if available <= 0:
                        return

                    widths = list(base)
                    base_sum = int(sum(base))
                    if available > base_sum:
                        extra = int(available - base_sum)
                        weights = [0, 1, 1, 1]
                        wsum = int(sum(weights))
                        if wsum > 0:
                            per = int(extra // wsum)
                            rem = int(extra % wsum)
                            for i_w, wt in enumerate(weights):
                                if wt:
                                    widths[i_w] += per * wt
                            for i_w in (1, 2, 3):
                                if rem <= 0:
                                    break
                                widths[i_w] += 1
                                rem -= 1

                    for col, w in enumerate(widths):
                        hh.resizeSection(int(col), int(w))
                except Exception:
                    pass

            for i, v in enumerate(versions, 1):
                if isinstance(v, dict):
                    v["parent_file_id"] = file_id
                try:
                    raw = v.get("_raw") or v
                    ver_no = v.get("version_number") or raw.get("versionNumber") or raw.get("version") or i
                    when_raw = v.get("created_ts") or raw.get("createTime") or raw.get("createdAt")
                    when = ""
                    if when_raw:
                        ts = parse_date_like(str(when_raw))
                        if ts > 0:
                            when = _user_display_datetime(ts)
                    who = v.get("created_by") or raw.get("modifiedBy") or ""
                    status = v.get("status") or ""
                    status_text = get_status_translation(status)

                    # Храним dict версии в первой ячейке строки
                    it_ver = _version_item(ver_no, version=v)
                    v["_table_item"] = it_ver
                    table.setItem(i - 1, 0, it_ver)
                    table.setItem(i - 1, 1, _version_item(when or ""))
                    table.setItem(i - 1, 2, _version_item(who or ""))
                    table.setItem(i - 1, 3, _version_item(status_text or ""))
                except Exception:
                    versions[i - 1]["parent_file_id"] = file_id
                    it_ver = _version_item(i, version=versions[i - 1])
                    versions[i - 1]["_table_item"] = it_ver
                    table.setItem(i - 1, 0, it_ver)
                    table.setItem(i - 1, 1, _version_item(""))
                    table.setItem(i - 1, 2, _version_item(""))
                    table.setItem(i - 1, 3, _version_item(""))

            try:
                table.clearSelection()
            except Exception:
                pass
            try:
                table.setCurrentCell(-1, -1)
            except Exception:
                pass

            _resize_version_columns()

            try:
                header_style = (
                    """
                    QTableWidget#versionsTable QHeaderView::section,
                    QTableWidget#versionsTable QHeaderView::section:selected {
                        background: #121212;
                        color: #e0e0e0;
                        border: none;
                        border-radius: 0;
                        padding: 6px 8px;
                    }
                    QTableWidget#versionsTable QHeaderView::section:hover,
                    QTableWidget#versionsTable QHeaderView::section:selected:hover {
                        background: rgba(247, 146, 30, 0.15);
                    }
                    QTableWidget#versionsTable QHeaderView::section:pressed,
                    QTableWidget#versionsTable QHeaderView::section:selected:pressed {
                        background: rgba(247, 146, 30, 0.25);
                    }
                    """
                    if is_dark
                    else """
                    QTableWidget#versionsTable QHeaderView::section,
                    QTableWidget#versionsTable QHeaderView::section:selected {
                        background: transparent;
                        color: #000000;
                        border: none;
                        border-radius: 0;
                        padding: 6px 8px;
                    }
                    QTableWidget#versionsTable QHeaderView::section:hover,
                    QTableWidget#versionsTable QHeaderView::section:selected:hover {
                        background: #FFE3C2;
                    }
                    QTableWidget#versionsTable QHeaderView::section:pressed,
                    QTableWidget#versionsTable QHeaderView::section:selected:pressed {
                        background: #FFC37A;
                    }
                    """
                )
                table.setStyleSheet("""
                    QTableWidget {
                        background: transparent;
                        border: none;
                        outline: none;
                        selection-background-color: transparent;
                        selection-color: palette(text);
                    }
                    QTableWidget::item {
                        border: none;
                        outline: none;
                        background: transparent;
                    }
                    QTableWidget::item:selected,
                    QTableWidget::item:selected:active,
                    QTableWidget::item:selected:!active,
                    QTableWidget::item:focus {
                        background: transparent;
                        border: none;
                        outline: none;
                    }
                """ + header_style)
            except Exception:
                pass

            try:
                # Row background is painted by install_viewport_row_highlighter().
                # This delegate draws only cell text and fully suppresses native per-cell
                # selection/focus painting to avoid vertical seams.
                class _VersionTableDelegate(QStyledItemDelegate):
                    def paint(self, painter, option, index):
                        opt = QStyleOptionViewItem(option)
                        self.initStyleOption(opt, index)

                        # Fully suppress native selection/focus/hover for cells.
                        opt.state &= ~QStyle.State_Selected
                        opt.state &= ~QStyle.State_HasFocus
                        opt.state &= ~QStyle.State_MouseOver
                        opt.showDecorationSelected = False

                        painter.save()
                        painter.setFont(opt.font)
                        painter.setPen(opt.palette.color(QPalette.Text))
                        rect = opt.rect.adjusted(10, 0, -10, 0)
                        icon = QIcon()
                        if index.column() == 0:
                            icon = opt.icon
                            if icon.isNull():
                                icon = index.data(Qt.DecorationRole)
                        badge_size = 16
                        gap = 6
                        pixmap = icon.pixmap(QSize(badge_size, badge_size)) if isinstance(icon, QIcon) and not icon.isNull() else None
                        text = index.data(Qt.DisplayRole)
                        s = "" if text is None else str(text)
                        fm = painter.fontMetrics()
                        text_width = max(0, rect.width() - (badge_size + gap if pixmap is not None else 0))
                        s = fm.elidedText(s, Qt.ElideRight, text_width)
                        painter.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine, s)
                        if pixmap is not None and not pixmap.isNull():
                            icon_x = rect.left() + fm.horizontalAdvance(s) + gap
                            if icon_x + badge_size <= rect.right():
                                painter.drawPixmap(
                                    icon_x, rect.top() + max(0, (rect.height() - badge_size) // 2), pixmap
                                )
                        painter.restore()

                table._version_text_delegate = _VersionTableDelegate(table)
                table.setItemDelegate(table._version_text_delegate)
                install_viewport_row_highlighter(table)
                table._hover_row = -1
                table._pressed_row = -1

                class _VersionHoverPressFilter(QtCore.QObject):
                    def __init__(self, tbl):
                        super().__init__(tbl.viewport())
                        self._t = tbl

                    def _pos(self, ev):
                        try:
                            return ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
                        except Exception:
                            return QPoint()

                    def eventFilter(self, obj, ev):
                        try:
                            et = ev.type()
                            if et in (QEvent.MouseMove, QEvent.HoverMove):
                                idx = self._t.indexAt(self._pos(ev))
                                row = idx.row() if idx.isValid() else -1
                                if getattr(self._t, "_hover_row", -1) != row:
                                    self._t._hover_row = row
                                    self._t.viewport().update()
                            elif et == QEvent.Leave:
                                if getattr(self._t, "_hover_row", -1) != -1:
                                    self._t._hover_row = -1
                                    self._t.viewport().update()
                            elif et == QEvent.MouseButtonPress:
                                idx = self._t.indexAt(self._pos(ev))
                                self._t._pressed_row = idx.row() if idx.isValid() else -1
                                self._t.viewport().update()
                            elif et == QEvent.MouseButtonRelease:
                                if getattr(self._t, "_pressed_row", -1) != -1:
                                    self._t._pressed_row = -1
                                    self._t.viewport().update()
                        except Exception:
                            pass
                        return False

                _f = _VersionHoverPressFilter(table)
                table.viewport().installEventFilter(_f)
                table._version_hover_filter = _f  # keep alive
            except Exception:
                pass

            lay.addWidget(table)

            def _safe_ver_filename(base_name: str, ver: dict) -> str:
                base = _sanitize_filename(base_name or name)
                stem, ext = os.path.splitext(base)
                raw = ver.get("_raw") or ver
                ver_no = ver.get("version_number") or raw.get("versionNumber") or raw.get("version") or ""
                when_raw = ver.get("created_ts") or raw.get("createTime") or raw.get("createdAt")
                ts = 0.0
                if when_raw:
                    ts = parse_date_like(str(when_raw))
                parts = [stem]
                if ver_no != "":
                    parts.append(f"v{ver_no}")
                if ts > 0:
                    parts.append(datetime.fromtimestamp(ts).strftime("%Y%m%d_%H%M%S"))
                fname = " - ".join(parts) + ext
                return fname

            def _download_version_local(ver: dict) -> str:
                version_id = ver.get("version_id")
                if not version_id:
                    raw = ver.get("_raw") or {}
                    version_id = raw.get("versionId") or raw.get("version_id")
                if not version_id:
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
                    local_path = self.api.download_document_version(version_id, fname, progress_cb=_cb)
                finally:
                    self._set_progress_visible(False)
                    try:
                        wait.set_done(t("version.download_complete"))
                    except Exception:
                        pass
                return local_path or ""

            def _open_selected_local():
                ver = _selected_version()
                if not ver:
                    return
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
            def on_row_double_clicked(_row: int, _col: int):
                _open_selected_local()
            table.cellDoubleClicked.connect(on_row_double_clicked)

            btns = QDialogButtonBox(QDialogButtonBox.Close, parent=dlg)
            btns.rejected.connect(dlg.reject)
            btns.accepted.connect(dlg.accept)
            lay.addWidget(btns)

            btn_open_pc = QPushButton(t("version.open_on_pc"), dlg)
            btn_open_pc.setEnabled(False)
            btn_open_pc.setToolTip(t("version.select_file_version_tooltip"))
            btn_open_pc.clicked.connect(_open_selected_local)
            btns.addButton(btn_open_pc, QDialogButtonBox.ActionRole)

            def _selected_version():
                try:
                    sm = table.selectionModel()
                    rows = sm.selectedRows() if sm is not None else []
                except Exception:
                    rows = []

                if rows:
                    try:
                        row = int(rows[0].row())
                    except Exception:
                        row = table.currentRow()
                else:
                    row = table.currentRow()

                if row is None or int(row) < 0:
                    return None
                it0 = table.item(int(row), 0)
                if it0 is None:
                    return None
                return it0.data(Qt.UserRole) or None

            def _update_version_buttons():
                has_selection = _selected_version() is not None
                btn_open_pc.setEnabled(bool(has_selection))
                if has_selection:
                    btn_open_pc.setToolTip("")
                else:
                    btn_open_pc.setToolTip(t("version.select_file_version_tooltip"))

            try:
                table.selectionModel().selectionChanged.connect(lambda *_: _update_version_buttons())
            except Exception:
                pass
            try:
                table.currentCellChanged.connect(lambda *_: _update_version_buttons())
            except Exception:
                pass

            if name.lower().endswith('.pdf'):
                btn_compare = QPushButton(t("version.compare_pdf"), dlg)
                can_compare = _configure_version_compare_button(
                    btn_compare, len(versions), t("version.compare_requires_two")
                )
                if not can_compare:
                    class _DisabledCompareTooltipFilter(QObject):
                        def eventFilter(self, obj, event):
                            if event.type() == QEvent.ToolTip:
                                try:
                                    pos = event.globalPosition().toPoint()
                                except AttributeError:
                                    pos = event.globalPos()
                                QToolTip.showText(pos, obj.toolTip(), obj)
                                event.accept()
                                return True
                            return False

                    _compare_tooltip_filter = _DisabledCompareTooltipFilter(btn_compare)
                    btn_compare.installEventFilter(_compare_tooltip_filter)
                    dlg._compare_tooltip_filter = _compare_tooltip_filter
                btn_compare.clicked.connect(_compare_selected_pdf)
                btns.addButton(btn_compare, QDialogButtonBox.ActionRole)

            dlg.resize(640, 380)
            _update_version_buttons()
            def _version_context_menu(pos):
                index = table.indexAt(pos)
                if not index.isValid():
                    return
                item = table.item(index.row(), 0)
                version = item.data(Qt.UserRole) if item else None
                if not isinstance(version, dict):
                    return
                version_id = version.get("version_id") or (version.get("_raw") or {}).get("versionId")
                if version_id is None or not str(version_id).strip().isdigit():
                    return
                link_url = version.get("public_link_url")
                link_state = version.get("public_link_state")
                registry_entry = getattr(self, "_public_links_by_target", {}).get(str(version_id))
                if registry_entry and registry_entry.get("url"):
                    link_url = registry_entry["url"]
                    link_state = "exists"
                    version["public_link_state"] = "exists"
                    version["has_public_link"] = True
                    version["public_link_url"] = link_url
                    version["parent_file_id"] = registry_entry.get("parent_file_id")
                    item.setData(Qt.UserRole, version)
                if link_state is None and link_url:
                    link_state = "exists"
                menu = QMenu(table)
                menu.setObjectName("versionPublicLinkMenu")
                action = None
                open_action = None
                copy_action = None
                delete_action = None
                if link_state == "exists" and link_url:
                    open_action = menu.addAction(t("public_link.open_link"))
                    copy_action = menu.addAction(t("public_link.copy_link"))
                    delete_action = menu.addAction(t("public_link.delete_link"))
                elif link_state == "absent":
                    action = menu.addAction(t("public_link.create_version"))
                elif link_state == "error":
                    self._show_status_message(t("public_link.state_error"), 3500)
                    action = menu.addAction(t("public_link.create_version"))
                else:
                    action = menu.addAction(t("public_link.create_version"))
                chosen = menu.exec(table.viewport().mapToGlobal(pos))
                if chosen is action:
                    menu.close()
                    menu.hide()
                    menu.deleteLater()
                    self._pending_version_link_action = (version, item, dlg)
                    # Kept inside the handler: QTimer.singleShot(0, _open_version_public_link)
                    QTimer.singleShot(0, self._resolve_pending_version_link_action)
                elif open_action is not None and chosen is open_action:
                    QDesktopServices.openUrl(QUrl(str(link_url)))
                    menu.close()
                    menu.deleteLater()
                elif copy_action is not None and chosen is copy_action:
                    QApplication.clipboard().setText(str(link_url))
                    self._show_status_message(t("public_link.copied"), 2000)
                    menu.close()
                    menu.deleteLater()
                elif delete_action is not None and chosen is delete_action:
                    menu.close()
                    menu.deleteLater()
                    version["_table_item"] = item
                    QTimer.singleShot(0, lambda: self._show_public_link_dialog(
                        version, is_version=True, version_number=version.get("version_number")
                    ))
            table.setContextMenuPolicy(Qt.CustomContextMenu)
            table.customContextMenuRequested.connect(_version_context_menu)
            if hasattr(self.api, "get_public_link_info_result"):
                version_checks = getattr(self, "_version_link_checks", {})
                self._version_link_checks = version_checks
                for row in range(table.rowCount()):
                    item = table.item(row, 0)
                    version = item.data(Qt.UserRole) if item else None
                    version_id = (version or {}).get("version_id") or ((version or {}).get("_raw") or {}).get("versionId")
                    if not isinstance(version, dict) or not str(version_id or "").isdigit():
                        continue
                    thread = QThread(self)
                    worker = PublicLinkLookupWorker(self.api, version_id)
                    worker.moveToThread(thread)
                    version_checks[f"version:{version_id}"] = (version_id, dlg, item, thread, "version")
                    worker.finished.connect(self._on_version_link_check_finished, Qt.QueuedConnection)
                    thread.started.connect(worker.run)
                    worker.finished.connect(thread.quit)
                    thread.finished.connect(worker.deleteLater)
                    thread.finished.connect(self._on_version_link_check_thread_finished)
                    thread.finished.connect(thread.deleteLater)
                    thread.start()
                current_item = table.item(0, 0) if table.rowCount() else None
                if current_item is not None:
                    current_thread = QThread(self)
                    current_worker = PublicLinkLookupWorker(self.api, file_id)
                    current_worker.moveToThread(current_thread)
                    version_checks[f"file:{file_id}"] = (
                        file_id, dlg, current_item, current_thread, "current_file"
                    )
                    current_worker.finished.connect(self._on_version_link_check_finished, Qt.QueuedConnection)
                    current_thread.started.connect(current_worker.run)
                    current_worker.finished.connect(current_thread.quit)
                    current_thread.finished.connect(current_worker.deleteLater)
                    current_thread.finished.connect(self._on_version_link_check_thread_finished)
                    current_thread.finished.connect(current_thread.deleteLater)
                    current_thread.start()
            _resize_version_columns()
            try:
                QTimer.singleShot(0, _resize_version_columns)
            except Exception:
                pass

            try:
                class _VersionDlgResizeFilter(QtCore.QObject):
                    def eventFilter(self, obj, ev):
                        try:
                            if ev.type() == QEvent.Resize:
                                QTimer.singleShot(0, _resize_version_columns)
                        except Exception:
                            pass
                        return False
                _rf = _VersionDlgResizeFilter(dlg)
                dlg.installEventFilter(_rf)
                dlg._version_resize_filter = _rf  # keep alive
            except Exception:
                pass
            dlg.exec()
        except Exception:
            logging.getLogger(__name__).exception("Failed to open versions dialog")
            QMessageBox.warning(self, t("version.title"), t("version.load_error"))


    def _has_at_least_two_versions(self, node: dict) -> bool:
        """True, если у файла есть минимум 2 версии."""
        try:
            if not isinstance(node, dict) or str(node.get("type", "")).lower() != "file":
                return False
            file_id = node.get("id")
            if not file_id:
                return False
            self.status.showMessage(t("version.checking"))
            versions = self.api.list_file_versions(file_id)
        finally:
            try:
                self.status.clearMessage()
            except Exception:
                pass
        if versions is None:
            return False
        return len(versions) >= 2

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
        from larix_nexus.utils.i18n import get_status_translation

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

        file_id = node.get("id")
        name   = node.get("fileName") or node.get("name") or node.get("title") or "файл"
        if not file_id:
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
        versions = self.api.list_file_versions(file_id, force=True)
        self.status.clearMessage()

        if versions is None:
            from PySide6.QtCore import QTimer

            def show_load_error():
                try:
                    parent = self
                    if parent and hasattr(parent, 'window'):
                        parent = parent.window()
                    if parent:
                        QMessageBox.warning(parent, t("version.compare_title"), t("version.load_error"))
                except Exception:
                    pass

            QTimer.singleShot(200, show_load_error)
            return

        base_file_name = name
        for _v in versions:
            fn = _v.get("file_name") or (_v.get("_raw") or {}).get("fileName")
            if fn:
                base_file_name = fn
                break

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
                    raw = v.get("_raw") or v
                    ver_no = v.get("version_number") or raw.get("versionNumber") or raw.get("version") or i
                    when_raw = v.get("created_ts") or raw.get("createTime") or raw.get("createdAt")
                    ts = 0.0
                    if when_raw:
                        ts = parse_date_like(str(when_raw))
                    if ts > 0:
                        when = _user_display_datetime(ts)
                    else:
                        when = ""
                    who  = v.get("created_by") or raw.get("modifiedBy") or ""
                    status = get_status_translation(v.get("status") or "")
                    shared_txt = t("version.shared") if v.get("shared") else ""
                    label_parts = [f"v{ver_no}", when, str(who) if who else "", status, shared_txt]
                    label = "  ".join([p for p in label_parts if p])
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
        btn_cancel.setProperty("secondary", True)
        for btn in (btn_compare, btn_cancel):
            try:
                btn.style().unpolish(btn)
                btn.style().polish(btn)
            except Exception:
                pass
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
            raw = ver.get("_raw") or ver
            ver_no = ver.get("version_number") or raw.get("versionNumber") or raw.get("version") or ""
            when_raw = ver.get("created_ts") or raw.get("createTime") or raw.get("createdAt")
            ts = 0.0
            if when_raw:
                ts = parse_date_like(str(when_raw))
            parts = [stem]
            if ver_no != "":
                parts.append(f"v{ver_no}")
            if ts > 0:
                parts.append(datetime.fromtimestamp(ts).strftime("%Y%m%d_%H%M%S"))
            fname = " - ".join(parts) + ext
            return fname

        def _get_version_id(ver: dict):
            vid = ver.get("version_id")
            if not vid:
                raw = ver.get("_raw") or {}
                vid = raw.get("versionId") or raw.get("version_id")
            return vid

        def _download_version_local(ver: dict) -> str:
            version_id = _get_version_id(ver)
            if not version_id:
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
                local_path = self.api.download_document_version(version_id, fname, progress_cb=_cb)
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
            filenameA = _safe_ver_filename(name, verA)
            filenameB = _safe_ver_filename(name, verB)
            if filenameA == filenameB:
                stem, ext = os.path.splitext(filenameB)
                filenameB = f"{stem}_B{ext}"

            version_id_a = _get_version_id(verA)
            version_id_b = _get_version_id(verB)

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
                    pathA = self.api.download_document_version(version_id_a, filenameA)
                except Exception:
                    pathA = ""

            def _dl_b():
                nonlocal pathB
                try:
                    pathB = self.api.download_document_version(version_id_b, filenameB)
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
                    wait.accept()
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
            pdf_win._theme_managed_by_main = True
            pdf_win.setWindowModality(Qt.NonModal)  # Allow interaction with main window
            # Keep window on top of other windows
            
            # Apply theme to PDF window if functions available
            pdf_win.apply_theme_state(is_dark, persist=False)

            # Connect theme toggled signal from PDF_Compare to main window theme handler
            if hasattr(pdf_win, 'theme_switch') and hasattr(pdf_win.theme_switch, 'toggledTheme'):
                pdf_win.theme_switch.toggledTheme.connect(
                    lambda theme: self._on_theme_toggled(dark=(theme == THEME_DARK))
                )
            
            # Load PDFs if paths provided
            _downloads_prefix = os.path.abspath(DOWNLOAD_DIR)
            _versions_prefix = os.path.abspath(os.path.join(tempfile.gettempdir(), "larix_nexus_versions"))
            if pdf1_path and os.path.exists(pdf1_path):
                pdf_win.open_pdf_path(1, pdf1_path)
                # Mark as temp file for cleanup (downloads dir or versions temp dir)
                _p1 = os.path.abspath(pdf1_path)
                if _p1.startswith(_downloads_prefix) or _p1.startswith(_versions_prefix):
                    pdf_win._temp_files_to_cleanup.append(pdf1_path)
            if pdf2_path and os.path.exists(pdf2_path):
                pdf_win.open_pdf_path(2, pdf2_path)
                # Mark as temp file for cleanup (downloads dir or versions temp dir)
                _p2 = os.path.abspath(pdf2_path)
                if _p2.startswith(_downloads_prefix) or _p2.startswith(_versions_prefix):
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
            logging.exception("Failed to open PDF comparison window")
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
    def _get_notification_refresh_interval_seconds(self) -> int:
        """notification_refresh_interval from settings (sync group), default 300."""
        try:
            settings = load_settings()
            return max(1, int(settings.get("sync", {}).get("notification_refresh_interval", 300)))
        except Exception:
            return 300

    def _next_notification_check_datetime(self):
        """Next aligned notification poll time (local clock, no microseconds). Same grid as sync timer."""
        from datetime import timedelta

        now = datetime.now()
        interval_seconds = self._get_notification_refresh_interval_seconds()

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

    def _ms_until_next_notification_check(self) -> int:
        """Milliseconds until the next boundary-aligned notification poll."""
        next_run = self._next_notification_check_datetime()
        now = datetime.now()
        ms = int((next_run - now).total_seconds() * 1000)
        return max(ms, 1000)

    def _schedule_next_notification_timer(self) -> None:
        """Single-shot: fire at next aligned boundary, then timeout handler reschedules."""
        try:
            timer = getattr(self, "_notifications_timer", None)
            if timer is None:
                return
            timer.setSingleShot(True)
            timer.start(self._ms_until_next_notification_check())
        except Exception:
            pass

    @Slot()
    def _on_notifications_timer_timeout(self) -> None:
        try:
            self._check_notifications()
        except Exception:
            pass
        try:
            self._schedule_next_notification_timer()
        except Exception:
            pass

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
                # Interval read in _schedule_next_notification_timer via settings (default 300 s).
                if not hasattr(self, "_notifications_timer") or self._notifications_timer is None:
                    self._notifications_timer = QTimer(self)
                    self._notifications_timer.timeout.connect(self._on_notifications_timer_timeout)
                self._notifications_timer.setSingleShot(True)
                self._schedule_next_notification_timer()
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
                        tray_icon = QIcon(ICON_PATH) if ICON_PATH and os.path.exists(ICON_PATH) else QIcon()
                        if tray_icon.isNull():
                            tray_icon = self.windowIcon()
                        self._notify_tray.setIcon(tray_icon)
                    except Exception:
                        try:
                            self._notify_tray.setIcon(self.windowIcon())
                        except Exception:
                            self._notify_tray.setIcon(QIcon())
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
            try:
                settings = load_settings()
                idle_interval = max(1, int(settings.get("sync", {}).get("auto_sync_interval", 300)))
            except Exception:
                idle_interval = 300
            # Проверяем, прошёл ли выбранный интервал без активности
            current_time = time.time()
            last_activity = getattr(self, '_last_user_activity', current_time)
            time_since_activity = current_time - last_activity
            
            # Если с последней активности прошло меньше выбранного интервала, пропускаем
            if time_since_activity < idle_interval:
                return
            
            # Проверяем, есть ли загруженный проект
            pid = self.current_project_id()
            if not pid:
                return
            
            # Сохраняем текущее состояние файлов перед обновлением
            old_files_current = getattr(self, 'files_current', [])
            
            # Выполняем обновление
            try:
                if hasattr(self, "_show_status_message"):
                    self._show_status_message(t("status.auto_refresh"), 2000, owner="ui")
                else:
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
        """Backward-compatible hook: recursive search now follows flat mode."""
        self._search_recursive = bool(on)

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
        # Compute badge pixmaps first; if present, reserve a fixed right zone
        # and let Qt elide the text before that zone.
        notify_pixmap = None
        sync_pixmap = None
        try:
            # Notifications badge (INDEPENDENT)
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
            notify_pixmap = None

        try:
            # Sync badge (theme-aware via nik_icon) - INDEPENDENT
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
            sync_pixmap = None

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

        if notify_pixmap is None and sync_pixmap is None:
            # No badges: keep the previous behavior.
            return super().paint(painter, option, index)

        original_rect = QtCore.QRect(option.rect)
        badge_size = min(max(12, original_rect.height() - 4), 20)
        notify_draw_size = max(10, min(badge_size, int(badge_size * 0.85)))
        tab_px = 8
        right_pad = 4

        # Compute text rect and elided visible text width.
        opt = QtWidgets.QStyleOptionViewItem(option)
        try:
            self.inner.initStyleOption(opt, index)  # type: ignore[attr-defined]
        except Exception:
            pass

        widget = getattr(option, "widget", None)
        style = widget.style() if widget else QtWidgets.QApplication.style()
        text_rect = style.subElementRect(QtWidgets.QStyle.SE_ItemViewItemText, opt, widget)

        try:
            fm = QtGui.QFontMetrics(opt.font)
        except Exception:
            fm = painter.fontMetrics()

        badge_count = int(sync_pixmap is not None) + int(notify_pixmap is not None)
        gap_w = tab_px if badge_count >= 2 else 0
        badges_w = badge_count * badge_size + gap_w

        available_right = int(original_rect.right() - right_pad)
        available_text_w = max(0, int(available_right - text_rect.x() - tab_px - badges_w))

        # Let Qt draw the item (background, icon, elided text) with a clipped rect,
        # so text never renders under the badges.
        opt_text = QtWidgets.QStyleOptionViewItem(option)
        opt_text.rect = QtCore.QRect(original_rect)
        opt_text.rect.setRight(int(available_right - tab_px - badges_w))
        super().paint(painter, opt_text, index)

        # Draw badges immediately after visible text/ellipsis.
        try:
            elide_mode = getattr(opt, "textElideMode", QtCore.Qt.ElideRight)
        except Exception:
            elide_mode = QtCore.Qt.ElideRight

        try:
            drawn_text = fm.elidedText(str(getattr(opt, "text", "") or ""), elide_mode, int(available_text_w))
        except Exception:
            drawn_text = ""
        try:
            text_width = int(fm.horizontalAdvance(drawn_text))
        except Exception:
            text_width = 0

        badge_x = int(text_rect.x() + text_width + tab_px)
        badge_x = min(badge_x, int(available_right - badges_w + 1))
        badge_x = max(badge_x, int(text_rect.x()))

        try:
            cur_x = int(badge_x)
            if sync_pixmap is not None:
                y = original_rect.top() + (original_rect.height() - badge_size) // 2
                painter.drawPixmap(cur_x, int(y), sync_pixmap.scaled(badge_size, badge_size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                cur_x += badge_size + (tab_px if notify_pixmap is not None else 0)

            if notify_pixmap is not None:
                y = original_rect.top() + (original_rect.height() - notify_draw_size) // 2
                x2 = int(cur_x + (badge_size - notify_draw_size) // 2)
                painter.drawPixmap(x2, int(y), notify_pixmap.scaled(notify_draw_size, notify_draw_size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
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
