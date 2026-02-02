# -*- coding: utf-8 -*-

import os
import sys
import re
import tempfile
import platform
from typing import Optional

from PySide6.QtCore import Qt, QObject, QEvent, QSettings, QTimer, QPoint, QLibraryInfo, QLocale, QTranslator, QDate, Slot
from PySide6.QtGui import QColor, QPixmap, QIcon, QPainter, QPalette, QBrush, QTextCharFormat
from PySide6.QtWidgets import QApplication, QMessageBox, QVBoxLayout, QWidget, QLayout, QSizePolicy, QStyle, QLabel, QCalendarWidget, QStyledItemDelegate, QTableView
from PySide6 import QtCore, QtGui, QtWidgets


def _env_bool(name: str, default: bool = False) -> bool:
    try:
        v = (os.getenv(name) or "").strip().lower()
        if v in ("1", "true", "yes", "y", "on"):
            return True
        if v in ("0", "false", "no", "n", "off"):
            return False
    except Exception:
        pass
    return default


# QMessageBox customizations have caused native access violations on some Windows setups.
_SAFE_MESSAGEBOX = _env_bool("LARIX_SAFE_MESSAGEBOX", sys.platform == "win32")

# --- Resource paths ---
from .paths import rsrc_path

ARROW_LEFT_ICON_PATH = rsrc_path("icon", "arrow-left.png").replace("\\", "/")
ARROW_RIGHT_ICON_PATH = rsrc_path("icon", "arrow-right.png").replace("\\", "/")
ARROW_UP_ICON_PATH = rsrc_path("icon", "arrow-up.png").replace("\\", "/")
ARROW_DOWN_ICON_PATH = rsrc_path("icon", "arrow-down.png").replace("\\", "/")
DOWN_ARROW_ICON_PATH = ARROW_DOWN_ICON_PATH
SORT_ICON_UP_PATH = ARROW_UP_ICON_PATH
SORT_ICON_DOWN_PATH = ARROW_DOWN_ICON_PATH
WARNING_ICON_PATH = rsrc_path("icon", "warning.png").replace("\\", "/")
FILTER_ICON_PATH = rsrc_path("icon", "filter.png").replace("\\", "/")
CHECK_ICON_OFF_PATH = rsrc_path("icon", "check.png").replace("\\", "/")
CHECK_ICON_ON_PATH = rsrc_path("icon", "select.png").replace("\\", "/")
CHECK_ICON_MID_PATH = rsrc_path("icon", "poloska.png").replace("\\", "/")
RCHECK_ICON_OFF_PATH = CHECK_ICON_OFF_PATH
RCHECK_ICON_ON_PATH = CHECK_ICON_ON_PATH

# --- Settings constants ---
SETTINGS_ORG = "Larix"
SETTINGS_APP = "NexusDesktop"
SETTINGS_THEME_KEY = "ui/theme"
THEME_LIGHT = "light"
THEME_DARK = "dark"


def _app_settings() -> QSettings:
    """Legacy QSettings accessor. Use load_settings()/save_settings() for new code."""
    return QSettings(SETTINGS_ORG, SETTINGS_APP)

LIGHT_THEME_QSS = ""
DARK_THEME_QSS = ""
EXTRA_QSS = (
    "QSplitter::handle:horizontal { width: 2px; background: rgba(0,0,0,0.06); border-radius: 10px; margin: 4px 0; }\n"
    "QSplitter::handle:horizontal:hover { background: rgba(247,146,30,0.12); }\n"
    "QSplitter::handle:vertical { border-radius: 10px; }\n"
    "QTreeWidget#docsTree, QTreeWidget#docsTree:focus, QTreeWidget#docsTree::item, "
    "QTreeWidget#docsTree::item:selected:active, QTreeWidget#docsTree::item:selected:!active, "
    "QTreeWidget#docsTree::item:focus { outline: 0; }\n"
    "QTreeWidget#docsTree::branch { border-image: none; image: none; background: transparent; width: 0px; }\n"
    "\n"
    "/* Smaller cancel chip in status bar (initial sync) */\n"
    "QPushButton#syncCancelBtn, QPushButton#syncCancelBtn:hover, QPushButton#syncCancelBtn:pressed, QPushButton#syncCancelBtn:disabled {\n"
    "    padding: 4px 12px;\n"
    "    min-height: 24px;\n"
    "    border-radius: 12px;\n"
    "    font-size: 12px;\n"
    "}\n"
    "\n"
    "/* Keep 'без папок' icon button compact */\n"
    "QToolButton#btnNoFolders, QToolButton#btnNoFolders:hover, QToolButton#btnNoFolders:pressed, QToolButton#btnNoFolders:checked {\n"
    "    padding: 0 8px;\n"
    "    margin: 0;\n"
    "    min-width: 32px;\n"
    "    max-width: 32px;\n"
    "    border-radius: 12px;\n"
    "}\n"
    "/* Scrollbar background - override QWidget rule */\n"
    "QScrollBar { background-color: #FFFFFF !important; }\n"
    "QScrollBar::add-line { background-color: #FFFFFF !important; }\n"
    "QScrollBar::sub-line { background-color: #FFFFFF !important; }\n"
    "QScrollBar::add-page { background-color: #FFFFFF !important; }\n"
    "QScrollBar::sub-page { background-color: #FFFFFF !important; }\n"
)

_COLOR_REPLACEMENTS = {
    # Main backgrounds - УНИФИЦИРОВАНЫ для единого фона
    "#FFFFFF": "#121212",
    "#FFF": "#121212",
    "#F5F5F5": "#121212",
    "#FAFAFA": "#121212",
    "#F0F0F0": "#121212",
    "#EFEFEF": "#121212",
    "#EAEAEA": "#121212",
    "#E6E6E6": "#121212",
    "#EEEEEE": "#121212",
    "#F2F2F2": "#121212",
    "#DCDCDC": "#404040",
    "#C9C9C9": "#505050",
    "#222222": "#e0e0e0",
    "#222": "#e0e0e0",
    "#000000": "#e0e0e0",
    "#000": "#e0e0e0",
    "#fff": "#121212",
    "#FFF": "#121212",
    "#333": "#d0d0d0",
    "#444": "#c0c0c0",
    "#555": "#b0b0b0",
    "#666": "#a0a0a0",
    "#777": "#909090",
    "#888": "#808080",
    "#999": "#707070",
    "#AAA": "#666666",
    "#B5B5B5": "#666666",
    "#9B9B9B": "#777777",
    "#FFE3C2": "#FFE3C2",
    "#FFC37A": "#FFC37A",
    "#FFE8D1": "#3a2b1a",
    "#FFF0DC": "#3f2f1f",
    "#FFF3E6": "#3e2d1c",
    "#FFD1A0": "#71451f",
    "#FFCA91": "#6a3f18",
    "#FFF9F0": "#30251c",
    "#FFF7EC": "#31241a",
    "#E8F0FE": "#2c3a4f",
    "#1A73E8": "#8ab4f8",
    "#010101": "#fefefe"
}

_COLOR_PATTERN = re.compile(
    "|".join(sorted((re.escape(k) for k in _COLOR_REPLACEMENTS), key=len, reverse=True)),
    flags=re.IGNORECASE
)

_WHITE_ICON_CACHE: dict[str, QIcon] = {}


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


def _get_white_icon_path_for_dark_theme(path: str) -> str:
    """Generate a white-tinted icon and return its path for use in dark theme CSS."""
    if not path or not os.path.exists(path):
        return path or ""
    
    try:
        pm = QPixmap(path)
        if not pm.isNull() and _should_tint_icon_white(path):
            white_pm = _tint_pixmap(pm, QColor(Qt.white))
            temp_name = f"white_{os.path.basename(path)}"
            temp_path = os.path.join(tempfile.gettempdir(), temp_name)
            white_pm.save(temp_path)
            return temp_path.replace("\\", "/")
    except Exception:
        pass
    
    return path.replace("\\", "/")


def _should_tint_icon_white(path: str) -> bool:
    """Determine if an icon should be tinted white for dark theme.
    Returns False for Settings and Refresh icons to keep them unchanged."""
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


def white_tinted_icon(source: QIcon) -> QIcon:
    if source.isNull():
        return source
    icon = QIcon()
    try:
        for size in (16, 20, 24, 28, 32, 40, 48, 64):
            pm = source.pixmap(size, size)
            if pm.isNull():
                continue
            icon.addPixmap(_tint_pixmap(pm, QColor("#e0e0e0")))
    except Exception:
        return source
    return icon if not icon.isNull() else source


def themed_icon(path: str) -> QIcon:
    """Load an icon with appropriate theming based on current theme.
    In dark mode, most icons are tinted light gray except Settings and Refresh."""
    if not path:
        return QIcon()
    
    try:
        app = QApplication.instance()
        if app and _is_dark_mode():
            return load_white_icon(path)
        else:
            return QIcon(path)
    except Exception:
        return QIcon(path)


def _settings_dir() -> str:
    """Get settings directory path."""
    app_data = os.getenv("APPDATA") or os.path.expanduser("~/.config")
    return os.path.join(app_data, "LarixNexus")


def _settings_path() -> str:
    """Get path to settings JSON file."""
    return os.path.join(_settings_dir(), "settings.json")


def load_settings() -> dict:
    """Load global settings from JSON."""
    from .atomic_json import atomic_read_json
    path = _settings_path()
    default = {
        "version": 1,
        "theme": "light",
        "remember_me": False,
        "last_username": "",
        "auto_login": False,
        "ui": {
            "window_geometry": None,
            "splitter_state": None,
            "column_widths": {}
        },
        "sync": {
            "auto_sync_interval": 300,
            "conflict_resolution": "newer",
            "mass_delete_threshold": 20
        }
    }
    return atomic_read_json(path, default=default)


def save_settings(settings: dict) -> bool:
    """Save global settings to JSON."""
    from .atomic_json import atomic_write_json
    path = _settings_path()
    return atomic_write_json(path, settings, ensure_dir=True)


def update_settings(updater) -> bool:
    """Atomically update settings using updater function."""
    from .atomic_json import atomic_update_json
    path = _settings_path()
    default = {
        "version": 1,
        "theme": "light",
        "remember_me": False,
        "last_username": "",
        "auto_login": False,
        "ui": {},
        "sync": {}
    }
    return atomic_update_json(path, updater, default=default)


def _rotated_icon_path(src_path: str, degrees: int = 180) -> str:
    return src_path.replace("\\", "/")


def ensure_arrow_left() -> str:
    """Делаем перевёрнутую копию стрелки после старта QApplication и кешируем."""
    global ARROW_LEFT_ICON_PATH
    if ARROW_LEFT_ICON_PATH and os.path.exists(ARROW_LEFT_ICON_PATH):
        return ARROW_LEFT_ICON_PATH
    try:
        pm = QPixmap(ARROW_RIGHT_ICON_PATH)
        pm = pm.transformed(QtGui.QTransform().rotate(180))
        dst = os.path.join(tempfile.gettempdir(), "_arrow_rot_180.png")
        pm.save(dst)
        ARROW_LEFT_ICON_PATH = dst.replace("\\", "/")
    except Exception:
        ARROW_LEFT_ICON_PATH = ARROW_RIGHT_ICON_PATH
    return ARROW_LEFT_ICON_PATH


