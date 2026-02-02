"""PDF_Compare — версия на PySide6 с собственным стилем, скопированным из Dekstop.py.

Функции:
- Загрузка двух PDF
- Режимы отображения: Версия 1 / Версия 2 / Сравнение
- Масштабирование колесом, поворот, смещение для diff (перетаскиванием)
- Навигация по страницам + миниатюры
- Экспорт текущего изображения в PDF

Требования: PySide6, fitz(PyMuPDF), numpy, opencv-python, Pillow
"""

from __future__ import annotations
import os, sys
import threading
import re
import fitz  # PyMuPDF
import numpy as np
import cv2
import argparse
import io
from PIL import Image, ImageOps

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QSettings, Qt, QUrl
from PySide6.QtGui import QPixmap, QColor
from concurrent.futures import ThreadPoolExecutor
import queue
import platform

from larix_nexus.utils.paths import rsrc_path, ICON_PATH
from larix_nexus.constants import (
    SETTINGS_ORG, SETTINGS_APP, SETTINGS_THEME_KEY, THEME_LIGHT, THEME_DARK,
    ARROW_LEFT_PATH, ARROW_RIGHT_PATH, ARROW_LEFT_ICON_PATH, ARROW_RIGHT_ICON_PATH,
    DOWN_ARROW_ICON_PATH, DOWN_ARROW_WHITE_ICON_PATH,
    SORT_ICON_UP_PATH, SORT_ICON_DOWN_PATH,
    CHECK_ICON_OFF_PATH, CHECK_ICON_ON_PATH, CHECK_ICON_MID_PATH,
    RCHECK_ICON_OFF_PATH, RCHECK_ICON_ON_PATH, WARNING_ICON_PATH,
    _COLOR_REPLACEMENTS as GLOBAL_COLOR_REPLACEMENTS,
)

# Icon directory for all icon resources
ICON_DIR = rsrc_path("icon")

def icon_url(path: str) -> str:
    """Convert file path to URL for use in QSS/CSS."""
    return QUrl.fromLocalFile(path).toString()

def icon_url_encoded(path: str) -> str:
    """Convert file path to URL with proper encoding for QSS/CSS (handles non-ASCII paths)."""
    from urllib.request import pathname2url
    abs_path = os.path.abspath(path)
    return "file:" + pathname2url(abs_path)

def _app_settings() -> QSettings:
    return QSettings(SETTINGS_ORG, SETTINGS_APP)

def load_saved_theme() -> str:
    """Load theme from settings (same as Dekstop.py)."""
    try:
        s = _app_settings()
        val = s.value(SETTINGS_THEME_KEY, THEME_LIGHT)
        return str(val).lower() if val in (THEME_LIGHT, THEME_DARK) else THEME_LIGHT
    except Exception:
        return THEME_LIGHT

def save_theme(theme: str) -> None:
    """Save theme to settings (same as Dekstop.py)."""
    try:
        s = _app_settings()
        s.setValue(SETTINGS_THEME_KEY, theme)
        s.sync()
    except Exception:
        pass


def _set_window_theme(window, dark: bool = False) -> None:
    """Set Windows title bar theme (light/dark) for window."""
    if platform.system() != "Windows":
        return
    try:
        import ctypes
        from ctypes import c_int, byref, sizeof
        hwnd = window.winId().__int__()
        # DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        value = c_int(1 if dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, byref(value), sizeof(value)
        )
        # Title bar colors (Windows 11+)
        caption_color = 0x202020 if dark else 0xFFFFFF
        text_color = 0xFFFFFF if dark else 0x000000
        for attr, color in ((35, caption_color), (36, text_color)):
            try:
                cval = c_int(color)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, byref(cval), sizeof(cval))
            except Exception:
                pass
        # Force window repaint to update title bar
        try:
            window.update()
            from ctypes import windll
            windll.user32.RedrawWindow(hwnd, None, None, 0x0001 | 0x0004 | 0x0010)  # RDW_INVALIDATE | RDW_FRAME | RDW_UPDATENOW
        except Exception:
            pass
    except Exception:
        pass


# --- PDF-specific style additions (extended from constants.py) ---
# Additional color replacements specific to PDF Compare (scrollbar colors)
PDF_COLOR_REPLACEMENTS = {
    "#F0F0F0": "#1e1e1e",  # Scrollbar background - slightly lighter than main
    "#F9F9F9": "#1e1e1e",  # Scrollbar areas - slightly lighter
    "#DCDCDC": "#606060",  # Border color - more visible in dark theme
    "#C0C0C0": "#404040",  # Scrollbar button pressed
    "#D0D0D0": "#4a4a4a",  # Scrollbar button hover
    "#E0E0E0": "#2a2a2a",  # Scrollbar button normal
}
# Merge with global replacements
_COLOR_REPLACEMENTS = {**GLOBAL_COLOR_REPLACEMENTS, **PDF_COLOR_REPLACEMENTS}

# --- Color replacements for dark theme (merged with globals) ---
# Additional color replacements specific to PDF Compare (scrollbar colors)
PDF_COLOR_REPLACEMENTS = {
    "#F0F0F0": "#1e1e1e",  # Scrollbar background - slightly lighter than main
    "#F9F9F9": "#1e1e1e",  # Scrollbar areas - slightly lighter
    "#DCDCDC": "#606060",  # Border color - more visible in dark theme
    "#C0C0C0": "#404040",  # Scrollbar button pressed
    "#D0D0D0": "#4a4a4a",  # Scrollbar button hover
    "#E0E0E0": "#2a2a2a",  # Scrollbar button normal
}
# Merge with global replacements
_COLOR_REPLACEMENTS = {**GLOBAL_COLOR_REPLACEMENTS, **PDF_COLOR_REPLACEMENTS}

_COLOR_PATTERN = re.compile(
    "|".join(sorted((re.escape(k) for k in _COLOR_REPLACEMENTS), key=len, reverse=True)),
    flags=re.IGNORECASE
)


def _create_white_arrow_icons():
    """Create white versions of arrow icons for dark theme."""
    try:
        from PIL import Image, ImageOps
        import os
        
        icon_dir = os.path.dirname(DOWN_ARROW_ICON_PATH)
        white_dir = os.path.join(icon_dir, "white")
        
        # Create white directory if it doesn't exist
        os.makedirs(white_dir, exist_ok=True)
        
        # List of icons to convert
        icons_to_convert = [
            ("arrow-down.png", "arrow-down.png"),
            ("arrow-up.png", "arrow-up.png"),
            ("arrow-left.png", "arrow-left.png"),
            ("arrow-right.png", "arrow-right.png"),
        ]
        
        for source_name, target_name in icons_to_convert:
            source_path = os.path.join(icon_dir, source_name)
            target_path = os.path.join(white_dir, target_name)
            
            # Skip if white version already exists
            if os.path.exists(target_path):
                continue
                
            # Skip if source doesn't exist
            if not os.path.exists(source_path):
                continue
            
            try:
                # Open the image
                img = Image.open(source_path).convert("RGBA")
                
                # Invert colors to make black -> white
                r, g, b, a = img.split()
                rgb = Image.merge("RGB", (r, g, b))
                inverted_rgb = ImageOps.invert(rgb)
                inverted_img = Image.merge("RGBA", (*inverted_rgb.split(), a))
                
                # Save white version
                inverted_img.save(target_path, "PNG")
            except Exception as e:
                print(f"Failed to create white icon {target_name}: {e}")
                
    except Exception as e:
        print(f"Failed to create white arrow icons: {e}")


def _replace_colors_for_dark(qss: str) -> str:
    """Replace light theme colors with dark theme colors."""
    if not qss:
        return qss

    def _replacer(match: re.Match) -> str:
        token = match.group(0).upper()
        return _COLOR_REPLACEMENTS.get(token, match.group(0))

    replaced = _COLOR_PATTERN.sub(_replacer, qss)
    
    # Create white arrow icons for dark theme
    _create_white_arrow_icons()
    
    # Replace icon paths with white versions
    icon_dir = os.path.dirname(DOWN_ARROW_ICON_PATH)
    white_dir = os.path.join(icon_dir, "white")
    
    if os.path.exists(white_dir):
        # Replace all arrow icon paths with white versions
        arrow_files = {
            "arrow-down.png": "arrow-down.png",
            "arrow-up.png": "arrow-up.png", 
            "arrow-left.png": "arrow-left.png",
            "arrow-right.png": "arrow-right.png",
        }
        
        for filename in arrow_files.keys():
            white_path = os.path.join(white_dir, filename)
            if os.path.exists(white_path):
                original_path = os.path.join(icon_dir, filename)
                white_path_formatted = white_path
                replaced = replaced.replace(original_path.replace("\\", "/"), white_path_formatted.replace("\\", "/"))
                replaced = replaced.replace(icon_url(original_path), icon_url(white_path_formatted))
                replaced = replaced.replace(icon_url_encoded(original_path), icon_url_encoded(white_path_formatted))
    
    return replaced


def apply_dekstop_style(app: QtWidgets.QApplication, dark: bool = False, target: QtWidgets.QWidget | None = None):
    """Применение полного стиля из Dekstop.py к PDF_Compare."""
    # Устанавливаем свойство темы для внутренней функции is_dark_theme()
    app.setProperty("nik_theme", "dark" if dark else "light")
    
    left_arrow = ARROW_LEFT_ICON_PATH
    
    style = ("""
        /* ===================== Основа ===================== */
        * { font-family: "Segoe UI","Arial",sans-serif; color: #222; font-size: 10pt; }
        QWidget, QDialog, QMainWindow { background: #FFFFFF; }

        /* Заголовок и статус-бар */
        #header { background: #FFFFFF; border: none; }
        QStatusBar { background: #FFFFFF; border-top: 1px solid #eeeeee; color: #222; }

        /* ===================== Кнопки ===================== */
        /* Основные кнопки: Версия 1, Версия 2, Маппинг и т.п. */
        QToolButton#btn_primary, QPushButton#btn_primary,
        QPushButton[objectName="btn_primary"],
        QToolButton[class="primary"], QPushButton[class="primary"] {
            background: #F7921E;
            border: 1px solid #F7921E;
            border-radius: 14px;
            color: #FFFFFF;
            font-weight: 600;
            padding: 6px 12px;
        }
        QToolButton#btn_primary:hover, QPushButton#btn_primary:hover,
        QPushButton[objectName="btn_primary"]:hover,
        QToolButton[class="primary"]:hover, QPushButton[class="primary"]:hover {
            background: #FFE3C2;
            color: #000000;
        }
        QToolButton#btn_primary:pressed, QPushButton#btn_primary:pressed,
        QPushButton[objectName="btn_primary"]:pressed,
        QToolButton[class="primary"]:pressed, QPushButton[class="primary"]:pressed {
            background: #FFC37A;
        }

        /* Белые кнопки (без установки objectName): Настройки, Скачать и т.п. */
        QToolButton, QPushButton,
        QToolButton#btn_secondary, QPushButton#btn_secondary,
        QPushButton[objectName="btn_secondary"],
        QToolButton[class="secondary"], QPushButton[class="secondary"],
        QPushButton[secondary="true"], QToolButton[secondary="true"],
        QDialogButtonBox QPushButton {
            background: #FFFFFF;
            color: #000000;
            border: 1px solid #dcdcdc;
            border-radius: 14px;
            padding: 6px 12px;
            font-weight: 600;
            min-height: 16px;
        }
        QToolButton:hover, QPushButton:hover,
        QToolButton#btn_secondary:hover, QPushButton#btn_secondary:hover,
        QPushButton[objectName="btn_secondary"]:hover,
        QToolButton[class="secondary"]:hover, QPushButton[class="secondary"]:hover,
        QPushButton[secondary="true"]:hover, QToolButton[secondary="true"]:hover,
        QDialogButtonBox QPushButton:hover {
            background: #FFE3C2;
            color: #000000;
            border-color: #FFA74B;
        }
        QToolButton:pressed, QPushButton:pressed,
        QToolButton#btn_secondary:pressed, QPushButton#btn_secondary:pressed,
        QPushButton[objectName="btn_secondary"]:pressed,
        QToolButton[class="secondary"]:pressed, QPushButton[class="secondary"]:pressed,
        QPushButton[secondary="true"]:pressed, QToolButton[secondary="true"]:pressed,
        QDialogButtonBox QPushButton:pressed {
            background: #FFC37A;
            border-color: #E07E12;
        }
        QToolButton:disabled, QPushButton:disabled,
        QPushButton[secondary="true"]:disabled, QToolButton[secondary="true"]:disabled,
        QDialogButtonBox QPushButton:disabled {
            background: #f0f0f0;
            color: #9b9b9b;
            border-color: #e6e6e6;
        }

        /* Checked состояние для переключаемых кнопок */
        QPushButton:checked,
        QToolButton:checked {
            background: #F7921E;
            color: #FFFFFF;
            border-color: #F7921E;
        }
        QPushButton:checked:hover,
        QToolButton:checked:hover {
            background: #FFE3C2;
            color: #000000;
            border-color: #FFA74B;
        }

        /* ===================== Splitter ===================== */
        QSplitter::handle {
            background: transparent;
        }
        QSplitter::handle:hover {
            background: transparent;
        }

        /* ===================== Inputs ===================== */
        QLineEdit {
            background: #FFFFFF;
            color: #222;
            border: 1px solid #dcdcdc;
            border-radius: 8px;
            padding: 4px 10px;
        }

        /* ===================== ComboBox ===================== */
        QComboBox {
            background: #FFFFFF;
            color: #222;
            border: 1px solid #dcdcdc;
            border-radius: 8px;
            padding: 4px 10px;
        }
        QComboBox::drop-down {
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 18px;
            border: none;
            background: transparent;
        }
        QComboBox::down-arrow {
            image: url(\"""" + icon_url_encoded(DOWN_ARROW_ICON_PATH) + """\");
            width: 12px;
            height: 12px;
            margin: 0;
            background: transparent;
            border: none;
        }
        QComboBox QAbstractItemView {
            background: #FFFFFF;
            /* тонкая оранжевая рамка по периметру списка */
            border: 1px solid #FFA74B;
            border-radius: 12px;
            outline: none;
            /* не красим selection системно — скругления/рамка на item */
            selection-background-color: transparent;
            selection-color: #000000;
        }
        QComboBox QAbstractItemView::viewport {
            border-top-left-radius: 12px;
            border-top-right-radius: 12px;
            border-bottom-right-radius: 12px;
            border-bottom-left-radius: 12px;
        }
        QComboBox QAbstractItemView::item {
            padding: 6px 10px;
            border: 1px solid transparent;
            border-radius: 6px;
            margin: 2px;
        }
        QComboBox QAbstractItemView::item:hover {
            background: #FFE3C2;
            border-color: #FFA74B;
            color: #0a0a0a;
        }
        QComboBox QAbstractItemView::item:selected {
            /* подсветка выбранной строки как у кнопки (не плотная заливка) */
            background: rgba(247, 146, 30, 0.10);
            border-color: #FFA74B;
            color: #0a0a0a;
        }
        QComboBox QAbstractItemView::item:selected:hover {
            background: rgba(247, 146, 30, 0.20);
            border-color: #E07E12;
            color: #0a0a0a;
        }

        /* ===================== Scrollbars ===================== */
        QScrollBar:horizontal, QScrollBar:vertical {
            background: #FFFFFF;
            border: none;
        }
        QScrollBar:horizontal {
            height: 14px;
            margin: 0 18px 0 18px;
        }
        QScrollBar:vertical {
            width: 14px;
            margin: 18px 0 18px 0;
        }
        QScrollBar::handle:horizontal, QScrollBar::handle:vertical {
            background: #B8691A;
            border-radius: 7px;
            min-width: 30px;
            min-height: 30px;
        }
        QScrollBar::handle:horizontal:hover, QScrollBar::handle:vertical:hover {
            background: #C88540;
        }
        QScrollBar::handle:horizontal:pressed, QScrollBar::handle:vertical:pressed {
            background: #D89A50;
        }
        
        /* Кнопки со стрелками */
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
            background: #FFFFFF;
            width: 18px;
            height: 14px;
            subcontrol-origin: margin;
            border: none;
            border-radius: 0;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            background: #FFFFFF;
            width: 14px;
            height: 18px;
            subcontrol-origin: margin;
            border: none;
            border-radius: 0;
        }
        QScrollBar::add-line:horizontal:hover, QScrollBar::sub-line:horizontal:hover,
        QScrollBar::add-line:vertical:hover, QScrollBar::sub-line:vertical:hover {
            background: rgba(247, 146, 30, 0.2);
        }
        QScrollBar::add-line:horizontal:pressed, QScrollBar::sub-line:horizontal:pressed,
        QScrollBar::add-line:vertical:pressed, QScrollBar::sub-line:vertical:pressed {
            background: rgba(247, 146, 30, 0.4);
        }
        
        QScrollBar::add-line:horizontal {
            subcontrol-position: right;
        }
        QScrollBar::sub-line:horizontal {
            subcontrol-position: left;
        }
        QScrollBar::add-line:vertical {
            subcontrol-position: bottom;
        }
        QScrollBar::sub-line:vertical {
            subcontrol-position: top;
        }
        
        /* Стрелки */
        QScrollBar::left-arrow:horizontal {
            image: url(\"""" + QUrl.fromLocalFile(ARROW_LEFT_ICON_PATH).toString() + """\");
            width: 10px;
            height: 10px;
        }
        QScrollBar::right-arrow:horizontal {
            image: url(\"""" + QUrl.fromLocalFile(ARROW_RIGHT_ICON_PATH).toString() + """\");
            width: 10px;
            height: 10px;
        }
        QScrollBar::up-arrow:vertical {
            image: url(\"""" + QUrl.fromLocalFile(SORT_ICON_UP_PATH).toString() + """\");
            width: 10px;
            height: 10px;
        }
        QScrollBar::down-arrow:vertical {
            image: url(\"""" + QUrl.fromLocalFile(SORT_ICON_DOWN_PATH).toString() + """\");
            width: 10px;
            height: 10px;
        }
        
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal,
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
            background: #FFFFFF;
        }

        /* ===================== Меню ===================== */
        QMenu {
            background: #FFFFFF;
            border: 1px solid #dcdcdc;
            border-radius: 12px;
            padding: 6px 0;
        }
        QMenu::item {
            color: #000000;
            padding: 6px 12px;
            margin: 2px 6px;
            border: 1px solid transparent;
            border-radius: 8px;
            background: transparent;
        }
        QMenu::item:selected,
        QMenu::item:hover {
            background: #FFE3C2;
            border-color: #FFA74B;
            color: #000000;
        }
        QMenu::item:pressed {
            background: #FFC37A;
            border-color: #E07E12;
            color: #000000;
        }
        QMenu::separator {
            height: 1px;
            background: #e6e6e6;
            margin: 6px 8px;
        }

        /* Календарь и DateEdit */
        QDateEdit {
            background: #FFFFFF;
            color: #222;
            border: 1px solid #dcdcdc;
            border-radius: 8px;
            padding: 4px 10px;
        }
        QDateEdit::drop-down {
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 22px;
            border: none;
            background: transparent;
        }
        QDateEdit::down-arrow {
            image: url(\"\" + icon_url_encoded(DOWN_ARROW_ICON_PATH) + \"\");
            width: 12px;
            height: 12px;
        }

        /* QCalendarWidget */
        QCalendarWidget {
            background: #FFFFFF;
            border: 1px solid #dcdcdc;
            border-radius: 12px;
        }
        QCalendarWidget QWidget#qt_calendar_navigationbar {
            background: #FFFFFF;
            border-bottom: 1px solid #dcdcdc;
            padding: 6px 8px;
        }
        QCalendarWidget QToolButton#qt_calendar_monthbutton,
        QCalendarWidget QToolButton#qt_calendar_yearbutton {
            background: transparent;
            color: #222;
            border: 1px solid transparent;
            border-radius: 12px;
            padding: 4px 10px;
            font-weight: 600;
        }
        QCalendarWidget QToolButton#qt_calendar_monthbutton:hover,
        QCalendarWidget QToolButton#qt_calendar_yearbutton:hover {
            background: #FFE3C2;
            border-color: #FFA74B;
        }
        QCalendarWidget QToolButton#qt_calendar_monthbutton:pressed,
        QCalendarWidget QToolButton#qt_calendar_yearbutton:pressed {
            background: #FFC37A;
            border-color: #E07E12;
        }
        QCalendarWidget QAbstractItemView {
            background: #FFFFFF;
            outline: none;
            gridline-color: transparent;
            selection-background-color: #F7921E;
            selection-color: #fff;
            qproperty-textElideMode: ElideNone;
        }
        QCalendarWidget QAbstractItemView::item {
            padding: 2px;
        }
        QCalendarWidget QAbstractItemView::item:hover {
            background: #FFE3C2;
            border: none;
            border-radius: 6px;
        }
        QCalendarWidget QAbstractItemView::item:selected {
            background: #FFC37A;
            border: none;
            border-radius: 6px;
            color: #222;
        }
        QCalendarWidget QTableView QHeaderView::section {
            background: #FFFFFF;
            color: #888;
            border: none;
            padding: 4px 0;
            font-weight: 600;
        }
        QCalendarWidget QToolButton#qt_calendar_prevmonth,
        QCalendarWidget QToolButton#qt_calendar_nextmonth,
        QCalendarWidget QToolButton#qt_calendar_prevyear,
        QCalendarWidget QToolButton#qt_calendar_nextyear {
            background: transparent;
            border: none;
            padding: 0;
            margin: 0 4px;
            min-width: 24px;
            max-width: 24px;
            min-height: 24px;
            max-height: 24px;
            qproperty-iconSize: 16px 16px;
        }
        QCalendarWidget QToolButton#qt_calendar_prevmonth {
            qproperty-arrowType: NoArrow;
            qproperty-icon: url(\"""" + icon_url(ARROW_LEFT_ICON_PATH) + """\");
        }
        QCalendarWidget QToolButton#qt_calendar_nextmonth {
            qproperty-arrowType: NoArrow;
            qproperty-icon: url(\"""" + icon_url(ARROW_RIGHT_ICON_PATH) + """\");
        }
        QCalendarWidget QToolButton#qt_calendar_prevyear {
            qproperty-arrowType: NoArrow;
            qproperty-icon: url(\"""" + icon_url(ARROW_LEFT_ICON_PATH) + """\");
        }
        QCalendarWidget QToolButton#qt_calendar_nextyear {
            qproperty-arrowType: NoArrow;
            qproperty-icon: url(\"""" + icon_url(ARROW_RIGHT_ICON_PATH) + """\");
        }
        QCalendarWidget QToolButton#qt_calendar_prevmonth:hover,
        QCalendarWidget QToolButton#qt_calendar_nextmonth:hover,
        QCalendarWidget QToolButton#qt_calendar_prevyear:hover,
        QCalendarWidget QToolButton#qt_calendar_nextyear:hover {
            background: rgba(0,0,0,0.06);
            border-radius: 12px;
        }

        /* Убираем системные стрелки у всех кнопок с меню */
        QToolButton {
            qproperty-arrowType: NoArrow;
        }
        QToolButton::menu-indicator {
            image: none;
            width: 0px;
            height: 0px;
            margin: 0;
            padding: 0;
            subcontrol-origin: padding;
            subcontrol-position: right center;
        }
        QPushButton::menu-indicator {
            image: none;
            width: 0px;
            height: 0px;
            margin: 0;
            padding: 0;
            subcontrol-origin: padding;
            subcontrol-position: right center;
        }

        /* Диалоги */
        QDialog {
            background: #FFFFFF;
        }
        QWidget#propsCard {
            background: #FFFFFF;
            border: 1px solid #dcdcdc;
            border-radius: 12px;
        }
        QWidget#propsCard QLabel {
            color: #222;
        }
        QWidget#propsCard QDialogButtonBox {
            border-top: 1px solid #eeeeee;
            padding-top: 8px;
        }
        QMessageBox {
            background: #FFFFFF;
        }

        /* Чекбоксы с PNG индикаторами */
        QCheckBox {
            padding: 2px;
        }
        QCheckBox::indicator {
            width: 18px;
            height: 18px;
        }
        QCheckBox::indicator:unchecked {
            image: url(\"""" + icon_url(CHECK_ICON_OFF_PATH) + """\");
        }
        QCheckBox::indicator:checked {
            image: url(\"""" + icon_url(CHECK_ICON_ON_PATH) + """\");
        }
        QCheckBox::indicator:indeterminate {
            image: url(\"""" + icon_url(CHECK_ICON_MID_PATH) + """\");
        }

        /* Круглые чекбоксы через property round=true */
        QCheckBox[round="true"]::indicator {
            width: 18px;
            height: 18px;
        }
        QCheckBox[round="true"]::indicator:unchecked {
            image: url(\"""" + icon_url(RCHECK_ICON_OFF_PATH) + """\");
        }
        QCheckBox[round="true"]::indicator:checked {
            image: url(\"""" + icon_url(RCHECK_ICON_ON_PATH) + """\");
        }
        QCheckBox[round="true"]::indicator:indeterminate {
            image: url(\"""" + icon_url(RCHECK_ICON_ON_PATH) + """\");
        }

        /* Индикаторы в QListView/QListWidget */
        QListView::indicator, QListWidget::indicator {
            width: 18px;
            height: 18px;
        }
        QListView::indicator:unchecked, QListWidget::indicator:unchecked {
            image: url(\"""" + icon_url(CHECK_ICON_OFF_PATH) + """\");
        }
        QListView::indicator:checked, QListWidget::indicator:checked {
            image: url(\"""" + icon_url(CHECK_ICON_ON_PATH) + """\");
        }
        QListView::indicator:indeterminate, QListWidget::indicator:indeterminate {
            image: url(\"""" + icon_url(CHECK_ICON_MID_PATH) + """\");
        }
        QListView::indicator:hover, QListWidget::indicator:hover {
            background: transparent;
            border-radius: 0;
        }
        QCheckBox::indicator:hover {
            background: transparent;
            border-radius: 0;
        }

        /* QSpinBox стрелки */
        QSpinBox::up-button, QSpinBox::down-button {
            background: transparent;
            border: none;
            margin: 0;
            padding: 0;
            width: 16px;
        }
        QSpinBox::up-button:hover, QSpinBox::down-button:hover {
            background: #FFE3C2;
            border: 1px solid #FFA74B;
            border-radius: 6px;
        }
        QSpinBox::up-button:pressed, QSpinBox::down-button:pressed {
            background: #ffca91;
            border: 1px solid #FFA74B;
            border-radius: 6px;
        }
        QSpinBox::up-arrow {
            image: url(\"""" + icon_url_encoded(SORT_ICON_UP_PATH) + """\");
            width: 12px;
            height: 12px;
        }
        QSpinBox::down-arrow {
            image: url(\"""" + icon_url_encoded(SORT_ICON_DOWN_PATH) + """\");
            width: 12px;
            height: 12px;
        }

        /* QLabel базовый стиль */
        QLabel {
            color: #222;
            background: transparent;
        }

        /* QListWidget */
        QListWidget {
            background: #FFFFFF;
            border: 1px solid #dcdcdc;
            border-radius: 12px;
            outline: none;
            selection-background-color: #FFC37A;
            selection-color: #000000;
        }
        QListWidget::item {
            padding: 6px 8px;
            border: none;
        }
        QListWidget::item:hover {
            background: #FFE3C2;
            color: #000000;
        }
        QListWidget::item:selected {
            background: #FFC37A;
            color: #000000;
        }

        /* QScrollArea стили */
        QScrollArea {
            border: none;
            background: #FFFFFF;
        }

        /* QGroupBox - скруглённая рамка */
        QGroupBox {
            background: #FFFFFF;
            border: 1px solid #dcdcdc;
            border-radius: 12px;
            margin-top: 16px;
            padding-top: 8px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 12px;
            padding: 0 8px;
            background-color: #FFFFFF;
            color: #222;
        }

        /* QTextEdit и QPlainTextEdit */
        QTextEdit, QPlainTextEdit {
            border: 1px solid #dcdcdc;
            border-radius: 12px;
            background: #FFFFFF;
            selection-background-color: #FFC37A;
            selection-color: #000000;
            color: #222;
        }

        /* QTabWidget и QTabBar */
        QTabWidget::pane {
            border: none;
            border-radius: 12px;
            margin-top: 8px;
        }
        QTabBar::pane {
            background: #FFFFFF;
            border: none;
        }
        QTabBar::tab {
            background: #FFFFFF;
            color: #222;
            border: 1px solid #dcdcdc;
            border-bottom-color: #dcdcdc;
            padding: 6px 14px;
            border-top-left-radius: 10px;
            border-top-right-radius: 10px;
            margin: 0 4px;
        }
        QTabBar::tab:hover {
            background: #FFE3C2;
            color: #000000;
            border-color: #FFA74B;
        }
        QTabBar::tab:selected {
            background: #FFC37A;
            color: #000000;
            border-color: #FFA74B;
        }
        QTabBar::tab:!selected {
            margin-top: 6px;
        }

        /* QToolBar и QMenuBar */
        QStatusBar, QMenuBar, QToolBar {
            background: #FFFFFF;
            border: 1px solid #dcdcdc;
        }

        /* QDockWidget */
        QDockWidget::title {
            background: #FFFFFF;
            border: 1px solid #dcdcdc;
        }

        /* Баннер кеширования */
        QFrame#cacheBanner {
            background: #FFE3C2;
            border: 1px solid #FFA74B;
            border-radius: 8px;
        }
        QFrame#cacheBanner QLabel {
            color: #000000;
            font-weight: 600;
        }
    """
    )

    # Overrides to align with Dekstop.py button hover/pressed and splitter hover
    style += (
        """
        /* ===================== Dekstop.py Overrides ===================== */
        /* Buttons hover/pressed: translucent orange with border accents */
        QToolButton#btn_primary:hover, QPushButton#btn_primary:hover,
        QPushButton[objectName="btn_primary"]:hover,
        QToolButton[class="primary"]:hover, QPushButton[class="primary"]:hover {
            background: rgba(247, 146, 30, 0.10);
            color: #000000;
            border-color: #FFA74B;
        }
        QToolButton#btn_primary:pressed, QPushButton#btn_primary:pressed,
        QPushButton[objectName="btn_primary"]:pressed,
        QToolButton[class="primary"]:pressed, QPushButton[class="primary"]:pressed {
            background: rgba(247, 146, 30, 0.20);
            border-color: #E07E12;
        }

        QToolButton:hover, QPushButton:hover,
        QToolButton#btn_secondary:hover, QPushButton#btn_secondary:hover,
        QPushButton[objectName="btn_secondary"]:hover,
        QToolButton[class="secondary"]:hover, QPushButton[class="secondary"]:hover,
        QPushButton[secondary="true"]:hover, QToolButton[secondary="true"]:hover,
        QDialogButtonBox QPushButton:hover {
            background: rgba(247, 146, 30, 0.10);
            color: #000000;
            border-color: #FFA74B;
        }
        QToolButton:pressed, QPushButton:pressed,
        QToolButton#btn_secondary:pressed, QPushButton#btn_secondary:pressed,
        QPushButton[objectName="btn_secondary"]:pressed,
        QToolButton[class="secondary"]:pressed, QPushButton[class="secondary"]:pressed,
        QPushButton[secondary="true"]:pressed, QToolButton[secondary="true"]:pressed,
        QDialogButtonBox QPushButton:pressed {
            background: rgba(247, 146, 30, 0.20);
            border-color: #E07E12;
        }

        /* Splitter hover */
        QSplitter::handle:hover {
            background: rgba(247, 146, 30, 0.12);
        }
        """
    )
    
    # Apply dark theme color replacements if needed
    if dark:
        style = _replace_colors_for_dark(style)
    
    (target or app).setStyleSheet(style)


