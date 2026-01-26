# -*- coding: utf-8 -*-

import os
import math
import tempfile
import sys
import platform
from typing import Optional, Dict, Any

from PySide6.QtCore import (
    Qt, QSize, QEvent, QRect, QPoint, QTimer,
    QPropertyAnimation, QEasingCurve, Property
)
from PySide6.QtGui import (
    QIcon, QPixmap, QPainter, QColor, QPen, QCursor, QBrush, QPalette
)
from PySide6.QtWidgets import (
    QApplication, QHeaderView, QAbstractButton, QWidget,
    QFrame, QVBoxLayout, QHBoxLayout, QCheckBox, QLabel,
    QPushButton, QDialog, QMenu, QProxyStyle, QStyle, QAbstractItemView, QTableView, QSizePolicy
)
from PySide6 import QtCore, QtGui, QtWidgets

from PySide6.QtCore import QSettings

from larix_nexus.utils.paths import rsrc_path, program_dir as _program_dir, ICON_PATH as _APP_ICON_PATH
from larix_nexus.utils.helpers import _set_window_theme_dark

# Constants
SETTINGS_ORG = "Larix"
SETTINGS_APP = "NexusDesktop"
THEME_LIGHT = "light"
THEME_DARK = "dark"

ICON_PATH = _APP_ICON_PATH

CHECKBOX_COLUMN_WIDTH = 36

SCROLLBAR_SLIDER_MIN = 24

# Icon paths (project-relative)
SORT_ICON_UP_PATH = rsrc_path("icon", "arrow-up.png").replace("\\", "/")
SORT_ICON_DOWN_PATH = rsrc_path("icon", "arrow-down.png").replace("\\", "/")