def apply_nik_style(app: QApplication):  # name kept for compatibility
    global LIGHT_THEME_QSS
    left_arrow = ensure_arrow_left()
    try:
        up = SORT_ICON_UP_PATH
        down = SORT_ICON_DOWN_PATH
        if not os.path.exists(up) and os.path.exists(down):
            up = _rotated_icon_path(down, 180)
        if not os.path.exists(down) and os.path.exists(up):
            down = _rotated_icon_path(up, 180)
        globals()["SORT_ICON_UP_PATH"] = up
        globals()["SORT_ICON_DOWN_PATH"] = down
        
    except Exception:
        pass
    style =("""
        /* БАЗА */
        * {{ font-family: "Segoe UI","Arial",sans-serif; color: #222; font-size: 10pt; }}
        QMainWindow {{ background: #FFF; }}
        QStatusBar {{ background: #FFFFFF; border-top: 1px solid #dcdcdc; }}
        QLabel#Header {{ background: #FFFFFF; border: 1px solid #dcdcdc; padding: 6px 10px; border-radius: 8px; font-weight: 600; }}
        QLineEdit {{ border: 1px solid #dcdcdc; padding: 6px 8px; border-radius: 8px; selection-background-color: #F7921E; }}
        QLineEdit:focus {{ border-color: #C9C9C9; }}

        /* ЛЕВОЕ ДЕРЕВО */
        QTreeWidget#docsTree {{
            background: #FFFFFF;
            border: none; border-right: 0;
            border-top-left-radius: 8px; border-bottom-left-radius: 8px;
            border-top-right-radius: 0; border-bottom-right-radius: 0;
            /* Delegate paints hover/selection; keep Qt selection transparent to avoid double highlight */
            selection-background-color: transparent;
        }}
        QTreeWidget#docsTree::viewport {{ border-top-left-radius: 8px; border-bottom-left-radius: 8px; }}
        QTreeWidget#docsTree QHeaderView {{ background: #FFFFFF; border: none; border-top-left-radius: 8px; }}
        QTreeWidget#docsTree QHeaderView::section {{
            background: #FFFFFF; border: none; border-right: none; border-left: none; padding: 4px 6px;
        }}
        QTreeWidget#docsTree QHeaderView::section:first {{ border-top-left-radius: 8px; }}
        /* Скрываем стандартный индикатор сортировки Qt */
        QHeaderView::down-arrow,
        QHeaderView::up-arrow {{
            width: 0px;
            height: 0px;
            image: none;
        }}
        /* Запрещаем hover перекрашивать выбранные элементы в дереве */
        /* Делаем фон прозрачным - делегат сам рисует скругленный фон */
        QTreeWidget#docsTree::item:hover { background: transparent; }
        QTreeWidget#docsTree::item:hover:!selected { background: transparent; }
        QTreeWidget#docsTree::item:selected,
        QTreeWidget#docsTree::item:selected:active,
        QTreeWidget#docsTree::item:selected:!active { background: transparent; color: #000000; }

        /* ПРАВАЯ ТАБЛЦА */
        QTableView {{
            background: #FFF;
            border: none;
            border-top-right-radius: 0; border-bottom-right-radius: 0;
            border-top-left-radius: 0; border-bottom-left-radius: 0;
            gridline-color: transparent;
            /* unify with tree selection */
            selection-background-color: transparent; selection-color: #000;
        }}
        QTableView::item {{ padding: 6px 8px; border: none; }}
        QTableView::item:hover {{ background: transparent; }}
        /* hover для НЕвыбранных в таблице - делегат рисует сам */
        QTableView::item:hover:!selected { background: transparent; }

        /* выбранный элемент в таблице - делегат рисует скругленный фон */
        QTableView::item:selected,
        QTableView::item:selected:active,
        QTableView::item:selected:!active { background: transparent; color: #000000; }
        /* Списки версий (левая/правая) — как в дереве */
        QListWidget::item { padding: 6px 8px; }
        QListWidget::item:hover:!selected { background: #FFE3C2; color: #000000; }
        QListWidget::item:hover { background: #FFE3C2; color: #000000; }
        QListWidget::item:selected,
        QListWidget::item:selected:active,
        QListWidget::item:selected:!active { background: #FFC37A; color: #000000; }
        QListWidget::item:pressed { background: #FFCA91; color: #000000; }



        /* Граница-ручка сплиттера: мягкая, скругленная, без рамки */
        QSplitter::handle:vertical {{
            background: rgba(0,0,0,12);
            border: none;
            border-radius: 8px; /* скругление сверху и снизу */
            margin: 0; /* тянется до границы статус-бара */
        }}

        /* КНОПКИ - общие стили */
        QToolButton, QPushButton {{
            background: #F7921E; border: 1px solid #F7921E;
            border-radius: 14px; padding: 6px 12px; font-weight: 600;
        }}
        QToolButton:hover, QPushButton:hover {{ background: rgba(247, 146, 30, 0.10); border-color: #FFA74B; }}
        QToolButton:pressed, QPushButton:pressed {{ background: rgba(247, 146, 30, 0.20); border-color: #E07E12; }}
        QToolButton:disabled, QPushButton:disabled {{ background: #f0f0f0; color: #9b9b9b; border-color: #e6e6e6; }}

        /* Белые кнопки (диалоги, вторичные, accent, user) - общий базовый стиль */
        QDialogButtonBox QPushButton,
        QPushButton[secondary="true"], QToolButton[secondary="true"],
        QToolButton#accent, QPushButton#accent,
        QToolButton#btnUser {{
            background: #FFFFFF; color: #222222;
            border: 1px solid #dcdcdc; border-radius: 14px; padding: 6px 12px; font-weight: 600;
        }}
        
        /* Hover для белых кнопок */
        QDialogButtonBox QPushButton:hover,
        QPushButton[secondary="true"]:hover, QToolButton[secondary="true"]:hover,
        QToolButton#btnUser:hover {{ 
            background: rgba(247, 146, 30, 0.10); border-color: #FFA74B; 
        }}
        
        /* Pressed для белых кнопок */
        QDialogButtonBox QPushButton:pressed,
        QPushButton[secondary="true"]:pressed, QToolButton[secondary="true"]:pressed,
        QToolButton#accent:pressed, QPushButton#accent:pressed,
        QToolButton#btnUser:pressed {{ 
            background: rgba(247, 146, 30, 0.20); border-color: #E07E12; 
        }}
        
        /* Специальный hover для accent (более прозрачный) */
        QToolButton#accent:hover, QPushButton#accent:hover {{ 
            background: rgba(247, 146, 30, 0.10); border-color: #FFA74B; 
        }}
        
        /* Disabled для вторичных кнопок */
        QPushButton[secondary="true"]:disabled, QToolButton[secondary="true"]:disabled {{ 
            background: #fafafa; color: #b5b5b5; border: 1px solid #eaeaea; 
        }}
        
        
        /* Комбобокс проектов */
        #projectsCombo {{
            
            background: #FFFFFF; color: #222;
            border: 1px solid #dcdcdc; border-radius: 12px;
            padding: 4px 30px 4px 10px;
        }}
        #projectsCombo:hover {{
            border: 1px solid #dcdcdc;
        }}
        #projectsCombo:disabled {{
            background: #f0f0f0; color: #9b9b9b;
            border: 1px solid #dcdcdc;
        }}
        #projectsCombo::drop-down {{
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 26px;
            border-left: none;
            background: #FFFFFF;
            border-top-right-radius: 12px;
            border-bottom-right-radius: 12px;
        }}
        #projectsCombo::down-arrow {{
            image: url("{DOWN_ARROW_ICON_PATH}");
            width: 12px; height: 12px;
        }}
          
        #projectsCombo QListView {{ background: #FFFFFF; border: none; border-radius: 8px; outline: none; selection-background-color: transparent; selection-color: #222222; }}
        #projectsCombo QListView::viewport {{ border: none; outline: none; }}
        #projectsCombo QListView::item {{ padding: 6px 10px; margin: 2px; border: none; border-radius: 6px; }}
        #projectsCombo QListView::frame {{ border: none; outline: none; }}
        #projectsCombo QListView::item:hover {{ background: transparent !important; border: none !important; color: #000000; }}
        #projectsCombo QListView::item:selected {{ background: transparent !important; border: none !important; color: #000000; }}
        #projectsCombo QListView::item:selected:hover {{ background: transparent !important; border: none !important; color: #000000; }}

        /* Сплиттер - мягкая «перо» ручка */
        QSplitter {{ background: transparent; border: none; }}
        QSplitter::handle {{ margin: 0; }}
        QSplitter::handle:horizontal {{
            width: 2px;
            background: rgba(0,0,0,0.08);
            border-radius: 8px; /* скругление сверху/снизу */
            margin: 6px 0; /* показать округлый торец сверху и снизу */
        }}
        QSplitter::handle:horizontal:hover {{
            background: rgba(247,146,30,0.12);
        }}
 
        /* Modern tooltips - light theme */
        QToolTip {{
            background-color: rgba(255, 255, 255, 0.95);
            color: #222222;
            border: 1px solid rgba(247, 146, 30, 0.4);
            border-radius: 10px;
            padding: 8px 12px;
            font-size: 12px;
        }}
        
        /* СКРОЛЛБАРЫ - общие стили (как в xml.py: 12px, 6px radius, 16px margin) */
        QScrollBar:vertical {{ background: #FFFFFF; width: 12px; margin: 16px 0 16px 0; border: none; }}
        QScrollBar::handle:vertical {{ background: rgba(247, 146, 30, 0.12); min-height: 24px; border-radius: 6px; border: 1px solid #FFA74B; }}
        QScrollBar::handle:vertical:hover {{ background: rgba(247, 146, 30, 0.15); border: 1px solid #FFA74B; }}
        QScrollBar::handle:vertical:pressed {{ background: rgba(247, 146, 30, 0.25); border: 1px solid #E07E12; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ background: #FFFFFF; height: 16px; subcontrol-origin: margin; border: none; border-radius: 0; image: none; }}
        QScrollBar::add-line:vertical {{ subcontrol-position: bottom; border: none; }}
        QScrollBar::sub-line:vertical {{ subcontrol-position: top; border: none; }}
        QScrollBar::add-line:vertical:hover, QScrollBar::sub-line:vertical:hover {{ background: rgba(247, 146, 30, 0.15); }}
        QScrollBar::add-line:vertical:pressed, QScrollBar::sub-line:vertical:pressed {{ background: rgba(247, 146, 30, 0.25); }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: #FFFFFF; }}
        QScrollBar:horizontal {{ background: #FFFFFF; height: 12px; margin: 0 16px 0 16px; border: none; }}
        QScrollBar::handle:horizontal {{ background: rgba(247, 146, 30, 0.12); min-width: 24px; border-radius: 6px; border: 1px solid #FFA74B; }}
        QScrollBar::handle:horizontal:hover {{ background: rgba(247, 146, 30, 0.15); border: 1px solid #FFA74B; }}
        QScrollBar::handle:horizontal:pressed {{ background: rgba(247, 146, 30, 0.25); border: 1px solid #E07E12; }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ background: #FFFFFF; width: 16px; subcontrol-origin: margin; border: none; border-radius: 0; image: none; }}
        QScrollBar::add-line:horizontal {{ subcontrol-position: right; border: none; }}
        QScrollBar::sub-line:horizontal {{ subcontrol-position: left; border: none; }}
        QScrollBar::add-line:horizontal:hover, QScrollBar::sub-line:horizontal:hover {{ background: rgba(247, 146, 30, 0.15); }}
        QScrollBar::add-line:horizontal:pressed, QScrollBar::sub-line:horizontal:pressed {{ background: rgba(247, 146, 30, 0.25); }}
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: #FFFFFF; }}

        /* Стрелки скролл-бара */
        QScrollBar::left-arrow:horizontal {{ image: url("{{ARROW_LEFT_ICON_PATH}}"); width: 12px; height: 12px; }}
        QScrollBar::right-arrow:horizontal {{ image: url("{{ARROW_RIGHT_ICON_PATH}}"); width: 12px; height: 12px; }}
        QScrollBar::up-arrow:vertical {{ image: url("{SORT_ICON_UP_PATH}"); width: 12px; height: 12px; }}
        QScrollBar::down-arrow:vertical {{ image: url("{SORT_ICON_DOWN_PATH}"); width: 12px; height: 12px; }}


        /* МЕНЮ - общие стили */
        QMenu,
        QMenu#popupMenu,
        QMenu#downloadMenu,
        QMenu#plusMenu,
        QMenu#userMenu,
        QMenu#columnsMenu {{ 
            background: #FFFFFF; color: #222222; border-radius: 8px; padding: 4px 0; min-width: 150px; 
        }}
        
        QMenu#popupMenu, QMenu#downloadMenu, QMenu#columnsMenu {{ 
            border: 1px solid #dcdcdc; 
        }}
        
        /* Элементы меню */
        QMenu::item,
        QMenu#popupMenu::item,
        QMenu#downloadMenu::item,
        QMenu#plusMenu::item,
        QMenu#userMenu::item,
        QMenu#columnsMenu::item {{ 
            padding: 6px 14px; border-radius: 6px; color: #222; 
        }}
        
        /* Hover для меню (оранжевый для всех) */
        QMenu::item:selected,
        QMenu#popupMenu::item:selected,
        QMenu#popupMenu::item:pressed,
        QMenu#downloadMenu::item:selected,
        QMenu#plusMenu::item:selected,
        QMenu#columnsMenu::item:selected,
        QMenu#columnsMenu::item:hover {{
            background: #FFE3C2; color: #000000;
        }}
        QMenu#treeMenu::item:hover {{ background: #FFE3C2; color: #000000; }}
        QMenu#treeMenu::item:selected {{ background: #FFE3C2; color: #000000; }}

        /* User menu - светлая подсветка как у кнопок */
        QMenu#userMenu::item:selected {{ background: #FFE3C2; color: #000000; }}
        
        /* Разделители */
        QMenu::separator,
        QMenu#popupMenu::separator,
        QMenu#downloadMenu::separator,
        QMenu#plusMenu::separator,
        QMenu#userMenu::separator,
        QMenu#columnsMenu::separator {{ 
            height: 1px; margin: 4px 8px; background: #eaeaea; 
        }}

        /* Чекбоксы внутри меню столбцов */
        QMenu#columnsMenu QCheckBox[menuitem="true"]{{
            color: #222; padding: 6px 12px; margin: 2px 6px;
            border: 1px solid transparent; border-radius: 8px; background: transparent;
        }}
        QMenu#columnsMenu QCheckBox[menuitem="true"]:hover{{
            background: #FFE3C2; border-color: #FFA74B; color: #000000;
        }}
        QMenu#columnsMenu QCheckBox[menuitem="true"]::indicator {{ width: 0px; height: 0px; }}

         /* Скроллбары в меню */
         QMenu QScrollBar:vertical {{ background: #FFFFFF !important; width: 12px; margin: 0; border: none; }}
         QMenu QScrollBar::handle:vertical {{ background: rgba(247, 146, 30, 0.12) !important; min-height: 24px; border-radius: 6px; border: 1px solid #FFA74B !important; }}
         QMenu QScrollBar::handle:vertical:hover {{ background: rgba(247, 146, 30, 0.15) !important; border: 1px solid #FFA74B !important; }}
         QMenu QScrollBar::handle:vertical:pressed {{ background: rgba(247, 146, 30, 0.25) !important; border: 1px solid #E07E12 !important; }}
         QMenu QScrollBar::add-line:vertical, QMenu QScrollBar::sub-line:vertical {{ background: #FFFFFF !important; height: 0; subcontrol-origin: margin; border: none; }}
         QMenu QScrollBar::add-page:vertical, QMenu QScrollBar::sub-page:vertical {{ background: #FFFFFF !important; }}

        /* Прокрытие пунктирного фокуса у дерева и таблицы */
        QTreeView, QTableView {{ outline: 0; }}
        QTreeView::item:selected:active,
        QTreeView::item:selected:!active,
        QTableView::item:selected:active,
        QTableView::item:selected:!active {{ outline: 0; }}

        /* Визуальная «молния» */
        QToolButton#btnFlash {{
            background: #FFFFFF; color: #222; border: 1px solid #dcdcdc; border-radius: 14px; padding: 6px 12px;
        }}
        QToolButton#btnFlash[checked="true"] {{
            background: #FFE3C2; border-color: #FFA74B;
        }}
        QToolButton#btnFlash:hover {{
            background: #FFE3C2; color: #222; border-color: #FFA74B;
        }}
        QToolButton#btnFlash[checked="true"]:hover {{
            background: #FFA74B; color: #222; border-color: #FFA74B;
        }}

        /* Панель быстрых фильтров + перемычка */
        QFrame#quickFiltersPanel {{
            background: #FFFFFF; border: 1px solid #FFA74B; padding: 0px; border-radius: 8px; /* скругление сверху и снизу */
        }}
        #qfConnector {{ background: #FFA74B; border: none; border-radius: 999px; }}

        /* Белая карточка диалогов свойств */
        /* Диалоги */
        QDialog {{ background: #FFFFFF; }}
        QWidget#propsCard {{ background: #FFFFFF; border: 1px solid #dcdcdc; border-radius: 12px; }}
        QWidget#propsCard QLabel {{ color: #222; }}
        QWidget#propsCard QDialogButtonBox {{ border-top: 1px solid #eeeeee; padding-top: 8px; }}

        QMessageBox {{ background: #FFFFFF; }}      /* по стилю, опционально */

        
        /* ндикатор прогресса */
        QProgressBar {{ text-align: center; border: 1px solid #dcdcdc; border-radius: 8px; background: #FFF; }}
        QProgressBar::chunk {{ background-color: #FFB347; border-radius: 8px; }}
        
        /* Календарь и DateEdit */
        QDateEdit {{
            background: #FFFFFF;
            color: #222;
            border: 1px solid #dcdcdc;
            border-radius: 8px;
            padding: 4px 10px;
        }}
        QDateEdit::drop-down {{
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 22px;
            border-left: 1px solid #dcdcdc;
            background: #FFFFFF;
            border-top-right-radius: 8px;
            border-bottom-right-radius: 8px;
        }}
        QDateEdit::down-arrow {{
            image: url("{{DOWN_ARROW_ICON_PATH}}");
            width: 12px; height: 12px;
        }}


        /* ===================== QCalendarWidget ===================== */

        /* Корневой виджет календаря */
        QCalendarWidget {{
            background: #FFFFFF;                 /* белый фон */
            border: 1px solid #dcdcdc;
            border-radius: 12px;
        }}

        /* Верхняя панель навигации */
        QCalendarWidget QWidget#qt_calendar_navigationbar {{
            background: #FFFFFF;                 /* тоже белая */
            border-bottom: 1px solid #dcdcdc;
            padding: 6px 8px;
        }}

        /* Кнопки "Месяц" и "Год" в шапке */
        QCalendarWidget QToolButton#qt_calendar_monthbutton,
        QCalendarWidget QToolButton#qt_calendar_yearbutton {{
            background: transparent;
            color: #222;
            border: 1px solid transparent;
            border-radius: 12px;
            padding: 4px 10px;
            font-weight: 600;
        }}
        /* Ховер как у кнопки "Скачать" - мягкий серый */
        /* Ховер и нажатие - как у вторичных кнопок ("Настройки") */
        QCalendarWidget QToolButton#qt_calendar_monthbutton:hover,
        QCalendarWidget QToolButton#qt_calendar_yearbutton:hover {{
            background: #FFE3C2;
            border-color: #FFA74B;
        }}
        QCalendarWidget QToolButton#qt_calendar_monthbutton:pressed,
        QCalendarWidget QToolButton#qt_calendar_yearbutton:pressed {{
            background: #FFC37A;
            border-color: #E07E12;
        }}


        /* Таблица дней */
        QCalendarWidget QAbstractItemView {{
            background: #FFFFFF;                 /* белое поле дней */
            outline: none;
            gridline-color: transparent;
            selection-background-color: #F7921E;
            selection-color: #fff;
            qproperty-textElideMode: ElideNone;  /* без "..." вместо чисел */
        }}
        QCalendarWidget QAbstractItemView::item {{
            padding: 2px;                        /* перекрываем глобальные большие паддинги */
        }}

        
        /* Ховер/выделение ячеек дней как у «Настроек» */
        QCalendarWidget QAbstractItemView::item:hover {{
            background: rgba(247, 146, 30, 0.10);
            color: #000000;
            border: 1px solid #FFA74B;
            border-radius: 6px;
        }}

        QCalendarWidget QAbstractItemView::item:selected {{
            background: rgba(247, 146, 30, 0.20);
            color: #000000;
            border: 1px solid #E07E12;
            border-radius: 6px;
        }}

        /* Заголовки дней недели */
        QCalendarWidget QTableView QHeaderView::section {{
            background: #FFFFFF;
            color: #888;
            border: none;
            padding: 4px 0;
            font-weight: 600;
        }}


        /* Подсветка всей правой области таблицы, когда курсор с файлами над пустой зоной */
        QTableView#filesTable[dropHoverEmpty="true"] {{
            background: #FFE8D1;
        }}
        QTableView#filesTable[dropHoverEmpty="true"]::viewport {{
            background: #FFE8D1;
        }}
        /* Красим и строки, чтобы не было «белых полос» между ними */
        QTableView#filesTable[dropHoverEmpty="true"]::item {{
            background: #FFE8D1;
        }}
        /* Выбранная строка остаётся чуть темнее поверх общей подсветки */
        QTableView#filesTable[dropHoverEmpty="true"]::item:selected {{
            background: #FFC37A;
        }}

        /* --------- Стрелки навигации (месяц/год) --------- */
        QCalendarWidget QToolButton#qt_calendar_prevmonth,
        QCalendarWidget QToolButton#qt_calendar_nextmonth,
        QCalendarWidget QToolButton#qt_calendar_prevyear,
        QCalendarWidget QToolButton#qt_calendar_nextyear {{
            background: transparent;
            border: none;
            padding: 0;
            margin: 0 4px;
            min-width: 24px;  max-width: 24px;
            min-height: 24px; max-height: 24px;
            qproperty-iconSize: 16px 16px;
        }}

        /* Только наши PNG - системные стрелки выключены */
        QCalendarWidget QToolButton#qt_calendar_prevmonth {{
            qproperty-arrowType: NoArrow;
            qproperty-icon: url("{{ARROW_LEFT_ICON_PATH}}");
        }}
        QCalendarWidget QToolButton#qt_calendar_nextmonth {{
            qproperty-arrowType: NoArrow;
            qproperty-icon: url("{{ARROW_RIGHT_ICON_PATH}}");
        }}
        QCalendarWidget QToolButton#qt_calendar_prevyear {{
            qproperty-arrowType: NoArrow;
            qproperty-icon: url("{{ARROW_LEFT_ICON_PATH}}");
        }}
        QCalendarWidget QToolButton#qt_calendar_nextyear {{
            qproperty-arrowType: NoArrow;
            qproperty-icon: url("{{ARROW_RIGHT_ICON_PATH}}");
        }}

        /* Ховер по стрелкам - как у "Скачать" */
        QCalendarWidget QToolButton#qt_calendar_prevmonth:hover,
        QCalendarWidget QToolButton#qt_calendar_nextmonth:hover,
        QCalendarWidget QToolButton#qt_calendar_prevyear:hover,
        QCalendarWidget QToolButton#qt_calendar_nextyear:hover {{
            background: rgba(0,0,0,0.06);
            border-radius: 12px;
        }}

        /* ===================== DROPDOWNS (Menus & Combo popups) ===================== */

        /* QMenu — фон и отделка */
        QMenu {{
            background: #FFFFFF;
            border: 1px solid #dcdcdc;
            border-radius: 12px;
            padding: 6px 0;
        }}
        QMenu::separator {{
            height: 1px;
            background: #e6e6e6;
            margin: 6px 8px;
        }}
        /* Пункты меню: hover/pressed как у "Настройки" */
        QMenu::item {{
            color: #222;
            padding: 6px 12px;
            margin: 2px 6px;
            border: 1px solid transparent;
            border-radius: 8px;
        }}
        QMenu::item:selected,
        QMenu::item:hover {{
            background: #FFE3C2;            /* hover = как у "Настройки" */
            border-color: #FFA74B;
            color: #000000;
        }}
        QMenu::item:pressed {{
            background: #FFC37A;            /* pressed = как у "Настройки" */
            border-color: #E07E12;
            color: #000000;
        }}
        QMenu#popupMenu::right-arrow {{ image: url("{{ARROW_RIGHT_ICON_PATH}}"); width: 12px; height: 12px; }}
    QMenu#popupMenu::left-arrow  {{ image: url("{{ARROW_LEFT_ICON_PATH}}");  width: 12px; height: 12px; }}
    QMenu#columnsMenu::right-arrow {{ image: url("{{ARROW_RIGHT_ICON_PATH}}"); width: 12px; height: 12px; }}
    QMenu#columnsMenu::left-arrow  {{ image: url("{{ARROW_LEFT_ICON_PATH}}");  width: 12px; height: 12px; }}


        /* ===== Ховер пунктов меню фильтров заголовка (как у «Настройки») ===== */
        QMenu#nikHeaderMenu {{
            background: #FFFFFF;
            border: 1px solid #dcdcdc;
            border-radius: 12px;
            padding: 6px 0;
        }}
        QMenu#nikHeaderMenu::separator {{
            height: 1px;
            background: #e6e6e6;
            margin: 6px 8px;
        }}
        QMenu#nikHeaderMenu::item {{
            color: #000000;
            padding: 6px 12px;
            margin: 2px 6px;
            border: 1px solid transparent;
            border-radius: 8px;
            background: transparent;
        }}
        /* hover/selected — мягкий, как у «Настройки» */
        QMenu#nikHeaderMenu::item:selected,
        QMenu#nikHeaderMenu::item:hover {{
            background: #FFE3C2;
            border-color: #FFA74B;
            color: #000000;
        }}
        /* pressed — как у «Настройки» при нажатии */
        QMenu#nikHeaderMenu::item:pressed {{
            background: #FFC37A;
            border-color: #E07E12;
            color: #000000;
        }}


        /* Пункты фильтров в header-меню как обычные элементы с галочкой */
        QMenu#nikHeaderMenu QCheckBox[menuitem="true"] {{
            color: #222;
            padding: 6px 12px;
            margin: 2px 6px;
            border: 1px solid transparent;
            border-radius: 8px;
            background: transparent;
        }}
        QMenu#nikHeaderMenu QCheckBox[menuitem="true"]:hover {{
            background: #FFE3C2;
            border-color: #FFA74B;
            color: #000000;
        }}
        /* прячем квадратный индикатор чекбокса */
        QMenu#nikHeaderMenu QCheckBox[menuitem="true"]::indicator {{
            width: 0px; height: 0px;
        }}


        /* QComboBox — сам виджет */
        QComboBox {{
            background: #FFFFFF;
            color: #222;
            border: 1px solid #dcdcdc;
            border-radius: 12px;
            padding: 4px 10px;
        }}
        /* По желанию: ховер самого комбобокса */
        QComboBox:hover,
        QComboBox:!editable:on {{
            background: #FFE3C2;
            border-color: #dcdcdc;
            color: #000000;
        }}

        /* Popup-список QComboBox (рамка вокруг всего списка) */
        QFrame#qt_combobox_popup,
        QComboBoxPrivateContainer {
            background: #FFFFFF;
            border: 1px solid #FFA74B;
            border-radius: 12px;
            padding: 0px;
        }
        QFrame#qt_combobox_popup QAbstractItemView,
        QComboBoxPrivateContainer QAbstractItemView {
            /* рамка на контейнере, внутри без рамки */
            border: none;
            background: #FFFFFF;
            outline: none;
            selection-background-color: transparent;
            selection-color: #000000;
        }
        /* Fallback: keep solid background; no extra border (border is on popup container). */
        QComboBox QAbstractItemView {{
            background: #FFFFFF;
            outline: none;
            border: none;
            selection-background-color: transparent;
            selection-color: #000000;
        }}
        QComboBox QAbstractItemView::viewport {{
            background: #FFFFFF;
            border: none;
        }}
        QComboBox QAbstractItemView::item {{
            padding: 6px 10px;
            border: 1px solid transparent;
            border-radius: 6px;
            margin: 2px;
        }}
        QComboBox QAbstractItemView::item:hover {{
            background: #FFE3C2;
            border-color: #FFA74B;
            color: #000000;
        }}
        QComboBox QAbstractItemView::item:selected {{
            /* подсветка выбранной строки как у кнопки (не плотная заливка) */
            background: rgba(247, 146, 30, 0.10);
            border-color: #FFA74B;
            color: #000000;
        }}
        QComboBox QAbstractItemView::item:selected:hover {{
            background: rgba(247, 146, 30, 0.20);
            border-color: #E07E12;
            color: #000000;
        }}

        /* (Опционально) Скрыть стрелку у ComboBox, если хочешь без "треугольника" */
        /*
        QComboBox::down-arrow {{ image: none; }}
        QComboBox::drop-down  {{ width: 0px; border: none; }}
        */

        /* Enable explicit down-arrow icon for comboboxes */
        QComboBox::down-arrow {{
            image: url("{{DOWN_ARROW_ICON_PATH}}");
            width: 12px;
            height: 12px;
            margin: 0;
            background: transparent;
            border: none;
        }}
        QComboBox::drop-down  {{ width: 18px; border: none; background: transparent; }}

        /* (keep default branch indicators; recolor handled by proxy style) */


        /* Кнопка-глазик в Login диалоге */
        QToolButton#pw_eye {{ background: transparent; border: none; padding: 0; }}

        /* Кнопки-"таблетки": уведомления и "без папок" */
        QToolButton#btnNotify, QToolButton#btnNoFolders {{ background: transparent; border: 1px solid #dcdcdc; border-radius: 12px; padding: 4px 8px; }}
        QToolButton#btnNotify:hover, QToolButton#btnNoFolders:hover {{ background: rgba(247, 146, 30, 0.1); border-color: #FFA74B; }}
        QToolButton#btnNotify:pressed, QToolButton#btnNoFolders:pressed {{ background: rgba(247, 146, 30, 0.2); border-color: #E07E12; }}
        QToolButton#btnNoFolders:checked {{ background: rgba(247, 146, 30, 0.2); border-color: #FFA74B; }}

        /* Кнопка с именем пользователя */
        QToolButton#btnUser {{ background: #FFFFFF; color: #000000; border: 1px solid #dcdcdc; border-radius: 14px; padding: 6px 12px; font-weight: 600; }}
        QToolButton#btnUser:hover {{ background: #FFE3C2; border-color: #FFA74B; }}
        QToolButton#btnUser:pressed {{ background: #FFC37A; }}

        /* Убираем системные «стрелки вниз» у всех кнопок с меню */
        QToolButton {{
            qproperty-arrowType: NoArrow;   /* на всякий случай отключим любые встроенные стрелки */
        }}
        QToolButton::menu-indicator {{
            image: none;
            width: 0px;
            height: 0px;
            margin: 0;
            padding: 0;
            subcontrol-origin: padding;
            subcontrol-position: right center;
        }}
        QPushButton::menu-indicator {{
            image: none;
            width: 0px;
            height: 0px;
            margin: 0;
            padding: 0;
            subcontrol-origin: padding;
            subcontrol-position: right center;
        }}
            
        QTreeWidget#docsTree::item:hover,
        QTreeView#docsTree::item:hover { background: transparent; }
        QTreeWidget#docsTree::item:selected,
        QTreeView#docsTree::item:selected { background: transparent; color: inherit; }

        /* Чипы DOCX/PDF/JPG/CAD/«Без папок» — один стиль, углы всегда круглые */
        QFrame#quickFiltersPanel QPushButton#chipButton,
        QPushButton#chipButton,
        QFrame#quickFiltersPanel QPushButton[class="tag"],
        QPushButton[class="tag"],
        QPushButton[chip="true"],
        QFrame#quickFiltersPanel QToolButton#chipButton,
        QToolButton#chipButton,
        QFrame#quickFiltersPanel QToolButton[class="tag"],
        QToolButton[class="tag"],
        QToolButton[chip="true"] {{
            background: #FFF;
            color: #222;
            border-width: 1px;
            border-style: solid;
            border-color: #dcdcdc;
            border-top-left-radius: 16px;
            border-top-right-radius: 16px;
            border-bottom-right-radius: 16px;
            border-bottom-left-radius: 16px;
            padding: 8px 20px;
            min-height: 32px;
            font-weight: 600;
            font-size: 13px;
            border-image: none;
        }}

        QFrame#quickFiltersPanel QPushButton#chipButton:hover,
        QPushButton#chipButton:hover,
        QFrame#quickFiltersPanel QPushButton[class="tag"]:hover,
        QPushButton[class="tag"]:hover,
        QPushButton[chip="true"]:hover,
        QFrame#quickFiltersPanel QToolButton#chipButton:hover,
        QToolButton#chipButton:hover,
        QFrame#quickFiltersPanel QToolButton[class="tag"]:hover,
        QToolButton[class="tag"]:hover,
        QToolButton[chip="true"]:hover {{
            background: #FFE3C2;
            border-style: solid;
            border-color: #FFA74B;
            border-top-left-radius: 16px;
            border-top-right-radius: 16px;
            border-bottom-right-radius: 16px;
            border-bottom-left-radius: 16px;
            padding: 8px 20px;
            min-height: 32px;
            color: #222;
            border-image: none;
        }}

        QFrame#quickFiltersPanel QPushButton#chipButton:pressed,
        QPushButton#chipButton:pressed,
        QFrame#quickFiltersPanel QPushButton[class="tag"]:pressed,
        QPushButton[class="tag"]:pressed,
        QPushButton[chip="true"]:pressed,
        QFrame#quickFiltersPanel QToolButton#chipButton:pressed,
        QToolButton#chipButton:pressed,
        QFrame#quickFiltersPanel QToolButton[class="tag"]:pressed,
        QToolButton[class="tag"]:pressed,
        QToolButton[chip="true"]:pressed {{
            background: #FFC37A;
            border-style: solid;
            border-color: #E07E12;
            border-top-left-radius: 16px;
            border-top-right-radius: 16px;
            border-bottom-right-radius: 16px;
            border-bottom-left-radius: 16px;
            padding: 8px 20px;
            min-height: 32px;
            color: #222;
            border-image: none;
        }}

        QFrame#quickFiltersPanel QPushButton#chipButton:checked,
        QPushButton#chipButton:checked,
        QFrame#quickFiltersPanel QPushButton[class="tag"]:checked,
        QPushButton[class="tag"]:checked,
        QPushButton[chip="true"]:checked,
        QFrame#quickFiltersPanel QToolButton#chipButton:checked,
        QToolButton#chipButton:checked,
        QFrame#quickFiltersPanel QToolButton[class="tag"]:checked,
        QToolButton[class="tag"]:checked,
        QToolButton[chip="true"]:checked {{
            background: #F7921E;
            border-style: solid;
            border-color: #F7921E;
            border-top-left-radius: 16px;
            border-top-right-radius: 16px;
            border-bottom-right-radius: 16px;
            border-bottom-left-radius: 16px;
            padding: 8px 20px;
            min-height: 32px;
            color: #FFF;
            border-image: none;
        }}

        QFrame#quickFiltersPanel QPushButton#chipButton:checked:hover,
        QPushButton#chipButton:checked:hover,
        QFrame#quickFiltersPanel QPushButton[class="tag"]:checked:hover,
        QPushButton[class="tag"]:checked:hover,
        QPushButton[chip="true"]:checked:hover,
        QFrame#quickFiltersPanel QToolButton#chipButton:checked:hover,
        QToolButton#chipButton:checked:hover,
        QFrame#quickFiltersPanel QToolButton[class="tag"]:checked:hover,
        QToolButton[class="tag"]:checked:hover,
        QToolButton[chip="true"]:checked:hover {{
            background: #FFE3C2;
            border-style: solid;
            border-color: #FFA74B;
            border-top-left-radius: 16px;
            border-top-right-radius: 16px;
            border-bottom-right-radius: 16px;
            border-bottom-left-radius: 16px;
            padding: 8px 20px;
            min-height: 32px;
            color: #222;
            border-image: none;
        }}

        QFrame#quickFiltersPanel QPushButton#chipButton:disabled,
        QPushButton#chipButton:disabled,
        QFrame#quickFiltersPanel QPushButton[class="tag"]:disabled,
        QPushButton[class="tag"]:disabled,
        QPushButton[chip="true"]:disabled,
        QFrame#quickFiltersPanel QToolButton#chipButton:disabled,
        QToolButton#chipButton:disabled,
        QFrame#quickFiltersPanel QToolButton[class="tag"]:disabled,
        QToolButton[class="tag"]:disabled,
        QToolButton[chip="true"]:disabled {{
            background: #f0f0f0;
            color: #9b9b9b;
            border-style: solid;
            border-color: #e6e6e6;
            border-top-left-radius: 16px;
            border-top-right-radius: 16px;
            border-bottom-right-radius: 16px;
            border-bottom-left-radius: 16px;
            padding: 8px 20px;
            min-height: 32px;
            border-image: none;
        }}
        /* Замок скруглений на все состояния chipButton */
        QPushButton#chipButton,
        QPushButton#chipButton:hover,
        QPushButton#chipButton:pressed,
        QPushButton#chipButton:checked,
        QPushButton#chipButton:checked:hover {{
            border-top-left-radius: 12px;
            border-top-right-radius: 12px;
            border-bottom-right-radius: 12px;
            border-bottom-left-radius: 12px;
            border-image: none;
        }}
        QToolButton#chipButton,
        QToolButton#chipButton:hover,
        QToolButton#chipButton:pressed,
        QToolButton#chipButton:checked,
        QToolButton#chipButton:checked:hover {{
            border-top-left-radius: 12px;
            border-top-right-radius: 12px;
            border-bottom-right-radius: 12px;
            border-bottom-left-radius: 12px;
            border-image: none;
        }}

        QHeaderView::section {{ padding: 6px 22px 6px 8px; }}
        /* Заголовок таблицы: делаем место под стрелку */
        QTableView QHeaderView {{
            background: transparent;
            border: none;
        }}
        QTableView QHeaderView::section {{
        background: #FFFFFF;
        border: none;
        border-right: none;
        border-left: none;
        margin: 0;
        padding: 6px 10px 6px 8px;   /* top right bottom left: слева 8px - как у ячеек, справа 22px - под стрелку/иконку */
        }}
        /* Подсветка секции заголовка со скруглениями */
        QHeaderView::section:hover   {{ 
            background: #FFE3C2; 
            border: none;
            border-radius: 8px;
        }}
        QHeaderView::section:pressed {{ 
            background: #FFC37A; 
            border: none;
            border-radius: 8px;
        }}

        /* Стрелки сортировки в заголовке */
        QHeaderView::up-arrow {{
            image: url("{SORT_ICON_UP_PATH}");
            width: 12px; height: 12px;
            subcontrol-origin: padding;
            subcontrol-position: right center;
            right: 1px;
            margin: 0;
            background: transparent;
        }}
        QHeaderView::down-arrow {{
            image: url("{SORT_ICON_DOWN_PATH}");
            width: 12px; height: 12px;
            subcontrol-origin: padding;
            subcontrol-position: right center;
            right: 1px;
            margin: 0;
            background: transparent;
        }}
        /* Кнопка "глубокий поиск" внутри поля поиска */
        QToolButton#searchDeepBtn {{
            background: transparent;
            border: none;
            padding: 0 4px;        /* узкая «таблетка» вокруг иконки */
            margin: 0;
            min-width: 0;
            min-height: 0;
            border-radius: 6px;
         }}
        /* загорается ТОЛЬКО когда включена */
        QToolButton#searchDeepBtn:checked {{
            background: #FFE3C2;
            border: 1px solid #FFA74B;
         }}
        /* мягкий hover без включения */
        QToolButton#searchDeepBtn:hover{{
            background: #FFF0DC;
         }}

        /* Чекбоксы в меню фильтрации заголовка */
        QMenu#nikHeaderMenu QCheckBox[menuitem=\"true\"] {{
            color: #222;
            background: transparent;
            border: 1px solid transparent;
            border-radius: 8px;
            padding: 6px 12px;
        }}
        QMenu#nikHeaderMenu QCheckBox[menuitem=\"true\"]:hover {{
            color: #000;
            background: #FFE3C2;
            border-color: #FFA74B;
        }}
        QMenu#nikHeaderMenu QCheckBox[menuitem=\"true\"]:checked {{
            color: #000;
            background: #FFC37A;
            border-color: #E07E12;
        }}
        QMenu#nikHeaderMenu QCheckBox[menuitem=\"true\"]::indicator {{
            width: 0px;
            height: 0px;
        }}


    """ 
    )
    # Подменяем пути к иконкам — поддерживаем варианты с двойными/одинарными/квадрупльными скобками,
    # чтобы не зависеть от того, была ли QSS записана как f-string ранее.
    repl_left = (left_arrow or "").replace("\\", "/")
    repl_right = (ARROW_RIGHT_ICON_PATH or "").replace("\\", "/")
    repl_down = (DOWN_ARROW_ICON_PATH or "").replace("\\", "/")
    repl_sort_up = (SORT_ICON_UP_PATH or "").replace("\\", "/")
    repl_sort_down = (SORT_ICON_DOWN_PATH or "").replace("\\", "/")

    replacements = {
        # left arrow
        "{{ARROW_LEFT_ICON_PATH}}": repl_left,
        "{ARROW_LEFT_ICON_PATH}": repl_left,
        "{{{{ARROW_LEFT_ICON_PATH}}}}": repl_left,
        # right arrow
        "{{ARROW_RIGHT_ICON_PATH}}": repl_right,
        "{ARROW_RIGHT_ICON_PATH}": repl_right,
        "{{{{ARROW_RIGHT_ICON_PATH}}}}": repl_right,
        # down arrow
        "{{DOWN_ARROW_ICON_PATH}}": repl_down,
        "{DOWN_ARROW_ICON_PATH}": repl_down,
        "{{{{DOWN_ARROW_ICON_PATH}}}}": repl_down,
        # sort icons
        "{SORT_ICON_UP_PATH}": repl_sort_up,
        "{{SORT_ICON_UP_PATH}}": repl_sort_up,
        "{SORT_ICON_DOWN_PATH}": repl_sort_down,
        "{{SORT_ICON_DOWN_PATH}}": repl_sort_down,
    }

    for k, v in replacements.items():
        style = style.replace(k, v)

        # Финальная нормализация скобок: {{ → {, }} → } (после всех замен)
        style = style.replace("{{", "{").replace("}}", "}")


    # --- Image-based checkbox indicators (PNG) ---
    try:
        # Use explicit paths; dark-theme pass will swap to white variants if needed
        style += f"""
        /* Checkboxes with PNG indicators */
        QCheckBox {{ padding: 2px; }}
        QCheckBox::indicator {{ width: 18px; height: 18px; }}
        QCheckBox::indicator:unchecked {{ image: url("{CHECK_ICON_OFF_PATH}"); }}
        QCheckBox::indicator:checked   {{ image: url("{CHECK_ICON_ON_PATH}"); }}
        QCheckBox::indicator:indeterminate {{ image: url("{CHECK_ICON_MID_PATH}"); }}

        /* Round checkbox style via property round=true */
        QCheckBox[round="true"]::indicator {{ width: 18px; height: 18px; }}
        QCheckBox[round="true"]::indicator:unchecked {{ image: url("{RCHECK_ICON_OFF_PATH}"); }}
        QCheckBox[round="true"]::indicator:checked   {{ image: url("{RCHECK_ICON_ON_PATH}"); }}
        QCheckBox[round="true"]::indicator:indeterminate {{ image: url("{RCHECK_ICON_ON_PATH}"); }}

        /* Also use same indicators for QListView/QListWidget item checkstates */
        QListView::indicator, QListWidget::indicator {{ width: 18px; height: 18px; }}
        QListView::indicator:unchecked, QListWidget::indicator:unchecked {{ image: url("{CHECK_ICON_OFF_PATH}"); }}
        QListView::indicator:checked,   QListWidget::indicator:checked   {{ image: url("{CHECK_ICON_ON_PATH}"); }}
        QListView::indicator:indeterminate, QListWidget::indicator:indeterminate {{ image: url("{CHECK_ICON_MID_PATH}"); }}
        QListView::indicator:hover, QListWidget::indicator:hover {{ background: transparent; border-radius: 0; }}
        QCheckBox::indicator:hover {{ background: transparent; border-radius: 0; }}
        """
    except Exception:
        pass



    # Добавим стили для стрелок QSpinBox (иконки + ховеры без рамок)
    try:
        _up = repl_sort_up
        _dn = repl_sort_down
        style += f"""
        QSpinBox::up-button, QSpinBox::down-button {{
            background: transparent; border: none; margin: 0; padding: 0; width: 16px;
        }}
        QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
            background: #FFE3C2; border: 1px solid #FFA74B; border-radius: 6px;
        }}
        QSpinBox::up-button:pressed, QSpinBox::down-button:pressed {{
            background: #ffca91; border: 1px solid #FFA74B; border-radius: 6px;
        }}
        QSpinBox::up-arrow {{ image: url("{_up}"); width: 12px; height: 12px; }}
        QSpinBox::down-arrow {{ image: url("{_dn}"); width: 12px; height: 12px; }}
        """
    except Exception:
        pass

    # Regression-like runtime checks (no external tests): ensure placeholders were replaced
    try:
        def _extract_url(regex_pat: str) -> str | None:
            m = re.search(regex_pat, style, flags=re.S)
            if not m:
                return None
            return (m.group(1) or "").strip()

        checks = [
            (r'QScrollBar::left-arrow:horizontal[^}]*url\(["\']?([^"\')]+)["\']?\)', 'ARROW_LEFT_ICON_PATH'),
            (r'QScrollBar::right-arrow:horizontal[^}]*url\(["\']?([^"\')]+)["\']?\)', 'ARROW_RIGHT_ICON_PATH'),
            (r'QComboBox::down-arrow[^}]*url\(["\']?([^"\')]+)["\']?\)', 'DOWN_ARROW_ICON_PATH'),
            (r'QCalendarWidget[^}]*QToolButton#qt_calendar_prevmonth[^}]*url\(["\']?([^"\')]+)["\']?\)', 'ARROW_LEFT_ICON_PATH'),
        ]


        for patt, name in checks:
            url = _extract_url(patt)
            assert url is not None and url != '' , f"Missing icon url for {name} in light QSS"
            assert '{' not in url and 'ARROW_LEFT_ICON_PATH' not in url and 'ARROW_RIGHT_ICON_PATH' not in url and 'DOWN_ARROW_ICON_PATH' not in url, f"Placeholder not replaced for {name}: {url}"
            # Prefer png icons
            assert url.lower().endswith('.png'), f"Icon for {name} doesn't look like PNG: {url}"
    except AssertionError:
        # Surface regression info — raise so developer notices during development runs
        raise

    # Do not set the app stylesheet here — return the built QSS so callers
    # (apply_light_theme/apply_dark_theme) can apply it in a safe, ordered way.
    def _apply_cal_one_month_only(cal: QCalendarWidget, year: int | None = None, month: int | None = None):
        def _dow(v):
            try:
                return int(getattr(v, 'value', v))
            except Exception:
                return 1  # Monday
        try:
            if year is None or month is None:
                try:
                    year = cal.yearShown()  # type: ignore[attr-defined]
                    month = cal.monthShown()  # type: ignore[attr-defined]
                except Exception:
                    d = cal.selectedDate()
                    year, month = int(d.year()), int(d.month())
            year = int(year) if year is not None else QDate.currentDate().year()
            month = int(month) if month is not None else QDate.currentDate().month()

            # Determine first visible date in the 6x7 grid
            first_day = QDate(year, month, 1)
            try:
                fdow = _dow(cal.firstDayOfWeek())
            except Exception:
                fdow = 1
            shift = (first_day.dayOfWeek() - fdow + 7) % 7
            grid_start = first_day.addDays(-shift)

            # Prepare formats
            fmt_hide = QTextCharFormat()
            try:
                # Hide numbers and any background for out-of-month days
                transparent = QBrush(QColor(0, 0, 0, 0))
                fmt_hide.setForeground(transparent)
                fmt_hide.setBackground(transparent)
            except Exception:
                pass
            fmt_show = QTextCharFormat()  # default resets formatting

            # Apply to 42 cells (6 weeks)
            for i in range(42):
                d = grid_start.addDays(i)
                if d.month() != month:
                    cal.setDateTextFormat(d, fmt_hide)
                else:
                    cal.setDateTextFormat(d, fmt_show)
        except Exception:
            pass

    def _enable_one_month_only(cal: QCalendarWidget):
        try:
            # Initial apply
            _apply_cal_one_month_only(cal)
            # Update on page change using a QObject slot (no lambda) to avoid connect warnings
            try:
                if not getattr(cal, "_nik_one_month_connected", False):
                    if not hasattr(cal, "_nik_one_month_enforcer"):
                        class _OneMonthEnforcer(QObject):
                            @Slot(int, int)
                            def on_page(self, y, m):
                                try:
                                    _apply_cal_one_month_only(cal, y, m)
                                except Exception:
                                    pass
                        # keep reference on the calendar to avoid GC
                        cal._nik_one_month_enforcer = _OneMonthEnforcer(cal)
                    try:
                        cal.currentPageChanged.connect(cal._nik_one_month_enforcer.on_page)
                    except TypeError:
                        # Fallback to lambda if needed (older bindings)
                        cal.currentPageChanged.connect(lambda y, m, c=cal: _apply_cal_one_month_only(c, y, m))
                    cal._nik_one_month_connected = True
            except Exception:
                pass
        except Exception:
            pass

    class _OneMonthDelegate(QStyledItemDelegate):
        def __init__(self, cal):
            super().__init__(cal)
            self.cal = cal
        def paint(self, painter, option, index):
            try:
                y = int(self.cal.yearShown())
                m = int(self.cal.monthShown())
            except Exception:
                d = self.cal.selectedDate(); y, m = int(d.year()), int(d.month())
            first_day = QDate(y, m, 1)
            try:
                fdow = int(getattr(self.cal.firstDayOfWeek(), 'value', self.cal.firstDayOfWeek()))
            except Exception:
                fdow = 1
            shift = (first_day.dayOfWeek() - fdow + 7) % 7
            grid_start = first_day.addDays(-shift)
            idx = index
            try:
                r, c = idx.row(), idx.column()
            except Exception:
                r, c = 0, 0
            d = grid_start.addDays(r * 7 + c)
            if d.month() != m:
                painter.save()
                painter.fillRect(option.rect, option.palette.base())
                painter.restore()
                return
            return super().paint(painter, option, index)

    class _OneMonthClickBlocker(QObject):
        def __init__(self, cal, view):
            super().__init__(view)
            self.cal = cal
            self.view = view
        def eventFilter(self, obj, ev):
            try:
                if obj is self.view.viewport() and ev.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick):
                    try:
                        y = int(self.cal.yearShown()); m = int(self.cal.monthShown())
                    except Exception:
                        d = self.cal.selectedDate(); y, m = int(d.year()), int(d.month())
                    first_day = QDate(y, m, 1)
                    try:
                        fdow = int(getattr(self.cal.firstDayOfWeek(), 'value', self.cal.firstDayOfWeek()))
                    except Exception:
                        fdow = 1
                    shift = (first_day.dayOfWeek() - fdow + 7) % 7
                    grid_start = first_day.addDays(-shift)
                    idx = self.view.indexAt(ev.pos())
                    if idx.isValid():
                        r, c = idx.row(), idx.column()
                        d = grid_start.addDays(r * 7 + c)
                        if d.month() != m:
                            return True
            except Exception:
                pass
            return False

    def _prep_cal_hover(cal: QCalendarWidget):
        view = cal.findChild(QTableView, "qt_calendar_calendarview")
        if view:
            # Ensure weekday header shows Monday..Sunday with short names
            try:
                cal.setFirstDayOfWeek(Qt.Monday)
            except Exception:
                pass
            try:
                cal.setHorizontalHeaderFormat(QCalendarWidget.ShortDayNames)
            except Exception:
                pass
            try:
                # Hide week numbers to keep header compact and fully visible
                cal.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
            except Exception:
                pass

            view.setMouseTracking(True)
            view.viewport().setMouseTracking(True)

        # Reset any custom date formats so the month grid shows all dates
        try:
            try:
                year = int(cal.yearShown())
                month = int(cal.monthShown())
            except Exception:
                d = cal.selectedDate()
                year, month = int(d.year()), int(d.month())
            first_day = QDate(year, month, 1)
            try:
                fd = cal.firstDayOfWeek()
                fdow = int(getattr(fd, "value", fd))
            except Exception:
                fdow = 1
            shift = (first_day.dayOfWeek() - fdow + 7) % 7
            grid_start = first_day.addDays(-shift)
            fmt_reset = QTextCharFormat()
            for i in range(42):
                cal.setDateTextFormat(grid_start.addDays(i), fmt_reset)
        except Exception:
            pass

    # пропатчить уже существующие календари
    for w in app.allWidgets():
        if isinstance(w, QCalendarWidget):
            _prep_cal_hover(w)

    # и все, что создадутся позже (например, в попапе фильтра)
    class _CalHoverWatcher(QObject):
        def eventFilter(self, obj, ev):
            if isinstance(obj, QCalendarWidget) and ev.type() == QEvent.Show:
                _prep_cal_hover(obj)
            return False

    _cal_hover_watcher = _CalHoverWatcher(app)
    app.installEventFilter(_cal_hover_watcher)
    app._nik_cal_hover_watcher = _cal_hover_watcher  # не дать сборщику мусора убрать
    LIGHT_THEME_QSS = style
    return style

    # Regression-like runtime checks (no external tests): ensure placeholders were replaced
    try:
        def _extract_url(regex_pat: str) -> str | None:
            m = re.search(regex_pat, style, flags=re.S)
            if not m:
                return None
            return (m.group(1) or "").strip()

        checks = [
            (r'QScrollBar::left-arrow:horizontal[^}]*url\(["\']?([^"\')]+)["\']?\)', 'ARROW_LEFT_ICON_PATH'),
            (r'QScrollBar::right-arrow:horizontal[^}]*url\(["\']?([^"\')]+)["\']?\)', 'ARROW_RIGHT_ICON_PATH'),
            (r'QComboBox::down-arrow[^}]*url\(["\']?([^"\')]+)["\']?\)', 'DOWN_ARROW_ICON_PATH'),
            (r'QCalendarWidget[^}]*QToolButton#qt_calendar_prevmonth[^}]*url\(["\']?([^"\')]+)["\']?\)', 'ARROW_LEFT_ICON_PATH'),
        ]


        for patt, name in checks:
            url = _extract_url(patt)
            assert url is not None and url != '' , f"Missing icon url for {name} in light QSS"
            assert '{' not in url and 'ARROW_LEFT_ICON_PATH' not in url and 'ARROW_RIGHT_ICON_PATH' not in url and 'DOWN_ARROW_ICON_PATH' not in url, f"Placeholder not replaced for {name}: {url}"
            # Prefer png icons
            assert url.lower().endswith('.png'), f"Icon for {name} doesn't look like PNG: {url}"
    except AssertionError:
        # Surface regression info — raise so developer notices during development runs
        raise

    # Do not set the app stylesheet here — return the built QSS so callers
    # (apply_light_theme/apply_dark_theme) can apply it in a safe, ordered way.
    def _apply_cal_one_month_only(cal: QCalendarWidget, year: int | None = None, month: int | None = None):
        def _dow(v):
            try:
                return int(getattr(v, 'value', v))
            except Exception:
                return 1  # Monday
        try:
            if year is None or month is None:
                try:
                    year = cal.yearShown()  # type: ignore[attr-defined]
                    month = cal.monthShown()  # type: ignore[attr-defined]
                except Exception:
                    d = cal.selectedDate()
                    year, month = int(d.year()), int(d.month())
            year = int(year) if year is not None else QDate.currentDate().year()
            month = int(month) if month is not None else QDate.currentDate().month()

            # Determine first visible date in the 6x7 grid
            first_day = QDate(year, month, 1)
            try:
                fdow = _dow(cal.firstDayOfWeek())
            except Exception:
                fdow = 1
            shift = (first_day.dayOfWeek() - fdow + 7) % 7
            grid_start = first_day.addDays(-shift)

            # Prepare formats
            fmt_hide = QTextCharFormat()
            try:
                # Hide numbers and any background for out-of-month days
                transparent = QBrush(QColor(0, 0, 0, 0))
                fmt_hide.setForeground(transparent)
                fmt_hide.setBackground(transparent)
            except Exception:
                pass
            fmt_show = QTextCharFormat()  # default resets formatting

            # Apply to 42 cells (6 weeks)
            for i in range(42):
                d = grid_start.addDays(i)
                if d.month() != month:
                    cal.setDateTextFormat(d, fmt_hide)
                else:
                    cal.setDateTextFormat(d, fmt_show)
        except Exception:
            pass

    def _enable_one_month_only(cal: QCalendarWidget):
        try:
            # Initial apply
            _apply_cal_one_month_only(cal)
            # Update on page change using a QObject slot (no lambda) to avoid connect warnings
            try:
                if not getattr(cal, "_nik_one_month_connected", False):
                    if not hasattr(cal, "_nik_one_month_enforcer"):
                        class _OneMonthEnforcer(QObject):
                            @Slot(int, int)
                            def on_page(self, y, m):
                                try:
                                    _apply_cal_one_month_only(cal, y, m)
                                except Exception:
                                    pass
                        # keep reference on the calendar to avoid GC
                        cal._nik_one_month_enforcer = _OneMonthEnforcer(cal)
                    try:
                        cal.currentPageChanged.connect(cal._nik_one_month_enforcer.on_page)
                    except TypeError:
                        # Fallback to lambda if needed (older bindings)
                        cal.currentPageChanged.connect(lambda y, m, c=cal: _apply_cal_one_month_only(c, y, m))
                    cal._nik_one_month_connected = True
            except Exception:
                pass
        except Exception:
            pass

    class _OneMonthDelegate(QStyledItemDelegate):
        def __init__(self, cal):
            super().__init__(cal)
            self.cal = cal
        def paint(self, painter, option, index):
            try:
                y = int(self.cal.yearShown())
                m = int(self.cal.monthShown())
            except Exception:
                d = self.cal.selectedDate(); y, m = int(d.year()), int(d.month())
            first_day = QDate(y, m, 1)
            try:
                fdow = int(getattr(self.cal.firstDayOfWeek(), 'value', self.cal.firstDayOfWeek()))
            except Exception:
                fdow = 1
            shift = (first_day.dayOfWeek() - fdow + 7) % 7
            grid_start = first_day.addDays(-shift)
            idx = index
            try:
                r, c = idx.row(), idx.column()
            except Exception:
                r, c = 0, 0
            d = grid_start.addDays(r * 7 + c)
            if d.month() != m:
                painter.save()
                painter.fillRect(option.rect, option.palette.base())
                painter.restore()
                return
            return super().paint(painter, option, index)

    class _OneMonthClickBlocker(QObject):
        def __init__(self, cal, view):
            super().__init__(view)
            self.cal = cal
            self.view = view
        def eventFilter(self, obj, ev):
            try:
                if obj is self.view.viewport() and ev.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick):
                    try:
                        y = int(self.cal.yearShown()); m = int(self.cal.monthShown())
                    except Exception:
                        d = self.cal.selectedDate(); y, m = int(d.year()), int(d.month())
                    first_day = QDate(y, m, 1)
                    try:
                        fdow = int(getattr(self.cal.firstDayOfWeek(), 'value', self.cal.firstDayOfWeek()))
                    except Exception:
                        fdow = 1
                    shift = (first_day.dayOfWeek() - fdow + 7) % 7
                    grid_start = first_day.addDays(-shift)
                    idx = self.view.indexAt(ev.pos())
                    if idx.isValid():
                        r, c = idx.row(), idx.column()
                        d = grid_start.addDays(r * 7 + c)
                        if d.month() != m:
                            return True
            except Exception:
                pass
            return False

    def _prep_cal_hover(cal: QCalendarWidget):
        view = cal.findChild(QTableView, "qt_calendar_calendarview")
        if view:
            # Ensure weekday header shows Monday..Sunday with short names
            try:
                cal.setFirstDayOfWeek(Qt.Monday)
            except Exception:
                pass
            try:
                cal.setHorizontalHeaderFormat(QCalendarWidget.ShortDayNames)
            except Exception:
                pass
            try:
                # Hide week numbers to keep header compact and fully visible
                cal.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
            except Exception:
                pass

            view.setMouseTracking(True)
            view.viewport().setMouseTracking(True)

        # Reset any custom date formats so the month grid shows all dates
        try:
            try:
                year = int(cal.yearShown())
                month = int(cal.monthShown())
            except Exception:
                d = cal.selectedDate()
                year, month = int(d.year()), int(d.month())
            first_day = QDate(year, month, 1)
            try:
                fd = cal.firstDayOfWeek()
                fdow = int(getattr(fd, "value", fd))
            except Exception:
                fdow = 1
            shift = (first_day.dayOfWeek() - fdow + 7) % 7
            grid_start = first_day.addDays(-shift)
            fmt_reset = QTextCharFormat()
            for i in range(42):
                cal.setDateTextFormat(grid_start.addDays(i), fmt_reset)
        except Exception:
            pass

    # пропатчить уже существующие календари
    for w in app.allWidgets():
        if isinstance(w, QCalendarWidget):
            _prep_cal_hover(w)

    # и все, что создадутся позже (например, в попапе фильтра)
    class _CalHoverWatcher(QObject):
        def eventFilter(self, obj, ev):
            if isinstance(obj, QCalendarWidget) and ev.type() == QEvent.Show:
                _prep_cal_hover(obj)
            return False

    _cal_hover_watcher = _CalHoverWatcher(app)
    app.installEventFilter(_cal_hover_watcher)
    app._nik_cal_hover_watcher = _cal_hover_watcher  # не дать сборщику мусора убрать
    LIGHT_THEME_QSS = style
    return style