# --- Helper functions to replace nik_style functionality ---

def is_dark_theme(app: QtWidgets.QApplication | None = None) -> bool:
    """Check if dark theme is active (copied from nik_style)."""
    app = app or QtWidgets.QApplication.instance()
    if not app:
        return False
    prop = app.property("nik_theme")
    if isinstance(prop, str):
        return prop.lower() == "dark"
    pal = app.palette()
    base = pal.color(QtGui.QPalette.Window)
    return (0.299 * base.red() + 0.587 * base.green() + 0.114 * base.blue()) < 128


def resolve_icon_path(name: str, icon_dir: str, *, app: QtWidgets.QApplication | None = None) -> str:
    """Resolve icon path based on theme (simplified from nik_style)."""
    app = app or QtWidgets.QApplication.instance()
    dark = is_dark_theme(app) if app else False
    
    # Icon mapping (simplified)
    icon_files = {
        "navigation": "navigation.png",
        "arrow_left": "arrow-left.png",
        "arrow_right": "arrow-right.png",
        "rotate_left": "rotate-left.png",
        "rotate_right": "rotate-right.png",
        "1": "1.png",
        "2": "2.png",
        "move": "move.png",
        "compare": "compare.png",
        "extend": "extend.png",
    }
    
    filename = icon_files.get(name, f"{name}.png")
    path = os.path.join(icon_dir, filename)
    
    if not os.path.exists(path):
        # Try alternative naming
        alt_path = os.path.join(icon_dir, name.replace("_", "-") + ".png")
        if os.path.exists(alt_path):
            path = alt_path
    
    return path if os.path.exists(path) else ""


