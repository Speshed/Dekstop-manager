# -*- coding: utf-8 -*-

import os
from datetime import datetime

from PySide6.QtCore import Qt, QEventLoop, QSettings, QSize
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QWidget, QLabel, QFormLayout,
    QDialogButtonBox, QPushButton, QHBoxLayout, QListWidget,
    QListWidgetItem, QCheckBox, QAbstractItemView, QApplication, QLineEdit,
    QSizePolicy
)

from .widgets import BusyDots, NikCheckBoxStyle
from larix_nexus.models.files_table import IconProvider

# Imports from utils modules
from larix_nexus.utils.theme import (
    load_white_icon,
    _is_dark_mode
)
from larix_nexus.utils.paths import rsrc_path
from larix_nexus.utils.helpers import _set_window_theme_dark
from larix_nexus.utils.i18n import t
from larix_nexus.constants import (
    SETTINGS_ORG, SETTINGS_APP
)

# Icons
CHECK_ICON_OFF_PATH = rsrc_path("icon", "check_off.png")
CHECK_ICON_ON_PATH = rsrc_path("icon", "check_on.png")
CHECK_ICON_MID_PATH = rsrc_path("icon", "check_mid.png")

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
        s = _app_settings()
        s.beginGroup("time")
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
        self.setWindowTitle(t("dialog.file_properties"))
        self.setMinimumWidth(520)
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
        
        # Safety net: unwrap common API response wrappers
        if data and isinstance(data, dict):
            for wrapper_key in ["data", "document", "item", "result", "doc"]:
                if wrapper_key in data and isinstance(data[wrapper_key], dict):
                    data = data[wrapper_key]
                    break

        if not data:
            layout.addRow(QLabel(t("dialog.data_load_error")))
        else:
            def _mk_props_label(text: str) -> QLabel:
                lbl = QLabel(text)
                lbl.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
                lbl.setFocusPolicy(Qt.StrongFocus)
                lbl.setCursor(Qt.IBeamCursor)
                lbl.setAutoFillBackground(False)
                lbl.setStyleSheet("background: transparent;")
                return lbl

            def _get_value(data: dict, keys: list):
                for k in keys:
                    v = data.get(k)
                    if v is not None and v != "":
                        return v
                return None

            def _format_timestamp(val):
                ts = parse_date_like(str(val))
                if ts > 0:
                    return _user_display_datetime(ts)
                return str(val)

            def _format_size(val):
                try:
                    size = int(val)
                    if size < 1024:
                        return f"{size} B"
                    elif size < 1024 * 1024:
                        return f"{size / 1024:.1f} KB"
                    else:
                        return f"{size / (1024*1024):.2f} MB"
                except (ValueError, TypeError):
                    return str(val)

            def _get_extension(filename: str) -> str:
                if not filename:
                    return ""
                parts = filename.rsplit(".")
                if len(parts) > 1:
                    return parts[-1].upper()
                return ""

            shown_keys = set()
            fields_order = [
                ("id", ["id"], t("dialog.field_id")),
                ("originalName", ["originalName", "name", "title", "filename"], t("dialog.field_file_name")),
                ("fileName", ["fileName", "serverName"], t("dialog.field_server_name")),
                ("version", ["version", "version_count"], t("dialog.field_version")),
                ("type", ["type"], t("dialog.field_object_type")),
                ("documentType", ["documentType", "document_type"], t("dialog.field_document_type")),
                ("extension", [], t("dialog.field_extension")),
                ("size", ["size", "file_size", "fileSize"], t("dialog.field_size_bytes")),
                ("createdBy", ["createdBy", "created_by", "creator"], t("dialog.field_created_by")),
                ("createTime", ["createTime", "createdAt", "created_ts", "created"], t("dialog.field_created")),
                ("modifiedBy", ["modifiedBy", "modified_by", "author", "updater"], t("dialog.field_modified_by")),
                ("modifTime", ["modifTime", "updatedAt", "updated_at", "modifiedDate", "modified_ts"], t("dialog.field_modified")),
                ("status", ["status"], t("dialog.field_status")),
                ("folderId", ["folderId", "folder_id", "parentFolderId"], t("dialog.field_folder_id")),
            ]

            for field_key, source_keys, label in fields_order:
                value = None
                if field_key == "extension":
                    filename = _get_value(data, ["originalName", "name", "fileName"])
                    if filename:
                        value = _get_extension(str(filename))
                else:
                    value = _get_value(data, source_keys)
                
                if value is None:
                    continue
                
                val_str = str(value)
                
                if field_key in ("createTime", "modifTime"):
                    val_str = _format_timestamp(value)
                elif field_key == "size":
                    val_str = _format_size(value)
                elif field_key == "status":
                    from ..utils.i18n import get_status_translation
                    val_str = get_status_translation(str(value))
                
                layout.addRow(_mk_props_label(f"{label}:"), _mk_props_label(val_str))
                shown_keys.add(field_key)

            extra_fields = {}
            skip_keys = {"id", "originalName", "name", "fileName", "version", "version_count",
                          "type", "documentType", "document_type", "size", "file_size", "fileSize",
                          "createdBy", "created_by", "creator", "createTime", "createdAt", "created_ts", "created",
                          "modifiedBy", "modified_by", "author", "updater", "modifTime", "updatedAt", "updated_at", "modifiedDate", "modified_ts",
                          "status", "folderId", "folder_id", "parentFolderId"}
            for key, value in data.items():
                if key in skip_keys or value is None or value == "":
                    continue
                if key not in shown_keys:
                    extra_fields[key] = value

            if extra_fields:
                layout.addRow(QLabel("─" * 30))
                for key, value in sorted(extra_fields.items()):
                    val_str = str(value)
                    if isinstance(value, (list, dict)):
                        val_str = str(value)[:100]
                    elif str(key).lower() == "status":
                        from ..utils.i18n import get_status_translation
                        val_str = get_status_translation(val_str)
                    layout.addRow(_mk_props_label(f"{key}:"), _mk_props_label(val_str))

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addRow(buttons)


