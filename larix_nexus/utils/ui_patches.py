# -*- coding: utf-8 -*-
"""UI patches for Qt widgets."""

import os
from PySide6.QtWidgets import QApplication, QMessageBox, QFileDialog, QDialog
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QComboBox, QAbstractItemView, QFrame, QMenu

from .paths import program_dir


def patch_qfiledialog_initial_dir():
    """Ensure all QFileDialog static pickers default to program_dir().
    - getOpenFileNames: if no dir provided, inject program_dir().
    - getSaveFileName: if provided filename without directory, prefix program_dir().
    - getExistingDirectory: if dir missing/empty, use program_dir().
    """
    try:
        base = program_dir()
        _orig_open = QFileDialog.getOpenFileNames
        _orig_save = QFileDialog.getSaveFileName
        _orig_dir = QFileDialog.getExistingDirectory
        
        def _wrap_open(parent=None, caption="", *args, **kwargs):
            a = list(args)
            if len(a) == 0:
                a = [base]
            else:
                try:
                    if not a[0]:
                        a[0] = base
                except Exception:
                    a[0] = base
            return _orig_open(parent, caption, *a, **kwargs)
        
        def _wrap_save(parent=None, caption="", *args, **kwargs):
            a = list(args)
            if len(a) == 0:
                a = [base]
            else:
                try:
                    path = str(a[0] or "")
                    if not os.path.dirname(path):
                        a[0] = os.path.join(base, path) if path else base
                except Exception:
                    a[0] = base
            return _orig_save(parent, caption, *a, **kwargs)
        
        def _wrap_dir(parent=None, caption="", *args, **kwargs):
            a = list(args)
            if len(a) == 0:
                a = [base]
            else:
                try:
                    if not a[0]:
                        a[0] = base
                except Exception:
                    a[0] = base
            return _orig_dir(parent, caption, *a, **kwargs)
        
        QFileDialog.getOpenFileNames = _wrap_open
        QFileDialog.getSaveFileName = _wrap_save
        QFileDialog.getExistingDirectory = _wrap_dir
    except Exception:
        pass


def patch_dir_picker_binding():
    """Ensure directory picking uses a single folder-selection dialog."""
    try:
        def _pick_dir_with_files(self, title: str = "Выбор папки") -> str:
            try:
                start_dir = program_dir()
            except Exception:
                start_dir = os.getcwd()
            try:
                options = QFileDialog.Options()
                try:
                    options |= QFileDialog.ShowDirsOnly
                except Exception:
                    pass
                path = QFileDialog.getExistingDirectory(self, title, start_dir, options)
                return path or ""
            except Exception:
                try:
                    return QFileDialog.getExistingDirectory(self, title, start_dir) or ""
                except Exception:
                    return ""
        
        from larix_nexus.ui import MainWindow
        MainWindow._pick_directory_showing_files = _pick_dir_with_files
    except Exception:
        pass


def patch_menu_popup_border():
    """Make QMenu dropdown clearly separated in dark mode.
    
    Fixes light title-bar issue on QMenu popups in dark theme by ensuring
    the popup container has proper dark background.
    """
    try:
        if getattr(QApplication, "_larix_menu_popup_patched", False):
            return
        
        def _is_dark(widget) -> bool:
            try:
                c = widget.palette().color(widget.backgroundRole())
                y = (c.red() * 299 + c.green() * 587 + c.blue() * 114) / 1000
                return y < 140
            except Exception:
                return False
        
        _orig_popup = QMenu.popup
        
        def _popup_at(self, pos, action=None):
            _orig_popup(self, pos, action)
            
            def _apply():
                try:
                    dark = _is_dark(self)
                    if not dark:
                        return
                    
                    popup = self
                    try:
                        if not bool(popup.windowFlags() & Qt.Popup):
                            w = popup
                            while w is not None:
                                try:
                                    if bool(w.windowFlags() & Qt.Popup):
                                        popup = w
                                        break
                                except Exception:
                                    pass
                                try:
                                    w = w.parentWidget()
                                except Exception:
                                    break
                    except Exception:
                        pass
                    
                    try:
                        popup.setAttribute(Qt.WA_StyledBackground, True)
                    except Exception:
                        pass
                    
                    try:
                        lay = popup.layout()
                        if lay is not None:
                            lay.setContentsMargins(0, 0, 0, 0)
                            lay.setSpacing(0)
                        else:
                            popup.setContentsMargins(0, 0, 0, 0)
                    except Exception:
                        pass
                    
                    try:
                        popup.setStyleSheet("background: #1e1e1e; border: none;")
                    except Exception:
                        pass
                    
                    try:
                        from .helpers import _set_window_theme_dark
                        _set_window_theme_dark(popup, dark=True)
                    except Exception:
                        pass
                except Exception:
                    pass
            
            QTimer.singleShot(0, _apply)
        
        QMenu.popup = _popup_at
        QApplication._larix_menu_popup_patched = True
    except Exception:
        pass


def patch_qdialog_title_theme():
    """Automatically set dark title bar for all QDialog in dark mode."""
    try:
        if getattr(QApplication, "_larix_qdialog_theme_patched", False):
            return
        
        from .theme import _is_dark_mode
        from .helpers import _set_window_theme_dark
        
        _orig_qdialog_init = QDialog.__init__
        
        def _qdialog_init_with_theme(self, *args, **kwargs):
            _orig_qdialog_init(self, *args, **kwargs)
            
            def _apply_theme():
                try:
                    if _is_dark_mode():
                        _set_window_theme_dark(self, dark=True)
                except Exception:
                    pass
            
            QTimer.singleShot(0, _apply_theme)
        
        QDialog.__init__ = _qdialog_init_with_theme
        QApplication._larix_qdialog_theme_patched = True
    except Exception:
        pass