def apply_rotate_left_button(button: QtWidgets.QPushButton, icon_dir: str) -> None:
    """Apply rotate-left icon to button."""
    app = QtWidgets.QApplication.instance()
    path = resolve_icon_path("rotate_left", icon_dir, app=app)
    if path:
        pm = QtGui.QPixmap(path)
        if not pm.isNull():
            pm = pm.scaled(16, 16, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            # Default color: white in dark theme, black in light theme
            tint = QtGui.QColor(Qt.white) if is_dark_theme(app) else QtGui.QColor(0, 0, 0)
            tinted = QtGui.QPixmap(pm.size())
            tinted.fill(QtCore.Qt.transparent)
            p = QtGui.QPainter(tinted)
            p.drawPixmap(0, 0, pm)
            p.setCompositionMode(QtGui.QPainter.CompositionMode_SourceIn)
            p.fillRect(tinted.rect(), tint)
            p.end()
            button.setIcon(QtGui.QIcon(tinted))
            button.setIconSize(QtCore.QSize(16, 16))


def apply_rotate_right_button(button: QtWidgets.QPushButton, icon_dir: str) -> None:
    """Apply rotate-right icon to button."""
    app = QtWidgets.QApplication.instance()
    path = resolve_icon_path("rotate_right", icon_dir, app=app)
    if path:
        pm = QtGui.QPixmap(path)
        if not pm.isNull():
            pm = pm.scaled(16, 16, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            # Default color: white in dark theme, black in light theme
            tint = QtGui.QColor(Qt.white) if is_dark_theme(app) else QtGui.QColor(0, 0, 0)
            tinted = QtGui.QPixmap(pm.size())
            tinted.fill(QtCore.Qt.transparent)
            p = QtGui.QPainter(tinted)
            p.drawPixmap(0, 0, pm)
            p.setCompositionMode(QtGui.QPainter.CompositionMode_SourceIn)
            p.fillRect(tinted.rect(), tint)
            p.end()
            button.setIcon(QtGui.QIcon(tinted))
            button.setIconSize(QtCore.QSize(16, 16))


# ThemeSwitch widget with sun/moon icons (from Dekstop.py)
class ThemeSwitch(QtWidgets.QAbstractButton):
    """Theme toggle switch with sun/moon icons."""
    toggledTheme = QtCore.Signal(str)
    
    def __init__(self, parent=None, icon_dir: str = "icon"):
        super().__init__(parent)
        self.setCheckable(True)
        self._icon_dir = icon_dir
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setToolTip("Переключить тему")
        self.setFixedSize(66, 28)
        
        # Load sun and moon icons
        self._sun_icon = self._load_icon(os.path.join(icon_dir, "sun.png"))
        self._moon_icon = self._load_icon(os.path.join(icon_dir, "moon.png"))
        
        app = QtWidgets.QApplication.instance()
        self.setChecked(is_dark_theme(app))
        
        self.toggled.connect(self._on_toggled)
    
    @staticmethod
    def _load_icon(path: str) -> QtGui.QPixmap:
        """Load icon from path."""
        if path and os.path.exists(path):
            pm = QtGui.QPixmap(path)
            if not pm.isNull():
                return pm
        return QtGui.QPixmap()
    
    def _on_toggled(self, checked: bool):
        app = QtWidgets.QApplication.instance()
        new_theme = THEME_DARK if checked else THEME_LIGHT
        win = self.window()
        apply_dekstop_style(app, dark=checked, target=win if win else None)
        save_theme(new_theme)
        self.toggledTheme.emit(new_theme)
    
    def sizeHint(self):
        return QtCore.QSize(66, 28)
    
    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        
        rect = self.rect()
        track = rect.adjusted(1, 1, -1, -1)
        
        dark = self.isChecked()
        
        # Background track (as in Dekstop.py)
        track_bg = QtGui.QColor("#555555" if dark else "#e8e8e8")
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(track_bg)
        radius = track.height() / 2.0
        p.drawRoundedRect(track, radius, radius)
        
        # Icon positions
        icon_size = int(track.height() * 0.5)
        center_y = track.center().y()
        left_x = track.left() + 6
        right_x = track.right() - icon_size - 6
        
        # Icons swap positions (sun on left in light theme, moon on left in dark theme)
        sun_on_left = True  # Always keep sun on left for simplicity
        sun_x = left_x
        moon_x = right_x
        
        # Prepare tinted pixmaps (black in light theme, white in dark theme)
        tint = QtGui.QColor(Qt.white) if dark else QtGui.QColor("#000000")
        sun_pm = QtGui.QPixmap()
        moon_pm = QtGui.QPixmap()
        
        if not self._sun_icon.isNull():
            _sun = self._sun_icon.scaled(icon_size, icon_size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            sun_pm = self._tint_pixmap(_sun, tint)
        
        if not self._moon_icon.isNull():
            _moon = self._moon_icon.scaled(icon_size, icon_size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            moon_pm = self._tint_pixmap(_moon, tint)
        
        # Highlight the selected theme icon (orange circle)
        p.save()
        p.setPen(QtCore.Qt.NoPen)
        if not dark and not sun_pm.isNull():
            # Light theme selected -> highlight sun
            hl_size = icon_size + 8
            p.setBrush(QtGui.QColor("#F7921E"))
            p.drawEllipse(QtCore.QRectF(
                sun_x - (hl_size - icon_size) / 2,
                center_y - hl_size / 2,
                hl_size,
                hl_size
            ))
        elif dark and not moon_pm.isNull():
            # Dark theme selected -> highlight moon
            hl_size = icon_size + 8
            p.setBrush(QtGui.QColor("#F7921E"))
            p.drawEllipse(QtCore.QRectF(
                moon_x - (hl_size - icon_size) / 2,
                center_y - hl_size / 2,
                hl_size,
                hl_size
            ))
        p.restore()
        
        # Draw icons on top
        if not sun_pm.isNull():
            p.drawPixmap(int(sun_x), int(center_y - sun_pm.height() / 2), sun_pm)
        if not moon_pm.isNull():
            p.drawPixmap(int(moon_x), int(center_y - moon_pm.height() / 2), moon_pm)
        
        p.end()
    
    @staticmethod
    def _tint_pixmap(pm: QtGui.QPixmap, color: QtGui.QColor) -> QtGui.QPixmap:
        """Tint pixmap to specified color."""
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


THUMB_DPI = 50
PAGE_DPI = 300
ICON_PX = 16
THREAD_POOL_WORKERS = 4
DIFF_DRAG_INTERVAL_MS = 8
DIFF_FINAL_DELAY_MS = 60
DIFF_OFFSET_SLACK_PX = 200  # allow some freedom beyond strict canvas bounds

# Detach opened PDFs into memory by default to:
# - avoid holding a file handle (Windows move/rename/delete won't hang)
# - keep the compare session stable even if the source file is moved
# Can be overridden via env var LARIX_PDF_COMPARE_DETACH_MAX_MB (0 disables).
DETACH_PDF_TO_MEMORY_DEFAULT_MAX_MB = 200

def pil_to_qimage(im: Image.Image) -> QtGui.QImage:
    if im.mode != 'RGBA':
        im = im.convert('RGBA')
    data = im.tobytes('raw', 'RGBA')
    qimg = QtGui.QImage(data, im.width, im.height, QtGui.QImage.Format_RGBA8888)
    return qimg


def fitz_page_to_pil(page: fitz.Page, dpi: int = PAGE_DPI, rotation: int = 0, low_quality: bool = False) -> Image.Image:
    mat = fitz.Matrix(dpi / 72.0, dpi / 72.0).prerotate(int(rotation or 0))
    # Для быстрого preview используем меньшее разрешение и без сглаживания
    if low_quality:
        pix = page.get_pixmap(matrix=mat, alpha=False, dpi=dpi)
    else:
        pix = page.get_pixmap(matrix=mat, alpha=False)
    mode = 'RGB'
    im = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
    return im


class ImageView(QtWidgets.QLabel):
    # requestDrag(dx, dy, offset_mode)
    # offset_mode=True means "adjust diff alignment" (not panning)
    requestDrag = QtCore.Signal(int, int, bool)
    zoomChanged = QtCore.Signal(float)
    dragStarted = QtCore.Signal()
    dragEnded = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setBackgroundRole(QtGui.QPalette.Base)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self._dragging = False
        self._drag_offset_mode = False
        self._zoom = 1.0
        
        # Таймер для сглаживания быстрого зума колесом
        self._zoom_timer = QtCore.QTimer(self)
        self._zoom_timer.setSingleShot(True)
        self._zoom_timer.timeout.connect(self._emit_zoom)
        self._zoom_pending = None
    
    def _emit_zoom(self):
        """Отложенная отправка сигнала зума для сглаживания."""
        if self._zoom_pending is not None:
            try:
                self.zoomChanged.emit(self._zoom_pending)
            except Exception:
                pass
            self._zoom_pending = None

    def wheelEvent(self, ev: QtGui.QWheelEvent) -> None:
        angle = ev.angleDelta().y()
        # запоминаем позицию курсора в глобальных координатах - для зума к точке
        try:
            # Попробуем несколько способов получить глобальную позицию
            if hasattr(ev, 'globalPosition'):
                pos = ev.globalPosition()
                if hasattr(pos, 'toPoint'):
                    self._last_global = pos.toPoint()
                else:
                    self._last_global = QtCore.QPoint(int(pos.x()), int(pos.y()))
            elif hasattr(ev, 'globalPos'):
                self._last_global = ev.globalPos()
            else:
                self._last_global = None
        except Exception as e:
            # Fallback: используем локальную позицию + mapToGlobal
            try:
                if hasattr(ev, 'position'):
                    local_pos = ev.position()
                    local_point = QtCore.QPoint(int(local_pos.x()), int(local_pos.y()))
                elif hasattr(ev, 'pos'):
                    local_point = ev.pos()
                else:
                    local_point = QtCore.QPoint(0, 0)
                self._last_global = self.mapToGlobal(local_point)
            except Exception:
                self._last_global = None

        # Slightly larger zoom step to feel responsive on big drawings.
        self._zoom *= 1.12 if angle > 0 else 1/1.12
        # Убираем жесткое ограничение сверху - позволяем отдаляться больше для больших файлов
        self._zoom = max(0.05, min(10.0, self._zoom))
        
        # Используем отложенную отправку сигнала для плавности
        self._zoom_pending = self._zoom
        self._zoom_timer.stop()
        self._zoom_timer.start(50)  # 50ms задержка для группировки быстрых событий колеса
        
        ev.accept()

    def mousePressEvent(self, ev: QtGui.QMouseEvent) -> None:
        # Check if we're in diff offset mode first
        is_offset_mode = False
        try:
            win = self.window()
            if getattr(win, 'mode', None) == 'diff' and getattr(getattr(win, 'btn_offset', None), 'isChecked', lambda: False)():
                is_offset_mode = True
        except Exception:
            pass

        mods = ev.modifiers()

        # Pan override: middle click always pans; Ctrl+LMB pans even in offset mode.
        force_pan = False
        try:
            if ev.button() == QtCore.Qt.MiddleButton:
                force_pan = True
            elif ev.button() == QtCore.Qt.LeftButton and (mods & QtCore.Qt.ControlModifier):
                force_pan = True
        except Exception:
            force_pan = False

        # Left button: pan (scrollbars) OR offset mode when enabled
        if ev.button() == QtCore.Qt.LeftButton:
            if is_offset_mode and not force_pan:
                # Offset mode: adjust diff alignment
                self._dragging = True
                self._drag_offset_mode = True
                self._last = ev.position().toPoint()
                try:
                    self.setCursor(QtCore.Qt.ClosedHandCursor)
                except Exception:
                    pass
                try:
                    self.dragStarted.emit()
                except Exception:
                    pass
                return

            # Normal pan mode
            # Проверяем, есть ли вообще смысл в перемещении
            # Если scrollbars не активны (изображение помещается целиком), не начинаем drag
            # Ищем реальную QScrollArea выше по иерархии и проверяем, есть ли что панорамировать
            sa = self.parent()
            while sa is not None and not isinstance(sa, QtWidgets.QScrollArea):
                sa = sa.parent()
            can_drag = False
            try:
                if sa is not None:
                    hbar = sa.horizontalScrollBar()
                    vbar = sa.verticalScrollBar()
                    vp = sa.viewport()
                    pm = getattr(self, "pixmap", lambda: None)()
                    need_h = need_v = False
                    if isinstance(pm, QtGui.QPixmap) and not pm.isNull():
                        need_h = pm.width() > vp.width()
                        need_v = pm.height() > vp.height()
                    can_drag = (need_h or need_v)

                else:
                    can_drag = False
            except Exception:
                can_drag = False

            if not can_drag:
                # Если перемещаться некуда, не активируем режим перетаскивания
                super().mousePressEvent(ev)
                return

            self._dragging = True
            self._drag_offset_mode = False
            self._last = ev.position().toPoint()
            try:
                self.setCursor(QtCore.Qt.ClosedHandCursor)
            except Exception:
                pass
            try:
                self.dragStarted.emit()
            except Exception:
                pass

        # Middle button: pan mode
        elif ev.button() == QtCore.Qt.MiddleButton:
            self._dragging = True
            self._drag_offset_mode = False
            self._last = ev.position().toPoint()
            try:
                self.setCursor(QtCore.Qt.ClosedHandCursor)
            except Exception:
                pass
            try:
                self.dragStarted.emit()
            except Exception:
                pass

        # Right button: also adjust diff alignment (when enabled)
        elif ev.button() == QtCore.Qt.RightButton:
            try:
                win = self.window()
                if getattr(win, 'mode', None) != 'diff':
                    super().mousePressEvent(ev)
                    return
                if not getattr(getattr(win, 'btn_offset', None), 'isChecked', lambda: False)():
                    super().mousePressEvent(ev)
                    return
            except Exception:
                super().mousePressEvent(ev)
                return

            self._dragging = True
            self._drag_offset_mode = True
            self._last = ev.position().toPoint()
            try:
                self.setCursor(QtCore.Qt.ClosedHandCursor)
            except Exception:
                pass
            try:
                self.dragStarted.emit()
            except Exception:
                pass

        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev: QtGui.QMouseEvent) -> None:
        if self._dragging:
            d = ev.position().toPoint() - self._last
            self._last = ev.position().toPoint()
            try:
                self.requestDrag.emit(d.x(), d.y(), bool(self._drag_offset_mode))
            except Exception:
                pass
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev: QtGui.QMouseEvent) -> None:
        try:
            self.dragEnded.emit()
        except Exception:
            pass
        self._dragging = False
        self._drag_offset_mode = False
        try:
            self.unsetCursor()
        except Exception:
            pass
        super().mouseReleaseEvent(ev)


    def keyPressEvent(self, ev: QtGui.QKeyEvent) -> None:
        # Forward arrow-key nudging to parent window in diff/offset scenarios
        try:
            win = self.window()
            if hasattr(win, 'mode') and win.mode == 'diff':
                mods = ev.modifiers()
                step = 5
                if mods & QtCore.Qt.ControlModifier:
                    step = 1
                elif mods & QtCore.Qt.ShiftModifier:
                    step = 20
                sign = -1 if (mods & QtCore.Qt.AltModifier) else 1
                if ev.key() == QtCore.Qt.Key_Left:
                    getattr(win, '_adjust_diff_offset', lambda *_: None)(-step * sign, 0); ev.accept(); return
                if ev.key() == QtCore.Qt.Key_Right:
                    getattr(win, '_adjust_diff_offset', lambda *_: None)(step * sign, 0); ev.accept(); return
                if ev.key() == QtCore.Qt.Key_Up:
                    getattr(win, '_adjust_diff_offset', lambda *_: None)(0, -step * sign); ev.accept(); return
                if ev.key() == QtCore.Qt.Key_Down:
                    getattr(win, '_adjust_diff_offset', lambda *_: None)(0, step * sign); ev.accept(); return
        except Exception:
            pass
        super().keyPressEvent(ev)

class _CachingDialog(QtWidgets.QDialog):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setModal(False)  # не блокируем UI
        self.setWindowTitle("Подождите")
        self.setWindowFlags(
            QtCore.Qt.Dialog
            | QtCore.Qt.WindowTitleHint
            | QtCore.Qt.CustomizeWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
        )
        
        self._cancelled = False  # Flag for cancellation
        
        # Load warning icon from the same path as Dekstop.py
        pm = QtGui.QPixmap(WARNING_ICON_PATH)
        
        # Set window icon
        if not pm.isNull():
            self.setWindowIcon(QtGui.QIcon(pm))
        else:
            try:
                self.setWindowIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MessageBoxWarning))
            except Exception:
                pass

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(14, 12, 14, 12)
        main_layout.setSpacing(8)

        # Верхняя часть: иконка + текст + прогресс
        content_layout = QtWidgets.QHBoxLayout()
        content_layout.setSpacing(8)

        # слева - пиктограмма (warning icon как в Dekstop.py)
        ico = QtWidgets.QLabel(self)
        if not pm.isNull():
            # Use the same icon size as in Dekstop.py QMessageBox
            size_px = QtWidgets.QApplication.style().pixelMetric(QtWidgets.QStyle.PM_MessageBoxIconSize)
            ico.setPixmap(pm.scaled(size_px, size_px, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
        else:
            ico.setText("⚠")
            ico.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)

        # справа - текст + прогресс
        right = QtWidgets.QVBoxLayout()
        right.setSpacing(8)

        self._lbl = QtWidgets.QLabel(text, self)
        self._lbl.setWordWrap(True)
        self._lbl.setAlignment(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft)
        # Match font from Dekstop.py QMessageBox
        self._lbl.setTextFormat(QtCore.Qt.PlainText)

        self._bar = QtWidgets.QProgressBar(self)
        self._bar.setRange(0, 100)  # Реальный прогресс вместо индикатора "занято"
        self._bar.setValue(0)
        self._bar.setTextVisible(True)
        self._bar.setFormat("%p%")  # Показываем проценты
        self._bar.setFixedWidth(200)

        right.addWidget(self._lbl)
        right.addWidget(self._bar)

        content_layout.addWidget(ico, 0, QtCore.Qt.AlignTop)
        content_layout.addLayout(right, 1)

        # Кнопка отмены
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch()
        
        self._cancel_btn = QtWidgets.QPushButton("Отмена", self)
        self._cancel_btn.setObjectName("btn_secondary")
        self._cancel_btn.clicked.connect(self._on_cancel)
        self._cancel_btn.setFixedWidth(100)
        
        button_layout.addWidget(self._cancel_btn)

        main_layout.addLayout(content_layout)
        main_layout.addLayout(button_layout)

        # Match sizing from Dekstop.py (минимум 420px ширины)
        try:
            self.setMinimumWidth(420)
        except Exception:
            pass
        try:
            self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        except Exception:
            pass
        
        # Auto-size like in Dekstop.py
        try:
            self.layout().setSizeConstraint(QtWidgets.QLayout.SetMinimumSize)
            self.adjustSize()
        except Exception:
            pass
        
        # Set window title bar theme based on current app theme
        try:
            app = QtWidgets.QApplication.instance()
            if app:
                theme_prop = app.property("nik_theme")
                dark = (theme_prop == "dark") if theme_prop else False
                _set_window_theme(self, dark=dark)
        except Exception:
            pass
    
    def _on_cancel(self):
        """Handle cancel button click."""
        self._cancelled = True
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.setText("Отмена...")
        self.set_message("Отмена кэширования...")
        # Force close after short delay to ensure parent gets the message
        QtCore.QTimer.singleShot(500, self.close)
    
    def closeEvent(self, event):
        """Handle dialog close - always mark as cancelled if not completed."""
        if not self._cancelled and self._bar.value() < 100:
            self._cancelled = True
        super().closeEvent(event)
    
    def is_cancelled(self) -> bool:
        """Check if user cancelled the operation."""
        return self._cancelled
    
    def set_progress(self, value: int) -> None:
        """Update progress bar value (0-100)."""
        try:
            if 0 <= value <= 100:
                self._bar.setValue(value)
        except Exception:
            pass

    def set_message(self, text: str) -> None:
        try:
            self._lbl.setText(text or "")
        except Exception:
            pass

    def finish_and_close(self, ok_text: str = "Кеширование завершено", auto_close_ms: int = 800) -> None:
        try:
            self._bar.setValue(100)  # Set to 100% on completion
        except Exception:
            pass
        try:
            self._lbl.setText(ok_text or "")
        except Exception:
            pass
        try:
            # Change cancel button to close button
            self._cancel_btn.setEnabled(True)
            self._cancel_btn.setText("Закрыть")
            # Disconnect old handler and connect new one
            try:
                self._cancel_btn.clicked.disconnect()
            except Exception:
                pass
            self._cancel_btn.clicked.connect(self.close)
        except Exception:
            pass
        
        # Безопасное закрытие с проверкой существования объекта
        def safe_close():
            try:
                from shiboken6 import isValid
                if isValid(self):
                    self.close()
            except Exception:
                try:
                    self.close()
                except Exception:
                    pass
        
        try:
            QtCore.QTimer.singleShot(auto_close_ms, safe_close)
        except Exception:
            pass
            QtCore.QTimer.singleShot(max(200, int(auto_close_ms)), safe_close)
        except Exception:
            safe_close()

class PDFCompareWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('PDF сравнение')
        try:
            if os.path.exists(ICON_PATH):
                self.setWindowIcon(QtGui.QIcon(ICON_PATH))
        except Exception:
            pass
        self.resize(1200, 800)

        # State
        self.pdf1: fitz.Document | None = None
        self.pdf2: fitz.Document | None = None
        self.pdf1_path: str | None = None
        self.pdf2_path: str | None = None

        # Keep source PDFs detached in memory (prevents file locking).
        self._pdf1_bytes: bytes | None = None
        self._pdf2_bytes: bytes | None = None
        try:
            _mb = int(os.environ.get("LARIX_PDF_COMPARE_DETACH_MAX_MB", str(DETACH_PDF_TO_MEMORY_DEFAULT_MAX_MB)))
        except Exception:
            _mb = DETACH_PDF_TO_MEMORY_DEFAULT_MAX_MB
        self._detach_stream_max_bytes = max(0, int(_mb)) * 1024 * 1024
        self.page1 = 0
        self.page2 = 0
        self.rotation = 0
        self.scale = 1.0
        self.offset = QtCore.QPoint(0, 0)  # for diff
        self.mode = 'diff'  # 'pdf1' | 'pdf2' | 'diff'
        self._fitted_once = False
        self._layout_applied = False  # флаг для предотвращения повторного вызова _apply_initial_layout
        # Маппинг и пер-страничные смещения (как в tkinter-версии)
        self.mappings: list[tuple[int,int]] = []     # [(p1, p2), ...]
        self.page_offsets: dict[tuple[int,int], QtCore.QPoint] = {}  # {(p1,p2): QPoint}

        # Render cache to make zooming smooth: store high-DPI page images
        # Adaptive max DPI based on page size - smaller DPI for larger formats
        self._cache_max_dpi = 600  # Default for A4 and smaller
        self._adaptive_cache_dpi = True  # Enable adaptive DPI selection
        self._page_cache: dict[tuple[int,int,int,int], Image.Image] = {}
        self._binary_cache: dict[tuple[int,int,int,int], np.ndarray] = {}
        # Background workers + UI queue
        self._pool = ThreadPoolExecutor(max_workers=THREAD_POOL_WORKERS)
        self._ui_queue = queue.Queue()
        self._ui_timer = QtCore.QTimer(self)
        self._ui_timer.timeout.connect(self._process_ui_queue)
        self._ui_timer.start(8)

        # PyMuPDF (fitz) is not reliably thread-safe on a single Document.
        # We serialize all load_page/get_pixmap work to avoid native crashes.
        self._fitz_lock = threading.RLock()
        
        # Lock for cache access to prevent race conditions between main and worker threads
        self._cache_lock = threading.RLock()

        # Background work suspension (when window is deactivated).
        # This keeps the rest of the app responsive during operations like move/rename.
        self._bg_paused = False
        self._bg_epoch = 0

        # Coalesced drag for diff
        self._render_seq = 0
        self._drag_accum = QtCore.QPoint(0, 0)
        self._drag_scheduled = False
        self._diff_final_timer = QtCore.QTimer(self)
        self._diff_final_timer.setSingleShot(True)
        self._diff_final_timer.timeout.connect(lambda: self._request_diff_render(low_quality=False))
        # управление потоком рендера diff
        self._diff_busy = False
        self._diff_pending = None  # "low" или "hi"
        
        # управление потоком рендера одиночных страниц (pdf1/pdf2 режимы)
        self._single_render_busy = False
        self._single_render_pending = None  # кортеж (which, page_index, rotation, scale)
        
        # Флаг для блокировки изменения размеров сплиттера
        self._splitter_locked = False
        
        # Theme synchronization with Dekstop.py
        self._current_theme = load_saved_theme()
        self._theme_check_timer = QtCore.QTimer(self)
        self._theme_check_timer.timeout.connect(self._check_theme_change)
        # Timer will be started after UI is fully built to avoid accessing uninitialized widgets
        self._theme_check_started = False

        # Temporary files tracking for cleanup on close
        self._temp_files_to_cleanup = []

        self._build_ui()
        self._connect()
        
        # Start theme check timer after UI is ready
        try:
            QtCore.QTimer.singleShot(200, lambda: self._theme_check_timer.start(1000) if hasattr(self, "_theme_check_timer") else None)
            self._theme_check_started = True
        except Exception:
            pass

    # -----------------------------
    # Display name helper: strip timestamp and copy postfix
    # -----------------------------
    def _check_theme_change(self):
        """Check if theme was changed in Dekstop.py and sync."""
        try:
            saved_theme = load_saved_theme()
            if saved_theme != self._current_theme:
                self._current_theme = saved_theme
                dark = saved_theme == THEME_DARK
                app = QtWidgets.QApplication.instance()
                if app:
                    apply_dekstop_style(app, dark=dark, target=self)
                    _set_window_theme(self, dark=dark)
                    self._apply_toolbar_icons()
                    self._update_ui_state()
                    
                    # Sync theme switch state
                    if hasattr(self, 'theme_switch') and self.theme_switch:
                        try:
                            self.theme_switch.blockSignals(True)
                            self.theme_switch.setChecked(dark)
                            self.theme_switch.blockSignals(False)
                        except Exception:
                            pass
        except Exception:
            pass
    
    def closeEvent(self, event):
        """Handle window close - cleanup temporary files."""
        # Pause all background work immediately
        self._bg_paused = True
        self._bg_epoch = getattr(self, "_bg_epoch", 0) + 1
        
        # Stop theme check timer
        try:
            if hasattr(self, "_theme_check_timer") and self._theme_check_timer is not None:
                self._theme_check_timer.stop()
        except Exception:
            pass
        
        # Shutdown thread pool to prevent worker crashes
        try:
            if hasattr(self, "_pool") and self._pool is not None:
                self._pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        self._pool = None
        
        # Release documents early to avoid Windows file locks.
        try:
            if self.pdf1:
                self.pdf1.close()
        except Exception:
            pass
        try:
            if self.pdf2:
                self.pdf2.close()
        except Exception:
            pass
        self.pdf1 = None
        self.pdf2 = None
        self._pdf1_bytes = None
        self._pdf2_bytes = None

        # Clear caches
        try:
            self._page_cache.clear()
        except Exception:
            pass
        try:
            self._binary_cache.clear()
        except Exception:
            pass

        # Clean up temporary PDF files
        for temp_file in self._temp_files_to_cleanup:
            try:
                if temp_file and os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception:
                pass  # Ignore cleanup errors
        
        # Clear list
        self._temp_files_to_cleanup.clear()
        
        # Stop UI queue timer
        try:
            if hasattr(self, "_ui_timer") and self._ui_timer is not None:
                self._ui_timer.stop()
        except Exception:
            pass
        
        # Stop diff final timer
        try:
            if hasattr(self, "_diff_final_timer") and self._diff_final_timer is not None:
                self._diff_final_timer.stop()
        except Exception:
            pass
        
        # Call parent closeEvent
        try:
            super().closeEvent(event)
        except Exception:
            pass
        self._pool = None
        
        # Release documents early to avoid Windows file locks.
        try:
            if self.pdf1:
                self.pdf1.close()
        except Exception:
            pass
        try:
            if self.pdf2:
                self.pdf2.close()
        except Exception:
            pass
        self.pdf1 = None
        self.pdf2 = None
        self._pdf1_bytes = None
        self._pdf2_bytes = None

        # Clear caches
        try:
            self._page_cache.clear()
        except Exception:
            pass
        try:
            self._binary_cache.clear()
        except Exception:
            pass

        # Clean up temporary PDF files
        for temp_file in self._temp_files_to_cleanup:
            try:
                if temp_file and os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception:
                pass  # Ignore cleanup errors
        
        # Clear the list
        self._temp_files_to_cleanup.clear()
        
        # Stop UI queue timer
        try:
            if hasattr(self, "_ui_timer") and self._ui_timer is not None:
                self._ui_timer.stop()
        except Exception:
            pass
        
        # Call parent closeEvent
        try:
            super().closeEvent(event)
        except Exception:
            pass

    def showEvent(self, ev):
        # Ensure we fit to the real viewport size (open_pdf_path can run before show()).
        try:
            super().showEvent(ev)
        except Exception:
            try:
                QtWidgets.QMainWindow.showEvent(self, ev)
            except Exception:
                pass

        if getattr(self, "_did_initial_fit", False):
            return
        self._did_initial_fit = True

        def _after_layout():
            try:
                if not self.isVisible():
                    QtCore.QTimer.singleShot(50, _after_layout)
                    return
                if not hasattr(self, "view_scroll"):
                    return
                vp = self.view_scroll.viewport().size()
                # Skip too-early tiny sizes.
                if vp.width() < 240 or vp.height() < 240:
                    QtCore.QTimer.singleShot(50, _after_layout)
                    return
                self._fitted_once = False
                self.fit_to_window()
            except Exception:
                pass

        QtCore.QTimer.singleShot(0, _after_layout)

    def _install_wheel_forwarding(self) -> None:
        """Forward wheel events from the scroll viewport to the image view.

        QScrollArea tends to consume wheel events for scrolling, which makes zoom
        unreliable. We forward the wheel to ImageView so zoom works consistently.
        """
        try:
            if not hasattr(self, "view_scroll") or not hasattr(self, "view"):
                return
            vp = self.view_scroll.viewport()
            if vp is None:
                return
            if getattr(self, "_wheel_filter_installed", False):
                return

            win = self

            class _WheelForwardFilter(QtCore.QObject):
                def eventFilter(self, obj, event):
                    try:
                        if event.type() == QtCore.QEvent.Wheel:
                            QtWidgets.QApplication.sendEvent(win.view, event)
                            return True
                    except Exception:
                        return False
                    return False

            self._wheel_forward_filter = _WheelForwardFilter(vp)
            vp.installEventFilter(self._wheel_forward_filter)
            self._wheel_filter_installed = True
        except Exception:
            pass

    def event(self, ev):
        try:
            t = ev.type()
            if t == QtCore.QEvent.WindowDeactivate:
                self._set_bg_paused(True)
            elif t == QtCore.QEvent.WindowActivate:
                self._set_bg_paused(False)
        except Exception:
            pass
        return super().event(ev)

    def _set_bg_paused(self, paused: bool) -> None:
        try:
            paused = bool(paused)
        except Exception:
            paused = False
        if getattr(self, "_bg_paused", False) == paused:
            return
        self._bg_paused = paused
        # Bump epoch so queued tasks can self-abort.
        try:
            self._bg_epoch = int(getattr(self, "_bg_epoch", 0)) + 1
        except Exception:
            self._bg_epoch = 1

    def _bg_token(self) -> int:
        try:
            return int(getattr(self, "_bg_epoch", 0))
        except Exception:
            return 0

    def _bg_should_abort(self, token: int) -> bool:
        try:
            if getattr(self, "_bg_paused", False):
                return True
            return int(token) != int(getattr(self, "_bg_epoch", 0))
        except Exception:
            return False

    def _open_pdf_document(self, path: str) -> tuple[fitz.Document, bytes | None]:
        """Open PDF either from disk path or detached memory stream.

        Detaching to memory avoids holding an OS file handle, so moving/renaming
        the source file won't block.
        """
        # If disabled via env, use normal open.
        if not path:
            raise RuntimeError("Empty path")

        limit = int(getattr(self, "_detach_stream_max_bytes", 0) or 0)
        if limit <= 0:
            return fitz.open(path), None

        try:
            size = os.path.getsize(path)
        except Exception:
            size = None

        # If size is unknown, assume it's safe to detach (best UX).
        if size is not None and size > limit:
            return fitz.open(path), None

        data: bytes | None = None
        try:
            with open(path, "rb") as f:
                data = f.read()
            # Safety: if file grew beyond limit while reading, fall back.
            if len(data) > limit:
                return fitz.open(path), None
            return fitz.open(stream=data, filetype="pdf"), data
        except Exception:
            # Fallback to file-backed open.
            return fitz.open(path), None
    
    def _display_name(self, path: str) -> str:
        if not path:
            return ''
        base = os.path.basename(path)
        name, ext = os.path.splitext(base)
        # Normalize dashes
        s = name
        # Remove trailing " (copy ...)"
        s = re.sub(r"\s*\(copy[^)]*\)$", "", s, flags=re.IGNORECASE)
        # Remove timestamp like " - 20260122_104240"
        s = re.sub(r"\s*-\s*\d{8}_\d{6}\s*$", "", s, flags=re.IGNORECASE)
        # If nothing matched, fallback to original name without timestamp and copy
        s = s.strip()
        return f"{s}{ext}" if s else base

    def _on_theme_toggled(self, theme=None):
        """Переключение темы + обновление иконок и вида."""
        app = QtWidgets.QApplication.instance()
        # Determine if dark theme
        dark = theme == THEME_DARK if theme else False
        # Apply full Dekstop.py style with theme
        apply_dekstop_style(app, dark=dark, target=self)
        # Save theme to settings (sync with Dekstop.py)
        if theme:
            save_theme(theme)
            self._current_theme = theme  # Update current theme
        
        # Set window title bar theme (Windows only)
        _set_window_theme(self, dark=dark)

        # Дублируем обновление иконок
        try:
            apply_rotate_left_button(self.btn_rot_l, icon_dir=ICON_DIR)
            apply_rotate_right_button(self.btn_rot_r, icon_dir=ICON_DIR)
        except Exception:
            pass
        # После применения темы переустановим все иконки сразу (без ожидания hover)
        self._apply_toolbar_icons()
        # Повторная установка иконок после применения палитры, когда она уже обновилась
        QtCore.QTimer.singleShot(0, lambda: self._apply_toolbar_icons())
        self._update_ui_state()

    # UI
    def _build_ui(self):
        central = QtWidgets.QWidget()
        root = QtWidgets.QVBoxLayout(central); root.setContentsMargins(8,6,8,6); root.setSpacing(4)

        # Header controls
        header = QtWidgets.QWidget(); hb = QtWidgets.QHBoxLayout(header); hb.setContentsMargins(0,0,0,0); hb.setSpacing(6)
        self.btn_pdf1 = QtWidgets.QPushButton('Версия 1'); self.btn_pdf1.setObjectName('btn_secondary')
        try:
            self.btn_pdf1.setText("")
            self.btn_pdf1.setIcon(self._make_tinted_icon("1", ICON_PX))
            self.btn_pdf1.setIconSize(QtCore.QSize(ICON_PX, ICON_PX))

        except Exception:
            pass
        self.btn_pdf1.setToolTip("Загрузить PDF - Версия 1")

        self.btn_pdf2 = QtWidgets.QPushButton('Версия 2'); self.btn_pdf2.setObjectName('btn_secondary')
        try:
            self.btn_pdf2.setText("")
            self.btn_pdf2.setIcon(self._make_tinted_icon("2", ICON_PX))
            self.btn_pdf2.setIconSize(QtCore.QSize(ICON_PX, ICON_PX))

        except Exception:
            pass
        self.btn_pdf2.setToolTip("Загрузить PDF - Версия 2")

        self.btn_map  = QtWidgets.QPushButton('Маппинг листов'); self.btn_map.setObjectName('btn_secondary')
        try:
            self.btn_map.setText("")
            self.btn_map.setIcon(self._make_tinted_icon("compare", ICON_PX))
            self.btn_map.setIconSize(QtCore.QSize(ICON_PX, ICON_PX))

        except Exception:
            pass
        self.btn_map.setToolTip("Открыть окно маппинга листов")
        self.btn_map.setEnabled(True)


        self.cmb_mode = QtWidgets.QComboBox(); self.cmb_mode.addItems(['Сравнение','Версия 1','Версия 2'])
        self.cmb_mode.setToolTip("Режим отображения - сравнение или одиночная версия")
        self.btn_nav = QtWidgets.QPushButton('Навигация')
        self.btn_nav.setCheckable(True)
        self.btn_offset = QtWidgets.QPushButton('Смещение')
        self.btn_offset.setCheckable(True)
        try:
            self.btn_offset.setText("")
            self.btn_offset.setIcon(self._make_tinted_icon("move", ICON_PX))
            self.btn_offset.setIconSize(QtCore.QSize(ICON_PX, ICON_PX))

        except Exception:
            pass
        self.btn_offset.setToolTip("Включить режим смещения - двигайте стрелками или мышью")

        # In compare mode users most often want to align overlays.
        # Panning is still available via Ctrl+drag or by toggling this button off.
        try:
            self.btn_offset.setChecked(True)
        except Exception:
            pass

        self.btn_rot_l = QtWidgets.QPushButton('↺')
        self.btn_rot_l.setObjectName('btn_secondary')
        self.btn_rot_l.setFixedSize(32, 32)
        
        self.btn_rot_r = QtWidgets.QPushButton('↻')
        self.btn_rot_r.setObjectName('btn_secondary')
        self.btn_rot_r.setFixedSize(32, 32)
        self.btn_export = QtWidgets.QPushButton('Экспорт PDF')
        self.btn_export.setObjectName('btn_secondary')
        self.btn_export.setToolTip("Экспорт текущего кадра в PDF")
        # кнопка "уместить изображение целиком"
        self.btn_fit = QtWidgets.QPushButton()
        self.btn_fit.setObjectName('btn_secondary')
        self.btn_fit.setFixedSize(32, 32)
        self.btn_fit.setToolTip("Уместить изображение целиком в окно просмотра")


        # Apply rotate icons
        try:
            self.btn_rot_l.setText('')
            self.btn_rot_r.setText('')
            apply_rotate_left_button(self.btn_rot_l, icon_dir=ICON_DIR)
            apply_rotate_right_button(self.btn_rot_r, icon_dir=ICON_DIR)
            self.btn_rot_l.setToolTip('Повернуть влево')
            self.btn_rot_r.setToolTip('Повернуть вправо')
        except Exception:
            pass
        self._apply_toolbar_icons()
        for w in (self.btn_pdf1, self.btn_pdf2, self.btn_map, self.cmb_mode, self.btn_nav, self.btn_offset, self.btn_rot_l, self.btn_rot_r, self.btn_export):
            hb.addWidget(w)
        hb.addStretch(1)
        hb.addWidget(self.btn_fit)  # справа сверху

        # hide legacy "Навигация" button - replaced by edge arrow
        try:
            self.btn_nav.setVisible(False)
        except Exception:
            pass
        self.btn_nav.setVisible(True)
        # прячем старую кнопку "Навигация" - у нас стрелка у левого края
        self.btn_nav.setVisible(False)

        # Theme switch (now internal to PDF_Compare)
        self.theme_switch = ThemeSwitch(icon_dir=ICON_DIR)
        hb.addWidget(self.theme_switch)

        # Splitter
        splitter = QtWidgets.QSplitter(); splitter.setOrientation(QtCore.Qt.Horizontal)
        self.splitter = splitter
        self.splitter.setChildrenCollapsible(False)


        # Navigation panel (thumbnails)
        self.panel = QtWidgets.QWidget(); pv = QtWidgets.QVBoxLayout(self.panel); pv.setContentsMargins(0,0,0,0); pv.setSpacing(4)
        self.thumb_scroll = QtWidgets.QScrollArea(); self.thumb_scroll.setWidgetResizable(True)
        self.thumb_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.thumb_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.thumb_scroll.setViewportMargins(0, 0, 0, 0)
        self.thumb_root = QtWidgets.QWidget(); self.thumb_layout = QtWidgets.QGridLayout(self.thumb_root)
        self.thumb_layout.setContentsMargins(0,0,0,0); self.thumb_layout.setHorizontalSpacing(4); self.thumb_layout.setVerticalSpacing(4)
        self.thumb_scroll.setWidget(self.thumb_root)
        pv.addWidget(self.thumb_scroll, 1)
        self.panel.setMinimumWidth(340)

        # Display area
        self.view = ImageView()
        self.view.setMinimumSize(200, 200)
        self.view_scroll = QtWidgets.QScrollArea()
        self.view_scroll.setWidget(self.view)               # кладём view внутрь скролла
        self.view_scroll.setWidgetResizable(False)
        self.view_scroll.setAlignment(QtCore.Qt.AlignCenter)
        # пиксельный шаг прокрутки - без рывков
        try:
            self.view_scroll.horizontalScrollBar().setSingleStep(1)
            self.view_scroll.verticalScrollBar().setSingleStep(1)
        except Exception:
            pass

        splitter.addWidget(self.panel)                      # панель слева
        splitter.addWidget(self.view_scroll)                # просмотр справа
        # гарантия видимости области просмотра сразу
        try:
            self.view_scroll.show()
            self.view.show()
        except Exception:
            pass

        # edge navigation arrow + container that keeps arrow visible
        self.nav_toggle = QtWidgets.QPushButton()
        self.nav_toggle.setObjectName("btn_secondary")
        self.nav_toggle.setFlat(False)
        self.nav_toggle.setFixedWidth(34)
        self.nav_toggle.setCursor(QtCore.Qt.PointingHandCursor)
        self.nav_toggle.setToolTip("Навигация - открыть/закрыть меню миниатюр")
        self.nav_toggle.setIconSize(QtCore.QSize(ICON_PX, ICON_PX))
        self._set_nav_arrow(False)

        self.nav_container = QtWidgets.QWidget()
        _nh = QtWidgets.QHBoxLayout(self.nav_container); _nh.setContentsMargins(0,0,0,0); _nh.setSpacing(4)
        _nh.addWidget(self.nav_toggle, 0, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        _nh.addWidget(self.panel, 1)

        # Make wheel zoom reliable.
        self._install_wheel_forwarding()

        # replace left pane with the container
        self.splitter.replaceWidget(0, self.nav_container)

        # Кнопку "Навигация" в хедере прячем - теперь есть стрелка у края
        try:
            self.btn_nav.setVisible(False)
        except Exception:
            pass

        self.nav_toggle.clicked.connect(self.toggle_nav)
        self._refresh_all_icons()
                # FORCE: слева nav_container (стрелка + миниатюры), справа view_scroll
        try:
            # убираем лишние виджеты из сплиттера, если вдруг остались
            keep = {id(self.nav_container), id(self.view_scroll)}
            for i in reversed(range(self.splitter.count())):
                w = self.splitter.widget(i)
                if id(w) not in keep:
                    w.setParent(None)

            # гарантируем наличие обеих панелей в сплиттере
            if self.splitter.indexOf(self.nav_container) == -1:
                self.splitter.insertWidget(0, self.nav_container)
            if self.splitter.indexOf(self.view_scroll) == -1:
                self.splitter.addWidget(self.view_scroll)

            # фиксируем порядок: индекс 0 - nav_container, индекс 1 - просмотр
            if self.splitter.indexOf(self.nav_container) != 0:
                self.nav_container.setParent(None)
                self.splitter.insertWidget(0, self.nav_container)
            if self.splitter.indexOf(self.view_scroll) != 1:
                self.view_scroll.setParent(None)
                self.splitter.insertWidget(1, self.view_scroll)

            # левая часть фикс, правая растягивается
            self.splitter.setStretchFactor(0, 0)
            self.splitter.setStretchFactor(1, 1)

            # на всякий случай показываем обе части
            self.nav_container.show()
            self.panel.show()
            self.view.show()
            self.view_scroll.show()
        except Exception:
            pass

        # refresh arrow on theme change
        if getattr(self, "theme_switch", None):
            try:
                self.theme_switch.toggledTheme.connect(lambda _t=None: self._set_nav_arrow(self.panel.isVisible()))
            except Exception:
                pass

        splitter.setStretchFactor(1, 1)

        # правая область тянется, левая фиксирована
        try:
            splitter.setStretchFactor(0, 0)
            splitter.setStretchFactor(1, 1)
        except Exception:
            pass

        # Footer navigation
        footer = QtWidgets.QWidget(); fb = QtWidgets.QHBoxLayout(footer); fb.setContentsMargins(0,0,0,0); fb.setSpacing(6)
        self.lbl_page = QtWidgets.QLabel('Страница:')
        self.ed_page = QtWidgets.QLineEdit(); self.ed_page.setFixedWidth(56)
        self.lbl_total = QtWidgets.QLabel('/ 0')
        
        # Navigation buttons icon size (match Dekstop.py typical 16px)
        NAV_ICON_SIZE = 16
        self.btn_prev = QtWidgets.QPushButton()
        self.btn_prev.setObjectName('btn_secondary')
        self.btn_prev.setIcon(self._make_tinted_icon("arrow_left", NAV_ICON_SIZE))
        self.btn_prev.setIconSize(QtCore.QSize(NAV_ICON_SIZE, NAV_ICON_SIZE))
        self.btn_prev.setFixedSize(32, 32)
        
        self.btn_next = QtWidgets.QPushButton()
        self.btn_next.setObjectName('btn_secondary')
        self.btn_next.setIcon(self._make_tinted_icon("arrow_right", NAV_ICON_SIZE))
        self.btn_next.setIconSize(QtCore.QSize(NAV_ICON_SIZE, NAV_ICON_SIZE))
        self.btn_next.setFixedSize(32, 32)

        # tooltips for footer
        self.btn_prev.setToolTip("Предыдущая страница")
        self.btn_next.setToolTip("Следующая страница")
        self.ed_page.setToolTip("Номер текущей страницы")

        for w in (self.lbl_page, self.ed_page, self.lbl_total, self.btn_prev, self.btn_next):
            fb.addWidget(w)
        fb.addStretch(1)

        root.addWidget(header)
        root.addWidget(splitter, 1)
        root.addWidget(footer)
        self.setCentralWidget(central)
        QtCore.QTimer.singleShot(0, self._apply_initial_layout)
        # применяем корректные иконки после того, как стили полностью применятся
        QtCore.QTimer.singleShot(0, self._apply_toolbar_icons)


    # --- Баннер кеширования (тонкий статус-бар) ---
    def _ensure_cache_banner(self):
        try:
            if getattr(self, "_cache_banner", None) is not None:
                return
            self._cache_banner = QtWidgets.QFrame(self)
            self._cache_banner.setObjectName("cacheBanner")
            self._cache_banner.setVisible(False)

            lay = QtWidgets.QHBoxLayout(self._cache_banner)
            lay.setContentsMargins(10, 6, 10, 6)
            lay.setSpacing(8)

            self._cache_icon = QtWidgets.QLabel("⚠", self._cache_banner)
            self._cache_text = QtWidgets.QLabel("Кеширование файлов - можно продолжать работать", self._cache_banner)
            self._cache_text.setTextInteractionFlags(QtCore.Qt.NoTextInteraction)

            self._cache_pbar = QtWidgets.QProgressBar(self._cache_banner)
            try:
                self._cache_pbar.setRange(0, 0)  # индикатор «занято»
                self._cache_pbar.setTextVisible(False)
                self._cache_pbar.setFixedWidth(120)
                self._cache_pbar.setMaximumHeight(16)  # Тонкий прогресс-бар
            except Exception:
                pass

            lay.addWidget(self._cache_icon, 0)
            lay.addWidget(self._cache_text, 1)
            lay.addWidget(self._cache_pbar, 0)

            # Стили применяются через apply_dekstop_style в CSS
        except Exception:
            pass

    def _show_cache_banner(self, text: str = "Кеширование файлов - можно продолжать работать"):
        try:
            self._ensure_cache_banner()
            self._cache_text.setText(text)
            if not self._cache_banner.isVisible():
                self._cache_banner.show()
        except Exception:
            pass

    def _hide_cache_banner(self):
        try:
            if getattr(self, "_cache_banner", None) is not None:
                self._cache_banner.hide()
        except Exception:
            pass


    # --- диалог «Кеширование…» (не используется, оставлен для совместимости) ---
    def _ensure_caching_dialog(self):
        try:
            dlg = getattr(self, "_caching_dlg", None)
            # если ссылка мёртвая - считаем, что диалога нет
            try:
                from shiboken6 import isValid
                if dlg is not None and not isValid(dlg):
                    dlg = None
            except Exception:
                pass
            if dlg is None:
                self._caching_dlg = _CachingDialog("Кеширование файлов для лучшей работы…", self)
                try:
                    self._caching_dlg.destroyed.connect(lambda *_: setattr(self, "_caching_dlg", None))
                except Exception:
                    pass
            return getattr(self, "_caching_dlg", None)
        except Exception:
            self._caching_dlg = None
            return None



    def _begin_caching(self, n: int = 1):
        try:
            # счётчик задач кеширования
            self._caching_tasks = int(getattr(self, "_caching_tasks", 0)) + int(max(1, n))
            self._total_caching_tasks = int(max(1, n))  # Track total for progress calculation
            self._completed_caching_tasks = 0  # Track completed tasks

            # показываем диалог о кешировании
            dlg = self._ensure_caching_dialog()
            if dlg and not dlg.isVisible():
                try:
                    dlg.show()
                    # Center dialog on parent window
                    if self.isVisible():
                        parent_geom = self.geometry()
                        dlg_geom = dlg.geometry()
                        x = parent_geom.x() + (parent_geom.width() - dlg_geom.width()) // 2
                        y = parent_geom.y() + (parent_geom.height() - dlg_geom.height()) // 2
                        dlg.move(x, y)
                    
                    # Safety timeout: if caching doesn't complete in 10 seconds, force close
                    def _timeout_check():
                        try:
                            # Get current dialog reference
                            timeout_dlg = getattr(self, "_caching_dlg", None)
                            if timeout_dlg and timeout_dlg.isVisible():
                                # Force close - something went wrong
                                self._caching_tasks = 0
                                self._completed_caching_tasks = 0
                                timeout_dlg.set_message("Превышено время ожидания - закрываем...")
                                QtCore.QTimer.singleShot(300, lambda: self._force_close_caching_dialog(timeout_dlg))
                        except Exception:
                            pass
                    
                    # Start safety timeout timer - reduced to 10 seconds
                    QtCore.QTimer.singleShot(10000, _timeout_check)
                    
                except Exception:
                    pass
        except Exception:
            pass


    def _end_caching(self, n: int = 1):
        try:
            self._caching_tasks = max(0, int(getattr(self, "_caching_tasks", 0)) - int(max(1, n)))

            if int(getattr(self, "_caching_tasks", 0)) == 0:
                # все задачи завершены - закрываем диалог
                dlg = getattr(self, "_caching_dlg", None)
                if dlg:
                    # Проверяем, что диалог еще существует и не был уже закрыт
                    try:
                        from shiboken6 import isValid
                        if not isValid(dlg):
                            self._caching_dlg = None
                            return
                    except Exception:
                        pass
                    
                    try:
                        if dlg.isVisible():
                            # Check if cancelled - close immediately without "completion" message
                            if dlg.is_cancelled():
                                QtCore.QTimer.singleShot(0, lambda: self._cancel_caching_dialog(dlg))
                            else:
                                # Вызываем через QTimer для безопасности
                                QtCore.QTimer.singleShot(0, lambda: self._finish_caching_dialog(dlg))
                    except Exception:
                        pass
        except Exception:
            pass
    
    def _cancel_caching_dialog(self, dlg):
        """Cancel and close the caching dialog immediately."""
        try:
            # Force reset caching counter to prevent hanging
            self._caching_tasks = 0
            self._completed_caching_tasks = 0
            
            from shiboken6 import isValid
            if not isValid(dlg):
                self._caching_dlg = None
                return
            if dlg.isVisible():
                dlg.close()
            self._caching_dlg = None
        except Exception:
            # Fallback - force reset counter anyway
            try:
                self._caching_tasks = 0
                self._completed_caching_tasks = 0
                self._caching_dlg = None
            except Exception:
                pass
    
    def _force_close_caching_dialog(self, dlg):
        """Force close the caching dialog (for timeout scenarios)."""
        try:
            self._caching_tasks = 0
            self._completed_caching_tasks = 0
            
            from shiboken6 import isValid
            if isValid(dlg):
                try:
                    dlg.close()
                    dlg.deleteLater()
                except Exception:
                    pass
            self._caching_dlg = None
        except Exception:
            try:
                self._caching_tasks = 0
                self._caching_dlg = None
            except Exception:
                pass
    
    def _update_caching_progress(self):
        """Update progress bar in caching dialog."""
        try:
            dlg = getattr(self, "_caching_dlg", None)
            if dlg and dlg.isVisible():
                total = int(getattr(self, "_total_caching_tasks", 1))
                completed = int(getattr(self, "_completed_caching_tasks", 0))
                if total > 0:
                    progress = int((completed / total) * 100)
                    dlg.set_progress(progress)
        except Exception:
            pass
    
    def _is_caching_cancelled(self) -> bool:
        """Check if user cancelled caching."""
        try:
            dlg = getattr(self, "_caching_dlg", None)
            if dlg:
                return dlg.is_cancelled()
        except Exception:
            pass
        return False
    
    def _finish_caching_dialog(self, dlg):
        """Безопасное завершение диалога кеширования."""
        try:
            from shiboken6 import isValid
            if not isValid(dlg):
                return
            if dlg.isVisible():
                dlg.finish_and_close("Кеширование завершено", auto_close_ms=800)
        except Exception:
            pass




    def _apply_initial_layout(self):
                # безопасная фиксация: слева миниатюры + стрелка, справа просмотр
        # Предотвращаем повторный вызов после первоначальной настройки
        if self._layout_applied:
            return
        self._layout_applied = True
        
        try:
            if self.splitter.indexOf(self.nav_container) != 0:
                self.nav_container.setParent(None)
                self.splitter.insertWidget(0, self.nav_container)
            if self.splitter.indexOf(self.view_scroll) != 1:
                self.view_scroll.setParent(None)
                self.splitter.insertWidget(1, self.view_scroll)
            self.splitter.setStretchFactor(0, 0)
            self.splitter.setStretchFactor(1, 1)
        except Exception:
            pass
        
        # Фиксированная ширина панели на основе известных размеров миниатюр
        # TW=160 для каждой колонки + 18 для номеров + отступы
        TW = 160
        num_columns = 2  # максимум 2 колонки (PDF1 и PDF2)
        index_col_width = 18
        spacing = 4 * (num_columns + 1)  # horizontal spacing между колонками
        
        # Рассчитываем ширину контента: номера + 2 колонки миниатюр + отступы
        content_w = index_col_width + (TW * num_columns) + spacing
        
        frame_w = self.thumb_scroll.frameWidth() * 2 if hasattr(self, "thumb_scroll") else 0
        vbar_w  = self.thumb_scroll.verticalScrollBar().sizeHint().width() if hasattr(self, "thumb_scroll") else 0
        
        # Итоговая ширина панели
        left = int(content_w + frame_w + vbar_w + 10)
        
        # Учитываем ширину стрелки навигации
        try:
            left += self.nav_toggle.sizeHint().width() + 4
        except Exception:
            left += 38  # фиксированная ширина стрелки

        # Устанавливаем только минимальную ширину (без максимальной, чтобы сплиттер работал)
        self.panel.setMinimumWidth(left)
        
        # Применяем размеры сплиттера ОДИН РАЗ при старте
        if hasattr(self, "splitter"):
            self.splitter.setSizes([left, max(1, self.width() - left)])

        # фиксируем левую область как "панель + стрелка"
        try:
            self.splitter.setStretchFactor(0, 0)
            self.splitter.setStretchFactor(1, 1)
        except Exception:
            pass

        try:
            self._nav_saved_width = left
            if hasattr(self, "nav_toggle"):
                self._set_nav_arrow(mirrored=self.panel.isVisible())
        except Exception:
            pass
   

        self.update_view()



    def _connect(self):
        self.btn_pdf1.clicked.connect(lambda: self.open_pdf(1))
        self.btn_pdf2.clicked.connect(lambda: self.open_pdf(2))
        self.btn_map.clicked.connect(lambda _=None: self._open_mapping_window_safe())
        self.cmb_mode.currentIndexChanged.connect(self.on_mode_change)
        self.btn_nav.clicked.connect(self.toggle_nav)
        self.btn_rot_l.clicked.connect(lambda: self.rotate(-90))
        self.btn_rot_r.clicked.connect(lambda: self.rotate(90))
        self.btn_export.clicked.connect(self.export_pdf)
        self.btn_fit.clicked.connect(self.fit_to_window)
        self.btn_prev.clicked.connect(self.prev_page)
        self.btn_next.clicked.connect(self.next_page)
        self.ed_page.returnPressed.connect(self.go_to_page)
        self.view.requestDrag.connect(self.on_drag)
        self.view.zoomChanged.connect(self.on_zoom_changed)
        # фиксация выравнивания области просмотра при ручном перетаскивании
        try:
            self.view.dragStarted.connect(self._on_pan_start)
            self.view.dragEnded.connect(self._on_pan_end)
        except Exception:
            pass

        if self.theme_switch:
            self.theme_switch.toggledTheme.connect(self._on_theme_toggled)
            # Re-apply rotate icons on theme changes for correct tint
            self.theme_switch.toggledTheme.connect(lambda _t=None: apply_rotate_left_button(self.btn_rot_l, icon_dir=ICON_DIR))
            self.theme_switch.toggledTheme.connect(lambda _t=None: apply_rotate_right_button(self.btn_rot_r, icon_dir=ICON_DIR))
            
            # Sync theme switch state with saved theme
            try:
                dark = self._current_theme == THEME_DARK
                self.theme_switch.blockSignals(True)
                self.theme_switch.setChecked(dark)
                self.theme_switch.blockSignals(False)
            except Exception:
                pass

    # -----------------------------
    # Caching helpers
    # -----------------------------
    def _get_adaptive_max_dpi(self, which: int, page_index: int) -> int:
        """Get adaptive max DPI based on page size to prevent huge images for large formats."""
        if not self._adaptive_cache_dpi:
            return self._cache_max_dpi
        
        try:
            doc = self.pdf1 if which == 1 else self.pdf2
            if not doc:
                return self._cache_max_dpi
            
            with getattr(self, "_fitz_lock", threading.RLock()):
                page = doc.load_page(int(page_index))
                rect = page.rect
            
            # Get page dimensions in points (1 point = 1/72 inch)
            width_pt = rect.width
            height_pt = rect.height
            
            # Calculate diagonal in inches
            diagonal_inches = ((width_pt ** 2 + height_pt ** 2) ** 0.5) / 72.0
            
            # Adaptive DPI: smaller for larger pages
            # A4 diagonal ≈ 14" → 600 DPI
            # A3 diagonal ≈ 20" → 400 DPI  
            # A2 diagonal ≈ 28" → 300 DPI
            # A1 diagonal ≈ 40" → 250 DPI
            # A0 diagonal ≈ 56" → 200 DPI
            
            if diagonal_inches < 15:  # A4 and smaller
                return 600
            elif diagonal_inches < 22:  # A3
                return 400
            elif diagonal_inches < 32:  # A2
                return 300
            elif diagonal_inches < 48:  # A1
                return 250
            else:  # A0 and larger
                return 200
        except Exception:
            return self._cache_max_dpi
    
    def _cache_key(self, which: int, page: int, rotation: int, dpi: int) -> tuple[int,int,int,int]:
        return (int(which), int(page), int(rotation) % 360, int(dpi))

    def _get_page_image(self, which: int, page_index: int, dpi: int, rotation: int, low_quality: bool = False) -> Image.Image:
        key = self._cache_key(which, page_index, rotation, dpi)
        
        # Thread-safe cache read
        with getattr(self, "_cache_lock", threading.RLock()):
            img = self._page_cache.get(key)
        if img is not None:
            return img
            
        doc = self.pdf1 if which == 1 else self.pdf2
        if doc is None:
            raise RuntimeError("Document not loaded")
            
        # Render page with fitz lock
        with getattr(self, "_fitz_lock", threading.RLock()):
            p = doc.load_page(int(page_index))
            img = fitz_page_to_pil(p, dpi=int(dpi), rotation=int(rotation), low_quality=low_quality)
        
        # Thread-safe cache write
        with getattr(self, "_cache_lock", threading.RLock()):
            self._page_cache[key] = img
        return img

    def _get_best_page_image(self, which: int, page_index: int, eff_dpi: int, rotation: int) -> Image.Image:
        # Prefer pre-cached max-DPI image for smooth zooming
        # Use adaptive max DPI based on page size
        adaptive_max_dpi = self._get_adaptive_max_dpi(which, page_index)
        key_max = self._cache_key(which, page_index, rotation, adaptive_max_dpi)
        # Thread-safe cache read
        with getattr(self, "_cache_lock", threading.RLock()):
            img = self._page_cache.get(key_max)
        if img is not None:
            return img
        return self._get_page_image(which, page_index, eff_dpi, rotation)

    def _clear_page_cache(self):
        try:
            self._page_cache.clear()
        except Exception:
            self._page_cache = {}
        try:
            self._binary_cache.clear()
        except Exception:
            self._binary_cache = {}

    def _precache_current_pages_maxdpi(self):
        # Synchronous pre-render of current pages at max DPI to trade initial load time for smooth zoom later
        try:
            if self.pdf1:
                self._get_page_image(1, self.page1, self._cache_max_dpi, self.rotation)
            if self.pdf2:
                self._get_page_image(2, self.page2, self._cache_max_dpi, self.rotation)
        except Exception:
            pass
    def _get_binary_mask(self, which: int, page_index: int, dpi: int, rotation: int) -> np.ndarray:
        key = (int(which), int(page_index), int(rotation) % 360, int(dpi))
        # Thread-safe cache read
        with getattr(self, "_cache_lock", threading.RLock()):
            m = getattr(self, "_binary_cache", {}).get(key)
        if m is not None:
            return m
        im = self._get_page_image(which, page_index, int(dpi), int(rotation))
        arr = np.asarray(im, dtype=np.uint8)
        try:
            gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        except Exception:
            gray = arr if arr.ndim == 2 else cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        t, _ = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        thr = int(max(210, min(245, t)))
        content = (gray < thr).astype(np.uint8) * 255
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        content = cv2.morphologyEx(content, cv2.MORPH_OPEN, k, iterations=1)
        # Thread-safe cache write
        try:
            with getattr(self, "_cache_lock", threading.RLock()):
                self._binary_cache[key] = content
        except Exception:
            pass
        return content

    # -----------------------------
    # Background tasks + coalesced diff render + prefetch
    # -----------------------------
    def _start_background_task(self, fn):
        # Do not schedule new work while paused.
        if getattr(self, "_bg_paused", False):
            return
        token = self._bg_token()

        def _wrapped():
            try:
                if self._bg_should_abort(token):
                    return
            except Exception:
                pass
            try:
                fn()
            except Exception:
                pass

        try:
            self._pool.submit(_wrapped)
        except Exception:
            try:
                from concurrent.futures import ThreadPoolExecutor as _TP
                self._pool = _TP(max_workers=THREAD_POOL_WORKERS)
                self._pool.submit(_wrapped)
            except Exception:
                pass

    def _process_ui_queue(self):
        try:
            max_per_tick = 16
            processed = 0
            latest_diff = None  # (pil, used_dpi, is_low)
            latest_single = None  # (pil, used_dpi, used_max_dpi, scale, which, page_index)

            while processed < max_per_tick:
                try:
                    item = self._ui_queue.get_nowait()
                except Exception:
                    break

                tag = item[0]

                if tag == "update_cache_progress":
                    # Update caching progress bar
                    self._update_caching_progress()
                    processed += 1
                    continue

                if tag == "diff_ready":
                    # коалесим - берём только последний diff за тик
                    if len(item) >= 5:
                        _, seq, pil, used_dpi, is_low = item
                    else:
                        _, seq, pil, used_dpi = item
                        is_low = False
                    if seq == getattr(self, "_render_seq", 0):
                        latest_diff = (pil, used_dpi, is_low)
                    processed += 1
                    continue

                if tag == "diff_done":
                    # освобождаем блокировку и при необходимости запускаем отложенный рендер
                    self._diff_busy = False
                    pend = getattr(self, "_diff_pending", None)
                    self._diff_pending = None
                    if pend is not None:
                        QtCore.QTimer.singleShot(0, lambda p=pend: self._request_diff_render(low_quality=(p == "low")))
                    processed += 1
                    continue

                if tag == "thumb_ready":
                    try:
                        _, which, page_index, pil_img, tw, th, pw, ph = item
                        pm = QtGui.QPixmap.fromImage(pil_to_qimage(pil_img)).scaled(
                            tw - pw, th - ph, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
                        )
                        if which == 1:
                            if 0 <= page_index < len(self.thumbs1) and self.thumbs1[page_index] is not None:
                                self.thumbs1[page_index].setPixmap(pm)
                        else:
                            if 0 <= page_index < len(self.thumbs2) and self.thumbs2[page_index] is not None:
                                self.thumbs2[page_index].setPixmap(pm)
                    except Exception:
                        pass
                    finally:
                        # Always decrement caching counter, even on error
                        try:
                            # Update progress when thumbnail is complete
                            self._completed_caching_tasks = getattr(self, "_completed_caching_tasks", 0) + 1
                            self._update_caching_progress()
                            self._end_caching(1)
                        except Exception:
                            pass
                    processed += 1
                    continue

                if tag == "thumb_cancelled":
                    # Handle cancelled thumbnail - still need to decrement counter
                    try:
                        self._end_caching(1)
                    except Exception:
                        pass
                    processed += 1
                    continue
                
                if tag == "single_ready":
                    # коалесим - берём только последний single за тик
                    if len(item) >= 8:
                        _, seq, which, page_index, pil, used_dpi, used_max_dpi, scale = item
                    else:
                        processed += 1
                        continue
                    if seq == getattr(self, "_single_render_seq", 0):
                        latest_single = (pil, used_dpi, used_max_dpi, scale, which, page_index)
                    processed += 1
                    continue
                
                if tag == "single_done":
                    # освобождаем блокировку и при необходимости запускаем отложенный рендер
                    self._single_render_busy = False
                    pend = getattr(self, "_single_render_pending", None)
                    self._single_render_pending = None
                    if pend is not None:
                        QtCore.QTimer.singleShot(0, lambda p=pend: self._request_single_render(
                            p[0], p[1], p[2], p[3], low_quality=(p[4] if len(p) > 4 else False)
                        ))
                    processed += 1
                    continue

                # прочие события
                processed += 1

            # отрисовываем только последний single кадр (для pdf1/pdf2 режимов)
            if latest_single is not None and self.mode in ('pdf1', 'pdf2'):
                pil, used_dpi, used_max_dpi, scale, which, page_index = latest_single
                # проверяем, что страница и документ всё ещё актуальны
                current_page = self.page1 if self.mode == 'pdf1' else self.page2
                if page_index == current_page:
                    self._apply_single_render(pil, used_dpi, used_max_dpi, scale)

            # отрисовываем только последний diff кадр
            if latest_diff is not None and self.mode == 'diff':
                pil, used_dpi, is_low = latest_diff
                try:
                    self._last_render_dpi_used = int(used_dpi)
                except Exception:
                    self._last_render_dpi_used = PAGE_DPI

                # первичная подгонка под окно
                try:
                    if not getattr(self, "_fitted_once", False) and hasattr(self, "view_scroll"):
                        vp = self.view_scroll.viewport().size()
                        if pil.width > 0 and pil.height > 0 and vp.width() > 0 and vp.height() > 0:
                            base_scale = float(PAGE_DPI) / float(self._last_render_dpi_used or PAGE_DPI)
                            eff_w = pil.width * base_scale
                            eff_h = pil.height * base_scale
                            fit = min(vp.width() / eff_w, vp.height() / eff_h)
                            self.scale = min(1.0, float(fit))
                            try:
                                self.view._zoom = float(self.scale)
                            except Exception:
                                pass
                            self._fitted_once = True
                except Exception:
                    pass

                try:
                    scale_px = float(self.scale) * (float(PAGE_DPI) / float(self._last_render_dpi_used or PAGE_DPI))
                except Exception:
                    scale_px = 1.0
                if abs(scale_px - 1.0) > 1e-3:
                    w = max(1, int(pil.width * scale_px))
                    h = max(1, int(pil.height * scale_px))
                    pil = pil.resize((w, h), Image.BILINEAR if is_low else Image.LANCZOS)

                qimg = pil_to_qimage(pil)
                pm = QtGui.QPixmap.fromImage(qimg)
                self.view.setPixmap(pm)
                self.view.resize(pm.size())
        except Exception:
            pass


    def _request_diff_render(self, low_quality: bool = False):
        if not (self.mode == 'diff' and self.pdf1 and self.pdf2):
            self.update_view()
            return
        # антизависание - не плодим рендеры пачками
        if getattr(self, "_diff_busy", False):
            want = "low" if low_quality else "hi"
            prev = getattr(self, "_diff_pending", None)
            if prev != "hi":
                self._diff_pending = want
            return
        self._diff_busy = True

        try:
            # Use adaptive max DPI based on page sizes
            adaptive_dpi1 = self._get_adaptive_max_dpi(1, self.page1)
            adaptive_dpi2 = self._get_adaptive_max_dpi(2, self.page2)
            adaptive_max = min(adaptive_dpi1, adaptive_dpi2)  # Use smaller to prevent huge images
            
            # Calculate effective DPI based on scale, but cap at adaptive max
            base_dpi = int(PAGE_DPI * (self.scale if self.scale > 1.0 else 1.0))
            eff_dpi = max(100, min(adaptive_max, base_dpi))
        except Exception:
            eff_dpi = PAGE_DPI

        s = 0.5 if low_quality else 1.0
        use_dpi = int(max(50, eff_dpi * s))

        im1 = self._get_page_image(1, self.page1, use_dpi, self.rotation, low_quality=low_quality)
        im2 = self._get_page_image(2, self.page2, use_dpi, self.rotation, low_quality=low_quality)

        key = (self.page1, self.page2)
        pt = self.page_offsets.get(key, QtCore.QPoint(0, 0))
        # Clamp at render-time against current images so the offset never exceeds canvas
        try:
            # compute bounds based on current DPI images
            w1, h1 = im1.width, im1.height
            w2, h2 = im2.width, im2.height
            canvas_w, canvas_h = max(w1, w2), max(h1, h2)
            slack_x = int(2 * canvas_w)
            slack_y = int(2 * canvas_h)
            if w1 <= canvas_w:
                dx_min, dx_max = (-(canvas_w - w1) - slack_x), (0 + slack_x)
            else:
                dx_min, dx_max = (0 - slack_x), ((w1 - canvas_w) + slack_x)
            if h1 <= canvas_h:
                dy_min, dy_max = (-(canvas_h - h1) - slack_y), (0 + slack_y)
            else:
                dy_min, dy_max = (0 - slack_y), ((h1 - canvas_h) + slack_y)
            cx = max(dx_min, min(dx_max, int(pt.x())))
            cy = max(dy_min, min(dy_max, int(pt.y())))
        except Exception:
            cx, cy = int(pt.x()), int(pt.y())
        dx, dy = int(cx * s), int(cy * s)

        self._render_seq = int(getattr(self, "_render_seq", 0)) + 1
        seq = self._render_seq

        token = self._bg_token()

        def worker():
            try:
                if self._bg_should_abort(token):
                    return
                # быстрые бинарные маски (кешируются)
                m1 = self._get_binary_mask(1, self.page1, use_dpi, self.rotation)
                m2 = self._get_binary_mask(2, self.page2, use_dpi, self.rotation)

                # фиксированный холст - по максимальному из двух изображений, без расширения при смещении
                max_w = max(im1.width, im2.width)
                max_h = max(im1.height, im2.height)

                # смещения с учётом направления
                x1, y1 = max(0, -dx), max(0, -dy)
                x2, y2 = max(0,  dx), max(0,  dy)

                # подготовим канвасы для обоих изображений
                arr1 = np.full((max_h, max_w, 3), 255, dtype=np.uint8)
                arr2 = np.full((max_h, max_w, 3), 255, dtype=np.uint8)

                def paste_rgb(dst, src_img, tx, ty):
                    H, W = dst.shape[:2]
                    w, h = src_img.width, src_img.height
                    tx0, ty0 = int(tx), int(ty)
                    if tx0 >= W or ty0 >= H:
                        return
                    sx0 = 0; sy0 = 0
                    if tx0 < 0: sx0 = -tx0; tx0 = 0
                    if ty0 < 0: sy0 = -ty0; ty0 = 0
                    tw = min(w - sx0, W - tx0)
                    th = min(h - sy0, H - ty0)
                    if tw <= 0 or th <= 0:
                        return
                    src_arr = np.asarray(src_img, dtype=np.uint8)
                    dst[ty0:ty0+th, tx0:tx0+tw] = src_arr[sy0:sy0+th, sx0:sx0+tw, :3]

                paste_rgb(arr1, im1, x1, y1)
                paste_rgb(arr2, im2, x2, y2)

                # маски на фиксированный холст
                M1 = np.zeros((max_h, max_w), dtype=np.uint8)
                M2 = np.zeros((max_h, max_w), dtype=np.uint8)

                def paste_mask(dst, src, tx, ty):
                    H, W = dst.shape
                    h, w = src.shape
                    tx0, ty0 = int(tx), int(ty)
                    if tx0 >= W or ty0 >= H:
                        return
                    sx0 = 0; sy0 = 0
                    if tx0 < 0: sx0 = -tx0; tx0 = 0
                    if ty0 < 0: sy0 = -ty0; ty0 = 0
                    tw = min(w - sx0, W - tx0)
                    th = min(h - sy0, H - ty0)
                    if tw <= 0 or th <= 0:
                        return
                    dst[ty0:ty0+th, tx0:tx0+tw] = src[sy0:sy0+th, sx0:sx0+tw]

                paste_mask(M1, m1, x1, y1)
                paste_mask(M2, m2, x2, y2)

                only1 = (M1 > 0) & (M2 == 0)
                only2 = (M2 > 0) & (M1 == 0)

                arr = arr1.copy()
                arr[only1] = [255, 0, 0]
                arr[only2] = [0, 0, 255]

                if self._bg_should_abort(token):
                    return

                pil = Image.fromarray(arr)
                try:
                    self._ui_queue.put(("diff_ready", seq, pil, use_dpi, low_quality))
                    self._ui_queue.put(("diff_done", seq))
                except Exception:
                    pass
            except Exception:
                pass


        self._start_background_task(worker)


    def _clamp_offset_for_pair(self, key: tuple[int, int], pt: QtCore.QPoint) -> QtCore.QPoint:
        """
        Ограничивает смещение так, чтобы хотя бы часть каждого изображения оставалась видимой
        в пределах canvas размером max(w1, w2) x max(h1, h2).
        Offset определяет, насколько im1 смещён относительно im2.
        """
        try:
            eff_dpi = max(150, min(600, int(PAGE_DPI * (self.scale if self.scale > 1.0 else 1.0))))
        except Exception:
            eff_dpi = PAGE_DPI
        try:
            p1 = int(key[0])
            p2 = int(key[1]) if len(key) > 1 else -1
        except Exception:
            p1, p2 = self.page1, (self.page2 if self.pdf2 else -1)

        try:
            im1 = self._get_page_image(1, p1, eff_dpi, self.rotation)
            if self.pdf2 and p2 >= 0:
                im2 = self._get_page_image(2, p2, eff_dpi, self.rotation)
            else:
                im2 = im1
            
            w1 = getattr(im1, "width", 0)
            h1 = getattr(im1, "height", 0)
            w2 = getattr(im2, "width", 0)
            h2 = getattr(im2, "height", 0)
            
            canvas_w = max(w1, w2)
            canvas_h = max(h1, h2)
            
            # Constrain movement within the frame of the largest sheet (canvas)
            # im1 is pasted at (-dx, -dy) on a canvas of size (canvas_w, canvas_h)
            # We clamp so that im1 stays within the canvas bounds window:
            #   if im1 smaller than canvas -> im1 fully inside [0 .. canvas - size]
            #   if im1 larger than canvas  -> allow sliding window over im1: paste in [-(w1-canvas_w) .. 0]
            dx = int(pt.x()); dy = int(pt.y())

            # Dynamic slack: allow moving roughly a whole canvas dimension
            slack_x = int(2 * canvas_w)
            slack_y = int(2 * canvas_h)
            # X axis (soft limits with slack)
            if w1 <= canvas_w:
                dx_min, dx_max = (-(canvas_w - w1) - slack_x), (0 + slack_x)
            else:
                dx_min, dx_max = (0 - slack_x), ((w1 - canvas_w) + slack_x)
            # Y axis
            if h1 <= canvas_h:
                dy_min, dy_max = (-(canvas_h - h1) - slack_y), (0 + slack_y)
            else:
                dy_min, dy_max = (0 - slack_y), ((h1 - canvas_h) + slack_y)

            dx = max(dx_min, min(dx_max, dx))
            dy = max(dy_min, min(dy_max, dy))

            return QtCore.QPoint(dx, dy)
        except Exception:
            return QtCore.QPoint(int(pt.x()), int(pt.y()))


    def _apply_drag_coalesced(self):
        self._drag_scheduled = False
        acc = getattr(self, "_drag_accum", QtCore.QPoint(0, 0))
        if acc.x() or acc.y():
            key = (self.page1, self.page2 if self.pdf2 else -1)
            cur = self.page_offsets.get(key, QtCore.QPoint(0, 0))
            new_pt = QtCore.QPoint(int(cur.x()) + int(acc.x()), int(cur.y()) + int(acc.y()))
            if self.mode == 'diff' and self.pdf2:
                new_pt = self._clamp_offset_for_pair(key, new_pt)
            self.page_offsets[key] = new_pt

            self._drag_accum = QtCore.QPoint(0, 0)
            self._request_diff_render(low_quality=True)

    def _prefetch_pages_around(self, radius: int = 2):
        token = self._bg_token()

        def _prefetch_one(which: int, page_index: int, token_local: int):
            try:
                if self._bg_should_abort(token_local):
                    return
                adaptive_dpi = self._get_adaptive_max_dpi(which, page_index)
                self._get_page_image(which, page_index, adaptive_dpi, self.rotation)
                try:
                    self._ui_queue.put(("page_cached", which, page_index))
                except Exception:
                    pass
            except Exception:
                pass
        for which, doc, cur in ((1, self.pdf1, self.page1), (2, self.pdf2, self.page2)):
            if not doc:
                continue
            cnt = int(getattr(doc, "page_count", 0))
            if cnt <= 0:
                continue
            indices = set()
            for d in range(-radius, radius + 1):
                j = cur + d
                if 0 <= j < cnt:
                    indices.add(j)
            for j in sorted(indices):
                adaptive_dpi = self._get_adaptive_max_dpi(which, j)
                key = self._cache_key(which, j, self.rotation, adaptive_dpi)
                if key in self._page_cache:
                    continue
                self._start_background_task(lambda w=which, p=j, tok=token: _prefetch_one(w, p, tok))



    # --- Background thumbnail renderer ---
    def _thumb_worker(self, which: int, page_index: int, TW: int, TH: int, PAD_W: int, PAD_H: int):
        cancelled = False
        token = self._bg_token()
        try:
            if self._bg_should_abort(token):
                cancelled = True
                return

            # Check for cancellation before starting
            if self._is_caching_cancelled():
                cancelled = True
                return
            
            # Захватываем документ и проверяем его внутри lock
            with getattr(self, "_fitz_lock", threading.RLock()):
                doc = self.pdf1 if which == 1 else self.pdf2
                if not doc:
                    return
                cnt = int(getattr(doc, 'page_count', 0))
                if not (0 <= page_index < cnt):
                    return
                
                # Check for cancellation before heavy work
                if self._is_caching_cancelled():
                    cancelled = True
                    return

                if self._bg_should_abort(token):
                    cancelled = True
                    return
                    
                page = doc.load_page(int(page_index))
                pil = fitz_page_to_pil(page, dpi=THUMB_DPI)
            
            # Check for cancellation before updating UI
            if self._is_caching_cancelled():
                cancelled = True
                return
            
            try:
                self._ui_queue.put(("thumb_ready", which, page_index, pil, TW, TH, PAD_W, PAD_H))
            except Exception:
                pass
        except Exception:
            pass
        finally:
            # If cancelled, still need to decrement counter to prevent infinite dialog
            if cancelled:
                try:
                    self._ui_queue.put(("thumb_cancelled", which, page_index))
                except Exception:
                    pass


    def _update_ui_state(self):
        # активный документ/страница зависят от режима
        if self.mode == 'pdf2' and self.pdf2:
            total = self.pdf2.page_count
            cur_page = self.page2
            have = True
        else:
            total = self.pdf1.page_count if self.pdf1 else 0
            cur_page = (self.page1 if self.pdf1 else -1)
            have = self.pdf1 is not None

        if hasattr(self, "lbl_total"):
            self.lbl_total.setText(f'/ {total}')
        if hasattr(self, "ed_page"):
            self.ed_page.setText(str((cur_page + 1) if have else 0))
        if hasattr(self, "btn_prev"):
            self.btn_prev.setEnabled(have and cur_page > 0)
        if hasattr(self, "btn_next"):
            self.btn_next.setEnabled(have and (cur_page + 1) < total)
        if hasattr(self, "btn_export"):
            self.btn_export.setEnabled(have)
        if hasattr(self, "btn_nav") and hasattr(self, "panel"):
            self.btn_nav.setChecked(self.panel.isVisible())
    # Actions
    def open_pdf(self, which: int):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Выберите PDF', '', 'PDF Files (*.pdf)')
        if not path:
            return
        try:
            doc, data = self._open_pdf_document(path)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, 'Ошибка', f'Не удалось открыть PDF:\n{e}')
            return
        # сбрасываем маппинг, если подменили один из файлов
        try:
            if (which == 1 and self.pdf1_path and os.path.abspath(path) != os.path.abspath(self.pdf1_path)) \
               or (which == 2 and self.pdf2_path and os.path.abspath(path) != os.path.abspath(self.pdf2_path)):
                self.mappings.clear()
                self.page_offsets.clear()
        except Exception:
            pass

        if which == 1:
            if self.pdf1:
                self.pdf1.close()
            self.pdf1 = doc
            self._pdf1_bytes = data
            self.pdf1_path = path
            self.page1 = 0
            if self.pdf2:
                self.page2 = min(self.page1, self.pdf2.page_count - 1)
        else:
            if self.pdf2:
                self.pdf2.close()
            self.pdf2 = doc
            self._pdf2_bytes = data
            self.pdf2_path = path
            self.page2 = 0
        self.rotation = 0
        self._fitted_once = False
        self.scale = 1.0
        self.offset = QtCore.QPoint(0, 0)
        self._clear_page_cache()
        self._build_thumbs()
        self._update_ui_state()
        # Pre-render current pages at max DPI for smoother subsequent zoom (background)
        # Defer to avoid crashes during initialization
        def _defer_precache():
            try:
                to_precache = 1 + (1 if self.pdf2 else 0)
                self._begin_caching(to_precache)
                
                def _pc():
                    try:
                        if self.pdf1:
                            adaptive_dpi1 = self._get_adaptive_max_dpi(1, self.page1)
                            self._get_page_image(1, self.page1, adaptive_dpi1, self.rotation)
                        if self.pdf2:
                            adaptive_dpi2 = self._get_adaptive_max_dpi(2, self.page2)
                            self._get_page_image(2, self.page2, adaptive_dpi2, self.rotation)
                    except Exception:
                        pass
                    finally:
                        try:
                            self._ui_queue.put(("page_cached", 0, 0))
                        except Exception:
                            pass
                        try:
                            self._end_caching(to_precache)
                        except Exception:
                            pass
                self._start_background_task(_pc)
                self._prefetch_pages_around()
            except Exception:
                pass
        
        try:
            QtCore.QTimer.singleShot(100, _defer_precache)
        except Exception:
            pass

        self.update_view()
    def open_pdf_path(self, which: int, path: str):
        try:
            doc, data = self._open_pdf_document(path)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Ошибка", f"Не удалось открыть PDF:\n{e}")
            return
        # сбрасываем маппинг, если подменили один из файлов
        try:
            if (which == 1 and self.pdf1_path and os.path.abspath(path) != os.path.abspath(self.pdf1_path)) \
               or (which == 2 and self.pdf2_path and os.path.abspath(path) != os.path.abspath(self.pdf2_path)):
                self.mappings.clear()
                self.page_offsets.clear()
        except Exception:
            pass

        if which == 1:
            if self.pdf1:
                self.pdf1.close()
            self.pdf1 = doc
            self._pdf1_bytes = data
            self.pdf1_path = path
            self.page1 = 0
            if self.pdf2:
                self.page2 = min(self.page1, self.pdf2.page_count - 1)
        else:
            if self.pdf2:
                self.pdf2.close()
            self.pdf2 = doc
            self._pdf2_bytes = data
            self.pdf2_path = path
            self.page2 = 0
        self.rotation = 0
        self._fitted_once = False
        self.scale = 1.0
        self.offset = QtCore.QPoint(0, 0)
        self._clear_page_cache()
        self._build_thumbs()
        self._update_ui_state()
        # Pre-render current pages at max DPI for smoother subsequent zoom (background)
        # Defer until after window is shown to avoid crashes during initialization
        def _defer_precache():
            try:
                to_precache = 1 + (1 if self.pdf2 else 0)
                self._begin_caching(to_precache)
                
                def _pc():
                    try:
                        if self.pdf1:
                            adaptive_dpi1 = self._get_adaptive_max_dpi(1, self.page1)
                            self._get_page_image(1, self.page1, adaptive_dpi1, self.rotation)
                        if self.pdf2:
                            adaptive_dpi2 = self._get_adaptive_max_dpi(2, self.page2)
                            self._get_page_image(2, self.page2, adaptive_dpi2, self.rotation)
                    except Exception:
                        pass
                    finally:
                        try:
                            self._ui_queue.put(("page_cached", 0, 0))
                        except Exception:
                            pass
                        try:
                            self._end_caching(to_precache)
                        except Exception:
                            pass
                self._start_background_task(_pc)
                self._prefetch_pages_around()
            except Exception:
                pass
            
        try:
            QtCore.QTimer.singleShot(100, _defer_precache)
        except Exception:
            pass

        self.update_view()
        
        # Schedule background precaching after a short delay to let UI become responsive
        def _deferred_precache():
            try:
                to_precache = 1 + (1 if self.pdf2 else 0)
                self._begin_caching(to_precache)
            except Exception:
                to_precache = 0
            def _pc2():
                cancelled = False
                try:
                    # Check for cancellation before starting
                    if self._is_caching_cancelled():
                        cancelled = True
                        return
                    
                    if self.pdf1:
                        adaptive_dpi1 = self._get_adaptive_max_dpi(1, self.page1)
                        self._get_page_image(1, self.page1, adaptive_dpi1, self.rotation)
                        # Update progress after first page
                        self._completed_caching_tasks = getattr(self, "_completed_caching_tasks", 0) + 1
                        self._ui_queue.put(("update_cache_progress", 0, 0))
                        
                        # Check for cancellation between files
                        if self._is_caching_cancelled():
                            cancelled = True
                            return
                    
                    if self.pdf2:
                        adaptive_dpi2 = self._get_adaptive_max_dpi(2, self.page2)
                        self._get_page_image(2, self.page2, adaptive_dpi2, self.rotation)
                        # Update progress after second page
                        self._completed_caching_tasks = getattr(self, "_completed_caching_tasks", 0) + 1
                        self._ui_queue.put(("update_cache_progress", 0, 0))
                        
                        # Final check
                        if self._is_caching_cancelled():
                            cancelled = True
                            return
                except Exception:
                    pass
                finally:
                    try:
                        if not cancelled:
                            self._ui_queue.put(("page_cached", 0, 0))
                    except Exception:
                        pass
                    # Always end caching, even if cancelled
                    try:
                        self._end_caching(to_precache)
                    except Exception:
                        pass
            self._start_background_task(_pc2)
            self._prefetch_pages_around()
        
        # Defer precaching by 100ms to allow window to show first
        QtCore.QTimer.singleShot(100, _deferred_precache)


    def _build_thumbs(self):
        # Блокируем изменение размеров сплиттера во время построения миниатюр
        self._splitter_locked = True
        
        # Очистка layout
        while self.thumb_layout.count():
            it = self.thumb_layout.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        
        # Очистка списков миниатюр
        self.thumbs1 = []
        self.thumbs2 = []

        if not self.pdf1 and not self.pdf2:
            self._splitter_locked = False
            return

        c1 = self.pdf1.page_count if self.pdf1 else 0
        c2 = self.pdf2.page_count if self.pdf2 else 0
        rows = max(c1, c2)

        show_left  = (self.mode != 'pdf2') and (self.pdf1 is not None)
        show_right = (self.mode != 'pdf1') and (self.pdf2 is not None)

        # если показываем один столбец - он всегда в левой колонке
        col_left  = 1 if show_left else None
        col_right = (2 if show_left else 1) if show_right else None

        try:
            self.thumb_layout.setColumnStretch(0, 0)
            if col_left:
                self.thumb_layout.setColumnStretch(col_left, 1)
            if col_right:
                self.thumb_layout.setColumnStretch(col_right, 1)
        except Exception:
            pass

        # Извлекаем базовые названия и версии файлов
        def _extract_base_name_and_version(path: str) -> tuple[str, str]:
            """Возвращает (базовое_название, версия). Если версии нет - (полное_название, '')."""
            if not path:
                return ('', '')
            base = os.path.basename(path)
            name, ext = os.path.splitext(base)
            # Удаляем "(copy ...)" и временную метку
            name = re.sub(r"\s*\(copy[^)]*\)$", "", name, flags=re.IGNORECASE)
            name = re.sub(r"\s*-\s*\d{8}_\d{6}\s*$", "", name, flags=re.IGNORECASE)
            name = name.strip()

            # Пытаемся найти версию в названии (паттерн "- v3" или "-v3" или " v3")
            m = re.search(r"^(.*?)(?:\s*-\s*v|-v|\s+v)(\d+)\b", name, flags=re.IGNORECASE)
            if m:
                base_name = f"{m.group(1).strip()}{ext}"
                version = f"-v{m.group(2)}"
                return base_name, version
            return f"{name}{ext}", ''
        
        base1, ver1 = _extract_base_name_and_version(self.pdf1_path) if self.pdf1_path else ('', '')
        base2, ver2 = _extract_base_name_and_version(self.pdf2_path) if self.pdf2_path else ('', '')

        # Проверяем, одинаковы ли базовые названия
        same_base = base1 and base2 and base1 == base2

        # Сравниваем полные названия для отображения, если файлы разные
        name1 = self._display_name(self.pdf1_path) if self.pdf1_path else ''
        name2 = self._display_name(self.pdf2_path) if self.pdf2_path else ''
        header_style = "font-weight:600; padding:2px;"
        header_style_center = "font-weight:600; padding:2px; color: #555; font-size: 9pt;"

        if same_base and col_left and col_right:
            # Одинаковое название - показываем по центру в одну строку
            h_title = QtWidgets.QLabel(base1)
            h_title.setAlignment(QtCore.Qt.AlignCenter)
            h_title.setStyleSheet(header_style)
            self.thumb_layout.addWidget(h_title, 0, 1, 1, 2)  # занимаем 2 колонки

            # Версии показываем каждый над своим столбцом
            if ver1:
                h_ver1 = QtWidgets.QLabel(ver1)
                h_ver1.setAlignment(QtCore.Qt.AlignCenter)
                h_ver1.setStyleSheet(header_style_center)
                self.thumb_layout.addWidget(h_ver1, 1, 1, 1, 1)
            if ver2:
                h_ver2 = QtWidgets.QLabel(ver2)
                h_ver2.setAlignment(QtCore.Qt.AlignCenter)
                h_ver2.setStyleSheet(header_style_center)
                self.thumb_layout.addWidget(h_ver2, 1, 2, 1, 1)
        else:
            # Разные названия - показываем по бокам
            if col_left:
                h1 = QtWidgets.QLabel(name1)
                h1.setAlignment(QtCore.Qt.AlignCenter)
                h1.setStyleSheet(header_style)
                h1.setWordWrap(True)
                self.thumb_layout.addWidget(h1, 0, col_left)
            if col_right:
                h2 = QtWidgets.QLabel(name2)
                h2.setAlignment(QtCore.Qt.AlignCenter)
                h2.setStyleSheet(header_style)
                h2.setWordWrap(True)
                self.thumb_layout.addWidget(h2, 0, col_right)

        # одинаковые рамки + центрирование
        TH = 120                # высота миниатюры
        TW = 160                # фиксированная ширина рамки
        
        # Если названия одинаковые, миниатюры начинаются со строки 2 (чтобы поместились версии)
        start_row = 2 if same_base and col_left and col_right else 1
        
        # Ограничим заголовки шириной и высотой
        if not (same_base and col_left and col_right):
            # Только для разных названий
            try:
                if col_left and h1:
                    h1.setMaximumWidth(TW)
                    _fm = h1.fontMetrics()
                    h1.setFixedHeight(_fm.lineSpacing() * 2 + 6)  # ровно 2 строки
                    h1.setToolTip(name1 or "")
            except NameError:
                pass
            try:
                if col_right and h2:
                    h2.setMaximumWidth(TW)
                    _fm = h2.fontMetrics()
                    h2.setFixedHeight(_fm.lineSpacing() * 2 + 6)  # ровно 2 строки
                    h2.setToolTip(name2 or "")
            except NameError:
                pass

        PAD_W, PAD_H = 10, 10   # внутренние отступы при масштабировании
        
        self.thumbs1 = [None] * c1
        self.thumbs2 = [None] * c2
        
        for i in range(rows):
            # узкая колонка номеров страниц слева - максимально узкая
            lbl_idx = QtWidgets.QLabel(str(i + 1))
            lbl_idx.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            lbl_idx.setIndent(0)
            lbl_idx.setFixedWidth(18)
            self.thumb_layout.addWidget(lbl_idx, start_row + i, 0)

            # Левая колонка (PDF1)
            if col_left:
                if i < c1:
                    th1 = QtWidgets.QLabel()
                    th1.setFixedSize(TW, TH)
                    th1.setAlignment(QtCore.Qt.AlignCenter)
                    # placeholder thumbnail
                    try:
                        pm = QtGui.QPixmap(TW - PAD_W, TH - PAD_H)
                        pm.fill(QtGui.QColor('#FFFFFF'))
                    except Exception:
                        pm = QtGui.QPixmap(TW - PAD_W, TH - PAD_H); pm.fill(QtGui.QColor('#FFFFFF'))
                    th1.setPixmap(pm)
                    th1.setStyleSheet("border: 1px solid #555;")
                    th1.setCursor(QtCore.Qt.PointingHandCursor)
                    th1.mousePressEvent = lambda _e, idx=i: self._set_page1(idx)
                    self.thumbs1[i] = th1
                    self.thumb_layout.addWidget(th1, start_row + i, col_left)
                    # schedule background render + show caching toast
                    try:
                        self._begin_caching(1)
                    except Exception:
                        pass
                    self._start_background_task(lambda w=1, p=i: self._thumb_worker(w, p, TW, TH, PAD_W, PAD_H))
                else:
                    spacer1 = QtWidgets.QLabel(); spacer1.setFixedSize(TW, TH)
                    self.thumb_layout.addWidget(spacer1, start_row + i, col_left)

            # Правая колонка (PDF2)
            if col_right:
                if i < c2:
                    th2 = QtWidgets.QLabel()
                    th2.setFixedSize(TW, TH)
                    th2.setAlignment(QtCore.Qt.AlignCenter)
                    try:
                        pm2 = QtGui.QPixmap(TW - PAD_W, TH - PAD_H)
                        pm2.fill(QtGui.QColor('#FFFFFF'))
                    except Exception:
                        pm2 = QtGui.QPixmap(TW - PAD_W, TH - PAD_H); pm2.fill(QtGui.QColor('#FFFFFF'))
                    th2.setPixmap(pm2)
                    th2.setStyleSheet("border: 1px solid #555;")
                    th2.setCursor(QtCore.Qt.PointingHandCursor)
                    th2.mousePressEvent = lambda _e, idx=i: self._set_page2(idx)
                    if i < len(self.thumbs2):
                        self.thumbs2[i] = th2
                    self.thumb_layout.addWidget(th2, start_row + i, col_right)
                    try:
                        self._begin_caching(1)
                    except Exception:
                        pass
                    self._start_background_task(lambda w=2, p=i: self._thumb_worker(w, p, TW, TH, PAD_W, PAD_H))
                else:
                    spacer2 = QtWidgets.QLabel(); spacer2.setFixedSize(TW, TH)
                    self.thumb_layout.addWidget(spacer2, start_row + i, col_right)

        # Добавляем вертикальную распорку в конец, чтобы миниатюры прижимались к верху
        # Это важно когда у PDF мало страниц (1-2), чтобы они не центрировались вертикально
        final_row = start_row + rows
        spacer_bottom = QtWidgets.QWidget()
        spacer_bottom.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        self.thumb_layout.addWidget(spacer_bottom, final_row, 0, 1, 3)  # растягиваем на все 3 колонки
        
        # Убираем вертикальное растяжение с строк с миниатюрами
        for row_idx in range(final_row):
            self.thumb_layout.setRowStretch(row_idx, 0)
        # Последняя строка (распорка) должна растягиваться
        self.thumb_layout.setRowStretch(final_row, 1)

        self._refresh_thumb_highlight()
        # Убираем повторный вызов _apply_initial_layout - он должен быть только один раз при запуске
        # QtCore.QTimer.singleShot(0, self._apply_initial_layout)
        
        # Разблокируем изменение размеров сплиттера после построения миниатюр
        self._splitter_locked = False




    def _refresh_thumb_highlight(self):
        active_left  = (self.mode != 'pdf2')
        active_right = (self.mode != 'pdf1')

        # Подсветка выбранных миниатюр: красная рамка для PDF1, синяя для PDF2
        if hasattr(self, 'thumbs1'):
            for i, lbl in enumerate(self.thumbs1):
                if not lbl:
                    continue
                is_selected = (active_left and i == self.page1)
                if is_selected:
                    lbl.setStyleSheet("border: 2px solid #e74c3c; border-radius: 8px;")  # Красная рамка для выделенной страницы PDF1
                else:
                    lbl.setStyleSheet("border: 1px solid #555; border-radius: 8px;")

        if hasattr(self, 'thumbs2'):
            for i, lbl in enumerate(self.thumbs2):
                if not lbl:
                    continue
                is_selected = (active_right and i == self.page2)
                if is_selected:
                    lbl.setStyleSheet("border: 2px solid #3498db; border-radius: 8px;")  # Синяя рамка для выделенной страницы PDF2
                else:
                    lbl.setStyleSheet("border: 1px solid #555; border-radius: 8px;")


    def _set_page1(self, idx: int):
        if not self.pdf1:
            return
        self.page1 = max(0, min(idx, self.pdf1.page_count - 1))
        self.rotation = 0
        self.offset = QtCore.QPoint(0, 0)
        self._update_ui_state()
        self.update_view()
        # Precache current pages at max DPI for smooth zoom after page change
        self._precache_current_pages_maxdpi()
        self._prefetch_pages_around()
        self._refresh_thumb_highlight()

    def _set_page2(self, idx: int):
        if not self.pdf2:
            return
        self.page2 = max(0, min(idx, self.pdf2.page_count - 1))
        self.rotation = 0
        self.offset = QtCore.QPoint(0, 0)
        self._update_ui_state()
        self.update_view()
        # Precache current pages at max DPI for smooth zoom after page change
        self._precache_current_pages_maxdpi()
        self._prefetch_pages_around()
        self._refresh_thumb_highlight()

    def _thumb_click(self, idx: int):
        if not self.pdf1:
            return
        self.page1 = idx
        if self.pdf2:
            self.page2 = min(idx, self.pdf2.page_count - 1)
        self.rotation = 0
        self.offset = QtCore.QPoint(0, 0)
        self._update_ui_state()
        # Если в маппинге есть пара для этой страницы PDF1 — использовать её
        if self.pdf2:
            for (p1, p2) in self.mappings:
                if p1 == self.page1:
                    self.page2 = min(p2, self.pdf2.page_count - 1)
                    break

        self.update_view()
        # Precache current pages at max DPI for smooth zoom after page change
        self._precache_current_pages_maxdpi()
        self._refresh_thumb_highlight()


    def go_to_page(self):
        try:
            val = int(self.ed_page.text()) - 1
        except Exception:
            return

        if self.mode == 'pdf2' and self.pdf2:
            val = max(0, min(val, self.pdf2.page_count - 1))
            self._set_page2(val)
        else:
            if not self.pdf1:
                return
            val = max(0, min(val, self.pdf1.page_count - 1))
            self._set_page1(val)


    def prev_page(self):
        if self.mode == 'diff':
            if self.pdf1:
                self._set_page1(max(0, self.page1 - 1))
            if self.pdf2:
                self._set_page2(max(0, self.page2 - 1))
            return
        if self.mode == 'pdf2':
            if not self.pdf2 or self.page2 <= 0:
                return
            self._set_page2(self.page2 - 1)
        else:
            if not self.pdf1 or self.page1 <= 0:
                return
            self._set_page1(self.page1 - 1)



    def next_page(self):
        if self.mode == 'diff':
            # листаем синхронно
            if self.pdf1:
                self._set_page1(min(self.page1 + 1, self.pdf1.page_count - 1))
            if self.pdf2:
                self._set_page2(min(self.page2 + 1, self.pdf2.page_count - 1))
            return
        if self.mode == 'pdf2':
            if not self.pdf2:
                return
            if self.page2 + 1 < self.pdf2.page_count:
                self._set_page2(self.page2 + 1)
        else:
            if not self.pdf1:
                return
            if self.page1 + 1 < self.pdf1.page_count:
                self._set_page1(self.page1 + 1)



    def on_zoom_changed(self, zoom: float):
        # зум к курсору: вычисляем «якорь» в координатах содержимого и сохраняем его
        if not hasattr(self, "view_scroll"):
            self.scale = zoom
            self.update_view()
            return
            
        prev = self.scale if self.scale > 0 else 1.0
        vp = self.view_scroll.viewport()
        hbar = self.view_scroll.horizontalScrollBar()
        vbar = self.view_scroll.verticalScrollBar()

        # Определяем точку зума (курсор мыши или центр viewport)
        gp = getattr(self.view, "_last_global", None)
        if gp is not None:
            vp_pos = vp.mapFromGlobal(gp)
            # Ограничиваем позицию границами viewport
            vp_pos.setX(max(0, min(vp_pos.x(), vp.width() - 1)))
            vp_pos.setY(max(0, min(vp_pos.y(), vp.height() - 1)))
        else:
            # Если нет сохранённой позиции курсора - зумим к центру
            vp_pos = QtCore.QPoint(vp.width() // 2, vp.height() // 2)

        # Запоминаем точку в координатах контента ДО масштабирования
        cx = hbar.value() + vp_pos.x()
        cy = vbar.value() + vp_pos.y()

        # Применяем новый масштаб и обновляем вид
        self.scale = zoom
        
        # Блокируем автоматическое выравнивание при update_view
        self.view_scroll.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        
        self.update_view()

        # Используем отложенное обновление скроллбаров после полной отрисовки
        def adjust_scrollbars():
            try:
                # Корректируем скроллбары так, чтобы точка зума осталась под курсором
                # После масштабирования координата контента изменилась пропорционально
                r = float(self.scale) / float(prev) if prev > 0 else 1.0
                new_cx = int(cx * r)
                new_cy = int(cy * r)
                
                # Новые значения скроллбаров: новая координата контента минус позиция в viewport
                new_h = new_cx - vp_pos.x()
                new_v = new_cy - vp_pos.y()
                
                # Применяем с учётом границ
                hbar.setValue(max(hbar.minimum(), min(new_h, hbar.maximum())))
                vbar.setValue(max(vbar.minimum(), min(new_v, vbar.maximum())))
                
                # Восстанавливаем центрирование для маленьких изображений
                if hbar.maximum() == 0 and vbar.maximum() == 0:
                    if getattr(self, "mode", "diff") == "diff":
                        self.view_scroll.setAlignment(QtCore.Qt.AlignCenter)
                    else:
                        self.view_scroll.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
                else:
                    self.view_scroll.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
            except Exception:
                pass
        
        # Откладываем настройку скроллбаров до следующего кадра
        QtCore.QTimer.singleShot(0, adjust_scrollbars)


    def on_mode_change(self, idx: int):
        text = self.cmb_mode.currentText()
        self.mode = 'diff' if text == 'Сравнение' else ('pdf1' if text == 'Версия 1' else 'pdf2')
        self._fitted_once = False
        self._diff_busy = False
        self._diff_pending = None

        # Изменяем ширину боковой панели в зависимости от режима
        if self.mode == 'diff':
            base_panel_w = 340
        else:
            base_panel_w = 200
        self.panel.setMinimumWidth(base_panel_w)
        self.panel.setMaximumWidth(base_panel_w)

        self._build_thumbs()  # обновляем левую колонку под режим
        def _apply_panel_width():
            try:
                desired_panel_w = base_panel_w
                if self.mode == 'diff' and hasattr(self, "thumb_root"):
                    try:
                        self.thumb_root.adjustSize()
                        self.panel.adjustSize()
                    except Exception:
                        pass
                    hint_w = int(self.thumb_root.sizeHint().width())
                    if hint_w > 0:
                        desired_panel_w = max(base_panel_w, hint_w + 16)
                self.panel.setMinimumWidth(desired_panel_w)
                self.panel.setMaximumWidth(desired_panel_w)
                self._sync_splitter_width(desired_panel_w)
            except Exception:
                pass
        _apply_panel_width()
        QtCore.QTimer.singleShot(0, _apply_panel_width)
        QtCore.QTimer.singleShot(80, _apply_panel_width)
        self.update_view()
        self._update_ui_state()

        # В режиме одиночного файла пересчитываем масштаб с задержкой, чтобы viewport обновился
        if self.mode != 'diff':
            def _force_left_align():
                try:
                    self.setLayoutDirection(QtCore.Qt.LeftToRight)
                    self.view_scroll.setLayoutDirection(QtCore.Qt.LeftToRight)
                    self.view_scroll.viewport().setLayoutDirection(QtCore.Qt.LeftToRight)
                    self.view.setLayoutDirection(QtCore.Qt.LeftToRight)
                    self.view_scroll.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
                    self.view.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
                    hbar = self.view_scroll.horizontalScrollBar()
                    vbar = self.view_scroll.verticalScrollBar()
                    hbar.setInvertedAppearance(False)
                    hbar.setInvertedControls(False)
                    vbar.setInvertedAppearance(False)
                    vbar.setInvertedControls(False)
                    hbar.setValue(hbar.minimum())
                    vbar.setValue(vbar.minimum())
                except Exception:
                    pass

            def _refit_scale():
                self._fitted_once = False
                self.update_view()
                # Принудительно ставим LTR и прижимаем к левому краю
                QtCore.QTimer.singleShot(0, _force_left_align)
                QtCore.QTimer.singleShot(100, _force_left_align)
                QtCore.QTimer.singleShot(200, _force_left_align)
            QtCore.QTimer.singleShot(50, _refit_scale)
        else:
            # В режиме сравнения центрируем
            QtCore.QTimer.singleShot(0, lambda: self.view_scroll.setAlignment(QtCore.Qt.AlignCenter))
            QtCore.QTimer.singleShot(0, lambda: self.view.setAlignment(QtCore.Qt.AlignCenter))

        # Убираем вызов _apply_initial_layout - он должен быть только при старте
        # QtCore.QTimer.singleShot(0, self._apply_initial_layout)



    def toggle_nav(self):
        # slide thumbnails with animation and mirror arrow
        if hasattr(self, "nav_toggle"):
            want_show = (self.panel.maximumWidth() == 0) or (not self.panel.isVisible())
            self._toggle_nav_animated(want_show)
            return
        vis = not self.panel.isVisible()
        self.panel.setVisible(vis)
        self.btn_nav.setChecked(vis)
        # синхронизируем иконку стрелки и в неанимированном пути
        self._set_nav_arrow(vis)

    # --- animated navigation panel and arrow mirroring ---
    def _nav_icon_pixmap(self, mirrored: bool = False, size: int = 16) -> QtGui.QPixmap:
        try:
            app = QtWidgets.QApplication.instance()
            path = resolve_icon_path("navigation", ICON_DIR, app=app)
            pm = QtGui.QPixmap(path)
            if pm.isNull():
                return pm
            pm = pm.scaled(size, size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            if mirrored:
                pm = pm.transformed(QtGui.QTransform().scale(-1, 1), QtCore.Qt.SmoothTransformation)
            # подкраска под тему
            try:
                pm = self._tint_pixmap(pm, QtGui.QColor(Qt.white) if not self._is_light_theme() else QtGui.QColor(0, 0, 0))
            except Exception:
                pass

            return pm
        except Exception:
            return QtGui.QPixmap()

    def _set_nav_arrow(self, mirrored: bool) -> None:
        if hasattr(self, "nav_toggle"):
            try:
                # Set theme icons on rotate buttons
                # (icons follow theme automatically via resolve_icon_path)
                pm = self._nav_icon_pixmap(mirrored=mirrored, size=ICON_PX)
                if not pm.isNull():
                    self.nav_toggle.setIcon(QtGui.QIcon(pm))
                    self.nav_toggle.setIconSize(QtCore.QSize(ICON_PX, ICON_PX))
            except Exception:
                pass


    def _refresh_all_icons(self) -> None:
        try:
            # единая точка - используем наши тонированные иконки сразу под текущую тему
            self._apply_toolbar_icons()
        except Exception:
            pass

    def _is_obj_alive(self, obj) -> bool:
        try:
            if obj is None:
                return False
            from shiboken6 import isValid
            return bool(isValid(obj))
        except Exception:
            return obj is not None

    def _is_light_theme(self) -> bool:
        # Check theme using is_dark_theme which respects the app property
        try:
            return not is_dark_theme(QtWidgets.QApplication.instance())
        except Exception:
            # Safe default: assume light
            return True


    def _tint_pixmap(self, pm: QtGui.QPixmap, color: QtGui.QColor) -> QtGui.QPixmap:
        if pm.isNull():
            return pm
        tinted = QtGui.QPixmap(pm.size())
        tinted.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(tinted)
        p.drawPixmap(0, 0, pm)
        p.setCompositionMode(QtGui.QPainter.CompositionMode_SourceIn)
        p.fillRect(tinted.rect(), color)
        p.end()
        return tinted

    def _icon_color(self) -> QtGui.QColor:
        # в светлой теме иконки тёмные, в тёмной светлые
        return QtGui.QColor(0, 0, 0) if self._is_light_theme() else QtGui.QColor(Qt.white)

    def _make_tinted_icon(self, name: str, size: int) -> QtGui.QIcon:
        """Load icon with fallbacks and tint for current theme."""
        app = QtWidgets.QApplication.instance()
        
        # Try resolve_icon_path first
        path = resolve_icon_path(name, ICON_DIR, app=app)
        
        # Fallback: try direct paths with different extensions and name variations
        if not path or not os.path.exists(path):
            candidates = [
                os.path.join(ICON_DIR, f"{name}.png"),
                os.path.join(ICON_DIR, f"{name}.svg"),
                os.path.join(ICON_DIR, name.replace("_", "-") + ".png"),
                os.path.join(ICON_DIR, name.replace("-", "_") + ".png"),
            ]
            for candidate in candidates:
                if os.path.exists(candidate):
                    path = candidate
                    break
        
        if not path or not os.path.exists(path):
            return QtGui.QIcon()
        
        pm = QtGui.QPixmap(path)
        if pm.isNull():
            return QtGui.QIcon()
        
        # Scale and tint
        pm = pm.scaled(size, size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        pm = self._tint_pixmap(pm, QtGui.QColor(Qt.white) if not self._is_light_theme() else QtGui.QColor(0, 0, 0))
        return QtGui.QIcon(pm)

    def _apply_toolbar_icons(self, size: int | None = None) -> None:
        # верхние кнопки
        px = int(size) if size is not None else ICON_PX
        try:
            for btn_attr, name in (
                ("btn_pdf1", "1"),
                ("btn_pdf2", "2"),
                ("btn_map", "compare"),
                ("btn_offset", "move"),
            ):
                if hasattr(self, btn_attr):
                    btn = getattr(self, btn_attr)
                    btn.setText("")
                    btn.setIcon(self._make_tinted_icon(name, px))
                    btn.setIconSize(QtCore.QSize(px, px))
                    # ховер - в тёмной теме иконка становится чёрной
                    self._attach_dark_hover(btn, name, px)

        except Exception:
            pass

        try:
            self._apply_combo_arrow()
        except Exception:
            pass

        # иконка для кнопки "уместить целиком"
        if hasattr(self, "btn_fit"):
            try:
                self.btn_fit.setText("")
                self.btn_fit.setIcon(self._make_tinted_icon("extend", px))
                self.btn_fit.setIconSize(QtCore.QSize(px, px))
                # ховер - тёмная иконка в тёмной теме
                self._attach_dark_hover(self.btn_fit, "extend", px)
            except Exception:
                pass

        # поворот (меньший размер)
        try:
            ROT_ICON_SIZE = 16
            if hasattr(self, "btn_rot_l"):
                self.btn_rot_l.setIconSize(QtCore.QSize(ROT_ICON_SIZE, ROT_ICON_SIZE))
            if hasattr(self, "btn_rot_r"):
                self.btn_rot_r.setIconSize(QtCore.QSize(ROT_ICON_SIZE, ROT_ICON_SIZE))
        except Exception:
            pass

        # ховер для кнопок поворота - в тёмной теме иконка тоже темнеет
        try:
            if hasattr(self, "btn_rot_l"):
                self._attach_dark_hover(self.btn_rot_l, None, 14)
            if hasattr(self, "btn_rot_r"):
                self._attach_dark_hover(self.btn_rot_r, None, 14)
        except Exception:
            pass

        # стрелки внизу (меньший размер)
        try:
            NAV_ICON_SIZE = 16
            if hasattr(self, "btn_prev"):
                self.btn_prev.setText("")
                self.btn_prev.setIcon(self._make_tinted_icon("arrow_left", NAV_ICON_SIZE))
                self.btn_prev.setIconSize(QtCore.QSize(NAV_ICON_SIZE, NAV_ICON_SIZE))
            if hasattr(self, "btn_next"):
                self.btn_next.setText("")
                self.btn_next.setIcon(self._make_tinted_icon("arrow_right", NAV_ICON_SIZE))
                self.btn_next.setIconSize(QtCore.QSize(NAV_ICON_SIZE, NAV_ICON_SIZE))
            # hover - в тёмной теме стрелки становятся чёрными
            if hasattr(self, "btn_prev"):
                self._attach_dark_hover(self.btn_prev, "arrow_left", NAV_ICON_SIZE)
            if hasattr(self, "btn_next"):
                self._attach_dark_hover(self.btn_next, "arrow_right", NAV_ICON_SIZE)


        except Exception:
            pass
        # стрелка у левого края
        try:
            if hasattr(self, "panel") and hasattr(self, "nav_toggle"):
                self._set_nav_arrow(self.panel.isVisible())
        except Exception:
            pass
        # hover у стрелки у левого края - в тёмной теме делаем её чёрной
        try:
            if hasattr(self, "nav_toggle"):
                self._attach_dark_hover(self.nav_toggle, None, px)
        except Exception:
            pass

    def _apply_combo_arrow(self) -> None:
        if not hasattr(self, "cmb_mode"):
            return
        app = QtWidgets.QApplication.instance()
        icon_path = resolve_icon_path("arrow_down", ICON_DIR, app=app)
        if not self._is_light_theme():
            white_path = os.path.join(ICON_DIR, "white", "arrow-down.png")
            if os.path.exists(white_path):
                icon_path = white_path
        if not icon_path or not os.path.exists(icon_path):
            icon_path = DOWN_ARROW_ICON_PATH
        if not icon_path or not os.path.exists(icon_path):
            return
        arrow_path = icon_path.replace("\\", "/")
        self.cmb_mode.setStyleSheet(
            "QComboBox { padding-right: 20px; }"
            "QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 16px; border: none; background: transparent; "
            "background-image: url('%s'); background-repeat: no-repeat; background-position: center left; }"
            "QComboBox::down-arrow { image: url('%s'); width: 12px; height: 12px; margin-right: 4px; }"
            % (arrow_path, arrow_path)
        )



    def _nav_arrow_width(self) -> int:
        try:
            return (self.nav_toggle.sizeHint().width() if hasattr(self, "nav_toggle") else 0) + 4
        except Exception:
            return 0

    def _sync_splitter_width(self, panel_w: int) -> None:
        # panel_w - целевая ширина панели миниатюр без учёта стрелки
        # Блокировка изменения размеров во время построения миниатюр
        if getattr(self, '_splitter_locked', False):
            return
        try:
            total = max(1, self.width())
            left = max(self._nav_arrow_width(), min(panel_w + self._nav_arrow_width(), total - 1))
            if hasattr(self, "splitter"):
                self.splitter.setSizes([left, total - left])
        except Exception:
            pass

    def _toggle_nav_animated(self, show: bool) -> None:
        if not hasattr(self, "_nav_anim"):
            self._nav_anim = QtCore.QPropertyAnimation(self.panel, b"maximumWidth", self)
            self._nav_anim.setDuration(220)
            self._nav_anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        # синхронизация ширины левой области со значением анимации
        if not hasattr(self, "_nav_anim_upd"):
            self._nav_anim_upd = lambda v: self._sync_splitter_width(int(v))
        else:
            try:
                self._nav_anim.valueChanged.disconnect(self._nav_anim_upd)
            except Exception:
                pass
        self._nav_anim.valueChanged.connect(self._nav_anim_upd)

        if not hasattr(self, "_nav_saved_width") or self._nav_saved_width <= 0:
            self._nav_saved_width = max(self.panel.width(), self.panel.minimumWidth(), 240)

        self._nav_anim.stop()
        if show:
            self.panel.setVisible(True)
            # когда панель показываем - возвращаем выравнивание влево - вверх
            try:
                if getattr(self, "mode", "diff") == "diff":
                    self.view_scroll.setAlignment(QtCore.Qt.AlignCenter)
                else:
                    self.view_scroll.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
            except Exception:
                pass

            # перед стартом раздвинем левую часть только до стрелки
            self._sync_splitter_width(0)

            self.panel.setMinimumWidth(0)
            self.panel.setMaximumWidth(self._nav_saved_width)
            self._nav_anim.setStartValue(0)
            self._nav_anim.setEndValue(self._nav_saved_width)
            self._nav_anim.start()
            self._set_nav_arrow(True)
            try:
                self.btn_nav.setChecked(True)
            except Exception:
                pass
        else:
            self._nav_saved_width = max(self.panel.width(), self.panel.minimumWidth(), 240)
            self.panel.setMinimumWidth(0)
            # старт анимации с текущей ширины панели
            try:
                self._nav_anim.setStartValue(self.panel.width())
            except Exception:
                self._nav_anim.setStartValue(self._nav_saved_width)

            self._nav_anim.setEndValue(0)
            def _hide():
                self.panel.setVisible(False)
                # при сворачивании подвинем сплиттер к стрелке
                try:
                    self._sync_splitter_width(0)
                except Exception:
                    pass
                
                # когда панель миниатюр свернули - центрируем область просмотра
                try:
                    if getattr(self, "mode", "diff") == "diff":
                        self.view_scroll.setAlignment(QtCore.Qt.AlignCenter)
                    else:
                        self.view_scroll.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
                except Exception:
                    pass

                self._set_nav_arrow(False)
                try:
                    self.btn_nav.setChecked(False)
                except Exception:
                    pass
                try:
                    self._nav_anim.finished.disconnect(_hide)
                except Exception:
                    pass
            self._nav_anim.finished.connect(_hide)
            self._nav_anim.start()

    def _on_pan_start(self):
        try:
            # For offset-alignment drag we don't want to touch scrollbars/alignment
            if bool(getattr(getattr(self, "view", None), "_drag_offset_mode", False)):
                return
            # запоминаем политики, включаем "всегда", чтобы полосы не мигали
            self._saved_hbar_policy = self.view_scroll.horizontalScrollBarPolicy()
            self._saved_vbar_policy = self.view_scroll.verticalScrollBarPolicy()
            self.view_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
            self.view_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
            # в одиночных режимах фиксируем левый-верх, чтобы не тянуло к центру
            if self.mode != 'diff' or not self.btn_offset.isChecked():
                self.view_scroll.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        except Exception:
            pass

    def _on_pan_end(self):
        try:
            # For offset-alignment drag we don't want to touch scrollbars/alignment
            if bool(getattr(getattr(self, "view", None), "_drag_offset_mode", False)):
                return
            # возвращаем центр и прежние политики полос прокрутки
            if getattr(self, "mode", "diff") == "diff":
                self.view_scroll.setAlignment(QtCore.Qt.AlignCenter)
            else:
                self.view_scroll.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
            hp = getattr(self, "_saved_hbar_policy", QtCore.Qt.ScrollBarAsNeeded)
            vp = getattr(self, "_saved_vbar_policy", QtCore.Qt.ScrollBarAsNeeded)
            self.view_scroll.setHorizontalScrollBarPolicy(hp)
            self.view_scroll.setVerticalScrollBarPolicy(vp)
        except Exception:
            pass


    def on_drag(self, dx: int, dy: int, offset_mode: bool = False):
        if not self.pdf1:
            return

        # Offset drag: adjust overlay alignment (diff mode only)
        if bool(offset_mode) and self.mode == 'diff' and self.pdf2 and self.btn_offset.isChecked():
            key = (self.page1, self.page2 if self.pdf2 else -1)
            acc = self._drag_accum
            self._drag_accum = QtCore.QPoint(acc.x() + dx, acc.y() + dy)
            if not self._drag_scheduled:
                self._drag_scheduled = True
                QtCore.QTimer.singleShot(DIFF_DRAG_INTERVAL_MS, self._apply_drag_coalesced)
            self._diff_final_timer.start(DIFF_FINAL_DELAY_MS)
            return

        # Иначе - обычная панорама "камерой" (как при просмотре одного файла)
        # Прямое обновление без блокировки сигналов для мгновенной визуальной обратной связи
        if hasattr(self, "view_scroll"):
            hbar = self.view_scroll.horizontalScrollBar()
            vbar = self.view_scroll.verticalScrollBar()
            hbar.setValue(hbar.value() - dx)
            vbar.setValue(vbar.value() - dy)



    def rotate(self, angle: int):
        self.rotation = (self.rotation + angle) % 360
        self._request_diff_render(low_quality=False)

    def _adjust_diff_offset(self, dx: int, dy: int):
        # Nudge overlay alignment in diff mode by updating page_offsets
        if not (self.mode == 'diff' and self.pdf1 and self.pdf2):
            return
        key = (self.page1, self.page2)
        cur = self.page_offsets.get(key, QtCore.QPoint(0, 0))
        new_pt = QtCore.QPoint(int(cur.x()) + int(dx), int(cur.y()) + int(dy))
        self.page_offsets[key] = self._clamp_offset_for_pair(key, new_pt)

        self._request_diff_render(low_quality=True)


    def keyPressEvent(self, ev: QtGui.QKeyEvent) -> None:
        # In diff mode, arrow keys nudge the files themselves (overlay offset),
        # not the scrollbars, for precise alignment.
        if self.mode == 'diff':
            mods = ev.modifiers()
            step = 5
            if mods & QtCore.Qt.ControlModifier:
                step = 1
            elif mods & QtCore.Qt.ShiftModifier:
                step = 20
            sign = -1 if (mods & QtCore.Qt.AltModifier) else 1

            if ev.key() == QtCore.Qt.Key_Left:
                self._adjust_diff_offset(-step * sign, 0); ev.accept(); return
            if ev.key() == QtCore.Qt.Key_Right:
                self._adjust_diff_offset(step * sign, 0); ev.accept(); return
            if ev.key() == QtCore.Qt.Key_Up:
                self._adjust_diff_offset(0, -step * sign); ev.accept(); return
            if ev.key() == QtCore.Qt.Key_Down:
                self._adjust_diff_offset(0, step * sign); ev.accept(); return
        if self.btn_offset.isChecked():
            if self.mode == 'diff':
                # двигаем именно относительное смещение между файлами (PDF2 относительно PDF1).
                # Модификаторы:
                #   Ctrl - точный шаг (1 px)
                #   Shift - крупный шаг (20 px)
                #   Alt   - двигать "как бы PDF1" (инвертировать направление)
                mods = ev.modifiers()
                step = 5
                if mods & QtCore.Qt.ControlModifier:
                    step = 1
                elif mods & QtCore.Qt.ShiftModifier:
                    step = 20
                sign = -1 if (mods & QtCore.Qt.AltModifier) else 1

                if ev.key() == QtCore.Qt.Key_Left:
                    self.on_drag(-step * sign, 0); ev.accept(); return
                if ev.key() == QtCore.Qt.Key_Right:
                    self.on_drag(step * sign, 0); ev.accept(); return
                if ev.key() == QtCore.Qt.Key_Up:
                    self.on_drag(0, -step * sign); ev.accept(); return
                if ev.key() == QtCore.Qt.Key_Down:
                    self.on_drag(0, step * sign); ev.accept(); return
            else:
                # одиночные режимы - панорамируем "камеру" шагом 20px
                step = 20
                if ev.key() == QtCore.Qt.Key_Left:
                    self.on_drag(-step, 0); ev.accept(); return
                if ev.key() == QtCore.Qt.Key_Right:
                    self.on_drag(step, 0); ev.accept(); return
                if ev.key() == QtCore.Qt.Key_Up:
                    self.on_drag(0, -step); ev.accept(); return
                if ev.key() == QtCore.Qt.Key_Down:
                    self.on_drag(0, step); ev.accept(); return
        super().keyPressEvent(ev)


    def _render_current(self) -> Image.Image | None:
        if not self.pdf1 and not self.pdf2:
            return None

        # Рендер текущих страниц
        # dpi рендера: при зуме > 1 ререндерим страницу с повышенным dpi вместо апскейла
        # При зуме < 1 уменьшаем DPI для ускорения рендеринга больших файлов
        # Use adaptive max DPI to prevent huge images on large formats
        
        # Сначала отрабатываем одиночные режимы, чтобы лишний раз не трогать второй документ
        if self.mode == 'pdf2' and self.pdf2:
            adaptive_max = self._get_adaptive_max_dpi(2, self.page2)
            eff_dpi = max(50, min(adaptive_max, int(PAGE_DPI * self.scale)))
            used_max_2 = (self._cache_key(2, self.page2, self.rotation, adaptive_max) in self._page_cache)
            im2 = self._get_best_page_image(2, self.page2, eff_dpi, self.rotation)
            self._last_render_dpi_used = (adaptive_max if used_max_2 else eff_dpi)
            return im2

        if self.pdf1:
            adaptive_max1 = self._get_adaptive_max_dpi(1, self.page1)
            eff_dpi1 = max(50, min(adaptive_max1, int(PAGE_DPI * self.scale)))
            used_max_1 = (self._cache_key(1, self.page1, self.rotation, adaptive_max1) in self._page_cache)
            im1 = self._get_best_page_image(1, self.page1, eff_dpi1, self.rotation)
            if self.mode == 'pdf1' or not self.pdf2:
                self._last_render_dpi_used = (adaptive_max1 if used_max_1 else eff_dpi1)
                return im1

        if self.pdf2:
            adaptive_max2 = self._get_adaptive_max_dpi(2, self.page2)
            eff_dpi2 = max(50, min(adaptive_max2, int(PAGE_DPI * self.scale)))
            used_max_2 = (self._cache_key(2, self.page2, self.rotation, adaptive_max2) in self._page_cache)
            im2 = self._get_best_page_image(2, self.page2, eff_dpi2, self.rotation)
        else:
            return None


        # Единый ключ смещения строго по паре (p1, p2)
        key = (self.page1, self.page2)
        pt = self.page_offsets.get(key, QtCore.QPoint(0, 0))
        # Clamp against current images/canvas
        try:
            w1, h1 = im1.width, im1.height
            w2, h2 = im2.width, im2.height
            canvas_w, canvas_h = max(w1, w2), max(h1, h2)
            slack_x = int(2 * canvas_w)
            slack_y = int(2 * canvas_h)
            if w1 <= canvas_w:
                dx_min, dx_max = (-(canvas_w - w1) - slack_x), (0 + slack_x)
            else:
                dx_min, dx_max = (0 - slack_x), ((w1 - canvas_w) + slack_x)
            if h1 <= canvas_h:
                dy_min, dy_max = (-(canvas_h - h1) - slack_y), (0 + slack_y)
            else:
                dy_min, dy_max = (0 - slack_y), ((h1 - canvas_h) + slack_y)
            dx = max(dx_min, min(dx_max, int(pt.x())))
            dy = max(dy_min, min(dy_max, int(pt.y())))
        except Exception:
            dx, dy = int(pt.x()), int(pt.y())

        # Canvas limited to maximum sheet size (e.g., A3 if comparing A3 vs A4)
        # Everything beyond the larger sheet is clipped
        canvas_w = max(im1.width, im2.width)
        canvas_h = max(im1.height, im2.height)
        
        # Create white backgrounds exactly the size of the canvas
        bg1 = Image.new('RGB', (canvas_w, canvas_h), (255, 255, 255))
        bg2 = Image.new('RGB', (canvas_w, canvas_h), (255, 255, 255))
        
        # Calculate paste positions with offset, ensuring images are clipped to canvas
        # For im1: offset by -dx, -dy (inverse of im2's offset)
        paste_x1 = -dx
        paste_y1 = -dy
        
        # For im2: offset by 0, 0 (im1 moves relative to im2)
        paste_x2 = 0
        paste_y2 = 0
        
        # Paste with automatic clipping - PIL will only paste the visible portion
        bg1.paste(im1, (paste_x1, paste_y1))
        bg2.paste(im2, (paste_x2, paste_y2))

        arr1 = np.array(bg1)
        arr2 = np.array(bg2)
        # Маска чернил: Otsu по размытым серым + лёгкая очистка шумов
        gray1 = cv2.cvtColor(arr1, cv2.COLOR_RGB2GRAY)
        gray2 = cv2.cvtColor(arr2, cv2.COLOR_RGB2GRAY)

        blur1 = cv2.GaussianBlur(gray1, (5, 5), 0)
        blur2 = cv2.GaussianBlur(gray2, (5, 5), 0)

        t1, _ = cv2.threshold(blur1, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        t2, _ = cv2.threshold(blur2, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        thr1 = int(max(210, min(245, t1)))
        thr2 = int(max(210, min(245, t2)))

        content1 = (gray1 < thr1)
        content2 = (gray2 < thr2)

        k = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        content1 = cv2.morphologyEx((content1.astype(np.uint8) * 255), cv2.MORPH_OPEN, k, iterations=1) > 0
        content2 = cv2.morphologyEx((content2.astype(np.uint8) * 255), cv2.MORPH_OPEN, k, iterations=1) > 0

        only1 = np.logical_and(content1, np.logical_not(content2))
        only2 = np.logical_and(content2, np.logical_not(content1))

        result = arr1.copy()
        result[only1] = [255, 0, 0]   # красный - только PDF1
        result[only2] = [0, 0, 255]   # синий  - только PDF2

        # Remember which DPI was used for size mapping in update_view
        self._last_render_dpi_used = (self._cache_max_dpi if (used_max_1 or used_max_2) else eff_dpi)
        return Image.fromarray(result)

    def _render_diff_pair_to_image(self, p1_index: int, p2_index: int, dpi: int) -> Image.Image | None:
        if not (self.pdf1 and self.pdf2):
            return None
        # страницы
        im1 = self._get_page_image(1, int(p1_index), int(dpi), self.rotation)
        im2 = self._get_page_image(2, int(p2_index), int(dpi), self.rotation)

        # смещение берём строго по ключу пары
        key = (int(p1_index), int(p2_index))
        pt = self.page_offsets.get(key, QtCore.QPoint(0, 0))

        # Canvas limited to maximum sheet size (e.g., A3 if comparing A3 vs A4)
        # Everything beyond the larger sheet is clipped
        canvas_w = max(im1.width, im2.width)
        canvas_h = max(im1.height, im2.height)

        # Clamp offset to stay within canvas bounds, but allow dynamic slack freedom
        try:
            w1, h1 = im1.width, im1.height
            slack_x = int(2 * canvas_w)
            slack_y = int(2 * canvas_h)
            if w1 <= canvas_w:
                dx_min, dx_max = (-(canvas_w - w1) - slack_x), (0 + slack_x)
            else:
                dx_min, dx_max = (0 - slack_x), ((w1 - canvas_w) + slack_x)
            if h1 <= canvas_h:
                dy_min, dy_max = (-(canvas_h - h1) - slack_y), (0 + slack_y)
            else:
                dy_min, dy_max = (0 - slack_y), ((h1 - canvas_h) + slack_y)
            dx = max(dx_min, min(dx_max, int(pt.x())))
            dy = max(dy_min, min(dy_max, int(pt.y())))
        except Exception:
            dx, dy = int(pt.x()), int(pt.y())
        
        # Create white backgrounds exactly the size of the canvas
        bg1 = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))
        bg2 = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))
        
        # Calculate paste positions with offset, ensuring images are clipped to canvas
        # For im1: offset by -dx, -dy (inverse of im2's offset)
        paste_x1 = -dx
        paste_y1 = -dy
        
        # For im2: offset by 0, 0 (im1 moves relative to im2)
        paste_x2 = 0
        paste_y2 = 0
        
        # Paste with automatic clipping - PIL will only paste the visible portion
        bg1.paste(im1, (paste_x1, paste_y1))
        bg2.paste(im2, (paste_x2, paste_y2))

        arr1 = np.asarray(bg1).astype(np.uint8)
        arr2 = np.asarray(bg2).astype(np.uint8)

        gray1 = cv2.cvtColor(arr1, cv2.COLOR_RGB2GRAY)
        gray2 = cv2.cvtColor(arr2, cv2.COLOR_RGB2GRAY)
        blur1 = cv2.GaussianBlur(gray1, (5, 5), 0)
        blur2 = cv2.GaussianBlur(gray2, (5, 5), 0)
        t1, _ = cv2.threshold(blur1, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        t2, _ = cv2.threshold(blur2, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        thr1 = int(max(210, min(245, t1)))
        thr2 = int(max(210, min(245, t2)))

        content1 = (gray1 < thr1)
        content2 = (gray2 < thr2)
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        content1 = cv2.morphologyEx((content1.astype(np.uint8) * 255), cv2.MORPH_OPEN, k, iterations=1) > 0
        content2 = cv2.morphologyEx((content2.astype(np.uint8) * 255), cv2.MORPH_OPEN, k, iterations=1) > 0

        only1 = np.logical_and(content1, np.logical_not(content2))
        only2 = np.logical_and(content2, np.logical_not(content1))

        result = arr1.copy()
        result[only1] = [255, 0, 0]   # красный - только PDF1
        result[only2] = [0, 0, 255]   # синий  - только PDF2
        return Image.fromarray(result)


    def _request_single_render(self, which: int, page_index: int, rotation: int, scale: float, low_quality: bool = False):
        """Синхронный рендеринг одиночной страницы (простой и безопасный)."""
        doc = self.pdf1 if which == 1 else self.pdf2
        if doc is None:
            return
        
        try:
            # Простой синхронный рендер с адаптивным DPI
            adaptive_max = self._get_adaptive_max_dpi(which, page_index)
            base_dpi = int(PAGE_DPI * (scale if scale > 1.0 else 1.0))
            use_dpi = max(THUMB_DPI, min(adaptive_max, base_dpi))
            
            # Проверяем кэш
            key_max = self._cache_key(which, page_index, rotation, adaptive_max)
            with getattr(self, "_cache_lock", threading.RLock()):
                cached_img = self._page_cache.get(key_max)
            
            if cached_img is not None:
                self._apply_single_render(cached_img, adaptive_max, True, scale)
            else:
                # Синхронный рендер
                img = self._get_page_image(which, page_index, use_dpi, rotation, low_quality=True)
                self._apply_single_render(img, use_dpi, False, scale)
        except Exception:
            pass
    
    def _apply_single_render(self, pil_img: Image.Image, used_dpi: int, used_max_dpi: bool, scale: float):
        """Применить отрендеренное изображение одиночной страницы к UI."""
        try:
            self._last_render_dpi_used = int(used_dpi)
        except Exception:
            self._last_render_dpi_used = PAGE_DPI
        
        im = pil_img
        
        # авто-подгон под окно при первом показе
        if not getattr(self, "_fitted_once", False) and hasattr(self, "view_scroll"):
            vp = self.view_scroll.viewport().size()
            if im.width > 0 and im.height > 0 and vp.width() > 0 and vp.height() > 0:
                dpi_used = float(self._last_render_dpi_used or PAGE_DPI)
                if dpi_used <= 0:
                    dpi_used = float(PAGE_DPI)
                base_scale = float(PAGE_DPI) / float(dpi_used)
                eff_w = im.width * base_scale
                eff_h = im.height * base_scale
                fit = min(vp.width() / eff_w, vp.height() / eff_h)
                self.scale = min(1.0, float(fit))
                try:
                    self.view._zoom = float(self.scale)
                except Exception:
                    pass
                self._fitted_once = True
        
        # масштабирование
        dpi_used = float(self._last_render_dpi_used or PAGE_DPI)
        if dpi_used <= 0:
            dpi_used = float(PAGE_DPI)
        scale_px = float(scale) * (float(PAGE_DPI) / float(dpi_used))
        if abs(scale_px - 1.0) > 1e-3:
            w = max(1, int(im.width * scale_px))
            h = max(1, int(im.height * scale_px))
            im = im.resize((w, h), Image.LANCZOS)
        
        qimg = pil_to_qimage(im)
        pm = QtGui.QPixmap.fromImage(qimg)
        self.view.setPixmap(pm)
        self.view.resize(pm.size())

    def update_view(self):
        if self.mode == 'diff' and self.pdf1 and self.pdf2:
            self._request_diff_render(low_quality=False)
            return
        
        # Для одиночных режимов используем фоновый рендеринг
        if self.mode == 'pdf1' and self.pdf1:
            self._request_single_render(1, self.page1, self.rotation, self.scale, low_quality=False)
            return
        
        if self.mode == 'pdf2' and self.pdf2:
            self._request_single_render(2, self.page2, self.rotation, self.scale, low_quality=False)
            return
        
        # Fallback для режимов без документов
        self.view.setPixmap(QtGui.QPixmap())

    def export_pdf(self):
        """
        Экспорт:
        - если есть пары маппинга и пользователь выбирает "Пары из маппинга" - формируем PDF, где КАЖДАЯ пара это отдельная страница со сравнением,
        с учётом сохранённого смещения пары.
        - иначе сохраняем текущий вид (то, что отображает self.view) одной страницей.
        """
        if not getattr(self, "view", None):
            QtWidgets.QMessageBox.warning(self, "Экспорт", "Нет активного просмотра.")
            return

        # выбор режима экспорта
        export_mode = "current"
        if getattr(self, "mappings", None):
            msg = QtWidgets.QMessageBox(self)
            msg.setWindowTitle("Экспорт PDF")
            msg.setText("Что экспортировать?")
            btn_cur   = msg.addButton("Текущую страницу", QtWidgets.QMessageBox.AcceptRole)
            btn_pairs = msg.addButton("Пары из маппинга", QtWidgets.QMessageBox.ActionRole)
            btn_cancel= msg.addButton("Отмена", QtWidgets.QMessageBox.RejectRole)
            msg.exec()
            if msg.clickedButton() is btn_cancel:
                return
            if msg.clickedButton() is btn_pairs:
                export_mode = "pairs"

        # внутренняя функция рендера сравнения конкретной пары в PIL.Image
        def _render_pair_to_image(p1_index: int, p2_index: int, dpi: int):
            # если в проект вставлена моя хелпер-функция - пользуемся ею
            if hasattr(self, "_render_diff_pair_to_image"):
                return self._render_diff_pair_to_image(p1_index, p2_index, dpi)

            # fallback - простой рендер без зависимости на внешний метод
            if not (getattr(self, "pdf1", None) and getattr(self, "pdf2", None)):
                return None
            try:
                with getattr(self, "_fitz_lock", threading.RLock()):
                    p1 = self.pdf1.load_page(int(p1_index))
                    p2 = self.pdf2.load_page(int(p2_index))
                    im1 = fitz_page_to_pil(p1, dpi=dpi, rotation=getattr(self, "rotation", 0))
                    im2 = fitz_page_to_pil(p2, dpi=dpi, rotation=getattr(self, "rotation", 0))

                # смещение по ключу пары
                key = (int(p1_index), int(p2_index))
                pt = getattr(self, "page_offsets", {}).get(key, QtCore.QPoint(0, 0))
                dx, dy = int(pt.x()), int(pt.y())

                x1, y1 = max(0, -dx), max(0, -dy)
                x2, y2 = max(0,  dx), max(0,  dy)
                w = max(im1.width + x1, im2.width + x2)
                h = max(im1.height + y1, im2.height + y2)

                bg1 = Image.new("RGB", (w, h), (255, 255, 255))
                bg2 = Image.new("RGB", (w, h), (255, 255, 255))
                bg1.paste(im1, (x1, y1))
                bg2.paste(im2, (x2, y2))

                arr1 = np.asarray(bg1).astype(np.uint8)
                arr2 = np.asarray(bg2).astype(np.uint8)

                gray1 = cv2.cvtColor(arr1, cv2.COLOR_RGB2GRAY)
                gray2 = cv2.cvtColor(arr2, cv2.COLOR_RGB2GRAY)
                blur1 = cv2.GaussianBlur(gray1, (5, 5), 0)
                blur2 = cv2.GaussianBlur(gray2, (5, 5), 0)
                t1, _ = cv2.threshold(blur1, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                t2, _ = cv2.threshold(blur2, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                thr1 = int(max(210, min(245, t1)))
                thr2 = int(max(210, min(245, t2)))

                content1 = (gray1 < thr1)
                content2 = (gray2 < thr2)
                k = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
                content1 = cv2.morphologyEx((content1.astype(np.uint8) * 255), cv2.MORPH_OPEN, k, iterations=1) > 0
                content2 = cv2.morphologyEx((content2.astype(np.uint8) * 255), cv2.MORPH_OPEN, k, iterations=1) > 0

                only1 = np.logical_and(content1, np.logical_not(content2))
                only2 = np.logical_and(content2, np.logical_not(content1))

                result = arr1.copy()
                result[only1] = [255, 0, 0]   # красный - только PDF1
                result[only2] = [0, 0, 255]   # синий  - только PDF2
                return Image.fromarray(result)
            except Exception:
                return None

        # ------------------------------------------------------------------------------------------------------------------
        # Экспорт пар как сравнений
        if export_mode == "pairs":
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Сохранить PDF", "pairs.pdf", "PDF Files (*.pdf)")
            if not path:
                return
            try:
                eff_dpi = max(100, min(600, int(PAGE_DPI * (getattr(self, "scale", 1.0) if getattr(self, "scale", 1.0) > 1.0 else 1.0))))
                out = fitz.open()
                for (p1, p2) in list(self.mappings):
                    img = _render_pair_to_image(int(p1), int(p2), eff_dpi)
                    if img is None:
                        continue
                    bio = io.BytesIO()
                    img.save(bio, format="PNG")
                    png_bytes = bio.getvalue()
                    width_pt  = img.width  * 72.0 / eff_dpi
                    height_pt = img.height * 72.0 / eff_dpi
                    page = out.new_page(width=width_pt, height=height_pt)
                    rect = fitz.Rect(0, 0, width_pt, height_pt)
                    page.insert_image(rect, stream=png_bytes)
                out.save(path, deflate=True, clean=True)
                out.close()
                QtWidgets.QMessageBox.information(self, "Готово", f"Экспортировано: {path}")
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить PDF:\n{e}")
            return

        # ------------------------------------------------------------------------------------------------------------------
        # Экспорт текущего вида (то, что на self.view)
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Сохранить PDF", "page.pdf", "PDF Files (*.pdf)")
        if not path:
            return
        try:
            pm = getattr(self.view, "pixmap", lambda: None)()
            if not isinstance(pm, QtGui.QPixmap) or pm.isNull():
                QtWidgets.QMessageBox.warning(self, "Экспорт", "Нечего сохранять - изображение отсутствует.")
                return

            eff_dpi = max(100, min(600, int(PAGE_DPI * (getattr(self, "scale", 1.0) if getattr(self, "scale", 1.0) > 1.0 else 1.0))))

            qim = pm.toImage()
            buf = QtCore.QBuffer()
            buf.open(QtCore.QIODevice.WriteOnly)
            qim.save(buf, "PNG")
            data = bytes(buf.data())

            width_pt  = pm.width()  * 72.0 / eff_dpi
            height_pt = pm.height() * 72.0 / eff_dpi
            doc = fitz.open()
            page = doc.new_page(width=width_pt, height=height_pt)
            rect = fitz.Rect(0, 0, width_pt, height_pt)
            page.insert_image(rect, stream=data)
            doc.save(path, deflate=True, clean=True)
            doc.close()
            QtWidgets.QMessageBox.information(self, "Готово", f"Экспортировано: {path}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить PDF:\n{e}")


    def fit_to_window(self):
        """Уместить изображение целиком в окно просмотра."""
        if not self.pdf1 and not self.pdf2:
            return
        
        if not hasattr(self, "view_scroll"):
            return
        
        # Получаем размер viewport с учётом scrollbars + небольшой отступ
        vp = self.view_scroll.viewport().size()
        margin = 16  # Увеличенный отступ для лучшей видимости
        available_w = max(100, vp.width() - margin * 2)
        available_h = max(100, vp.height() - margin * 2)
        
        if available_w <= 0 or available_h <= 0:
            return
        
        # Получаем реальные размеры страниц в points (не пикселях!)
        # Это даст нам правильные пропорции независимо от DPI
        try:
            if self.mode == 'diff' and self.pdf1 and self.pdf2:
                # Для режима сравнения берём максимальный размер из обеих страниц
                with getattr(self, "_fitz_lock", threading.RLock()):
                    p1 = self.pdf1.load_page(self.page1)
                    p2 = self.pdf2.load_page(self.page2)
                
                # Учитываем поворот
                if self.rotation % 180 == 0:
                    w1, h1 = p1.rect.width, p1.rect.height
                    w2, h2 = p2.rect.width, p2.rect.height
                else:
                    w1, h1 = p1.rect.height, p1.rect.width
                    w2, h2 = p2.rect.height, p2.rect.width
                
                page_width = max(w1, w2)
                page_height = max(h1, h2)
                
            elif self.mode == 'pdf2' and self.pdf2:
                with getattr(self, "_fitz_lock", threading.RLock()):
                    p = self.pdf2.load_page(self.page2)
                if self.rotation % 180 == 0:
                    page_width, page_height = p.rect.width, p.rect.height
                else:
                    page_width, page_height = p.rect.height, p.rect.width
                    
            elif self.pdf1:
                with getattr(self, "_fitz_lock", threading.RLock()):
                    p = self.pdf1.load_page(self.page1)
                if self.rotation % 180 == 0:
                    page_width, page_height = p.rect.width, p.rect.height
                else:
                    page_width, page_height = p.rect.height, p.rect.width
            else:
                return
            
            # Конвертируем points в пиксели при базовом DPI (300)
            # page_width/height уже в points (1 point = 1/72 inch)
            base_pixels_w = page_width * (PAGE_DPI / 72.0)
            base_pixels_h = page_height * (PAGE_DPI / 72.0)
            
            # Вычисляем масштаб для полного умещения
            fit_w = available_w / base_pixels_w
            fit_h = available_h / base_pixels_h
            fit_scale = min(fit_w, fit_h)
            
            # Применяем масштаб с ограничениями
            self.scale = max(0.05, min(10.0, float(fit_scale)))
            
            try:
                self.view._zoom = float(self.scale)
            except Exception:
                pass
            
            self._fitted_once = True
            self.update_view()
            
        except Exception as e:
            print(f"Error in fit_to_window: {e}")
            return


    # иконка заданного цвета и ховер-хэндлер для тёмной темы
    def _make_colored_icon(self, name: str, size: int, color_hex: str) -> QtGui.QIcon:
        app = QtWidgets.QApplication.instance()
        path = resolve_icon_path(name, ICON_DIR, app=app)
        pm = QtGui.QPixmap(path)
        if pm.isNull():
            return QtGui.QIcon()
        pm = pm.scaled(size, size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        pm = self._tint_pixmap(pm, QtGui.QColor(color_hex))
        return QtGui.QIcon(pm)

    def _attach_dark_hover(self, btn: QtWidgets.QPushButton, icon_name: str | None, px: int):
        # фиксируем имя иконки для восстановления
        if icon_name:
            btn.setProperty("_icon_name", icon_name)
        btn.setAttribute(QtCore.Qt.WA_Hover, True)
        btn.setMouseTracking(True)

        def _enter(ev):
            try:
                # In dark theme: keep icons light on hover (do NOT darken)
                # In light theme: keep icons black on hover
                name = btn.property("_icon_name")
                if self._is_light_theme():
                    # Light theme: keep icons pure black on hover as requested
                    if name:
                        btn.setIcon(self._make_colored_icon(name, px, "#000000"))
                    else:
                        ic = btn.icon()
                        pm = ic.pixmap(px, px)
                        if not pm.isNull():
                            pm = self._tint_pixmap(pm, QtGui.QColor(0, 0, 0))
                            btn.setIcon(QtGui.QIcon(pm))
                else:
                    # Dark theme: no darkening on hover — keep icon white
                    if name:
                        btn.setIcon(self._make_colored_icon(name, px, "#ffffff"))
                    else:
                        ic = btn.icon()
                        pm = ic.pixmap(px, px)
                        if not pm.isNull():
                            pm = self._tint_pixmap(pm, QtGui.QColor(Qt.white))
                            btn.setIcon(QtGui.QIcon(pm))
            finally:
                QtWidgets.QPushButton.enterEvent(btn, ev)

        def _leave(ev):
            try:
                # Restore normal theme-appropriate color
                name = btn.property("_icon_name")
                if name:
                    btn.setIcon(self._make_tinted_icon(name, px))
                else:
                    ic = btn.icon()
                    pm = ic.pixmap(px, px)
                    if not pm.isNull():
                        pm = self._tint_pixmap(pm, QtGui.QColor(Qt.white) if not self._is_light_theme() else QtGui.QColor(0, 0, 0))
                        btn.setIcon(QtGui.QIcon(pm))
            finally:
                QtWidgets.QPushButton.leaveEvent(btn, ev)

        btn.enterEvent = _enter
        btn.leaveEvent = _leave

    # Mapping window — simplified placeholder retaining visual style
    def _open_mapping_window_safe(self):
        try:
            self.open_mapping_window()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Маппинг - ошибка", str(e))

    def open_mapping_window(self):
        def _has_doc(doc):
            try:
                return (doc is not None) and int(getattr(doc, "page_count", 0)) > 0
            except Exception:
                return False

        if not (_has_doc(self.pdf1) and _has_doc(self.pdf2)):
            QtWidgets.QMessageBox.information(self, "Маппинг", "Загрузите оба PDF.")
            return


        dlg = QtWidgets.QDialog(self)
        dlg.setAttribute(QtCore.Qt.WA_QuitOnClose, False)
        dlg.setWindowTitle("Маппинг листов")
        dlg.resize(1200, 700)
        
        app = QtWidgets.QApplication.instance()
        dark = self._current_theme == THEME_DARK
        if app:
            dark = getattr(app, "_pdf_theme_dark", False) or self._current_theme == THEME_DARK
            _set_window_theme(dlg, dark=dark)
            QtCore.QTimer.singleShot(0, lambda d=dlg, dk=dark: _set_window_theme(d, dark=dk))



        grid = QtWidgets.QGridLayout(dlg)

        # Левая колонка
        left_scroll = QtWidgets.QScrollArea(); left_scroll.setWidgetResizable(True)
        left_inner = QtWidgets.QWidget(); left_v = QtWidgets.QVBoxLayout(left_inner); left_v.setSpacing(6)
        left_scroll.setWidget(left_inner)
        left_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        left_v.setContentsMargins(0, 0, 0, 0)
        left_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)


        # Правая колонка
        right_scroll = QtWidgets.QScrollArea(); right_scroll.setWidgetResizable(True)
        right_inner = QtWidgets.QWidget(); right_v = QtWidgets.QVBoxLayout(right_inner); right_v.setSpacing(6)
        right_scroll.setWidget(right_inner)
        right_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        right_v.setContentsMargins(0, 0, 0, 0)
        right_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)


        # Центр - превью выбора и кнопки
        center = QtWidgets.QWidget(); cb = QtWidgets.QVBoxLayout(center); cb.setSpacing(10)

        title = QtWidgets.QLabel("Выбранные страницы"); title.setStyleSheet("font-weight:600;")
        cb.addWidget(title)

        left_preview = QtWidgets.QLabel("Не выбрано"); left_preview.setAlignment(QtCore.Qt.AlignCenter)
        left_preview.setFixedSize(220, 280); left_preview.setFrameShape(QtWidgets.QFrame.Box)
        right_preview = QtWidgets.QLabel("Не выбрано"); right_preview.setAlignment(QtCore.Qt.AlignCenter)
        right_preview.setFixedSize(220, 280)
        # Цвет рамок как в главном меню
        preview_left_border = "#ffffff" if dark else "#e74c3c"
        preview_right_border = "#ffffff" if dark else "#3498db"
        left_preview.setStyleSheet(f"border: 2px solid {preview_left_border};")
        right_preview.setStyleSheet(f"border: 2px solid {preview_right_border};")


        previews = QtWidgets.QHBoxLayout(); previews.addWidget(left_preview); previews.addWidget(right_preview)
        cb.addLayout(previews)

        btn_save = QtWidgets.QPushButton("Сохранить пару"); btn_save.setEnabled(False)
        cb.addWidget(btn_save)
        cb.addStretch(1)

        # Нижняя панель - сохранённые пары
        saved_title = QtWidgets.QLabel("Сохранённые пары"); saved_title.setStyleSheet("font-weight:600;")
        saved_list = QtWidgets.QListWidget()
        saved_list.setFrameShape(QtWidgets.QFrame.NoFrame)
        list_bg = "#FFFFFF" if not dark else "#1e1e1e"
        list_border = "#dcdcdc" if not dark else "#606060"
        list_hover = "#FFE3C2" if not dark else "#3a2b1a"
        list_hover_border = "#FFA74B" if not dark else "#71451f"
        row_base_style = f"QWidget#saved_pair_row{{background:{list_bg};border:1px solid {list_border};border-radius:12px;}}"
        row_hover_style = f"QWidget#saved_pair_row{{background:{list_hover};border:1px solid {list_hover_border};border-radius:12px;}}"
        saved_list.setStyleSheet(
            "QListWidget{padding:6px;border:0;background:transparent;}"
            "QListWidget::item{background:transparent;border:0;margin:2px 0px;}"
        )
        saved_list.setUniformItemSizes(False)
        saved_list.setWordWrap(False)
        saved_list.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)

        saved_list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        saved_list.setMouseTracking(True)
        saved_list.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        saved_list.setFocusPolicy(QtCore.Qt.NoFocus)

        saved_list.setMouseTracking(True)


        grid.addWidget(left_scroll,  0, 0)
        grid.addWidget(center,       0, 1)
        grid.addWidget(right_scroll, 0, 2)
        grid.addWidget(saved_title,  1, 0, 1, 3)
        grid.addWidget(saved_list,   2, 0, 1, 3)
        # чтобы рамка подсветки не выходила за пределы списка
        saved_list.setViewportMargins(6, 4, 6, 4)


        # Подготовка превью страниц
        TH = 160  # высота миниатюры
        def page_thumb(doc, idx):
            try:
                with getattr(self, "_fitz_lock", threading.RLock()):
                    im = fitz_page_to_pil(doc.load_page(idx), dpi=THUMB_DPI)
                qim = pil_to_qimage(im)
                qpm = QtGui.QPixmap.fromImage(qim)
                pm = qpm.scaledToHeight(TH, QtCore.Qt.SmoothTransformation) if not qpm.isNull() else QtGui.QPixmap()
            except Exception:
                pm = QtGui.QPixmap(120, TH); pm.fill(QtGui.QColor("#EEE"))
            return pm

        left_labels = []
        right_labels = []
        sel = {'p1': None, 'p2': None}
        thumb_border = "#ffffff" if dark else "#555"
        sel_left_border = "#ffffff" if dark else "#e74c3c"
        sel_right_border = "#ffffff" if dark else "#3498db"

        def make_row(vbox, idx, pm, side):
            row = QtWidgets.QWidget(); hb = QtWidgets.QHBoxLayout(row); hb.setContentsMargins(0,0,0,0); hb.setSpacing(8)
            row.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
            num = QtWidgets.QLabel(str(idx+1)); num.setFixedWidth(28); num.setAlignment(QtCore.Qt.AlignRight|QtCore.Qt.AlignVCenter)
            lbl = QtWidgets.QLabel(); lbl.setPixmap(pm); lbl.setFrameShape(QtWidgets.QFrame.Box); lbl.setLineWidth(1)
            lbl.setCursor(QtCore.Qt.PointingHandCursor)
            # Центрируем миниатюру в фиксированной рамке как в начальном меню
            lbl.setAlignment(QtCore.Qt.AlignCenter)
            lbl.setFixedSize(160, TH)
            try:
                lbl.setPixmap(pm.scaled(lbl.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
            except Exception:
                pass
            lbl.setStyleSheet(f"border: 1px solid {thumb_border}; border-radius: 8px;")
            hb.addWidget(num); hb.addWidget(lbl, 1)
            vbox.addWidget(row)
            def pick():
                # Сброс подсветки
                for L in (left_labels if side == 1 else right_labels):
                    L.setStyleSheet(f"border: 1px solid {thumb_border}; border-radius: 8px;")
                # Выделение
                if side == 1:
                    lbl.setStyleSheet(f"border: 2px solid {sel_left_border}; border-radius: 8px;")
                else:
                    lbl.setStyleSheet(f"border: 2px solid {sel_right_border}; border-radius: 8px;")
                # Превью
                prev = left_preview if side == 1 else right_preview
                try:
                    doc = self.pdf1 if side == 1 else self.pdf2
                    with getattr(self, "_fitz_lock", threading.RLock()):
                        im_prev = fitz_page_to_pil(doc.load_page(idx), dpi=120)
                    pm_prev = QtGui.QPixmap.fromImage(pil_to_qimage(im_prev)).scaled(
                        prev.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
                    )
                    prev.setPixmap(pm_prev)
                except Exception:
                    prev.setPixmap(pm.scaled(prev.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
                prev.setText("")
                sel['p1' if side == 1 else 'p2'] = idx
                btn_save.setEnabled(sel['p1'] is not None and sel['p2'] is not None)
            lbl.mousePressEvent = lambda _e: pick()
            return lbl

        # Заполняем левую колонку
        for i in range(self.pdf1.page_count):
            pm = page_thumb(self.pdf1, i)
            L = make_row(left_v, i, pm, side=1)
            left_labels.append(L)

        # Заполняем правую колонку
        for i in range(self.pdf2.page_count):
            pm = page_thumb(self.pdf2, i)
            R = make_row(right_v, i, pm, side=2)
            right_labels.append(R)
            # Имена файлов для подписей
            name1 = self._display_name(self.pdf1_path) if self.pdf1_path else "PDF1"
            name2 = self._display_name(self.pdf2_path) if self.pdf2_path else "PDF2"


        # ВНУТРЕННЯЯ функция: перерисовать список сохранённых пар.
        # подгонять ширину строк списка под viewport, чтобы не появлялся горизонтальный скролл
        def _fit_saved_width():
            w = max(1, saved_list.viewport().width() - 4)
            for i in range(saved_list.count()):
                it = saved_list.item(i)
                row = saved_list.itemWidget(it)
                if row:
                    row.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
                    row.setMinimumWidth(w)
                    row.setMaximumWidth(w)
                    it.setSizeHint(QtCore.QSize(w, row.sizeHint().height()))

        # ВАЖНО: внутри open_mapping_window, чтобы были доступны saved_list / btn_del и т.п.
        def refresh_saved():
            
            QtCore.QTimer.singleShot(0, _fit_saved_width)
            saved_list.clear()

            # удаление пары из сохранённых
            def _del_pair(pair):
                try:
                    self.mappings.remove(pair)
                except ValueError:
                    pass
                refresh_saved()

            app = QtWidgets.QApplication.instance()
            name1 = self._display_name(getattr(self, "pdf1_path", "") or "PDF1")
            name2 = self._display_name(getattr(self, "pdf2_path", "") or "PDF2")

            for (p1, p2) in self.mappings:
                it = QtWidgets.QListWidgetItem()
                it.setData(QtCore.Qt.UserRole, (p1, p2))
                it.setFlags(it.flags() & ~QtCore.Qt.ItemIsSelectable)


                row = QtWidgets.QWidget()
                row.setObjectName("saved_pair_row")
                row.setAttribute(QtCore.Qt.WA_StyledBackground, True)
                row.setMinimumHeight(32)
                hb = QtWidgets.QHBoxLayout(row); hb.setContentsMargins(10, 6, 10, 6); hb.setSpacing(8)
                row.setStyleSheet(row_base_style)


                lbl_l = QtWidgets.QLabel(f"{name1} стр.{p1+1}")
                lbl_r = QtWidgets.QLabel(f"{name2} стр.{p2+1}")
                lbl_l.setFrameShape(QtWidgets.QFrame.NoFrame)
                lbl_r.setFrameShape(QtWidgets.QFrame.NoFrame)
                # красивая подсветка как в nik_style и эллипис по центру
                # в тёмной теме сразу делаем текст белым (на ховере он станет чёрным)
                if not self._is_light_theme():
                    lbl_l.setStyleSheet("color:#fff;")
                    lbl_r.setStyleSheet("color:#fff;")
                row.setAttribute(QtCore.Qt.WA_Hover, True)
                row.setMouseTracking(True)

                for _lab, _align in ((lbl_l, QtCore.Qt.AlignLeft), (lbl_r, QtCore.Qt.AlignRight)):
                    _lab.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
                    _lab.setAlignment(QtCore.Qt.AlignVCenter | _align)
                    _lab.setMinimumWidth(10)
                    _lab.setToolTip(_lab.text())  # полный текст в тултипе

                # элайд по середине при ресайзе, чтобы текст не «схлопывался»
                _lfull, _rfull = lbl_l.text(), lbl_r.text()
                def _elide_row():
                    fmL, fmR = lbl_l.fontMetrics(), lbl_r.fontMetrics()
                    lbl_l.setText(fmL.elidedText(_lfull, QtCore.Qt.ElideMiddle, max(80, lbl_l.width() - 8)))
                    lbl_r.setText(fmR.elidedText(_rfull, QtCore.Qt.ElideMiddle, max(80, lbl_r.width() - 8)))
                _old_row_resize = getattr(row, "resizeEvent", None)
                def _row_resize(ev):
                    try:
                        if _old_row_resize:
                            _old_row_resize(ev)
                    finally:
                        _elide_row()
                row.resizeEvent = _row_resize
                QtCore.QTimer.singleShot(0, _elide_row)

                ico = QtWidgets.QLabel()
                try:
                    path = resolve_icon_path("arrow-oba", ICON_DIR, app=app)
                    pm = QtGui.QPixmap(path)
                    if not pm.isNull():
                        pm = pm.scaledToHeight(16, QtCore.Qt.SmoothTransformation)
                        pm = self._tint_pixmap(pm, QtGui.QColor(Qt.white) if not self._is_light_theme() else QtGui.QColor(0, 0, 0))
                        ico.setPixmap(pm)
                    else:
                        # нет файла – оставляем пустое место фикс. ширины, без текстовой стрелки
                        ico.setFixedWidth(16)
                except Exception:
                    ico.setFixedWidth(16)



                hb.addWidget(lbl_l, 1)
                hb.addWidget(ico, 0, QtCore.Qt.AlignVCenter)
                hb.addWidget(lbl_r, 1)
                hb.addStretch(1)
                # кнопка удаления пары
                btn_del = QtWidgets.QPushButton()
                btn_del.setFlat(True)
                btn_del.setStyleSheet("QPushButton{background:transparent;border:none;padding:2px;border-radius:8px}"
                        "QPushButton:hover{background:transparent}"
                        "QPushButton:pressed{background:transparent}")
                btn_del.setObjectName("btn_icon")
                btn_del.setCursor(QtCore.Qt.PointingHandCursor)
                btn_del.setToolTip("Удалить эту пару")
                btn_del.setIcon(self._make_tinted_icon("delete", 16))
                btn_del.setIconSize(QtCore.QSize(16, 16))
                btn_del.clicked.connect(lambda _=None, pr=(p1, p2): _del_pair(pr))
                hb.addWidget(btn_del, 0, QtCore.Qt.AlignVCenter)
                # чёрные текст и иконка корзины на hover строки
                def _row_enter(_e):
                    try:
                        row.setStyleSheet(row_hover_style)
                        lbl_l.setStyleSheet("color:#000;")
                        lbl_r.setStyleSheet("color:#000;")
                        app = QtWidgets.QApplication.instance()
                        pth = resolve_icon_path("delete", ICON_DIR, app=app)
                        _pm = QtGui.QPixmap(pth).scaled(16, 16, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
                        _pm = self._tint_pixmap(_pm, QtGui.QColor(0, 0, 0) if self._is_light_theme() else QtGui.QColor(Qt.white))
                        btn_del.setIcon(QtGui.QIcon(_pm))
                        # стрелка "оба" в строке пары - тоже чёрная при hover
                        pth2 = resolve_icon_path("arrow-oba", ICON_DIR, app=app)
                        pm2 = QtGui.QPixmap(pth2)
                        if not pm2.isNull():
                            pm2 = pm2.scaledToHeight(16, QtCore.Qt.SmoothTransformation)
                            pm2 = self._tint_pixmap(pm2, QtGui.QColor(0, 0, 0) if self._is_light_theme() else QtGui.QColor(Qt.white))
                            ico.setPixmap(pm2)
                        else:
                            ico.setFixedWidth(16)
                    except Exception:
                        pass
                    return QtWidgets.QWidget.enterEvent(row, _e)

                def _row_leave(_e):
                    try:
                        row.setStyleSheet(row_base_style)
                        if self._is_light_theme():
                            lbl_l.setStyleSheet("")
                            lbl_r.setStyleSheet("")
                        else:
                            lbl_l.setStyleSheet("color:#fff;")
                            lbl_r.setStyleSheet("color:#fff;")
                        btn_del.setIcon(self._make_tinted_icon("delete", 16))
                        # вернуть стрелку "оба" к оттенку темы
                        pm0_path = resolve_icon_path("arrow-oba", ICON_DIR, app=app)
                        pm0 = QtGui.QPixmap(pm0_path)
                        if not pm0.isNull():
                            pm0 = pm0.scaledToHeight(16, QtCore.Qt.SmoothTransformation)
                            pm0 = self._tint_pixmap(pm0, self._icon_color())
                            ico.setPixmap(pm0)
                        else:
                            ico.setFixedWidth(16)
                    except Exception:
                        pass
                    return QtWidgets.QWidget.leaveEvent(row, _e)

                row.enterEvent = _row_enter
                row.leaveEvent = _row_leave

                # ширина и аккуратное "… в середине" для длинных имён
                row.setAttribute(QtCore.Qt.WA_Hover, True)
                row.setMouseTracking(True)

                for _lab in (lbl_l, lbl_r):
                    _lab.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
                    _lab.setMinimumWidth(10)
                    _lab.setAlignment(QtCore.Qt.AlignVCenter | (QtCore.Qt.AlignLeft if _lab is lbl_l else QtCore.Qt.AlignRight))
                    _lab.setToolTip(_lab.text())  # показываем полное имя в тултипе

                _left_full = lbl_l.text()
                _right_full = lbl_r.text()

                def _do_elide():
                    try:
                        fmL = lbl_l.fontMetrics()
                        fmR = lbl_r.fontMetrics()
                        lbl_l.setText(fmL.elidedText(_left_full, QtCore.Qt.ElideMiddle, max(80, lbl_l.width() - 8)))
                        lbl_r.setText(fmR.elidedText(_right_full, QtCore.Qt.ElideMiddle, max(80, lbl_r.width() - 8)))
                    except Exception:
                        pass

                _old_resize = getattr(row, "resizeEvent", None)
                def _row_resize(ev):
                    try:
                        if _old_resize:
                            _old_resize(ev)
                    except Exception:
                        pass
                    _do_elide()

                row.resizeEvent = _row_resize
                row.setMinimumHeight(32)
                QtCore.QTimer.singleShot(0, _do_elide)

                it.setSizeHint(QtCore.QSize(max(1, saved_list.viewport().width() - 8),
                            max(32, row.sizeHint().height())))

                saved_list.addItem(it)
                # добавить вертикальный зазор между строками - чтобы скруглённая подсветка не упиралась в края
                saved_list.setSpacing(6)
                saved_list.setItemWidget(it, row)
                # отложенно подгоняем ширину после вставки элементов
                QtCore.QTimer.singleShot(0, _fit_saved_width)


        def do_save():
            if sel['p1'] is None or sel['p2'] is None:
                return
            pair = (int(sel['p1']), int(sel['p2']))
            if pair not in self.mappings:
                self.mappings.append(pair)
                refresh_saved()
            # Сброс выбора
            sel['p1'] = sel['p2'] = None
            left_preview.setText("Не выбрано"); left_preview.setPixmap(QtGui.QPixmap())
            right_preview.setText("Не выбрано"); right_preview.setPixmap(QtGui.QPixmap())
            for L in left_labels + right_labels:
                L.setStyleSheet("")
            btn_save.setEnabled(False)
            QtWidgets.QMessageBox.information(dlg, "Успех", f"Пара сохранена: PDF1 стр.{pair[0]+1} ↔ PDF2 стр.{pair[1]+1}")

        def go_to_pair(item):
            p1, p2 = item.data(QtCore.Qt.UserRole)
            self.page1, self.page2 = int(p1), int(p2)
            self.rotation = 0
            self.update_view()
            self._update_ui_state()
            dlg.accept()

        btn_save.clicked.connect(do_save)
        saved_list.itemDoubleClicked.connect(go_to_pair)
        # после открытия окна ещё раз подгоняем ширину строк
        QtCore.QTimer.singleShot(0, _fit_saved_width)

        # заполнить список сохранёнными парами при открытии окна
        refresh_saved()
        QtCore.QTimer.singleShot(0, _fit_saved_width)

        _orig_resize = saved_list.resizeEvent
        def _on_saved_resize(ev):
            try:
                _orig_resize(ev)
            except Exception:
                pass
            _fit_saved_width()
        saved_list.resizeEvent = _on_saved_resize


        dlg.exec()


# --- Main entry point (only when run directly, not when imported) ---
if __name__ == "__main__":
    app_args = sys.argv[1:]

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--pdf1")
    parser.add_argument("--pdf2")
    args, _ = parser.parse_known_args(app_args)

    app = QtWidgets.QApplication(sys.argv)

    # Load saved theme from Dekstop.py settings and apply full Dekstop.py style
    saved_theme = load_saved_theme()
    dark = saved_theme == THEME_DARK
    apply_dekstop_style(app, dark=dark)

    win = PDFCompareWindow()

    # Повторно применяем стиль после создания окна для гарантии
    apply_dekstop_style(app, dark=dark)

    # Set window title bar theme to match saved theme
    _set_window_theme(win, dark=dark)

    # Предзагрузка файлов, если пришли аргументы
    if args.pdf1:
        win.open_pdf_path(1, args.pdf1)
    if args.pdf2:
        win.open_pdf_path(2, args.pdf2)
    if args.pdf1 and args.pdf2:
        # Включаем режим "Сравнение"
        idx = win.cmb_mode.findText("Сравнение")
        if idx >= 0:
            win.cmb_mode.setCurrentIndex(idx)

    win.show()

    # Финальное применение иконок после полной инициализации UI
    QtCore.QTimer.singleShot(50, win._apply_toolbar_icons)

    sys.exit(app.exec())