class FolderDetailsDialog(QDialog):
    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.setWindowTitle(t("dialog.folder_properties"))
        self.setMinimumWidth(520)
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
        
        # Safety net: unwrap common API response wrappers
        if data and isinstance(data, dict):
            for wrapper_key in ["data", "folder", "item", "result", "doc"]:
                if wrapper_key in data and isinstance(data[wrapper_key], dict):
                    data = data[wrapper_key]
                    break

        if not data:
            layout.addRow(QLabel(t("dialog.data_load_error")))
        else:
            def _mk_props_label(text: str) -> QLabel:
                lbl = QLabel(text)
                lbl.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
                lbl.setFocusPolicy(Qt.StrongFocus)
                lbl.setCursor(Qt.IBeamCursor)
                lbl.setAutoFillBackground(False)
                lbl.setStyleSheet("background: transparent;")
                return lbl

            def _get_value(data: dict, keys: list):
                for k in keys:
                    v = data.get(k)
                    if v is not None and v != "":
                        return v
                return None

            def _format_timestamp(val):
                ts = parse_date_like(str(val))
                if ts > 0:
                    return _user_display_datetime(ts)
                return str(val)

            shown_keys = set()
            fields_order = [
                ("id", ["id"], t("dialog.field_id")),
                ("name", ["name", "title"], t("dialog.field_title")),
                ("projectId", ["projectId", "project_id"], t("dialog.field_project_id")),
                ("parentFolderId", ["parentFolderId", "parent_folder_id", "parentId"], t("dialog.field_parent_id")),
                ("createdBy", ["createdBy", "created_by", "author"], t("dialog.field_created_by")),
                ("createTime", ["createTime", "createdAt", "created_ts", "created"], t("dialog.field_created")),
                ("modifiedBy", ["modifiedBy", "modified_by", "updater"], t("dialog.field_modified_by")),
                ("modifTime", ["modifTime", "updatedAt", "updated_at", "modifiedDate", "modified_ts"], t("dialog.field_modified")),
                ("type", ["type"], t("dialog.field_object_type")),
            ]

            for field_key, source_keys, label in fields_order:
                value = _get_value(data, source_keys)
                if value is None:
                    continue
                val_str = str(value)
                if field_key in ("createTime", "modifTime"):
                    val_str = _format_timestamp(value)
                layout.addRow(_mk_props_label(f"{label}:"), _mk_props_label(val_str))
                shown_keys.add(field_key)

            skip_keys = {"id", "name", "title", "projectId", "project_id", "parentFolderId", "parent_folder_id", "parentId",
                          "createdBy", "created_by", "author", "createTime", "createdAt", "created_ts", "created",
                          "modifiedBy", "modified_by", "updater", "modifTime", "updatedAt", "updated_at", "modifiedDate", "modified_ts",
                          "type", "children", "files", "folders", "documents"}
            extra_fields = {}
            for key, value in data.items():
                if key in skip_keys or value is None or value == "":
                    continue
                if key not in shown_keys:
                    extra_fields[key] = value

            if extra_fields:
                layout.addRow(QLabel("─" * 30))
                for key, value in sorted(extra_fields.items()):
                    val_str = str(value)
                    if isinstance(value, (list, dict)):
                        val_str = str(value)[:100]
                    elif str(key).lower() == "status":
                        from ..utils.i18n import get_status_translation
                        val_str = get_status_translation(val_str)
                    layout.addRow(_mk_props_label(f"{key}:"), _mk_props_label(val_str))

        _buttons = QDialogButtonBox(QDialogButtonBox.Ok)


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
        self.setWindowTitle(t("dialog.download_files"))
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
        self._apply_all_style = NikCheckBoxStyle()

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

        self.info_label = QLabel(t("dialog.conflict_action"), self)
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        self.conflict_label = QLabel("", self)
        self.conflict_label.setWordWrap(True)
        self.conflict_label.setMaximumHeight(80)
        layout.addWidget(self.conflict_label)

        self.apply_all_box = QCheckBox(t("dialog.apply_to_all"), self)
        self.apply_all_box.setObjectName("bulkApplyAllBox")
        self.apply_all_box.setStyle(self._apply_all_style)
        self.apply_all_box.setCursor(Qt.PointingHandCursor)
        layout.addWidget(self.apply_all_box, 0, Qt.AlignLeft)

        self.list_widget = QListWidget(self)
        self.list_widget.setSelectionMode(QAbstractItemView.NoSelection)
        self.list_widget.setSpacing(0)
        self.list_widget.setFocusPolicy(Qt.NoFocus)
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

        self.btn_replace = QPushButton(t("dialog.replace"), self)
        self.btn_copy = QPushButton(t("dialog.save_copy"), self)
        self.btn_cancel = QPushButton(t("common.cancel"), self)
        self.btn_ok = QPushButton(t("common.ok"), self)
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
        item.setSizeHint(QSize(0, 40))
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
            self.conflict_label.setText(t("dialog.conflict_found"))
        else:
            self.conflict_label.clear()

    def update_progress(self, current: int, total: int) -> None:
        total = max(1, total)
        current = max(0, min(current, total))
        self.progress_anim.setVisible(current < total)
        self.progress_label.setText(t("dialog.downloading", current=current, total=total))
        QApplication.processEvents()

    def ask_conflict(self, key: str, name: str, remaining: int) -> tuple[str, bool]:
        self._conflict_index = self._conflicts_total - remaining + 1 if self._conflicts_total else 1
        self.set_active(key, True)
        if remaining > 0 and not self.apply_all_box.isChecked():
            self.conflict_label.setText(t("dialog.file_exists_indexed", index=self._conflict_index, total=self._conflicts_total, name=name))
        else:
            self.conflict_label.setText(t("dialog.file_exists", name=name))
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
        if hasattr(self, "btn_skip"):
            self.btn_skip.hide()
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
    def __init__(self, parent: QWidget | None, icon_provider: IconProvider | None, item: dict, display_name: str):
        super().__init__(parent)
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.setModal(True)
        self.setWindowTitle(t("dialog.download_file"))
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
        self._row_item.setSizeHint(QSize(0, 40))
        self.list_widget.setItemWidget(self._row_item, self._row_widget)
        progress_row = QHBoxLayout()
        progress_row.setContentsMargins(0, 0, 0, 0)
        progress_row.setSpacing(8)
        self.progress_anim = BusyDots(self, color="#F7921E", dots=5, r_min=2, r_max=4, spacing=6, interval_ms=90)
        self.progress_anim.setRange(0, 0)
        self.progress_anim.setVisible(True)
        progress_row.addWidget(self.progress_anim, 0, Qt.AlignLeft | Qt.AlignVCenter)
        self.progress_label = QLabel(t("common.loading"), self)
        progress_row.addWidget(self.progress_label, 1, Qt.AlignLeft | Qt.AlignVCenter)
        layout.addLayout(progress_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)
        self.btn_cancel = QPushButton(t("common.cancel"), self)
        self.btn_ok = QPushButton(t("common.ok"), self)
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
        self.progress_label.setText(t("dialog.downloaded", current=current, total=total))
        QApplication.processEvents()

    def finish(self, ok: bool, text: str = "") -> None:
        self.progress_anim.setVisible(False)
        if ok:
            self.set_status("ok", t("dialog.file_downloaded"))
            if text:
                self.progress_label.setText(text)
        else:
            self.set_status("none", t("dialog.download_error"))
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
        self._full_path = name
        self.status = "queued"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        self.icon_label = QLabel(self)
        self.icon_label.setFixedSize(24, 24)
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.set_icon(file_icon)

        self.name_label = QLabel(self)
        self.name_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.name_label.setWordWrap(False)
        self.name_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.name_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        name_font = self.name_label.font()
        name_font.setUnderline(True)
        self.name_label.setFont(name_font)
        self.name_label.setCursor(Qt.PointingHandCursor)
        self.setCursor(Qt.PointingHandCursor)

        layout.addWidget(self.icon_label, 0, Qt.AlignVCenter)
        layout.addWidget(self.name_label, 1, Qt.AlignVCenter)

        self.status_label = QLabel(self)
        self.status_label.setFixedSize(16, 16)
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setScaledContents(True)
        layout.addWidget(self.status_label, 0, Qt.AlignVCenter)
        self.setFixedHeight(40)
        self.setToolTip(name)
        self.name_label.setToolTip(name)
        self._update_display_name()
    def set_icon(self, icon: QIcon | None):
        if isinstance(icon, QIcon) and not icon.isNull():
            self.icon_label.setPixmap(icon.pixmap(20, 20))
        else:
            self.icon_label.clear()

    def set_status(self, status: str, tooltip: str = "") -> None:
        self.status = status
        self.status_label.setToolTip(tooltip or "")
        if status in {"queued", "cancelled", "skipped"}:
            self.status_label.clear()
            return
        icon = self._status_icons.get(status)
        if icon is None or icon.isNull():
            self.status_label.clear()
        else:
            self.status_label.setPixmap(icon.pixmap(14, 14))
        self.status_label.setToolTip(tooltip or "")

    def set_name(self, name: str) -> None:
        self._full_path = name
        self.setToolTip(name)
        self.name_label.setToolTip(name)
        self._update_display_name()

    def set_active(self, active: bool) -> None:
        font = self.name_label.font()
        font.setBold(active)
        self.name_label.setFont(font)
        self._update_display_name()

    def sizeHint(self) -> QSize:
        return QSize(0, 40)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_display_name()

    def _update_display_name(self) -> None:
        separator = max(self._full_path.rfind("/"), self._full_path.rfind("\\"))
        basename = self._full_path[separator + 1:]
        width = self.name_label.width()
        if width > 0:
            basename = self.name_label.fontMetrics().elidedText(basename, Qt.ElideRight, width)
        self.name_label.setText(basename)


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




