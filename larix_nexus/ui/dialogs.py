# -*- coding: utf-8 -*-

import os
from datetime import datetime
from typing import Optional, Dict, Any, Callable

from PySide6.QtCore import Qt, QEventLoop, QRect, QPoint, QTimer, QSize, QSettings
from PySide6.QtGui import QIcon, QPixmap, QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QWidget, QLabel, QFormLayout,
    QDialogButtonBox, QPushButton, QHBoxLayout, QListWidget,
    QListWidgetItem, QCheckBox, QAbstractItemView, QApplication, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox
)
from PySide6 import QtCore, QtGui, QtWidgets

# Imports from utils modules
from larix_nexus.utils.theme import (
    _get_white_icon_path_for_dark_theme, load_white_icon,
    _is_dark_mode
)
from larix_nexus.utils.paths import rsrc_path, ICON_PATH
from larix_nexus.utils.helpers import _set_window_theme_dark
from larix_nexus.constants import (
    THEME_LIGHT, THEME_DARK, SETTINGS_ORG, SETTINGS_APP
)

# Icons
CHECK_ICON_OFF_PATH = rsrc_path("icon", "check_off.png")
CHECK_ICON_ON_PATH = rsrc_path("icon", "check_on.png")
CHECK_ICON_MID_PATH = rsrc_path("icon", "check_mid.png")

# Widgets
from .widgets import BusyDots, NikCheckBoxStyle, ConflictListItem

# IconProvider type from files_table module
from larix_nexus.models.files_table import IconProvider

# Helper functions
def _app_settings() -> QSettings:
    return QSettings(SETTINGS_ORG, SETTINGS_APP)

def parse_date_like(s: str, tz_offset_min: int | None = None) -> float:
    """Parse a cloud datetime into UTC epoch seconds."""
    if not s:
        return 0.0
    try:
        if isinstance(s, (int, float)) or (isinstance(s, str) and s.strip().isdigit()):
            val = float(s)
            if val > 1e12:
                val = val / 1000.0
            return float(val)
    except Exception:
        pass
    s = str(s).strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        from datetime import timezone, timedelta
        if dt.tzinfo is None:
            ofs = int(tz_offset_min or 0)
            dt2 = dt + timedelta(minutes=ofs)
            return dt2.replace(tzinfo=timezone.utc).timestamp()
        return dt.timestamp()
    except Exception:
        pass
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            from datetime import timezone, timedelta
            ofs = int(tz_offset_min or 0)
            dt2 = dt + timedelta(minutes=ofs)
            return dt2.replace(tzinfo=timezone.utc).timestamp()
        except (ValueError, TypeError):
            continue
    return 0.0

def _user_display_datetime(ts: float) -> str:
    """Format epoch seconds according to user timezone settings."""
    try:
        from datetime import timedelta
        s = _app_settings(); s.beginGroup("time")
        try:
            use_auto = bool(int(s.value("auto", 1) or 1))
            offset = int(s.value("offset_minutes", 0) or 0)
        finally:
            s.endGroup()
        if use_auto:
            dt = datetime.fromtimestamp(float(ts))
        else:
            dt = datetime.utcfromtimestamp(float(ts)) + timedelta(minutes=offset)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        try:
            return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return ""

def _get_white_icon_path_for_dark_theme(path: str) -> str:
    """Generate a white-tinted icon and return its path for use in dark theme CSS."""
    if not path or not os.path.exists(path):
        return path or ""
    try:
        pm = QPixmap(path)
        if not pm.isNull():
            # Just return the original path - tinting will be handled in code
            return path.replace("\\", "/")
    except Exception:
        pass
    return path.replace("\\", "/")


class FileDetailsDialog(QDialog):
    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.setWindowTitle("Свойства файла")
        self.setMinimumWidth(460)
        try:
            if _is_dark_mode():
                _set_window_theme_dark(self, dark=True)
        except Exception:
            pass
        outer = QVBoxLayout(self)
        wrap = QWidget(self); wrap.setObjectName("propsCard")
        layout = QFormLayout(wrap)
        layout.setContentsMargins(14, 14, 10, 10)
        layout.setSpacing(8)
        outer.addWidget(wrap)
        if not data:
            layout.addRow(QLabel("Не удалось загрузить данные."))
        else:
            def _mk_props_label(text: str) -> QLabel:
                lbl = QLabel(text)
                # Make text selectable/copyable and avoid per-label background blocks in dark theme.
                lbl.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
                lbl.setFocusPolicy(Qt.StrongFocus)
                lbl.setCursor(Qt.IBeamCursor)
                lbl.setAutoFillBackground(False)
                lbl.setStyleSheet("background: transparent;")
                return lbl

            key_map = {
                "id": "ID", "originalName": "мя файла", "fileName": "мя файла (сервер)",
                "name": "Внутреннее имя", "version": "Версия",
                "createdBy": "Кем создан", "createTime": "Создано",
                "modifiedBy": "Кем изменено", "modifTime": "Изменено",
                "folderId": "ID папки", "documentType": "Тип документа", "type": "Тип объекта",
                "size": "Размер (байт)"
            }
            for key, label in key_map.items():
                value = data.get(key)
                if value is None: continue
                val_str = str(value)
                if key in ("createTime","modifTime"):
                    ts = parse_date_like(val_str)
                    if ts > 0:
                        val_str = _user_display_datetime(ts)
                layout.addRow(_mk_props_label(f"{label}:"), _mk_props_label(val_str))

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addRow(buttons)


