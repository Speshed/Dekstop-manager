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
try:
    from requests_toolbelt.multipart.encoder import MultipartEncoder  # type: ignore
except Exception:
    MultipartEncoder = None  # type: ignore 

# Imports from larix_nexus modules
from larix_nexus.api import APIClient
from larix_nexus.sync import sync_files_new

# Temporary imports from old Dekstop.py for sync functionality
# TODO: Move FolderSyncManager and _InitialSyncWorker to larix_nexus.sync module
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
try:
    from Dekstop import FolderSyncManager, _InitialSyncWorker
except Exception:
    FolderSyncManager = None
    _InitialSyncWorker = None
from larix_nexus.constants import (
    APP_TITLE, BASE_URL, DOWNLOAD_DIR, CACHE_TTL_SEC,
    CHECKBOX_COLUMN_WIDTH, NOTIFY_DB_PATH, NOTIFY_SETTINGS_GROUP,
    SETTINGS_ORG, SETTINGS_APP, SETTINGS_THEME_KEY,
    THEME_LIGHT, THEME_DARK, LIGHT_THEME_QSS, DARK_THEME_QSS, EXTRA_QSS,
    _COLOR_REPLACEMENTS, ICON_BOX, SYNC_ROLE, NOTIFY_ROLE,
    ALARM_ICON_PATH, ALARM1_ICON_PATH, LOGIN_ICON_PATH, EYE_OPEN_ICON_PATH, EYE_CLOSED_ICON_PATH
)
from larix_nexus.utils.paths import rsrc_path, program_dir, ICON_PATH
from larix_nexus.utils.logging import sync_log, sync_exc, _cleanup_sync_log_file, _sync_log_path
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
from larix_nexus.notifications import (
    init_notifications_db,
    load_pending_notifications,
    save_pending_notifications,
    load_folder_notifications,
    is_folder_notification_enabled,
    save_folder_notification,
    remove_folder_notification,
)
from larix_nexus.models.files_table import FilesTableModel, IconProvider, file_ext
from larix_nexus.models.tombstone_table import TombstoneTableModel

# Imports from ui modules
from .widgets import (
    NikCheckBoxStyle, ThemeToggle, StickyMenu, HeaderCheckButton,
    SortHeader, BusyDots, WaitDialog,
    CHECK_ICON_OFF_PATH, CHECK_ICON_ON_PATH
)
from .delegates import CheckBoxDelegate, CheckBoxDelegateBg
from .delegates import RowHoverDelegate, MenuLikeTreeDelegate
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
SORT_ICON_UP_PATH = rsrc_path("icon", "arrow-up.png").replace("\\", "/")
SORT_ICON_DOWN_PATH = rsrc_path("icon", "arrow-down.png").replace("\\", "/")
CUSTOM_ICONS_DIR = rsrc_path("icon")
ARROW_ICON_PATHS = {
    "left": rsrc_path("icon", "arrow-left.png").replace("\\", "/"),
    "right": rsrc_path("icon", "arrow-right.png").replace("\\", "/"),
    "up": SORT_ICON_UP_PATH,
    "down": SORT_ICON_DOWN_PATH,
}
FILTER_ICON_PATH = rsrc_path("icon", "filter.png").replace("\\", "/")
REFRESH_ICON_PATH = rsrc_path("icon", "free-icon-refresh-5234214.png").replace("\\", "/")
INSERT_ICON_PATH = rsrc_path("icon", "insert.png").replace("\\", "/")
EDIT_ICON_PATH = rsrc_path("icon", "edit.png").replace("\\", "/")
DELETE_ICON_PATH = rsrc_path("icon", "delete.png").replace("\\", "/")
STRUCTURE_ICON_PATH = rsrc_path("icon", "structure.png").replace("\\", "/")
SYNC_ICON_PATH = rsrc_path("icon", "sync.png").replace("\\", "/")
COMPARISON_ICON_PATH = rsrc_path("icon", "comparison.png").replace("\\", "/")
BACK_ICON_PATH = rsrc_path("icon", "back.png").replace("\\", "/")
CUSTOM_FOLDER_ICON_PATH = rsrc_path("icon", "folder_icon_variant_1.png").replace("\\", "/")
NO_FOLDER_ICON_PATH = rsrc_path("icon", "no folder.png").replace("\\", "/")
EYE_OPEN_ICON_PATH = rsrc_path("icon", "free-icon-eye-2455724.png").replace("\\", "/")
EYE_CLOSED_ICON_PATH = rsrc_path("icon", "free-icon-hide-11238328.png").replace("\\", "/")
CUSTOM_SAVE_ICON_PATH = rsrc_path("icon", "free-icon-download-126488.png").replace("\\", "/")
CUSTOM_PLUS_ICON_PATH = rsrc_path("icon", "free-icon-plus-3303893.png").replace("\\", "/")
DOWN_ARROW_ICON_PATH = rsrc_path("icon", "free-icon-down-arrow-3889508.png").replace("\\", "/")
FLASH_ICON_PATH = rsrc_path("icon", "flash.png").replace("\\", "/")
LOGIN_ICON_PATH = rsrc_path("icon", "free-icon-login-2623062.png").replace("\\", "/")
CAD_ICON_PATH = rsrc_path("icon", "free-icon-cad-8304395.png").replace("\\", "/")
GEAR_ICON_NAME = rsrc_path("icon", "free-icon-setting-3288004.png").replace("\\", "/")