def _ensure_light_stylesheet(app: QApplication) -> str:
    global LIGHT_THEME_QSS
    if not LIGHT_THEME_QSS:
        LIGHT_THEME_QSS = apply_nik_style(app)
        try:
            class _MsgBoxTopAligner(QObject):
                def eventFilter(self, obj, ev):
                    try:
                        if isinstance(obj, QMessageBox) and ev.type() == QEvent.Show:
                            move_messagebox_text_to_top(obj, TEXT_TOP_Y)
                            if _is_dark_mode():
                                try:
                                    palette = obj.palette()
                                    palette.setColor(QPalette.Window, QColor("#121212"))
                                    palette.setColor(QPalette.WindowText, QColor("#e0e0e0"))
                                    obj.setPalette(palette)
                                    obj.setStyleSheet("QMessageBox { background-color: #121212; }")
                                    # Устанавливаем тёмный title-bar для Windows
                                    try:
                                        set_dark_titlebar(obj)
                                    except Exception:
                                        pass
                                    try:
                                        from PySide6.QtWidgets import QStyleFactory
                                        if "Fusion" in QStyleFactory.keys():
                                            obj.setStyle(QStyleFactory.create("Fusion"))
                                    except Exception:
                                        pass
                                except Exception:
                                    pass
                        elif isinstance(obj, QtWidgets.QDialog) and ev.type() == QEvent.Show:
                            if _is_dark_mode():
                                try:
                                    palette = obj.palette()
                                    palette.setColor(QPalette.Window, QColor("#121212"))
                                    palette.setColor(QPalette.WindowText, QColor("#e0e0e0"))
                                    obj.setPalette(palette)
                                    # Устанавливаем тёмный title-bar для Windows
                                    try:
                                        set_dark_titlebar(obj)
                                    except Exception:
                                        pass
                                    try:
                                        from PySide6.QtWidgets import QStyleFactory
                                        if "Fusion" in QStyleFactory.keys():
                                            obj.setStyle(QStyleFactory.create("Fusion"))
                                    except Exception:
                                        pass
                                except Exception:
                                    pass
                    except Exception:
                        pass
                    return False
            if not hasattr(app, "_nik_msgbox_aligner"):
                _flt = _MsgBoxTopAligner(app)
                app.installEventFilter(_flt)
                app._nik_msgbox_aligner = _flt  # type: ignore[attr-defined]
        except Exception:
            pass
    return LIGHT_THEME_QSS