class FolderDetailsDialog(QDialog):
    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.setWindowTitle("Свойства папки")
        self.setMinimumWidth(460)
        try:
            if _is_dark_mode():
                _set_window_theme_dark(self, dark=True)
        except Exception:
            pass
        outer = QVBoxLayout(self)
        wrap = QWidget(self)
        wrap.setObjectName("propsCard")
        layout = QFormLayout(wrap)
        layout.setContentsMargins(14, 14, 10, 10)
        layout.setSpacing(8)
        outer.addWidget(wrap)

        if not data:
            layout.addRow(QLabel("Не удалось загрузить данные."))
        else:
            key_map = {
                "id": "ID", "name": "Название", "title": "Заголовок",
                "projectId": "ID проекта", "parentFolderId": "ID родителя",
                "createdBy": "Кем создана", "createTime": "Создана",
                "modifiedBy": "Кем изменена", "modifTime": "зменена",
                "type": "Тип объекта"
            }
            for key, label in key_map.items():
                value = data.get(key)
                if value is None: continue
                val_str = str(value)
                if key in ("createTime","modifTime"):
                    ts = parse_date_like(val_str)
                    if ts > 0:
                        val_str = _user_display_datetime(ts)
                layout.addRow(QLabel(f"{label}:"), QLabel(val_str))

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addRow(buttons)


