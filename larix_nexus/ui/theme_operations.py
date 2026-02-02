# -*- coding: utf-8 -*-
"""Theme and UI styling operations for Larix Nexus."""

import os
from PySide6.QtCore import Qt, QSize, QObject
from PySide6.QtGui import QIcon, QColor, QPixmap, QPainter
from PySide6.QtWidgets import QSplitter, QAbstractButton, QApplication, QStyle
import PySide6.QtGui as QtGui
from ..constants import (
    THEME_LIGHT, THEME_DARK, TOOLBAR_REFRESH_ICON, TOOLBAR_UPLOAD_ICON,
    TOOLBAR_DOWNLOAD_ICON, TOOLBAR_NEW_FOLDER_ICON, TOOLBAR_SETTINGS_ICON,
    SORT_ICON_UP_PATH, SORT_ICON_DOWN_PATH, ARROW_LEFT_PATH, ARROW_RIGHT_PATH,
    FILTER_ICON_PATH, INSERT_ICON_PATH, REFRESH_ICON_PATH, BACK_ICON_PATH,
    SYNC_ICON_PATH, CUSTOM_PLUS_ICON_PATH, CUSTOM_SAVE_ICON_PATH, EDIT_ICON_PATH,
    COMPARISON_ICON_PATH, MOVE_FOLDER_ICON_PATH, COPY_FOLDER_ICON_PATH,
    DELETE_ICON_PATH, ALARM_ICON_PATH, NO_FOLDER_ICON_PATH, GEAR_ICON_NAME
)
from ..utils.theme import load_white_icon, white_tinted_icon, _tint_pixmap

# Define icon paths locally
ARROW_ICON_PATHS = {
    "up": SORT_ICON_UP_PATH,
    "down": SORT_ICON_DOWN_PATH,
    "left": ARROW_LEFT_PATH,
    "right": ARROW_RIGHT_PATH,
}


def _themed_icon(self, path: str, *, tint_allowed: bool = True) -> QIcon:
    """Return icon taking current theme into account."""
    try:
        if not path:
            return QIcon()
        normalized = path.replace("\\", "/")
        if normalized in ARROW_ICON_PATHS:
            if getattr(self, "_current_theme", THEME_LIGHT) == THEME_DARK:
                return load_white_icon(path)
            return QIcon(path)
        if getattr(self, "_current_theme", THEME_LIGHT) == THEME_DARK and tint_allowed:
            return load_white_icon(path)
        return QIcon(path)
    except Exception:
        return QIcon(path)


def _themed_standard_icon(self, std_icon: QStyle.StandardPixmap) -> QIcon:
    """Standard icon adjusted for current theme (white in dark)."""
    try:
        icon = self.style().standardIcon(std_icon)
    except Exception:
        icon = QIcon()
    if getattr(self, "_current_theme", THEME_LIGHT) == THEME_DARK:
        return white_tinted_icon(icon)
    return icon