def _replace_colors_for_dark(qss: str) -> str:
    if not qss:
        return qss

    def _replacer(match: re.Match) -> str:
        token = match.group(0).upper()
        return _COLOR_REPLACEMENTS.get(token, match.group(0))

    replaced = _COLOR_PATTERN.sub(_replacer, qss)

    # Replace icon paths with white versions for dark theme (for QSS-driven icons).
    # Use on-disk white variants so QSS can load them. Skip icons we should not tint.
    try:
        icon_paths_to_replace = [
            SORT_ICON_UP_PATH,
            SORT_ICON_DOWN_PATH,
            ARROW_RIGHT_ICON_PATH,
            ARROW_LEFT_ICON_PATH,
            DOWN_ARROW_ICON_PATH,
            FILTER_ICON_PATH,
            CHECK_ICON_OFF_PATH,
            CHECK_ICON_ON_PATH,
            CHECK_ICON_MID_PATH,
            RCHECK_ICON_OFF_PATH,
            RCHECK_ICON_ON_PATH,
        ]

        for original_path in icon_paths_to_replace:
            if not original_path:
                continue
            if not _should_tint_icon_white(original_path):
                continue
            try:
                orig_norm = original_path.replace("\\", "/")
                white_variant = _get_white_icon_path_for_dark_theme(original_path)
                if white_variant:
                    replaced = replaced.replace(orig_norm, white_variant)
            except Exception:
                continue
    except Exception:
        pass

    # Enhanced dark theme adjustments
    white_down_arrow = _get_white_icon_path_for_dark_theme(DOWN_ARROW_ICON_PATH) if DOWN_ARROW_ICON_PATH else ""
    white_left_arrow = _get_white_icon_path_for_dark_theme(ARROW_LEFT_ICON_PATH) if ARROW_LEFT_ICON_PATH else ""
    white_right_arrow = _get_white_icon_path_for_dark_theme(ARROW_RIGHT_ICON_PATH) if ARROW_RIGHT_ICON_PATH else ""
    white_up_arrow = _get_white_icon_path_for_dark_theme(SORT_ICON_UP_PATH) if SORT_ICON_UP_PATH else ""
    white_down_sort_arrow = _get_white_icon_path_for_dark_theme(SORT_ICON_DOWN_PATH) if SORT_ICON_DOWN_PATH else ""

    appended = (
        "\n/* ColumnsPopup QCheckBox dark theme overrides */\n"
        "QWidget#columnsPopup QCheckBox[menuitem=\"true\"] { color:#e0e0e0; background:transparent; border:1px solid transparent; border-radius:8px; padding:6px 12px; }\n"
        "QWidget#columnsPopup QCheckBox[menuitem=\"true\"]:hover { color:#000000; background:#FFE3C2; border-color:#FFA74B; }\n"
        "QWidget#columnsPopup QCheckBox[menuitem=\"true\"]:checked { color:#000000; background:#FFC37A; border-color:#E07E12; }\n"
        "QWidget#columnsPopup QCheckBox[menuitem=\"true\"]::indicator { width:0px; height:0px; }\n"
        "\n/* QCheckBox menu items in any menu (including type filter) */\n"
        "QMenu QCheckBox[menuitem=\"true\"] { color:#e0e0e0; background:transparent; border:1px solid transparent; border-radius:8px; padding:6px 12px; }\n"
        "QMenu QCheckBox[menuitem=\"true\"]:hover { color:#000000; background:#FFE3C2; border-color:#FFA74B; }\n"
        "QMenu QCheckBox[menuitem=\"true\"]:checked { color:#000000; background:#FFC37A; border-color:#E07E12; }\n"
        "QMenu QCheckBox[menuitem=\"true\"]::indicator { width:0px; height:0px; }\n"
        "\n/* nikHeaderMenu specific checkbox styling */\n"
        "QMenu#nikHeaderMenu QCheckBox[menuitem=\"true\"] { color:#e0e0e0; background:transparent; border:1px solid transparent; border-radius:8px; padding:6px 12px; }\n"
        "QMenu#nikHeaderMenu QCheckBox[menuitem=\"true\"]:hover { color:#000000; background:#FFE3C2; border-color:#FFA74B; }\n"
        "QMenu#nikHeaderMenu QCheckBox[menuitem=\"true\"]:checked { color:#000000; background:#FFC37A; border-color:#E07E12; }\n"
        "QMenu#nikHeaderMenu QCheckBox[menuitem=\"true\"]::indicator { width:0px; height:0px; }\n"
        "\n/* QLabel inside QMenu - white text in dark theme */\n"
        "QMenu QLabel { color: #e0e0e0; background: transparent; }\n"
        "QMenu QLabel:hover { color: #e0e0e0; }\n"
        "QMenu#nikHeaderMenu QLabel { color: #e0e0e0; background: transparent; }\n"
        "QMenu#nikHeaderMenu QLabel:hover { color: #e0e0e0; }\n"
        "\n/* Props card - dark theme */\n"
        "QWidget#propsCard { background: #1e1e1e; border: 1px solid #505050; border-radius: 12px; }\n"
        "QWidget#propsCard QLabel { color: #e0e0e0; }\n"
        "QWidget#propsCard QDialogButtonBox { border-top: 1px solid #505050; padding-top: 8px; }\n"
        "\n/* Dark theme base colors - ЕДИНЫЙ ФОН */\n"
        "QWidget { background-color: #121212; color: #e0e0e0; }\n"
        "QMainWindow { background-color: #121212; }\n"
        "QDialog { background-color: #121212; }\n"
        "QWidget { background-color: #121212; color: #e0e0e0; }\n"
        "QMessageBox { background-color: #121212; }\n"
        "QFrame { background-color: #121212; }\n"
        "QLabel { color: #e0e0e0; background-color: #121212; }\n"
        "QStatusBar { background-color: #121212; }\n"
        "QScrollBar { background-color: transparent !important; }\n"
        "QScrollBar::add-line { background-color: transparent !important; }\n"
        "QScrollBar::sub-line { background-color: transparent !important; }\n"
        "QScrollBar::add-page { background-color: transparent !important; }\n"
        "QScrollBar::sub-page { background-color: transparent !important; }\n"
        "QMenu QScrollBar { background-color: transparent !important; }\n"
        "QMenu QScrollBar::add-line { background-color: transparent !important; }\n"
        "QMenu QScrollBar::sub-line { background-color: transparent !important; }\n"
        "QMenu QScrollBar::add-page { background-color: transparent !important; }\n"
        "QMenu QScrollBar::sub-page { background-color: transparent !important; }\n"
        "QMenu::viewport, QMenu::scroll-area-widget { background-color: #121212 !important; }\n"
        "\n/* Dark theme buttons with borders */\n"
        "QToolButton, QPushButton { background-color: #1e1e1e; border: 1px solid #333333; }\n"
        "/* Dialog buttons (OK/Cancel) - transparent background in dark theme */\n"
        "QDialogButtonBox QPushButton { background: transparent; color: #e0e0e0; border: 1px solid #505050; border-radius: 14px; padding: 6px 12px; font-weight: 600; }\n"
        "QDialogButtonBox QPushButton:hover { background: rgba(247, 146, 30, 0.15); border-color: #FFA74B; color: #e0e0e0; }\n"
        "QDialogButtonBox QPushButton:pressed { background: rgba(247, 146, 30, 0.25); border-color: #E07E12; color: #e0e0e0; }\n"
        "QToolButton#accent, QPushButton#accent { background: #FFFFFF; color: #222222; border: 1px solid #dcdcdc; border-radius: 14px; padding: 6px 12px; font-weight: 600; }\n"
        "QToolButton#accent:hover, QPushButton#accent:hover { background: rgba(247, 146, 30, 0.08); color: #e0e0e0; border-color: #505050; }\n"
        "QToolButton#accent:pressed, QPushButton#accent:pressed { background: #FFC37A; border-color: #E07E12; }\n"
        "QToolButton:disabled, QPushButton:disabled { background-color: #1a1a1a; color: #666666; border: 1px solid #333333; }\n"
        "/* Notification and 'No Folders' buttons - rounded border */\n"
        "QToolButton#btnNotify, QToolButton#btnNoFolders { background: transparent; border: 1px solid #505050; border-radius: 12px; padding: 4px 8px; }\n"
        "QToolButton#btnNotify:hover, QToolButton#btnNoFolders:hover { background: rgba(247, 146, 30, 0.15); border-color: #FFA74B; }\n"
        "QToolButton#btnNotify:pressed, QToolButton#btnNoFolders:pressed { background: rgba(247, 146, 30, 0.25); border-color: #E07E12; }\n"
        "QToolButton#btnNoFolders:checked { background: rgba(247, 146, 30, 0.25); border-color: #FFA74B; }\n"
        "QToolButton:hover, QPushButton:hover { background: rgba(247, 146, 30, 0.15); border-color: #FFA74B; }\n"
        "QToolButton:pressed, QPushButton:pressed { background: rgba(247, 146, 30, 0.25); border-color: #E07E12; }\n"
        "/* User button - orange base */\n"
        "QToolButton#btnUser { background: transparent; color: #FFFFFF; border: 1px solid #505050; border-radius: 14px; padding: 6px 12px; font-weight: 600; }\n"
        "QToolButton#btnUser:hover { background: rgba(247, 146, 30, 0.15); color: #e0e0e0; border-color: #FFA74B; }\n"
        "QToolButton#btnUser:pressed { background: rgba(247, 146, 30, 0.25); border-color: #E07E12; }\n"
        "\n/* General QComboBox - dark theme */\n"
        "QComboBox { background: #1e1e1e; color: #e0e0e0; border: 1px solid #505050; border-radius: 8px; padding: 4px 10px; }\n"
        "QComboBox:hover { border: 1px solid #FFA74B; }\n"
        "QComboBox::drop-down { background: #1e1e1e; border-top-right-radius: 8px; border-bottom-right-radius: 8px; }\n"
        "QComboBox QAbstractItemView { background: #1e1e1e; border: none; border-radius: 0px; outline: none; }\n"
        "QComboBox QAbstractItemView::item { padding: 6px 10px; border: 1px solid transparent; border-radius: 6px; margin: 2px; color: #e0e0e0; }\n"
        "QComboBox QAbstractItemView::item:hover { color: #e0e0e0 !important; background: transparent !important; border-color: transparent !important; }\n"
        "QComboBox QAbstractItemView::item:selected { color: #e0e0e0 !important; background: transparent !important; border-color: transparent !important; }\n"
        "QComboBox QAbstractItemView::item:selected:hover { color: #e0e0e0 !important; background: transparent !important; border-color: transparent !important; }\n"
        "\n/* Project combo - dark theme with button-like border */\n"
        "QFrame#qt_combobox_popup { background: #1e1e1e; border: none; border-radius: 12px; padding: 0px; }\n"
        "QComboBoxPrivateContainer { background: #1e1e1e; border: none; border-radius: 12px; padding: 0px; }\n"
        "QFrame#qt_combobox_popup QAbstractItemView { border: none; background: #1e1e1e; }\n"
        "QComboBoxPrivateContainer QAbstractItemView { border: none; background: #1e1e1e; }\n"
        "#projectsCombo { background: #1e1e1e; color: #e0e0e0; border: 1px solid #505050; border-radius: 12px; padding: 4px 30px 4px 10px; }\n"
        "#projectsCombo:hover { border: 1px solid #505050; }\n"
        "#projectsCombo:disabled { background: #2A2A2A; color: #8f8f8f; border: 1px solid #505050; }\n"
        "#projectsCombo::drop-down { background: #1e1e1e; border-top-right-radius: 12px; border-bottom-right-radius: 12px; }\n"
        "\n/* QComboBox arrow - white in dark theme */\n"
        f"QComboBox::down-arrow {{ image: url(\"{white_down_arrow}\"); }}\n"
        "\n/* Project combo dropdown - dark theme with orange border */\n"
        "#projectsCombo QListView { background: #1e1e1e; border: none; border-radius: 8px; outline: none; }\n"
        "#projectsCombo QListView::viewport { border: none; outline: none; }\n"
        "#projectsCombo QListView::frame { border: none; outline: none; }\n"
        "#projectsCombo QListView::item { padding: 6px 10px; margin: 2px; border: none; border-radius: 6px; color: #e0e0e0; }\n"
        "#projectsCombo QListView::item:hover { color: #e0e0e0 !important; background: transparent !important; border: none !important; }\n"
        "#projectsCombo QListView::item:selected { color: #e0e0e0 !important; background: transparent !important; border: none !important; }\n"
        "#projectsCombo QListView::item:selected:hover { color: #e0e0e0 !important; background: transparent !important; border: none !important; }\n"
        "\n/* Project combo arrow - white in dark theme */\n"
        f"#projectsCombo::down-arrow {{\n"
        f"    image: url(\"{white_down_arrow}\");\n"
        f"}}\n"
        "\n/* Modern tooltips - dark theme */\n"
        "QToolTip {\n"
        "    background-color: rgba(18, 18, 18, 0.95);\n"
        "    color: #FFFFFF;\n"
        "    border: 1px solid rgba(247, 146, 30, 0.4);\n"
        "    border-radius: 10px;\n"
        "    padding: 8px 12px;\n"
        "    font-size: 12px;\n"
        "}\n"
        "\n/* Scrollbars dark theme (as in xml.py: 12px, 6px radius, 16px margin) */\n"
        "QScrollBar:vertical { background: transparent; width: 12px; margin: 16px 0 16px 0; border: none; }\n"
        "QScrollBar::handle:vertical { background: rgba(247, 146, 30, 0.12); min-height: 24px; border-radius: 6px; border: 1px solid #FFA74B; }\n"
        "QScrollBar::handle:vertical:hover { background: rgba(247, 146, 30, 0.15); border: 1px solid #FFA74B; }\n"
        "QScrollBar::handle:vertical:pressed { background: rgba(247, 146, 30, 0.25); border: 1px solid #E07E12; }\n"
        "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { background: transparent; height: 16px; subcontrol-origin: margin; border: none; border-radius: 0; image: none; }\n"
        "QScrollBar::add-line:vertical { subcontrol-position: bottom; border: none; }\n"
        "QScrollBar::sub-line:vertical { subcontrol-position: top; border: none; }\n"
        "QScrollBar::add-line:vertical:hover, QScrollBar::sub-line:vertical:hover { background: rgba(247, 146, 30, 0.15); }\n"
        "QScrollBar::add-line:vertical:pressed, QScrollBar::sub-line:vertical:pressed { background: rgba(247, 146, 30, 0.25); }\n"
        "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }\n"
        "QScrollBar:horizontal { background: transparent; height: 12px; margin: 0 16px 0 16px; border: none; }\n"
        "QScrollBar::handle:horizontal { background: rgba(247, 146, 30, 0.12); min-width: 24px; border-radius: 6px; border: 1px solid #FFA74B; }\n"
        "QScrollBar::handle:horizontal:hover { background: rgba(247, 146, 30, 0.15); border: 1px solid #FFA74B; }\n"
        "QScrollBar::handle:horizontal:pressed { background: rgba(247, 146, 30, 0.25); border: 1px solid #E07E12; }\n"
        "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { background: transparent; width: 16px; subcontrol-origin: margin; border: none; border-radius: 0; image: none; }\n"
        "QScrollBar::add-line:horizontal { subcontrol-position: right; border: none; }\n"
        "QScrollBar::sub-line:horizontal { subcontrol-position: left; border: none; }\n"
        "QScrollBar::add-line:horizontal:hover, QScrollBar::sub-line:horizontal:hover { background: rgba(247, 146, 30, 0.15); }\n"
        "QScrollBar::add-line:horizontal:pressed, QScrollBar::sub-line:horizontal:pressed { background: rgba(247, 146, 30, 0.25); }\n"
        "QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }\n"
        "\n/* Scrollbar arrows - white in dark theme */\n"
        f"QScrollBar::left-arrow:horizontal {{ image: url(\"{white_left_arrow}\"); width: 12px; height: 12px; }}\n"
        f"QScrollBar::right-arrow:horizontal {{ image: url(\"{white_right_arrow}\"); width: 12px; height: 12px; }}\n"
        f"QScrollBar::up-arrow:vertical {{ image: url(\"{white_up_arrow}\"); width: 12px; height: 12px; }}\n"
        f"QScrollBar::down-arrow:vertical {{ image: url(\"{white_down_sort_arrow}\"); width: 12px; height: 12px; }}\n"
        "\n/* Menu styling for dark theme */\n"
        "QMenu { background: #1e1e1e; color: #e0e0e0; border: none; padding: 4px 0; border-radius: 8px; min-width: 150px; }\n"
        "QMenu::item { color: #e0e0e0; background: transparent; padding: 6px 12px; }\n"
        "QMenu#nikHeaderMenu { background: #1e1e1e; color: #e0e0e0; }\n"
        "QMenu#nikHeaderMenu::item { color: #e0e0e0; background: transparent; padding: 6px 12px; }\n"
        "\n/* Hover/selection states */\n"
        "QCalendarWidget QAbstractItemView::item:hover { color: #e0e0e0; background: rgba(247, 146, 30, 0.15); border: 1px solid #FFA74B; border-radius: 6px; }\n"
        "QCalendarWidget QAbstractItemView::item:selected { color: #e0e0e0; background: rgba(247, 146, 30, 0.22); border: none; border-radius: 6px; }\n"
        "QMenu::item:hover { color: #e0e0e0; background: rgba(247, 146, 30, 0.15); }\n"
        "QMenu::item:selected { color: #e0e0e0; background: rgba(247, 146, 30, 0.22); }\n"
        "QMenu#nikHeaderMenu::item:hover { color: #e0e0e0; background: rgba(247, 146, 30, 0.15); }\n"
        "QMenu#nikHeaderMenu::item:selected { color: #e0e0e0; background: rgba(247, 146, 30, 0.22); }\n"
        "QMenu#popupMenu::item:hover { color: #e0e0e0; background: rgba(247, 146, 30, 0.15); }\n"
        "QMenu#downloadMenu::item:hover { color: #e0e0e0; background: rgba(247, 146, 30, 0.15); }\n"
        "QMenu#plusMenu::item:hover { color: #e0e0e0; background: rgba(247, 146, 30, 0.15); }\n"
        "QMenu#userMenu::item:hover { color: #e0e0e0; background: rgba(247, 146, 30, 0.15); }\n"
        "QMenu#columnsMenu::item:hover { color: #e0e0e0; background: rgba(247, 146, 30, 0.15); }\n"
        "QMenu#columnsMenu::item:selected { color: #e0e0e0; background: rgba(247, 146, 30, 0.22); }\n"
        "QMenu#treeMenu::item:hover { color: #e0e0e0; background: rgba(247, 146, 30, 0.15); }\n"
        "QMenu#treeMenu::item:selected { color: #e0e0e0; background: rgba(247, 146, 30, 0.22); }\n"
        "QListWidget::item:hover { color: #e0e0e0; background: rgba(247, 146, 30, 0.15); }\n"
        "QListWidget::item:selected { color: #e0e0e0; background: rgba(247, 146, 30, 0.22); }\n"
        "QHeaderView::section { border: none; border-right: none; border-left: none; }\n"
        "QHeaderView::section:hover { color: #e0e0e0; background: rgba(247, 146, 30, 0.15); border: none; }\n"
        "QHeaderView::section:selected { color: #e0e0e0; background: rgba(247, 146, 30, 0.22); border: none; }\n"
        "\n/* Sort arrows in dark theme - white always */\n"
        f"QHeaderView::up-arrow {{ image: url(\"{white_up_arrow}\"); width: 12px; height: 12px; subcontrol-origin: padding; subcontrol-position: right center; right: 1px; margin: 0; background: transparent; }}\n"
        f"QHeaderView::down-arrow {{ image: url(\"{white_down_sort_arrow}\"); width: 12px; height: 12px; subcontrol-origin: padding; subcontrol-position: right center; right: 1px; margin: 0; background: transparent; }}\n"
        "\n/* Скроллбары в меню - тёмная тема */\n"
        "QMenu QScrollBar:vertical { background: transparent !important; width: 12px; margin: 0; border: none; }\n"
        "QMenu QScrollBar::handle:vertical { background: rgba(247, 146, 30, 0.12) !important; min-height: 24px; border-radius: 6px; border: 1px solid #FFA74B !important; }\n"
        "QMenu QScrollBar::handle:vertical:hover { background: rgba(247, 146, 30, 0.15) !important; border: 1px solid #FFA74B !important; }\n"
        "QMenu QScrollBar::handle:vertical:pressed { background: rgba(247, 146, 30, 0.25) !important; border: 1px solid #E07E12 !important; }\n"
        "QMenu QScrollBar::add-line:vertical, QMenu QScrollBar::sub-line:vertical { background: transparent !important; height: 0; subcontrol-origin: margin; border: none; }\n"
        "QMenu QScrollBar::add-page:vertical, QMenu QScrollBar::sub-page:vertical { background: transparent !important; }\n"
        "\n/* Secondary buttons в темной теме при hover темный текст */\n"
        "QPushButton[secondary=\"true\"]:hover, QToolButton[secondary=\"true\"]:hover { }\n"
        "\n/* Make file table highlight match tree colors in dark theme - делегат рисует скругленный фон */\n"
        "QTableView::item:hover { background: transparent; color: #e0e0e0; }\n"
        "QTableView::item:selected, QTableView::item:selected:active, QTableView::item:selected:!active { background: transparent; color: #e0e0e0; }\n"
        "QTableView::item:pressed { background: transparent; color: #e0e0e0; }\n"
        "\n/* Project combo dropdown - dark theme with orange border */\n"
        "\n/* Input fields dark theme */\n"
        "QLineEdit {\n"
        "    background: #252525;\n"
        "    color: #e0e0e0;\n"
        "    border: 1px solid #404040;\n"
        "    selection-background-color: #FFC37A;\n"
        "    selection-color: #121212;\n"
        "}\n"
        "QLineEdit:focus {\n"
        "    border-color: #F7921E;\n"
        "}\n"
        "QTextEdit, QPlainTextEdit {\n"
        "    background: #121212;\n"
        "    color: #e0e0e0;\n"
        "    selection-background-color: #FFC37A;\n"
        "    selection-color: #121212;\n"
        "}\n"
        "QLineEdit:focus {\n"
        "    border-color: #F7921E;\n"
        "}\n"
        "QSpinBox, QDateEdit {\n"
        "    background: #252525;\n"
        "    color: #e0e0e0;\n"
        "    border: 1px solid #404040;\n"
        "    border-radius: 8px;\n"
        "    padding: 4px 10px;\n"
        "}\n"
        "QSpinBox:focus, QDateEdit:focus {\n"
        "    border-color: #F7921E;\n"
        "}\n"
        "QDateEdit::drop-down {\n"
        "    background: #252525;\n"
        "    border-left: 1px solid #404040;\n"
        "}\n"
        "\n/* Calendar widget dark theme */\n"
        "QCalendarWidget {\n"
        "    background: #1e1e1e;\n"
        "    border: 1px solid #505050;\n"
        "    border-radius: 12px;\n"
        "}\n"
        "QCalendarWidget QWidget#qt_calendar_navigationbar {\n"
        "    background: #1e1e1e;\n"
        "    border-bottom: 1px solid #505050;\n"
        "}\n"
        "QCalendarWidget QToolButton#qt_calendar_monthbutton,\n"
        "QCalendarWidget QToolButton#qt_calendar_yearbutton {\n"
        "    background: transparent;\n"
        "    color: #e0e0e0;\n"
        "    border: 1px solid transparent;\n"
        "    border-radius: 12px;\n"
        "    padding: 4px 10px;\n"
        "    font-weight: 600;\n"
        "}\n"
        "QCalendarWidget QToolButton#qt_calendar_monthbutton:hover,\n"
        "QCalendarWidget QToolButton#qt_calendar_yearbutton:hover {\n"
        "    background: rgba(247, 146, 30, 0.15);\n"
        "    border-color: #FFA74B;\n"
        "    color: #e0e0e0;\n"
        "}\n"
        "QCalendarWidget QToolButton#qt_calendar_monthbutton:pressed,\n"
        "QCalendarWidget QToolButton#qt_calendar_yearbutton:pressed {\n"
        "    background: rgba(247, 146, 30, 0.25);\n"
        "    border-color: #E07E12;\n"
        "    color: #e0e0e0;\n"
        "}\n"
        "QCalendarWidget QAbstractItemView {\n"
        "    background: #1e1e1e;\n"
        "    outline: none;\n"
        "    gridline-color: transparent;\n"
        "    selection-background-color: #F7921E;\n"
        "    selection-color: #121212;\n"
        "    color: #e0e0e0;\n"
        "}\n"
        "QCalendarWidget QTableView QHeaderView::section {\n"
        "    background: #1e1e1e;\n"
        "    color: #888888;\n"
        "    border: none;\n"
        "    padding: 4px 0;\n"
        "    font-weight: 600;\n"
        "}\n"
        "QTextEdit, QPlainTextEdit {\n"
        "    background: #121212;\n"
        "    color: #e0e0e0;\n"
        "    selection-background-color: #FFC37A;\n"
        "    selection-color: #000000;\n"
        "}\n"
        "\n/* Tree widget dark theme unification - ЕДИНЫЙ ФОН */\n"
        "QTreeWidget#docsTree {\n"
        "    background: #121212;\n"
        "    border-right: 1px solid #2a2a2a;\n"
        "}\n"
        "QTreeWidget#docsTree QHeaderView {\n"
        "    background: #121212;\n"
        "}\n"
        "QTreeWidget#docsTree QHeaderView::section {\n"
        "    background: #121212;\n"
        "    border: none;\n"
        "    border-right: none;\n"
        "    border-left: none;\n"
        "    color: #e0e0e0;\n"
        "}\n"
        "QTreeWidget::item:hover { background: transparent; color: #e0e0e0; }\n"
        "QTreeWidget::item:selected { background: transparent; color: #e0e0e0; }\n"
        "QTreeWidget::branch { background: transparent; border-image: none; image: none; }\n"
        "QTreeWidget::branch:selected { background: transparent; }\n"
        "QTreeWidget::branch:hover { background: transparent; }\n"
        "\n/* Splitter handle (neutral in dark theme, like light theme) */\n"
        "QSplitter::handle:horizontal {\n"
        "    width: 2px;\n"
        "    background: rgba(255,255,255,0.06);\n"
        "    border-radius: 10px;\n"
        "    margin: 4px 0;\n"
        "}\n"
        "QSplitter::handle:horizontal:hover { background: rgba(255,255,255,0.10); }\n"
        "\n/* Disabled elements */\n"
        "QPushButton[secondary=\"true\"]:disabled, QToolButton[secondary=\"true\"]:disabled { background: #1f1f1f; color: #555555; border: 1px solid #3a3a3a; }\n"
        "QWidget:disabled {\n"
        "    color: #666666;\n"
        "}\n"
        "QPushButton:disabled, QToolButton:disabled {\n"
        "    background: #2a2a2a;\n"
        "    color: #666666;\n"
        "    border: 1px solid #404040;\n"
        "}\n"
        "\n/* Chip buttons in dark theme - larger and more rounded */\n"
        "QPushButton[chip=\"true\"], QToolButton[chip=\"true\"] {\n"
        "    background: #2a2a2a;\n"
        "    color: #e0e0e0;\n"
        "    border: 1px solid #505050;\n"
        "    border-radius: 16px;\n"
        "    padding: 8px 20px;\n"
        "    min-height: 32px;\n"
        "    font-weight: 600;\n"
        "    font-size: 13px;\n"
        "    border-image: none;\n"
        "}\n"
        "QPushButton[chip=\"true\"]:hover, QToolButton[chip=\"true\"]:hover {\n"
        "    background: rgba(247, 146, 30, 0.15);\n"
        "    border-color: #FFA74B;\n"
        "    color: #e0e0e0;\n"
        "}\n"
        "QPushButton[chip=\"true\"]:pressed, QToolButton[chip=\"true\"]:pressed {\n"
        "    background: rgba(247, 146, 30, 0.25);\n"
        "    border-color: #E07E12;\n"
        "    color: #e0e0e0;\n"
        "}\n"
        "QPushButton[chip=\"true\"]:checked, QToolButton[chip=\"true\"]:checked {\n"
        "    background: #F7921E;\n"
        "    border-color: #F7921E;\n"
        "    color: #FFFFFF;\n"
        "}\n"
        "QPushButton[chip=\"true\"]:checked:hover, QToolButton[chip=\"true\"]:checked:hover {\n"
        "    background: rgba(247, 146, 30, 0.15);\n"
        "    border-color: #FFA74B;\n"
        "    color: #FFFFFF;\n"
        "}\n"
        "QPushButton[chip=\"true\"]:disabled, QToolButton[chip=\"true\"]:disabled {\n"
        "    background: #1a1a1a;\n"
        "    color: #666666;\n"
        "    border-color: #333333;\n"
        "}\n"
        "/* Override btnNoFolders specifically to have small size like light theme */\n"
        "QToolButton#btnNoFolders[chip=\"true\"], QPushButton#btnNoFolders[chip=\"true\"] {\n"
        "    background: transparent;\n"
        "    color: #e0e0e0;\n"
        "    border: 1px solid #505050;\n"
        "    border-radius: 12px;\n"
        "    padding: 4px 8px;\n"
        "    min-height: 0px;\n"
        "    font-weight: 600;\n"
        "    border-image: none;\n"
        "}\n"
        "QToolButton#btnNoFolders[chip=\"true\"]:hover, QPushButton#btnNoFolders[chip=\"true\"]:hover {\n"
        "    background: rgba(247, 146, 30, 0.15);\n"
        "    border-color: #FFA74B;\n"
        "    color: #e0e0e0;\n"
        "}\n"
        "QToolButton#btnNoFolders[chip=\"true\"]:pressed, QPushButton#btnNoFolders[chip=\"true\"]:pressed {\n"
        "    background: rgba(247, 146, 30, 0.25);\n"
        "    border-color: #E07E12;\n"
        "    color: #e0e0e0;\n"
        "}\n"
        "QToolButton#btnNoFolders[chip=\"true\"]:checked, QPushButton#btnNoFolders[chip=\"true\"]:checked {\n"
        "    background: rgba(247, 146, 30, 0.25);\n"
        "    border-color: #FFA74B;\n"
        "    color: #FFFFFF;\n"
        "}\n"
        "QPushButton[chipTiny=\"true\"] {\n"
        "    padding: 1px 6px;\n"
        "    min-height: 14px;\n"
        "    font-size: 8px;\n"
        "    border-radius: 6px;\n"
        "}\n"
        "QPushButton[chipSmall=\"true\"] {\n"
        "    padding: 2px 8px;\n"
        "    min-height: 20px;\n"
        "    font-size: 10px;\n"
        "    background: #2a2a2a;\n"
        "    color: #e0e0e0;\n"
        "    border: 1px solid #505050;\n"
        "    border-radius: 10px;\n"
        "    font-weight: 500;\n"
        "    border-image: none;\n"
        "}\n"
        "QPushButton[chipSmall=\"true\"]:hover {\n"
        "    background: rgba(247, 146, 30, 0.15);\n"
        "    border-color: #FFA74B;\n"
        "    color: #e0e0e0;\n"
        "}\n"
        "QPushButton[chipSmall=\"true\"]:pressed {\n"
        "    background: rgba(247, 146, 30, 0.25);\n"
        "    border-color: #E07E12;\n"
        "    color: #e0e0e0;\n"
        "}\n"
        "QPushButton[chipSmall=\"true\"]:checked {\n"
        "    background: #F7921E;\n"
        "    border-color: #F7921E;\n"
        "    color: #FFFFFF;\n"
        "}\n"
        "QPushButton[chipSmall=\"true\"]:checked:hover {\n"
        "    background: rgba(247, 146, 30, 0.15);\n"
        "    border-color: #FFA74B;\n"
        "    color: #FFFFFF;\n"
        "}\n"
        "QPushButton[chipSmall=\"true\"]:disabled {\n"
        "    background: #1a1a1a;\n"
        "    color: #666666;\n"
        "    border-color: #333333;\n"
        "}\n"
        "\n/* Чекбоксы в меню фильтрации заголовка - тёмная тема */\n"
        "QMenu#nikHeaderMenu QCheckBox[menuitem=\"true\"] {\n"
        "    color: #e0e0e0;\n"
        "    background: transparent;\n"
        "    border: 1px solid transparent;\n"
        "    border-radius: 8px;\n"
        "    padding: 6px 12px;\n"
        "}\n"
        "QMenu#nikHeaderMenu QCheckBox[menuitem=\"true\"]:hover {\n"
        "    color: #e0e0e0;\n"
        "    background: rgba(247, 146, 30, 0.15);\n"
        "    border-color: #FFA74B;\n"
        "}\n"
        "QMenu#nikHeaderMenu QCheckBox[menuitem=\"true\"]:checked {\n"
        "    color: #e0e0e0;\n"
        "    background: rgba(247, 146, 30, 0.25);\n"
        "    border-color: #E07E12;\n"
        "}\n"
        "QMenu#nikHeaderMenu QCheckBox[menuitem=\"true\"]::indicator {\n"
        "    width: 0px;\n"
        "    height: 0px;\n"
        "}\n"
    )

    # Only append if not already present
    if appended.strip() not in replaced:
        replaced += appended
    return replaced