class BatchDownloadDialog(QDialog):
    STATUS_ICON_FILES = {
        "ok": "ok.png",
        "process": "process.png",
        "none": "none.png",
    }

    def __init__(self, parent: QWidget | None, total: int, icon_provider: IconProvider | None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.setModal(True)
        self.setWindowTitle("Скачивание файлов")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowMinimizeButtonHint, False)
        try:
            if _is_dark_mode():
                _set_window_theme_dark(self, dark=True)
        except Exception:
            pass
        self.setMaximumSize(550, 380)
        self.resize(400, 220)

        self._allow_close = False
        self._cancelled = False
        self._decision_loop: QEventLoop | None = None
        self._decision: str = "cancel"
        self._icon_provider = icon_provider
        self._conflicts_total = 0
        self._conflict_index = 0
        self._rows: dict[str, tuple[QListWidgetItem, ConflictListItem]] = {}
        self._apply_all_style = NikCheckBoxStyle(self.style())

        self._status_icons: dict[str, QIcon] = {}
        for key, filename in self.STATUS_ICON_FILES.items():
            try:
                path = rsrc_path("icon", filename)
                if key == "process" and _is_dark_mode():
                    self._status_icons[key] = load_white_icon(path)
                else:
                    self._status_icons[key] = QIcon(path)
            except Exception:
                self._status_icons[key] = QIcon()
 
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 8)
        layout.setSpacing(6)

        self.info_label = QLabel("Выберите действие для файлов с совпадающими именами.", self)
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        self.conflict_label = QLabel("", self)
        self.conflict_label.setWordWrap(True)
        self.conflict_label.setMaximumHeight(80)
        layout.addWidget(self.conflict_label)

        self.apply_all_box = QCheckBox("Применить ко всем конфликтам", self)
        self.apply_all_box.setObjectName("bulkApplyAllBox")
        self.apply_all_box.setStyle(self._apply_all_style)
        self.apply_all_box.setCursor(Qt.PointingHandCursor)
        layout.addWidget(self.apply_all_box, 0, Qt.AlignLeft)

        self.list_widget = QListWidget(self)
        self.list_widget.setSelectionMode(QAbstractItemView.NoSelection)
        self.list_widget.setFocusPolicy(Qt.NoFocus)
        self.list_widget.setUniformItemSizes(True)
        self.list_widget.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list_widget.setMaximumHeight(200)
        self.list_widget.setStyleSheet(
            "QListWidget { border: none; }"
            "QListWidget::item { background: transparent; }"
            "QListWidget::item:hover { background: transparent; }"
            "QListWidget::item:selected { background: transparent; }"
        )
        layout.addWidget(self.list_widget, 1)

        progress_row = QHBoxLayout()
        progress_row.setContentsMargins(0, 0, 0, 0)
        progress_row.setSpacing(8)
        self.progress_anim = BusyDots(self, color="#F7921E", dots=5, r_min=2, r_max=4, spacing=6, interval_ms=90)
        self.progress_anim.setRange(0, 0)
        self.progress_anim.setVisible(False)
        progress_row.addWidget(self.progress_anim, 0, Qt.AlignLeft | Qt.AlignVCenter)
        self.progress_label = QLabel("", self)
        progress_row.addWidget(self.progress_label, 1, Qt.AlignLeft | Qt.AlignVCenter)
        layout.addLayout(progress_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.btn_replace = QPushButton("Заменить", self)
        self.btn_copy = QPushButton("Сохранить копию", self)
        self.btn_cancel = QPushButton("Отмена", self)
        self.btn_ok = QPushButton("Ок", self)
        self.btn_ok.setVisible(False)

        for btn in (self.btn_replace, self.btn_copy, self.btn_cancel, self.btn_ok):
            btn.setProperty("chip", True)
            btn.setProperty("chipSmall", True)
            btn.setStyleSheet("padding: 3px 10px; min-height: 24px; font-size: 11px;")
            btn_row.addWidget(btn)

        self.btn_replace.clicked.connect(lambda: self._emit_decision("replace"))
        self.btn_copy.clicked.connect(lambda: self._emit_decision("copy"))
        self.btn_cancel.clicked.connect(self._cancel)
        self.btn_ok.clicked.connect(self.accept)

    def add_entry(self, key: str, item_info: dict, display_name: str) -> None:
        qicon = QIcon()
        try:
            if self._icon_provider is not None:
                qicon = self._icon_provider.get_icon(item_info)
        except Exception:
            qicon = QIcon()
        row = ConflictListItem(qicon, display_name, self._status_icons, self)
        item = QListWidgetItem(self.list_widget)
        item.setSizeHint(QSize(0, 50))
        self.list_widget.setItemWidget(item, row)
        self._rows[key] = (item, row)

    def set_status(self, key: str, status: str, tooltip: str = "") -> None:
        row = self._rows.get(key)
        if not row:
            return
        if status not in self._status_icons:
            status = "none"
        row[1].set_status(status, tooltip)

    def set_name(self, key: str, name: str) -> None:
        row = self._rows.get(key)
        if row:
            row[1].set_name(name)

    def set_active(self, key: str, active: bool) -> None:
        for k, (_, widget) in self._rows.items():
            widget.set_active(active and k == key)

    def set_total_conflicts(self, total: int) -> None:
        self._conflicts_total = max(0, total)
        has_conflicts = self._conflicts_total > 0
        self.apply_all_box.setVisible(has_conflicts)
        self.info_label.setVisible(has_conflicts)
        self.btn_replace.setVisible(has_conflicts)
        self.btn_copy.setVisible(has_conflicts)
        self.progress_anim.setVisible(False)
        self.progress_label.clear()
        if has_conflicts:
            self.conflict_label.setText("Обнаружены файлы с совпадающими именами.")
        else:
            self.conflict_label.clear()

    def update_progress(self, current: int, total: int) -> None:
        total = max(1, total)
        current = max(0, min(current, total))
        self.progress_anim.setVisible(current < total)
        self.progress_label.setText(f"Скачивание: {current} из {total}")
        QApplication.processEvents()

    def ask_conflict(self, key: str, name: str, remaining: int) -> tuple[str, bool]:
        self._conflict_index = self._conflicts_total - remaining + 1 if self._conflicts_total else 1
        self.set_active(key, True)
        if remaining > 0 and not self.apply_all_box.isChecked():
            self.conflict_label.setText(f"Файл уже существует ({self._conflict_index}/{self._conflicts_total}): {name}")
        else:
            self.conflict_label.setText(f"Файл уже существует: {name}")
        self._adjust_width_to_content()
        self._decision = "cancel"
        loop = QEventLoop(self)
        self._decision_loop = loop
        loop.exec()
        self._decision_loop = None
        chosen = self._decision
        apply_all = self.apply_all_box.isChecked()
        self.set_active(key, False)
        return chosen, apply_all

    def finish(self, text: str) -> None:
        self.conflict_label.setText(text)
        self.apply_all_box.hide()
        self.btn_replace.hide()
        self.btn_copy.hide()
        self.btn_cancel.hide()
        self.btn_ok.show()
        self.progress_anim.setVisible(False)
        self.progress_label.clear()
        self.progress_label.hide()
        self._allow_close = True
        self.set_active("", False)
        self._adjust_width_to_content()

    def was_cancelled(self) -> bool:
        return self._cancelled

    def _emit_decision(self, decision: str) -> None:
        if self._decision_loop is None:
            return
        self._decision = decision
        loop = self._decision_loop
        self._decision_loop = None
        loop.quit()

    def _cancel(self) -> None:
        self._cancelled = True
        self._emit_decision("cancel")
        self._allow_close = True
        self.reject()

    def closeEvent(self, event):
        if not self._allow_close and not self._cancelled:
            self._cancel()
        super().closeEvent(event)

    def _adjust_width_to_content(self) -> None:
        try:
            text = self.conflict_label.text()
            fm = self.conflict_label.fontMetrics()
            text_width = fm.horizontalAdvance(text)
            margins = 12 * 2
            required_width = text_width + margins + 40
            current_width = self.width()
            if required_width > current_width:
                new_width = min(required_width, 550)
                self.resize(new_width, self.height())
        except Exception:
            pass


class SingleDownloadDialog(QDialog):
    """Окно для одиночного скачивания с нижней строкой статуса (точки + текст)."""
    def __init__(self, parent: QWidget | None, icon_provider: IconProvider | None, item: dict, display_name: str):
        super().__init__(parent)
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.setModal(True)
        self.setWindowTitle("Скачивание файла")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowMinimizeButtonHint, False)
        try:
            if _is_dark_mode():
                _set_window_theme_dark(self, dark=True)
        except Exception:
            pass
        self.setWindowFlag(Qt.WindowMinimizeButtonHint, False)
        self.resize(400, 100)

        self._cancelled = False
        self._status_icons: dict[str, QIcon] = {}
        try:
            for key, filename in BatchDownloadDialog.STATUS_ICON_FILES.items():
                path = rsrc_path("icon", filename)
                if key == "process" and _is_dark_mode():
                    self._status_icons[key] = load_white_icon(path)
                else:
                    self._status_icons[key] = QIcon(path)
        except Exception:
            pass

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self.list_widget = QListWidget(self)
        self.list_widget.setSelectionMode(QAbstractItemView.NoSelection)
        self.list_widget.setFocusPolicy(Qt.NoFocus)
        self.list_widget.setStyleSheet(
            "QListWidget { border: none; }"
            "QListWidget::item { background: transparent; }"
            "QListWidget::item:hover { background: transparent; }"
            "QListWidget::item:selected { background: transparent; }"
        )
        layout.addWidget(self.list_widget, 1)

        qicon = QIcon()
        try:
            if icon_provider is not None:
                qicon = icon_provider.get_icon(item)
        except Exception:
            qicon = QIcon()
        self._row_widget = ConflictListItem(qicon, display_name, self._status_icons, self)
        self._row_item = QListWidgetItem(self.list_widget)
        self._row_item.setSizeHint(QSize(0, 50))
        self.list_widget.setItemWidget(self._row_item, self._row_widget)

        progress_row = QHBoxLayout()
        progress_row.setContentsMargins(0, 0, 0, 0)
        progress_row.setSpacing(8)
        self.progress_anim = BusyDots(self, color="#F7921E", dots=5, r_min=2, r_max=4, spacing=6, interval_ms=90)
        self.progress_anim.setRange(0, 0)
        self.progress_anim.setVisible(True)
        progress_row.addWidget(self.progress_anim, 0, Qt.AlignLeft | Qt.AlignVCenter)
        self.progress_label = QLabel("Скачивание...", self)
        progress_row.addWidget(self.progress_label, 1, Qt.AlignLeft | Qt.AlignVCenter)
        layout.addLayout(progress_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)
        self.btn_cancel = QPushButton("Отмена", self)
        self.btn_ok = QPushButton("ОК", self)
        self.btn_ok.setVisible(False)
        self.btn_cancel.setProperty("chip", True)
        self.btn_cancel.setProperty("chipSmall", True)
        self.btn_cancel.setStyleSheet("padding: 3px 10px; min-height: 24px; font-size: 11px;")
        btn_row.addWidget(self.btn_cancel)
        self.btn_ok.setProperty("chip", True)
        self.btn_ok.setProperty("chipTiny", True)
        btn_row.addWidget(self.btn_ok)
        self.btn_cancel.clicked.connect(self._on_cancel)
        self.btn_ok.clicked.connect(self.accept)

    def set_status(self, status: str, tooltip: str = "") -> None:
        if status not in self._status_icons:
            status = "none"
        self._row_widget.set_status(status, tooltip)
        self._adjust_width_to_content()

    def _adjust_width_to_content(self) -> None:
        try:
            name_label = self._row_widget.name_label
            fm = name_label.fontMetrics()
            text = name_label.text()
            text_width = fm.horizontalAdvance(text)
            icon_width = 24
            status_width = 16
            margins = 8 * 2
            spacing = 8 * 2
            required_width = icon_width + text_width + status_width + margins + spacing + 40
            current_width = self.width()
            if required_width > current_width:
                new_width = min(required_width, 800)
                self.resize(new_width, self.height())
        except Exception:
            pass

    def set_name(self, name: str) -> None:
        self._row_widget.set_name(name)
        self._adjust_width_to_content()

    def update_count(self, current: int, total: int) -> None:
        total = max(1, total)
        current = max(0, min(current, total))
        self.progress_anim.setVisible(current < total)
        self.progress_label.setText(f"Скачано: {current} из {total}")
        QApplication.processEvents()

    def finish(self, ok: bool, text: str = "") -> None:
        self.progress_anim.setVisible(False)
        if ok:
            self.set_status("ok", "Файл скачан")
            if text:
                self.progress_label.setText(text)
        else:
            self.set_status("none", "Ошибка скачивания")
            if text:
                self.progress_label.setText(text)
        self.btn_cancel.hide()
        self.btn_ok.show()
        self._adjust_width_to_content()

    def was_cancelled(self) -> bool:
        return self._cancelled

    def _on_cancel(self):
        self._cancelled = True
        self.reject()


