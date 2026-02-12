"""Theme toggle widget with animated pill UI."""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QEasingCurve, Property, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPixmap, QRadialGradient

from larix_nexus.utils.paths import rsrc_path


class ThemeToggle(QtWidgets.QWidget):
    """Animated theme toggle. checked=True means dark theme."""

    toggled = QtCore.Signal(bool)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._checked = False
        self._handle_progress = 0.0
        self._hovered = False
        self._pressed = False
        self._icon_cache: dict[tuple[str, int, float], QPixmap] = {}

        self._sun_source = self._load_icon("sun.png")
        self._moon_source = self._load_icon("moon.png")

        self._anim = QPropertyAnimation(self, b"handleProgress", self)
        self._anim.setDuration(190)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_Hover, True)
        self.setMinimumSize(48, 24)
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)

    @staticmethod
    def _load_icon(file_name: str) -> QPixmap:
        path = rsrc_path("icon", file_name)
        pm = QPixmap(path)
        return pm if not pm.isNull() else QPixmap()

    def _scaled_icon(self, key: str, source: QPixmap, size: int) -> QPixmap:
        if source.isNull() or size <= 0:
            return QPixmap()
        dpr = max(1.0, self.devicePixelRatioF())
        cache_key = (key, size, dpr)
        cached = self._icon_cache.get(cache_key)
        if cached is not None:
            return cached

        px = max(1, int(round(size * dpr)))
        scaled = source.scaled(px, px, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        scaled.setDevicePixelRatio(dpr)
        self._icon_cache[cache_key] = scaled
        return scaled

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(66, 28)

    def minimumSizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(48, 24)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool, animate: bool = True) -> None:
        checked = bool(checked)
        if self._checked == checked:
            return
        self._checked = checked
        target = 1.0 if checked else 0.0

        if animate and self.isVisible():
            self._anim.stop()
            self._anim.setStartValue(self._handle_progress)
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self._handle_progress = target
            self.update()

        self.toggled.emit(self._checked)

    checked = Property(bool, isChecked, setChecked, notify=toggled)

    def _get_handle_progress(self) -> float:
        return self._handle_progress

    def _set_handle_progress(self, value: float) -> None:
        self._handle_progress = max(0.0, min(1.0, float(value)))
        self.update()

    handleProgress = Property(float, _get_handle_progress, _set_handle_progress)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._pressed = True
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            was_pressed = self._pressed
            self._pressed = False
            if was_pressed and self.rect().contains(event.position().toPoint()):
                self.setChecked(not self._checked)
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.setChecked(not self._checked)
            event.accept()
            return
        super().keyPressEvent(event)

    def enterEvent(self, event: QtCore.QEvent) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self._hovered = False
        self._pressed = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        track = QRectF(self.rect().adjusted(1, 1, -1, -1))
        radius = track.height() * 0.5

        if self._checked:
            track_top = QColor("#1b1d20")
            track_bottom = QColor("#131416")
            thumb_base = QColor("#f4f4f6")
            border = QColor(0, 0, 0, 78)
        else:
            track_top = QColor("#f5f5f6")
            track_bottom = QColor("#e8e9eb")
            thumb_base = QColor("#2b2d31")
            border = QColor(0, 0, 0, 44)

        if self._hovered:
            track_top = track_top.lighter(104)
            track_bottom = track_bottom.lighter(103)
            border = border.lighter(108)
        if self._pressed:
            track_top = track_top.darker(103)
            track_bottom = track_bottom.darker(104)

        track_grad = QLinearGradient(track.topLeft(), track.bottomLeft())
        track_grad.setColorAt(0.0, track_top)
        track_grad.setColorAt(1.0, track_bottom)
        p.setPen(Qt.NoPen)
        p.setBrush(track_grad)
        p.drawRoundedRect(track, radius, radius)

        gloss = QLinearGradient(track.topLeft(), track.bottomLeft())
        gloss.setColorAt(0.0, QColor(255, 255, 255, 32 if not self._checked else 16))
        gloss.setColorAt(0.45, QColor(255, 255, 255, 6 if not self._checked else 3))
        gloss.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(gloss)
        p.drawRoundedRect(track, radius, radius)

        p.setPen(QPen(border, 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(track, radius, radius)

        pad = max(4.0, track.height() * 0.085)
        handle_d = track.height() - pad * 2.0
        handle_r = handle_d * 0.5
        left_x = track.left() + pad
        right_x = track.right() - pad - handle_d
        handle_x = left_x + (right_x - left_x) * self._handle_progress
        handle = QRectF(handle_x, track.top() + pad, handle_d, handle_d)

        icon_size = int(max(18.0, min(22.0, track.height() * 0.33)))
        icon_rect = QRectF(
            track.left() + track.height() * 0.40,
            track.center().y() - icon_size * 0.5,
            icon_size,
            icon_size,
        )
        icon_pm = self._scaled_icon(
            "moon" if self._checked else "sun",
            self._moon_source if self._checked else self._sun_source,
            icon_size,
        )
        if not icon_pm.isNull():
            src = QRectF(
                0.0,
                0.0,
                icon_pm.width() / icon_pm.devicePixelRatio(),
                icon_pm.height() / icon_pm.devicePixelRatio(),
            )
            p.drawPixmap(icon_rect, icon_pm, src)

        shadow_boost = 1.0
        if self._hovered:
            shadow_boost = 1.15
        if self._pressed:
            shadow_boost = 1.25

        center = handle.center()
        shadow = QRadialGradient(center + QtCore.QPointF(0.0, 1.6), handle_r * 1.22)
        shadow.setColorAt(0.0, QColor(0, 0, 0, int(58 * shadow_boost)))
        shadow.setColorAt(0.58, QColor(0, 0, 0, int(24 * shadow_boost)))
        shadow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(shadow)
        p.drawEllipse(handle.adjusted(-2.5, -1.5, 2.5, 3.0))

        thumb_top = QColor(thumb_base)
        thumb_bottom = thumb_base.darker(108 if self._checked else 112)
        if self._hovered:
            thumb_top = thumb_top.lighter(104)
            thumb_bottom = thumb_bottom.lighter(102)
        if self._pressed:
            thumb_top = thumb_top.darker(102)
            thumb_bottom = thumb_bottom.darker(103)

        thumb_grad = QLinearGradient(handle.topLeft(), handle.bottomLeft())
        thumb_grad.setColorAt(0.0, thumb_top)
        thumb_grad.setColorAt(1.0, thumb_bottom)
        p.setBrush(thumb_grad)
        p.setPen(QPen(QColor(0, 0, 0, 50 if self._checked else 74), 1.0))
        p.drawEllipse(handle)

        inner_glow = QRadialGradient(
            handle.center() - QtCore.QPointF(handle_r * 0.22, handle_r * 0.28),
            handle_r * 0.95,
        )
        inner_glow.setColorAt(0.0, QColor(255, 255, 255, 42 if self._checked else 24))
        inner_glow.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(inner_glow)
        p.drawEllipse(handle.adjusted(1.0, 1.0, -1.0, -1.0))

        if self.hasFocus():
            ring = QColor("#4C8DFF")
            ring.setAlpha(165)
            p.setPen(QPen(ring, 1.0))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(track.adjusted(-2.0, -2.0, 2.0, 2.0), radius + 2.0, radius + 2.0)


class ThemeTogglePdfStyle(ThemeToggle):
    """PDF_Compare visual style for theme toggle."""

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)

        rect = self.rect()
        track = rect.adjusted(1, 1, -1, -1)
        dark = self._checked

        if dark:
            bg_start = QtGui.QColor("#2c2c2e")
            bg_end = QtGui.QColor("#1c1c1e")
        else:
            bg_start = QtGui.QColor("#f5f5f6")
            bg_end = QtGui.QColor("#e8e9eb")

        grad = QtGui.QLinearGradient(track.topLeft(), track.bottomLeft())
        grad.setColorAt(0, bg_start)
        grad.setColorAt(1, bg_end)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(grad)
        radius = track.height() * 0.5
        p.drawRoundedRect(track, radius, radius)

        icon_size = int(track.height() * 0.5)
        center_y = track.center().y()
        left_x = track.left() + 6
        right_x = track.right() - icon_size - 6

        sun_pm = QtGui.QPixmap()
        moon_pm = QtGui.QPixmap()

        if not self._sun_source.isNull():
            _sun = self._sun_source.scaled(icon_size, icon_size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            sun_pm = self._tint_pixmap(_sun, QtGui.QColor(0, 0, 0) if not dark else QtGui.QColor(255, 255, 255))

        if not self._moon_source.isNull():
            _moon = self._moon_source.scaled(icon_size, icon_size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            moon_pm = self._tint_pixmap(_moon, QtGui.QColor(0, 0, 0) if not dark else QtGui.QColor(255, 255, 255))

        p.save()
        p.setPen(QtCore.Qt.NoPen)

        if not dark:
            hl_size = icon_size + 8
            p.setBrush(QtGui.QColor("#F7921E"))
            p.drawEllipse(QtCore.QRectF(right_x - (hl_size - icon_size) / 2, center_y - hl_size / 2, hl_size, hl_size))
        else:
            hl_size = icon_size + 8
            p.setBrush(QtGui.QColor("#F7921E"))
            p.drawEllipse(QtCore.QRectF(left_x - (hl_size - icon_size) / 2, center_y - hl_size / 2, hl_size, hl_size))
        p.restore()

        if not sun_pm.isNull():
            p.setOpacity(1.0 if not dark else 0.4)
            p.drawPixmap(int(right_x), int(center_y - sun_pm.height() / 2), sun_pm)
        if not moon_pm.isNull():
            p.setOpacity(0.4 if not dark else 1.0)
            p.drawPixmap(int(left_x), int(center_y - moon_pm.height() / 2), moon_pm)

        p.end()

    @staticmethod
    def _tint_pixmap(pm: QtGui.QPixmap, color: QtGui.QColor) -> QtGui.QPixmap:
        if pm.isNull():
            return pm
        tinted = QtGui.QPixmap(pm.size())
        tinted.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(tinted)
        painter.drawPixmap(0, 0, pm)
        painter.setCompositionMode(QtGui.QPainter.CompositionMode_SourceIn)
        painter.fillRect(tinted.rect(), color)
        painter.end()
        return tinted