def _set_stylesheet_with_extras(app: QApplication, base_qss: str) -> None:
    parts = []
    if base_qss:
        parts.append(base_qss.strip())
    if EXTRA_QSS:
        parts.append(EXTRA_QSS.strip())
    try:
        def _menu_indicator_qss() -> str:
            try:
                return (
                    f"QMenu#nikHeaderMenu::indicator {{ width: 18px; height: 18px; }}\n"
                    f"QMenu#nikHeaderMenu::indicator:unchecked {{ image: url('{CHECK_ICON_OFF_PATH}'); }}\n"
                    f"QMenu#nikHeaderMenu::indicator:checked {{ image: url('{CHECK_ICON_ON_PATH}'); }}\n"
                    f"QMenu#nikHeaderMenu::indicator:indeterminate {{ image: url('{CHECK_ICON_MID_PATH}'); }}\n"
                )
            except Exception:
                return ""
        mi = _menu_indicator_qss().strip()
        if mi:
            parts.append(mi)
    except Exception:
        pass
    final = "\n".join(parts)
    if not final.strip():
        return
    app.setStyleSheet(final)


def _apply_light_palette(app: QApplication) -> None:
    try:
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor("#FFFFFF"))
        palette.setColor(QPalette.WindowText, QColor("#000000"))
        palette.setColor(QPalette.Base, QColor("#FFFFFF"))
        palette.setColor(QPalette.AlternateBase, QColor("#F0F0F0"))
        palette.setColor(QPalette.ToolTipBase, QColor("#FFFFFF"))
        palette.setColor(QPalette.ToolTipText, QColor("#000000"))
        palette.setColor(QPalette.Text, QColor("#000000"))
        palette.setColor(QPalette.Button, QColor("#FFFFFF"))
        palette.setColor(QPalette.ButtonText, QColor("#000000"))
        palette.setColor(QPalette.BrightText, QColor("#FF0000"))
        palette.setColor(QPalette.Link, QColor("#0000FF"))
        palette.setColor(QPalette.Highlight, QColor("#F7921E"))
        palette.setColor(QPalette.HighlightedText, QColor("#000000"))
        palette.setColor(QPalette.Disabled, QPalette.Text, QColor("#808080"))
        palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#808080"))
        palette.setColor(QPalette.Disabled, QPalette.WindowText, QColor("#808080"))
        app.setPalette(palette)
    except Exception:
        pass


