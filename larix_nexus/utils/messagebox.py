# -*- coding: utf-8 -*-
"""Message box patches for fixing corrupted texts."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from larix_nexus.utils.paths import rsrc_path


def message_dialog_pixmap(kind: str, dark: bool = False, size: int = 48) -> QPixmap:
    """Return the shared warning/alert pixmap, tinted for dark dialogs."""
    if kind not in {"warning", "alert"}:
        return QPixmap()
    try:
        source = QPixmap(rsrc_path("icon", f"{kind}.png"))
        if source.isNull():
            return QPixmap()
        source = source.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if not dark or kind == "warning":
            return source
        tinted = QPixmap(source.size())
        tinted.fill(Qt.transparent)
        painter = QPainter(tinted)
        painter.drawPixmap(0, 0, source)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(tinted.rect(), QColor("#E0E0E0"))
        painter.end()
        return tinted
    except Exception:
        return QPixmap()


from PySide6.QtWidgets import QMessageBox


def patch_messagebox_texts():
    """Normalize some corrupted info messages after downloads (e.g., '????')."""
    try:
        import re
        _orig_info = QMessageBox.information
        
        def _info(parent, title, text, *args, **kwargs):
            try:
                t = title or ""
                m = text or ""
                if isinstance(t, str) and t and all(ch == '?' or ch.isspace() for ch in t):
                    n = None
                    if isinstance(m, str):
                        nums = re.findall(r"\d+", m)
                        if nums:
                            n = nums[-1]
                    if n is not None:
                        t = "Скачивание файлов"
                        m = f"Скачано файлов: {n}"
                    else:
                        t = "Информация"
                        m = "Готово."
            except Exception:
                t = title
                m = text
            return _orig_info(parent, t, m, *args, **kwargs)
        
        QMessageBox.information = _info
    except Exception:
        pass
