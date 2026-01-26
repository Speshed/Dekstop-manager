# -*- coding: utf-8 -*-
"""Message box patches for fixing corrupted texts."""

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