# Local helper functions
def get_title(node: dict) -> str:
    return (node or {}).get("name") or (node or {}).get("title") or "Без названия"

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
                    valid_ids.add(idx.internalId())
                except Exception:
                    pass
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
        self.setWindowTitle("Авторизация")
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        form_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        settings = load_settings()
        saved_username = settings.get("last_username", "")

        self.le_username = QLineEdit(saved_username)
        form_layout.addRow(QLabel("Логин:"), self.le_username)

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
                self._eye_btn.setText("Показать" if not on else "Скрыть")
        self.le_password.setTextMargins(0, 0, 24, 0)
        self._eye_btn.toggled.connect(_sync_eye)
        _sync_eye(False)

        form_layout.addRow(QLabel("Пароль:"), self.le_password)

        layout.addLayout(form_layout)

        self.cb_remember = QCheckBox("Запомнить меня")
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
            QMessageBox.warning(self, "Ошибка", "Введите логин и пароль.")
            return

        if self.api.login(u, p, remember_me=remember):
            settings = load_settings()
            settings["remember_me"] = remember
            save_settings(settings)
            self.accept()
            return

        QMessageBox.critical(self, "Ошибка", "Неверный логин или пароль.")


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
                QtCore.QEvent.DragEnter,
                QtCore.QEvent.Drop
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
                    if hasattr(self, "hdrcb") and self.hdrcb and self.hdrcb.isVisible():
                        g = self.hdrcb.geometry()
                        if g.contains(ev.pos()):
                            pos = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
                            local = pos - g.topLeft()
                            qev = QtGui.QMouseEvent(t, local, ev.button(), ev.buttons(), ev.modifiers())
                            QtWidgets.QApplication.sendEvent(self.hdrcb, qev)
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

    def _themed_icon(self, path: str, *, tint_allowed: bool = True) -> QIcon:
        """Return icon taking current theme into account.
        - For arrow icons, always force white in dark theme.
        - For other icons, tint to white in dark theme when allowed.
        """
        try:
            if not path:
                return QIcon()
            normalized = path.replace("\\", "/")
            if normalized in ARROW_ICON_PATHS:
                if getattr(self, "_current_theme", THEME_LIGHT) == THEME_DARK:
                    return load_white_icon(path)
                return QIcon(path)
            if getattr(self, "_current_theme", THEME_LIGHT) == THEME_DARK and tint_allowed:
                return load_white_icon(path)
            return QIcon(path)
        except Exception:
            return QIcon(path)

    def _themed_standard_icon(self, std_icon: QStyle.StandardPixmap) -> QIcon:
        """Standard icon adjusted for current theme (white in dark)."""
        try:
            icon = self.style().standardIcon(std_icon)
        except Exception:
            icon = QIcon()
        if getattr(self, "_current_theme", THEME_LIGHT) == THEME_DARK:
            return white_tinted_icon(icon)
        return icon

    # --- persist UI preferences ---
    def _save_columns_visibility(self) -> None:
        try:
            model = self.table.model() or self.files_model
            if model is None:
                return
            try:
                count = model.columnCount()
            except Exception:
                count = len(getattr(FilesTableModel, "HEADERS", []))
            hidden = []
            for i in range(count):
                try:
                    if self.table.isColumnHidden(i):
                        hidden.append(str(i))
                except Exception:
                    continue
            s = _app_settings(); s.beginGroup("table")
            try:
                s.setValue("cols_hidden", ",".join(hidden))
                s.sync()
            finally:
                s.endGroup()
        except Exception:
            pass

    # --- auto sync progress indicators (first run) ---
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
            act_ru = 'Загрузка' if action == 'download' else ('Выгрузка' if action == 'upload' else action)
            folder_title = ""
            try:
                it = getattr(self, 'folder_item_by_id', {}).get(normalize_id(folder_id))
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

    def _load_columns_visibility(self) -> None:
        try:
            model = self.table.model() or self.files_model
            if model is None:
                return
            try:
                count = model.columnCount()
            except Exception:
                count = len(getattr(FilesTableModel, "HEADERS", []))
            s = _app_settings(); s.beginGroup("table")
            try:
                raw = s.value("cols_hidden", "") or ""
            finally:
                s.endGroup()
            applied = False
            if isinstance(raw, str) and raw.strip():
                parts = [p.strip() for p in str(raw).split(",") if p.strip().isdigit()]
                idxs = {int(p) for p in parts}
                for i in range(count):
                    try:
                        self.table.setColumnHidden(i, i in idxs)
                    except Exception:
                        pass
                applied = True
            if not applied:
                # default: ensure Modified column visible
                try:
                    if 0 <= 7 < count:
                        self.table.setColumnHidden(7, False)
                except Exception:
                    pass
        except Exception:
            pass

    def _update_filter_icon_pm(self) -> None:
        """(Re)load header filter overlay pixmap honoring current theme."""
        self._filter_icon_pm = None
        try:
            if not os.path.exists(FILTER_ICON_PATH):
                return

            target_size = QSize(14, 14)
            dark = getattr(self, "_current_theme", THEME_LIGHT) == THEME_DARK
            pm = QPixmap()

            if dark:
                try:
                    icon = load_white_icon(FILTER_ICON_PATH)
                    pm = icon.pixmap(target_size)
                except Exception:
                    pm = QPixmap()

            if pm.isNull():
                pm = QPixmap(FILTER_ICON_PATH)
                if dark and not pm.isNull():
                    pm = _tint_pixmap(pm, QColor(Qt.white))

            if pm.isNull():
                return

            if pm.size() != target_size:
                pm = pm.scaled(target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._filter_icon_pm = pm
        except Exception:
            pass

    def _update_search_icon(self) -> None:
        if not hasattr(self, "btn_search_deep"):
            return
        if self.btn_search_deep.isChecked():
            icon = self._tinted_icon(INSERT_ICON_PATH, QColor("#F7921E"))
        else:
            icon = self._themed_icon(INSERT_ICON_PATH)
        self.btn_search_deep.setIcon(icon)

    def _refresh_search_palette(self) -> None:
        try:
            self.search.style().unpolish(self.search)
            self.search.style().polish(self.search)
            self.search.update()
        except Exception:
            pass

    def _refresh_secondary_style(self, *buttons: QAbstractButton) -> None:
        for btn in buttons:
            if not isinstance(btn, QAbstractButton):
                continue
            try:
                style = btn.style()
                style.unpolish(btn)
                style.polish(btn)
                btn.update()
            except Exception:
                pass

    def _apply_icon_theme(self, theme: str) -> None:
        dark = theme == THEME_DARK

        def set_icon(btn: QAbstractButton, path: str, *, tint: bool = True, required: bool = False, text_on_missing: str | None = None):
            if path and os.path.exists(path):
                # remember base icon path for hover retinting
                try:
                    btn.setProperty("baseIconPath", path)
                except Exception:
                    pass
                btn.setIcon(self._themed_icon(path, tint_allowed=tint))
                if text_on_missing is not None:
                    btn.setText("")
                return True
            if required and text_on_missing is not None:
                btn.setIcon(QIcon())
                btn.setText(text_on_missing)
            return False

        set_icon(self.btn_refresh, REFRESH_ICON_PATH, tint=False)

        try:
            if BACK_ICON_PATH:
                set_icon(self.btn_back, BACK_ICON_PATH)
        except Exception:
            pass

        if CUSTOM_PLUS_ICON_PATH and os.path.exists(CUSTOM_PLUS_ICON_PATH):
            set_icon(self.btn_plus, CUSTOM_PLUS_ICON_PATH)
        else:
            self.btn_plus.setIcon(QIcon())
            self.btn_plus.setText("+")

        if CUSTOM_SAVE_ICON_PATH and os.path.exists(CUSTOM_SAVE_ICON_PATH):
            self.btn_download.setIcon(self._themed_icon(CUSTOM_SAVE_ICON_PATH))
        else:
            self.btn_download.setIcon(self._themed_standard_icon(QStyle.SP_DialogSaveButton))

        set_icon(self.btn_rename, EDIT_ICON_PATH)
        set_icon(self.btn_compare, COMPARISON_ICON_PATH)
        set_icon(self.btn_delete, DELETE_ICON_PATH)

        # Sync-all button: ensure icon follows theme (white in dark)
        try:
            if hasattr(self, 'btn_sync_all') and SYNC_ICON_PATH and os.path.exists(SYNC_ICON_PATH):
                self.btn_sync_all.setIcon(self._themed_icon(SYNC_ICON_PATH))
        except Exception:
            pass

        if os.path.exists(NO_FOLDER_ICON_PATH):
            set_icon(self.btn_no_folders, NO_FOLDER_ICON_PATH)
        else:
            self.btn_no_folders.setIcon(QIcon())
            self.btn_no_folders.setText("без папок")

        gear_path = self._resolve_icon_path(GEAR_ICON_NAME)
        if gear_path:
            set_icon(self.btn_columns, gear_path, tint=False)

        # Login control: show text "Войти" instead of icon
        try:
            if hasattr(self, "btn_login"):
                self.btn_login.setIcon(QIcon())
                self.btn_login.setText("Войти")
        except Exception:
            pass
                
        self._update_search_icon()
        # Update custom header arrows tint
        try:
            hdr = self.table.horizontalHeader()
            if isinstance(hdr, SortHeader):
                # print(f"DEBUG: Setting dark_mode={dark} on SortHeader")
                hdr.set_dark_mode(dark)
                # Принудительно перерисовываем header
                hdr.viewport().update()
        except Exception:
            pass
        # Rebuild header filter icon pixmap to respect theme
        try:
            self._update_filter_icon_pm()
            self.header_filter_icons_update()
        except Exception:
            pass
        # Propagate theme flag to views for custom delegates
        try:
            self.table._dark_theme = dark
            self.tree._dark_theme = dark
            vp = getattr(self.tree, "viewport", None)
            if callable(vp):
                vp = self.tree.viewport()
            if vp is not None:
                setattr(vp, "_dark_theme", dark)
                vp.update()
        except Exception:
            pass
        # Header checkbox style to white in dark theme
        try:
            if hasattr(self, "hdrcb"):
                self.hdrcb.setStyle(self._checkbox_style if dark else self.style())
        except Exception:
            pass
        
        # Update notification button icon for theme
        try:
            if hasattr(self, "btn_notify"):
                has_pending = bool(getattr(self, "_pending_notifications", {}))
                path = ALARM1_ICON_PATH if has_pending else ALARM_ICON_PATH
                self.btn_notify.setIcon(self._themed_icon(path))
        except Exception:
            pass

        try:
            if hasattr(self, "_status_icons") and isinstance(self._status_icons, dict):
                # status icons remain as loaded, no recolor required
                pass
        except Exception:
            pass

        if hasattr(self, "btn_back"):
            try:
                self.btn_back.update()
            except Exception:
                pass

        self._refresh_secondary_style(
            getattr(self, "btn_refresh", None),
            getattr(self, "btn_back", None),
            getattr(self, "btn_go_to_root", None),
            getattr(self, "btn_plus", None),
            getattr(self, "btn_download", None),
            getattr(self, "btn_rename", None),
            getattr(self, "btn_delete", None),
            getattr(self, "btn_columns", None),
            getattr(self, "btn_no_folders", None),
        )

        self._refresh_search_palette()
        # Update notification icon theme
        try:
            self._update_notify_icon()
        except Exception:
            pass

    def _restore_button_icon_from_base(self, btn: QAbstractButton) -> None:
        try:
            path = str(btn.property("baseIconPath") or "")
            if path:
                btn.setIcon(self._themed_icon(path))
        except Exception:
            pass

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

    def _apply_hover_filter(self, btn: QAbstractButton) -> None:
        try:
            if not isinstance(btn, QAbstractButton):
                return
            old = getattr(btn, '_hover_filter', None)
            if isinstance(old, QObject):
                try:
                    btn.removeEventFilter(old)
                except Exception:
                    pass
            filt = self._HoverIconFilter(btn)
            try:
                btn.setMouseTracking(True)
            except Exception:
                pass
            btn.installEventFilter(filt)
            setattr(btn, '_hover_filter', filt)
        except Exception:
            pass

    def _install_hover_black_icons(self) -> None:
        """Install per-button hover filters so icons become black on hover in dark theme."""
        try:
            widgets = [
                getattr(self, 'btn_plus', None),
                getattr(self, 'btn_download', None),
                getattr(self, 'btn_rename', None),
                getattr(self, 'btn_compare', None),
                getattr(self, 'btn_delete', None),
                getattr(self, 'btn_go_to_root', None),
                getattr(self, 'btn_back', None),
                getattr(self, 'btn_refresh', None),
                getattr(self, 'btn_columns', None),
                getattr(self, 'btn_no_folders', None),
                getattr(self, 'btn_sync_all', None),
                # btn_notify excluded - keep white icon on hover
            ]
            for b in widgets:
                if isinstance(b, QAbstractButton):
                    self._apply_hover_filter(b)
        except Exception:
            pass

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
            print("WARNING: FolderSyncManager not available from Dekstop.py")
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

        self.cb_projects.setMinimumWidth(420); self.cb_projects.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        try:
            self.cb_projects.aboutToPopup.connect(self.ensure_projects_loaded)
            self.cb_projects.aboutToPopup.connect(self.adjust_projects_popup)
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
        self.btn_refresh.setToolTip("Обновить")

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
        self.btn_back.setToolTip("Назад")
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
        self.btn_sync_all.setToolTip("Синхронизировать все")
        try:
            self.btn_sync_all.setIconSize(self.btn_refresh.iconSize())
        except Exception:
            pass
        try:
            self.btn_sync_all.clicked.connect(self._on_sync_all_clicked)
        except Exception:
            pass

        self.btn_go_to_root = QToolButton(self); self.btn_go_to_root.setText("В корень"); self.btn_go_to_root.setProperty("secondary", True)        # Add btn_login here
        self._refresh_secondary_style(self.btn_go_to_root)
        self.btn_login = QToolButton(self); self.btn_login.setText("Войти"); self.btn_login.setProperty("secondary", False)
        self.btn_login.setEnabled(True); self.btn_login.setCursor(Qt.PointingHandCursor); self.btn_login.setObjectName("accent")

        # Кнопка "+" для загрузки/создания
        self.btn_plus = QToolButton(self); self.btn_plus.setText("+")
        self.btn_plus.setObjectName("btnPlus")
        self.btn_plus.setPopupMode(QToolButton.InstantPopup)
        self.btn_plus.setProperty("secondary", True)
        self._refresh_secondary_style(self.btn_plus)
        if hasattr(self, "btn_download"):
            self.btn_plus.setIconSize(self.btn_download.iconSize())
        self.btn_plus.setToolTip("Добавить")

        try:
            if CUSTOM_PLUS_ICON_PATH and os.path.exists(CUSTOM_PLUS_ICON_PATH):
                self.btn_plus.setIcon(self._themed_icon(CUSTOM_PLUS_ICON_PATH)); self.btn_plus.setText("")
        except Exception:
            pass

        # новое меню для кнопки "+"
        menu_plus = QMenu(self.btn_plus)
        menu_plus.setObjectName("plusMenu")
        try:
            menu_plus.setMinimumWidth(160)
            menu_plus.setMaximumWidth(220)
        except Exception:
            pass

        # создаём экшены один раз и запоминаем их как поля
        self.act_upload_file = QAction("Загрузить файл", self)
        self.act_upload_file.triggered.connect(self._action_upload_file)

        self.act_create_folder = QAction("Создать папку", self)
        self.act_create_folder.triggered.connect(self._action_create_folder)

        self.act_upload_folder = QAction("Загрузить папку", self)
        self.act_upload_folder.triggered.connect(self._action_upload_folder)

        # порядок: файл -> создать папку -> загрузить папку
        menu_plus.addAction(self.act_upload_file)
        menu_plus.addAction(self.act_create_folder)
        menu_plus.addAction(self.act_upload_folder)

        self.btn_plus.setMenu(menu_plus)
        self.btn_plus.setPopupMode(QToolButton.InstantPopup)

        # перед показом меню скрываем/показываем пункт "Загрузить файл" в зависимости от того, открыт ли корень
        menu_plus.aboutToShow.connect(self._update_upload_menu_visibility)

        self.btn_login.setEnabled(True); self.btn_login.setCursor(Qt.PointingHandCursor); self.btn_login.setObjectName("accent")
        self.btn_user = QToolButton(self); self.btn_user.setVisible(False); self.btn_user.setPopupMode(QToolButton.InstantPopup)
        self.btn_user.setObjectName("btnUser")
        self.btn_user_menu = QMenu(self.btn_user); self.btn_user.setMenu(self.btn_user_menu)
        self.btn_user_menu.setObjectName("userMenu")

        # Отдельная кнопка "Создать пользователя" на верхней панели

        self.btn_user_menu.clear()
        act_switch = self.btn_user_menu.addAction("Сменить пользователя")
        act_switch.triggered.connect(self.logout_and_relogin)

        act_create = self.btn_user_menu.addAction("Создать пользователя")

        self.btn_download = QToolButton(self)
        self.btn_download.setProperty("secondary", True)
        self._refresh_secondary_style(self.btn_download)
        self.btn_download.setObjectName("btnDownload")
        self.btn_download.setIcon(white_tinted_icon(self.style().standardIcon(QStyle.SP_DialogSaveButton))); 
        self.btn_download.setToolTip("Скачать отмеченное")
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
        self.btn_rename.setToolTip("Переименовать")
        # Сравнить версии
        self.btn_compare = QToolButton(self)
        self.btn_compare.setProperty("secondary", True)
        self._refresh_secondary_style(self.btn_compare)
        self.btn_compare.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.btn_compare.setIcon(self._themed_icon(COMPARISON_ICON_PATH))
        self.btn_compare.setIcon(self._themed_icon(COMPARISON_ICON_PATH, tint_allowed=True))
        self.btn_compare.setText("")
        self.btn_compare.setToolTip("Сравнить версии")
        self.btn_compare.setEnabled(False)


        # Удалить
        self.btn_delete = QToolButton(self)
        self.btn_delete.setProperty("secondary", True)
        self._refresh_secondary_style(self.btn_delete)
        self.btn_delete.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.btn_delete.setIcon(self._themed_icon(DELETE_ICON_PATH))
        self.btn_delete.setText("")
        self.btn_delete.setToolTip("Удалить")

        # чтобы размер иконок совпал с кнопкой «скачать»
        same = self.btn_download.iconSize()
        self.btn_rename.setIconSize(same)
        self.btn_delete.setIconSize(same)
        self.btn_compare.setIconSize(same)
        for b in (self.btn_download, self.btn_delete, self.btn_rename):
            b.setEnabled(False)

        # Порядок: Документы — Проект: [combo] — Обновить — В корень — Диаграмма — [справа: Войти/Пользователь]
        lbl_proj = QLabel("Проект:", self)
        for w in (lbl_proj, self.cb_projects, self.btn_refresh, self.btn_go_to_root, self.btn_back, self.btn_sync_all):
            top_l.addWidget(w)
        top_l.addStretch(1)
        sun_icon_path = self._resolve_icon_path("sun.png")
        moon_icon_path = self._resolve_icon_path("moon.png")
        self.theme_toggle = ThemeToggle(sun_icon_path=sun_icon_path, moon_icon_path=moon_icon_path, parent=self)
        self.theme_toggle.setToolTip("Light / Dark")
        # Всегда начинаем со светлой темы (unchecked)
        self.theme_toggle.blockSignals(True)
        self.theme_toggle.setChecked(False)  # False = светлая тема
        self.theme_toggle.snap_to_state()
        self.theme_toggle.blockSignals(False)
        self.theme_toggle.toggled.connect(self._on_theme_toggled)
        # expose alias with camelCase name requested by UX
        self.themeToggle = self.theme_toggle
        top_l.addWidget(self.theme_toggle)
        
        # Notifications button (alarm icon) near theme switch - СПРАВА
        self.btn_notify = QToolButton(self)
        self.btn_notify.setObjectName("btnNotify")
        self.btn_notify.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.btn_notify.setAutoRaise(False)
        self.btn_notify.setCursor(Qt.PointingHandCursor)
        # Use themed icon so it turns white in dark theme
        self.btn_notify.setIcon(self._themed_icon(ALARM_ICON_PATH))
        self.btn_notify.setToolTip("Уведомления")
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
        self.search = QLineEdit(self); self.search.setPlaceholderText("Поиск по имени")
        # флаг логики (если где-то выше не задан)
        self._search_recursive = getattr(self, "_search_recursive", False)

        # кнопка внутри поля поиска (справа)
        self.btn_search_deep = QToolButton(self.search)
        self.btn_search_deep.setObjectName("searchDeepBtn")
        self.btn_search_deep.setCheckable(True)
        self.btn_search_deep.setChecked(self._search_recursive)
        self.btn_search_deep.setCursor(Qt.PointingHandCursor)
        self.btn_search_deep.setIcon(self._themed_icon(INSERT_ICON_PATH))
        self.btn_search_deep.setToolTip("Искать во вложенных папках")
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
        self.btn_no_folders.setToolTip("Показывать только файлы (без папок)")

        try:
            if os.path.exists(NO_FOLDER_ICON_PATH):
                self.btn_no_folders.setIcon(self._themed_icon(NO_FOLDER_ICON_PATH))
                # иконка ровно как у "Скачать"
                if hasattr(self, "btn_download"):
                    self.btn_no_folders.setIconSize(self.btn_download.iconSize())
            else:
                # запасной вариант, если иконки нет
                self.btn_no_folders.setToolButtonStyle(Qt.ToolButtonTextOnly)
                self.btn_no_folders.setText("без папок")
        except Exception:
            self.btn_no_folders.setToolButtonStyle(Qt.ToolButtonTextOnly)
            self.btn_no_folders.setText("без папок")

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
        self.btn_columns.setToolTip("Настройки столбцов")

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

        fl.addWidget(self.btn_columns)

        split = QSplitter(self)
        split.setHandleWidth(2)
        try:
            self._enhance_splitter_handles(split)
        except Exception:
            pass
        split.setContentsMargins(0,0,0,0)  # без внешних отступов

        self.tree = QTreeWidget(self); self.tree.setHeaderLabels(["Файлы проекта"]); self.tree.header().setStretchLastSection(True)
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
        # Unify tree row hover/selection width and keep selection color on hover
        try:
            self.tree.setItemDelegate(MenuLikeTreeDelegate(self.tree))
        except Exception:
            pass
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu); self.tree.customContextMenuRequested.connect(self._ctx_menu_sync)
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
        self.table.setItemDelegate(RowHoverDelegate(
            parent=self.table,
            icon_size=ICON_BOX,
            # Match hover/pressed visuals of buttons (see QSS in utils/theme.py)
            hover_color=QtGui.QColor(247, 146, 30, int(255 * 0.10)),
            # Selected row should be more prominent than hover
            selected_color=QtGui.QColor(247, 146, 30, int(255 * 0.28)),
            pressed_color=QtGui.QColor(247, 146, 30, int(255 * 0.20)),
        ))

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

        # Всегда включена сортировка и индикатор - чтобы было что рисовать
        self.table.setSortingEnabled(False)
        hdr.setSortIndicatorShown(True)
        try:
            name_col = FilesTableModel.HEADERS.index("Название")
        except Exception:
            name_col = 1
        hdr.setSortIndicator(name_col, Qt.AscendingOrder)

        # — отключаем сортировку и прячем стрелку по умолчанию
        self._sorting_armed = False
        self.table.setSortingEnabled(False)
        hdr.setSortIndicatorShown(False)


        # — при первом нажатии по заголовку включим сортировку и вернём стрелку
        hdr = self.table.horizontalHeader()
        try:
            hdr.sectionClicked.disconnect(self._arm_sorting)
        except Exception:
            pass



        try:
            # колонка по умолчанию
            name_col = FilesTableModel.HEADERS.index("Название")
        except Exception:
            name_col = 1

        default_order = Qt.AscendingOrder
        self._last_sort_section = name_col
        self._last_sort_order = default_order

        # если нужен хук на смену сортировки - оставь
        try:
            hdr.sortIndicatorChanged.connect(self.on_sort_changed, Qt.UniqueConnection)
        except Exception:
            pass

        hdr.setSectionResizeMode(0, QHeaderView.Fixed)  # 0-я колонка фикс
        hdr.resizeSection(0, CHECKBOX_COLUMN_WIDTH)
        # Do not stretch only the last section; manage widths ourselves to avoid oversized right column
        self.table.horizontalHeader().setStretchLastSection(False); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        # Жёстко фиксируем только 0-й столбец
        hdr.setSectionResizeMode(0, QHeaderView.Fixed)
        hdr.resizeSection(0, CHECKBOX_COLUMN_WIDTH)
        
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
        self.table.setContextMenuPolicy(Qt.CustomContextMenu); self.table.customContextMenuRequested.connect(self.table_context_menu)
        self.table.viewport().installEventFilter(self)
        self.table.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        # Автоскрытие 0-й колонки при горизонтальной прокрутке
        self.table.horizontalScrollBar().valueChanged.connect(self._toggle_first_col_on_scroll)
        self.table.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.horizontalHeader().customContextMenuRequested.connect(self.header_context_menu)
        hdr = self.table.horizontalHeader()
        hdr.setSectionsClickable(True)
       
        hdr.sectionClicked.connect(self._on_header_clicked_sort, Qt.UniqueConnection)

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
        try:
            self.hdrcb.raise_()
        except Exception:
            pass

        self.hdrcb.setToolTip("Выбрать / снять все")
        self.hdr.viewport().installEventFilter(self)
        
        try:
            self.hdr.sectionResized.connect(self._update_header_checkbox_pos)
            self.hdr.sectionMoved.connect(self._update_header_checkbox_pos)
            self.hdr.geometriesChanged.connect(self._update_header_checkbox_pos)
        except Exception:
            pass


        self.hdrcb.stateChanged.connect(lambda *_: self._update_actions_enabled())
        self.hdrcb.stateChanged.connect(self.on_header_cb_state_changed)
        # Убираем toggled.connect чтобы избежать двойной обработки
        # self.hdrcb.toggled.connect(self.on_header_cb_clicked)
        # Для совместимости используем stateChanged - HeaderCheckButton не имеет сигнала toggled
        # Клик по самой картинке приводит к смене состояния и попадает в on_header_cb_state_changed

        self._update_header_checkbox_pos()
        try:
            # Make sure the header checkbox sits above any overlay labels/icons
            self.hdrcb.raise_()
        except Exception:
            pass



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
        self.progress.setVisible(False)
        self.status.addPermanentWidget(self.progress)
        
        # Глобальная кнопка уведомлений (колокольчик) справа в status bar
        self.global_notify_btn = QPushButton(self)
        self.global_notify_btn.setFlat(True)
        self.global_notify_btn.setFixedSize(32, 28)
        self.global_notify_btn.setIconSize(QSize(20, 20))
        self.global_notify_btn.setIcon(QIcon(ALARM1_ICON_PATH))  # Set initial icon
        self.global_notify_btn.setToolTip("Уведомления")
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
        self.btn_delete.setToolTip("Удалить отмеченное")
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
        
        self.table.setObjectName("filesTable")
        self.table.setProperty("dropHoverEmpty", False)
        self.table.viewport().setAcceptDrops(True)  # если ещё не включено
        self.table.viewport().setAttribute(Qt.WA_StyledBackground, True)
        self.table.viewport().setAutoFillBackground(True)
        # DnD только для центральной таблицы (правая область)
        self.table.setObjectName("filesTable")
        self.table.setProperty("dropHover", False)
        self.table.setDragDropMode(QAbstractItemView.NoDragDrop)
        self.table.setDefaultDropAction(Qt.CopyAction)
        self.table.setSortingEnabled(True)
        
        self._tune_columns()
        self._bind_table_selection_signals()
        self._update_actions_enabled()
        # Ensure checkbox background uses the same hover/selected colors and the inner delegate draws the checkbox
        self.table.setItemDelegateForColumn(0, CheckBoxDelegateBg(self.table, CheckBoxDelegate(self.table)))
        # Клик на чекбокс обрабатывается в CheckBoxDelegate.editorEvent
        # Обновляем состояние заголовочного чекбокса при любых изменениях данных
        try:
            # Сигналы прокси
            self.proxy.dataChanged.connect(lambda *_: self.update_header_checkbox())
            self.proxy.rowsInserted.connect(lambda *_: self.update_header_checkbox())
            self.proxy.rowsRemoved.connect(lambda *_: self.update_header_checkbox())
            self.proxy.modelReset.connect(lambda *_: self.update_header_checkbox())
            # И одновременно пересчитываем доступность кнопок
            self.files_model.dataChanged.connect(lambda *_: self._update_actions_enabled())
        except Exception:
            pass
        self.update_header_checkbox()
        self.table.horizontalHeader().sortIndicatorChanged.connect(self.on_sort_changed)

        self.set_initial_view()

        # Автовход через переменные окружения или диалог
        env_user, env_pass = os.environ.get("LARIX_USER"), os.environ.get("LARIX_PASS")
        if env_user and env_pass and self.api.login(env_user, env_pass, remember_me=True):
            self.on_logged_in()
        else:
            # Не авторизованы на старте; пользователь сам жмёт 'Войти'
            self.status.showMessage('Не авторизован')

            
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
                self.userButton.setText("Гость")  # ли пустая строка/иконка
            except AttributeError:
                pass
    def _menu_exec(self, menu, global_pos):
        try:
            return menu.exec(global_pos)   # PySide6 / Qt6
        except Exception:
            return menu.exec_(global_pos)  # PyQt5

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
        act_zip = menu.addAction("Скачать как ZIP")
        act_folder = menu.addAction("Скачать структуру")
        menu.addSeparator()

        folder_id = (node or {}).get("id")
        fid_key = normalize_id(folder_id)
        is_synced = bool(getattr(self, 'sync2', None) and self.sync2.is_synced(folder_id))
        if is_synced:
            act_path_open = None
            try:
                pth = self.sync2.get_sync_path(folder_id)
                act_path_open = menu.addAction("Путь синхронизации…")
                act_path_open.setToolTip(pth)
            except Exception:
                pth = ""
            # Показать время до следующей синхронизации
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
                            return f"{m} мин {s:02d} сек"
                        return f"{s} сек"
                    except Exception:
                        return "—"
                eta_text = _fmt_eta(eta_ms)
                act_eta = menu.addAction(f"Следующая синхронизация: через {eta_text}")
                act_eta.setEnabled(False)
            except Exception:
                pass
            act_unsync = menu.addAction("Отключить синхронизацию")
        else:
            act_sync = menu.addAction("Синхронизировать...")
            try:
                act_sync.setEnabled(bool(self.api.is_available()))
            except Exception:
                pass

        if is_synced:
            try:
                act_sync_now = menu.addAction("Синхронизировать сейчас")
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
                act_view_notif = menu.addAction("Уведомления")

            # Пункт подписки/отписки - всегда показывается
            try:
                if subscribed:
                    act_sub = menu.addAction("Отписаться от уведомлений")
                else:
                    act_sub = menu.addAction("Подписаться на уведомления")
            except Exception:
                act_sub = None

        except Exception:
            act_view_notif = None
            act_sub = None

        chosen = self._menu_exec(menu, self.tree.mapToGlobal(pos))
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

                QMessageBox.information(self, "Синхронизация", "Синхронизация отключена.")
            except Exception:
                pass
            return
        if (not is_synced) and chosen == locals().get('act_sync'):
            if not self.api.is_available():
                try:
                    self.status.showMessage("Сервер недоступен. Повторите попытку позже.", 5000)
                except Exception:
                    pass
                return
            path = QFileDialog.getExistingDirectory(self, "Выберите локальную папку для синхронизации", "", QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks)
            if not path:
                return
            # создаём подпапку с именем облачной папки внутри выбранного пути
            try:
                folder_name = ""
                try:
                    folder_name = item.text(0)
                except Exception:
                    try:
                        folder_name = (node or {}).get("name") or ""
                    except Exception:
                        folder_name = ""
                safe_name = _sanitize_filename(folder_name) or f"folder_{folder_id}"
                target_dir = os.path.join(path, safe_name)
                os.makedirs(target_dir, exist_ok=True)
                path = target_dir  # дальше работаем именно с подпапкой
            except Exception:
                pass

            proj = self.current_project_id()
            if not proj:
                QMessageBox.warning(self, "Синхронизация", "Не выбран проект.")
                return
            
            # ДИАГНОСТИКА: Проверка sync2
            sync_log("SYNC_MENU: folder_id={} path='{}' project_id={}", folder_id, path, proj)
            
            try:
                if not hasattr(self, 'sync2') or self.sync2 is None:
                    sync_log("SYNC_MENU: ERROR - self.sync2 не существует или равен None!")
                    msg = "Менеджер синхронизации не инициализирован!\n\n"
                    if not hasattr(self, 'sync2'):
                        msg += "Атрибут sync2 не найден. Проверьте инициализацию в __init__."
                    elif self.sync2 is None:
                        msg += "Атрибут sync2 равен None. Возможно, не удалось импортировать FolderSyncManager из Dekstop.py."
                    QMessageBox.critical(self, "Ошибка", msg)
                    return
                
                sync_log("SYNC_MENU: Вызов self.sync2.add_sync...")
                self.sync2.add_sync(folder_id, path, proj)
                sync_log("SYNC_MENU: add_sync успешно выполнен")
            except Exception as e:
                sync_log("SYNC_MENU: ERROR в add_sync - {}", str(e))
                import traceback
                full_traceback = traceback.format_exc()
                sync_log("SYNC_MENU: TRACEBACK:\n{}", full_traceback)
                QMessageBox.critical(self, "Ошибка", f"Не удалось добавить папку в синхронизацию:\n{e}\n\n{full_traceback}")
                return
            
            try:
                item.setData(0, SYNC_ROLE, True)
                self.tree.viewport().update()
            except Exception as e:
                sync_log("SYNC_MENU: WARNING - не удалось обновить UI дерева: {}", str(e))
            
            # КРИТИЧНО: НЕ глушим исключения!
            try:
                sync_log("SYNC_MENU: Запуск _start_initial_sync...")
                self._start_initial_sync(folder_id, path, proj)
                sync_log("SYNC_MENU: _start_initial_sync запущен успешно")
            except Exception as e:
                sync_log("SYNC_MENU: CRITICAL ERROR в _start_initial_sync - {}", str(e))
                import traceback
                sync_log("TRACEBACK:\n{}", traceback.format_exc())
                try:
                    self.progress.setVisible(False)
                except Exception:
                    pass
                QMessageBox.critical(self, "Ошибка синхронизации", 
                                   f"Не удалось запустить синхронизацию:\n{e}\n\nПодробности в логе: sync\\_sync_debug.log")
                return
            
            QMessageBox.information(self, "Синхронизация",f"Папка будет синхронизирована каждые 30 минут (в 00 и 30 минут каждого часа) после первичной загрузки.\nПуть: {path}")


        # Handle "View Notifications" action
        if chosen == locals().get('act_view_notif'):
            if node:
                try:
                    folder_id_check = normalize_id((node or {}).get("id"))
                    if folder_id_check:
                        self._show_changes_dialog(folder_id_check)
                except Exception as e:
                    QMessageBox.warning(self, "Ошибка", f"Не удалось показать уведомления: {e}")
            return

        # Notifications subscribe/unsubscribe handling
        if (chosen == locals().get('act_sub')) or (chosen and chosen.text() in ("Подписаться на уведомления", "Отписаться от уведомлений", "Отключить уведомления")):
            # Используем централизованную функцию для обработки подписки
            if node:
                self.toggle_folder_notifications(node)
            return

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
                    if fid and hasattr(self, 'sync2'):
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
                if hasattr(self, 'sync2') and not self.sync2.timer.isActive():
                    self.sync2.schedule_next_half_hour()
                    
            else:
                base = getattr(self, "_sync_path", "")
                msg = f"Синхронизация прервана: {base}" if base else "Синхронизация прервана"
                self.status.showMessage(msg, 8000)
                # Show expanded error dialog with details, avoid truncation
                try:
                    from PySide6.QtWidgets import QMessageBox
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

    @QtCore.Slot(bool)
    def _on_sync_now_finished(self, ok: bool):
        try:
            self.progress.setVisible(False)
            self.progress.setRange(0, 0)
            base = getattr(self, "_sync_now_path", "")
            if ok:
                self.status.showMessage((f"Синхронизация завершена: {base}" if base else "Синхронизация завершена"), 4000)
                # Обновить список файлов после успешной синхронизации
                try:
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

    def _trigger_sync_now(self, folder_id: int | str) -> None:
        try:
            path = self.sync2.get_sync_path(folder_id) if hasattr(self, 'sync2') else ""
        except Exception:
            path = ""
        self._sync_now_path = path
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
        th.started.connect(worker.run)
        worker.sig_started.connect(self._on_sync_now_started, QtCore.Qt.QueuedConnection)
        worker.sig_finished.connect(self._on_sync_now_finished, QtCore.Qt.QueuedConnection)
        # Per-thread cleanup when worker finishes
        try:
            worker.sig_finished.connect(lambda _ok, _th=th, _w=worker: self._cleanup_worker_thread(_th, _w), QtCore.Qt.QueuedConnection)
        except Exception:
            pass
        th.start()

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

    @QtCore.Slot()
    def _on_sync_all_clicked(self):
        try:
            mgr = getattr(self, 'sync2', None)
            if not mgr or not getattr(mgr, 'map', None):
                return
            try:
                self.status.showMessage("Синхронизация всех папок запущена", 3000)
            except Exception:
                pass
            # Run each folder's sync in its own worker to avoid blocking UI
            for fid, cfg in list(mgr.map.items()):
                # only those with configured local path
                try:
                    lp = (cfg or {}).get('local_path') or ''
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

    def closeEvent(self, event):
        """Ensure all worker threads are cleanly stopped before window closes."""
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

    @QtCore.Slot()
    def _on_sync_cancel(self):
        # invoke worker.cancel() in its own thread
        try:
            worker = getattr(self, "_sync_worker", None)
            if worker is not None:
                QtCore.QMetaObject.invokeMethod(worker, "cancel", QtCore.Qt.QueuedConnection)
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
                raise ImportError("_InitialSyncWorker недоступен - проверьте импорт из Dekstop.py")
            
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
            self.progress.setVisible(True)
            self.progress.setRange(0, 0)
            self.status.showMessage(f"Синхронизация: {path} — подсчет файлов…")
            sync_log("✓ UI обновлён (прогресс-бар показан)")
        except Exception as e:
            sync_log("WARNING: не удалось обновить UI: {}", str(e))

        try:
            btn_cancel = QPushButton("Отмена", self)
            btn_cancel.setObjectName("syncCancelBtn")
            btn_cancel.setProperty("chip", True)

            self.status.addPermanentWidget(btn_cancel)
            self._sync_cancel_btn = btn_cancel
            btn_cancel.clicked.connect(self._on_sync_cancel)
            sync_log("✓ Кнопка отмены создана")
        except Exception as e:
            sync_log("WARNING: не удалось создать кнопку отмены: {}", str(e))
            self._sync_cancel_btn = None

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

    def _on_selection_changed(self, *args):
        self._update_actions_enabled()

    def _on_model_data_changed(self, *args):
        # то, что вы делали в лямбде
        try:
            self.update_header_checkbox()
        except Exception:
            pass
        self._update_actions_enabled()

        try:
            self._resize_columns_to_contents_and_fill()
        except Exception:
            pass

    def _recalc_columns(self, *args):
        try:
            self._resize_columns_to_contents_and_fill()
        except Exception:
            pass

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

    
    def _update_actions_enabled(self):
        try:
            n_checked = len(self.get_checked_visible_items())
        except Exception:
            n_checked = 0

        try:
            sel = self.selected_item() or {}
            has_sel = bool(sel)
        except Exception:
            sel = {}
            has_sel = False

        # скачать - если есть галочки Л есть выделение (файл или папка)
        can_download = (n_checked > 0) or has_sel
        # удалить - если есть галочки Л есть выделение
        can_delete   = (n_checked > 0) or has_sel
        # переименовать - одиночное выделение Л ровно одна галочка
        try:
            sel_rows = self.table.selectionModel().selectedRows()
            has_single_selection = len(sel_rows) == 1
        except Exception:
            has_single_selection = False
        can_rename = has_single_selection or (n_checked == 1)
                # сравнение версий - если выбран хотя бы один файл с >=2 версиями (только PDF)
        can_compare = False
        try:
            candidates = []
            if n_checked > 0:
                candidates = [it for it in self.get_checked_visible_items() if str(it.get("type", "")).lower() == "file"]
            elif has_sel and str(sel.get("type", "")).lower() == "file":
                candidates = [sel]
            for it in candidates:
                try:
                    fname = it.get("originalName") or it.get("name") or ""
                    if not fname.lower().endswith('.pdf'):
                        continue
                    vers = self.api.get_document_versions(it.get("id"))
                    if isinstance(vers, dict):
                        vers = vers.get("versions") or []
                    if len(list(vers or [])) >= 2:
                        can_compare = True
                        break
                except Exception:
                    continue
        except Exception:
            can_compare = False


        for btn, state in (
            (self.btn_download, can_download),
            (self.btn_delete,   can_delete),
            (self.btn_rename,   can_rename),
        ):
            try:
                btn.setEnabled(state)
            except Exception:
                pass

        # отдельная логика доступности для кнопки сравнения версий
        try:
            self.btn_compare.setEnabled(bool(globals()))
            self.btn_compare.setEnabled(can_compare)
        except Exception:
            pass


    def _zip_folder_to_path(self, node: dict, save_path: str):
        if not node or node.get("type") != "folder":
            return

        files_to_pack, dir_paths = self._collect_files_and_dirs_for_zip(node)

        # Пишем ZIP напрямую, без промежуточного сохранения файлов на диск
        try:
            self.progress.setVisible(True)
            self.progress.setRange(0, 0)
            QApplication.processEvents()
        except Exception:
            pass
        wait = None
        try:
            wait = WaitDialog("Архивирование папки...", self)
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
                self.progress.setVisible(False)
            except Exception:
                pass
            try:
                if wait:
                    wait.set_done("Готово")
            except Exception:
                pass

    def _populate_columns_menu(self):
        try:
            self.menu_columns.clear()
            
            settings = load_settings()
            current_notification_interval = settings.get("sync", {}).get("notification_refresh_interval", 300)
            current_sync_interval = settings.get("sync", {}).get("auto_sync_interval", 300)
            
            notification_intervals = [
                (300, "5 минут"),
                (600, "10 минут"),
                (900, "15 минут"),
                (1800, "30 минут"),
                (2700, "45 минут"),
                (3600, "60 минут"),
                (86400, "1 раз в день")
            ]
            
            sync_intervals = notification_intervals.copy()
            
            act_notification = self.menu_columns.addAction("Частота уведомлений")
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
            
            act_sync = self.menu_columns.addAction("Частота синхронизации")
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
            
            act_columns = self.menu_columns.addAction("Столбцы")
            menu_columns_submenu = QMenu(self)
            model = self.table.model()
            if model:
                cols = model.columnCount()
                for col in range(1, cols):
                    title = str(model.headerData(col, Qt.Horizontal) or f"Столбец {col}")
                    act = menu_columns_submenu.addAction(title)
                    act.setCheckable(True)
                    act.blockSignals(True)
                    act.setChecked(not self.table.isColumnHidden(col))
                    act.blockSignals(False)
                    act.toggled.connect(lambda checked, c=col: self.table.setColumnHidden(c, not checked))
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


    def _blur_splitter_handles(self, split: QSplitter):
        """Добавляет мягкую размыtую тень вокруг ручек сплиттера."""
        try:
            for i in range(1, split.count()):
                h = split.handle(i)
                eff = QGraphicsDropShadowEffect(h)
                eff.setBlurRadius(22)          # 18–26 — степень «размытия»
                eff.setColor(QColor(0, 0, 0, 45))  # очень мягкий серый
                eff.setOffset(0, 0)            # светится равномерно
                h.setGraphicsEffect(eff)
        except Exception:
            pass





    def _enhance_splitter_handles(self, split: QSplitter):
        """Доп. размытие и скругление ручки сплиттера."""
        try:
            for i in range(1, split.count()):
                h = split.handle(i)
                eff = QGraphicsDropShadowEffect(h)
                eff.setBlurRadius(10)
                eff.setColor(QColor(0, 0, 0, 32))
                eff.setOffset(0, 0)
                h.setGraphicsEffect(eff)
                try:
                    h.setStyleSheet("QSplitterHandle{border-radius:8px;}")
                except Exception:
                    pass
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


    def _find_node_by_id_in_tree(self, nodes: list, fid):
        fid_key = normalize_id(fid)
        for n in nodes or []:
            if not isinstance(n, dict):
                continue
            if n.get("type") == "folder" and normalize_id(n.get("id")) == fid_key:
                return n
            child = self._find_node_by_id_in_tree(n.get("children") or [], fid)
            if child:
                return child
        return None

    def _ensure_subfolder(self, project_id: int | str, parent_folder_id: int | str, name: str) -> int | str | None:
        """Гарантирует наличие подпапки name под parent_folder_id - возвращает её id."""
        try:
            # 0) сбросить кэш перед любым чтением дерева
            try:
                self.api.cache.pop(f"tree:{project_id}", None)
            except Exception:
                pass

            # 1) попробовать найти без создания
            tree = self.api.list_folders(project_id) or []
            fid = self._child_folder_id_by_name(tree, parent_folder_id, name)
            if fid:
                return fid

            # 2) создать
            create_result = self.api.create_folder(project_id, parent_folder_id, name)
            if not create_result:
                return None

            # Если API вернул id, используем его напрямую
            if isinstance(create_result, (int, str)) and create_result not in (True, False, 0, ""):
                return normalize_id(create_result)

            # 3) ещё раз сбросить кэш и перечитать - теперь подпапка уже должна быть
            try:
                self.api.cache.pop(f"tree:{project_id}", None)
            except Exception:
                pass
            tree = self.api.list_folders(project_id) or []
            fid = self._child_folder_id_by_name(tree, parent_folder_id, name)
            return fid or parent_folder_id  # fallback, чтобы не падать
        except Exception:
            return None


    def _upload_dir_recursive(self, project_id: int | str, parent_folder_id: int | str, local_dir: Path):
        """Создаёт на сервере папку local_dir.name и рекурсивно загружает содержимое."""
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
                            # Log user action for notification filtering
                            self._log_user_action("upload", file_name=entry.name, folder_id=base_id)
                            self._upload_ok = getattr(self, "_upload_ok", 0) + 1
                        else:
                            self._upload_fail = getattr(self, "_upload_fail", 0) + 1
                    except Exception:
                        pass
        except Exception:
            pass

    def _collect_upload_tasks(self, paths: list[Path], display_prefix: tuple[str, ...] = ()) -> list[dict]:
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
                
                # Пробуем разные поля для родительской папки
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
        except Exception as e:
            pass
        
        if names:
            return names
        
        # Если в кеше нет файлов, пробуем получить их из API
        try:
            details = self.api.get_folder_details(folder_id)
            
            if isinstance(details, dict):
                # Пробуем разные ключи для получения файлов
                possible_keys = ["files", "children", "items", "documents", "content"]
                files = []
                for key in possible_keys:
                    if key in details:
                        potential_files = details[key]
                        if isinstance(potential_files, list):
                            files = potential_files
                            break
                
                for file_info in files:
                    if isinstance(file_info, dict):
                        file_type = file_info.get("type", "").lower()
                        
                        if file_type == "file":
                            name = file_info.get("originalName") or file_info.get("name")
                            if name:
                                names.add(name.casefold())
        except Exception as e:
            details = None
        
        return names

    def _ensure_remote_path_chain(self, project_id: int | str, folder_cache: dict[tuple[str, ...], int], parts: tuple[str, ...]) -> int | None:
        parent_id = folder_cache.get(tuple())
        if parent_id is None:
            return None
        current = tuple()
        for part in parts:
            current = current + (part,)
            if current in folder_cache:
                parent_id = folder_cache[current]
                continue
            new_id = self._ensure_subfolder(project_id, parent_id, part)
            if not new_id:
                return None
            folder_cache[current] = new_id
            parent_id = new_id
        return parent_id

    def _unique_remote_name(self, taken: set[str], name: str) -> str:
        base, ext = os.path.splitext(name)
        base = (base or name or "file").strip() or "file"
        candidate = f"{base} (copy){ext}"
        idx = 2
        while candidate.casefold() in taken:
            candidate = f"{base} (copy {idx}){ext}"
            idx += 1
        return candidate

    def _upload_list_to_folder(self, target_folder: dict, paths: list[Path], display_prefix: tuple[str, ...] = ()):
        """Загрузка списка путей в целевую папку (с подсчетом успешных/ошибок)."""
        
        pid = self.current_project_id()
        if not pid:
            return
        target_id = normalize_id(target_folder.get("id"))
        if not target_id:
            return

        tasks = self._collect_upload_tasks(paths, display_prefix)
        if not tasks:
            QMessageBox.information(self, "Загрузка", "Нет файлов для загрузки.")
            return

        # Проверяем конфликты имен файлов на сервере для всех папок
        existing_map: dict[tuple[str, ...], set[str]] = {tuple(): self._existing_names_for_folder(target_id)}
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
        self._upload_ok, self._upload_fail = 0, 0

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
        QTimer.singleShot(50, lambda: None)
        QApplication.processEvents()

        folder_cache: dict[tuple[str, ...], int] = {tuple(): target_id}
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
                parent_id = self._ensure_remote_path_chain(pid, folder_cache, folder_parts)
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
                                future_names_set = existing_map.setdefault(future_folder_parts, self._existing_names_for_folder(folder_cache.get(future_folder_parts, target_id)))
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
                ok = self.api.upload_file(parent_id, str(task["path"]), task["name"])
            except Exception as exc:
                ok = False
                error_detail = str(exc)

            if ok:
                ok_count += 1
                names_set.add(task["name"].casefold())
                dlg.set_status(task["key"], "ok", "Загружено.")
                
                # Log user action for notification filtering
                try:
                    # We don't have file_id yet (just uploaded), so log by name and folder
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
            self.soft_refresh_and_restore_view()
        except Exception:
            pass

        cancelled = cancelled or dlg.was_cancelled()
        if cancelled:
            self.status.showMessage("Загрузка отменена пользователем.", 5000)
            return

        if fail_count:
            dlg.finish(f"Загружено файлов: {ok_count} из {total}.")
            dlg.exec()
            self.status.showMessage(f"Загружено файлов: {ok_count} из {total}.", 6000)
        else:
            dlg.finish(f"Загружено файлов: {ok_count}.")
            dlg.exec()
            self.status.showMessage(f"Загружено файлов: {ok_count}.", 5000)
    def _handle_os_drop(self, paths: list[Path], target_folder: dict):
        pid = self.current_project_id()
        if not pid:
            QMessageBox.information(self, "Загрузка", "Не выполнен вход в систему.")
            return
        raw_fid = target_folder.get("id") or 0
        try:
            target_id = int(raw_fid)
        except (ValueError, TypeError):
            target_id = raw_fid
        # Check for invalid ID (both numeric and string)
        if (isinstance(target_id, (int, float)) and target_id <= 0) or (isinstance(target_id, str) and not target_id.strip()):
            QMessageBox.information(self, "Загрузка", "Не удалось определить целевую папку.")
            return

        normalized: list[Path] = []
        for p in paths or []:
            normalized.append(p if isinstance(p, Path) else Path(p))
        self._upload_list_to_folder(target_folder, normalized)

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
                if hasattr(self, "hdrcb") and self.hdrcb is not None:
                    self.hdrcb.raise_()
            except Exception:
                pass

        except Exception:
            pass



    def upload_file(self):
        parent = self.current_folder_node()
        if not parent or parent.get("type") != "folder":
            QMessageBox.information(self, "Загрузка", "Выберите целевую папку слева."); return
        paths, _ = QFileDialog.getOpenFileNames(self, "Выберите файл(ы)")
        if not paths: return
        ok_total = 0
        self.progress.setVisible(True); self.progress.setRange(0, 0); QApplication.processEvents()
        try:
            for p in paths:
                filename = os.path.basename(p)
                if self.api.upload_file(parent.get("id"), p, filename):
                    ok_total += 1
                    # Log user action to filter from notifications
                    try:
                        self._log_user_action("upload", file_name=filename, folder_id=parent.get("id"))
                    except Exception:
                        pass
                    try:
                        raw_fid = parent.get("id") or 0
                        try:
                            fid = int(raw_fid)
                        except (ValueError, TypeError):
                            fid = raw_fid
                        if fid and hasattr(self, 'sync2') and self.sync2.is_synced(fid):
                            if hasattr(self, '_trigger_sync_now'):
                                self._trigger_sync_now(fid)
                            else:
                                self.sync2.sync_now(fid)
                    except Exception:
                        pass
                else: QMessageBox.warning(self, "Загрузка", f"Не удалось загрузить: {filename}")
        finally:
            self.progress.setVisible(False)
        if ok_total:
            self.soft_refresh_and_restore_view()
            QMessageBox.information(self, "Загрузка", f"Загружено файлов: {ok_total}")

    def set_initial_view(self):
        """ Скрывает лишние колонки для начального вида. """
        self.tree.clear(); self.files_current = []; self.update_table()
        # Показываем все колонки по умолчанию
        for i in range(len(FilesTableModel.HEADERS)):
            self.table.setColumnHidden(i, False)
        try:
            format_idx = FilesTableModel.HEADERS.index("Формат")
            self.table.horizontalHeader().resizeSection(format_idx, 90)
        except (ValueError, IndexError): pass
    def _toggle_first_col_on_scroll(self, value: int):
        try:
            hdr = self.table.horizontalHeader()
            if value > 0:
                any_other = any(not self.table.isColumnHidden(c)
                                for c in range(1, self.files_model.columnCount()))
                if any_other:
                    self.table.setColumnHidden(0, True)
            else:
                if self.table.isColumnHidden(0):
                    self.table.setColumnHidden(0, False)
                    hdr.setSectionResizeMode(0, QHeaderView.Fixed)
                    hdr.resizeSection(0, CHECKBOX_COLUMN_WIDTH)
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
                QMessageBox.warning(self, 'Авторизация', 'Вход не выполнен. Приложение будет закрыто.')
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

        self.status.showMessage("Загружаю проекты")
        projects = self.api.list_projects()
        self.cb_projects.blockSignals(True); self.cb_projects.clear(); self.cb_projects.addItem("Выберите проект", userData=None)
        for p in projects:
            self.cb_projects.addItem(get_title(p), userData=p.get("id"))
        self.cb_projects.blockSignals(False)
        self.status.showMessage(f"Загружено проектов: {len(projects)}", 3000)

    def logout_and_relogin(self):
        self.api.logout()
        self.cb_projects.clear()
        self.btn_user.setVisible(False); self.btn_login.setVisible(True)
        self.status.showMessage("Вы вышли из аккаунта", 3000)
        self.set_initial_view()
        self.do_login()

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
    def populate_tree_widget(self):
        self.tree.clear(); self.folder_item_by_id.clear()
        pid = self.current_project_id()
        def add_items(parent, nodes, *, top_level: bool = False):
            for n in sorted(nodes, key=lambda x: get_title(x).lower()):
                if not isinstance(n, dict):
                    continue
                if n.get("type") == "folder":
                    item = QTreeWidgetItem(parent, [get_title(n)])
                    item.setData(0, Qt.UserRole, n)
                    item.setIcon(0, self.icon_provider.get_icon(n))
                    fid = n.get("id")
                    if fid is not None:
                        fid_key = normalize_id(fid)
                        if fid_key:
                            self.folder_item_by_id[fid_key] = item
                        
                        # NOTIFY_ROLE не устанавливается по умолчанию
                        # Иконка уведомлений появится только при обнаружении реальных изменений
                        # в папке (сравнение сохраненного file_state с текущим)

                    add_items(item, n.get("children") or [], top_level=False)
        add_items(self.tree.invisibleRootItem(), self.full_tree, top_level=True)
        
        # Restore notification icons for subscribed folders
        try:
            subs = getattr(self, "_subscriptions", {}) or {}
            for fid, cfg in subs.items():
                try:
                    it = self.folder_item_by_id.get(normalize_id(fid))
                    if it is not None:
                        # Set NOTIFY_ROLE: False = subscribed (no changes), True = has changes
                        # None = not subscribed (no icon)
                        has_pending = bool(cfg.get('pending'))
                        # Always show badge for subscribed folders: False if no changes, True if has changes
                        value = True if has_pending else False
                        it.setData(0, NOTIFY_ROLE, value)
                except Exception:
                    pass
            # Also restore from persisted notifications in QSettings
            if pid:
                try:
                    notifications = load_folder_notifications()
                    sub_keys = {normalize_id(k) for k in subs}
                    for notif in notifications:
                        if normalize_project_id(notif.get("project_id")) == normalize_project_id(pid):
                            nfid = notif.get("folder_id")
                            # Always set NOTIFY_ROLE for all subscribed folders from persistence
                            if nfid:
                                key = normalize_id(nfid)
                                it = self.folder_item_by_id.get(key)
                                if it is not None:
                                    if key not in sub_keys:
                                        it.setData(0, NOTIFY_ROLE, False)
                except Exception:
                    pass
            
            # Restore pending notifications badges (red bell for unread changes)
            try:
                for folder_id in self._pending_notifications.keys():
                    key = normalize_id(folder_id)
                    it = self.folder_item_by_id.get(key)
                    if it is not None:
                        it.setData(0, NOTIFY_ROLE, True)  # True = has unread changes
                        print(f"[POPULATE_TREE] Restored pending notification badge for folder_id={folder_id}")
            except Exception as e:
                print(f"[POPULATE_TREE] Error restoring pending badges: {e}")
            
             # Restore SYNC_ROLE for synced folders
            try:
                print(f"[POPULATE_TREE] Restoring SYNC_ROLE...")
                print(f"[POPULATE_TREE]   hasattr(self, 'sync2'): {hasattr(self, 'sync2')}")
                if hasattr(self, 'sync2'):
                    print(f"[POPULATE_TREE]   self.sync2: {self.sync2}")
                    print(f"[POPULATE_TREE]   self.sync2.map: {self.sync2.map}")
                if hasattr(self, 'sync2') and self.sync2 and hasattr(self.sync2, 'map'):
                    print(f"[POPULATE_TREE]   Starting to restore {len(self.sync2.map)} folders...")
                    restored_count = 0
                    for fid_str, cfg in self.sync2.map.items():
                        key = normalize_id(fid_str)
                        it = self.folder_item_by_id.get(key)
                        print(f"[POPULATE_TREE]   fid_str={fid_str!r} key={key!r} it_found={it is not None}")
                        if it is not None:
                            it.setData(0, SYNC_ROLE, True)
                            restored_count += 1
                            print(f"[POPULATE_TREE]   ✓ Restored SYNC_ROLE for folder_id={fid_str}")
                        else:
                            print(f"[POPULATE_TREE]   ✗ Item not found for folder_id={fid_str}")
                    print(f"[POPULATE_TREE]   Total restored: {restored_count}")
                else:
                    print(f"[POPULATE_TREE]   sync2 not available yet")
            except Exception as e:
                print(f"[POPULATE_TREE] Error restoring SYNC_ROLE: {e}")
                import traceback
                traceback.print_exc()
             
            self.tree.viewport().update()
        except Exception:
            pass
        
        self.tree.expandToDepth(0)
        self.go_to_project_root()

    def load_tree_for_project(self, project_id: int | str):
        self.status.showMessage("Загрузка структуры проекта")
        self.progress.setVisible(True); self.progress.setRange(0, 0); QApplication.processEvents()
        tree = self.api.list_folders(project_id)
        if tree is None:
            self.progress.setVisible(False)
            QMessageBox.warning(self, "Структура", "Не удалось загрузить структуру проекта."); return
        self.full_tree = tree
        # Убрали полное обогащение данных при загрузке проекта - быстрый старт
        self.progress.setVisible(False)
        self.current_path_nodes = []
        
        # Load persisted subscriptions for this project into memory
        try:
            notifications = load_folder_notifications()
            for notif in notifications:
                if normalize_project_id(notif.get("project_id")) == normalize_project_id(project_id):
                    fid = notif.get("folder_id")
                    if fid:
                        try:
                            fid_str = normalize_id(fid)
                            # Only add if not already in memory
                            if fid_str not in self._subscriptions:
                                # Get baseline state from cloud
                                try:
                                    state = self._cloud_state_for_folder(project_id, fid_str)
                                except Exception:
                                    state = {}
                                self._subscriptions[fid_str] = {
                                    'project_id': project_id,
                                    'state': state,
                                    'pending': False,
                                    'title': notif.get('folder_path', ''),
                                }
                        except Exception:
                            pass
        except Exception:
            pass
        
        self.populate_tree_widget()
        
        # Restore SYNC_ROLE for synced folders after loading project tree
        def restore_sync_badges():
            try:
                if hasattr(self, 'sync2') and self.sync2 and hasattr(self.sync2, 'map'):
                    for fid_str, cfg in self.sync2.map.items():
                        key = normalize_id(fid_str)
                        it = self.folder_item_by_id.get(key)
                        if it is not None:
                            it.setData(0, SYNC_ROLE, True)
                    self.tree.viewport().update()
            except Exception as e:
                print(f"[SYNC] Error restoring sync badges: {e}")
        
        # Immediate restoration
        restore_sync_badges()
        
        # Deferred restoration (to handle cases where tree is not fully populated)
        QtCore.QTimer.singleShot(100, restore_sync_badges)
        QtCore.QTimer.singleShot(500, restore_sync_badges)
        
        self.status.showMessage("Структура загружена", 3000)

    def enrich_all_tree(self, nodes: list):  # не вызывается при загрузке проекта (убрали долгую загрузку)
        # Показать индикатор занятости в статус-баре
        self.status.showMessage("Получение метаданных")
        self.progress.setVisible(True); self.progress.setRange(0, 0)
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
        self.progress.setVisible(False)
        self.status.clearMessage()

    def refresh_tree(self):
        pid = self.current_project_id()
        if not pid:
            QMessageBox.information(self, "Проект", "Сначала выберите проект."); return
        self.soft_refresh_and_restore_view()

    def soft_refresh_and_restore_view(self):
        pid = self.current_project_id()
        if not pid: return
        current_node_id = (self.current_folder_node() or {}).get("id")
        key = f"tree:{pid}"; self.api.cache.pop(key, None)
        tree = self.api.list_folders(pid)
        if tree is None: return
        self.full_tree = tree
        
        # Убрали полное обогащение данных при обновлении дерева - быстрый рефреш
        self.populate_tree_widget()
        
        # Restore SYNC_ROLE for synced folders after tree refresh
        def restore_sync_badges():
            try:
                if hasattr(self, 'sync2') and self.sync2 and hasattr(self.sync2, 'map'):
                    for fid_str, cfg in self.sync2.map.items():
                        key = normalize_id(fid_str)
                        it = self.folder_item_by_id.get(key)
                        if it is not None:
                            it.setData(0, SYNC_ROLE, True)
                    self.tree.viewport().update()
            except Exception as e:
                print(f"[SYNC] Error restoring sync badges: {e}")
        
        restore_sync_badges()
        
        # Проверить уведомления ПОСЛЕ обновления дерева, чтобы использовать свежие данные
        try:
            self._check_notifications()
        except Exception:
            pass
        if current_node_id and current_node_id in self.folder_item_by_id:
            item_to_select = self.folder_item_by_id[current_node_id]
            self.tree.setCurrentItem(item_to_select)
            self.open_folder_node(item_to_select.data(0, Qt.UserRole))
        else:
            self.go_to_project_root()

    def on_tree_click(self, item: QTreeWidgetItem, _col: int):
        node = item.data(0, Qt.UserRole) or {}
        self.open_folder_node(node)

    def tree_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item:
            return
        node = item.data(0, Qt.UserRole)
        if not node or node.get("type") != "folder":
            return

        menu = QMenu(self)
        menu.setObjectName("treeMenu")
        act_zip    = menu.addAction("Скачать как ZIP")
        act_folder = menu.addAction("Скачать структуру")
        
        # Добавляем пункт для управления уведомлениями
        menu.addSeparator()
        pid = self.current_project_id()
        fid = node.get("id")
        if pid and fid:
            is_subscribed = is_folder_notification_enabled(pid, fid)
            notify_text = "🔕 Отключить уведомления" if is_subscribed else "🔔 Включить уведомления"
            act_notify = menu.addAction(notify_text)
        else:
            act_notify = None

        chosen = self._menu_exec(menu, self.tree.mapToGlobal(pos))
        if chosen == act_zip:
            self.download_folder_as_zip(node)
        elif chosen == act_folder:
            self.download_folder_plain(node)
        elif act_notify and chosen == act_notify:
            self.toggle_folder_notifications(node)

    def toggle_folder_notifications(self, node: dict):
        """Toggle notifications for a folder"""
        pid = self.current_project_id()
        fid = node.get("id")
        if not pid or not fid:
            return
        
        folder_path = get_title(node)
        is_subscribed = is_folder_notification_enabled(pid, fid)
        
        if is_subscribed:
            # Отключить уведомления - удалить из persistent storage и из памяти
            remove_folder_notification(pid, fid)
            try:
                fid_str = normalize_id(fid)
                if fid_str in self._subscriptions:
                    del self._subscriptions[fid_str]
            except Exception:
                pass
            QMessageBox.information(
                self,
                "Уведомления",
                f"Уведомления для папки \"{folder_path}\" отключены."
            )
        else:
            # Включить уведомления - сохранить текущее состояние файлов
            try:
                # Получить текущее состояние файлов через API (не полагаться на ключ children в дереве)
                files = self._build_notification_file_state(pid, fid, folder_path, force_fresh=True)

                # Сохранить состояние в persistent storage
                print(f"[SUBSCRIBE] Saving {len(files)} files to DB for folder: {folder_path}")
                if len(files) > 0:
                    print(f"[SUBSCRIBE] First 3 files: {[(f.get('name'), f.get('id'), f.get('updatedAt')) for f in files[:3]]}")
                save_folder_notification(pid, fid, folder_path, files)

                # Также добавить в память (_subscriptions) для polling
                try:
                    fid_str = normalize_id(fid)
                    # Получить базовое состояние из облака
                    try:
                        state = self._cloud_state_for_folder(pid, fid_str)
                    except Exception:
                        state = {}
                    self._subscriptions[fid_str] = {
                        'project_id': pid,
                        'state': state,
                        'pending': False,
                        'title': folder_path,
                    }
                except Exception:
                    pass
                
                QMessageBox.information(
                    self,
                    "Уведомления",
                    f"Уведомления для папки \"{folder_path}\" включены.\n"
                    f"Вы будете получать уведомления об изменениях файлов."
                )
            except Exception as e:
                QMessageBox.warning(self, "Ошибка", f"Не удалось включить уведомления: {e}")
        
        # Обновить дерево чтобы показать/скрыть иконку
        # Установить NOTIFY_ROLE для визуализации значка
        try:
            it = self.folder_item_by_id.get(normalize_id(fid))
            if it is not None:
                print(f"[TOGGLE_NOTIFY] Folder: {get_title(node)}, is_subscribed: {is_subscribed}, item exists: {it is not None}")
                if is_subscribed:
                    # Был подписан, теперь отписались - убрать значок
                    it.setData(0, NOTIFY_ROLE, None)
                    print(f"[TOGGLE_NOTIFY] Set NOTIFY_ROLE=None (unsubscribe)")
                else:
                    # Только что подписались - показать значок (без изменений пока)
                    it.setData(0, NOTIFY_ROLE, False)
                    print(f"[TOGGLE_NOTIFY] Set NOTIFY_ROLE=False (subscribe)")
                self.tree.viewport().update()
                print(f"[TOGGLE_NOTIFY] Tree viewport updated")
        except Exception as e:
            print(f"[TOGGLE_NOTIFY] Error: {e}")
        
        # Обновить notify button/menu
        try:
            self._update_notify_icon()
            self._build_notify_menu()
        except Exception:
            pass
 
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
        """Periodic check for file changes in subscribed folders"""
        print(f"[CHECK_NOTIF START] ======================================================")
        print(f"[CHECK_NOTIF START] Starting notification check...")
        try:
            # During app startup (or after logout) API may be unavailable; avoid false
            # "everything deleted" notifications when cloud scan returns empty.
            try:
                if not getattr(self.api, "token", None):
                    print(f"[CHECK_NOTIF START] No API token, skipping")
                    return
            except Exception:
                print(f"[CHECK_NOTIF START] Exception checking token, skipping")
                return

            subscriptions = load_folder_notifications()
            print(f"[CHECK_NOTIF START] Loaded {len(subscriptions)} subscriptions")
            if not subscriptions:
                print(f"[CHECK_NOTIF START] No subscriptions found")
                self._update_global_notification_badge()
                return
            
            print(f"[NOTIFICATIONS] Checking {len(subscriptions)} subscriptions...")
            
            for sub in subscriptions:
                project_id = sub["project_id"]
                folder_id = sub["folder_id"]
                folder_path = sub["folder_path"]
                saved_state = sub["file_state"]

                # Migrate legacy/buggy baselines where ids were missing/0 and thus
                # broke change detection.
                try:
                    fixed = False
                    if isinstance(saved_state, list):
                        for f in saved_state:
                            if not isinstance(f, dict):
                                continue
                            fid = f.get("id")
                            if fid in (None, "", 0, "0", False):
                                name = str(f.get("name") or "").strip()
                                p = str(f.get("path") or "").replace("\\", "/").strip("/")
                                new_id = f"{p}/{name}" if (p and name) else (name or p)
                                if new_id:
                                    f["id"] = new_id
                                    fixed = True
                    if fixed:
                        try:
                            save_folder_notification(project_id, folder_id, folder_path, saved_state)
                        except Exception:
                            pass
                except Exception:
                    pass
                
                print(f"[NOTIFICATIONS] Checking folder_id={folder_id}, path={folder_path}")
                print(f"[NOTIFICATIONS] Saved state has {len(saved_state)} items")
                if len(saved_state) > 0:
                    print(f"[NOTIFICATIONS] Saved state first 3 files: {[(f.get('name'), f.get('id'), f.get('path')) for f in saved_state[:3]]}")
                
                current_files = self._build_notification_file_state(project_id, folder_id, folder_path, force_fresh=True)

                print(f"[NOTIFICATIONS] Current state has {len(current_files)} items")
                if len(current_files) > 0:
                    print(f"[NOTIFICATIONS] Current state first 3 files: {[(f.get('name'), f.get('id'), f.get('path')) for f in current_files[:3]]}")

                # Guard against transient empty scans (startup/network/API hiccup).
                # Require 2 consecutive empty scans before treating it as a real
                # "all deleted" situation.
                try:
                    if not hasattr(self, "_notify_empty_hits") or getattr(self, "_notify_empty_hits") is None:
                        self._notify_empty_hits = {}
                    hits = getattr(self, "_notify_empty_hits", {})
                    hit_key = f"{normalize_project_id(project_id)}:{normalize_id(folder_id)}"

                    if isinstance(saved_state, list) and len(saved_state) > 0 and (not isinstance(current_files, list) or len(current_files) == 0):
                        prev_hits = int(hits.get(hit_key, 0) or 0)
                        new_hits = prev_hits + 1
                        hits[hit_key] = new_hits
                        self._notify_empty_hits = hits
                        try:
                            sync_log("NOTIFY empty scan folder={} hits={} saved={}", hit_key, new_hits, len(saved_state))
                        except Exception:
                            pass
                        if new_hits < 2:
                            continue
                    else:
                        # Reset counter on any successful/non-empty scan
                        try:
                            if hit_key in hits:
                                hits.pop(hit_key, None)
                                self._notify_empty_hits = hits
                        except Exception:
                            pass
                except Exception:
                    pass

                # Heal legacy/empty baselines: if we previously couldn't fetch folder contents,
                # the saved baseline may be empty. Initialize it once from the first successful
                # cloud scan so deletions can be detected on subsequent checks.
                try:
                    if (not isinstance(saved_state, list) or len(saved_state) == 0) and isinstance(current_files, list) and len(current_files) > 0:
                        print(f"[NOTIFICATIONS] Baseline was empty; initializing from current state ({len(current_files)} items)")
                        try:
                            save_folder_notification(project_id, folder_id, folder_path, current_files)
                        except Exception:
                            pass
                        # Use the freshly initialized baseline for this run (no notification).
                        continue
                except Exception:
                    pass

                # Cleanup expired user actions before filtering
                self._cleanup_expired_user_actions()
                
                # Show all changes (including user actions). Filtering here caused missed notifications.
                print(f"[NOTIFICATIONS] Filtering mode: ALL CHANGES")
                print(f"[NOTIFICATIONS] Saved state (old): {len(saved_state)} items")
                if len(saved_state) > 0:
                    print(f"[NOTIFICATIONS] Saved state first 3: {[(f.get('name'), f.get('id'), f.get('updatedAt')) for f in saved_state[:3]]}")
                print(f"[NOTIFICATIONS] Current state (new): {len(current_files)} items")
                if len(current_files) > 0:
                    print(f"[NOTIFICATIONS] Current state first 3: {[(f.get('name'), f.get('id'), f.get('updatedAt')) for f in current_files[:3]]}")
                changes = compare_file_states(saved_state, current_files, filter_func=None)

                # Persist lightweight diagnostics for troubleshooting
                try:
                    sync_log("NOTIFY check project={} folder={} saved={} current={} changes={}",
                             normalize_project_id(project_id), normalize_id(folder_id),
                             len(saved_state) if isinstance(saved_state, list) else -1,
                             len(current_files) if isinstance(current_files, list) else -1,
                             len(changes) if isinstance(changes, list) else -1)
                    if changes:
                        for ch in changes[:5]:
                            try:
                                sync_log("NOTIFY change type={} name={} id={}",
                                         ch.get("type"),
                                         (ch.get("file") or {}).get("name"),
                                         (ch.get("file") or {}).get("id"))
                            except Exception:
                                pass
                except Exception:
                    pass
                
                print(f"[NOTIFICATIONS] Found {len(changes)} changes (after filtering)")
                if changes:
                    for change in changes[:5]:  # Show first 5
                        print(f"[NOTIFICATIONS]   - {change['type']}: {change['file'].get('name')}")
                
                if changes:
                    # Store changes in pending notifications (don't show QMessageBox immediately)
                    existing_notif = self._pending_notifications.get(folder_id)
                    if existing_notif:
                        print(f"[NOTIFICATIONS] Updating existing notification with {len(changes)} new changes")
                    else:
                        print(f"[NOTIFICATIONS] Creating new notification with {len(changes)} changes")

                    # Toast only on new/changed payload to avoid spamming every poll
                    try:
                        sig_parts = []
                        for ch in (changes or [])[:20]:
                            try:
                                ctype = str((ch or {}).get("type") or "")
                                f = (ch or {}).get("file") or {}
                                fid = normalize_id(f.get("id"))
                                fname = str(f.get("name") or "")
                                sig_parts.append(f"{ctype}:{fid}:{fname}")
                            except Exception:
                                continue
                        new_sig = "|".join(sig_parts)
                    except Exception:
                        new_sig = ""
                    try:
                        prev_sig = str((existing_notif or {}).get("_sig") or "")
                    except Exception:
                        prev_sig = ""
                    should_toast = (not existing_notif) or (new_sig and new_sig != prev_sig)
                    
                    self._pending_notifications[folder_id] = {
                        "project_id": project_id,
                        "folder_path": folder_path,
                        "changes": changes,
                        "current_files": current_files,
                        "_sig": new_sig,
                    }
                    
                    # Save to persistent storage
                    save_pending_notifications(self._pending_notifications)
                    
                    print(f"[NOTIFICATIONS] Stored in pending notifications, total pending: {len(self._pending_notifications)}")
                    
                    # Update global notification badge FIRST
                    self._update_global_notification_badge()
                    # Also refresh the top-bar notify button and its menu
                    try:
                        self._update_notify_icon()
                        self._build_notify_menu()
                    except Exception:
                        pass

                    # OS-level toast notification (if available)
                    if should_toast:
                        try:
                            self._toast_changes(folder_path, changes)
                        except Exception:
                            pass
                    
                    # Update tree badge to show notification icon
                    try:
                        it = self.folder_item_by_id.get(normalize_id(folder_id))
                        if it is not None:
                            it.setData(0, NOTIFY_ROLE, True)  # True = has changes (red bell)
                            self.tree.viewport().update()
                            print(f"[NOTIFICATIONS] Set NOTIFY_ROLE=True on tree item")
                        else:
                            print(f"[NOTIFICATIONS] WARNING: tree item not found for folder_id={folder_id}")
                    except Exception as e:
                        print(f"[NOTIFICATIONS] Error updating tree badge: {e}")
                else:
                    # No changes - remove from pending if exists
                    self._pending_notifications.pop(folder_id, None)
                    
                    # Save to persistent storage
                    save_pending_notifications(self._pending_notifications)
                    
                    # Update global badge
                    self._update_global_notification_badge()
                    # Also refresh top-bar notify button and menu
                    try:
                        self._update_notify_icon()
                        self._build_notify_menu()
                    except Exception:
                        pass
                    
                    # Update tree badge to show subscribed but no changes
                    try:
                        it = self.folder_item_by_id.get(normalize_id(folder_id))
                        if it is not None:
                            it.setData(0, NOTIFY_ROLE, False)  # False = subscribed, no changes
                            self.tree.viewport().update()
                    except Exception:
                        pass
            
            # Update global notification badge
            self._update_global_notification_badge()
            print(f"[NOTIFICATIONS] Global badge updated, visible: {self.global_notify_btn.isVisible()}")
        
        except Exception as e:
            # Silent fail for background checks
            print(f"[NOTIFICATIONS] EXCEPTION: {e}")
            import traceback
            traceback.print_exc()

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
            search_box.setPlaceholderText("Поиск по имени...")
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
            table.setHorizontalHeaderLabels(["Операция", "Тип", "Имя"])
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
                    op_item.setText("Новый")
                elif op_type == "modified":
                    op_item.setIcon(themed_icon(EDIT_ICON_PATH))
                    if change.get("version_update"):
                        op_item.setText("Обновлена версия")
                    else:
                        op_item.setText("Изменён")
                elif op_type == "renamed":
                    op_item.setIcon(themed_icon(EDIT_ICON_PATH))
                    op_item.setText("Переименован")
                elif op_type == "deleted":
                    op_item.setIcon(themed_icon(DELETE_ICON_PATH))
                    op_item.setText("Удалён")
                op_item.setFlags(op_item.flags() & ~Qt.ItemIsEditable)
                
                # Column 1: Type with icon
                type_item = QTableWidgetItem()
                item_type = file_data.get("type", "file")
                if item_type == "folder":
                    type_item.setIcon(themed_icon(CUSTOM_FOLDER_ICON_PATH))
                    type_item.setText("Папка")
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
                    type_item.setText("Файл")
                type_item.setFlags(type_item.flags() & ~Qt.ItemIsEditable)
                
                # Column 2: Name (with old name for renamed files)
                name_item = QTableWidgetItem()
                file_name = file_data.get("name", "Неизвестно")
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
            QMessageBox.warning(self, "Ошибка", f"Не удалось показать изменения: {e}")

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
                QMessageBox.warning(self, "Навигация", f"Не удалось найти папку с файлом {file_name}")
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
                QMessageBox.information(self, "Навигация", 
                    f"Открыта папка с файлом, но файл '{file_name}' не найден.\n"
                    f"Возможно, файл был удалён или перемещён.")
        
        except Exception as e:
            print(f"[NAVIGATE] Error: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.warning(self, "Ошибка навигации", f"Не удалось перейти к файлу: {e}")


    def go_to_project_root(self):
        if not self.current_project_id():
            if self.cb_projects.count() > 0:
                self.files_current = []
                self.update_table()
            else:
                QMessageBox.information(self, "Корень проекта", "Сначала выберите проект.");
            return
        self.current_path_nodes = []
        self.tree.clearSelection()
        self.update_path_label()
        self.files_current = self.collect_direct_level({"children": self.full_tree})
        self.update_table()
        try:
            if hasattr(self, "btn_back"):
                self._nav_back = []
                self.btn_back.setEnabled(False)
        except Exception:
            pass

    def go_back(self):
        try:
            stack = getattr(self, "_nav_back", [])
            if not stack:
                return
            prev = stack.pop()
            # Prevent recording when navigating back
            self._nav_suppress_record = True
            try:
                self.open_folder_node(prev)
            finally:
                self._nav_suppress_record = False
            try:
                if hasattr(self, "btn_back"):
                    self.btn_back.setEnabled(bool(stack))
            except Exception:
                pass
        except Exception:
            pass

    def open_folder_node(self, node: dict):
        if not node: return
        # Record navigation history unless suppressed or same folder
        try:
            if not getattr(self, "_nav_suppress_record", False):
                prev = self.current_folder_node() if hasattr(self, "current_folder_node") else None
                if isinstance(prev, dict) and prev.get("id") and prev.get("id") != node.get("id"):
                    if not hasattr(self, "_nav_back"):
                        self._nav_back = []
                    self._nav_back.append(prev)
                    try:
                        if hasattr(self, "btn_back"):
                            self.btn_back.setEnabled(True)
                    except Exception:
                        pass
        except Exception:
            pass
        self.current_path_nodes = []
        it = self.folder_item_by_id.get(normalize_id(node.get("id")))
        while it is not None:
            data = it.data(0, Qt.UserRole)
            if data: self.current_path_nodes.insert(0, data)
            it = it.parent()
        if not self.current_path_nodes: self.current_path_nodes = [node]
        self.update_path_label()
        self.files_current = self.collect_direct_level(node)
        self.update_table()
        try:
            if hasattr(self, "btn_back"):
                self.btn_back.setEnabled(bool(getattr(self, "_nav_back", [])))
        except Exception:
            pass
        # Freeze current visible order so it stays the same after metadata loads
        try:
            self._capture_visible_order()
            self._freeze_visible_order = True
        except Exception:
            pass
        self.lazy_enrich_current_files()

    def collect_direct_level(self, node: dict):
        return [c for c in (node.get("children") or []) if isinstance(c, dict) and c.get("type") in ("folder","file")]

    def collect_all_files_recursive(self, node: dict):
        out = []
        def walk(n):
            for c in (n.get("children") or []):
                if not isinstance(c, dict): continue
                if c.get("type") == "file": out.append(c)
                elif c.get("type") == "folder": walk(c)
        walk(node); return out

    def lazy_enrich_current_files(self, limit_per_folder: int = 200):
        """Догружает метаданные только для выбранной папки: и для файлов, и для вложенных папок."""
        # Собираем цели: текущий уровень файлов и папок (без рекурсии)
        items = [f for f in self.files_current if isinstance(f, dict) and f.get("type") in ("file","folder")]
        if not items:
            return
        self.status.showMessage("Получение метаданных")
        self.progress.setVisible(True); self.progress.setRange(0, 0)
        QApplication.processEvents()
        changed = False
        done = 0
        for it in items:
            if done >= max(1, limit_per_folder):
                break
            tid = it.get("id")
            if not tid:
                continue
            # пропускаем если базовые поля уже есть
            has_created = it.get("createdBy") and (it.get("createTime") or it.get("createdAt"))
            has_modified = (it.get("modifTime") or it.get("updatedAt") or it.get("modifiedDate")) is not None
            if has_created and has_modified and it.get("modifiedBy") or it.get("author"):
                continue
            if it.get("type") == "file":
                details = self.api.get_document_details(tid)
            else:
                details = self.api.get_folder_details(tid)
            if not details:
                continue
            for k in ("createdBy","createTime","createdAt","modifTime","updatedAt","modifiedDate","modifiedBy","author","commentsCount"):
                if k in details and details.get(k) not in (None, ""):
                    it[k] = details.get(k)
                    changed = True
            done += 1
            if (done % 5) == 0:
                QApplication.processEvents()
        if changed:
            # Rebuild the table but keep the current visible order unless user armed sorting
            self.update_table()
            try:
                if getattr(self, "_sorting_armed", False) and self.table.isSortingEnabled():
                    hdr = self.table.horizontalHeader()
                    self.table.sortByColumn(hdr.sortIndicatorSection(), hdr.sortIndicatorOrder())
            except Exception:
                pass
        self.progress.setVisible(False)
        self.status.clearMessage()


    def on_flat_toggled(self, _checked: bool):
        node = self.current_path_nodes[-1] if self.current_path_nodes else None
        if node: self.open_folder_node(node)
    def _bind_table_selection_signals(self):
        # 1) selectionModel (зависит от текущей модели/прокси)
        sm = self.table.selectionModel()

        if not hasattr(self, "_bound_sel_model"):
            self._bound_sel_model = None
        if sm is not None and sm is not self._bound_sel_model:
            # отцепить от предыдущего selectionModel, если был
            if self._bound_sel_model is not None:
                try:
                    self._bound_sel_model.selectionChanged.disconnect(self._on_selection_changed)
                except Exception:
                    pass
            # прицепить к новому
            try:
                sm.selectionChanged.connect(self._on_selection_changed, Qt.UniqueConnection)
            except TypeError:
                sm.selectionChanged.connect(self._on_selection_changed)
            self._bound_sel_model = sm

        # 2) dataChanged текущей files_model (вы её часто пересоздаёте)
        fm = getattr(self, "files_model", None)
        if not hasattr(self, "_bound_files_model"):
            self._bound_files_model = None
        if fm is not None and fm is not self._bound_files_model:
            if self._bound_files_model is not None:
                try:
                    self._bound_files_model.dataChanged.disconnect(self._on_model_data_changed)
                except Exception:
                    pass
            try:
                fm.dataChanged.connect(self._on_model_data_changed, Qt.UniqueConnection)
            except TypeError:
                fm.dataChanged.connect(self._on_model_data_changed)
            try:
                fm.layoutChanged.connect(self._recalc_columns, Qt.UniqueConnection)
                fm.modelReset.connect(self._recalc_columns, Qt.UniqueConnection)
                fm.rowsInserted.connect(self._recalc_columns, Qt.UniqueConnection)
            except Exception:
                try:
                    fm.layoutChanged.connect(self._recalc_columns)
                    fm.modelReset.connect(self._recalc_columns)
                    fm.rowsInserted.connect(self._recalc_columns)
                except Exception:
                    pass
            self._bound_files_model = fm


    def _on_table_cell_clicked(self, index):
        """Обработчик клика по ячейке таблицы для переключения чекбоксов"""
        # Работаем только с первой колонке
        if index.column() != 0:
            return
        
        # Получаем прямоугольник ячейки и координаты клика
        rect = self.table.visualRect(index)
        cursor_pos = self.table.viewport().mapFromGlobal(QCursor.pos())
        
        # Вычисляем область чекбокса (используем ТУ ЖЕ логику что и в CheckBoxDelegate.paint)
        size = 18  # CheckBoxDelegate.BOX
        actual_width = min(rect.width(), CHECKBOX_COLUMN_WIDTH)
        x = rect.x() + (actual_width - size) // 2
        y = rect.y() + (rect.height() - size) // 2
        checkbox_rect = QRect(x, y, size, size)
        
        # Проверяем попадание в чекбокс
        if not checkbox_rect.contains(cursor_pos):
            return
        
        print(f"[_on_table_cell_clicked] Row {index.row()}: Checkbox clicked")
        
        # Получаем исходную модель и ключи для изменения
        view_model = index.model()
        model = view_model
        source_index = index
        map_to_source = None
        map_from_source = None
        if hasattr(view_model, 'mapToSource') and hasattr(view_model, 'sourceModel'):
            map_to_source = view_model.mapToSource
            map_from_source = view_model.mapFromSource
            source_index = map_to_source(index)
            model = view_model.sourceModel()
        
        # Получаем текущее состояние и переключаем
        state = model.data(source_index, Qt.CheckStateRole)
        new_state = Qt.Unchecked if state == Qt.Checked else Qt.Checked
        should_check = (new_state == Qt.Checked)
        
        print(f"[_on_table_cell_clicked] Toggling: {'check' if should_check else 'uncheck'}")
        
        # Получаем все выбранные строки ИЗ ПЕРВОЙ КОЛОНКИ
        sm = self.table.selectionModel()
        selected_source_rows = set()
        if sm is not None:
            selected_indexes = sm.selectedIndexes()
            for idx in selected_indexes:
                if idx.column() == 0:  # Только первая колонка
                    row = idx.row()
                    selected_source_rows.add(row)
        
        print(f"[_on_table_cell_clicked] Selected rows: {sorted(selected_source_rows)}")
        
        # Применяем новое состояние напрямую к множеству checked
        for row in selected_source_rows:
            if 0 <= row < model.rowCount():
                item = model._data[row]
                key = model._cb_key(item)
                if should_check:
                    model.checked.add(key)
                else:
                    model.checked.discard(key)
        
        # Излучаем сигнал dataChanged для всех изменённых строк
        if selected_source_rows:
            top_row = min(selected_source_rows)
            bottom_row = max(selected_source_rows)
            top_idx = model.index(top_row, 0)
            bottom_idx = model.index(bottom_row, 0)
            model.dataChanged.emit(top_idx, bottom_idx, [Qt.CheckStateRole])
            print(f"[_on_table_cell_clicked] Emitted dataChanged for rows {top_row}-{bottom_row}")
            
            # Обновляем заголовочный чекбокс
            self.update_header_checkbox()
            # Обновляем доступность кнопок
            self._update_actions_enabled()



    def update_path_label(self):
        path = " / ".join(get_title(n) for n in self.current_path_nodes)
        pass  # нижний текст пути убран по требованию

    # Таблица/фильтры/сортировка
    def update_table(self):
        self.files_model = FilesTableModel(self.files_current, self.icon_provider, self.checked)

        self._bind_table_selection_signals()
        self._update_actions_enabled()
        self.proxy.setSourceModel(self.files_model)
        self.apply_table_filters()
        if self.current_project_id(): self.auto_hide_empty_columns()
        self._tune_columns()
        
        # ВАЖНО: гарантируем что первый столбец остается фиксированным после всех операций
        try:
            hdr = self.table.horizontalHeader()
            if hdr and hdr.count() > 0:
                hdr.setSectionResizeMode(0, QHeaderView.Fixed)
                hdr.resizeSection(0, CHECKBOX_COLUMN_WIDTH)
        except Exception:
            pass

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
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return

        # выделим строку под курсором
        try:
            self.table.selectRow(idx.row())
        except Exception:
            pass

        # попытка понять - папка это или файл
        node = None
        try:
            node = self._node_from_index(idx)
        except Exception:
            pass

        is_folder = _is_folder(node) if isinstance(node, dict) else False
        if not is_folder:
            # запасной способ - по колонке "Тип"
            model = self.table.model()
            type_col = getattr(self, "_col_type", None)
            if type_col is None:
                try:
                    for i in range(model.columnCount()):
                        hd = (model.headerData(i, Qt.Horizontal, Qt.DisplayRole) or "").strip().lower()
                        if hd in ("тип", "type"):
                            self._col_type = i
                            break
                except Exception:
                    self._col_type = None
                type_col = getattr(self, "_col_type", None)
            if type_col is not None:
                try:
                    tval = (model.index(idx.row(), type_col).data() or "")
                    is_folder = "папк" in tval.lower() or "folder" in tval.lower()
                except Exception:
                    pass

        # меню в вашей стилистике
        menu = QMenu(self)
        menu.setObjectName("popupMenu")
        act_copy_link = None
        has_copy_targets = False

        act_open = menu.addAction("Открыть")
        act_ren  = menu.addAction("Переименовать")
        act_del  = menu.addAction("Удалить")
        menu.addSeparator()

        # подменю "Скачать" - такой же стиль
        m_download = QMenu("Скачать", self)
        m_download.setObjectName("popupMenu")
        menu.addMenu(m_download)

        if is_folder:
            act_d_zip   = m_download.addAction("Скачать как ZIP")
            act_d_plain = m_download.addAction("Скачать структуру")
        else:
            act_d_file  = m_download.addAction("Скачать как файл")
            act_d_zip   = m_download.addAction("Скачать как ZIP")

        try:
            has_copy_targets = bool(self._context_file_items(node))
        except Exception:
            has_copy_targets = False
        if has_copy_targets:
            act_copy_link = menu.addAction("Копировать ссылку")
        # Только для файлов - пункт «Открыть версии...»
        if not is_folder:
            act_versions = menu.addAction("Открыть версии...")


        menu.addSeparator()
        act_props = menu.addAction("Свойства")

        # показать меню
        gpos = self.table.viewport().mapToGlobal(pos)
        try:
            chosen = self._menu_exec(menu, gpos)
        except Exception:
            chosen = menu.exec_(gpos)
        if not chosen:
            return

        # обработка
        # открыть диалог версий
        if 'act_versions' in locals() and chosen is act_versions:
            try:
                self._show_versions_for_node(node)
            except Exception:
                pass
            return

        if chosen is act_open:
            # открываем так же, как двойным кликом, но безопасно - не из колонки 0
            m = self.table.model()
            cur = self.table.currentIndex()
            row = cur.row() if cur.isValid() else idx.row()
            col = 1 if m.columnCount() > 1 else 0
            safe_idx = m.index(row, col)
            try:
                self.on_table_double_clicked(safe_idx)
            except Exception:
                pass
            return

        if chosen is act_ren:
            try:
                self.rename_selected_item()
            except Exception:
                try:
                    self.rename_selected_action()
                except Exception:
                    pass
            return

        if chosen is act_del:
            try:
                self.delete_selected_action()
            except Exception:
                try:
                    self.delete_selected_item()
                except Exception:
                    pass
            return

        if chosen is act_props:
            try:
                self.show_properties_dialog_for_index(idx)
            except Exception:
                try:
                    if is_folder and node:
                        self.show_folder_details(node)
                    else:
                        self.show_details_for_selected()
                except Exception:
                    pass
            return

        # копирование ссылок
        if act_copy_link and chosen is act_copy_link:
            self._show_document_link_dialog(node)
            return

        try:
            if is_folder:
                if 'act_d_zip' in locals() and chosen is act_d_zip:
                    self.download_folder_as_zip(node or {})
                else:
                    self.download_folder_plain(node or {})
            else:
                if 'act_d_file' in locals() and chosen is act_d_file:
                    self._download_file_plain_fixed(node or {})
                else:
                    self.download_file_as_zip(node or {})
        except Exception:
            pass

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
        """Fetch and present a document link in a compact dialog."""
        try:
            candidates = self._context_file_items(pivot_node)
        except Exception:
            candidates = []
        if not candidates:
            QMessageBox.information(self, "Копирование ссылки", "Выберите файл в таблице.")
            return

        target = candidates[0]
        doc_id = target.get("id")
        if not doc_id:
            QMessageBox.warning(self, "Копирование ссылки", "Не удалось определить идентификатор файла.")
            return

        result = self.api.generate_document_link(doc_id, "view")
        if not isinstance(result, dict):
            QMessageBox.warning(self, "Копирование ссылки", "Не удалось получить ссылку. Повторите попытку позже.")
            return

        if result.get("ok"):
            link = (result.get("url") or "").strip()
            if link:
                self._present_link_dialog(link)
                return
            QMessageBox.warning(self, "Копирование ссылки", "Ответ сервера не содержит ссылки.")
            return

        err_code = (result.get("error") or "").lower()
        detail = result.get("detail")
        if err_code == "unauthorized":
            QMessageBox.warning(self, "Авторизация", "Сессия истекла. Выполните вход заново.")
            try:
                self.logout_and_relogin()
            except Exception:
                try:
                    self.api.logout()
                except Exception:
                    pass
            return

        if err_code == "network":
            msg = "Сетевая ошибка при получении ссылки."
        elif err_code == "invalid_json":
            msg = "Сервер вернул некорректный ответ."
        elif err_code == "missing_url":
            msg = "Ответ сервера не содержит ссылки."
        else:
            msg = "Не удалось получить ссылку."
        if detail:
            msg = f"{msg}\n{detail}"
        QMessageBox.warning(self, "Копирование ссылки", msg)

    def _present_link_dialog(self, url: str):
        """Show a modal dialog with read-only link and copy button."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Ссылка на документ")
        dlg.setModal(True)

        layout = QVBoxLayout(dlg)

        info = QLabel("Ссылка на выбранный документ:")
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
        layout.addWidget(text)
        text.selectAll()

        controls = QHBoxLayout()
        copy_btn = QPushButton("Копировать", dlg)
        try:
            copy_icon = self._themed_icon(rsrc_path("icon", "copy.png"))
            if not copy_icon.isNull():
                copy_btn.setIcon(copy_icon)
        except Exception:
            pass
        copy_btn.setToolTip("Скопировать ссылку в буфер обмена")
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
                self.status.showMessage("Ссылка скопирована в буфер обмена.", 4000)
            except Exception as e:
                QMessageBox.warning(self, "Копирование ссылки", f"Не удалось скопировать ссылку: {e}")

        copy_btn.clicked.connect(_copy)

        dlg.resize(520, dlg.sizeHint().height())
        dlg.exec()

    def collect_all_items_recursive(self, node: dict):
        out = []
        def walk(n):
            for c in (n.get("children") or []):
                if not isinstance(c, dict):
                    continue
                t = (c.get("type") or "").lower()
                if t in ("file", "folder"):
                    out.append(c)
                if t == "folder":
                    walk(c)
        walk(node)
        return out

    def apply_table_filters(self):

        try:
            # --- 0) нициализация хранилищ ---
            if not hasattr(self, "_flt_type"): self._flt_type = None
            if not hasattr(self, "_flt_formats"): self._flt_formats = set()
            if not hasattr(self, "_flt_created"): self._flt_created = (None, None)
            if not hasattr(self, "_flt_modified"): self._flt_modified = (None, None)
            if not hasattr(self, "column_text_filters"): self.column_text_filters = {}
            if not hasattr(self, "column_filters"): self.column_filters = {}

            # Поиск по имени
            try:
                query = (self.search.text() or "").strip().lower()
            except Exception:
                query = ""
            # глубокий поиск по имени во вложенных папках
            deep_needed = bool(query) and getattr(self, "_search_recursive", False)

            if deep_needed != getattr(self, "_search_uses_recursive", False):
                # базовый узел для выборки: корень или текущая папка
                if self._is_root_open():
                    base = {"children": self.full_tree}   # корень проекта
                else:
                    base = (self.current_path_nodes[-1] if self.current_path_nodes else None)

                if base:
                    if deep_needed:
                        # глубоко: по всему поддереву
                        if self.cb_flat.isChecked():
                            # только файлы
                            self.files_current = self.collect_all_files_recursive(base)
                        else:
                            # файлы + папки (если нет готового метода - используем помощник ниже)
                            if hasattr(self, "collect_all_items_recursive"):
                                self.files_current = self.collect_all_items_recursive(base)
                            else:
                                self.files_current = self._collect_all_items_recursive(base)
                    else:
                        # неглубоко: только текущий уровень
                        if self.cb_flat.isChecked():
                            # только файлы на текущем уровне
                            ch = (base.get("children") or [])
                            self.files_current = [c for c in ch if isinstance(c, dict) and c.get("type") == "file"]
                        else:
                            # файлы и папки текущего уровня
                            self.files_current = self.collect_direct_level(base)

                    # пересоздать модель как у тебя было
                    self.files_model = FilesTableModel(self.files_current, self.icon_provider, self.checked)
                    self._search_uses_recursive = deep_needed
                    self.lazy_enrich_current_files(limit_per_folder=300)


            # --- 1) Хелперы для доступа к данным и колоночным индексам ---
            def _display_val_for(source_row: int, col: int) -> str:
                try:
                    idx = self.files_model.index(source_row, col)
                    v = self.files_model.data(idx)
                    return "" if v is None else str(v)
                except Exception:
                    return ""

            def _name_col_index() -> int:
                # На случай локализаций - ищем первую подходящую
                try:
                    return next(i for i, h in enumerate(FilesTableModel.HEADERS)
                                if str(h).strip().lower() in ("наименование", "название", "имя", "имя файла"))
                except Exception:
                    return 1  # дефолт

            def _col_idx(title: str) -> int:
                t = title.strip().lower()
                for i, h in enumerate(FilesTableModel.HEADERS):
                    if str(h).strip().lower() == t:
                        return i
                return -1

            # ндексы частых колонок
            name_col     = _name_col_index()
            created_col  = _col_idx("создано")
            modified_col = _col_idx("изменено")

            def _parse_dt(s: str):
                # Пытаемся распарсить дату-строку в QDateTime
                s = (s or "").strip()
                if not s:
                    return None
                dt = QDateTime.fromString(s, Qt.ISODate)
                if not dt.isValid():
                    dt = QDateTime.fromString(s, "yyyy-MM-dd HH:mm")
                if not dt.isValid():
                    dt = QDateTime.fromString(s, "yyyy-MM-dd")
                if not dt.isValid():
                    dt = QDateTime.fromString(s, "dd.MM.yyyy HH:mm")
                if not dt.isValid():
                    dt = QDateTime.fromString(s, "dd.MM.yyyy")
                return dt if dt.isValid() else None


            # Дата-диапазоны
            created_from, created_to = self._flt_created
            modified_from, modified_to = self._flt_modified
            if isinstance(created_from, QDate) and created_from.isValid():
                created_from_dt  = QDateTime(created_from,  QtCore.QTime(0, 0, 0))
            else:
                created_from_dt = None
            if isinstance(created_to, QDate) and created_to.isValid():
                created_to_dt    = QDateTime(created_to,    QtCore.QTime(23, 59, 59))
            else:
                created_to_dt = None
            if isinstance(modified_from, QDate) and modified_from.isValid():
                modified_from_dt = QDateTime(modified_from, QtCore.QTime(0, 0, 0))
            else:
                modified_from_dt = None
            if isinstance(modified_to, QDate) and modified_to.isValid():
                modified_to_dt   = QDateTime(modified_to,   QtCore.QTime(23, 59, 59))
            else:
                modified_to_dt = None

            # --- 2) Предикат допуска строки ---
            def _accept_row(source_row: int) -> bool:
                try:
                    item = self.files_model.item_at(source_row)
                except Exception:
                    item = {}
                if self._flt_formats and (item.get("type") or "").lower() == "folder":
                    return False
                # Тип: file/folder
                if self._flt_type:
                    t = (item.get("type") or "").lower()
                    if t not in self._flt_type:
                        return False

                # Поиск по имени
                if query:
                    hay = (_display_val_for(source_row, name_col) or "").lower()
                    if query not in hay:
                        return False

                # Формат по расширению - только для файлов
                # Если _flt_formats пустое множество или None - показываем все форматы (фильтр отключен)
                if self._flt_formats and (item.get("type") or "").lower() == "file":
                    name = (item.get("originalName") or item.get("name") or "")
                    ext = file_ext(name)  # ваша утилита для расширения
                    if ext not in self._flt_formats:
                        return False

                # Текстовые фильтры по конкретным колонкам: substring case-insensitive
                for c, needle in (self.column_text_filters or {}).items():
                    if not str(needle):
                        continue
                    val = _display_val_for(source_row, int(c)).lower()
                    if str(needle).lower() not in val:
                        return False

                # Фильтр по фиксированным наборам значений в колонках (меню значений)
                for c, allowed in (self.column_filters or {}).items():
                    if not allowed:
                        continue
                    val = _display_val_for(source_row, int(c))
                    if val not in allowed:
                        return False

                # Диапазон "Создано"
                if created_col >= 0 and (created_from_dt or created_to_dt):
                    dt = _parse_dt(_display_val_for(source_row, created_col))
                    if dt is None:
                        return False
                    if created_from_dt and dt < created_from_dt:
                        return False
                    if created_to_dt and dt > created_to_dt:
                        return False

                # Диапазон "зменено"
                if modified_col >= 0 and (modified_from_dt or modified_to_dt):
                    dt = _parse_dt(_display_val_for(source_row, modified_col))
                    if dt is None:
                        return False
                    if modified_from_dt and dt < modified_from_dt:
                        return False
                    if modified_to_dt and dt > modified_to_dt:
                        return False

                return True

            # --- 3) Прокси-модель с нашим фильтром ---
            class _Proxy(QSortFilterProxyModel):
                def __init__(self, mw):
                    super().__init__(mw)
                    self.mw = mw
                    self.setDynamicSortFilter(True)

                def filterAcceptsRow(self, source_row, source_parent):
                    try:
                        return _accept_row(source_row)
                    except Exception:
                        return True  # fail-open, не роняем таблицу

                def lessThan(self, left, right):
                    # делегируем сортировку вашей модели по SORT_ROLE, если задан
                    # Keep visible order if frozen during metadata enrichment
                    try:
                        if getattr(self.mw, "_freeze_visible_order", False) and getattr(self.mw, "_frozen_order", None):
                            l_item = self.sourceModel().data(left, Qt.UserRole) or {}
                            r_item = self.sourceModel().data(right, Qt.UserRole) or {}
                            lk = ((l_item.get("type") or None), l_item.get("id"))
                            rk = ((r_item.get("type") or None), r_item.get("id"))
                            lpos = self.mw._frozen_order.get(lk, 10**9)
                            rpos = self.mw._frozen_order.get(rk, 10**9)
                            return lpos < rpos
                    except Exception:
                        pass
                    # Default role-based sorting
                    try:
                        role = getattr(FilesTableModel, "SORT_ROLE", Qt.UserRole)
                        l = self.sourceModel().data(left, role)
                        r = self.sourceModel().data(right, role)
                        if l is None:
                            l = ""
                        if r is None:
                            r = ""
                        return l < r
                    except Exception:
                        return super().lessThan(left, right)

            # --- 4) Сохранение состояния представления до смены модели ---
            header = self.table.horizontalHeader()
            try:
                sort_col = header.sortIndicatorSection()
                sort_ord = header.sortIndicatorOrder()
            except Exception:
                sort_col, sort_ord = 0, Qt.AscendingOrder

            src_model = self.table.model() or self.files_model
            try:
                col_count = src_model.columnCount()
            except Exception:
                col_count = len(getattr(FilesTableModel, "HEADERS", []))

            saved_hidden = [self.table.isColumnHidden(i) for i in range(col_count)]
            saved_widths = [self.table.columnWidth(i) for i in range(col_count)]

            # --- 5) Назначаем новую прокси-модель ---
            proxy = _Proxy(self)
            proxy.setSourceModel(self.files_model)
            try:
                proxy.setSortRole(FilesTableModel.SORT_ROLE)
            except Exception:
                pass
            self.proxy = proxy
            self.table.setModel(self.proxy)
            self._bind_table_selection_signals()
            # Apply persisted columns visibility (including defaults)
            try:
                self._load_columns_visibility()
            except Exception:
                pass
            try:
                # Ensure "Изменено" column visible by default
                modified_col = 7
                if 0 <= modified_col < self.proxy.columnCount():
                    self.table.setColumnHidden(modified_col, False)
            except Exception:
                pass
            

            # --- 6) Восстановление состояния колонок и сортировки ---
            new_cols = self.proxy.columnCount()
            for c in range(min(new_cols, len(saved_hidden))):
                try:
                    self.table.setColumnHidden(c, saved_hidden[c])
                except Exception:
                    pass
                try:
                    w = int(saved_widths[c])
                    if w > 0:
                        self.table.setColumnWidth(c, w)
                except Exception:
                    pass

            try:
                header.setSortIndicatorShown(self._sorting_armed)
                if self._sorting_armed:
                    header.setSortIndicator(sort_col, sort_ord)
                    self.table.sortByColumn(sort_col, sort_ord)
                sort_col = max(0, min(sort_col, new_cols - 1))
            except Exception:
                pass

            # --- 7) Обновляем связанные элементы UI ---
            try:
                self.update_header_checkbox()
            except Exception:
                pass
            try:
                self._update_actions_enabled()
            except Exception:
                pass
            try:
                if hasattr(self, "header_filter_icons_update"):
                    self.header_filter_icons_update()
            except Exception:
                pass
            try:
                if hasattr(self, "_bind_table_selection_signals"):
                    self._bind_table_selection_signals()
            except Exception:
                pass

        except Exception as e:
            try:
                QMessageBox.warning(self, "Фильтр", f"Не удалось применить фильтр:\n{e}")
            except Exception:
                pass

        
    def auto_hide_empty_columns(self):
        """Показываем все доступные столбцы по умолчанию"""
        proxy = getattr(self, "proxy", None)
        if proxy is None: 
            return
        
        # Показываем все столбцы по умолчанию
        for col in range(proxy.columnCount()):
            self.table.setColumnHidden(col, False)
        
        # Убедимся что основные столбцы видимы
        try:
            if proxy.columnCount() > 0:
                # Столбец с чекбоксами (0) всегда виден
                self.table.setColumnHidden(0, False)
                # Наименование (обычно столбец 2) всегда видимо
                if proxy.columnCount() > 2:
                    self.table.setColumnHidden(2, False)
        except Exception:
            pass


    def _update_header_checkbox_pos(self, *args):
        # Блокируем обновление если идёт изменение состояния чекбокса
        if getattr(self, '_updating_checkbox_state', False):
            return
        
        try:
            x = self.hdr.sectionViewportPosition(0)
            h = self.hdr.height()
            # Фиксированный размер чекбокса и столбца
            size = 18  # HeaderCheckButton.BOX = 18
            # Центрируем чекбокс идеально по центру столбца (как в строках таблицы)
            self.hdrcb.setGeometry(x + (CHECKBOX_COLUMN_WIDTH - size)//2, (h - size)//2, size, size)
            try:
                # Keep checkbox above header overlays (filter icons, etc.)
                self.hdrcb.raise_()
            except Exception:
                pass
        except Exception:
            pass

    def _fix_first_column_width(self):
        """Принудительно восстанавливает ширину первого столбца к фиксированному значению"""
        try:
            if hasattr(self, '_original_hdr_resize'):
                self._original_hdr_resize(0, CHECKBOX_COLUMN_WIDTH)
            else:
                self.hdr.resizeSection(0, CHECKBOX_COLUMN_WIDTH)
        except Exception:
            pass


    def set_all_visible_checked(self, on: bool):
        # Меняем флаги у всех видимых строк, не даём сортировке прыгать во время апдейта
        proxy = self.table.model() or getattr(self, "proxy", None)
        fm = getattr(self, "files_model", None)
        if proxy is None or fm is None:
            return

        rows = int(proxy.rowCount())
        if rows <= 0:
            return

        # Снимем сортировку на время массового изменения
        was_sorting = False
        try:
            was_sorting = bool(self.table.isSortingEnabled())
            if was_sorting:
                self.table.setSortingEnabled(False)
        except Exception:
            pass

        # Собираем список исходных строк до любых изменений, чтобы порядок не мешал
        src_rows = []
        for r in range(rows):
            pidx = proxy.index(r, 0)
            if not pidx.isValid():
                continue
            try:
                sidx = proxy.mapToSource(pidx)
            except Exception:
                sidx = QModelIndex()
            if sidx.isValid():
                src_rows.append(sidx.row())

        if not src_rows:
            # Вернём сортировку как было
            try:
                if was_sorting:
                    self.table.setSortingEnabled(True)
            except Exception:
                pass
            return

        # Массово меняем множество отмеченных ключей
        if on:
            for r in src_rows:
                try:
                    item = fm._data[r]
                    fm.checked.add(fm._cb_key(item))
                except Exception:
                    pass
        else:
            for r in src_rows:
                try:
                    item = fm._data[r]
                    fm.checked.discard(fm._cb_key(item))
                except Exception:
                    pass

        # Оповестим модель одним диапазоном, чтобы перерисовать PNG-иконки
        try:
            top_s = fm.index(min(src_rows), 0)
            bot_s = fm.index(max(src_rows), 0)
            fm.dataChanged.emit(top_s, bot_s, [Qt.CheckStateRole])
        except Exception:
            pass

        # Вернём сортировку в исходное состояние
        try:
            if was_sorting:
                self.table.setSortingEnabled(True)
        except Exception:
            pass

        try:
            self.table.viewport().update()
        except Exception:
            pass

        self.update_header_checkbox()
        self._update_actions_enabled()



    def update_header_checkbox(self):
        try:
            proxy = self.table.model() or getattr(self, "proxy", None)
            fm = getattr(self, "files_model", None)
            if proxy is None or fm is None:
                return

            total = proxy.rowCount()
            if total <= 0:
                self.hdrcb.blockSignals(True)
                self.hdrcb.setCheckState(Qt.Unchecked)
                self.hdrcb.blockSignals(False)
                return

            checked = 0
            for r in range(total):
                pidx = proxy.index(r, 0)
                if not pidx.isValid():
                    continue
                try:
                    sidx = proxy.mapToSource(pidx)
                except Exception:
                    sidx = QModelIndex()
                if not sidx.isValid():
                    continue
                try:
                    item = fm._data[sidx.row()]
                    if fm._cb_key(item) in fm.checked:
                        checked += 1
                except Exception:
                    pass

            if checked == 0:
                state = Qt.Unchecked
            elif checked == total:
                state = Qt.Checked
            else:
                state = Qt.PartiallyChecked

            self.hdrcb.blockSignals(True)
            self.hdrcb.setCheckState(state)
            self.hdrcb.blockSignals(False)
        except Exception:
            pass




    def on_header_cb_clicked(self, checked: bool):
        # Простая логика: клик переключает все элементы
        # checked = True означает что чекбокс стал отмеченным
        self.set_all_visible_checked(checked)


    def on_header_cb_state_changed(self, state: int):
        # Блокируем обновление позиции чекбокса во время изменения состояния
        self._updating_checkbox_state = True
        try:
            # Сравниваем с целыми числами вместо enum
            if state == 1:  # Qt.PartiallyChecked
                # при клике по "полоске" включаем все видимые строки и фиксируем заголовок как Checked
                self.set_all_visible_checked(True)
                try:
                    self.hdrcb.blockSignals(True)
                    self.hdrcb.setCheckState(Qt.Checked)
                finally:
                    try:
                        self.hdrcb.blockSignals(False)
                    except Exception:
                        pass
            elif state == 2:  # Qt.Checked
                self.set_all_visible_checked(True)
            elif state == 0:  # Qt.Unchecked
                self.set_all_visible_checked(False)
        finally:
            self._updating_checkbox_state = False


    def on_sort_changed(self, column: int, _order: Qt.SortOrder):
        # Disallow sorting by the first checkbox column
        if column == 0:
            try:
                hdr = self.table.horizontalHeader()
                # Revert indicator back to the last allowed column/order
                last_col = getattr(self, "_last_sort_section", None)
                last_ord = getattr(self, "_last_sort_order", Qt.AscendingOrder)
                if isinstance(last_col, int) and last_col != 0:
                    hdr.blockSignals(True)
                    hdr.setSortIndicator(last_col, last_ord)
                    hdr.blockSignals(False)
            except Exception:
                pass
            return

        # Track last valid sort
        try:
            self._last_sort_section = int(column)
            self._last_sort_order = _order
        except Exception:
            pass
        fmt_col = FilesTableModel.HEADERS.index("Формат")
        for btn in getattr(self, "chips", {}).values():
            btn.setProperty("highlight", False); btn.style().unpolish(btn); btn.style().polish(btn); btn.update()
        if column == fmt_col and self.proxy.rowCount() > 0:
            idx = self.proxy.index(0, fmt_col); fmt = (self.proxy.data(idx) or "").upper()
            target = None
            if fmt == "PDF": target = "PDF"
            elif fmt in ("PNG", "JPG", "JPEG", "GIF", "BMP", "TIF", "TIFF", "WEBP", "SVG", "SVGZ", "ICO", "ICNS", "HEIC", "HEIF", "AVIF", "APNG", "JFIF", "JP2", "J2K", "JPF", "JPX", "JPM", "TGA", "DDS", "WBMP", "PSD", "AI", "EPS", "RAW", "DNG", "CR2", "CR3", "NEF", "ARW", "ORF", "RW2", "RAF", "SR2", "PEF"): target = "JPG"
            elif fmt in ("DOCX", "DOC", "DOCM", "DOTX", "DOTM", "DOT", "RTF", "DOCB", "MHT", "MHTML", "WBK", "XLSX", "XLS", "XLSM", "XLSB", "XLTX", "XLTM", "XLT", "XLAM", "XLA", "XLW", "XLL", "CRTX", "PPTX", "PPT", "PPTM", "POTX", "POTM", "POT", "PPSX", "PPSM", "PPS", "PPAM", "PPA", "THMX", "PST", "OST", "MSG", "OFT", "OLM", "NK2", "ONE", "ONEPKG", "ONETOC2", "ACCDB", "MDB", "ACCDE", "MDE", "ACCDT", "ACCDA", "ACCDR", "ACCDC", "ADP", "ADE", "MDW", "PUB", "VSDX", "VSD", "VSDM", "VSSX", "VSSM", "VSS", "VSTX", "VSTM", "VST", "VDX", "VSX", "VTX", "VDW", "MPP", "MPT", "MPD", "MPX", "XPS"): target = "DOC"
            elif fmt in {"DWG","DXF","STEP","STP","IGES","IGS","IFC", "CAD", "IMC", "RVT", "NWF", "NWC"}: target = "CAD"
            chips = getattr(self, "chips", {})
            if target and target in chips:
                b = chips[target]; b.setProperty("highlight", True); b.style().unpolish(b); b.style().polish(b); b.update()
        try:
            self.header_filter_icons_update()
        except Exception:
            pass


        
    def header_context_menu(self, pos):
        """
        ПКМ по заголовку: 
        - Тип -> чекбоксы «Файл»/«Папка»
        - Формат -> чекбоксы DOCX/PDF/JPG/CAD
        - Кем создан / Кем изменено -> текстовый фильтр
        - Создано / изменено -> диапазон дат через два календаря
        - Наименование -> ничего не открываем
        """
        m = StickyMenu(self)        # было QMenu(self)
        m.setObjectName("nikHeaderMenu")
        try:
            hdr = self.table.horizontalHeader()
            col = hdr.logicalIndexAt(pos)
            if col < 0:
                return

            # Заголовок и его «нижний регистр» для сравнения
            try:
                header_title = (self.table.model().headerData(col, Qt.Horizontal) or "")
            except Exception:
                header_title = ""
            title_l = str(header_title).strip().lower()

            # Держатели состояния новых фильтров
            if not hasattr(self, "_flt_type"):           # None = нет фильтра, иначе set({"file","folder"}) подмножество
                self._flt_type = None
            if not hasattr(self, "_flt_formats"):        # set({"DOCX","PDF","JPG","CAD"})
                self._flt_formats = set()
            if not hasattr(self, "_flt_created"):        # (QDate|None, QDate|None)
                self._flt_created = (None, None)
            if not hasattr(self, "_flt_modified"):
                self._flt_modified = (None, None)
            if not hasattr(self, "column_text_filters"): # для «Кем создан/изменено»
                self.column_text_filters = {}

            # Что не трогаем
            if title_l in {"наименование","название","имя","имя файла"}:
                return

            def _apply_and_close():
                try:
                    self.apply_table_filters()
                    if hasattr(self, "header_filter_icons_update"):
                        self.header_filter_icons_update()
                except Exception:
                    pass

            # ----- Тип -----
            if title_l in {"тип","type"}:
                # Создаем виджет-обёртку для чекбоксов
                wrap = QWidget(m)
                layout = QVBoxLayout(wrap)
                layout.setContentsMargins(4, 4, 4, 4)
                layout.setSpacing(4)

                # Подготовка иконок
                icon_off = self._themed_icon(CHECK_ICON_OFF_PATH)
                icon_on = self._themed_icon(CHECK_ICON_ON_PATH)

                checkboxes = {}
                rows = {}

                for lab, key in [("Файл", "file"), ("Папка", "folder")]:
                    # Кастомный виджет с иконкой (как в дереве папок)
                    row = QWidget(wrap)
                    row.setCursor(Qt.PointingHandCursor)
                    row_layout = QHBoxLayout(row)
                    row_layout.setContentsMargins(4, 4, 4, 4)
                    row_layout.setSpacing(8)

                    # Label с иконкой вместо кнопки (нет рамки)
                    cb_icon = QLabel(row)
                    cb_icon.setFixedSize(18, 18)
                    cb_icon.setScaledContents(True)
                    cb_icon.setPixmap(icon_off.pixmap(18, 18) if not icon_off.isNull() else QPixmap())
                    cb_icon.setCursor(Qt.PointingHandCursor)

                    # Label с названием
                    lbl = QLabel(lab, row)
                    lbl.setCursor(Qt.PointingHandCursor)

                    row_layout.addWidget(cb_icon, 0)
                    row_layout.addWidget(lbl, 1)

                    checkboxes[key] = cb_icon
                    rows[key] = row
                    layout.addWidget(row)

                # Добавляем виджет в меню через QWidgetAction
                action = QWidgetAction(m)
                action.setDefaultWidget(wrap)
                m.addAction(action)

                # Инициализируем галочки при открытии меню
                cur = set() if self._flt_type is None else set(self._flt_type)
                checked_state = {}
                for key, cb in checkboxes.items():
                    checked = key in cur
                    checked_state[key] = checked
                    pm = icon_on.pixmap(18, 18) if checked else icon_off.pixmap(18, 18)
                    cb.setPixmap(pm if not pm.isNull() else QPixmap())

                # Подключаем обработчики через row.mousePressEvent
                for key, row in rows.items():
                    def on_toggle(event, row=row, key=key):
                        checked_state[key] = not checked_state.get(key, False)
                        sel = set()
                        if checked_state.get("file", False):
                            sel.add("file")
                        if checked_state.get("folder", False):
                            sel.add("folder")
                        self._flt_type = None if len(sel) == 0 or len(sel) == 2 else sel
                        cb = checkboxes[key]
                        is_checked = checked_state[key]
                        pm = icon_on.pixmap(18, 18) if is_checked else icon_off.pixmap(18, 18)
                        cb.setPixmap(pm if not pm.isNull() else QPixmap())
                        _apply_and_close()

                    row.mousePressEvent = on_toggle

                m.addSeparator()
                act_clear = m.addAction("Сбросить фильтр")
                def _clear_type():
                    self._flt_type = None
                    for cb in checkboxes.values():
                        pm = icon_off.pixmap(18, 18)
                        cb.setPixmap(pm if not pm.isNull() else QPixmap())
                    for key in checked_state:
                        checked_state[key] = False
                    _apply_and_close()
                act_clear.triggered.connect(_clear_type)

            # ----- Формат -----
            elif title_l in {"формат", "format"}:
                opts = ["DOCX", "PDF", "JPG", "CAD"]
                label2ext = {
                            "DOCX": {
                                "docx","doc","docm","dotx","dotm","dot","rtf","docb","mht","mhtml","wbk",
                                "xlsx","xls","xlsm","xlsb","xltx","xltm","xlt","xlam","xla","xlw","xll","crtx",
                                "pptx","ppt","pptm","potx","potm","pot","ppsx","ppsm","pps","ppam","ppa","thmx",
                                "pst","ost","msg","oft","olm","nk2",
                                "one","onepkg","onetoc2",
                                "accdb","mdb","accde","mde","accdt","accda","accdr","accdc","adp","ade","mdw",
                                "pub",
                                "vsdx","vsd","vsdm","vssx","vssm","vss","vstx","vstm","vst","vdx","vsx","vtx","vdw",
                                "mpp","mpt","mpd","mpx",
                                "xps"},
                            "PDF": {"pdf"},
                            "JPG": {
                                "png","jpg","jpeg","gif","bmp","tif","tiff","webp","svg","svgz","ico","icns",
                                "heic","heif","avif","apng","jfif","jp2","j2k","jpf","jpx","jpm","tga","dds",
                                "wbmp","psd","ai","eps","raw","dng","cr2","cr3","nef","arw","orf","rw2","raf",
                                "sr2","pef"},
                            "CAD": {"dwg","dxf","step","stp","iges","igs","ifc","cad","imc","rvt","nwf","nwc"},
                }

                # Создаем виджет-обёртку для чекбоксов
                wrap = QWidget(m)
                layout = QVBoxLayout(wrap)
                layout.setContentsMargins(4, 4, 4, 4)
                layout.setSpacing(4)

                checkboxes = {}
                rows = {}

                for lab in opts:
                    # Кастомный виджет с иконкой (как в дереве папок)
                    row = QWidget(wrap)
                    row.setCursor(Qt.PointingHandCursor)
                    row_layout = QHBoxLayout(row)
                    row_layout.setContentsMargins(4, 4, 4, 4)
                    row_layout.setSpacing(8)

                    # Label с иконкой вместо кнопки (нет рамки)
                    cb_icon = QLabel(row)
                    cb_icon.setFixedSize(18, 18)
                    cb_icon.setScaledContents(True)
                    icon_off_tmp = self._themed_icon(CHECK_ICON_OFF_PATH)
                    cb_icon.setPixmap(icon_off_tmp.pixmap(18, 18) if not icon_off_tmp.isNull() else QPixmap())
                    cb_icon.setCursor(Qt.PointingHandCursor)

                    # Label с названием
                    lbl = QLabel(lab, row)
                    lbl.setCursor(Qt.PointingHandCursor)

                    row_layout.addWidget(cb_icon, 0)
                    row_layout.addWidget(lbl, 1)

                    checkboxes[lab] = cb_icon
                    rows[lab] = row
                    layout.addWidget(row)

                # Добавляем виджет в меню через QWidgetAction
                action = QWidgetAction(m)
                action.setDefaultWidget(wrap)
                m.addAction(action)

                # Подготовка иконок
                icon_off = self._themed_icon(CHECK_ICON_OFF_PATH)
                icon_on = self._themed_icon(CHECK_ICON_ON_PATH)

                # Инициализируем галочки при открытии меню
                cur = set(self._flt_formats or set())
                checked_state = {}
                for lab, cb in checkboxes.items():
                    exts = label2ext.get(lab, {lab.lower()})
                    checked = bool(exts & cur)
                    checked_state[lab] = checked
                    pm = icon_on.pixmap(18, 18) if checked else icon_off.pixmap(18, 18)
                    cb.setPixmap(pm if not pm.isNull() else QPixmap())

                # Подключаем обработчики через row.mousePressEvent
                for lab, row in rows.items():
                    def on_toggle(event, row=row, lab=lab):
                        is_checked = not checked_state.get(lab, False)
                        checked_state[lab] = is_checked
                        s = set()
                        for l, checked in checked_state.items():
                            if checked:
                                exts = label2ext.get(l, {l.lower()})
                                s |= exts
                        self._flt_formats = s
                        cb = checkboxes[lab]
                        pm = icon_on.pixmap(18, 18) if is_checked else icon_off.pixmap(18, 18)
                        cb.setPixmap(pm if not pm.isNull() else QPixmap())
                        _apply_and_close()

                    row.mousePressEvent = on_toggle

                m.addSeparator()
                act_clear = m.addAction("Сбросить")
                def _clear_formats():
                    self._flt_formats = set()
                    for cb in checkboxes.values():
                        pm = icon_off.pixmap(18, 18)
                        cb.setPixmap(pm if not pm.isNull() else QPixmap())
                    for lab in checked_state:
                        checked_state[lab] = False
                    _apply_and_close()
                act_clear.triggered.connect(_clear_formats)


                # Нижняя панель: "Сбросить" (не закрывает меню)
            # ----- Версия / Кем создан / Кем изменено -----
            elif title_l in {"версия","version","кем создан","created by","author","owner","кем изменено","modified by","editor"}:
                # локальный импорт: оставляем только нужное
        

                if not hasattr(self, "column_text_filters"): self.column_text_filters = {}
                if not hasattr(self, "column_filters"): self.column_filters = {}

                # helper
                def _apply_and_refresh():
                    try:
                        self.apply_table_filters()
                        if hasattr(self, "header_filter_icons_update"):
                            self.header_filter_icons_update()
                    except Exception:
                        pass

                # обёртка в родительском меню заголовка
                wrap = QWidget(m)
                vl = QVBoxLayout(wrap); vl.setContentsMargins(8,8,8,8); vl.setSpacing(6)

                # 1) верхний ряд: ввод + кнопка "Варианты"
                row_top = QWidget(wrap)
                ht = QHBoxLayout(row_top); ht.setContentsMargins(0,0,0,0); ht.setSpacing(8)

                le = QLineEdit(row_top)
                le.setPlaceholderText("введите текст")
                le.setMinimumWidth(260)
                le.setText(self.column_text_filters.get(col, ""))
                ht.addWidget(le, 1)

                btn = QToolButton(row_top)
                btn.setObjectName("filterTrigger")
                btn.setIcon(self._themed_icon(STRUCTURE_ICON_PATH))
                btn.setIconSize(QSize(16, 16))
                btn.setCheckable(True)
                btn.setAutoRaise(False)
                btn.setProperty("secondary", True)
                btn.setCursor(Qt.PointingHandCursor)
                btn.setToolTip("Варианты")
                btn.setStyleSheet("QToolButton::menu-indicator{ image: none; width:0; }")
                ht.addWidget(btn, 0)

                vl.addWidget(row_top)

                # 2) "Сбросить" под строкой ввода
                btn_reset_main = QPushButton("Сбросить", wrap)
                btn_reset_main.setProperty("secondary", True)
                vl.addWidget(btn_reset_main, 0)

                # 3) виджет со списком значений (скрыт по умолчанию)
                values_wrap = QWidget(wrap)
                values_wrap.setVisible(False)
                values_layout = QVBoxLayout(values_wrap)
                values_layout.setContentsMargins(4, 4, 4, 4)
                values_layout.setSpacing(4)

                # 4) собираем уникальные значения
                uniq = []
                try:
                    sm = self.files_model
                    seen = set()
                    for r in range(sm.rowCount()):
                        s = str(sm.data(sm.index(r, col)) or "").strip()
                        try:
                            t = title_l
                        except Exception:
                            t = ""
                        if s == "" and t in {"версия", "кем изменено", "кем создано", "version", "modified by", "created by"}:
                            continue
                        if t in {"формат", "format"} and s in {"???", "?"}:
                            continue
                        k = s.lower()
                        if k not in seen:
                            seen.add(k); uniq.append(s)
                except Exception:
                    pass

                display2real = {}
                for s in sorted(uniq, key=lambda x: (x == "", x.lower())):
                    disp = "(пусто)" if s == "" else s
                    display2real[disp] = s

                # 5) создаём чекбоксы для значений
                values_checkboxes = []
                for disp, real in display2real.items():
                    row = QWidget(values_wrap)
                    row.setCursor(Qt.PointingHandCursor)
                    row_layout = QHBoxLayout(row)
                    row_layout.setContentsMargins(4, 4, 4, 4)
                    row_layout.setSpacing(8)

                    # Label с иконкой вместо чекбокса
                    cb_icon = QLabel(row)
                    cb_icon.setFixedSize(18, 18)
                    cb_icon.setScaledContents(True)
                    icon_off = self._themed_icon(CHECK_ICON_OFF_PATH)
                    cb_icon.setPixmap(icon_off.pixmap(18, 18) if not icon_off.isNull() else QPixmap())
                    cb_icon.setCursor(Qt.PointingHandCursor)

                    # Label с названием
                    lbl = QLabel(disp, row)
                    lbl.setCursor(Qt.PointingHandCursor)

                    row_layout.addWidget(cb_icon, 0)
                    row_layout.addWidget(lbl, 1)

                    values_checkboxes.append((row, cb_icon, real))
                    values_layout.addWidget(row)

                # Добавляем виджет значений в layout
                vl.addWidget(values_wrap)

                # 6) функция для инициализации галочек
                def _init_checkboxes():
                    preselected = set(self.column_filters.get(col, set()))
                    icon_off = self._themed_icon(CHECK_ICON_OFF_PATH)
                    icon_on = self._themed_icon(CHECK_ICON_ON_PATH)
                    for row, cb, real in values_checkboxes:
                        checked = real in preselected
                        pm = icon_on.pixmap(18, 18) if checked else icon_off.pixmap(18, 18)
                        cb.setPixmap(pm if not pm.isNull() else QPixmap())

                # 7) обработчики для чекбоксов
                for row, cb, real in values_checkboxes:
                    def on_toggle(event, row=row, cb=cb, real=real):
                        checked_state = getattr(on_toggle, 'checked_state', {})
                        checked_state[real] = not checked_state.get(real, False)
                        selected = set()
                        for _, _, r in values_checkboxes:
                            if checked_state.get(r, False):
                                selected.add(r)
                        if selected:
                            self.column_filters[col] = selected
                        else:
                            self.column_filters.pop(col, None)
                        icon_off = self._themed_icon(CHECK_ICON_OFF_PATH)
                        icon_on = self._themed_icon(CHECK_ICON_ON_PATH)
                        pm = icon_on.pixmap(18, 18) if checked_state[real] else icon_off.pixmap(18, 18)
                        cb.setPixmap(pm if not pm.isNull() else QPixmap())
                        _apply_and_refresh()

                    row.mousePressEvent = on_toggle

                # 8) показываем/скрываем список при клике на кнопку
                def toggle_values():
                    values_wrap.setVisible(not values_wrap.isVisible())
                    if values_wrap.isVisible():
                        _init_checkboxes()

                btn.clicked.connect(toggle_values)

                # 9) живой текстовый фильтр
                le.textChanged.connect(
                    lambda _=None: (
                        self.column_text_filters.__setitem__(col, t) if (t := le.text().strip())
                        else self.column_text_filters.pop(col, None),
                        _apply_and_refresh()
                    )
                )

                # 10) общий сброс
                def _reset_all():
                    try:
                        le.blockSignals(True); le.clear(); le.blockSignals(False)
                    except Exception:
                        pass
                    self.column_text_filters.pop(col, None)
                    self.column_filters.pop(col, None)
                    _init_checkboxes()
                    _apply_and_refresh()

                btn_reset_main.clicked.connect(_reset_all)

                # 11) вставляем виджет в контекстное меню заголовка
                wa = QWidgetAction(m); wa.setDefaultWidget(wrap); m.addAction(wa)







            # ----- Создано / зменено (диапазон дат) -----
            elif title_l in {"создано","дата создания","created"} or title_l in {"изменено","дата изменения","modified"}:
                wrap = QWidget(m); vl = QVBoxLayout(wrap); vl.setContentsMargins(8,8,8,8); vl.setSpacing(6)
                row = QWidget(wrap); hl = QHBoxLayout(row); hl.setContentsMargins(0,0,0,0); hl.setSpacing(8)
                cal1 = QCalendarWidget(row); cal2 = QCalendarWidget(row)
                cal1.setGridVisible(True); cal2.setGridVisible(True)
                try:
                    cal1.setMinimumWidth(230)
                    cal2.setMinimumWidth(230)
                except Exception:
                    pass
                # Снять эллипсы и кастомные делегаты — иначе дни показываются как "..."
                for cal in (cal1, cal2):
                    # Спрятать номера недель и ограничить диапазон лет текущий±3
                    try:
                        cal.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
                        # Ensure Monday-first and visible weekday header
                        try:
                            cal.setFirstDayOfWeek(Qt.Monday)
                        except Exception:
                            pass
                        try:
                            cal.setHorizontalHeaderFormat(QCalendarWidget.ShortDayNames)
                        except Exception:
                            pass
                        cy = QDate.currentDate().year()
                        cal.setDateRange(QDate(cy-3, 1, 1), QDate(cy+3, 12, 31))
                    except Exception:
                        pass
                    # Задать иконки для кнопок изменения года
                    try:
                        prevy = cal.findChild(QToolButton, "qt_calendar_prevyear")
                        nexty = cal.findChild(QToolButton, "qt_calendar_nextyear")
                        if prevy and SORT_ICON_DOWN_PATH:
                            prevy.setIcon(self._themed_icon(SORT_ICON_DOWN_PATH))
                        if nexty and SORT_ICON_UP_PATH:
                            nexty.setIcon(self._themed_icon(SORT_ICON_UP_PATH))
                    except Exception:
                        pass
                    view = cal.findChild(QTableView, "qt_calendar_calendarview")
                    if view:
                        view.setTextElideMode(Qt.ElideNone)          # никакого "..."
                        view.setWordWrap(False)
                        view.setItemDelegate(QStyledItemDelegate(view))  # дефолтный делегат

                hl.addWidget(cal1); hl.addWidget(cal2); vl.addWidget(row)

                # Enforce single-month display for both calendars: hide neighbor months completely
                def _enforce_single_month(cal: QCalendarWidget):
                    try:
                        view = cal.findChild(QTableView, "qt_calendar_calendarview")
                        if view:
                            view.setItemDelegate(QStyledItemDelegate(view))
                    except Exception:
                        pass

                    # Reset date formats so the calendar shows each day in its default style
                    try:
                        try:
                            yy = int(cal.yearShown())
                            mm = int(cal.monthShown())
                        except Exception:
                            d = cal.selectedDate()
                            yy, mm = int(d.year()), int(d.month())
                        first = QDate(yy, mm, 1)
                        try:
                            fd = cal.firstDayOfWeek()
                            fdow = int(getattr(fd, 'value', fd))
                        except Exception:
                            fdow = 1
                        shift = (first.dayOfWeek() - fdow + 7) % 7
                        grid_start = first.addDays(-shift)
                        fmt_reset = QTextCharFormat()
                        for i in range(42):
                            cal.setDateTextFormat(grid_start.addDays(i), fmt_reset)
                    except Exception:
                        pass
                    try:
                        if not hasattr(cal, "_one_month_hooked"):
                            cal.currentPageChanged.connect(lambda _y, _m, c=cal: _enforce_single_month(c))
                            cal._one_month_hooked = True
                    except Exception:
                        pass

                _enforce_single_month(cal1)
                _enforce_single_month(cal2)

                # текущие значения
                cur = self._flt_created if title_l in {"создано","дата создания","created"} else self._flt_modified
                d1, d2 = cur
                if d1: cal1.setSelectedDate(d1)
                if d2: cal2.setSelectedDate(d2)
                def _attach_year_menu(cal):
                    year_btn = cal.findChild(QToolButton, "qt_calendar_yearbutton")
                    if not year_btn:
                        return  # на некоторых версиях Qt тут может быть spinbox, тогда пропускаем

                    menu = QMenu(year_btn)
                    # Динамический список годов: текущий±3
                    def rebuild_fixed():
                        try:
                            menu.clear()
                            cy = QDate.currentDate().year()
                            
                            # Добавляем поле для ручного ввода года в меню
                            input_container = QWidget(menu)
                            input_layout = QHBoxLayout(input_container)
                            input_layout.setContentsMargins(5, 5, 5, 5)
                            input_layout.setSpacing(5)
                            
                            year_input = QLineEdit(input_container)
                            year_input.setPlaceholderText("Введите год...")
                            try:
                                current_year = cal.yearShown()
                                year_input.setText(str(current_year))
                            except Exception:
                                year_input.setText(str(cy))
                            year_input.setMaximumWidth(100)
                            
                            apply_btn = QPushButton("ОК", input_container)
                            # Не даём кнопке быть слишком узкой — иначе "ОК" обрезается в попапе
                            try:
                                apply_btn.setMinimumWidth(apply_btn.sizeHint().width())
                            except Exception:
                                apply_btn.setMinimumWidth(56)
                            
                            def apply_year_input():
                                try:
                                    y = int(year_input.text())
                                    min_y = cy - 3
                                    max_y = cy + 3
                                    if min_y <= y <= max_y:
                                        cal.setCurrentPage(y, cal.monthShown())
                                        menu.close()
                                    else:
                                        year_input.setStyleSheet("border: 1px solid red")
                                        QTimer.singleShot(1000, lambda: year_input.setStyleSheet(""))
                                except ValueError:
                                    year_input.setStyleSheet("border: 1px solid red")
                                    QTimer.singleShot(1000, lambda: year_input.setStyleSheet(""))
                                    
                            apply_btn.clicked.connect(apply_year_input)
                            year_input.returnPressed.connect(apply_year_input)
                            
                            input_layout.addWidget(year_input)
                            input_layout.addWidget(apply_btn)
                            
                            wa = QWidgetAction(menu)
                            wa.setDefaultWidget(input_container)
                            menu.addAction(wa)
                            
                            menu.addSeparator()
                            
                            # Добавляем годы как отдельные пункты меню
                            for yy in range(cy - 3, cy + 4):
                                act = QAction(str(yy), menu)
                                act.setCheckable(True)
                                act.setChecked(yy == cal.yearShown())
                                act.triggered.connect(lambda _=False, yy=yy: cal.setCurrentPage(yy, cal.monthShown()))
                                menu.addAction(act)
                        except Exception:
                            pass

                    def rebuild(anchor_year=None):
                        menu.clear()
                        shown_y = anchor_year if anchor_year is not None else cal.yearShown()
                        min_y = max(cal.minimumDate().year(), shown_y - 6)
                        max_y = min(cal.maximumDate().year(), shown_y + 6)

                        # Добавляем поле для ручного ввода года в меню
                        input_container = QWidget(menu)
                        input_layout = QHBoxLayout(input_container)
                        input_layout.setContentsMargins(5, 5, 5, 5)
                        input_layout.setSpacing(5)
                        
                        year_input = QLineEdit(input_container)
                        year_input.setPlaceholderText("Введите год...")
                        try:
                            current_year = cal.yearShown()
                            year_input.setText(str(current_year))
                        except Exception:
                            year_input.setText(str(QDate.currentDate().year()))
                        year_input.setMaximumWidth(100)
                        
                        apply_btn = QPushButton("ОК", input_container)
                        # Ширина по sizeHint, чтобы текст не срезался
                        try:
                            apply_btn.setMinimumWidth(apply_btn.sizeHint().width())
                        except Exception:
                            apply_btn.setMinimumWidth(56)
                        
                        def apply_year_input():
                            try:
                                y = int(year_input.text())
                                if cal.minimumDate().year() <= y <= cal.maximumDate().year():
                                    cal.setCurrentPage(y, cal.monthShown())
                                    menu.close()
                                else:
                                    year_input.setStyleSheet("border: 1px solid red")
                                    QTimer.singleShot(1000, lambda: year_input.setStyleSheet(""))
                            except ValueError:
                                year_input.setStyleSheet("border: 1px solid red")
                                QTimer.singleShot(1000, lambda: year_input.setStyleSheet(""))
                                
                        apply_btn.clicked.connect(apply_year_input)
                        year_input.returnPressed.connect(apply_year_input)
                        
                        input_layout.addWidget(year_input)
                        input_layout.addWidget(apply_btn)
                        
                        wa = QWidgetAction(menu)
                        wa.setDefaultWidget(input_container)
                        menu.addAction(wa)
                        
                        menu.addSeparator()

                        prev_block = QAction("? Раньше", menu)
                        prev_block.triggered.connect(lambda: rebuild(min_y - 12))
                        menu.addAction(prev_block)

                        for yy in range(min_y, max_y + 1):
                            act = QAction(str(yy), menu)
                            act.setCheckable(True)
                            act.setChecked(yy == cal.yearShown())
                            act.triggered.connect(lambda _=False, yy=yy: cal.setCurrentPage(yy, cal.monthShown()))
                            menu.addAction(act)

                        next_block = QAction("Позже ?", menu)
                        next_block.triggered.connect(lambda: rebuild(max_y + 12))
                        menu.addAction(next_block)

                    try:
                        menu.aboutToShow.connect(rebuild_fixed)
                    except Exception:
                        pass
                    year_btn.setMenu(menu)
                    year_btn.setPopupMode(QToolButton.InstantPopup)

                def _attach_month_menu(cal):
                    month_btn = cal.findChild(QToolButton, "qt_calendar_monthbutton")
                    if not month_btn:
                        return  # на некоторых версиях Qt тут может быть другой контрол
                    
                    menu = QMenu(month_btn)
                    
                    def rebuild_month_menu():
                        try:
                            menu.clear()
                            
                            # Добавляем поле для ручного ввода месяца в меню
                            input_container = QWidget(menu)
                            input_layout = QHBoxLayout(input_container)
                            input_layout.setContentsMargins(5, 5, 5, 5)
                            input_layout.setSpacing(5)
                            
                            month_input = QLineEdit(input_container)
                            month_input.setPlaceholderText("№ месяца (1-12)")
                            try:
                                current_month = cal.monthShown()
                                month_input.setText(str(current_month))
                            except Exception:
                                month_input.setText(str(QDate.currentDate().month()))
                            month_input.setMaximumWidth(100)
                            
                            apply_btn = QPushButton("ОК", input_container)
                            # Ширина по sizeHint, чтобы текст не срезался
                            try:
                                apply_btn.setMinimumWidth(apply_btn.sizeHint().width())
                            except Exception:
                                apply_btn.setMinimumWidth(56)
                            
                            def apply_month_input():
                                try:
                                    m = int(month_input.text())
                                    if 1 <= m <= 12:
                                        cal.setCurrentPage(cal.yearShown(), m)
                                        menu.close()
                                    else:
                                        month_input.setStyleSheet("border: 1px solid red")
                                        QTimer.singleShot(1000, lambda: month_input.setStyleSheet(""))
                                except ValueError:
                                    month_input.setStyleSheet("border: 1px solid red")
                                    QTimer.singleShot(1000, lambda: month_input.setStyleSheet(""))
                            
                            apply_btn.clicked.connect(apply_month_input)
                            month_input.returnPressed.connect(apply_month_input)
                            
                            input_layout.addWidget(month_input)
                            input_layout.addWidget(apply_btn)
                            
                            wa = QWidgetAction(menu)
                            wa.setDefaultWidget(input_container)
                            menu.addAction(wa)
                            
                            menu.addSeparator()
                            
                            # Список месяцев
                            month_names = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", 
                                          "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
                            
                            try:
                                current_month = cal.monthShown()
                            except Exception:
                                current_month = QDate.currentDate().month()
                                
                            for i, month_name in enumerate(month_names, 1):
                                act = QAction(f"{i}. {month_name}", menu)
                                act.setCheckable(True)
                                act.setChecked(i == current_month)
                                act.triggered.connect(lambda _=False, m=i: cal.setCurrentPage(cal.yearShown(), m))
                                menu.addAction(act)
                                
                        except Exception:
                            pass
                            
                    try:
                        menu.aboutToShow.connect(rebuild_month_menu)
                    except Exception:
                        pass
                        
                    month_btn.setMenu(menu)
                    month_btn.setPopupMode(QToolButton.InstantPopup)
                
                # привязать меню к обоим календарям
                for _cal in (cal1, cal2):
                    _attach_year_menu(_cal)
                    _attach_month_menu(_cal)


                # --- панель быстрых диапазонов и управления ---
                ctrl = QWidget(wrap)
                ctl = QHBoxLayout(ctrl); ctl.setContentsMargins(0,0,0,0); ctl.setSpacing(8)

                btn_today = QPushButton("Сегодня", ctrl)
                btn_week  = QPushButton("Неделя",  ctrl)
                btn_month = QPushButton("Месяц",   ctrl)
                btn_clear = QPushButton("Сбросить", ctrl)
                btn_apply = QPushButton("Применить", ctrl)

                # стиль как у вторичных кнопок (чтобы совпадало с "Настройки")
                for b in (btn_today, btn_week, btn_month, btn_clear, btn_apply):
                    b.setProperty("secondary", True)

                ctl.addWidget(QLabel("Диапазон:"))
                ctl.addWidget(btn_today)
                ctl.addWidget(btn_week)
                ctl.addWidget(btn_month)
                ctl.addStretch(1)
                ctl.addWidget(btn_clear)
                ctl.addWidget(btn_apply)
                vl.addWidget(ctrl)


                def _set_today():
                    d = QDate.currentDate()
                    cal1.setSelectedDate(d)
                    cal2.setSelectedDate(d)

                def _set_week():
                    today = QDate.currentDate()
                    start = today.addDays(-6)   # неделя назад включительно
                    cal1.setSelectedDate(start)
                    cal2.setSelectedDate(today)


                def _set_month():
                    # Align both calendars to the month that user is working with and select its full range
                    def _shown_year_month(cal_widget: QCalendarWidget) -> tuple[int, int]:
                        try:
                            return int(cal_widget.yearShown()), int(cal_widget.monthShown())
                        except Exception:
                            d_local = cal_widget.selectedDate()
                            return int(d_local.year()), int(d_local.month())

                    focus = QApplication.focusWidget()
                    if isinstance(focus, QCalendarWidget):
                        year, month = _shown_year_month(focus)
                    else:
                        year, month = _shown_year_month(cal2)

                    start = QDate(year, month, 1)
                    last_day = start.daysInMonth()
                    end = QDate(year, month, last_day)

                    for target in (cal1, cal2):
                        try:
                            target.setCurrentPage(year, month)
                        except Exception:
                            pass

                    cal1.setSelectedDate(start)
                    cal2.setSelectedDate(end)


                def _apply_dates():
                    d_from = cal1.selectedDate()
                    d_to   = cal2.selectedDate()
                    # нормализуем порядок
                    if d_to < d_from:
                        d_from, d_to = d_to, d_from
                    if title_l in {"создано","дата создания","created"}:
                        self._flt_created = (d_from, d_to)
                    else:
                        self._flt_modified = (d_from, d_to)
                    _apply_and_close()
                    try:
                        m.close()   # закрыть контекстное меню с календарём
                    except Exception:
                        pass


                def _clear_dates():
                    if title_l in {"создано","дата создания","created"}:
                        self._flt_created = (None, None)
                    else:
                        self._flt_modified = (None, None)
                    _apply_and_close()
                    try:
                        m.close()
                    except Exception:
                        pass


                btn_today.clicked.connect(_set_today)
                btn_week.clicked.connect(_set_week)
                btn_month.clicked.connect(_set_month)
                btn_apply.clicked.connect(_apply_dates)
                btn_clear.clicked.connect(_clear_dates)

                btn_today.clicked.connect(lambda: [cal1.setSelectedDate(QDate.currentDate()), cal2.setSelectedDate(QDate.currentDate())])
                btn_apply.clicked.connect(_apply_dates)
                btn_clear.clicked.connect(_clear_dates)

                wa = QWidgetAction(m); wa.setDefaultWidget(wrap); m.addAction(wa)

            else:
                # по умолчанию — простой текстовый фильтр, как было
        
                container = QWidget(m)
                le = QLineEdit(container); le.setPlaceholderText("введите текст...")
                le.setMinimumWidth(220)
                le.setText(self.column_text_filters.get(col, ""))
                wa = QWidgetAction(m); wa.setDefaultWidget(le); m.addAction(wa)
                le.textChanged.connect(lambda _t, c=col: [self.column_text_filters.__setitem__(c, le.text().strip()) if le.text().strip() else self.column_text_filters.pop(c, None), _apply_and_close()])

                m.addSeparator()
                act_clear = m.addAction("Сбросить фильтр")
                act_clear.triggered.connect(lambda: [self.column_text_filters.pop(col, None), _apply_and_close()])

            # показать меню
            try:
                m.exec(hdr.mapToGlobal(pos))
            except Exception:
                m.exec_(hdr.mapToGlobal(pos))
        except Exception:
            pass
                    # показать меню
            gpos = hdr.mapToGlobal(pos)
            self._menu_exec(m, gpos)   # helper уже есть в классе


    def _name_col_index(self) -> int:
        try:
            return next(
                i for i, h in enumerate(FilesTableModel.HEADERS)
                if str(h).strip().lower() in ("наименование", "название", "имя", "имя файла")
            )
        except StopIteration:
            return 1  # запасной вариант: второй столбец (после чекбоксов)

    def _update_name_search_icon(self):
        """Показывает/прячет иконку фильтра у «Наименование» на основе поля 'Поиск по имени'."""
        try:
            txt = (self.search.text() or "").strip()
            col = self._name_col_index()
            # у тебя уже должны быть эти хелперы из прошлого шага:
            lbl = self._header_filter_icon_label(col)      # создаёт/возвращает QLabel-иконку
            lbl.setVisible(bool(txt))
            self._header_filter_icons_repos()              # переставить иконку вправо от заголовка
        except Exception:
            pass


        # --- Выбор по чекбоксам ---
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
                QMessageBox.information(self, "Скачать выбранные",
                                        "Отметьте элементы галочками или выделите файл или папку.")
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
                mode = self._ask_mode("Скачать файл", "Сохранить файл", "Скачать как ZIP")
                if mode == "":
                    return
                if mode == "B":
                    self.download_file_as_zip(it)
                    return
                def_name = _sanitize_filename(it.get("originalName") or it.get("name") or f"file_{it.get('id')}.bin")
                save_path, _ = QFileDialog.getSaveFileName(self, "Сохранить как", def_name, "Все файлы (*.*)")
                if not save_path:
                    return
                _prev = getattr(self, "_force_mode", None); self._force_mode = "A"
                try:
                    local = self.ensure_downloaded(it)
                finally:
                    self._force_mode = _prev
                if not local:
                    QMessageBox.warning(self, "Скачать файл", "Не удалось скачать файл.")
                    return
                import shutil
                try:
                    shutil.copyfile(local, save_path)
                    QMessageBox.information(self, "Скачать файл", "Файл сохранён.")
                except Exception as e:
                    QMessageBox.warning(self, "Скачать файл", f"Не удалось сохранить: {e}")
                return

            mode = self._ask_mode("Скачать файлы", "Скачать файлы", "Скачать как ZIP")
            if mode == "":
                return
            if mode == "A":
                dest_dir = self._pick_directory_showing_files("Куда сохранить файлы")
                if not dest_dir:
                    return
                import shutil
                ok = 0
                self.progress.setVisible(True); self.progress.setRange(0, len(files)); self.progress.setValue(0); QApplication.processEvents()
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
                    self.progress.setVisible(False)
                QMessageBox.information(self, "Скачать файлы", f"Сохранено файлов: {ok}")
                return

            default = f"Файлы_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
            save_path, _ = QFileDialog.getSaveFileName(self, "Сохранить ZIP", default, "Все файлы (*.*);;ZIP (*.zip)")
            if not save_path:
                return
            self.progress.setVisible(True); self.progress.setRange(0, 0); QApplication.processEvents()
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
                QMessageBox.information(self, "Скачать как ZIP", "ZIP-архив сформирован.")
            except Exception as e:
                QMessageBox.warning(self, "Скачать как ZIP", f"Не удалось собрать архив: {e}")
            finally:
                self.progress.setVisible(False)
            return
        # только папки
        if folders and not files:
            mode = getattr(self, "_force_mode", None) or self._ask_mode("Скачать папку", "Скачать структуру", "Скачать как ZIP")
            if mode == "":
                return
            if mode == "A":
                dest_dir = self._pick_directory_showing_files("Куда сохранить папку")
                if not dest_dir:
                    return
                self.progress.setVisible(True); self.progress.setRange(0, len(folders)); self.progress.setValue(0); QApplication.processEvents()
                try:
                    for i, fd in enumerate(folders):
                        self.progress.setValue(i+1)
                        self._copy_folder_into(fd, dest_dir)  # без верхней «Выбранное_...»
                    QMessageBox.information(self, "Скачать структуру", "Копирование завершено.")
                finally:
                    self.progress.setVisible(False)
                return
            else:
                default = f"Папки_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
                save_path, _ = QFileDialog.getSaveFileName(self, "Сохранить ZIP", default, "Все файлы (*.*);;ZIP (*.zip)")
                if not save_path:
                    return
                self.progress.setVisible(True); self.progress.setRange(0, 0); QApplication.processEvents()
                try:
                    with zipfile.ZipFile(save_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                        for fd in folders:
                            self._zip_folder_into(fd, zf, arc_prefix="")
                    QMessageBox.information(self, "Скачать как ZIP", "ZIP-архив сформирован.")
                except Exception as e:
                    QMessageBox.warning(self, "Скачать как ZIP", f"Не удалось собрать архив: {e}")
                finally:
                    self.progress.setVisible(False)
                return

        # смешанный набор
        mode = getattr(self, "_force_mode", None) or self._ask_mode("Скачать выбранные", "Скачать структуру", "Скачать как ZIP")
        if mode == "":
            return

        if mode == "A":
            # Custom: pick destination folder with visible contents, then copy files and folders and return
            base_dir = self._pick_directory_showing_files("Куда сохранить")
            if not base_dir:
                return
            import shutil
            self.progress.setVisible(True); self.progress.setRange(0, len(items)); self.progress.setValue(0); QApplication.processEvents()
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
                QMessageBox.information(self, "Скачать структуру", "Копирование завершено.")
            finally:
                self.progress.setVisible(False)
            return
            # Предупреждения о дубликатах проверяются после выбора папки назначения
            base_dir = self._pick_directory_showing_files("Куда сохранить")
            if not base_dir:
                return
            import shutil
            self.progress.setVisible(True); self.progress.setRange(0, len(items)); self.progress.setValue(0); QApplication.processEvents()
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
                QMessageBox.information(self, "Скачать структуру", "Копирование завершено.")
            finally:
                self.progress.setVisible(False)
        else:
            default = f"Выбранное_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
            save_path, _ = QFileDialog.getSaveFileName(self, "Сохранить ZIP", default, "Все файлы (*.*);;ZIP (*.zip)")
            if not save_path:
                return
            self.progress.setVisible(True); self.progress.setRange(0, 0); QApplication.processEvents()
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
                QMessageBox.information(self, "Скачать как ZIP", "ZIP-архив сформирован.")
            except Exception as e:
                QMessageBox.warning(self, "Скачать как ZIP", f"Не удалось собрать архив: {e}")
            finally:
                self.progress.setVisible(False)

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
            text = "Скачать файл" if (len(files) == 1 and not folders) else "Скачать файлы"
            act_files = menu.addAction(text)
            act_files.setEnabled(bool(files) and not folders)
            act_files.triggered.connect(self.action_download_files)

            act_zip = menu.addAction("Скачать как ZIP")
            act_zip.setEnabled(bool(items))
            act_zip.triggered.connect(self.action_download_zip)

            act_folder = menu.addAction("Скачать структуру")
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
            dest_dir = self._pick_directory_showing_files("Куда сохранить файлы")
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
                    dlg.set_status(key, "none", "Файл с таким именем уже существует.")
                else:
                    dlg.set_status(key, "process", "В очереди на скачивание.")

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

                    dlg.set_status(task["key"], "process", "Скачивание…")
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
                        dlg.set_status(task["key"], "none", "Не удалось получить файл из хранилища.")
                    else:
                        target_path = os.path.join(dest_dir, task["target_name"])
                        # If source and destination are the same path, skip copy and treat as success
                        try:
                            same = os.path.normcase(os.path.abspath(local)) == os.path.normcase(os.path.abspath(target_path))
                        except Exception:
                            same = False
                        if same:
                            ok_count += 1
                            dlg.set_status(task["key"], "ok", "Файл уже существует")
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
                            dlg.set_status(task["key"], "ok", "Файл сохранён.")
                        except Exception as e:
                            errors.append(task["target_name"])
                            dlg.set_status(task["key"], "none", f"Ошибка копирования: {e}")

                    processed += 1
                    dlg.update_progress(processed, total)
                    QApplication.processEvents()

                if cancelled or dlg.was_cancelled():
                    self.status.showMessage("Скачивание отменено пользователем.", 5000)
                else:
                    if errors:
                        dlg.finish(f"Скачивание завершено частично: {ok_count} из {total}.")
                        dlg.exec()
                        self.status.showMessage(f"Скачано файлов: {ok_count} из {total}.", 6000)
                    else:
                        dlg.finish(f"Скачано файлов: {ok_count}.")
                        dlg.exec()
                        self.status.showMessage(f"Скачано файлов: {ok_count}.", 5000)
            finally:
                self._dl_busy = False
            return
        if len(files) == 1:
            it = files[0]
            def_name = _sanitize_filename(it.get("originalName") or it.get("name") or f"file_{it.get('id')}.bin")
            save_path, _ = QFileDialog.getSaveFileName(self, "Сохранить как", def_name, "Все файлы (*.*)")
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
                QMessageBox.warning(self, "Скачивание файла", "Не удалось скачать файл.")
                self._dl_busy = False
                return
            try:
                self.status.showMessage("Скачивание файла...")
                self.progress.setVisible(True)
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
                    QMessageBox.warning(self, "Скачивание файла", f"Не удалось сохранить файл: {e}")
            try:
                self.progress.setVisible(False)
                self.status.clearMessage()
            except Exception:
                pass
            if ok_msg:
                QMessageBox.information(self, "Скачивание завершено", "Скачано файлов: 1")
            self._dl_busy = False
            return

        QMessageBox.information(self, "Скачать файлы", "Нет выбранных файлов.")
        self._dl_busy = False
        return

    def action_download_zip(self):
        """Собирает ZIP из всего выбранного (файлы и/или папки) через диалог "Сохранить как".
        Исключает параллельное копирование отдельных файлов.
        """
        items = self._chosen_items_for_download()
        if not items:
            return
        default = f"Выбранное_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
        save_path, _ = QFileDialog.getSaveFileName(self, "Сохранить ZIP", default, "Все файлы (*.*);;ZIP (*.zip)")
        if not save_path:
            return
        self.progress.setVisible(True); self.progress.setRange(0, 0); QApplication.processEvents()
        wait = None
        try:
            wait = WaitDialog("Формирование ZIP...", self)
            try:
                wait.show(); QApplication.processEvents()
            except Exception:
                wait = None
        except Exception:
            wait = None
        try:
            with zipfile.ZipFile(save_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                used = set()
                for it in items:
                    t = (it or {}).get("type")
                    if t == "file":
                        fname = it.get("originalName") or it.get("name") or f"file_{it.get('id')}.bin"
                        arc = fname
                        if arc in used:
                            base, ext = os.path.splitext(fname); k = 1
                            while f"{base} ({k}){ext}" in used:
                                k += 1
                            arc = f"{base} ({k}){ext}"
                        used.add(arc)
                        try:
                            with zf.open(arc, 'w') as zentry:
                                self.api.write_file_to(it.get('id'), zentry)
                        except Exception:
                            pass
                    elif t == "folder":
                        self._zip_folder_into(it, zf, arc_prefix="")
            try:
                if wait:
                    wait.set_done("ZIP-архив сформирован.")
                else:
                    QMessageBox.information(self, "Скачать как ZIP", "ZIP-архив сформирован.")
            except Exception:
                pass
        except Exception as e:
            try:
                if wait:
                    wait.set_done("Ошибка при сборке ZIP")
                else:
                    QMessageBox.warning(self, "Скачать как ZIP", f"Не удалось собрать архив: {e}")
            except Exception:
                pass
        finally:
            self.progress.setVisible(False)

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

        # ----- ПРАВАЯ ТАБЛЦА: мышь + DnD -----
        table = getattr(self, "table", None)
        if table is not None and obj is table.viewport():
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
                paths = []
                if urls:
                    try:
                        paths = [Path(u.toLocalFile()) for u in urls if u.isLocalFile()]
                    except Exception:
                        paths = []

                if not paths:
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
                            QMessageBox.information(self, "Загрузка в корень", "В корень проекта можно переносить только папки.")
                        except Exception:
                            pass

                    if pid and dirs:
                        # спиннер
                        try:
                            self.status.showMessage("Загрузка в корень...")
                            self.progress.setVisible(True)
                            self.progress.setRange(0, 0)
                            QApplication.processEvents()
                        except Exception:
                            pass
                        try:
                            for d in dirs:
                                self._upload_dir_to_root(pid, d)
                        finally:
                            try:
                                self.progress.setVisible(False)
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
                    handler = getattr(self, "_handle_os_drop", None)
                    try:
                        if callable(handler):
                            handler(paths, target_node)
                        else:
                            self._upload_list_to_folder(target_node, paths)
                    except Exception:
                        pass

                ev.acceptProposedAction()
                self.table._hover_row = -1
                self.table.viewport().update()
                return True


            return False

        # по умолчанию - стандартная обработка
        return super().eventFilter(obj, ev)


    # --- Меню "Загрузить" и слоты ---

    def _build_upload_menu(self):
        m = QMenu("Загрузить", self)

        a_file = QAction("Загрузить файл", self)
        a_file.triggered.connect(self._action_upload_file)

        a_mkdir = QAction("Создать папку", self)
        a_mkdir.triggered.connect(self._action_create_folder)

        a_dir = QAction("Загрузить папку", self)
        a_dir.triggered.connect(self._action_upload_folder)

        # порядок как просил: файл > папка (создать) > папка (загрузить)
        m.addAction(a_file)
        m.addAction(a_mkdir)
        m.addAction(a_dir)
        return m

    def _action_upload_file(self):


        if self._is_root_open():  # корень открыт - запрет
            QMessageBox.information(self, "Загрузка в корень", "В корень проекта можно загружать только папки.")
            return

        node = self.current_folder_node()
        if not isinstance(node, dict) or str(node.get("type","")).lower() not in ("folder","dir","directory","папка"):
            QMessageBox.information(self, "Загрузка", "Сначала выберите папку справа.")
            return

        files, _ = QFileDialog.getOpenFileNames(self, "Выберите файлы")
        if not files:
            return

        paths = [Path(p) for p in files]
        # если есть готовый обработчик - используем его (со спиннером и рефрешем)
        handler = getattr(self, "_handle_os_drop", None)
        try:
            if callable(handler):
                handler(paths, node)
            else:
                self._upload_list_to_folder(node, paths)
        except Exception:
            pass

    def _action_create_folder(self):
        """Создать папку: в корне - в корень, иначе - в текущую папку."""

        name, ok = QInputDialog.getText(self, "Создать папку", "Имя папки:")
        if not ok or not (name or "").strip():
            return
        name = name.strip()
        pid = self.current_project_id()
        if not pid:
            QMessageBox.information(self, "Создать папку", "Не выбран проект.")
            return

        try:
            if self._is_root_open():
                # создать в КОРНЕ
                rid = self._ensure_subfolder(pid, None, name)
                if not rid:
                    QMessageBox.information(self, "Создать папку", "Не удалось создать папку в корне.")
            else:
                # создать внутри текущей папки
                node = self.current_folder_node()
                if not isinstance(node, dict):
                    QMessageBox.information(self, "Создать папку", "Не удалось определить текущую папку.")
                else:
                    self.api.create_folder(pid, node.get("id") or 0, name)
        finally:
            # мягкий рефреш
            try:
                self.soft_refresh_and_restore_view()
            except Exception:
                pass

    def _pick_directory_showing_files(self, title: str = "Выберите папку") -> str:
        try:
            try:
                start_dir = program_dir()
            except Exception:
                start_dir = os.path.expanduser("~")
            options = QFileDialog.Options()
            try:
                options |= QFileDialog.ShowDirsOnly
            except Exception:
                pass
            path = QFileDialog.getExistingDirectory(self, title, start_dir, options)
            return path or ""
        except Exception:
            try:
                return QFileDialog.getExistingDirectory(self, title) or ""
            except Exception:
                return ""

    def _pick_directory_native(self, title: str) -> str:
        try:
            start_dir = program_dir()
        except Exception:
            start_dir = os.getcwd()
        try:
            dir_path = QFileDialog.getExistingDirectory(self, title, start_dir)
            return dir_path or ""
        except Exception:
            return ""

    def _action_upload_folder(self):
        """Загрузка папки со структурой: в корне - в корень, иначе - в текущую папку."""

        dir_path = self._pick_directory_showing_files("Выберите папку")
        if not dir_path:
            return
        p = Path(dir_path)
        if not p.exists() or not p.is_dir():
            QMessageBox.information(self, "Загрузка папки", "Некорректная папка.")
            return

        pid = self.current_project_id()
        if not pid:
            QMessageBox.information(self, "Загрузка папки", "Не выбран проект.")
            return

        if self._is_root_open():
            base_id = self._ensure_subfolder(pid, None, p.name)
            if not base_id:
                QMessageBox.information(self, "Загрузка папки", "Не удалось создать папку в корне проекта.")
                return
            target = {"id": base_id, "name": p.name, "type": "folder"}
            children = list(p.iterdir())
            self._upload_list_to_folder(target, children, display_prefix=(p.name,))
        else:
            node = self.current_folder_node()
            if not isinstance(node, dict):
                QMessageBox.information(self, "Загрузка папки", "Не удалось определить текущую папку.")
                return
            self._upload_list_to_folder(node, [p])


    def _update_upload_menu_visibility(self):
        is_root = self._is_root_open()
        # в корне прячем пункт "Загрузить файл"
        self.act_upload_file.setVisible(not is_root)

    # CRUD действия
    def current_folder_node(self) -> dict:
        return self.current_path_nodes[-1] if self.current_path_nodes else {}
    
    def _get_item_relative_path(self, item: dict) -> str:
        """Получить относительный путь элемента от корня синхронизируемой папки.
        
        Args:
            item: Элемент из дерева (файл или папка)
        
        Returns:
            Относительный путь вида "folder1/folder2/file.txt" или "" если не удалось определить
        """
        try:
            # Собираем путь из текущих узлов дерева
            path_parts = []
            
            # Добавляем все промежуточные папки из current_path_nodes (кроме корневой)
            for node in self.current_path_nodes[1:]:  # Пропускаем корневую папку проекта
                name = node.get("name") or node.get("title") or ""
                if name:
                    path_parts.append(name)
            
            # Добавляем имя самого элемента
            item_name = item.get("name") or item.get("title") or item.get("originalName") or ""
            if item_name:
                path_parts.append(item_name)
            
            # Собираем в путь с разделителем /
            return "/".join(path_parts)
        except Exception:
            return ""
    
    def _find_col(self, title: str) -> int:
        """Найти индекс колонки по её заголовку."""
        m = self.table.model()
        if not m:
            return -1
        for i in range(m.columnCount()):
            t = (m.headerData(i, Qt.Horizontal, Qt.DisplayRole) or "").strip().lower()
            if t == title.strip().lower():
                return i
        return -1

    def _tune_columns(self):
        """Подогнать ширины всех колонок по содержимому.
        'Название' — по самому длинному; если не влезает — появится горизонтальный скролл."""
        view = self.table
        hh = view.horizontalHeader()

        # ничего не растягиваем под окно
        # Do not stretch last section: we'll distribute extra space across columns evenly
        hh.setStretchLastSection(False)
        hh.setMinimumSectionSize(20)
        hh.setHighlightSections(False)
        hh.setCascadingSectionResizes(True)

        # 1) временно измеряем по содержимому
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        view.resizeColumnsToContents()
        
        # ВАЖНО: восстанавливаем фиксированный размер первого столбца после resizeColumnsToContents
        if hh.count() > 0:
            hh.setSectionResizeMode(0, QHeaderView.Fixed)
            hh.resizeSection(0, CHECKBOX_COLUMN_WIDTH)

        # 2) фиксируем результат и даём пользователю возможность вручную тянуть
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(False)

        # 3) колонка с чекбоксами — фиксированная узкая (повторно для надежности)
        if hh.count() > 0:
            hh.setSectionResizeMode(0, QHeaderView.Fixed)
            hh.resizeSection(0, CHECKBOX_COLUMN_WIDTH)

        # плавный горизонтальный скролл
        view.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)

        # Подгон: сначала по содержимому, затем заполняем остаток ширины
        try:
            self._fill_table_width_to_viewport()
        except Exception:
            pass

    def _fill_table_width_to_viewport(self):
        """Расширить последний видимый столбец, чтобы заполнить правый край,
        сохраняя исходные ширины по содержимому для остальных."""
        try:
            view = self.table
            if not view:
                return
            hh = view.horizontalHeader()
            if not hh or hh.count() <= 0:
                return
            # Текущая суммарная ширина
            total = 0
            last_visible = None
            for i in range(hh.count()):
                if not view.isColumnHidden(i):
                    total += hh.sectionSize(i)
                    last_visible = i
            if last_visible is None:
                return
            viewport_w = view.viewport().width()
            extra = int(viewport_w - total)
            if extra > 0:
                try:
                    view.resizeColumnsToContents()
                    # ВАЖНО: восстанавливаем фиксированный размер первого столбца
                    if hh.count() > 0:
                        hh.setSectionResizeMode(0, QHeaderView.Fixed)
                        hh.resizeSection(0, CHECKBOX_COLUMN_WIDTH)
                except Exception:
                    pass
                # Пересчет после подгонки по содержимому
                total = 0
                last_visible = None
                for i in range(hh.count()):
                    if not view.isColumnHidden(i):
                        total += hh.sectionSize(i)
                        last_visible = i
                viewport_w = view.viewport().width()
                extra = int(viewport_w - total)
            if extra > 0:
                # Равномерно распределить лишнюю ширину между видимыми столбцами,
                # не затрагивая первый (иконка/чекбокс). Текст не урезаем, т.к. базу задали через resizeColumnsToContents.
                visible_cols = [i for i in range(hh.count()) if not view.isColumnHidden(i)]
                grow_cols = [i for i in visible_cols if i != 0] or visible_cols  # если остался только 0-й — растянем его
                if len(grow_cols) == 1:
                    i = grow_cols[0]
                    hh.resizeSection(i, max(hh.sectionSize(i) + extra, hh.minimumSectionSize()))
                else:
                    add_each = max(0, extra // len(grow_cols))
                    rem = max(0, extra - add_each * len(grow_cols))
                    for idx, i in enumerate(grow_cols):
                        inc = add_each + (1 if idx < rem else 0)
                        if inc > 0:
                            hh.resizeSection(i, max(hh.sectionSize(i) + inc, hh.minimumSectionSize()))
        except Exception:
            pass

    def _resize_columns_to_contents_and_fill(self):
        try:
            view = self.table
            if not view:
                return
            hh = view.horizontalHeader()
            if not hh:
                return
            view.resizeColumnsToContents()
            # Первый столбец (иконка/чекбокс) фиксированный
            try:
                if hh.count() > 0:
                    hh.setSectionResizeMode(0, QHeaderView.Fixed)
                    hh.resizeSection(0, CHECKBOX_COLUMN_WIDTH)
            except Exception:
                pass
            self._fill_table_width_to_viewport()
        except Exception:
            pass

    def create_new_folder(self):
        parent = self.current_folder_node()
        if not self.current_project_id():
                QMessageBox.information(self, "Новая папка", "Сначала выберите проект."); return
        if not parent or parent.get("type") != "folder":
                parent = {} # Create in root
        name, ok = QInputDialog.getText(self, "Новая папка", "Имя папки:")
        if not ok or not name.strip(): return
        pid = self.current_project_id(); parent_id = parent.get("id")
        if self.api.create_folder(pid, parent_id, name.strip()):
            QMessageBox.information(self, "Новая папка", "Папка создана.")
            self.soft_refresh_and_restore_view()
        else:
            QMessageBox.warning(self, "Новая папка", "Не удалось создать папку.")
    def _find_node_by_id_in_tree(self, nodes, fid: int):
        for n in nodes or []:
            if not isinstance(n, dict): 
                continue
            if normalize_id(n.get("id")) == normalize_id(fid):
                return n
            if n.get("type") == "folder":
                got = self._find_node_by_id_in_tree(n.get("children") or [], fid)
                if got: 
                    return got
        return None

    def _child_folder_id_by_name(self, project_tree: list, parent_id: int | None, name: str) -> int | None:
            if not name:
                return None

            # получить детей нужного узла
            if not parent_id:
                children = project_tree
            else:
                parent = self._find_node_by_id_in_tree(project_tree, parent_id)
                children = (parent or {}).get("children") or []

            low = name.strip().lower()
            for ch in children:
                if not isinstance(ch, dict):
                    continue
                ch_type = ch.get("type")
                is_folder = (str(ch_type).lower() == "folder") or (ch_type in (0, 1))
                if not is_folder:
                    continue

                title = (ch.get("name") or ch.get("title") or ch.get("folderName") or "").strip()
                if title.lower() == low:
                    try:
                        raw_fid = ch.get("id")
                        try:
                            return int(raw_fid)
                        except (ValueError, TypeError):
                            return raw_fid
                    except Exception:
                        return None
            return None

    def _collect_cloud_dirs(self, folder_node: dict, rel_path: str = "") -> list[str]:
        """Собирает ОТНОСИТЕЛЬНЫЕ пути папок в облаке (включая пустые)."""
        out = set()
        def walk(node: dict, rel: str):
            try:
                children = (node.get("children") or node.get("folders") or node.get("items") or node.get("documents") or node.get("content"))
                # Fallback: если children пусты/не список, пробуем folders/files
                if (not isinstance(children, list)) or (not children):
                    children = node.get("folders") or node.get("files") or []
                if not isinstance(children, list):
                    # если метаданные не обогащены - подтянем детали папки
                    try:
                        raw_fid = node.get("id") or node.get("folderId") or 0
                        try:
                            fid = int(raw_fid)
                        except (ValueError, TypeError):
                            fid = raw_fid
                        det = self.api.get_folder_details(fid, force=True)
                        if isinstance(det, dict):
                            children = (det.get("children") or det.get("folders") or det.get("items") or det.get("documents") or det.get("content"))
                            # Fallback: если список детей не получился, взять folders/files
                            if (not isinstance(children, list)) or (not children):
                                children = det.get("folders") or det.get("files") or []
                    except Exception:
                        children = None
                if isinstance(children, list):
                    for ch in children:
                        if not isinstance(ch, dict):
                            continue
                        ctype = str(ch.get("type") or "").lower()
                        is_folder = (
                            ctype == "folder"
                            or bool(ch.get("hasFolders"))
                            or any(isinstance(ch.get(k), list) for k in ("children", "folders", "items", "documents", "content"))
                            or (not any(k in ch for k in ("fileUid", "fileName", "originalName")) and (ch.get("title") or ch.get("folderName") or ch.get("name")))
                        )
                        if is_folder:
                            name = get_title(ch)
                            sub_rel = "/".join([p for p in [rel.strip("/"), name] if p])
                            if sub_rel:
                                out.add(sub_rel)
                            walk(ch, sub_rel)
            except Exception:
                pass
        walk(folder_node or {}, str(rel_path or ""))
        return sorted(out)

    def _ensure_cloud_path(self, project_id: int | str, root_folder_id: int | str, rel_path: str) -> int | str | None:
        """Гарантирует, что цепочка папок rel_path есть в облаке под root_folder_id."""
        fid = normalize_id(root_folder_id)
        for seg in [s for s in rel_path.replace("\\", "/").split("/") if s]:
            try:
                fid_int = int(fid)
            except (ValueError, TypeError):
                fid_int = fid
            fid = self._ensure_subfolder(int(project_id), fid_int, seg)
            if not fid:
                return None
        return fid

    def _ensure_subfolder(self, project_id: int | str, parent_folder_id: int | str | None, name: str) -> int | str | None:
        """Создаёт подпапку при отсутствии и возвращает её id, с коротким ретраем чтения дерева."""



        if not name or not project_id:
            return None

        # 1) попробовать найти сразу
        try:
            self.api.cache.pop(f"tree:{project_id}", None)
        except Exception:
            pass
        tree = self.api.list_folders(project_id) or []
        fid = self._child_folder_id_by_name(tree, parent_folder_id, name)
        if fid:
            return fid

        # 2) создать
        created = self.api.create_folder(project_id, parent_folder_id or 0, name.strip())
        if not created:
            return None  # создание не удалось

        # Если API вернул id, используем его напрямую
        if isinstance(created, (int, str)) and created not in (True, False, 0, ""):
            return normalize_id(created)

        # 3) дождаться появления в дереве
        for _ in range(15):  # ~1.5 сек
            try:
                self.api.cache.pop(f"tree:{project_id}", None)
            except Exception:
                pass
            tree = self.api.list_folders(project_id) or []
            fid = self._child_folder_id_by_name(tree, parent_folder_id, name)
            if fid:
                return fid
            QApplication.processEvents()
            time.sleep(0.1)

        return None  # лучше вернуть None, чем ошибочно класть в родителя


    def rename_selected_action(self):
        item = self.selected_item()
        if not item:
            checked = self.get_checked_visible_items()
            if len(checked) == 1:
                item = checked[0]
        if not item:
            QMessageBox.information(self, "Переименование", "Выберите элемент или отметьте один галочкой.")
            return
        new_name, ok = QInputDialog.getText(self, "Переименование", "Новое имя:", text=item.get("originalName") or item.get("name") or "")
        if not ok or not new_name.strip(): return
        if item.get("type") == "folder":
            pid = self.current_project_id(); parent_id = self.current_folder_node().get("id") or 0
            if self.api.update_folder(item.get("id"), pid, new_name.strip(), parent_id):
                # Log user action for notification filtering
                try:
                    self._log_user_action("rename", file_id=item.get("id"), file_name=new_name.strip(), folder_id=parent_id)
                except Exception:
                    pass
                self.soft_refresh_and_restore_view(); QMessageBox.information(self, "Переименование", "Папка переименована.")
            else:
                QMessageBox.warning(self, "Переименование", "Не удалось переименовать папку.")
        else:
            if self.api.rename_document(item.get("id"), new_name.strip()):
                # Log user action for notification filtering
                try:
                    folder_id = self.current_folder_node().get("id") if self.current_folder_node() else None
                    self._log_user_action("rename", file_id=item.get("id"), file_name=new_name.strip(), folder_id=folder_id)
                except Exception:
                    pass
                self.soft_refresh_and_restore_view(); QMessageBox.information(self, "Переименование", "Файл переименован.")
            else:
                QMessageBox.warning(self, "Переименование", "Не удалось переименовать файл.")
    def delete_checked(self):
        """
        Немедленное удаление выбранных элементов из облака:
        - если есть отмеченные галочками элементы – удаляем их;
        - если галочек нет – удаляем одиночный выделенный элемент (ЛКМ);
        - если ничего не выбрано – показываем подсказку.
        """
        # 1) Пытаемся взять отмеченные
        try:
            items = self.get_checked_visible_items()
        except Exception:
            items = []

        # 2) Если галочек нет – берем одиночное выделение
        if not items:
            sel = self.selected_item()
            if not sel:
                QMessageBox.information(self, "Удаление", "Отметьте элементы галочками или выделите один элемент.")
                return
            items = [sel]

        # Подсчет типов и подтверждение
        n_files = sum(1 for it in items if it.get("type") == "file")
        n_folds = sum(1 for it in items if it.get("type") == "folder")
        parts = []
        if n_folds: parts.append(f"папок: {n_folds}")
        if n_files: parts.append(f"файлов: {n_files}")
        caption = "Будет удалено " + (", ".join(parts) if parts else "выбранное") + "."
        if QMessageBox.question(self, "Удаление", caption, QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                return

        # Выполнение: прямое удаление через API и локально (если в синхронизируемой папке)
        ok_files = ok_folds = 0
        folder_id = self.current_folder_node().get("id") if self.current_folder_node() else None
        
        # Получаем путь синхронизации для текущей папки
        sync_path = None
        try:
            if hasattr(self, 'sync2') and folder_id:
                sync_path = self.sync2.get_sync_path(folder_id)
        except Exception:
            pass
        
        for it in items:
            try:
                if it.get("type") == "folder":
                    # Прямое удаление папки из облака
                    if self.api.delete_folder(it.get("id")): 
                        ok_folds += 1
                        
                        # Удаляем локальную папку, если настроена синхронизация
                        if sync_path:
                            try:
                                # Получаем относительный путь от корня дерева до этой папки
                                rel_path = self._get_item_relative_path(it)
                                if rel_path:
                                    local_folder = os.path.join(sync_path, rel_path.replace("/", os.sep))
                                    if os.path.exists(local_folder) and os.path.isdir(local_folder):
                                        import shutil
                                        shutil.rmtree(local_folder)
                                        sync_log("Локальная папка удалена: {}", local_folder)
                            except Exception as e:
                                sync_log("Ошибка удаления локальной папки: {}", str(e))
                else:
                    # Прямое удаление файла из облака
                    if self.api.delete_document(it.get("id")): 
                        ok_files += 1
                        
                        # Удаляем локальный файл, если настроена синхронизация
                        if sync_path:
                            try:
                                # Получаем относительный путь от корня дерева до этого файла
                                rel_path = self._get_item_relative_path(it)
                                if rel_path:
                                    local_file = os.path.join(sync_path, rel_path.replace("/", os.sep))
                                    if os.path.exists(local_file) and os.path.isfile(local_file):
                                        os.remove(local_file)
                                        sync_log("Локальный файл удалён: {}", local_file)
                            except Exception as e:
                                sync_log("Ошибка удаления локального файла: {}", str(e))
                        
                        # Log user action for notification filtering
                        try:
                            self._log_user_action("delete", file_id=it.get("id"), 
                                                file_name=it.get("originalName") or it.get("name") or "", 
                                                folder_id=folder_id)
                        except Exception:
                            pass
            except Exception:
                pass

        # Сбрасываем галочки и обновляем вид
        try:
            self.checked.clear()
        except Exception:
            pass
        self.soft_refresh_and_restore_view()

        # Информируем пользователя
        msg_parts = []
        if ok_files > 0: msg_parts.append(f"файлов удалено: {ok_files}")
        if ok_folds > 0: msg_parts.append(f"папок удалено: {ok_folds}")
        
        QMessageBox.information(self, "Удаление", 
            "\n".join(msg_parts) if msg_parts else "Операция завершена.")

    def delete_selected_action(self):
        """
        Немедленное удаление выделенного элемента из облака через API.
        """
        item = self.selected_item()
        if not item:
            QMessageBox.information(self, "Удаление", "Выберите папку или файл.")
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
                "Удаление папки", 
                "Удалить папку и ее содержимое?", 
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
                QMessageBox.information(self, "Удаление", "Папка удалена.")
            else: 
                QMessageBox.warning(self, "Удаление", "Не удалось удалить папку.")
        else:
            if QMessageBox.question(
                self, 
                "Удаление файла", 
                "Удалить файл?", 
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
                
                # Удаляем локальный файл, если настроена синхронизация
                if sync_path:
                    try:
                        rel_path = self._get_item_relative_path(item)
                        if rel_path:
                            local_file = os.path.join(sync_path, rel_path.replace("/", os.sep))
                            if os.path.exists(local_file) and os.path.isfile(local_file):
                                os.remove(local_file)
                                sync_log("Локальный файл удалён: {}", local_file)
                    except Exception as e:
                        sync_log("Ошибка удаления локального файла: {}", str(e))
                
                self.soft_refresh_and_restore_view()
                QMessageBox.information(self, "Удаление", "Файл удален.")
            else: 
                QMessageBox.warning(self, "Удаление", "Не удалось удалить файл.")

    def show_details_for_selected(self):
        item = self.selected_item()
        if not item or item.get("type") != "file":
            QMessageBox.information(self, "Свойства", "Выберите файл для просмотра свойств."); return
        doc_id = item.get("id")
        if not doc_id: return
        self.status.showMessage("Загрузка информации о файле")
        details = self.api.get_document_details(doc_id)
        self.status.clearMessage()
        if not details:
            QMessageBox.warning(self, "Свойства", "Не удалось получить детальную информацию о файле."); return
        dlg = FileDetailsDialog(details, self)
        dlg.exec()

    def _show_versions_for_node(self, node: dict):
        """Открыть диалог со списком версий выбранного файла."""
        try:
            if not isinstance(node, dict) or str(node.get("type", "")).lower() != "file":
                QMessageBox.information(self, "Версии", "Выберите файл."); 
                return
            doc_id = node.get("id")
            if not doc_id:
                QMessageBox.information(self, "Версии", "ID файла не определен."); 
                return

            name = node.get("originalName") or node.get("name") or f"Документ {doc_id}"
            self.status.showMessage("Загрузка версий...")
            versions = self.api.get_document_versions(doc_id)
            self.status.clearMessage()
            # Нормализуем ответ: поддержка dict {'file_name','versions'} и простого list
            base_file_name = name
            if isinstance(versions, dict):
                base_file_name = versions.get("file_name") or versions.get("fileName") or name
                versions = list(versions.get("versions") or [])
            else:
                versions = list(versions or [])

            if not versions:
                QMessageBox.information(self, "Версии", "Версии не найдены.")
                return

            dlg = QDialog(self)
            dlg.setWindowTitle(f"Версии - {name}")
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
                    extra = " · ".join([t for t in [when, str(who) if who else "", f"{size} байт" if size else ""] if t])
                    text = f"Версия {ver_no}" + (f" - {extra}" if extra else "")
                    lst.addItem(text)
                except Exception:
                    lst.addItem(f"Версия {i}")
            lay.addWidget(lst)
            # Разрешим мультивыбор для сравнения
            lst.setSelectionMode(QAbstractItemView.ExtendedSelection)

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

                self.progress.setVisible(True)
                self.progress.setRange(0, 0)
                QApplication.processEvents()
                wait = WaitDialog("Дождитесь скачивания версии", self)
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
                    self.progress.setVisible(False)
                    try:
                        wait.set_done("Скачивание версии завершено")
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
                    QMessageBox.warning(dlg, "Открыть версию", "Не удалось скачать файл версии.")

            def _compare_selected_pdf():
                dlg.accept()
                QtCore.QTimer.singleShot(100, lambda: self._show_compare_versions_for_node(node))

            # Двойной клик по версии - открыть локально
            lst.itemDoubleClicked.connect(lambda _itm: _open_selected_local())

            btns = QDialogButtonBox(QDialogButtonBox.Close, parent=dlg)
            btns.rejected.connect(dlg.reject)
            btns.accepted.connect(dlg.accept)
            lay.addWidget(btns)

            btn_open_pc = QPushButton("Открыть на ПК", dlg)
            btn_open_pc.clicked.connect(_open_selected_local)
            btns.addButton(btn_open_pc, QDialogButtonBox.ActionRole)

            if name.lower().endswith('.pdf'):
                btn_compare = QPushButton("Сравнить 2 версии (PDF)", dlg)
                btn_compare.clicked.connect(_compare_selected_pdf)
                btns.addButton(btn_compare, QDialogButtonBox.ActionRole)

            dlg.resize(400, 380)
            dlg.exec()
        except Exception:
            QMessageBox.warning(self, "Версии", "Не удалось открыть список версий.")


    def _has_at_least_two_versions(self, node: dict) -> bool:
        """True, если у файла есть минимум 2 версии."""
        try:
            if not isinstance(node, dict) or str(node.get("type", "")).lower() != "file":
                return False
            doc_id = node.get("id")
            if not doc_id:
                return False
            self.status.showMessage("Проверка версий...")
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
            QMessageBox.information(self, "Сравнение", "Выберите файл.")
            return
        self._show_compare_versions_for_node(target)


    def _show_compare_versions_for_node(self, node: dict):
        """Диалог: слева версия 1, справа версия 2, внизу - Сравнить/Отмена."""
        if not isinstance(node, dict) or str(node.get("type", "")).lower() != "file":
            QMessageBox.information(self, "Сравнение", "Выберите файл."); 
            return

        doc_id = node.get("id")
        name   = node.get("fileName") or node.get("name") or node.get("title") or "файл"
        if not doc_id:
            QMessageBox.information(self, "Сравнение", "ID файла не определен.")
            return

        # 1) получаем версии и нормализуем список
        self.status.showMessage("Загрузка версий...")
        versions = self.api.get_document_versions(doc_id)
        self.status.clearMessage()

        base_file_name = name
        if isinstance(versions, dict):
            base_file_name = versions.get("file_name") or versions.get("fileName") or name
            versions = list(versions.get("versions") or [])
        else:
            versions = list(versions or [])

        if len(versions) < 2:
            QMessageBox.information(self, "Сравнение", "Нужно минимум две версии для сравнения.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Сравнение версий - {name}")
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

        left_w,  lst1 = _make_side("Выберите версию 1")
        right_w, lst2 = _make_side("Выберите версию 2")
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
                }
                QListWidget::item:selected {
                    background: #FFC37A;
                }
            """)
            _lst.setViewportMargins(4, 4, 4, 4)


        # наполнение обоих списков одинаковыми элементами
        def _add_items(lst_widget: QListWidget):
            for i, v in enumerate(versions, 1):
                try:
                    ver_no = v.get("version") or v.get("versionNumber") or v.get("versionId") or i
                    when_raw = v.get("createTime") or v.get("createdAt") or v.get("modifTime") or v.get("updatedAt") or v.get("created_ts") or v.get("createdTs")
                    when = ""
                    if when_raw:
                        ts = parse_date_like(str(when_raw))
                        if ts > 0:
                            when = _user_display_datetime(ts)
                    who  = v.get("createdBy") or v.get("modifiedBy") or ""
                    size = v.get("size") or v.get("fileSize") or 0
                    size_text = human_readable_size(size) if callable(globals().get("human_readable_size", None)) else str(size)
                    label = f"v{ver_no}  {when}  {who}  {size_text}".strip()
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
        btn_compare = QPushButton("Сравнить", dlg)
        btn_cancel  = QPushButton("Отмена", dlg)
        btn_compare.setEnabled(False)
        btn_compare.setProperty("chip", False)
        btn_compare.setProperty("secondary", True)
        btn_cancel.setProperty("chip", False)
        btn_cancel.setProperty("secondary", True)
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

            self.progress.setVisible(True)
            self.progress.setRange(0, 0)
            QApplication.processEvents()
            wait = WaitDialog("Дождитесь скачивания версии", self)
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
                self.progress.setVisible(False)
                try:
                    if wait:
                        wait.set_done("Скачивание версии завершено")
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
            wait = WaitDialog("Скачивание 2 версий...", self)
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
                    wait.set_done("Готово")
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
                QMessageBox.warning(dlg, "Сравнение", "Не удалось скачать одну из версий.")
                return
            extA = os.path.splitext(pathA)[1].lower()
            extB = os.path.splitext(pathB)[1].lower()
            if extA != ".pdf" or extB != ".pdf":
                QMessageBox.information(dlg, "Сравнение", "Сравнение поддерживается для PDF. Открою обе версии.")
                open_in_os(pathA); open_in_os(pathB)
                return
            # Use integrated PDF_Compare window
            self.open_pdf_compare_window(pathA, pathB)
            dlg.accept()

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
            QMessageBox.warning(
                self, 
                "PDF Сравнение", 
                "Модуль PDF_Compare не доступен. Убедитесь, что файл PDF_Compare.py находится в той же папке."
            )
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
                idx = pdf_win.cmb_mode.findText("Сравнение")
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
            QMessageBox.critical(
                self, 
                "Ошибка", 
                f"Не удалось открыть окно сравнения PDF:\n{str(e)}"
            )

    def show_folder_details(self, folder_obj: dict):
        fid = folder_obj.get("id")
        if not fid:
            QMessageBox.information(self, "Свойства папки", "ID папки не определен."); return
        self.status.showMessage("Загрузка информации о папке")
        details = self.api.get_folder_details(fid)
        self.status.clearMessage()
        if not details:
            QMessageBox.warning(self, "Свойства папки", "Не удалось получить информацию о папке."); return
        dlg = FolderDetailsDialog(details, self)
        dlg.exec()

    # Upload / Download / Open
    def selected_item(self) -> dict:
        sel = self.table.selectionModel().selectedRows()
        if not sel: return {}
        row = self.proxy.mapToSource(sel[0]).row()
        return self.files_model.item_at(row)

    def ensure_downloaded(self, item: dict) -> str:
        if not item or item.get("type") != "file": return ""
        file_id = item.get("id")
        name = item.get("originalName") or item.get("name") or f"file_{file_id}.bin"
        # Проверка дубликатов и выбор действия
        safe = _sanitize_filename(name)
        try:
            os.makedirs(DOWNLOAD_DIR, exist_ok=True)
            existing = os.path.join(DOWNLOAD_DIR, safe)
            if os.path.exists(existing):
                mode = self._ask_mode(
                    title=f"Файл уже существует:\n{safe}",
                    a_text="Заменить",
                    b_text="Создать копию",
                )
                if mode == "B":
                    safe = self._unique_name(DOWNLOAD_DIR, safe)
                elif mode == "":
                    return ""
        except Exception:
            pass

        # по умолчанию — «занято»
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        QApplication.processEvents()
        wait = WaitDialog("Дождитесь скачивания", self)
        wait.show(); QApplication.processEvents()

        # попробуем проценты, если сервер дал Content-Length
        def _cb(done, total):
            # переключаемся на детерминированный бар и обновляем
            self.progress.setRange(0, 100)
            self.progress.setValue(int(done * 100 / max(1, total)))
            QApplication.processEvents()

        local_path = self.api.download_file(file_id, safe, progress_cb=_cb)
        self.progress.setVisible(False)
        try:
            wait.set_done("Скачивание завершено")
        except Exception:
            pass
        return local_path or ""
    def _copy_file_with_progress(self, src: str, dst: str, on_bytes) -> None:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(src, "rb") as fin, open(dst, "wb") as fout:
            while True:
                buf = fin.read(256 * 1024)  # 256К
                if not buf:
                    break
                fout.write(buf)
                on_bytes(len(buf))

    def _unique_name(self, dest_dir: str, name: str) -> str:
        """Подбирает уникальное имя (file.txt > file (copy).txt), если уже занято."""
        base, ext = os.path.splitext(name)
        base = (base or "").strip()
        if not base:
            base = name.strip()
            ext = ""
        if not base:
            base = "file"
        
        # Сначала проверяем, существует ли исходное имя
        if not os.path.exists(os.path.join(dest_dir, name)):
            return name
        
        # Если имя занято, добавляем "(copy)"
        candidate = f"{base} (copy){ext}"
        idx = 2
        while os.path.exists(os.path.join(dest_dir, candidate)):
            candidate = f"{base} (copy {idx}){ext}"
            idx += 1
        return candidate

    def _check_file_conflicts(self, target_folder_id: int | str, filenames: list[str]) -> dict[str, bool]:
        """Проверяет конфликты имен файлов на сервере в указанной папке.
        
        Args:
            target_folder_id: ID целевой папки на сервере
            filenames: Список имен файлов для проверки
            
        Returns:
            Словарь {filename: has_conflict}
        """
        conflicts = {}
        
        try:
            # Получаем список существующих файлов в папке на сервере
            existing_names = self._existing_names_for_folder(target_folder_id)
        except Exception:
            # При ошибке считаем, что конфликтов нет
            return {name: False for name in filenames}
        
        # Проверяем каждый файл на конфликт (всегда регистронезависимо для сервера)
        for name in filenames:
            conflicts[name] = name.casefold() in existing_names
        
        return conflicts

    def _unique_name_for_batch(self, target_dir: str, name: str, used_names: set[str]) -> str:
        """Создает уникальное имя для файла с учетом уже занятых имен в батче.
        Формат: name (copy).ext, name (2).ext, name (3).ext и т.д.
        
        Args:
            target_dir: Целевая директория
            name: Исходное имя файла
            used_names: Множество уже использованных имен в батче
            
        Returns:
            Уникальное имя файла
        """
        base, ext = os.path.splitext(name)
        base = (base or "").strip()
        if not base:
            base = name.strip()
            ext = ""
        if not base:
            base = "file"
        
        # Функция для проверки существования файла (учитывает регистр платформы)
        def file_exists(filename: str) -> bool:
            if os.name == 'nt':  # Windows - регистронезависимо
                return filename.lower() in used_names or os.path.exists(os.path.join(target_dir, filename))
            else:  # POSIX - регистрозависимо
                return filename in used_names or os.path.exists(os.path.join(target_dir, filename))
        
        # Сначала пробуем name (copy).ext
        candidate = f"{base} (copy){ext}"
        if not file_exists(candidate):
            return candidate
        
        # Затем name (2).ext, name (3).ext и т.д.
        idx = 2
        while True:
            candidate = f"{base} ({idx}){ext}"
            if not file_exists(candidate):
                return candidate
            idx += 1
    def _prompt_conflict_in_status(self, dest_dir: str, filename: str) -> str:
        """Inline conflict prompt in the status bar.
        Returns: 'replace' | 'copy' | 'cancel'.
        """
        try:
            frm = QFrame(self)
            lay = QHBoxLayout(frm); lay.setContentsMargins(8, 2, 8, 2); lay.setSpacing(6)
            lbl = QLabel(f"Файл уже существует: {filename}", frm)
            btn_replace = QPushButton("Заменить", frm)
            btn_copy = QPushButton("Создать копию", frm)
            btn_cancel = QPushButton("Отмена", frm)
            for b in (btn_replace, btn_copy, btn_cancel):
                b.setProperty("chip", True)
            lay.addWidget(lbl)
            lay.addWidget(btn_replace)
            lay.addWidget(btn_copy)
            lay.addWidget(btn_cancel)
            result = {"val": "cancel"}
            loop = QEventLoop(self)
            btn_replace.clicked.connect(lambda: (result.update(val="replace"), loop.quit()))
            btn_copy.clicked.connect(lambda: (result.update(val="copy"), loop.quit()))
            btn_cancel.clicked.connect(lambda: (result.update(val="cancel"), loop.quit()))
            try:
                self.status.addWidget(frm, 1)
            except Exception:
                frm.show()
            loop.exec()
        finally:
            try:
                frm.setParent(None)
                frm.deleteLater()
            except Exception:
                pass
        return result.get("val", "cancel")

    def _ask_mode(self, title: str, a_text: str, b_text: str) -> str:
        """Показывает диалог с двумя вариантами. Возвращает 'A' или 'B' или '' при отмене."""
        fm = getattr(self, "_force_mode", None)
        if fm in ("A","B"):
            return fm
        mb = QMessageBox(self)
        mb.setWindowTitle(title)
        mb.setText(title)
        # Use standard warning icon size like regular errors
        try:
            mb.setIcon(QMessageBox.Warning)
        except Exception:
            try:
                size_px = QApplication.style().pixelMetric(QStyle.PM_MessageBoxIconSize)
                pm = QPixmap(WARNING_ICON_PATH)
                if not pm.isNull():
                    mb.setIconPixmap(pm.scaled(size_px, size_px, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            except Exception:
                pass
        move_messagebox_text_to_top(mb, TEXT_TOP_Y)
        a = mb.addButton(a_text, QMessageBox.AcceptRole)
        b = mb.addButton(b_text, QMessageBox.DestructiveRole)
        mb.addButton(QMessageBox.Cancel)
        try:
            mb.exec()
        except Exception:
            mb.exec_()
        clicked = mb.clickedButton()
        if clicked is a:
            return "A"
        if clicked is b:
            return "B"
        return ""


    def _is_root_open(self) -> bool:
        """Определяем, открыт ли сейчас КОРЕНЬ проекта."""
        node = self.current_folder_node()
        if not node:
            return True  # чаще всего в корне current_folder_node() возвращает None
        t = str(node.get("type", "")).lower()
        nid = node.get("id")
        return (t == "root") or (nid in (None, 0))


        # 1) попробовать найти сразу
        try:
            self.api.cache.pop(f"tree:{project_id}", None)
        except Exception:
            pass
        tree = self.api.list_folders(project_id) or []
        fid = self._child_folder_id_by_name(tree, None, name)
        if fid:
            try:
                return int(fid)
            except (ValueError, TypeError):
                return fid

        # 2) создать в корне - важно передать parent=None
        created = self.api.create_folder(project_id, None, name.strip())
        # если API вернул id - сразу используем
        if isinstance(created, (int, str)) and created not in (True, False, 0, ""):
            return normalize_id(created)

        # 3) дождаться появления в дереве (короткий ретрай)
        for _ in range(15):
            try:
                self.api.cache.pop(f"tree:{project_id}", None)
            except Exception:
                pass
            tree = self.api.list_folders(project_id) or []
            fid = self._child_folder_id_by_name(tree, None, name)
            if fid:
                try:
                    return int(fid)
                except (ValueError, TypeError):
                    return fid
            QApplication.processEvents()
            time.sleep(0.1)
        return None

    def _upload_dir_to_root(self, project_id: int | str, local_dir: "Path"):
        """Создаёт в корне папку local_dir.name и рекурсивно грузит содержимое."""
        base_id = self._ensure_subfolder(project_id, None, local_dir.name)
        if not base_id:
                return
        for entry in sorted(local_dir.iterdir()):
            if entry.is_dir():
                # используем уже имеющийся рекурсивный загрузчик под родителем
                self._upload_dir_recursive(project_id, base_id, entry)
            elif entry.is_file():
                ok = self.api.upload_file(base_id, str(entry), entry.name)
                # Log user action for notification filtering
                try:
                    if ok:
                        self._log_user_action("upload", file_name=entry.name, folder_id=base_id)
                        self._upload_ok = getattr(self, "_upload_ok", 0) + 1
                    else:
                        self._upload_fail = getattr(self, "_upload_fail", 0) + 1
                except Exception:
                    pass


    def _zip_add_empty_dir(self, zf: zipfile.ZipFile, arc_dir: str):
        arc = arc_dir.rstrip("/").replace("\\", "/") + "/"
        zf.writestr(arc, b"")
    def _on_header_clicked_sort(self, section: int):
        # Ignore sorting on the first checkbox column
        if int(section) == 0:
            # НЕ переключаем чекбоксы при клике на заголовок!
            # Переключение происходит только при клике НА САМИ HeaderCheckButton
            # (он обрабатывается через сигнал stateChanged в HeaderCheckButton)
            # Просто игнорируем клик по заголовку первой колонки
            return
        try:
            hdr = self.table.horizontalHeader()
        except Exception:
                return
        # User explicitly triggered sorting — release frozen order
        try:
            self._freeze_visible_order = False
            self._frozen_order = {}
        except Exception:
            pass

        # Первый клик - "взводим" сортировку и ставим стрелку вверх (Ascending)
        if not getattr(self, "_sorting_armed", False):
            self._sorting_armed = True
            try:
                self.table.setSortingEnabled(True)
            except Exception:
                pass
            try:
                hdr.setSortIndicatorShown(True)
            except Exception:
                pass

            order = Qt.AscendingOrder  # 1 > 11 на первом клике
            try:
                hdr.setSortIndicator(section, order)
            except Exception:
                pass
            try:
                self.proxy.sort(section, order)
            except Exception:
                try:
                    self.table.sortByColumn(section, order)
                except Exception:
                    pass

            try:
                hdr.viewport().update()
            except Exception:
                pass
                return

        # Со второго клика и далее Qt сам инвертирует порядок и стрелку.
                return




    def _on_theme_toggled(self, dark: bool) -> None:
        app = QApplication.instance()
        if app is None:
            return
        # Keep toggle state in sync when theme changes originate elsewhere (e.g. PDF window)
        try:
            toggle = getattr(self, "theme_toggle", None)
            if toggle is not None and bool(toggle.isChecked()) != bool(dark):
                toggle.blockSignals(True)
                try:
                    toggle.setChecked(bool(dark))
                    snap = getattr(toggle, "snap_to_state", None)
                    if callable(snap):
                        snap()
                finally:
                    toggle.blockSignals(False)
        except Exception:
            pass
        theme = THEME_DARK if dark else THEME_LIGHT
        if getattr(self, "_current_theme", None) == theme:
            return
        self._current_theme = theme
        if theme == THEME_DARK:
            apply_dark_theme(app)
        else:
            apply_light_theme(app)
        save_theme(theme)
        self._apply_icon_theme(theme)
        try:
            self._install_hover_black_icons()
        except Exception:
            pass
        # Ensure header and views know about theme change
        try:
            hdr = self.table.horizontalHeader()
            if isinstance(hdr, SortHeader):
                hdr.set_dark_mode(theme == THEME_DARK)
                hdr.update()
        except Exception:
            pass
        
        # Refresh notification icon after theme change
        try:
            self._update_notify_icon()
        except Exception:
            pass
        
        # Update title bar theme
        _set_window_theme_dark(self, dark=dark)

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
            # DISABLED: Initialize notifications timer on project load instead of startup
            # Timer is now initialized in Dekstop.py patch for load_tree_for_project
            # try:
            #     if not hasattr(self, "_notifications_timer") or self._notifications_timer is None:
            #         self._notifications_timer = QTimer(self)
            #         self._notifications_timer.timeout.connect(self._check_notifications)
            #     self._notifications_timer.setInterval(60 * 1000)  # 1 minute
            #     if not self._notifications_timer.isActive():
            #         self._notifications_timer.start()
            #     # Kick off an early check so users don't have to wait a full interval
            #     # (also helps initialize legacy empty baselines).
            #     try:
            #         QTimer.singleShot(2000, self._check_notifications)
            #     except Exception:
            #         pass
            # except Exception:
            #     pass

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
            
            # Auto-refresh timer при неактивности (5 минут)
            self._auto_refresh_timer = QTimer(self)
            self._auto_refresh_timer.setInterval(5 * 60 * 1000)  # 5 минут в миллисекундах
            self._auto_refresh_timer.timeout.connect(self._on_auto_refresh_timeout)
            self._auto_refresh_timer.start()
            
            # Отслеживание последней активности пользователя
            self._last_user_activity = time.time()
            
            # Установить event filter для отслеживания активности
            self.installEventFilter(self)
        except Exception:
            pass

    def _update_notify_icon(self) -> None:
        try:
            has_pending = False
            try:
                # Prefer new pending notifications source
                has_pending = bool(getattr(self, "_pending_notifications", {}))
            except Exception:
                has_pending = False
            # Fallback to legacy subscriptions/notifications flags
            try:
                if not has_pending and any(bool(v.get('pending')) for v in getattr(self, "_subscriptions", {}).values()):
                    has_pending = True
            except Exception:
                pass
            if not has_pending:
                has_pending = bool(getattr(self, "_notifications", []))
            path = ALARM1_ICON_PATH if has_pending else ALARM_ICON_PATH
            # Theme-aware: white in dark theme
            try:
                self.btn_notify.setIcon(self._themed_icon(path))
            except Exception:
                self.btn_notify.setIcon(QIcon(path))
        except Exception:
            pass

    def _toast_changes(self, folder_path: str, changes: list) -> None:
        """Show an OS-level notification (system tray) if available."""
        try:
            from PySide6.QtWidgets import QSystemTrayIcon
        except Exception:
            return

        try:
            tray = getattr(self, "_notify_tray", None)
            if tray is None:
                return
            if not QSystemTrayIcon.isSystemTrayAvailable():
                return

            cnt = len(changes) if isinstance(changes, list) else 0
            if cnt <= 0:
                return

            # Build a short message (1-3 first items)
            lines = []
            if isinstance(changes, list):
                for ch in changes[:3]:
                    try:
                        ctype = str((ch or {}).get("type") or "")
                        fname = str(((ch or {}).get("file") or {}).get("name") or "")
                        if fname:
                            lines.append(f"{ctype}: {fname}")
                    except Exception:
                        continue
            msg = f"{folder_path}: {cnt} изменений"
            if lines:
                msg = msg + "\n" + "\n".join(lines)

            tray.showMessage(APP_TITLE, msg, QSystemTrayIcon.Information, 8000)
        except Exception:
            return

    def _build_notify_menu(self) -> None:
        try:
            self.menu_notify.clear()
            # Prefer new pending notifications data source
            try:
                _pending = getattr(self, "_pending_notifications", {}) or {}
            except Exception:
                _pending = {}
            if _pending:
                try:
                    for folder_id, notif in list(_pending.items()):
                        try:
                            folder_path = str((notif or {}).get("folder_path", ""))
                            changes = (notif or {}).get("changes", [])
                            cnt = len(changes) if isinstance(changes, (list, tuple)) else 0
                            act = self.menu_notify.addAction(f"{folder_path} ({cnt})")
                            act.setData(folder_id)
                            act.triggered.connect(lambda _=False, fid=folder_id: self._show_changes_dialog(fid))
                        except Exception:
                            pass
                    self.menu_notify.addSeparator()
                    act_clear2 = self.menu_notify.addAction("Очистить уведомления")
                    def _clear2():
                        try:
                            self._pending_notifications = {}
                            save_pending_notifications(self._pending_notifications)
                            try:
                                self._update_notify_icon()
                            except Exception:
                                pass
                            try:
                                self._build_notify_menu()
                            except Exception:
                                pass
                        except Exception:
                            pass
                    act_clear2.triggered.connect(_clear2)
                    return
                except Exception:
                    pass
            if not self._notifications:
                act = self.menu_notify.addAction("Нет уведомлений")
                act.setEnabled(False)
            else:
                # newest first
                for note in list(self._notifications)[-20:][::-1]:
                    title = str(note.get('title') or '')
                    path = str(note.get('path') or '')
                    text = str(note.get('text') or '')
                    act = self.menu_notify.addAction(f"{title}: {text}")
                    if path:
                        act.triggered.connect(lambda _=False, p=path: self._open_path_in_os(p))
            self.menu_notify.addSeparator()
            act_clear = self.menu_notify.addAction("Очистить уведомления")
            def _clear():
                try:
                    self._notifications.clear()
                    # reset pending flags
                    for v in self._subscriptions.values():
                        v['pending'] = False
                    # Сброс бейджей в дереве
                    try:
                        for _fid in list(self._subscriptions.keys()):
                            try:
                                it = self.folder_item_by_id.get(normalize_id(_fid))
                            except Exception:
                                it = None
                            if it is not None:
                                it.setData(0, NOTIFY_ROLE, False)
                        self.tree.viewport().update()
                    except Exception:
                        pass

                    self._update_notify_icon()
                    self._build_notify_menu()
                except Exception:
                    pass
            act_clear.triggered.connect(_clear)
        except Exception:
            pass

    def _open_path_in_os(self, p: str) -> None:
        try:
            open_in_os(p)
        except Exception:
            pass

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
                self.status.showMessage("Автообновление...", 2000)
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

    def _tinted_icon(self, path: str, color: 'QtGui.QColor') -> 'QtGui.QIcon':
        pm = QPixmap(path)
        if pm.isNull():
            return QIcon(path)
        pm = pm.scaled(16, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        out = QPixmap(pm.size())
        out.fill(Qt.transparent)
        p = QPainter(out)
        p.drawPixmap(0, 0, pm)
        p.setCompositionMode(QPainter.CompositionMode_SourceIn)
        p.fillRect(out.rect(), color)
        p.end()
        return QIcon(out)



    def _zip_folder_into(self, node: dict, zf: zipfile.ZipFile, arc_prefix: str = ""):
        """Кладёт папку node в архив zf, сохраняя пустые папки."""
        folder_title = get_title(node) or f"folder_{node.get('id')}"
        base = os.path.join(arc_prefix, folder_title) if arc_prefix else folder_title
        self._zip_add_empty_dir(zf, base)
        for ch in (node.get("children") or []):
            if not isinstance(ch, dict):
                continue
            if ch.get("type") == "file":
                fname = ch.get("originalName") or ch.get("name") or f"file_{ch.get('id')}.bin"
                try:
                    with zf.open(os.path.join(base, fname), 'w') as zentry:
                        self.api.write_file_to(ch.get('id'), zentry)
                except Exception:
                    pass
            elif ch.get("type") == "folder":
                self._zip_folder_into(ch, zf, base)

    def _copy_folder_into(self, node: dict, dest_dir: str, into_name: str | None = None):
        """Копирует папку node как обычную директорию в dest_dir, включая пустые подпапки."""
        import shutil
        folder_name = into_name or (get_title(node) or f"folder_{node.get('id')}")
        root_dst = os.path.join(dest_dir, self._unique_name(dest_dir, folder_name))
        os.makedirs(root_dst, exist_ok=True)
        # создаём пустые подпапки и кладём файлы
        def descend(n: dict, rel: str = ""):
            here = os.path.join(root_dst, rel)
            for ch in (n.get("children") or []):
                if not isinstance(ch, dict):
                    continue
                if ch.get("type") == "folder":
                    sub_rel = os.path.join(rel, get_title(ch))
                    os.makedirs(os.path.join(root_dst, sub_rel), exist_ok=True)
                    descend(ch, sub_rel)
                elif ch.get("type") == "file":
                    _prev = getattr(self, "_force_mode", None); self._force_mode = "A"
                    try:
                        local = self.ensure_downloaded(ch)
                    finally:
                        self._force_mode = _prev
                    if not local:
                        continue
                    fname = ch.get("originalName") or ch.get("name") or f"file_{ch.get('id')}.bin"
                    dst = os.path.join(here, self._unique_name(here, fname))
                    try:
                        shutil.copyfile(local, dst)
                    except Exception:
                        pass
        descend(node)
        return root_dst

    def download_selected(self):
        item = self.selected_item()
        if not item or item.get("type") != "file":
            QMessageBox.information(self, "Скачивание", "Выберите файл в таблице."); return
        _prev = getattr(self, "_force_mode", None); self._force_mode = "A"
        try:
            local_path = self.ensure_downloaded(item)
        finally:
            self._force_mode = _prev
        if not local_path:
            QMessageBox.warning(self, "Скачивание", "Не удалось скачать файл."); return
        save_path, _ = QFileDialog.getSaveFileName(self, "Сохранить как", os.path.basename(local_path), "Все файлы (*.*)")
        if save_path:
            import shutil
            try:
                shutil.copyfile(local_path, save_path); QMessageBox.information(self, "Скачивание", "Файл сохранен.")
            except Exception as e:
                QMessageBox.warning(self, "Скачивание", f"Не удалось сохранить: {e}")

    def on_table_double_clicked(self, index: QModelIndex):
        if index.column() == 0:
                return
        if not index.isValid(): return
        item = self.selected_item()
        if not item: return
        if item.get("type") == "folder":
            fid = item.get("id")
            if fid in self.folder_item_by_id: self.tree.setCurrentItem(self.folder_item_by_id[fid])
            self.open_folder_node(item); return
        _prev = getattr(self, "_force_mode", None); self._force_mode = "A"
        try:
            local_path = self.ensure_downloaded(item)
        finally:
            self._force_mode = _prev
        if not local_path:
            QMessageBox.warning(self, "Открытие", "Не удалось скачать файл для открытия."); return
        if not open_in_os(local_path):
            QMessageBox.warning(self, "Открытие", "ОС не смогла открыть файл. Сохраните его и откройте вручную.")
    def open_selected_item(self):
        """Открывает выбранный в таблице элемент: папку - в таблице, файл - внешней программой."""
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

        # файл
        _prev = getattr(self, "_force_mode", None); self._force_mode = "A"
        try:
            local_path = self.ensure_downloaded(item)
        finally:
            self._force_mode = _prev
        if not local_path:
            QMessageBox.warning(self, "Открытие", "Не удалось скачать файл для открытия.")
            return
        if not open_in_os(local_path):
            QMessageBox.warning(self, "Открытие", "ОС не смогла открыть файл. Сохраните его и откройте вручную.")

    def download_folder_as_zip(self, node):
        # нормализация: вдруг передали QTreeWidgetItem
        if isinstance(node, QTreeWidgetItem):
            node = node.data(0, Qt.UserRole)

        if not isinstance(node, dict):
            node = self.current_folder_node()

        typ = str((node or {}).get("type", "")).lower()
        if typ not in ("folder", "dir", "directory", "папка"):
            QMessageBox.information(self, "", "Выберите папку из дерева или из таблицы."); 
            return

        save_path, _ = QFileDialog.getSaveFileName(self, "Сохранить ZIP", f"{get_title(node)}.zip", "Все файлы (*.*);;ZIP (*.zip)")
        if not save_path:
            return
        try:
            self._zip_folder_to_path(node, save_path)
            QMessageBox.information(self, "", "ZIP-архив сформирован.")
        except Exception as e:
            QMessageBox.warning(self, "", f"Не удалось собрать архив: {e}")

    def download_folder_plain(self, node):
        if isinstance(node, QTreeWidgetItem):
            node = node.data(0, Qt.UserRole)
        if not isinstance(node, dict):
            node = self.current_folder_node()

        typ = str((node or {}).get("type", "")).lower()
        if typ not in ("folder", "dir", "directory", "папка"):
            return
        dest_dir = self._pick_directory_showing_files("Куда сохранить папку")
        if not dest_dir:
            return
        self.progress.setVisible(True); self.progress.setRange(0, 0); QApplication.processEvents()
        try:
            self._copy_folder_into(node, dest_dir)
            QMessageBox.information(self, "Скачать структуру", "Копирование завершено.")
        finally:
            self.progress.setVisible(False)

    def _download_file_plain_fixed(self, node: dict):
        if not node or node.get("type") != "file":
            return
        # Save As dialog to select destination file name
        def_name = _sanitize_filename(node.get("originalName") or node.get("name") or f"file_{node.get('id')}.bin")
        save_path, _ = QFileDialog.getSaveFileName(self, "Сохранить файл", def_name, "Все файлы (*.*)")
        if not save_path:
            return
        # Ensure file is downloaded locally first
        _prev = getattr(self, "_force_mode", None); self._force_mode = "A"
        try:
            local = self.ensure_downloaded(node)
        finally:
            self._force_mode = _prev
        if not local:
            QMessageBox.warning(self, "Скачать файл", "Не удалось скачать файл.")
            return
        # Copy to chosen path with small wait indicator
        try:
            self.status.showMessage("Сохранение файла...")
            self.progress.setVisible(True); self.progress.setRange(0, 0); QApplication.processEvents()
        except Exception:
            pass
        _wait = None
        try:
            _wait = WaitDialog("Сохранение файла", self); _wait.show(); QApplication.processEvents()
        except Exception:
            _wait = None
        try:
            import shutil
            shutil.copyfile(local, save_path)
            ok_msg = True
        except Exception as e:
            ok_msg = False
            QMessageBox.warning(self, "Скачать файл", f"Не удалось сохранить: {e}")
        finally:
            try:
                self.progress.setVisible(False); self.status.clearMessage()
            except Exception:
                pass
            try:
                if _wait: _wait.set_done("Готово")
            except Exception:
                pass
        if ok_msg:
            QMessageBox.information(self, "Скачать файл", "Файл сохранён.")

    def download_file_plain(self, node: dict):
        if not node or node.get("type") != "file":
            return
        # Native Save As to select destination folder and rename file
        def_name = _sanitize_filename(node.get("originalName") or node.get("name") or f"file_{node.get('id')}.bin")
        save_path, _ = QFileDialog.getSaveFileName(self, "Сохранить как", def_name, "Все файлы (*.*)")
        if not save_path:
            return
        # Ensure file is available locally before copying
        _prev = getattr(self, "_force_mode", None); self._force_mode = "A"
        try:
            local = self.ensure_downloaded(node)
        finally:
            self._force_mode = _prev
        if not local:
            QMessageBox.warning(self, "Ошибка скачивания", "Не удалось скачать файл.")
            return
        # show status + wait dialog for single file
        try:
            self.status.showMessage("Скачивание файла...")
            self.progress.setVisible(True); self.progress.setRange(0, 0); QApplication.processEvents()
        except Exception:
            pass
        _wait = None
        try:
            _wait = WaitDialog("Скачивание файла", self); _wait.show(); QApplication.processEvents()
        except Exception:
            _wait = None
        ok_msg = False
        try:
            import shutil
            shutil.copyfile(local, save_path)
            ok_msg = True
        except Exception as e:
            try:
                if os.path.exists(save_path) and os.path.getsize(save_path) > 0:
                    ok_msg = True
            except Exception:
                ok_msg = False
            if not ok_msg:
                QMessageBox.warning(self, "Скачивание файла", f"Не удалось сохранить файл: {e}")
        try:
            self.progress.setVisible(False); self.status.clearMessage()
        except Exception:
            pass
        try:
            if _wait: _wait.set_done("Готово")
        except Exception:
            pass
        if ok_msg:
            QMessageBox.information(self, "Скачивание завершено", "Скачано файлов: 1")
        return
        dest_dir = self._pick_directory_showing_files("Куда сохранить файл")
        if not dest_dir:
            return
        _prev = getattr(self, "_force_mode", None); self._force_mode = "A"
        try:
            local = self.ensure_downloaded(node)
        finally:
            self._force_mode = _prev
        if not local:
            QMessageBox.warning(self, "Скачать файл", "Не удалось скачать файл.")
            return
        import os, shutil
        fname = node.get("originalName") or node.get("name") or f"file_{node.get('id')}.bin"
        fname = _sanitize_filename(fname)
        dst = os.path.join(dest_dir, self._unique_name(dest_dir, fname))
        try:
            shutil.copyfile(local, dst)
            QMessageBox.information(self, "Скачать файл", "Файл сохранён.")
        except Exception as e:
            QMessageBox.warning(self, "Скачать файл", f"Не удалось сохранить: {e}")

    def download_file_as_zip(self, node: dict):
        if not node or node.get("type") != "file":
            return
        import os, zipfile
        name = node.get("originalName") or node.get("name") or f"file_{node.get('id')}.bin"
        name = _sanitize_filename(name)
        base, _ = os.path.splitext(name)
        save_path, _ = QFileDialog.getSaveFileName(self, "Сохранить ZIP", f"{base}.zip", "Все файлы (*.*);;ZIP (*.zip)")
        if not save_path:
            return
        wait = None
        try:
            try:
                wait = WaitDialog("Формирование ZIP...", self)
                wait.show(); QApplication.processEvents()
            except Exception:
                wait = None
            with zipfile.ZipFile(save_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                with zf.open(name, 'w') as zentry:
                    if not self.api.write_file_to(node.get('id'), zentry):
                        if wait:
                            wait.set_done("Не удалось скачать файл")
                        else:
                            QMessageBox.warning(self, "Скачать как ZIP", "Не удалось скачать файл.")
                        return
            if wait:
                wait.set_done("ZIP-архив сформирован.")
            else:
                QMessageBox.information(self, "Скачать как ZIP", "ZIP-архив сформирован.")
        except Exception as e:
            QMessageBox.warning(self, "Скачать как ZIP", f"Не удалось собрать архив: {e}")

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
                    folder_title = str(cfg.get("title") or f"Папка {pf}")
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
                        text = ", ".join(names) + suffix if names else "Изменения"
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
            
            # If no badges to draw, return early
            if not notify_pixmap and not sync_pixmap:
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
            
            # Adjust base_x to ensure badges don't overlap with text
            if total_badge_width > 0:
                max_x = text_rect.right() + tab_px
                if base_x + total_badge_width > max_x:
                    base_x = max(base_x, deco_rect.right() + 4 if deco_rect.isValid() else text_rect.x())
            
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
                    y = original_rect.top() + (original_rect.height() - badge_size) // 2
                    painter.drawPixmap(int(current_x), int(y), notify_pixmap.scaled(badge_size, badge_size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
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
                    delegate = _SyncBadgeRightDelegate(self.tree)
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