class DocumentTypeDialog(QDialog):
    def __init__(self, parent: QWidget | None, types_map: dict, current_id: int | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.setModal(True)
        self.setWindowTitle(t("dialog.document_type"))
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
        
        label = QLabel(t("dialog.select_document_type"))
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
        "error": "none.png",
    }

    def __init__(self, parent: QWidget | None, total: int, icon_provider: IconProvider | None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.setModal(True)
        self.setWindowTitle(t("dialog.upload"))
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowMinimizeButtonHint, False)
        try:
            if _is_dark_mode():
                _set_window_theme_dark(self, dark=True)
        except Exception:
            pass
        self.setMaximumSize(550, 380)
        self.setMinimumWidth(400)

        self._allow_close = False
        self._cancelled = False
        self._worker_running = False
        self._cancel_callback = None
        self._decision_loop: QEventLoop | None = None
        self._decision: str = "cancel"
        self._icon_provider = icon_provider
        self._conflicts_total = 0
        self._conflict_index = 0
        self._rows: dict[str, tuple[QListWidgetItem, ConflictListItem]] = {}
        self._apply_all_style = NikCheckBoxStyle()

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
            off_p = off_p.replace("\\", "/")
            on_p = on_p.replace("\\", "/")
            mid_p = mid_p.replace("\\", "/")
            _chk_qss = (
                "QCheckBox::indicator { width: 18px; height: 18px; }\n"
                f"QCheckBox::indicator:unchecked {{ image: url('{off_p}'); }}\n"
                f"QCheckBox::indicator:checked   {{ image: url('{on_p}'); }}\n"
                f"QCheckBox::indicator:indeterminate {{ image: url('{mid_p}'); }}\n"
            )
            self.setStyleSheet((self.styleSheet() or "") + "\n" + _chk_qss)
        except Exception:
            pass

        self.info_label = QLabel(t("dialog.conflict_action"), self)
        self.info_label.setWordWrap(True)
        self.info_label.hide()
        layout.addWidget(self.info_label)

        self.conflict_label = QLabel("", self)
        self.conflict_label.setWordWrap(True)
        self.conflict_label.setMaximumHeight(80)
        self.conflict_label.hide()
        layout.addWidget(self.conflict_label)

        self.apply_all_box = QCheckBox(t("dialog.apply_to_all"), self)
        self.apply_all_box.setObjectName("bulkApplyAllBox")
        self.apply_all_box.setStyle(self._apply_all_style)
        self.apply_all_box.setCursor(Qt.PointingHandCursor)
        self.apply_all_box.hide()
        layout.addWidget(self.apply_all_box, 0, Qt.AlignLeft)

        self.list_widget = QListWidget(self)
        self.list_widget.setSelectionMode(QAbstractItemView.NoSelection)
        self.list_widget.setFocusPolicy(Qt.NoFocus)
        self.list_widget.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list_widget.setMaximumHeight(200)
        self.list_widget.setMinimumHeight(0)
        self.list_widget.setSpacing(0)
        self.list_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
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

        self.btn_replace = QPushButton(t("dialog.replace"), self)
        self.btn_copy = QPushButton(t("dialog.save_copy"), self)
        self.btn_skip = QPushButton("Пропустить", self)
        self.btn_cancel = QPushButton(t("common.cancel"), self)
        self.btn_ok = QPushButton(t("common.ok"), self)
        self.btn_ok.setVisible(False)

        for btn in (self.btn_replace, self.btn_copy, self.btn_skip, self.btn_cancel, self.btn_ok):
            btn.setProperty("chip", True)
            btn.setProperty("chipSmall", True)
            btn.setStyleSheet("padding: 3px 10px; min-height: 24px; font-size: 11px;")
            btn_row.addWidget(btn)

        self.btn_replace.clicked.connect(lambda: self._emit_decision("replace"))
        self.btn_copy.clicked.connect(lambda: self._emit_decision("copy"))
        self.btn_skip.clicked.connect(lambda: self._emit_decision("skip"))
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
        item.setSizeHint(QSize(0, 40))
        self.list_widget.setItemWidget(item, row)
        self._rows[key] = (item, row)
    def set_status(self, key: str, status: str, tooltip: str = "") -> None:
        row = self._rows.get(key)
        if not row:
            return
        if status not in self._status_icons and status not in {"queued", "cancelled", "skipped"}:
            status = "error"
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
            self.conflict_label.setText(t("dialog.conflict_found"))
        else:
            self.conflict_label.clear()
        self.btn_skip.setVisible(has_conflicts)
        self._adjust_list_height(self.list_widget.count())

    def _adjust_list_height(self, rows: int) -> None:
        visible_rows = max(1, min(rows, 5))
        self.list_widget.setMaximumHeight(visible_rows * 40)
        if rows <= 5:
            self.list_widget.setMinimumHeight(rows * 40 if rows else 40)
        else:
            self.list_widget.setMinimumHeight(0)
        self.adjustSize()

    def update_progress(self, current: int, total: int) -> None:
        total = max(1, total)
        current = max(0, min(current, total))
        self.progress_anim.setVisible(current < total)
        self.progress_label.setText(t("dialog.uploading", current=current, total=total))

    def ask_conflict(self, key: str, name: str, remaining: int) -> tuple[str, bool]:
        self._conflict_index = self._conflicts_total - remaining + 1 if self._conflicts_total else 1
        self.set_active(key, True)
        if remaining > 0 and not self.apply_all_box.isChecked():
            self.conflict_label.setText(t("dialog.file_exists_indexed", index=self._conflict_index, total=self._conflicts_total, name=name))
        else:
            self.conflict_label.setText(t("dialog.file_exists", name=name))
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
        if hasattr(self, "btn_skip"):
            self.btn_skip.hide()
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
        callback = self._cancel_callback
        if callback is not None:
            callback()
        if self._worker_running:
            self.btn_cancel.setEnabled(False)
            self.btn_cancel.setText(t("status.cancelling"))
            return
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