class ConflictListItem(QWidget):
    """Widget for displaying a file with conflict in batch operations."""
    def __init__(self, file_icon: QIcon, name: str, status_icons: dict[str, QIcon], parent: QWidget | None = None):
        super().__init__(parent)
        self._status_icons = status_icons

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        self.icon_label = QLabel(self)
        self.icon_label.setFixedSize(24, 24)
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.set_icon(file_icon)

        self.name_label = QLabel(name, self)
        self.name_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.name_label.setWordWrap(True)

        layout.addWidget(self.icon_label, 0, Qt.AlignTop)
        layout.addWidget(self.name_label, 1, Qt.AlignTop)

        self.status_label = QLabel(self)
        self.status_label.setFixedSize(16, 16)
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setScaledContents(True)
        layout.addWidget(self.status_label, 0, Qt.AlignTop)

    def set_icon(self, icon: QIcon | None):
        if isinstance(icon, QIcon) and not icon.isNull():
            self.icon_label.setPixmap(icon.pixmap(20, 20))
        else:
            self.icon_label.clear()

    def set_status(self, status: str, tooltip: str = "") -> None:
        icon = self._status_icons.get(status)
        if icon is None or icon.isNull():
            self.status_label.clear()
        else:
            self.status_label.setPixmap(icon.pixmap(14, 14))
        self.status_label.setToolTip(tooltip or "")

    def set_name(self, name: str) -> None:
        self.name_label.setText(name)

    def set_active(self, active: bool) -> None:
        font = self.name_label.font()
        font.setBold(active)
        self.name_label.setFont(font)