# Check icon paths (PNG indicators)
CHECK_ICON_OFF_PATH = rsrc_path("icon", "check.png").replace("\\", "/")
CHECK_ICON_ON_PATH = rsrc_path("icon", "select.png").replace("\\", "/")
CHECK_ICON_MID_PATH = rsrc_path("icon", "poloska.png").replace("\\", "/")

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
        self._dark_mode = False
        self._up_path = icon_up_path or ""
        self._down_path = icon_down_path or ""
        self._pm_up = self._load_icon(self._up_path)
        self._pm_dn = self._load_icon(self._down_path)
        self.setSectionsClickable(True)
        self.setSortIndicatorShown(True)
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
        was_sort_shown = self.isSortIndicatorShown()
        is_sort_col = (logicalIndex == self.sortIndicatorSection())

        if was_sort_shown and is_sort_col:
            self.setSortIndicatorShown(False)

        super().paintSection(painter, rect, logicalIndex)

        if was_sort_shown and is_sort_col:
            self.setSortIndicatorShown(True)

        if not was_sort_shown or not is_sort_col:
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
            x = min(rect.x() + 8 + painter.fontMetrics().horizontalAdvance(text) + 6,
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
                    painter.setBrush(QColor("#000000"))
                else:
                    painter.setBrush(QColor("#888888"))
            else:
                painter.setBrush(QColor("#f0f0f0"))

            painter.drawPath(path)
            painter.restore()
            return

        text = str(self.model().headerData(logicalIndex, Qt.Horizontal, Qt.DisplayRole) or "")
        text_w = painter.fontMetrics().horizontalAdvance(text)
        x = min(rect.x() + 8 + text_w + 6, rect.right() - pm.width() - 4)
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


class ThemeToggle(QAbstractButton):
    def __init__(self, sun_icon_path: str = "", moon_icon_path: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("themeToggle")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setMinimumSize(58, 26)
        self.setMaximumHeight(28)
        self._sun_icon = self._load_icon(sun_icon_path)
        self._moon_icon = self._load_icon(moon_icon_path)
        self._shift = 0.0
        self._anim = QPropertyAnimation(self, b"shift", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate_toggle)

    @staticmethod
    def _load_icon(path: str) -> QPixmap:
        if path and os.path.exists(path):
            pm = QPixmap(path)
            if not pm.isNull():
                return pm
        return QPixmap()

    def snap_to_state(self) -> None:
        self._set_shift(1.0 if self.isChecked() else 0.0)

    def _animate_toggle(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._shift)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def sizeHint(self) -> QSize:
        return QSize(66, 28)

    def minimumSizeHint(self) -> QSize:
        return QSize(58, 26)

    def _get_shift(self) -> float:
        return self._shift

    def _set_shift(self, value: float) -> None:
        value = max(0.0, min(1.0, float(value)))
        if not math.isclose(self._shift, value, rel_tol=1e-3):
            self._shift = value
            self.update()

    shift = Property(float, _get_shift, _set_shift)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        track_rect = QtCore.QRectF(rect.adjusted(1, 1, -1, -1))

        dark = self.isChecked()
        track_color = QColor("#555555") if dark else QColor("#e8e8e8")
        painter.setPen(Qt.NoPen)
        painter.setBrush(track_color)
        radius = track_rect.height() / 2.0
        painter.drawRoundedRect(track_rect, radius, radius)

        knob_margin = 3
        knob_d = track_rect.height() - knob_margin * 2
        knob_x = track_rect.left() + knob_margin + (track_rect.width() - 2 * knob_margin - knob_d) * self._shift
        knob_rect = QtCore.QRectF(knob_x, track_rect.top() + knob_margin, knob_d, knob_d)
        knob_color = QColor("#101010") if dark else QColor("#fdfdfd")
        painter.setBrush(knob_color)
        painter.drawEllipse(knob_rect)

        icon_size = int(track_rect.height() * 0.5)
        center_y = track_rect.center().y()
        left_x = track_rect.left() + 6
        right_x = track_rect.right() - icon_size - 6
        sun_on_left = self._shift >= 0.5
        sun_x = left_x if sun_on_left else right_x
        moon_x = right_x if sun_on_left else left_x
        if icon_size > 0:
            sun_pm = QPixmap()
            moon_pm = QPixmap()
            tint = QColor(Qt.white) if dark else QColor("#222222")
            if not self._sun_icon.isNull():
                _sun = self._sun_icon.scaled(icon_size, icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                sun_pm = _tint_pixmap(_sun, tint)
            if not self._moon_icon.isNull():
                _moon = self._moon_icon.scaled(icon_size, icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                moon_pm = _tint_pixmap(_moon, tint)

            painter.save()
            painter.setPen(Qt.NoPen)
            if not dark and not sun_pm.isNull():
                highlight_size = icon_size + 8
                painter.setBrush(QColor("#F7921E"))
                painter.drawEllipse(QtCore.QRectF(
                    sun_x - (highlight_size - icon_size) / 2,
                    center_y - highlight_size / 2,
                    highlight_size,
                    highlight_size
                ))
            elif dark and not moon_pm.isNull():
                highlight_size = icon_size + 8
                painter.setBrush(QColor("#F7921E"))
                painter.drawEllipse(QtCore.QRectF(
                    moon_x - (highlight_size - icon_size) / 2,
                    center_y - highlight_size / 2,
                    highlight_size,
                    highlight_size
                ))
            painter.restore()

            if not sun_pm.isNull():
                painter.drawPixmap(int(sun_x), int(center_y - sun_pm.height() / 2), sun_pm)
            if not moon_pm.isNull():
                painter.drawPixmap(int(moon_x), int(center_y - moon_pm.height() / 2), moon_pm)


class ColumnsPopup(QWidget):
    toggled = QtCore.Signal(int, bool)
    def __init__(self, table: QTableView, parent=None):
        flags = Qt.Popup | Qt.FramelessWindowHint
        super().__init__(parent, flags)
        self.setObjectName("columnsPopup")
        self.table = table
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self._cb_style = NikCheckBoxStyle(self.style())

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
            if str(title).strip().lower() == "замечания":
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
            self.setWindowTitle("Подождите")
        except Exception:
            self.setWindowTitle(str("Подождите"))
        self.setWindowTitle("Подождите")
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.CustomizeWindowHint)
        try:
            self.setWindowTitle("Подождите")
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
        if st == Qt.Checked:
            self.setChecked(True)
            self._partial = False
        elif st == Qt.Unchecked:
            self.setChecked(False)
            self._partial = False
        else:
            self.setChecked(False)
            self._partial = True
        self.stateChanged.emit(self._checkStateAsInt())
        self.repaint()

    def checkState(self) -> int:
        if self.isChecked():
            return Qt.Checked
        return Qt.PartiallyChecked if self._partial else Qt.Unchecked

    def _checkStateAsInt(self) -> int:
        state = self.checkState()
        if hasattr(state, 'value'):
            return int(state.value)
        return int(state)

    def setChecked(self, on: bool):
        prev = self.isChecked()
        self._setting_checked = True
        try:
            super().setChecked(on)
        finally:
            self._setting_checked = False

        if prev != on:
            if self._partial:
                self._partial = False
            self.stateChanged.emit(self._checkStateAsInt())

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        size = min(self.BOX, min(self.width(), self.height()))
        x = (self.width() - size) // 2
        y = (self.height() - size) // 2

        dark = _is_dark_mode()
        is_hovered = self.underMouse()

        if self.isChecked():
            _icon_path = CHECK_ICON_ON_PATH
        elif getattr(self, "_partial", False):
            _icon_path = CHECK_ICON_MID_PATH
        else:
            _icon_path = CHECK_ICON_OFF_PATH

        try:
            if dark:
                _icon = load_white_icon(_icon_path)
                _pm = _icon.pixmap(size, size)
            else:
                _icon = QIcon(_icon_path)
                _pm = _icon.pixmap(size, size)
        except Exception:
            _pm = QPixmap()

        if _pm.isNull() and _icon_path:
            try:
                _base = QPixmap(_icon_path)
                if not _base.isNull():
                    if dark:
                        _base = _tint_pixmap(_base, QColor(Qt.white))
                    _pm = _base.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            except Exception:
                pass

        if dark and is_hovered and not _pm.isNull():
            try:
                _pm = _tint_pixmap(_pm, QColor(Qt.black))
            except Exception:
                pass

        if not _pm.isNull():
            px = int(x + (size - _pm.width()) // 2)
            py = int(y + (size - _pm.height()) // 2)
            p.drawPixmap(px, py, _pm)
            p.end()
            return

        rect = QtCore.QRectF(x, y, size, size)
        hovered = self.underMouse()
        pressed = self.isDown()

        if dark:
            fill_color = QColor("#101010")
            if hovered:
                fill_color = QColor("#181818")
            if pressed:
                fill_color = QColor("#060606")
            border_color = QColor("#fefefe")
            mark_color = QColor("#fefefe")
        else:
            fill_color = QColor("#ffffff")
            if hovered:
                fill_color = QColor("#f5f5f5")
            if pressed:
                fill_color = QColor("#e8e8e8")
            border_color = QColor("#888888")
            mark_color = QColor("#222222")

        p.setBrush(QBrush(fill_color))
        p.setPen(QPen(border_color, max(1, int(size * 0.08))))
        p.drawRoundedRect(rect, self.RADIUS, self.RADIUS)

        if self.isChecked():
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(mark_color))
            r = size * 0.25
            cx, cy = rect.center().x(), rect.center().y()
            path = QtGui.QPainterPath()
            path.moveTo(cx - size*0.25, cy)
            path.lineTo(cx - size*0.05, cy + size*0.2)
            path.lineTo(cx + size*0.25, cy - size*0.25)
            p.drawPath(path)
        elif self._partial:
            p.setPen(QPen(mark_color, max(2, int(size * 0.12))))
            ymid = rect.center().y()
            p.drawLine(rect.left() + 0.25*size, ymid, rect.right() - 0.25*size, ymid)


class ScrollbarProxyStyle(QProxyStyle):
    """Прокси-стиль для скругленных скроллбаров с минимальной длиной ползунка."""
    def __init__(self, base_style=None):
        super().__init__(base_style)

    def pixelMetric(self, metric, option=None, widget=None):
        if metric == QStyle.PM_ScrollBarSliderMin:
            return SCROLLBAR_SLIDER_MIN
        return super().pixelMetric(metric, option, widget)

    def drawControl(self, element, option, painter, widget=None):
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
        if element == QStyle.PE_IndicatorBranch:
            if not (option.state & QStyle.State_Children):
                return super().drawPrimitive(element, option, painter, widget)

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
                return
        return super().drawPrimitive(element, option, painter, widget)
