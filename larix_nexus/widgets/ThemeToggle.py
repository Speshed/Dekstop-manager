"""Theme toggle widget with animated pill UI."""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QEasingCurve, Property, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPixmap, QRadialGradient, QRegion

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
        # Paint only the rounded pill; do not let Qt or a parent stylesheet
        # fill the widget's rectangular corners first.
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._clip_to_track = True
        self.setMinimumSize(48, 24)
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        self._update_track_mask()

    def _update_track_mask(self) -> None:
        if not getattr(self, "_clip_to_track", True):
            self.clearMask()
            return
        track = self.rect().adjusted(1, 1, -1, -1)
        if track.width() <= 0 or track.height() <= 0:
            self.clearMask()
            return
        path = QtGui.QPainterPath()
        path.addRoundedRect(QtCore.QRectF(track), track.height() * 0.5, track.height() * 0.5)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        self._update_track_mask()
        super().resizeEvent(event)

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
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)

        p.save()
        p.setCompositionMode(QtGui.QPainter.CompositionMode_Source)
        p.fillRect(self.rect(), QtCore.Qt.transparent)
        p.restore()

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


class ThemeTogglePdfStyle(ThemeToggle):
    """PDF_Compare visual style for theme toggle."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._clip_to_track = False
        self.clearMask()
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)

        p.save()
        p.setCompositionMode(QtGui.QPainter.CompositionMode_Source)
        p.fillRect(self.rect(), QtCore.Qt.transparent)
        p.restore()

        rect = self.rect()
        track = rect.adjusted(1, 1, -1, -1)
        dark = self._checked

        bg = QtGui.QColor("#202020" if dark else "#fdfdfd")
        border = QtGui.QColor("#4a4a4a" if dark else "#e6e6e6")

        p.fillRect(rect, bg)

        p.setPen(QtGui.QPen(border, 1))
        p.setBrush(bg)
        radius = track.height() * 0.5
        p.drawRoundedRect(track, radius, radius)

        icon_size = int(track.height() * 0.5)
        center_y = track.center().y()
        left_x = track.left() + 6
        right_x = track.right() - icon_size - 6

        sun_pm = QtGui.QPixmap()
        moon_pm = QtGui.QPixmap()
        inactive = QtGui.QColor("#8a8a8a") if dark else QtGui.QColor("#6f6f6f")
        active = QtGui.QColor("#ffffff") if dark else QtGui.QColor("#111111")

        if not self._sun_source.isNull():
            _sun = self._sun_source.scaled(icon_size, icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            sun_pm = self._tint_pixmap(_sun, inactive if dark else active)
        if not self._moon_source.isNull():
            _moon = self._moon_source.scaled(icon_size, icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            moon_pm = self._tint_pixmap(_moon, active if dark else inactive)

        hl_size = icon_size + 8
        hl_x = left_x if dark else right_x
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor("#F7921E"))
        p.drawEllipse(QtCore.QRectF(hl_x - (hl_size - icon_size) / 2, center_y - hl_size / 2, hl_size, hl_size))

        if not moon_pm.isNull():
            p.setOpacity(1.0 if dark else 0.5)
            p.drawPixmap(int(left_x), int(center_y - moon_pm.height() / 2), moon_pm)
        if not sun_pm.isNull():
            p.setOpacity(0.5 if dark else 1.0)
            p.drawPixmap(int(right_x), int(center_y - sun_pm.height() / 2), sun_pm)

        p.end()