class InputDialog(QDialog):
    def __init__(self, parent: QWidget | None, title: str, label: str, default_text: str = ""):
        super().__init__(parent)
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.setModal(True)
        self.setWindowTitle(title)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(320)
        
        try:
            if _is_dark_mode():
                _set_window_theme_dark(self, dark=True)
        except Exception:
            pass
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 8)
        layout.setSpacing(8)
        
        layout.addWidget(QLabel(label))
        
        self.line_edit = QLineEdit(default_text)
        layout.addWidget(self.line_edit)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def get_text(self) -> str:
        return self.line_edit.text().strip()


class DocumentTypeSelectionDialog(QDialog):
    def __init__(self, parent: QWidget | None, tasks: list[dict], types_map: dict):
        super().__init__(parent)
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.setModal(True)
        self.setWindowTitle("Выбор типа документа")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(500)
        self.setMinimumHeight(350)
        self.resize(500, 350)
        
        try:
            if _is_dark_mode():
                _set_window_theme_dark(self, dark=True)
        except Exception:
            pass
        
        self.tasks = tasks
        self.types_map = types_map
        self.combos: dict[str, QComboBox] = {}
        self.checkboxes: dict[str, QCheckBox] = {}
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 8)
        layout.setSpacing(8)
        
        info_label = QLabel("Выберите тип документа для файлов:")
        layout.addWidget(info_label)
        
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["", "Файл", "Тип документа"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setStyleSheet("""
            QTableWidget::section {
                background-color: transparent;
                border: none;
                color: #888888;
                padding: 4px;
            }
            QTableWidget::section:hover {
                background-color: transparent;
            }
        """)
        layout.addWidget(self.table)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        self._populate_table()
    
    def _populate_table(self):
        self.table.setRowCount(len(self.tasks))
        
        type_names = []
        for k, v in self.types_map.items():
            try:
                kid = int(str(k).strip())
            except Exception:
                continue
            type_names.append((kid, str(v)))
        type_names.sort(key=lambda x: x[0])
        
        for row, task in enumerate(self.tasks):
            checkbox_widget = QWidget()
            checkbox_layout = QHBoxLayout(checkbox_widget)
            checkbox_layout.setContentsMargins(0, 0, 0, 0)
            checkbox_layout.setAlignment(Qt.AlignCenter)
            checkbox = QCheckBox()
            checkbox_layout.addWidget(checkbox)
            checkbox_widget.setLayout(checkbox_layout)
            self.table.setCellWidget(row, 0, checkbox_widget)
            self.checkboxes[task["key"]] = checkbox
            
            name_item = QTableWidgetItem(task["name"])
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 1, name_item)
            
            combo = QComboBox()
            for kid, name in type_names:
                combo.addItem(f"{name} ({kid})", kid)
            combo.setMinimumWidth(120)
            combo.currentIndexChanged.connect(lambda idx, r=row, t=task: self._on_combo_changed(r, t))
            self.table.setCellWidget(row, 2, combo)
            self.combos[task["key"]] = combo
    
    def _on_combo_changed(self, row: int, task: dict):
        combo = self.table.cellWidget(row, 2)
        if not isinstance(combo, QComboBox) or combo.currentIndex() < 0:
            return
        
        selected_type_id = combo.currentData()
        
        for r in range(self.table.rowCount()):
            checkbox = self.table.cellWidget(r, 0).findChild(QCheckBox)
            if isinstance(checkbox, QCheckBox) and checkbox.isChecked():
                row_combo = self.table.cellWidget(r, 2)
                if isinstance(row_combo, QComboBox) and row_combo != combo:
                    for i in range(row_combo.count()):
                        if row_combo.itemData(i) == selected_type_id:
                            row_combo.blockSignals(True)
                            row_combo.setCurrentIndex(i)
                            row_combo.blockSignals(False)
                            break
    
    def get_document_types(self) -> dict[str, int | None]:
        result = {}
        for task in self.tasks:
            combo = self.combos.get(task["key"])
            if isinstance(combo, QComboBox):
                result[task["key"]] = combo.currentData()
            else:
                result[task["key"]] = None
        return result