def _apply_dark_palette(app: QApplication) -> None:
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#121212"))
    palette.setColor(QPalette.WindowText, QColor("#e0e0e0"))
    palette.setColor(QPalette.Base, QColor("#121212"))
    palette.setColor(QPalette.AlternateBase, QColor("#121212"))
    palette.setColor(QPalette.ToolTipBase, QColor("#e0e0e0"))
    palette.setColor(QPalette.ToolTipText, QColor("#121212"))
    palette.setColor(QPalette.Text, QColor("#e0e0e0"))
    palette.setColor(QPalette.Button, QColor("#121212"))
    palette.setColor(QPalette.ButtonText, QColor("#e0e0e0"))
    palette.setColor(QPalette.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.Link, QColor("#ffa74b"))
    palette.setColor(QPalette.Highlight, QColor("#F7921E"))
    palette.setColor(QPalette.HighlightedText, QColor("#000000"))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor("#666666"))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#666666"))
    palette.setColor(QPalette.Disabled, QPalette.WindowText, QColor("#666666"))
    app.setPalette(palette)


def apply_light_theme(app: QApplication) -> None:
    global _WHITE_ICON_CACHE
    _apply_light_palette(app)
    style = _ensure_light_stylesheet(app)
    _set_stylesheet_with_extras(app, style)
    try:
        app.setProperty("nik_theme", THEME_LIGHT)
    except Exception:
        pass
    # Clear icon cache so icons are reloaded without tinting
    try:
        _WHITE_ICON_CACHE.clear()
    except Exception:
        pass


