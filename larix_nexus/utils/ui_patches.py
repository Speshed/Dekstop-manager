# -*- coding: utf-8 -*-
"""UI patches for Qt widgets."""

import os
from PySide6.QtWidgets import QApplication, QMessageBox, QFileDialog, QDialog
from PySide6.QtCore import Qt, QTimer
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QComboBox, QAbstractItemView, QAbstractScrollArea, QFrame, QMenu, QStyledItemDelegate, QStyle, QStyleOptionViewItem
from PySide6.QtGui import QColor, QPalette, QPainter, QBrush, QPen, QPainterPath, QRegion

from .paths import program_dir


class _ProjectsComboPopupDelegate(QStyledItemDelegate):
    """Force hover/selection highlight for projects combobox popup.

    Some styles / proxy widgets swallow QSS hover for QComboBox popups.
    A delegate guarantees we paint a visible background.
    """

    def paint(self, painter, option, index):
        # Copy option so we can clear selection/focus before default paint.
        opt = QStyleOptionViewItem(option)

        # Detect dark theme from widget (if available).
        try:
            w = index.model()
            if hasattr(w, "parent"):
                w = w.parent()
            if hasattr(w, "parent"):
                w = w.parent()
            if hasattr(w, "parentWidget"):
                w = w.parentWidget()
            if hasattr(w, "window"):
                w = w.window()
            if w is not None and hasattr(w, "palette"):
                bg = w.palette().color(w.backgroundRole())
                y = (bg.red() * 299 + bg.green() * 587 + bg.blue() * 114) / 1000
                dark = y < 140
            else:
                dark = False
        except Exception:
            dark = False

        # Match button hover/pressed colors exactly.
        if dark:
            # Dark theme: hover 0.15, pressed 0.25
            hover_color = QColor.fromRgbF(247/255.0, 146/255.0, 30/255.0, 0.15)
            selected_color = QColor.fromRgbF(247/255.0, 146/255.0, 30/255.0, 0.25)
        else:
            # Light theme: hover 0.10, pressed 0.20
            hover_color = QColor.fromRgbF(247/255.0, 146/255.0, 30/255.0, 0.10)
            selected_color = QColor.fromRgbF(247/255.0, 146/255.0, 30/255.0, 0.20)

        # Draw highlight ourselves and prevent the default style from drawing
        # its own selection/focus rect (which looks like a thicker border).
        try:
            rect = option.rect
            r = QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5)
            state = option.state
            if state & QStyle.State_Selected:
                painter.save()
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                try:
                    painter.setCompositionMode(QPainter.CompositionMode.SourceOver)
                except Exception:
                    pass
                painter.setBrush(QBrush(selected_color))
                painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(r, 6.0, 6.0)
                painter.restore()
            elif state & QStyle.State_MouseOver:
                painter.save()
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                try:
                    painter.setCompositionMode(QPainter.CompositionMode.SourceOver)
                except Exception:
                    pass
                painter.setBrush(QBrush(hover_color))
                painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(r, 6.0, 6.0)
                painter.restore()
        except Exception:
            pass

        # Prevent default painting of selection/focus (we already did it).
        try:
            opt.state &= ~QStyle.State_Selected
            opt.state &= ~QStyle.State_MouseOver
            opt.state &= ~QStyle.State_HasFocus
        except Exception:
            pass

        # Now draw text on top.
        try:
            pal = QPalette(opt.palette)
            pal.setColor(QPalette.Text, QColor("#000000"))
            pal.setColor(QPalette.HighlightedText, QColor("#000000"))
            opt.palette = pal
        except Exception:
            pass
        super().paint(painter, opt, index)