class DocumentTypeDialog(QDialog):
    def __init__(self, parent: QWidget | None, types_map: dict, current_id: int | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.setModal(True)
        self.setWindowTitle("Тип документа")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(320)
        
        try:
            if _is_dark_mode():
                _set_window_theme_dark(self, dark=True)
        except Exception:
            pass
        
        self._selected_id: int | None = None
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 8)
        layout.setSpacing(8)
        
        label = QLabel("Выберите тип документа для загрузки:")
        layout.addWidget(label)
        
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(self.list_widget)
        
        self._id_to_index: dict[int, int] = {}
        current_index = 0
        
        pairs = []
        for k, v in types_map.items():
            try:
                kid = int(str(k).strip())
            except Exception:
                continue
            pairs.append((kid, str(v)))
        pairs.sort(key=lambda x: x[0])
        
        for i, (kid, name) in enumerate(pairs):
            item_text = f"{name} ({kid})" if name else str(kid)
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, kid)
            self.list_widget.addItem(item)
            self._id_to_index[kid] = i
            if current_id is not None and kid == current_id:
                current_index = i
        
        if pairs:
            self.list_widget.setCurrentRow(current_index)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def get_selected_type_id(self) -> int | None:
        if self.result() == QDialog.Accepted:
            current = self.list_widget.currentItem()
            if current:
                return current.data(Qt.UserRole)
        return None


