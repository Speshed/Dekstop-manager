# -*- coding: utf-8 -*-
"""Drop animation overlay for visual feedback.

Creates animated icons that "bounce" from source to destination.
"""

from __future__ import annotations

from typing import Optional, List
from PySide6.QtCore import Qt, QObject, QPoint, QPropertyAnimation, QEasingCurve, QTimer, QProperty
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout


# Animation constants
ANIMATION_DURATION = 600  # ms
STAGGER_DELAY = 40  # ms delay between icons
BOUNCE_HEIGHT = -30  # pixels (negative = up)
ANIMATION_CURVE = QEasingCurve.OutBack


class _AnimatedIconLabel(QLabel):
    """Label that animates from source to destination."""
    
    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self._pixmap = pixmap
        self.setPixmap(pixmap)
        self.setAttribute(Qt.WA_TranslucentBackground)
    
    def set_opacity(self, opacity: float):
        """Set label opacity."""
        from PySide6.QtGui import QPalette, QColor
        pal = self.palette()
        color = pal.color(self.backgroundRole())
        color.setAlphaF(opacity)
        pal.setColor(self.backgroundRole(), color)
        self.setPalette(pal)
    
    opacity = QProperty(float, set_opacity)


class DropAnimationOverlay(QWidget):
    """Overlay widget that shows animated icons bouncing to destination.
    
    Usage:
        overlay = DropAnimationOverlay(main_window)
        overlay.animate_drop(source_pos, dest_pos, icons)
    """
    
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self._main_window = main_window
        self._animations: List[QPropertyAnimation] = []
        self._labels: List[_AnimatedIconLabel] = []
        self._fade_timer = QTimer(self)
        self._fade_timer.timeout.connect(self._fade_out_all)
        
        # Setup overlay
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        
    def animate_drop(self, source_pos: QPoint, dest_pos: QPoint, icons: List[QPixmap]):
        """Animate icons from source to destination with bounce effect.
        
        Args:
            source_pos: Starting position in global coordinates
            dest_pos: Ending position in global coordinates
            icons: List of pixmaps to animate
        """
        if not icons:
            return
        
        # Position overlay to cover entire area
        self._position_overlay(source_pos, dest_pos)
        
        # Create animated icons
        self._create_animated_icons(source_pos, dest_pos, icons)
        
        # Start fade out after last animation
        total_time = ANIMATION_DURATION + STAGGER_DELAY * len(icons) + 200
        self._fade_timer.start(total_time)
        
        print(f"[DropAnimationOverlay] Animating {len(icons)} icons")
    
    def _position_overlay(self, source_pos: QPoint, dest_pos: QPoint):
        """Position overlay widget to cover animation area."""
        # Calculate bounding rect
        x = min(source_pos.x(), dest_pos.x()) - 50
        y = min(source_pos.y(), dest_pos.y()) - 50
        w = abs(dest_pos.x() - source_pos.x()) + 100
        h = abs(dest_pos.y() - source_pos.y()) + 100
        
        # Ensure minimum size
        w = max(w, 200)
        h = max(h, 200)
        
        # Position overlay (use global coords)
        self.setGeometry(x, y, w, h)
        self.show()
        self.raise_()
        
        print(f"[DropAnimationOverlay] Overlay positioned at ({x}, {y}) {w}x{h}")
    
    def _create_animated_icons(self, source_pos: QPoint, dest_pos: QPoint, icons: List[QPixmap]):
        """Create and animate icon labels."""
        # Convert to overlay-relative coordinates
        overlay_pos = self.pos()
        rel_source = source_pos - overlay_pos
        rel_dest = dest_pos - overlay_pos
        
        for i, pixmap in enumerate(icons):
            # Stagger delay for each icon
            delay = i * STAGGER_DELAY
            
            # Create label
            label = _AnimatedIconLabel(pixmap, self)
            label.move(rel_source)
            label.resize(pixmap.size())
            self._labels.append(label)
            label.show()
            
            # Create animations with delay
            QTimer.singleShot(delay, lambda l=label, rs=rel_source, rd=rel_dest, pm=pixmap: 
                self._animate_icon(l, rs, rd, pm))
    
    def _animate_icon(self, label: _AnimatedIconLabel, source: QPoint, dest: QPoint, pixmap: QPixmap):
        """Animate single icon with bounce effect."""
        # Create animation sequence
        # 1. Bounce up
        # 2. Move to destination
        # 3. Fade out
        
        # Bounce animation (vertical)
        self._animate_bounce(label, source, dest)
        
        # Horizontal move animation
        self._animate_move(label, source, dest)
    
    def _animate_bounce(self, label: _AnimatedIconLabel, source: QPoint, dest: QPoint):
        """Animate vertical bounce."""
        anim = QPropertyAnimation(label, b"pos")
        anim.setDuration(ANIMATION_DURATION)
        anim.setEasingCurve(ANIMATION_CURVE)
        
        # Create keyframes: source -> bounce up -> destination y
        start_pos = source
        bounce_pos = QPoint(source.x(), source.y() + BOUNCE_HEIGHT)
        end_pos = QPoint(dest.x(), dest.y())
        
        anim.setKeyValueAt(0, start_pos)
        anim.setKeyValueAt(0.5, bounce_pos)
        anim.setKeyValueAt(1, end_pos)
        
        self._animations.append(anim)
        anim.start()
    
    def _animate_move(self, label: _AnimatedIconLabel, source: QPoint, dest: QPoint):
        """Animate horizontal move."""
        anim = QPropertyAnimation(label, b"pos")
        anim.setDuration(ANIMATION_DURATION)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        
        anim.setStartValue(source)
        anim.setEndValue(dest)
        
        self._animations.append(anim)
        anim.start()
    
    def _fade_out_all(self):
        """Fade out all animated icons and cleanup."""
        for label in self._labels:
            # Create fade animation
            anim = QPropertyAnimation(label, b"opacity")
            anim.setDuration(200)
            anim.setStartValue(1.0)
            anim.setEndValue(0.0)
            
            anim.finished.connect(lambda l=label: l.deleteLater())
            anim.start()
        
        # Schedule overlay cleanup
        QTimer.singleShot(300, self._cleanup)
    
    def _cleanup(self):
        """Cleanup animations and hide overlay."""
        # Stop all animations
        for anim in self._animations:
            anim.stop()
        
        self._animations.clear()
        self._labels.clear()
        self._fade_timer.stop()
        
        self.hide()
        
        print("[DropAnimationOverlay] Cleanup completed")


def show_drop_animation(main_window, source_pos: QPoint, dest_pos: QPoint, icons: List[QPixmap]):
    """Convenience function to show drop animation.
    
    Args:
        main_window: Main window reference
        source_pos: Source position in global coordinates
        dest_pos: Destination position in global coordinates
        icons: List of pixmaps to animate
    """
    overlay = DropAnimationOverlay(main_window, main_window)
    overlay.animate_drop(source_pos, dest_pos, icons)
    
    # Auto-delete after animation
    QTimer.singleShot(3000, overlay.deleteLater)
    
    return overlay