def _update_filter_icon_pm(self) -> None:
    """(Re)load header filter overlay pixmap honoring current theme."""
    self._filter_icon_pm = None
    try:
        if not os.path.exists(FILTER_ICON_PATH):
            return

        target_size = QSize(14, 14)
        dark = getattr(self, "_current_theme", THEME_LIGHT) == THEME_DARK
        pm = QPixmap()

        if dark:
            try:
                icon = load_white_icon(FILTER_ICON_PATH)
                pm = icon.pixmap(target_size)
            except Exception:
                pm = QPixmap()

        if pm.isNull():
            pm = QPixmap(FILTER_ICON_PATH)
            if dark and not pm.isNull():
                pm = _tint_pixmap(pm, QColor(Qt.white))

        if pm.isNull():
            return

        if pm.size() != target_size:
            pm = pm.scaled(target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._filter_icon_pm = pm
    except Exception:
        pass


def _update_search_icon(self) -> None:
    """Update search icon based on deep search state."""
    if not hasattr(self, "btn_search_deep"):
        return
    if self.btn_search_deep.isChecked():
        icon = self._tinted_icon(INSERT_ICON_PATH, QColor("#F7921E"))
    else:
        icon = self._themed_icon(INSERT_ICON_PATH)
    self.btn_search_deep.setIcon(icon)


def _refresh_search_palette(self) -> None:
    """Refresh search input palette for dark/light theme."""
    if not hasattr(self, "edit_search"):
        return
    dark = getattr(self, "_current_theme", THEME_LIGHT) == THEME_DARK
    try:
        palette = self.edit_search.palette()
        if dark:
            palette.setColor(self.edit_search.backgroundRole(), QColor("#2D2D2D"))
            palette.setColor(self.edit_search.foregroundRole(), QColor("#FFFFFF"))
        else:
            palette.setColor(self.edit_search.backgroundRole(), QColor("#FFFFFF"))
            palette.setColor(self.edit_search.foregroundRole(), QColor("#000000"))
        self.edit_search.setPalette(palette)
    except Exception:
        pass


def _refresh_secondary_style(self, *buttons: QAbstractButton) -> None:
    """Refresh secondary button icons for current theme."""
    dark = getattr(self, "_current_theme", THEME_LIGHT) == THEME_DARK
    for btn in buttons:
        try:
            self._restore_button_icon_from_base(btn)
            if dark:
                self._apply_hover_filter(btn)
        except Exception:
            pass


def _apply_icon_theme(self, theme: str) -> None:
    """Apply icon theme to all relevant UI elements."""
    dark = theme == THEME_DARK
    
    def set_icon(btn: QAbstractButton, path: str, *, tint: bool = True, required: bool = False, text_on_missing: str | None = None):
        try:
            icon = self._themed_icon(path, tint_allowed=tint) if tint else QIcon(path)
            btn.setIcon(icon)
            if not icon.isNull():
                btn.setProperty("icon_path", path)
                return True
        except Exception:
            pass
        if required and text_on_missing:
            btn.setText(text_on_missing)
        return False
    
    try:
        for btn_name, icon_path in [
            ("btn_refresh", REFRESH_ICON_PATH),
            ("btn_upload", TOOLBAR_UPLOAD_ICON),
            ("btn_download", CUSTOM_SAVE_ICON_PATH),
            ("btn_new_folder", TOOLBAR_NEW_FOLDER_ICON),
            ("btn_columns", TOOLBAR_SETTINGS_ICON),
            ("btn_back", BACK_ICON_PATH),
            ("btn_sync_all", SYNC_ICON_PATH),
            ("btn_plus", CUSTOM_PLUS_ICON_PATH),
            ("btn_rename", EDIT_ICON_PATH),
            ("btn_compare", COMPARISON_ICON_PATH),
            ("btn_move", MOVE_FOLDER_ICON_PATH),
            ("btn_copy", COPY_FOLDER_ICON_PATH),
            ("btn_delete", DELETE_ICON_PATH),
            ("btn_notify", ALARM_ICON_PATH),
            ("btn_search_deep", INSERT_ICON_PATH),
            ("btn_no_folders", NO_FOLDER_ICON_PATH),
        ]:
            if hasattr(self, btn_name):
                btn = getattr(self, btn_name)
                set_icon(btn, icon_path, tint=True)
    except Exception:
        pass
    
    self._update_filter_icon_pm()
    self._update_search_icon()
    self._refresh_search_palette()


def _restore_button_icon_from_base(self, btn: QAbstractButton) -> None:
    """Restore button icon from saved base path."""
    if not hasattr(btn, "icon_path"):
        return
    path = btn.property("icon_path")
    if path:
        try:
            btn.setIcon(self._themed_icon(path, tint_allowed=True))
        except Exception:
            pass


def _apply_hover_filter(self, btn: QAbstractButton) -> None:
    """Apply hover filter for black icon tinting in dark theme."""
    dark = getattr(self, "_current_theme", THEME_LIGHT) == THEME_DARK
    if not dark:
        return
    
    class HoverFilter(QObject):
        def __init__(self, button):
            super().__init__(button)
            self.button = button
            self.base_pixmap = None
            try:
                if not button.icon().isNull():
                    self.base_pixmap = button.icon().pixmap(button.iconSize())
            except Exception:
                pass
        
        def eventFilter(self, obj, ev):
            try:
                if ev.type() == ev.Type.Enter:
                    if self.base_pixmap:
                        tinted = _tint_pixmap(self.base_pixmap, QColor("#404040"))
                        self.button.setIcon(QIcon(tinted))
                elif ev.type() == ev.Type.Leave:
                    if self.base_pixmap:
                        self.button.setIcon(QIcon(self.base_pixmap))
            except Exception:
                pass
            return super().eventFilter(obj, ev)
    
    if btn.installEventFilter:
        try:
            filter_obj = HoverFilter(btn)
            # Keep a strong reference to avoid PySide/Qt crash on later events.
            try:
                setattr(btn, "_hover_filter_obj", filter_obj)
            except Exception:
                pass
            btn.installEventFilter(filter_obj)
        except Exception:
            pass


def _install_hover_black_icons(self) -> None:
    """Install hover filters for buttons in dark theme (disabled per user request)."""
    return


def _blur_splitter_handles(self, split: QSplitter):
    """Apply blur effect to splitter handles."""
    try:
        if not hasattr(split, "handle_count"):
            return
        for i in range(split.count()):
            handle = split.handle(i + 1)
            if handle:
                handle.setProperty("transparent", True)
                handle.setStyleSheet("QSplitter::handle { background: transparent; }")
    except Exception:
        pass


def _enhance_splitter_handles(self, split: QSplitter):
    """Enhance splitter handles with subtle gradient."""
    try:
        if not hasattr(split, "handle_count"):
            return
        dark = getattr(self, "_current_theme", THEME_LIGHT) == THEME_DARK
        base_color = "#1A1A1A" if dark else "#E0E0E0"
        for i in range(split.count()):
            handle = split.handle(i + 1)
            if handle:
                handle.setProperty("transparent", False)
                handle.setStyleSheet(f"""
                QSplitter::handle {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                        stop:0 {base_color}, stop:0.5 {base_color}, stop:1 {base_color});
                    border: 1px solid {"#2A2A2A" if dark else "#D0D0D0"};
                    width: 1px;
                }}
                QSplitter::handle:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                        stop:0 {"#3A3A3A" if dark else "#C0C0C0"}, 
                        stop:0.5 {"#3A3A3A" if dark else "#C0C0C0"}, 
                        stop:1 {"#3A3A3A" if dark else "#C0C0C0"});
                    width: 2px;
                }}
                """)
    except Exception:
        pass


def _tinted_icon(self, path: str, color: 'QtGui.QColor') -> 'QtGui.QIcon':
    """Create icon tinted with specified color."""
    try:
        if not path or not os.path.exists(path):
            return QIcon()
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return QIcon()
        tinted = _tint_pixmap(pixmap, color)
        return QIcon(tinted)
    except Exception:
        return QIcon()


def _on_theme_toggled(self, dark: bool) -> None:
    """Handle theme toggle event."""
    theme = THEME_DARK if dark else THEME_LIGHT
    self._current_theme = theme

    print(f"[THEME] Toggling theme to: {theme} (dark={dark})")

    try:
        if hasattr(self, "theme_toggle"):
            self.theme_toggle.setChecked(dark)
            self.theme_toggle.snap_to_state()
    except Exception:
        pass

    # Save theme to JSON settings
    try:
        from ..utils.theme import save_theme
        save_theme(theme)
    except Exception:
        pass

    # Apply theme stylesheets
    try:
        from ..utils.theme import apply_light_theme, apply_dark_theme
        app = QApplication.instance()
        if app:
            print(f"[THEME] Applying {'dark' if dark else 'light'} theme to QApplication")
            if dark:
                apply_dark_theme(app)
            else:
                apply_light_theme(app)
            print(f"[THEME] Theme applied, stylesheet length: {len(app.styleSheet() or '')}")
        else:
            print(f"[THEME] ERROR: QApplication.instance() is None")
    except Exception as e:
        print(f"[THEME] ERROR applying theme: {e}")
        import traceback
        traceback.print_exc()

    self._apply_icon_theme(theme)

    try:
        if dark:
            self._install_hover_black_icons()
    except Exception:
        pass

    try:
        from ..utils.helpers import _set_window_theme_dark
        _set_window_theme_dark(self, dark=dark)
    except Exception:
        pass

    QApplication.processEvents()


def inject_theme_operations_to_main_window(MainWindowClass):
    """Inject theme operations into MainWindow class."""
    MainWindowClass._themed_icon = _themed_icon
    MainWindowClass._themed_standard_icon = _themed_standard_icon
    MainWindowClass._update_filter_icon_pm = _update_filter_icon_pm
    MainWindowClass._update_search_icon = _update_search_icon
    MainWindowClass._refresh_search_palette = _refresh_search_palette
    MainWindowClass._refresh_secondary_style = _refresh_secondary_style
    MainWindowClass._apply_icon_theme = _apply_icon_theme
    MainWindowClass._restore_button_icon_from_base = _restore_button_icon_from_base
    MainWindowClass._apply_hover_filter = _apply_hover_filter
    MainWindowClass._install_hover_black_icons = _install_hover_black_icons
    MainWindowClass._blur_splitter_handles = _blur_splitter_handles
    MainWindowClass._enhance_splitter_handles = _enhance_splitter_handles
    MainWindowClass._tinted_icon = _tinted_icon
    MainWindowClass._on_theme_toggled = _on_theme_toggled