def apply_dark_theme(app: QApplication) -> None:
    global DARK_THEME_QSS, _WHITE_ICON_CACHE
    _apply_dark_palette(app)
    base = _ensure_light_stylesheet(app)
    if not DARK_THEME_QSS:
        DARK_THEME_QSS = _replace_colors_for_dark(base) or ""
    _set_stylesheet_with_extras(app, base)
    try:
        if DARK_THEME_QSS and DARK_THEME_QSS.strip():
            current = app.styleSheet() or ""
            appended = current + "\n" + DARK_THEME_QSS.strip()
            if appended.strip():
                app.setStyleSheet(appended)
    except Exception:
        pass
    try:
        app.setProperty("nik_theme", THEME_DARK)
    except Exception:
        pass
    # Clear icon cache so icons are re-tinted
    try:
        _WHITE_ICON_CACHE.clear()
    except Exception:
        pass


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


def load_saved_theme() -> str:
    """Load saved theme from JSON settings."""
    try:
        settings = load_settings()
        theme = settings.get("theme", THEME_LIGHT)
        if theme in (THEME_LIGHT, THEME_DARK):
            return theme
    except Exception:
        pass
    
    try:
        s = QSettings(SETTINGS_ORG, SETTINGS_APP)
        val = s.value(SETTINGS_THEME_KEY, THEME_LIGHT)
        if isinstance(val, str) and val in (THEME_LIGHT, THEME_DARK):
            def updater(data: dict) -> dict:
                data["theme"] = val
                return data
            update_settings(updater)
            s.remove(SETTINGS_THEME_KEY)
            return val
    except Exception:
        pass
    
    return THEME_LIGHT


def save_theme(theme: str) -> None:
    """Save theme to JSON settings."""
    try:
        if theme not in (THEME_LIGHT, THEME_DARK):
            return
        
        def updater(data: dict) -> dict:
            data["theme"] = theme
            return data
        
        update_settings(updater)
    except Exception:
        pass