class _PublicLinkComboPopupDelegate(_ProjectsComboPopupDelegate):
    """Use the exact projects popup palette for public-link combos."""


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

    Goal:
    - single rounded border (no double frames)
    - solid background (no black/unpainted strips)
    - consistent hover/selection for items

    Note: QComboBox popups are hosted in a separate top-level widget, so pure QSS
    selectors are not always reliable.
    """
    try:
        if getattr(QComboBox, "_larix_popup_border_patched", False):
            return

        def _is_dark(widget) -> bool:
            try:
                c = widget.palette().color(widget.backgroundRole())
                y = (c.red() * 299 + c.green() * 587 + c.blue() * 114) / 1000
                return y < 140
            except Exception:
                return False

        _orig_show = QComboBox.showPopup

        def _show_popup(self):
            # Sizing hints before Qt computes popup geometry.
            try:
                cnt = int(self.count())
            except Exception:
                cnt = -1
            is_public_link_combo = self.objectName() in {
                "publicLinkValidityCombo",
                "publicLinkAccessCombo",
            }

            try:
                if cnt > 0:
                    self.setMaxVisibleItems(cnt if is_public_link_combo else min(24, cnt))
            except Exception:
                pass

            try:
                view = self.view()
                if view is not None and cnt > 0:
                    try:
                        max_items = int(self.maxVisibleItems() or 10)
                    except Exception:
                        max_items = 10

                    if is_public_link_combo or cnt <= max_items:
                        view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                    else:
                        view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
                    view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                    view.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)

            except Exception:
                pass

            # Install the delegate before Qt creates/shows the popup. Changing
            # it from the deferred styling callback can close the first popup.
            try:
                if self.objectName() in {"publicLinkValidityCombo", "publicLinkAccessCombo"}:
                    view = self.view()
                    if not isinstance(view.itemDelegate(), _PublicLinkComboPopupDelegate):
                        view.setItemDelegate(_PublicLinkComboPopupDelegate(view))
                    # Apply the row metrics before Qt sizes the native popup.
                    # The deferred full stylesheet uses the same metrics; applying
                    # them only after showPopup() would make the first popup too short.
                    view.setStyleSheet(
                        view.styleSheet()
                        + "QAbstractItemView::item { padding: 6px 10px; margin: 2px; }"
                    )
                    view.doItemsLayout()
                    total_rows_height = sum(
                        max(0, int(view.sizeHintForRow(row)))
                        for row in range(max(0, cnt))
                    )
                    margins = view.contentsMargins()
                    frame = int(view.frameWidth())
                    # Include the view frame/margins and the small inset used by
                    # the native combo container, but do not affect other combos.
                    popup_view_height = (
                        total_rows_height
                        + margins.top()
                        + margins.bottom()
                        + (frame * 2)
                        + 10
                    )
                    if popup_view_height > 0:
                        view.setMinimumHeight(popup_view_height)
                        view.setMaximumHeight(popup_view_height)
                    view._larix_public_link_combo_delegate = True
            except Exception:
                pass

            _orig_show(self)

            def _apply():
                try:
                    view = self.view()
                    if view is None or not isinstance(view, QAbstractItemView):
                        return

                    # Qt recreates/configures the popup after showPopup(), so the
                    # root is identified here before its dedicated stylesheet is set.
                    popup_root = view.window()
                    if popup_root is not None:
                        popup_root.setObjectName("_larix_combo_popup")
                        popup_root.setAttribute(Qt.WA_StyledBackground, True)
                        popup_root.setAutoFillBackground(True)

                    try:
                        is_projects_combo = (self.objectName() == "projectsCombo")
                    except Exception:
                        is_projects_combo = False

                    # The projects popup is themed by theme.py and ui_helpers.py.  Keep
                    # this platform patch for other combo boxes, but do not overwrite the
                    # projects popup container or its view with a competing stylesheet.
                    if is_projects_combo:
                        return

                    dark = _is_dark(self)
                    fg = "#e0e0e0" if dark else "#222222"
                    fg_hover = "#e0e0e0" if dark else "#000000"
                    hover_bg = "rgba(247, 146, 30, 0.18)" if dark else "rgba(247, 146, 30, 0.08)"
                    sel_bg = "rgba(247, 146, 30, 0.28)" if dark else "rgba(247, 146, 30, 0.12)"
                    sel_hover_bg = "rgba(247, 146, 30, 0.36)" if dark else "rgba(247, 146, 30, 0.20)"

                    # Find the real popup container and style it (single border).
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
                    except Exception:
                        popup = None

                    if popup is None:
                        try:
                            popup = view.window()
                        except Exception:
                            popup = None

                    if popup is not None:
                        # Some styles are applied to the real top-level popup window.
                        # Depending on Qt version/platform, `popup` may be an inner container.
                        popups = []
                        try:
                            popups.append(popup)
                        except Exception:
                            pass
                        try:
                            wtop = popup.window()
                            if wtop is not None and wtop is not popup:
                                popups.append(wtop)
                        except Exception:
                            pass
                        try:
                            wv = view.window()
                            if wv is not None and wv not in popups:
                                popups.append(wv)
                        except Exception:
                            pass
                        try:
                            ap = QApplication.instance().activePopupWidget()  # type: ignore[attr-defined]
                            if ap is not None and ap not in popups:
                                popups.append(ap)
                        except Exception:
                            pass

                        for pw in list(popups) or [popup]:
                            try:
                                pw.setAttribute(Qt.WA_StyledBackground, True)
                                pw.setAutoFillBackground(True)
                            except Exception:
                                pass

                        # Remove native popup shadow (shows as dark right/bottom border on Windows).
                        # On Windows this "shadow" is often drawn outside the widget; the most
                        # reliable way to remove it is using a frameless + translucent popup
                        # and painting our own opaque rounded container.
                        for pw in list(popups) or [popup]:
                            try:
                                try:
                                    pw.setGraphicsEffect(None)
                                except Exception:
                                    pass
                                try:
                                    pw.setProperty("_q_windowsDropShadow", False)
                                except Exception:
                                    pass
                                try:
                                    pw.setAttribute(Qt.WA_TranslucentBackground, True)
                                except Exception:
                                    pass
                            except Exception:
                                pass

                        # On Windows, the system (DWM) shadow can remain even with
                        # NoDropShadowWindowHint. Switching the popup to frameless
                        # reliably removes the native black shadow/border.
                        try:
                            for pw in list(popups) or [popup]:
                                if pw is None:
                                    continue
                                # Do not replace Qt's native popup window flags.
                                if pw.property("_larix_frameless_popup") or not pw.property("_larix_use_frameless_popup"):
                                    continue
                                pw.setProperty("_larix_frameless_popup", True)

                                # Force a native window handle so window-flag changes
                                # actually recreate the platform popup.
                                try:
                                    pw.setAttribute(Qt.WA_NativeWindow, True)
                                except Exception:
                                    pass
                                try:
                                    _ = pw.winId()
                                except Exception:
                                    pass

                                # Hard-disable DWM shadow on Windows (Qt flags are not always enough).
                                try:
                                    import sys
                                    if sys.platform.startswith("win"):
                                        import ctypes
                                        from ctypes import wintypes
                                        hwnd = int(pw.winId())
                                        if hwnd:
                                            DWMWA_NCRENDERING_POLICY = 2
                                            DWMNCRP_DISABLED = 1
                                            DWMWA_TRANSITIONS_FORCEDISABLED = 3
                                            dwm = ctypes.WinDLL("dwmapi")
                                            val = ctypes.c_int(DWMNCRP_DISABLED)
                                            dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), DWMWA_NCRENDERING_POLICY, ctypes.byref(val), ctypes.sizeof(val))
                                            val2 = ctypes.c_int(1)
                                            dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), DWMWA_TRANSITIONS_FORCEDISABLED, ctypes.byref(val2), ctypes.sizeof(val2))
                                except Exception:
                                    pass

                                try:
                                    pw.hide()
                                except Exception:
                                    pass
                                try:
                                    flags = pw.windowFlags()
                                    try:
                                        flags |= Qt.FramelessWindowHint
                                    except Exception:
                                        pass
                                    try:
                                        flags |= Qt.NoDropShadowWindowHint
                                    except Exception:
                                        pass
                                    pw.setWindowFlags(flags)
                                except Exception:
                                    pass
                                try:
                                    pw.setProperty("_q_windowsDropShadow", False)
                                except Exception:
                                    pass
                                try:
                                    try:
                                        _ = pw.winId()
                                    except Exception:
                                        pass
                                    pw.show()
                                except Exception:
                                    pass
                        except Exception:
                            pass

                        # Kill native QFrame border/shadow (can look like a black bar).
                        for pw in list(popups) or [popup]:
                            try:
                                if isinstance(pw, QFrame):
                                    try:
                                        pw.setFrameShape(QFrame.NoFrame)
                                    except Exception:
                                        pass
                                    try:
                                        pw.setLineWidth(0)
                                        pw.setMidLineWidth(0)
                                    except Exception:
                                        pass
                            except Exception:
                                pass

                        # Inner popup container is usually QFrame#qt_combobox_popup.
                        # Remove its frame/shadow too.
                        try:
                            for fr in (popup.findChildren(QFrame) if popup is not None else []):
                                try:
                                    fr.setFrameShape(QFrame.NoFrame)
                                except Exception:
                                    pass
                                try:
                                    fr.setLineWidth(0)
                                    fr.setMidLineWidth(0)
                                except Exception:
                                    pass
                                try:
                                    fr.setFrameShadow(QFrame.Plain)
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        try:
                            for pw in list(popups) or [popup]:
                                try:
                                    lay = pw.layout()
                                    if lay is not None:
                                        lay.setContentsMargins(4, 4, 4, 4)
                                        lay.setSpacing(0)
                                    else:
                                        pw.setContentsMargins(4, 4, 4, 4)
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        try:
                            popup_bg = "#1e1e1e" if dark else "#FFFFFF"
                            # Paint an opaque rounded container inside the translucent popup.
                            # This avoids the system shadow while keeping the popup itself non-transparent.
                            for pw in list(popups) or [popup]:
                                try:
                                    if popup is not None:
                                        popup.setObjectName("_larix_combo_popup")
                                    # The objectName is deliberately scoped to the
                                    # actual top-level popup, never to its children.
                                    pw.setStyleSheet(
                                        f"QFrame#_larix_combo_popup {{ background: {popup_bg}; border: 1px solid #FFA74B; border-radius: 12px; }}"
                                    )
                                except Exception:
                                    pass
                        except Exception:
                            pass

                        # Ensure the popup window itself is clipped to rounded corners.
                        # (Stylesheet border-radius alone doesn't always clip top-level popups on Windows.)
                        try:
                            def _apply_mask():
                                try:
                                    for pw in list(popups) or [popup]:
                                        if pw is None:
                                            continue
                                        r = QRectF(pw.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
                                        path = QPainterPath()
                                        path.addRoundedRect(r, 12.0, 12.0)
                                        region = QRegion(path.toFillPolygon().toPolygon())
                                        pw.setMask(region)
                                except Exception:
                                    pass
                            # Keep the native popup shape; a mask on a translucent
                            # native window can expose a black DWM border on Windows.
                            # QTimer.singleShot(0, _apply_mask)
                        except Exception:
                            pass

                    # Hover tracking.
                    try:
                        view.setMouseTracking(True)
                        view.viewport().setMouseTracking(True)
                        view.setAttribute(Qt.WA_Hover, True)
                        view.viewport().setAttribute(Qt.WA_Hover, True)
                    except Exception:
                        pass

                    # Avoid native frame (often shows as a black border).
                    try:
                        view.setFrameShape(QFrame.NoFrame)
                    except Exception:
                        pass

                    if is_projects_combo:
                        try:
                            delg = _ProjectsComboPopupDelegate(view)
                            view.setItemDelegate(delg)
                            view._larix_projects_combo_delegate = True
                        except Exception:
                            pass
                        bg = "#1e1e1e" if dark else "#FFFFFF"
                        view.setStyleSheet(
                            f"QAbstractItemView {{ background: {bg}; border: none; outline: none; selection-background-color: {sel_bg}; selection-color: {fg}; }}"
                            f"QAbstractItemView::viewport {{ background: {bg}; border: none; outline: none; }}"
                            f"QAbstractItemView {{ color: {fg}; }}"
                            "QAbstractItemView::item { padding: 4px 8px; margin: 0px; border: 0px; border-top: 0px; border-bottom: 0px; outline: 0; }"
                            "QAbstractItemView::item:hover { border: 0px; border-top: 0px; border-bottom: 0px; outline: 0; }"
                            "QAbstractItemView::item:selected { border: 0px; border-top: 0px; border-bottom: 0px; outline: 0; }"
                            "QAbstractItemView::item:selected:hover { border: 0px; border-top: 0px; border-bottom: 0px; outline: 0; }"
                            "QAbstractItemView::item:focus { border: 0px; border-top: 0px; border-bottom: 0px; outline: 0; }"
                            "QAbstractItemView::item:selected:active { border: 0px; border-top: 0px; border-bottom: 0px; outline: 0; }"
                            "QAbstractItemView::item:selected:!active { border: 0px; border-top: 0px; border-bottom: 0px; outline: 0; }"
                            "QListView::item { padding: 4px 8px; margin: 0px; border: 0px; border-top: 0px; border-bottom: 0px; outline: 0; }"
                            "QListView::item:hover { border: 0px; border-top: 0px; border-bottom: 0px; outline: 0; }"
                            "QListView::item:selected { border: 0px; border-top: 0px; border-bottom: 0px; outline: 0; }"
                            "QListView::item:selected:hover { border: 0px; border-top: 0px; border-bottom: 0px; outline: 0; }"
                            "QListView::item:focus { border: 0px; border-top: 0px; border-bottom: 0px; outline: 0; }"
                            "QListView::item:selected:active { border: 0px; border-top: 0px; border-bottom: 0px; outline: 0; }"
                            "QListView::item:selected:!active { border: 0px; border-top: 0px; border-bottom: 0px; outline: 0; }"
                        )
                    else:
                        bg = "#1e1e1e" if dark else "#FFFFFF"
                        view.setStyleSheet(
                            f"QAbstractItemView {{ background: {bg}; border: none; outline: none; selection-background-color: {sel_bg}; selection-color: {fg}; }}"
                            f"QAbstractItemView::viewport {{ background: {bg}; }}"
                            f"QAbstractItemView {{ color: {fg}; }}"
                            "QAbstractItemView::item { padding: 6px 10px; margin: 2px; border: 1px solid transparent; border-radius: 8px; }"
                            f"QAbstractItemView::item:hover {{ background: {hover_bg}; border-color: #FFA74B; color: {fg_hover}; }}"
                            f"QAbstractItemView::item:selected {{ background: {sel_bg}; border-color: #FFA74B; color: {fg_hover}; }}"
                            f"QAbstractItemView::item:selected:hover {{ background: {sel_hover_bg}; border-color: #E07E12; color: {fg_hover}; }}"
                        )
                except Exception:
                    pass

            QTimer.singleShot(0, _apply)

        QComboBox.showPopup = _show_popup
        QComboBox._larix_popup_border_patched = True
    except Exception:
        pass
