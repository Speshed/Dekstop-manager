# -*- coding: utf-8 -*-

import os
import math
import tempfile
import sys
import platform
from typing import Optional, Dict, Any

from PySide6.QtCore import (
    Qt, QSize, QEvent, QRect, QRectF, QPoint, QPointF, QTimer,
    QPropertyAnimation, QEasingCurve, Property
)
from PySide6.QtGui import (
    QIcon, QPixmap, QPainter, QColor, QPen, QCursor, QBrush, QPalette,
    QLinearGradient,
)
from PySide6.QtWidgets import (
    QApplication, QHeaderView, QAbstractButton, QWidget,
    QFrame, QVBoxLayout, QHBoxLayout, QCheckBox, QLabel,
    QPushButton, QDialog, QMenu, QProxyStyle, QStyle, QStyleOptionViewItem, QAbstractItemView, QTableView, QSizePolicy
)
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtGui import QTransform, QFontMetrics

from PySide6.QtCore import QSettings
from ..style_tokens import ACCENT_PRIMARY


STATUS_CARD_OUTER_GAP = 10

from larix_nexus.utils.paths import rsrc_path, program_dir as _program_dir, ICON_PATH as _APP_ICON_PATH
from larix_nexus.utils.helpers import _set_window_theme_dark
from larix_nexus.utils.i18n import t
from larix_nexus.constants import (
    SETTINGS_ORG, SETTINGS_APP, THEME_LIGHT, THEME_DARK, CHECKBOX_COLUMN_WIDTH,
    SORT_ICON_UP_PATH, SORT_ICON_DOWN_PATH,
    CHECK_ICON_OFF_PATH, CHECK_ICON_ON_PATH, CHECK_ICON_MID_PATH
)

# Constants
ICON_PATH = _APP_ICON_PATH

SCROLLBAR_SLIDER_MIN = 24


# Cache for white icons
_WHITE_ICON_CACHE: dict[str, QIcon] = {}

# Cache for branch arrows
_BRANCH_BASE_PIXMAP_CACHE: dict = {}
_BRANCH_TINTED_PIXMAP_CACHE: dict = {}

def program_dir() -> str:
    return _program_dir()

def _tint_pixmap(pix: QPixmap, color: QColor) -> QPixmap:
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