TEXT_TOP_Y = 20


def move_messagebox_text_to_top(mb, top_y=TEXT_TOP_Y):
    """Ставит верх текста на фиксированную высоту от верхней грани окна."""
    def _apply():
        text_lbl = mb.findChild(QtWidgets.QLabel, "qt_msgbox_label")
        if text_lbl is None:
            cands = [w for w in mb.findChildren(QtWidgets.QLabel)
                     if w.isVisible() and w.objectName() not in ("qt_msgboxex_icon_label", "qt_msgbox_icon_label")]
            text_lbl = max(cands, key=lambda w: len(w.text()), default=None)
        if text_lbl is None:
            return
        
        try:
            text_lbl.setWordWrap(True)
            text_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        except Exception:
            pass

        if text_lbl.parent() and text_lbl.parent().objectName() == "msgtextwrap":
            wrap = text_lbl.parent()
            v = wrap.layout()
            cur_y = text_lbl.mapTo(mb, QPoint(0, 0)).y()
            offset = max(0, int(top_y) - int(cur_y))
            v.setContentsMargins(0, offset, 0, 0)
            mb.layout().setSizeConstraint(QLayout.SetMinimumSize)
            mb.adjustSize()
            return

        lay = mb.layout()
        r = c = rs = cs = 0
        if isinstance(lay, QtWidgets.QGridLayout):
            idx = lay.indexOf(text_lbl)
            if idx >= 0:
                r, c, rs, cs = lay.getItemPosition(idx)

        try:
            cur_y = text_lbl.mapTo(mb, QPoint(0, 0)).y()
        except Exception:
            cur_y = 0

        offset = max(0, int(top_y) - int(cur_y))
        if offset <= 0:
            return
        
        try:
            icon_lbl = (mb.findChild(QtWidgets.QLabel, "qt_msgbox_icon_label")
                        or mb.findChild(QtWidgets.QLabel, "qt_msgboxex_icon_label"))
            if icon_lbl is not None:
                icon_wrap = QtWidgets.QWidget(mb)
                icon_wrap.setObjectName("msgiconwrap")
                iv = QVBoxLayout(icon_wrap)
                iv.setContentsMargins(0, offset, 0, 0)
                iv.setSpacing(0)
                if isinstance(lay, QtWidgets.QGridLayout):
                    idx_i = lay.indexOf(icon_lbl)
                    if idx_i >= 0:
                        r_i, c_i, rs_i, cs_i = lay.getItemPosition(idx_i)
                        lay.addWidget(icon_wrap, r_i, c_i, rs_i, cs_i)
                        lay.removeWidget(icon_lbl)
                icon_lbl.setParent(icon_wrap)
                iv.addWidget(icon_lbl)
        except Exception:
            pass

        wrap = QtWidgets.QWidget(mb)
        wrap.setObjectName("msgtextwrap")
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, offset, 0, 0)
        v.setSpacing(0)

        if isinstance(lay, QtWidgets.QGridLayout) and (rs or cs):
            lay.addWidget(wrap, r, c, rs, cs)
            lay.removeWidget(text_lbl)
        text_lbl.setParent(wrap)
        v.addWidget(text_lbl)

        lay.setSizeConstraint(QLayout.SetMinimumSize)
        mb.adjustSize()

    QTimer.singleShot(0, _apply)


def _set_dark_titlebar_win32(hwnd: int) -> bool:
    """Устанавливает тёмную тему для title-bar окна в Windows 10/11.
    
    Args:
        hwnd: Window handle (int)
        
    Returns:
        True если успешно, False иначе
    """
    try:
        import ctypes
        from ctypes import wintypes
        
        # DWMWA_USE_IMMERSIVE_DARK_MODE = 20 для Windows 10 1809+
        # DWMWA_USE_IMMERSIVE_DARK_MODE = 19 для более старых версий
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        
        dwm_api = ctypes.windll.dwmapi
        
        # BOOL value = TRUE (1) для тёмной темы
        value = ctypes.c_int(1)
        
        result = dwm_api.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            ctypes.c_int(DWMWA_USE_IMMERSIVE_DARK_MODE),
            ctypes.byref(value),
            ctypes.sizeof(value)
        )
        
        return result == 0  # S_OK = 0
    except Exception:
        return False


def set_dark_titlebar(window) -> bool:
    """Устанавливает тёмную тему для title-bar окна (Windows only).
    
    Args:
        window: QWidget или окно (должен иметь winId())
        
    Returns:
        True если успешно, False иначе
    """
    try:
        if sys.platform != "win32":
            return False
        
        # Получаем HWND из Qt окна
        hwnd = int(window.winId())
        if hwnd == 0:
            return False
            
        return _set_dark_titlebar_win32(hwnd)
    except Exception:
        return False


def install_warning_icon_for_messageboxes():
    if _SAFE_MESSAGEBOX:
        return
    pm = QPixmap(WARNING_ICON_PATH)

    # Keep original question() implementation: our custom messagebox sizing/geometry
    # can trigger native crashes on some multi-monitor setups.
    _orig_question = getattr(QMessageBox, "question", None)

    def _box(parent, title, text,
             buttons=QMessageBox.Ok,
             defaultButton=QMessageBox.NoButton):
        # Minimal customization: only apply custom icon + plain text.
        mb = QMessageBox(parent)
        try:
            mb.setWindowTitle(title or "")
        except Exception:
            pass
        try:
            mb.setText(text or "")
        except Exception:
            pass
        try:
            mb.setTextFormat(Qt.TextFormat.PlainText)
        except Exception:
            pass
        try:
            mb.setStandardButtons(buttons)
        except Exception:
            pass

        try:
            if not pm.isNull():
                size_px = QApplication.style().pixelMetric(QStyle.PM_MessageBoxIconSize)
                mb.setIconPixmap(pm.scaled(size_px, size_px, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                mb.setIcon(QMessageBox.Warning)
        except Exception:
            try:
                mb.setIcon(QMessageBox.Warning)
            except Exception:
                pass

        try:
            if defaultButton != QMessageBox.NoButton:
                mb.setDefaultButton(defaultButton)
        except Exception:
            pass

        return mb.exec()

    def _question(parent, title, text,
                  buttons=QMessageBox.Yes | QMessageBox.No,
                  defaultButton=QMessageBox.NoButton):
        # Prefer the Qt built-in implementation for stability.
        if callable(_orig_question):
            try:
                return _orig_question(parent, title, text, buttons, defaultButton)
            except Exception:
                pass
        # Fallback: create a minimal QMessageBox instance.
        mb = QMessageBox(parent)
        try:
            mb.setWindowTitle(title or "")
            mb.setText(text or "")
            mb.setTextFormat(Qt.TextFormat.PlainText)
            mb.setIcon(QMessageBox.Question)
            mb.setStandardButtons(buttons)
            if defaultButton != QMessageBox.NoButton:
                mb.setDefaultButton(defaultButton)
        except Exception:
            pass
        return mb.exec()

    for cls in (QMessageBox, QtWidgets.QMessageBox):
        cls.information = staticmethod(_box)
        cls.warning     = staticmethod(_box)
        cls.critical    = staticmethod(_box)
        cls.question    = staticmethod(_question)


def install_russian_ui(app):
    try:
        QLocale.setDefault(QLocale(QLocale.Russian, QLocale.Russia))
    except Exception:
        pass

    try:
        tr_path = QLibraryInfo.path(QLibraryInfo.TranslationsPath)
    except Exception:
        tr_path = getattr(QLibraryInfo, "location", lambda *_: "")(QLibraryInfo.TranslationsPath)

    keep = getattr(app, "_translators", [])

    for name in ("qtbase_ru", "qt_ru"):
        try:
            tr = QTranslator(app)
            if tr.load(name, tr_path):
                app.installTranslator(tr)
                keep.append(tr)
        except Exception:
            pass

    app._translators = keep


def _patch_messagebox_texts_fixed():
    """Safe override for QMessageBox.information to normalize corrupted texts.
    Avoids problematic embedded quotes/encodings in source strings.
    """
    if _SAFE_MESSAGEBOX:
        return
    try:
        import re
        _orig_info = QMessageBox.information

        def _info(parent, title, text, *args, **kwargs):
            try:
                t = title or ""
                m = text or ""
                if isinstance(t, str) and t and all((ch == '?' or ch.isspace()) for ch in t):
                    n = None
                    if isinstance(m, str):
                        nums = re.findall(r"\d+", m)
                        if nums:
                            n = nums[-1]
                    if n is not None:
                        t = "Загрузка завершена"
                        m = f"Скачано файлов: {n}"
                    else:
                        t = "Сообщение"
                        m = "Готово."
            except Exception:
                t = title
                m = text
            return _orig_info(parent, t, m, *args, **kwargs)

        QMessageBox.information = _info  # type: ignore[assignment]
    except Exception:
        pass


def _set_window_theme_dark(window, dark: bool = False) -> None:
    """Set Windows title bar theme (light/dark) for a window on Windows."""
    if platform.system() != "Windows":
        return
    try:
        import ctypes
        from ctypes import c_int, byref, sizeof
        hwnd = window.winId().__int__()
        value = c_int(1 if dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, byref(value), sizeof(value)
        )
        caption_color = 0x202020 if dark else 0xFFFFFF
        text_color = 0xFFFFFF if dark else 0x000000
        for attr, color in ((35, caption_color), (36, text_color)):
            try:
                cval = c_int(color)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, byref(cval), sizeof(cval))
            except Exception:
                pass
    except Exception:
        pass


def enable_msgbox_autosize(app: QApplication) -> None:
    """Installs a single event filter that enables word wrap, calculates minimum width by longest line, limits width to 70% of screen and stretches window by height."""
    from PySide6 import QtCore, QtWidgets

    def _tune_msgbox(mb: QtWidgets.QMessageBox) -> None:
        """Make QMessageBox wrap and resize to fit text."""
        try:
            try:
                mb.setTextFormat(Qt.PlainText)
            except Exception:
                pass

            labels = []
            for name in ("qt_msgbox_label", "qt_msgbox_informativelabel"):
                lbl = mb.findChild(QtWidgets.QLabel, name)
                if lbl is None:
                    continue
                try:
                    lbl.setWordWrap(True)
                    try:
                        lbl.setTextFormat(Qt.PlainText)
                    except Exception:
                        pass
                    lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
                    sp = lbl.sizePolicy()
                    sp.setHorizontalPolicy(QSizePolicy.Preferred)
                    sp.setVerticalPolicy(QSizePolicy.Preferred)
                    lbl.setSizePolicy(sp)
                except Exception:
                    pass
                labels.append(lbl)

            minw = 360
            try:
                fm = mb.fontMetrics()
                parts = []
                for s in (mb.text(), mb.informativeText()):
                    if s:
                        parts.extend(str(s).replace("\r", "").split("\n"))
                longest = 0
                for s in parts or [""]:
                    w = fm.horizontalAdvance(s)
                    if w > longest:
                        longest = w
                icon_w = QApplication.style().pixelMetric(QStyle.PM_MessageBoxIconSize)
                padding = 160
                scr = QApplication.primaryScreen()
                cap = int((scr.availableGeometry().width() if scr else 1920) * 0.7)
                minw = max(360, min(longest + icon_w + padding, cap))
                mb.setMinimumWidth(minw)
                for lbl in labels:
                    try:
                        lbl.setMaximumWidth(max(220, minw - 120))
                    except Exception:
                        pass
            except Exception:
                pass

            try:
                move_messagebox_text_to_top(mb, TEXT_TOP_Y)  # type: ignore[name-defined]
            except Exception:
                pass

            # Recompute layout after we changed wrap/width.
            try:
                mb.layout().setSizeConstraint(QLayout.SetMinimumSize)
            except Exception:
                pass
            try:
                mb.adjustSize()
                hint = mb.sizeHint()
                mb.resize(max(hint.width(), minw), max(hint.height(), 140))
            except Exception:
                pass
        except Exception:
            pass

    class _MsgBoxAutosizer(QtCore.QObject):
        def eventFilter(self, obj, ev):
            try:
                if isinstance(obj, QtWidgets.QDialog) and ev.type() in (QtCore.QEvent.Show, QtCore.QEvent.ShowToParent):
                    if not isinstance(obj, QtWidgets.QMessageBox):
                        if _is_dark_mode():
                            try:
                                palette = obj.palette()
                                palette.setColor(QPalette.Window, QColor("#121212"))
                                palette.setColor(QPalette.WindowText, QColor("#e0e0e0"))
                                obj.setPalette(palette)
                                try:
                                    from PySide6.QtWidgets import QStyleFactory
                                    if "Fusion" in QStyleFactory.keys():
                                        obj.setStyle(QStyleFactory.create("Fusion"))
                                except Exception:
                                    pass
                            except Exception:
                                pass
                elif isinstance(obj, QtWidgets.QMainWindow) and ev.type() in (QtCore.QEvent.Show, QtCore.QEvent.ShowToParent):
                    if _is_dark_mode():
                        try:
                            palette = obj.palette()
                            palette.setColor(QPalette.Window, QColor("#121212"))
                            palette.setColor(QPalette.WindowText, QColor("#e0e0e0"))
                            obj.setPalette(palette)
                            try:
                                from PySide6.QtWidgets import QStyleFactory
                                if "Fusion" in QStyleFactory.keys():
                                    obj.setStyle(QStyleFactory.create("Fusion"))
                            except Exception:
                                pass
                        except Exception:
                            pass
                elif isinstance(obj, QtWidgets.QMessageBox) and ev.type() in (QtCore.QEvent.Show, QtCore.QEvent.ShowToParent):
                    # Avoid mutating QMessageBox geometry/styles on safe mode.
                    if _SAFE_MESSAGEBOX:
                        return False

                    mb = obj
                    _tune_msgbox(mb)
                    # After show/layout polish, tune again.
                    try:
                        QtCore.QTimer.singleShot(0, lambda _mb=mb: _tune_msgbox(_mb))
                    except Exception:
                        pass

                    if _is_dark_mode():
                        try:
                            palette = mb.palette()
                            palette.setColor(QPalette.Window, QColor("#121212"))
                            palette.setColor(QPalette.WindowText, QColor("#e0e0e0"))
                            mb.setPalette(palette)
                            mb.setStyleSheet("QMessageBox { background-color: #121212; }")
                            try:
                                from PySide6.QtWidgets import QStyleFactory
                                if "Fusion" in QStyleFactory.keys():
                                    mb.setStyle(QStyleFactory.create("Fusion"))
                            except Exception:
                                pass
                        except Exception:
                            pass
            except Exception:
                pass
            return False

    _flt = _MsgBoxAutosizer(app)
    app.installEventFilter(_flt)
    app._msgbox_autosizer = _flt  # type: ignore[attr-defined]


def load_saved_theme() -> str:
    """Load saved theme from JSON settings."""
    try:
        settings = load_settings()
        theme = settings.get("theme", THEME_LIGHT)
        if theme in (THEME_LIGHT, THEME_DARK):
            return theme
    except Exception:
        pass
    
    # Fallback to old QSettings if JSON not found
    try:
        s = _app_settings()
        val = s.value(SETTINGS_THEME_KEY, THEME_LIGHT)
        if isinstance(val, str) and val in (THEME_LIGHT, THEME_DARK):
            # Migrate to JSON
            def updater(data: dict) -> dict:
                data["theme"] = val
                return data
            update_settings(updater)
            # Clear old setting
            s.remove(SETTINGS_THEME_KEY)
            return val
    except Exception:
        pass
    
    return THEME_LIGHT


def _cloud_tz_offset_minutes() -> int:
    """Return offset in minutes to interpret naive cloud timestamps.
    Uses settings group 'time': keys 'auto' and 'offset_minutes'.
    Also removes legacy key sync2/tz_offset_min if present.
    """
    try:
        s = _app_settings()
        # remove deprecated key once
        try:
            s.beginGroup("sync2")
            try:
                if s.contains("tz_offset_min"):
                    s.remove("tz_offset_min")
            finally:
                s.endGroup()
        except Exception:
            pass
        
        # Get timezone offset from settings
        s.beginGroup("time")
        try:
            auto = s.value("auto", False, bool)
            if auto:
                # Auto-detect from system
                import datetime
                local_tz = datetime.now().astimezone().tzinfo
                local_offset = local_tz.utcoffset(None).total_seconds() / 60
                return int(local_offset)
            else:
                offset = s.value("offset_minutes", 0, int)
                return int(offset)
        finally:
            s.endGroup()
    except Exception:
        pass
    
    return 0