class BatchUploadDialog(QDialog):
    STATUS_ICON_FILES = {
        "ok": "ok.png",
        "process": "process.png",
        "none": "none.png",
    }

    def __init__(self, parent: QWidget | None, total: int, icon_provider: IconProvider | None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.setModal(True)
        self.setWindowTitle("Загрузка")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowMinimizeButtonHint, False)
        try:
            if _is_dark_mode():
                _set_window_theme_dark(self, dark=True)
        except Exception:
            pass
        self.setMaximumSize(550, 380)
        self.resize(400, 220)

        self._allow_close = False
        self._cancelled = False
        self._decision_loop: QEventLoop | None = None
        self._decision: str = "cancel"
        self._icon_provider = icon_provider
        self._conflicts_total = 0
        self._conflict_index = 0
        self._rows: dict[str, tuple[QListWidgetItem, ConflictListItem]] = {}
        self._apply_all_style = NikCheckBoxStyle(self.style())

        self._status_icons: dict[str, QIcon] = {}
        for key, filename in self.STATUS_ICON_FILES.items():
            try:
                path = rsrc_path("icon", filename)
                if key == "process" and _is_dark_mode():
                    self._status_icons[key] = load_white_icon(path)
                else:
                    self._status_icons[key] = QIcon(path)
            except Exception:
                self._status_icons[key] = QIcon()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 8)
        layout.setSpacing(6)
        try:
            dark = _is_dark_mode()
            off_p = CHECK_ICON_OFF_PATH
            on_p  = CHECK_ICON_ON_PATH
            mid_p = CHECK_ICON_MID_PATH
            if dark:
                try:
                    off_p = _get_white_icon_path_for_dark_theme(off_p)
                    on_p  = _get_white_icon_path_for_dark_theme(on_p)
                    mid_p = _get_white_icon_path_for_dark_theme(mid_p)
                except Exception:
                    pass
            _chk_qss = (
                "QCheckBox::indicator { width: 18px; height: 18px; }\n"
                f"QCheckBox::indicator:unchecked {{ image: url('{off_p}'); }}\n"
                f"QCheckBox::indicator:checked   {{ image: url('{on_p}'); }}\n"
                f"QCheckBox::indicator:indeterminate {{ image: url('{mid_p}'); }}\n"
            )
            self.setStyleSheet((self.styleSheet() or "") + "\n" + _chk_qss)
        except Exception:
            pass

        self.info_label = QLabel("Выберите действие для файлов с совпадающими именами.", self)
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        self.conflict_label = QLabel("", self)
        self.conflict_label.setWordWrap(True)
        self.conflict_label.setMaximumHeight(80)
        layout.addWidget(self.conflict_label)

        self.apply_all_box = QCheckBox("Применить ко всем конфликтам", self)
        self.apply_all_box.setObjectName("bulkApplyAllBox")
        self.apply_all_box.setStyle(self._apply_all_style)
        self.apply_all_box.setCursor(Qt.PointingHandCursor)
        layout.addWidget(self.apply_all_box, 0, Qt.AlignLeft)

        self.list_widget = QListWidget(self)
        self.list_widget.setSelectionMode(QAbstractItemView.NoSelection)
        self.list_widget.setFocusPolicy(Qt.NoFocus)
        self.list_widget.setUniformItemSizes(True)
        self.list_widget.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list_widget.setMaximumHeight(200)
        self.list_widget.setStyleSheet(
            "QListWidget { border: none; }"
            "QListWidget::item { background: transparent; }"
            "QListWidget::item:hover { background: transparent; }"
            "QListWidget::item:selected { background: transparent; }"
        )
        layout.addWidget(self.list_widget, 1)

        progress_row = QHBoxLayout()
        progress_row.setContentsMargins(0, 0, 0, 0)
        progress_row.setSpacing(8)
        self.progress_anim = BusyDots(self, color="#F7921E", dots=5, r_min=2, r_max=4, spacing=6, interval_ms=90)
        self.progress_anim.setRange(0, 0)
        self.progress_anim.setVisible(False)
        progress_row.addWidget(self.progress_anim, 0, Qt.AlignLeft | Qt.AlignVCenter)
        self.progress_label = QLabel("", self)
        progress_row.addWidget(self.progress_label, 1, Qt.AlignLeft | Qt.AlignVCenter)
        layout.addLayout(progress_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.btn_replace = QPushButton("Заменить", self)
        self.btn_copy = QPushButton("Сохранить копию", self)
        self.btn_cancel = QPushButton("Отмена", self)
        self.btn_ok = QPushButton("Ок", self)
        self.btn_ok.setVisible(False)

        for btn in (self.btn_replace, self.btn_copy, self.btn_cancel, self.btn_ok):
            btn.setProperty("chip", True)
            btn.setProperty("chipSmall", True)
            btn.setStyleSheet("padding: 3px 10px; min-height: 24px; font-size: 11px;")
            btn_row.addWidget(btn)

        self.btn_replace.clicked.connect(lambda: self._emit_decision("replace"))
        self.btn_copy.clicked.connect(lambda: self._emit_decision("copy"))
        self.btn_cancel.clicked.connect(self._cancel)
        self.btn_ok.clicked.connect(self.accept)

    def add_entry(self, key: str, item_info: dict, display_name: str) -> None:
        qicon = QIcon()
        try:
            if self._icon_provider is not None:
                qicon = self._icon_provider.get_icon(item_info)
        except Exception:
            qicon = QIcon()
        row = ConflictListItem(qicon, display_name, self._status_icons, self)
        item = QListWidgetItem(self.list_widget)
        item.setSizeHint(QSize(0, 50))
        self.list_widget.setItemWidget(item, row)
        self._rows[key] = (item, row)

    def set_status(self, key: str, status: str, tooltip: str = "") -> None:
        row = self._rows.get(key)
        if not row:
            return
        if status not in self._status_icons:
            status = "none"
        row[1].set_status(status, tooltip)

    def set_name(self, key: str, name: str) -> None:
        row = self._rows.get(key)
        if row:
            row[1].set_name(name)

    def set_active(self, key: str, active: bool) -> None:
        for k, (_, widget) in self._rows.items():
            widget.set_active(active and k == key)

    def set_total_conflicts(self, total: int) -> None:
        self._conflicts_total = max(0, total)
        has_conflicts = self._conflicts_total > 0
        self.apply_all_box.setVisible(has_conflicts)
        self.info_label.setVisible(has_conflicts)
        self.btn_replace.setVisible(has_conflicts)
        self.btn_copy.setVisible(has_conflicts)
        self.progress_anim.setVisible(False)
        self.progress_label.clear()
        if has_conflicts:
            self.conflict_label.setText("Обнаружены файлы с совпадающими именами.")
        else:
            self.conflict_label.clear()

    def update_progress(self, current: int, total: int) -> None:
        total = max(1, total)
        current = max(0, min(current, total))
        self.progress_anim.setVisible(current < total)
        self.progress_label.setText(f"Загрузка: {current} из {total}")
        QApplication.processEvents()

    def ask_conflict(self, key: str, name: str, remaining: int) -> tuple[str, bool]:
        self._conflict_index = self._conflicts_total - remaining + 1 if self._conflicts_total else 1
        self.set_active(key, True)
        if remaining > 0 and not self.apply_all_box.isChecked():
            self.conflict_label.setText(f"Файл уже существует ({self._conflict_index}/{self._conflicts_total}): {name}")
        else:
            self.conflict_label.setText(f"Файл уже существует: {name}")
        self._adjust_width_to_content()
        self._decision = "cancel"
        loop = QEventLoop(self)
        self._decision_loop = loop
        loop.exec()
        self._decision_loop = None
        chosen = self._decision
        apply_all = self.apply_all_box.isChecked()
        self.set_active(key, False)
        return chosen, apply_all

    def finish(self, text: str) -> None:
        self.conflict_label.setText(text)
        self.apply_all_box.hide()
        self.btn_replace.hide()
        self.btn_copy.hide()
        self.btn_cancel.hide()
        self.btn_ok.show()
        self.progress_anim.setVisible(False)
        self.progress_label.clear()
        self.progress_label.hide()
        self._allow_close = True
        self.set_active("", False)
        self._adjust_width_to_content()

    def was_cancelled(self) -> bool:
        return self._cancelled

    def _emit_decision(self, decision: str) -> None:
        if self._decision_loop is None:
            return
        self._decision = decision
        loop = self._decision_loop
        self._decision_loop = None
        loop.quit()

    def _cancel(self) -> None:
        self._cancelled = True
        self._emit_decision("cancel")
        self._allow_close = True
        self.reject()

    def closeEvent(self, event):
        if not self._allow_close and not self._cancelled:
            self._cancel()
        super().closeEvent(event)

    def _adjust_width_to_content(self) -> None:
        try:
            text = self.conflict_label.text()
            fm = self.conflict_label.fontMetrics()
            text_width = fm.horizontalAdvance(text)
            margins = 12 * 2
            required_width = text_width + margins + 40
            current_width = self.width()
            if required_width > current_width:
                new_width = min(required_width, 550)
                self.resize(new_width, self.height())
        except Exception:
            pass


# Type hint placeholder for IconProvider (to be imported from main module)
class IconProvider:
    def get_icon(self, item_info: dict) -> QIcon:
        return QIcon()