def navigation_pixmap(mirrored: bool = False, size: int = 16, dark: bool = False) -> QPixmap:
    """Load, mirror and theme the shared navigation edge-button asset."""
    size = max(8, int(size))
    color = QColor("#E0E0E0") if dark else QColor("#222222")
    try:
        pm = QPixmap(rsrc_path("icon", "navigation.png"))
        if not pm.isNull():
            image = pm.toImage()
            if image.hasAlphaChannel():
                bounds = None
                for y in range(image.height()):
                    for x in range(image.width()):
                        if image.pixelColor(x, y).alpha() > 0:
                            point = QtCore.QPoint(x, y)
                            bounds = QtCore.QRect(point, point) if bounds is None else bounds.united(QtCore.QRect(point, point))
                if bounds is not None and bounds.isValid():
                    pm = pm.copy(bounds)
            pm = pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            if mirrored:
                pm = pm.transformed(QtGui.QTransform().scale(-1, 1), Qt.SmoothTransformation)
            pm = _tint_pixmap(pm, color)
            if not pm.isNull():
                return pm
    except Exception:
        pass

    # Keep the button usable when the packaged/source PNG is missing or invalid.
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(color, max(2, size // 7), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    center = size / 2
    span = max(3, size * 0.28)
    points = [QPoint(int(center + span), int(center - span)),
              QPoint(int(center - span), int(center)),
              QPoint(int(center + span), int(center + span))]
    if mirrored:
        points = [QPoint(size - point.x(), point.y()) for point in points]
    painter.drawPolyline(points)
    painter.end()
    return pm

def _icon_from_pixmap_variants(pix: QPixmap) -> QIcon:
    icon = QIcon()
    if pix.isNull():
        return icon
    for size in (16, 20, 24, 28, 32, 40, 48, 64, 96, max(pix.width(), pix.height())):
        scaled = pix.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        icon.addPixmap(scaled)
    return icon

def _should_tint_icon_white(path: str) -> bool:
    if not path:
        return False
    path_lower = path.lower()
    if "setting" in path_lower or "gear" in path_lower:
        return False
    if "refresh" in path_lower:
        return False
    return True

def load_white_icon(path: str) -> QIcon:
    if not path:
        return QIcon()
    cached = _WHITE_ICON_CACHE.get(path)
    if cached is not None:
        return cached
    try:
        if not os.path.exists(path):
            icon = QIcon()
        else:
            pm = QPixmap(path)
            if pm.isNull():
                icon = QIcon(path)
            else:
                if _should_tint_icon_white(path):
                    tinted_pm = _tint_pixmap(pm, QColor(Qt.white))
                    icon = _icon_from_pixmap_variants(tinted_pm)
                else:
                    icon = _icon_from_pixmap_variants(pm)
    except Exception:
        icon = QIcon(path)
    _WHITE_ICON_CACHE[path] = icon
    return icon

def _is_dark_mode() -> bool:
    try:
        app = QApplication.instance()
        if not app:
            return False
        c = app.palette().color(QPalette.Window)
        lum = 0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF()
        return lum < 0.5
    except Exception:
        return False

def _app_settings() -> QSettings:
    return QSettings(SETTINGS_ORG, SETTINGS_APP)

def _branch_arrow_icon(direction: str, color: QColor, size: int) -> QPixmap:
    size = max(1, int(size))
    orientation = "down" if direction == "down" else "right"
    base_key = (orientation, size)
    base_pm = _BRANCH_BASE_PIXMAP_CACHE.get(base_key)
    if base_pm is None:
        src = QPixmap(SORT_ICON_DOWN_PATH or "")
        if orientation == "right" and not src.isNull():
            try:
                from PySide6.QtGui import QTransform
                src = src.transformed(QTransform().rotate(-90), Qt.SmoothTransformation)
            except Exception:
                pass
        pm = src
        if pm.isNull():
            base_pm = QPixmap()
        else:
            base_pm = pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        _BRANCH_BASE_PIXMAP_CACHE[base_key] = base_pm
    if base_pm.isNull():
        return base_pm

    if color.isValid():
        tint_color = QColor(color)
    else:
        try:
            app = QApplication.instance()
            if app and _is_dark_mode():
                tint_color = QColor("#e0e0e0")
            else:
                tint_color = QColor("#222222")
        except Exception:
            tint_color = QColor("#222222")

    if not color.isValid():
        try:
            app = QApplication.instance()
            if app and _is_dark_mode():
                tint_color = QColor("#e0e0e0")
            else:
                tint_color = QColor("#222222")
        except Exception:
            tint_color = QColor("#222222")
    else:
        tint_color = QColor(color)

    tint_key = (orientation, size, int(tint_color.rgba()))
    tinted = _BRANCH_TINTED_PIXMAP_CACHE.get(tint_key)
    if tinted is None:
        tinted = _tint_pixmap(base_pm, tint_color)
        _BRANCH_TINTED_PIXMAP_CACHE[tint_key] = tinted
    return tinted

class SortHeader(QHeaderView):
    def __init__(self, orientation, parent=None, icon_up_path=None, icon_down_path=None):
        super().__init__(orientation, parent)
        self._icon_px = 12
        # SortHeader paints its own sorting indicator, so it must initialise
        # its icon tint from the active application palette.
        self._dark_mode = _is_dark_mode()
        self._up_path = icon_up_path or ""
        self._down_path = icon_down_path or ""
        self._pm_up = self._load_icon(self._up_path)
        self._pm_dn = self._load_icon(self._down_path)
        self.setSectionsClickable(True)
        self.setSortIndicatorShown(False)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    def _load_icon(self, path: str) -> QPixmap:
        if not path:
            return QPixmap()

        pm = QPixmap()
        if self._dark_mode:
            try:
                icon = load_white_icon(path)
                pm = icon.pixmap(QSize(self._icon_px, self._icon_px))
            except Exception:
                pm = QPixmap()

        if pm.isNull():
            pm = QPixmap(path or "")
            if self._dark_mode and not pm.isNull():
                pm = _tint_pixmap(pm, QColor(Qt.white))

        if pm.isNull():
            return pm

        return pm.scaled(self._icon_px, self._icon_px, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def set_dark_mode(self, enabled: bool) -> None:
        if self._dark_mode == enabled:
            return
        self._dark_mode = enabled
        self._pm_up = self._load_icon(self._up_path)
        self._pm_dn = self._load_icon(self._down_path)
        self.viewport().update()
        self.update()

    def _ensure_icons_loaded(self):
        if self._pm_up.isNull() and self._up_path:
            self._pm_up = self._load_icon(self._up_path)
        if self._pm_dn.isNull() and self._down_path:
            self._pm_dn = self._load_icon(self._down_path)

    def paintSection(self, painter, rect, logicalIndex):
        # IMPORTANT: do not mutate header state during paint.
        # Toggling sortIndicatorShown inside paintSection can lead to re-entrancy
        # and native crashes (access violations) on some Qt/PySide builds.
        # Temporarily hide native sort indicator to prevent double arrows
        was_shown = self.isSortIndicatorShown()
        if was_shown:
            QHeaderView.setSortIndicatorShown(self, False)
        super().paintSection(painter, rect, logicalIndex)
        if was_shown:
            QHeaderView.setSortIndicatorShown(self, True)

        if not was_shown:
            return
        is_sort_col = (logicalIndex == self.sortIndicatorSection())
        if not is_sort_col:
            return

        self._ensure_icons_loaded()

        is_hovered = False
        is_pressed = False
        try:
            cursor_pos = self.mapFromGlobal(QCursor.pos())
            if rect.contains(cursor_pos):
                is_hovered = True
                if QApplication.mouseButtons() & Qt.LeftButton:
                    is_pressed = True
        except Exception:
            pass

        pm = self._pm_up if self.sortIndicatorOrder() == Qt.AscendingOrder else self._pm_dn

        if not pm.isNull():
            if self._dark_mode:
                pm = _tint_pixmap(pm, QColor("#FFFFFF"))
            else:
                pm = _tint_pixmap(pm, QColor("#000000"))

        if pm.isNull():
            if not self._dark_mode and not (is_hovered or is_pressed):
                return

            painter.save()
            sz = self._icon_px
            text = str(self.model().headerData(logicalIndex, Qt.Horizontal, Qt.DisplayRole) or "")
            x = min(rect.x() + 8 + painter.fontMetrics().horizontalAdvance(text) + 12,
                    rect.right() - sz - 4)
            y = rect.y() + (rect.height() - sz) // 2
            from PySide6.QtGui import QPainterPath
            path = QPainterPath()
            if self.sortIndicatorOrder() == Qt.AscendingOrder:
                path.moveTo(x, y + sz); path.lineTo(x + sz, y + sz); path.lineTo(x + sz, y); path.closeSubpath()
            else:
                path.moveTo(x, y); path.lineTo(x + sz, y); path.lineTo(x + sz, y + sz); path.closeSubpath()
            painter.setPen(Qt.NoPen)

            if is_hovered or is_pressed:
                if self._dark_mode:
                    painter.setBrush(QColor("#e0e0e0"))
                else:
                    painter.setBrush(QColor("#888888"))
            else:
                painter.setBrush(QColor("#f0f0f0"))

            painter.drawPath(path)
            painter.restore()
            return

        text = str(self.model().headerData(logicalIndex, Qt.Horizontal, Qt.DisplayRole) or "")
        text_w = painter.fontMetrics().horizontalAdvance(text)
        # Keep a clear visual gap between the header label and sort arrow.
        x = min(rect.x() + 8 + text_w + 12, rect.right() - pm.width() - 4)
        y = rect.y() + (rect.height() - pm.height()) // 2

        if not pm.isNull():
            painter.save()
            painter.drawPixmap(x, y, pm)
            painter.restore()

    def sectionSizeFromContents(self, logicalIndex):
        sz = super().sectionSizeFromContents(logicalIndex)
        h = max(sz.height(), self._icon_px + 6)
        extra_w = self._icon_px + 8
        return QSize(sz.width() + extra_w, h)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        self.viewport().update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.viewport().update()


class ThemeToggle(QtWidgets.QWidget):
    toggled = QtCore.Signal(bool)

    def __init__(self, sun_icon_path: str = "", moon_icon_path: str = "", parent=None):
        del sun_icon_path, moon_icon_path
        super().__init__(parent)
        from larix_nexus.widgets import ThemeTogglePdfStyle

        self._toggle = ThemeTogglePdfStyle(self)
        self._toggle.setFixedSize(66, 28)
        self._toggle.setGeometry(self.rect())
        # Clip only the main-window wrapper to the pill; PDF Compare keeps
        # its rectangular ThemeTogglePdfStyle variant.
        self._toggle._clip_to_track = True
        self._toggle._update_track_mask()

        self.setObjectName("themeToggle")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(66, 28)

        self._toggle.toggled.connect(self.toggled)

    def isChecked(self) -> bool:
        return self._toggle.isChecked()

    def setChecked(self, checked: bool, animate: bool = True) -> None:
        self._toggle.setChecked(checked, animate=animate)

    def resizeEvent(self, event):
        self._toggle.setGeometry(self.rect())
        super().resizeEvent(event)

    def snap_to_state(self) -> None:
        self.update()


class ColumnsPopup(QWidget):
    toggled = QtCore.Signal(int, bool)
    def __init__(self, table: QTableView, parent=None):
        flags = Qt.Popup | Qt.FramelessWindowHint
        super().__init__(parent, flags)
        self.setObjectName("columnsPopup")
        self.table = table
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self._cb_style = NikCheckBoxStyle()

        self.wrap = QFrame(self)
        self.wrap.setObjectName("propsCard")

        self.vl = QVBoxLayout(self.wrap); self.vl.setContentsMargins(8,8,8,8); self.vl.setSpacing(4)
        lay = QVBoxLayout(self); lay.setContentsMargins(0,0,0,0); lay.addWidget(self.wrap)

        self._checks = []
        self.rebuild()

    def rebuild(self):
        for i in reversed(range(self.vl.count())):
            w = self.vl.itemAt(i).widget()
            if w: w.deleteLater()
        self._checks.clear()

        model = self.table.model()
        if not model: return
        cols = model.columnCount()

        for col in range(1, cols):
            title = model.headerData(col, Qt.Horizontal) or f"Столбец {col}"
            # IMPORTANT: Skip critical columns (checkbox, createdBy, createTime, status)
            if col in [0, 5, 6, 9] or str(title).strip().lower() == "замечания":
                continue
            cb = QCheckBox(str(title), self.wrap)
            cb.setStyle(self._cb_style)
            cb.setProperty("menuitem", True)
            try:
                cb.setChecked(not self.table.isColumnHidden(col))
            except Exception:
                cb.setChecked(True)
            def _on_toggle(on, c=col):
                try:
                    self.table.setColumnHidden(c, not on)
                except Exception:
                    pass
                try:
                    mw = self.window()
                    if hasattr(mw, '_save_columns_visibility'):
                        mw._save_columns_visibility()
                except Exception:
                    pass
            cb.toggled.connect(_on_toggle)
            self.vl.addWidget(cb)
            self._checks.append(cb)

        row = QWidget(self.wrap); hl = QHBoxLayout(row); hl.setContentsMargins(0,6,0,0)
        btn_all = QPushButton("Показать все", row); btn_none = QPushButton("Скрыть все", row)
        btn_all.setProperty("secondary", True); btn_none.setProperty("secondary", True)
        btn_all.clicked.connect(lambda: [cb.setChecked(True) for cb in self._checks])
        btn_none.clicked.connect(lambda: [cb.setChecked(False) for cb in self._checks])
        hl.addWidget(btn_all); hl.addWidget(btn_none)
        self.vl.addWidget(row)

    def open_for(self, anchor: QWidget):
        self.rebuild()
        pos = anchor.mapToGlobal(QPoint(0, anchor.height()))
        self.move(pos)
        self.show()


class _OperationPathLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._full_text = ""
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumWidth(40)

    def set_full_text(self, text: str) -> None:
        self._full_text = str(text or "")
        self.setToolTip(self._full_text)
        self._refresh_text()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_text()

    def _refresh_text(self) -> None:
        metrics = QFontMetrics(self.font())
        self.setText(metrics.elidedText(self._full_text, Qt.ElideMiddle, max(20, self.width())))


class FileOperationStatusWidget(QFrame):
    """Content of the single persistent status card."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dark = False
        self._cancel_callback = None
        self._direction = "right"
        self._mode = None
        self.setObjectName("fileOperationStatus")
        self.setFixedHeight(36)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(8)

        self.title_label = QLabel(self)
        self.status_label = self.title_label
        self.title_label.setMinimumWidth(120)
        layout.addWidget(self.title_label, 1)

        separator = QFrame(self)
        separator.setFrameShape(QFrame.VLine)
        separator.setFrameShadow(QFrame.Plain)
        separator.setFixedHeight(22)
        layout.addWidget(separator)

        self.from_caption = QLabel(self)
        self.from_caption.setText(t("status.operation_from"))
        self.source_label = _OperationPathLabel(self)
        self.to_caption = QLabel(self)
        self.to_caption.setText(t("status.operation_to"))
        self.destination_label = _OperationPathLabel(self)
        layout.addWidget(self.from_caption)
        layout.addWidget(self.source_label, 2)

        self.arrow_label = QLabel(self)
        self.arrow_label.setFixedSize(20, 20)
        self.arrow_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.arrow_label)

        layout.addWidget(self.to_caption)
        layout.addWidget(self.destination_label, 2)

        self.progress = RainbowStatusProgress(self, width=265, height=6, interval_ms=40)
        self.progress_bar = self.progress  # compatibility alias; this is the only progress widget
        self.progress.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        layout.addWidget(self.progress, 0, Qt.AlignRight)

        self.cancel_button = QPushButton(t("common.cancel"), self)
        self.cancel_button.setObjectName("fileOperationCancel")
        self.cancel_button.setFixedHeight(26)
        self.cancel_button.clicked.connect(self._cancel)
        layout.addWidget(self.cancel_button)
        self._route_widgets = (
            separator,
            self.from_caption,
            self.source_label,
            self.arrow_label,
            self.to_caption,
            self.destination_label,
        )
        self._apply_visuals()
        self.progress.hide()

    def start_transfer(self, operation: str, source_path: str, destination_path: str, total: int, cancel_callback=None):
        self._mode = "transfer"
        self.set_cancel_callback(cancel_callback)
        key = "status.copy_operation" if operation == "copy" else "status.move_operation"
        self.title_label.setText(t(key))
        self.source_label.set_full_text(source_path)
        self.destination_label.set_full_text(destination_path)
        for widget in self._route_widgets:
            widget.show()
        self.set_progress(0, total)
        self.show()
        self.progress.show()
        self.raise_()
        self._apply_visuals()

    def start_generic(self, title: str, total=None, cancel_callback=None):
        self._mode = "generic"
        self.set_cancel_callback(cancel_callback)
        self.set_generic_title(title)
        for widget in self._route_widgets:
            widget.hide()
        self.set_progress(0, total)
        self.show()
        self.progress.show()
        self.raise_()
        self._apply_visuals()

    # Backwards-compatible name for existing callers.
    start = start_transfer

    def set_generic_title(self, title: str) -> None:
        self.set_status_text(title or t("status.loading"))

    def set_status_text(self, text: str) -> None:
        self.title_label.setText(str(text or ""))
        self.title_label.setToolTip(str(text or ""))

    def set_cancel_callback(self, callback=None) -> None:
        self._cancel_callback = callback
        self.cancel_button.setEnabled(callback is not None)
        self.cancel_button.setVisible(callback is not None)

    def set_progress(self, current: int, total: int, item_message: str = "") -> None:
        if total is None:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, max(0, int(total)))
        self.progress.setValue(max(0, int(current)))
        if item_message:
            self.progress.setToolTip(str(item_message))

    def finish(self) -> None:
        self._cancel_callback = None
        self._mode = None
        self.progress.hide()
        for widget in self._route_widgets:
            widget.hide()
        self.cancel_button.setEnabled(False)
        self.cancel_button.hide()

    reset = finish

    def set_direction(self, direction: str) -> None:
        self._direction = "left" if direction == "left" else "right"
        self._update_arrow()

    def set_dark_theme(self, dark: bool) -> None:
        self._dark = bool(dark)
        self._apply_visuals()

    def _cancel(self) -> None:
        callback = self._cancel_callback
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText(t("status.cancelling"))
        if callback is not None:
            callback()

    def _update_arrow(self) -> None:
        pixmap = QPixmap(rsrc_path("icon", "strelka.png"))
        if pixmap.isNull():
            self.arrow_label.clear()
            return
        if self._dark:
            tinted = QPixmap(pixmap.size())
            tinted.fill(Qt.transparent)
            painter = QPainter(tinted)
            painter.drawPixmap(0, 0, pixmap)
            painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
            painter.fillRect(tinted.rect(), QColor(Qt.white))
            painter.end()
            pixmap = tinted
        if self._direction == "left":
            pixmap = pixmap.transformed(QTransform().rotate(180), Qt.SmoothTransformation)
        self.arrow_label.setPixmap(pixmap.scaled(18, 18, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _apply_visuals(self) -> None:
        text = "#ffffff" if self._dark else "#222222"
        border = "#383838" if self._dark else "#e5e5e5"
        self.setStyleSheet(
            "QFrame#fileOperationStatus { background: transparent; border: 0; }"
            f"QLabel {{ color: {text}; }}"
            f"QPushButton#fileOperationCancel {{ color: {text}; background: transparent; border: 1px solid {border}; border-radius: 14px; padding: 0 14px; }}"
        )
        self._update_arrow()


class FileOperationStatusShell(QFrame):
    """Persistent inset card hosting the operation status content."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("fileOperationStatusShell")
        self.setFixedHeight(36 + 2 * STATUS_CARD_OUTER_GAP)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(22, STATUS_CARD_OUTER_GAP, 22, STATUS_CARD_OUTER_GAP)
        outer.setSpacing(0)

        self.card = QFrame(self)
        self.card.setObjectName("unifiedStatusCard")
        self.card.setAttribute(Qt.WA_StyledBackground, True)
        self.card.setFixedHeight(36)
        self.card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        card_layout = QHBoxLayout(self.card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)
        self.operation_widget = FileOperationStatusWidget(self.card)
        card_layout.addWidget(self.operation_widget)
        outer.addWidget(self.card)
        self.set_dark_theme(False)

    def set_dark_theme(self, dark: bool) -> None:
        background = "#1e1e1e" if dark else "#ffffff"
        border = "#383838" if dark else "#dedede"
        text = "#ffffff" if dark else "#222222"
        self.card.setStyleSheet(
            f"QFrame#unifiedStatusCard {{ background-color: {background}; "
            f"border: 1px solid {border}; border-radius: 10px; color: {text}; }}"
            f"QFrame#unifiedStatusCard QLabel {{ background: transparent; color: {text}; }}"
        )


# Public name for the single persistent status card.  Keep the old name for
# compatibility with existing callers.
UnifiedStatusCard = FileOperationStatusShell


class RainbowStatusProgress(QWidget):
    """Status-bar rainbow progress line (Lottie-inspired, pure QPainter).

    Visual reference: statusbar/e2d8ba6a-117d-11ee-b9ea-eb18c4ade269.lottie
    """
    rangeChanged = QtCore.Signal(int, int)
    valueChanged = QtCore.Signal(int)

    _TRACK_COLOR = QColor(245, 245, 245)
    _GRADIENT_STOPS = (
        (0.0, 0.973, 0.675, 0.545),
        (0.133, 0.982, 0.747, 0.475),
        (0.266, 0.992, 0.820, 0.404),
        (0.573, 0.976, 0.663, 0.357),
        (0.700, 0.961, 0.506, 0.310),
        (0.850, 0.625, 0.461, 0.624),
        (1.0, 0.290, 0.416, 0.937),
    )

    def __init__(self, parent=None, width: int = 220, height: int = 16, interval_ms: int = 40):
        super().__init__(parent)
        self._bar_w = int(width)
        self._bar_h = int(height)
        self._min = 0
        self._max = 0
        self._val = 0
        self._indeterminate = True
        self._phase = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(int(interval_ms))
        try:
            self._timer.setTimerType(Qt.CoarseTimer)
        except Exception:
            pass
        self._timer.timeout.connect(self._tick)
        self.setFixedSize(self._bar_w, self._bar_h)

    def setRange(self, mn: int, mx: int):
        self._min, self._max = int(mn), int(mx)
        self._indeterminate = (mn == 0 and mx == 0)
        self.rangeChanged.emit(self._min, self._max)
        if self.isVisible():
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def setValue(self, v: int):
        self._val = int(v)
        self.valueChanged.emit(self._val)
        self.update()

    def minimum(self) -> int:
        return self._min

    def maximum(self) -> int:
        return self._max

    def value(self) -> int:
        return self._val

    def setVisible(self, on: bool):
        super().setVisible(on)
        if on:
            self._timer.start()
        else:
            self._timer.stop()

    def sizeHint(self):
        return QSize(self._bar_w, self._bar_h)

    def _tick(self):
        # ~5.56 s loop (139 frames @ 25 fps in reference Lottie)
        self._phase = (self._phase + self._timer.interval() / 5560.0) % 1.0
        self.update()

    def _rainbow_gradient(self, x0: float, span: float) -> QLinearGradient:
        grad = QLinearGradient(x0, 0, x0 + span, 0)
        for pos, r, g, b in self._GRADIENT_STOPS:
            grad.setColorAt(pos, QColor(int(r * 255), int(g * 255), int(b * 255)))
        return grad

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        margin_x = 2.0
        track_w = max(1.0, w - 2 * margin_x)
        cy = h / 2.0
        pen_w = max(3.0, min(4.0, h * 0.25))

        track_pen = QPen(self._TRACK_COLOR)
        track_pen.setWidthF(pen_w)
        track_pen.setCapStyle(Qt.RoundCap)
        p.setPen(track_pen)
        p.drawLine(QPointF(margin_x, cy), QPointF(margin_x + track_w, cy))

        if self._indeterminate:
            seg = 0.42
            pos = (self._phase % 1.0) * (1.0 + seg) - seg
            x0 = margin_x + pos * track_w
            x1 = x0 + seg * track_w
        else:
            total = max(1, self._max - self._min)
            frac = max(0.0, min(1.0, (self._val - self._min) / total))
            x0 = margin_x
            x1 = margin_x + frac * track_w
            if x1 <= x0:
                p.end()
                return

        clip = QRectF(x0, 0.0, max(1.0, x1 - x0), h)
        grad = self._rainbow_gradient(margin_x, track_w)
        bar_pen = QPen(QBrush(grad), pen_w)
        bar_pen.setCapStyle(Qt.RoundCap)
        p.setPen(bar_pen)
        p.setClipRect(clip)
        p.drawLine(QPointF(margin_x, cy), QPointF(margin_x + track_w, cy))
        p.setClipping(False)
        p.end()


class BusyDots(QWidget):
    def __init__(self, parent=None, color="#F7921E", dots=5, r_min=2, r_max=4, spacing=6, interval_ms=80):
        super().__init__(parent)
        self.color = QColor(color)
        self.dots = int(dots)
        self.r_min, self.r_max = float(r_min), float(r_max)
        self.spacing = int(spacing)
        self._t = 0.0
        self._min = 0
        self._max = 0
        self._val = 0
        self._indeterminate = True

        self._timer = QTimer(self)
        self._timer.setInterval(int(interval_ms))
        self._timer.timeout.connect(self._tick)

        step = int(2*self.r_max + self.spacing)
        w = self.dots * step - self.spacing
        h = int(2*self.r_max + 4)
        self.setFixedSize(w, h)

    def setRange(self, mn: int, mx: int):
        self._min, self._max = int(mn), int(mx)
        self._indeterminate = (mn == 0 and mx == 0)
        if self.isVisible():
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def setValue(self, v: int):
        self._val = int(v)
        self.update()

    def setVisible(self, on: bool):
        super().setVisible(on)
        if on:
            self._timer.start()
        else:
            self._timer.stop()

    def sizeHint(self):
        return QSize(self.width(), self.height())

    def _tick(self):
        self._t = (self._t + 0.12) % 1000.0
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        cy = self.height() / 2.0
        step = 2*self.r_max + self.spacing

        if self._indeterminate:
            for i in range(self.dots):
                phase = (self._t - i*0.25) * 2.0 * math.pi
                s = (math.sin(phase) + 1.0) * 0.5
                r = self.r_min + s * (self.r_max - self.r_min)
                c = QColor(self.color); c.setAlpha(80 + int(s * 175))
                p.setBrush(c); p.setPen(Qt.NoPen)
                cx = i * step + self.r_max
                p.drawEllipse(QtCore.QRectF(cx - r, cy - r, 2*r, 2*r))
        else:
            total = max(1, self._max - self._min)
            frac = max(0.0, min(1.0, (self._val - self._min) / total))
            target = frac * self.dots
            for i in range(self.dots):
                s = max(0.0, min(1.0, target - i))
                if 0.0 < s < 1.0:
                    s = max(0.0, min(1.0, s + 0.15*math.sin(self._t*2*math.pi)))
                r = self.r_min + s * (self.r_max - self.r_min)
                c = QColor(self.color); c.setAlpha(60 + int(s * 195))
                p.setBrush(c); p.setPen(Qt.NoPen)
                cx = i * step + self.r_max
                p.drawEllipse(QtCore.QRectF(cx - r, cy - r, 2*r, 2*r))
        p.end()


class WaitDialog(QDialog):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setModal(True)
        try:
            self.setWindowTitle(t("common.please_wait"))
        except Exception:
            self.setWindowTitle(t("common.please_wait"))
        self.setWindowTitle(t("common.please_wait"))
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.CustomizeWindowHint | Qt.WindowCloseButtonHint)
        try:
            self.setWindowTitle(t("common.please_wait"))
        except Exception:
            pass
        try:
            if ICON_PATH and os.path.exists(ICON_PATH):
                self.setWindowIcon(QIcon(ICON_PATH))
        except Exception:
            pass

        app = QApplication.instance()
        if app:
            current_theme = getattr(app, "nik_theme", THEME_LIGHT)
            is_dark = current_theme == THEME_DARK
            _set_window_theme_dark(self, dark=is_dark)

        row = QHBoxLayout(); row.setContentsMargins(12,10,12,12); row.setSpacing(8)
        self._lbl = QLabel(text, self)
        self._lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        spinner = BusyDots(self)
        spinner.setRange(0, 0)
        spinner.setVisible(True)
        self._spinner = spinner
        row.addWidget(self._lbl, 1)
        row.addWidget(spinner, 0, Qt.AlignRight | Qt.AlignVCenter)

        lay = QVBoxLayout(self)
        lay.addLayout(row)
        self.setLayout(lay)
        self.resize(400, 80)
        QTimer.singleShot(0, lambda: QApplication.processEvents())

    def set_message(self, text: str):
        self._lbl.setText(text)
        self._adjust_width_to_content()
        QApplication.processEvents()

    def _adjust_width_to_content(self) -> None:
        try:
            fm = self._lbl.fontMetrics()
            text = self._lbl.text()
            text_width = fm.horizontalAdvance(text)
            spinner_width = 50
            margins = 12 * 2
            spacing = 8
            required_width = text_width + spinner_width + margins + spacing + 40
            current_width = self.width()
            if required_width > current_width:
                new_width = min(required_width, 800)
                self.resize(new_width, self.height())
        except Exception:
            pass

    def set_done(self, text: str, auto_close_ms: int = 1800):
        self._spinner.setVisible(False)
        self._lbl.setText(text)
        self._adjust_width_to_content()
        try:
            QTimer.singleShot(max(200, int(auto_close_ms)), self.accept)
        except Exception:
            pass


class NikCheckBoxStyle(QProxyStyle):
    """Proxy style that draws menu-like checkbox indicators."""

    def drawPrimitive(self, element, option, painter, widget=None):
        if element == QStyle.PE_IndicatorBranch:
            if not (option.state & QStyle.State_Children):
                return super().drawPrimitive(element, option, painter, widget)

            dark_attr = None
            try:
                dark_attr = getattr(widget, "_dark_theme") if widget is not None else None
            except Exception:
                dark_attr = None
            dark = bool(dark_attr) if dark_attr is not None else _is_dark_mode()

            color = QColor("#fefefe") if dark else QColor("#010101")
            if option.state & (QStyle.State_MouseOver | QStyle.State_Selected):
                color = QColor("#F7921E")

            rect = option.rect.adjusted(1, 1, -1, -1)
            icon_sz = int(max(8, min(rect.width(), rect.height(), 10)))
            direction = "down" if (option.state & QStyle.State_Open) else "right"
            pm = _branch_arrow_icon(direction, color, icon_sz)
            if not pm.isNull():
                painter.save()
                painter.setRenderHint(QPainter.Antialiasing, True)
                x = rect.x() + (rect.width() - pm.width()) / 2
                y = rect.y() + (rect.height() - pm.height()) / 2
                painter.drawPixmap(int(x), int(y), pm)
                painter.restore()
                return
        return super().drawPrimitive(element, option, painter, widget)


class CircularProcessSpinner(QWidget):
    """Small native orange spinner used by the upload conflict list."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(16, 16)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(35)
        self._timer.timeout.connect(self._advance)

    @property
    def timer(self) -> QTimer:
        return self._timer

    def _advance(self) -> None:
        self._angle = (self._angle + 8) % 360
        self.update()

    def set_running(self, running: bool) -> None:
        if running:
            if not self._timer.isActive():
                self._timer.start()
        elif self._timer.isActive():
            self._timer.stop()
        self.setVisible(running)
        if running:
            self.update()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        center = QPointF(self.width() / 2.0, self.height() / 2.0)
        radius = min(self.width(), self.height()) / 2.0 - 2.0
        segment_count = 12
        segment_span = 292.0 / segment_count
        rect = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
        for index in range(segment_count):
            alpha = int(55 + 200 * ((index + 1) / segment_count) ** 1.6)
            color = QColor(ACCENT_PRIMARY)
            color.setAlpha(alpha)
            pen = QPen(color)
            pen.setWidthF(3.25)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            start = self._angle + index * segment_span
            painter.drawArc(rect, int(start * 16), -int((segment_span - 1.4) * 16))


class ConflictListItem(QWidget):
    def __init__(self, file_icon: QIcon, name: str, status_icons: dict[str, QIcon], parent: QWidget | None = None):
        super().__init__(parent)
        self._status_icons = status_icons

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        self.icon_label = QLabel(self)
        self.icon_label.setFixedSize(24, 24)
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setScaledContents(False)
        self.set_icon(file_icon)

        self.name_label = QLabel(name, self)
        self.name_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.name_label.setWordWrap(True)

        layout.addWidget(self.icon_label, 0, Qt.AlignTop)
        layout.addWidget(self.name_label, 1, Qt.AlignTop)

        self.status_label = QLabel(self)
        self.status_label.setFixedSize(16, 16)
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setScaledContents(False)
        layout.addWidget(self.status_label, 0, Qt.AlignTop)

    def set_icon(self, icon: QIcon | None):
        if isinstance(icon, QIcon) and not icon.isNull():
            dpr = max(1.0, float(self.devicePixelRatioF()))
            width = max(1, round(self.icon_label.width() * dpr))
            height = max(1, round(self.icon_label.height() * dpr))
            pixmap = icon.pixmap(width, height)
            pixmap.setDevicePixelRatio(dpr)
            self.icon_label.setPixmap(pixmap)
        else:
            self.icon_label.clear()

    def set_status(self, status: str, tooltip: str = "") -> None:
        icon = self._status_icons.get(status)
        if icon is None or icon.isNull():
            self.status_label.clear()
        else:
            dpr = max(1.0, float(self.devicePixelRatioF()))
            width = max(1, round(self.status_label.width() * dpr))
            height = max(1, round(self.status_label.height() * dpr))
            pixmap = icon.pixmap(width, height)
            pixmap.setDevicePixelRatio(dpr)
            self.status_label.setPixmap(pixmap)
        self.status_label.setToolTip(tooltip or "")

    def set_name(self, name: str) -> None:
        self.name_label.setText(name)

    def set_active(self, active: bool) -> None:
        font = self.name_label.font()
        font.setBold(active)
        self.name_label.setFont(font)


class PillConnector(QWidget):
    def __init__(self, parent=None, color="#FFA74B"):
        super().__init__(parent)
        self._color = QColor(color)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def sizeHint(self):
        return QSize(6, 22)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = self.rect().adjusted(0, 0, -1, -1)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self._color))
        radius = r.width() / 2.0
        p.drawRoundedRect(r, radius, radius)


class StickyMenu(QMenu):
    def mouseReleaseEvent(self, e):
        p = e.position().toPoint() if hasattr(e, "position") else e.pos()
        act = self.actionAt(p)
        if act is not None and act.isCheckable() and act.isEnabled():
            act.toggle()
            e.accept()
            return
        super().mouseReleaseEvent(e)


class HeaderCheckButton(QAbstractButton):
    BOX = 18
    RADIUS = 4
    BORDER_W = 2
    stateChanged = QtCore.Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        # Visual state is tracked separately to avoid calling into Qt's
        # internal check state during model reset (can hard-crash on Windows).
        self._visual_checked = False
        self._partial = False
        self._setting_checked = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setMouseTracking(True)
        self.setFixedSize(self.BOX, self.BOX)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.toggled.connect(self._on_toggled)

    def sizeHint(self):
        return QSize(self.BOX, self.BOX)

    def minimumSizeHint(self):
        return QSize(self.BOX, self.BOX)

    def _on_toggled(self, checked):
        if self._setting_checked:
            return

        # Keep visual state in sync with user interaction.
        try:
            self._visual_checked = bool(checked)
        except Exception:
            self._visual_checked = False

        if self._partial:
            self._partial = False
        state_int = self._checkStateAsInt()
        self.stateChanged.emit(state_int)

    def setPartial(self, v: bool):
        old_partial = self._partial
        self._partial = bool(v)
        if old_partial != self._partial:
            self.stateChanged.emit(self._checkStateAsInt())

    def isPartial(self) -> bool:
        return self._partial

    def setCheckState(self, st: int):
        # IMPORTANT: do NOT call QAbstractButton.setChecked() here.
        # During model resets Qt can still be processing events and calling into
        # a stale wrapper; calling setChecked() may trigger a native crash.
        if st == Qt.Checked:
            self._visual_checked = True
            self._partial = False
        elif st == Qt.Unchecked:
            self._visual_checked = False
            self._partial = False
        else:
            self._visual_checked = False
            self._partial = True

        try:
            if not self.signalsBlocked():
                self.stateChanged.emit(self._checkStateAsInt())
        except Exception:
            pass
        try:
            self.update()
        except Exception:
            pass

    def checkState(self) -> int:
        if getattr(self, "_visual_checked", False):
            return Qt.Checked
        return Qt.PartiallyChecked if self._partial else Qt.Unchecked

    def _checkStateAsInt(self) -> int:
        state = self.checkState()
        if hasattr(state, 'value'):
            return int(state.value)
        return int(state)

    def setChecked(self, on: bool):
        prev = bool(getattr(self, "_visual_checked", False))
        self._setting_checked = True
        try:
            super().setChecked(on)
        finally:
            self._setting_checked = False

        # Always keep visual state updated.
        try:
            self._visual_checked = bool(on)
        except Exception:
            self._visual_checked = False

        if prev != on:
            if self._partial:
                self._partial = False
            self.stateChanged.emit(self._checkStateAsInt())

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        size = min(self.BOX, min(self.width(), self.height()))
        x = (self.width() - size) // 2
        y = (self.height() - size) // 2

        dark = _is_dark_mode()
        checked = getattr(self, "_visual_checked", False)
        partial = getattr(self, "_partial", False)
        hovered = self.underMouse()
        pressed = self.isDown()

        if checked:
            icon_path = CHECK_ICON_ON_PATH
        elif partial:
            icon_path = CHECK_ICON_MID_PATH
        else:
            icon_path = CHECK_ICON_OFF_PATH

        pm = QPixmap()
        try:
            if dark:
                icon = load_white_icon(icon_path)
                pm = icon.pixmap(int(size), int(size))
            else:
                base_pm = QPixmap(icon_path)
                if not base_pm.isNull():
                    pm = base_pm.scaled(int(size), int(size), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        except Exception:
            pm = QPixmap()

        if pm.isNull():
            try:
                base_pm = QPixmap(icon_path)
                if not base_pm.isNull():
                    if dark:
                        base_pm = _tint_pixmap(base_pm, QColor(Qt.white))
                    pm = base_pm.scaled(int(size), int(size), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            except Exception:
                pass

        if not pm.isNull():
            px = int(x + (size - pm.width()) // 2)
            py = int(y + (size - pm.height()) // 2)
            p.drawPixmap(px, py, pm)
        else:
            rect = QtCore.QRectF(x, y, size, size)
            p.setBrush(QBrush(QColor("#ffffff") if not dark else QColor("#2a2a2a")))
            p.setPen(QPen(QColor("#cccccc") if not dark else QColor("#777777"), 1))
            p.drawRoundedRect(rect, self.RADIUS, self.RADIUS)

        if (hovered or pressed) and not pm.isNull():
            overlay_rect = QtCore.QRectF(x, y, size, size)
            overlay_alpha = 26 if hovered and not pressed else 51
            if dark:
                overlay_alpha = 36 if hovered and not pressed else 64
            p.setBrush(QBrush(QColor(0, 0, 0, overlay_alpha)))
            p.setPen(Qt.NoPen)
            r = self.RADIUS
            clip_path = QtGui.QPainterPath()
            clip_path.addRoundedRect(overlay_rect, r, r)
            p.setClipPath(clip_path)
            p.drawRect(overlay_rect.toRect())
            p.setClipping(False)

        p.end()


class ItemViewNoNativeHighlightStyle(QProxyStyle):
    """Suppress native focus/drop primitives for item views."""

    def drawPrimitive(self, element, option, painter, widget=None):
        if element in (QStyle.PE_FrameFocusRect, QStyle.PE_IndicatorItemViewItemDrop):
            return
        if element in (QStyle.PE_PanelItemViewItem, QStyle.PE_PanelItemViewRow) and option is not None:
            try:
                opt = QStyleOptionViewItem(option)
                opt.state &= ~QStyle.State_Selected
                opt.state &= ~QStyle.State_HasFocus
                opt.state &= ~QStyle.State_MouseOver
                return super().drawPrimitive(element, opt, painter, widget)
            except Exception:
                pass
        return super().drawPrimitive(element, option, painter, widget)

    def drawControl(self, element, option, painter, widget=None):
        if element == QStyle.CE_ItemViewItem and option is not None:
            opt = QStyleOptionViewItem(option)
            opt.state &= ~QStyle.State_Selected
            opt.state &= ~QStyle.State_HasFocus
            opt.state &= ~QStyle.State_MouseOver
            try:
                opt.showDecorationSelected = False
            except Exception:
                pass
            return super().drawControl(element, opt, painter, widget)
        return super().drawControl(element, option, painter, widget)

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint in (QStyle.SH_ItemView_ShowDecorationSelected, QStyle.SH_ItemView_ChangeHighlightOnFocus):
            return 0
        return super().styleHint(hint, option, widget, returnData)


class ScrollbarProxyStyle(QProxyStyle):
    """Прокси-стиль для скругленных скроллбаров с минимальной длиной ползунка."""
    def __init__(self, base_style=None, arrow_paths=None, arrow_color=None, track_color=None):
        super().__init__(base_style)
        self._arrow_paths = dict(arrow_paths or {})
        self._arrow_color = QColor(arrow_color or "#E0E0E0")
        self._track_color = QColor(track_color or "#202020")
        self._arrow_cache = {}

    def pixelMetric(self, metric, option=None, widget=None):
        if metric == QStyle.PM_ScrollBarSliderMin:
            return SCROLLBAR_SLIDER_MIN
        return super().pixelMetric(metric, option, widget)

    def drawControl(self, element, option, painter, widget=None):
        if element in (QStyle.CE_ScrollBarAddLine, QStyle.CE_ScrollBarSubLine):
            orientation = getattr(option, "orientation", Qt.Vertical)
            horizontal = orientation == Qt.Horizontal
            if horizontal:
                key = "right" if element == QStyle.CE_ScrollBarAddLine else "left"
            else:
                key = "down" if element == QStyle.CE_ScrollBarAddLine else "up"

            painter.save()
            painter.fillRect(option.rect, self._track_color)
            path = self._arrow_paths.get(key, "")
            if path:
                cache_key = (key, path, self._arrow_color.name(), max(1, min(option.rect.width(), option.rect.height()) - 4))
                pm = self._arrow_cache.get(cache_key)
                if pm is None:
                    source = QPixmap(path)
                    if not source.isNull():
                        size = cache_key[-1]
                        source = source.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        pm = _tint_pixmap(source, self._arrow_color)
                    else:
                        pm = QPixmap()
                    self._arrow_cache[cache_key] = pm
                if not pm.isNull():
                    painter.drawPixmap(
                        option.rect.center() - QPoint(pm.width() // 2, pm.height() // 2),
                        pm,
                    )
            painter.restore()
            return
        if element == QStyle.CE_ScrollBarSlider:
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)

            try:
                is_dark = _is_dark_mode()
            except Exception:
                is_dark = False

            # Match button highlight feel: subtle hover/pressed tints.
            pressed = bool(option.state & QStyle.State_Sunken)
            hovered = bool(option.state & QStyle.State_MouseOver)

            if pressed:
                fill = QColor(247, 146, 30, int(255 * 0.25))
                stroke = QColor("#E07E12")
            elif hovered:
                fill = QColor(247, 146, 30, int(255 * 0.15))
                stroke = QColor("#FFA74B")
            else:
                fill = QColor(247, 146, 30, int(255 * 0.12))
                stroke = QColor("#FFA74B")

            painter.setBrush(QBrush(fill))
            painter.setPen(QPen(stroke, 1))
            r = option.rect.adjusted(0, 0, -1, -1)
            painter.drawRoundedRect(r, 6, 6)
            painter.restore()
            return

        super().drawControl(element, option, painter, widget)


class TreeBranchProxyStyle(QProxyStyle):
    """Proxy style for QTreeWidget/QTreeView branch arrows.
    Draws theme-aware chevrons (right for closed, down for open) and keeps them readable on hover/selection.
    """
    def __init__(self, base_style=None):
        super().__init__(base_style)

    def drawPrimitive(self, element, option, painter, widget=None):
        if element in (QStyle.PE_FrameFocusRect, QStyle.PE_IndicatorItemViewItemDrop):
            return
        if element in (QStyle.PE_PanelItemViewItem, QStyle.PE_PanelItemViewRow) and option is not None:
            try:
                opt = QStyleOptionViewItem(option)
                opt.state &= ~QStyle.State_Selected
                opt.state &= ~QStyle.State_HasFocus
                opt.state &= ~QStyle.State_MouseOver
                return super().drawPrimitive(element, opt, painter, widget)
            except Exception:
                pass
        if element == QStyle.PE_IndicatorBranch:
            # Never let native style paint branch background/selection stripes.
            if not (option.state & QStyle.State_Children):
                return

            dark_attr = None
            try:
                dark_attr = getattr(widget, "_dark_theme") if widget is not None else None
            except Exception:
                dark_attr = None
            dark = bool(dark_attr) if dark_attr is not None else _is_dark_mode()

            color = QColor("#e0e0e0") if dark else QColor("#222222")

            is_row_hovered = False
            if widget:
                try:
                    cursor_pos = widget.mapFromGlobal(QCursor.pos())
                    if option.rect.top() <= cursor_pos.y() <= option.rect.bottom():
                        if 0 <= cursor_pos.x() < widget.width():
                            is_row_hovered = True
                except Exception:
                    pass

            has_state_hover = bool(option.state & (QStyle.State_MouseOver | QStyle.State_Selected))

            if is_row_hovered or has_state_hover:
                color = QColor("#000000")

            rect = option.rect.adjusted(1, 1, -1, -1)
            icon_sz = int(max(8, min(rect.width(), rect.height(), 10)))
            direction = "down" if (option.state & QStyle.State_Open) else "right"
            pm = _branch_arrow_icon(direction, color, icon_sz)
            if not pm.isNull():
                painter.save()
                painter.setRenderHint(QPainter.Antialiasing, True)
                x = rect.x() + (rect.width() - pm.width()) / 2
                y = rect.y() + (rect.height() - pm.height()) / 2
                painter.drawPixmap(int(x), int(y), pm)
                painter.restore()
            # Always return to prevent default branch background
            return
        return super().drawPrimitive(element, option, painter, widget)

    def drawControl(self, element, option, painter, widget=None):
        if element == QStyle.CE_ItemViewItem and option is not None:
            try:
                opt = QStyleOptionViewItem(option)
                opt.state &= ~QStyle.State_Selected
                opt.state &= ~QStyle.State_HasFocus
                opt.state &= ~QStyle.State_MouseOver
                opt.showDecorationSelected = False
                return super().drawControl(element, opt, painter, widget)
            except Exception:
                pass
        return super().drawControl(element, option, painter, widget)

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint in (QStyle.SH_ItemView_ShowDecorationSelected, QStyle.SH_ItemView_ChangeHighlightOnFocus):
            return 0
        return super().styleHint(hint, option, widget, returnData)