def patch_combobox_popup_border():
    """Make QComboBox dropdown clearly separated.
    
    Why code patch: QSS selectors like `QComboBox QAbstractItemView { ... }` often
    don't match popup view because it is hosted in a separate top-level
    widget. Setting stylesheet directly on popup view is reliable.
    """
    try:
        if getattr(QComboBox, "_larix_popup_border_patched", False):
            return
        
        def _is_dark(widget) -> bool:
            try:
                c = widget.palette().color(widget.backgroundRole())
                # perceived luminance
                y = (c.red() * 299 + c.green() * 587 + c.blue() * 114) / 1000
                return y < 140
            except Exception:
                return False
        
        _orig_show = QComboBox.showPopup
        
        def _show_popup(self):
            # If there are only a few items, make popup open fully (no scroll).
            try:
                cnt = int(self.count())
                if cnt > 0:
                    self.setMaxVisibleItems(min(24, cnt))
            except Exception:
                cnt = -1
            
            # Apply sizing hints before Qt computes popup geometry.
            try:
                view = self.view()
                if view is not None and cnt > 0:
                    max_items = int(self.maxVisibleItems() or 10)
                    
                    # Prefer no scrolling for small lists.
                    if cnt <= max_items:
                        view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                    else:
                        view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
                    view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                    
                    # Expand popup to fit all items (when list is small).
                    if cnt <= max_items and cnt <= 12:
                        try:
                            row_h = int(view.sizeHintForRow(0) or 0)
                        except Exception:
                            row_h = 0
                        if row_h <= 0:
                            row_h = int(view.fontMetrics().height() + 14)
                        
                        # 4px padding top/bottom from view stylesheet + a small safety margin.
                        popup_h = int(cnt * row_h + 16)
                        view.setFixedHeight(popup_h)
            except Exception:
                pass
            
            _orig_show(self)
            
            def _apply():
                try:
                    view = self.view()
                    if view is None or not isinstance(view, QAbstractItemView):
                        return
                    
                    dark = _is_dark(self)
                    bg = "#1e1e1e" if dark else "#FFFFFF"
                    fg = "#e0e0e0" if dark else "#222222"
                    fg_hover = "#e0e0e0" if dark else "#000000"
                    
                    # Find real popup container (Qt::Popup) and draw border on it.
                    popup = None
                    try:
                        w = view
                        while w is not None:
                            try:
                                if bool(w.windowFlags() & Qt.Popup):
                                    popup = w
                                    break
                            except Exception:
                                pass
                            try:
                                w = w.parentWidget()
                            except Exception:
                                break
                        if popup is None:
                            try:
                                popup = view.window()
                            except Exception:
                                popup = None
                    except Exception:
                        popup = None
                    
                    if popup is not None:
                        try:
                            popup.setAttribute(Qt.WA_StyledBackground, True)
                        except Exception:
                            pass
                        try:
                            lay = popup.layout()
                            if lay is not None:
                                lay.setContentsMargins(0, 0, 0, 0)
                                lay.setSpacing(0)
                            else:
                                popup.setContentsMargins(0, 0, 0, 0)
                        except Exception:
                            pass
                        try:
                            popup_bg = "#1e1e1e" if dark else "#FFFFFF"
                            popup.setStyleSheet(f"background: {popup_bg}; border: none;")
                        except Exception:
                            pass
                    
                    # Never show scrollbars when everything fits.
                    try:
                        max_items = int(self.maxVisibleItems())
                    except Exception:
                        max_items = 10
                    try:
                        if cnt > 0 and cnt <= max_items:
                            view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                        else:
                            view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
                        view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                    except Exception:
                        pass
                    
                    # Style view contents (solid background; no outer border).
                    try:
                        # Disable native QFrame border (often drawn as black).
                        try:
                            view.setFrameShape(QFrame.NoFrame)
                        except Exception:
                            pass
                        
                        view.setStyleSheet(
                            "QAbstractItemView {"
                            f" background: {bg}; color: {fg};"
                            " border:1px solid #FFA74B;"
                            " border-radius: 12px;"
                            " padding:4px;"
                            " outline: none;"
                            " selection-background-color: transparent;"
                            " }"
                            "QAbstractItemView::viewport {"
                            f" background: {bg};"
                            " border-radius: 11px;"
                            " }"
                            "QAbstractItemView::item {"
                            " padding: 6px 10px;"
                            " margin: 2px;"
                            " border: 1px solid transparent;"
                            " border-radius: 8px;"
                            " }"
                            "QAbstractItemView::item:hover {"
                            " background: rgba(247, 146, 30, 0.08);"
                            " border-color: #FFA74B;"
                            f" color: {fg_hover};"
                            " }"
                            "QAbstractItemView::item:selected {"
                            " background: rgba(247, 146, 30, 0.12);"
                            " border-color: #FFA74B;"
                            f" color: {fg_hover};"
                            " }"
                            "QAbstractItemView::item:selected:hover {"
                            " background: rgba(247, 146, 30, 0.20);"
                            " border-color: #E07E12;"
                            f" color: {fg_hover};"
                            " }"
                        )
                    except Exception:
                        pass
                except Exception:
                    pass
            
            QTimer.singleShot(0, _apply)
        
        QComboBox.showPopup = _show_popup
        QComboBox._larix_popup_border_patched = True
    except Exception:
        pass
