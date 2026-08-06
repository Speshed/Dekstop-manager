# -*- coding: utf-8 -*-
"""Safe dialog helpers to avoid nested event loop crashes.

This module provides non-blocking alternatives to QMessageBox.exec()
and QDialog.exec() which can cause access violation crashes on Windows
when used with timers and other signals.

Usage:
    from larix_nexus.utils.safe_dialogs import show_confirmation

    def my_callback(confirmed: bool):
        if confirmed:
            do_something()

    show_confirmation(parent, "Are you sure?", on_result=my_callback)
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QHBoxLayout,
    QVBoxLayout,
)
from .messagebox import message_dialog_pixmap
from .theme import themed_icon


def _trace(msg: str, *args) -> None:
    """Lightweight trace logging for debugging."""
    try:
        from larix_nexus.utils.ui_trace import trace as ui_trace

        ui_trace("safe_dialogs: " + msg, *args)
    except Exception:
        pass


def show_confirmation(
    parent,
    title: str,
    text: str,
    on_result: Optional[Callable[[bool], None]] = None,
    yes_text: str = "Да",
    no_text: str = "Нет",
    icon_path: Optional[str] = None,
) -> None:
    """Show a non-blocking confirmation dialog.

    This avoids QDialog.exec() and nested event loops which can cause
    access violation crashes on Windows.

    Args:
        parent: Parent widget
        title: Dialog title
        text: Dialog message
        on_result: Callback function that receives bool (True=Yes, False=No)
        yes_text: Text for Yes button (default "Да")
        no_text: Text for No button (default "Нет")
    """
    _trace("show_confirmation: creating dialog title={}", title)

    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setAttribute(Qt.WA_QuitOnClose, False)
    dlg.setMinimumWidth(360)

    layout = QVBoxLayout(dlg)
    row = QHBoxLayout()
    dark = QApplication.palette().color(QPalette.Window).value() < 128
    icon = QLabel()
    pm = None
    if icon_path:
        try:
            candidate = themed_icon(icon_path).pixmap(48, 48)
            if not candidate.isNull():
                pm = candidate
        except Exception:
            pm = None
    if pm is None or pm.isNull():
        pm = message_dialog_pixmap("alert", dark=dark, size=48)
    if not pm.isNull():
        icon.setPixmap(pm)
        icon.setFixedSize(48, 48)
        dlg.setWindowIcon(QIcon(pm))
    row.addWidget(icon, 0, Qt.AlignTop)

    msg_label = QLabel(text)
    msg_label.setWordWrap(True)
    row.addWidget(msg_label, 1)
    layout.addLayout(row)

    btn_box = QDialogButtonBox()
    yes_btn = QPushButton(yes_text)
    no_btn = QPushButton(no_text)

    btn_box.addButton(yes_btn, QDialogButtonBox.ButtonRole.AcceptRole)
    btn_box.addButton(no_btn, QDialogButtonBox.ButtonRole.RejectRole)
    layout.addWidget(btn_box)

    # Track cleanup to avoid multiple calls
    _cleanup_done = [False]
    _callback_called = [False]

    def _cleanup() -> None:
        """Safely cleanup dialog and signals."""
        if _cleanup_done[0]:
            return  # Already cleaned up

        _cleanup_done[0] = True
        _trace("show_confirmation: cleanup")

        # CRITICAL: Don't call dlg.close() or deleteLater() here!
        # Just disconnect signals and let Qt handle the rest
        try:
            yes_btn.clicked.disconnect(_on_yes)
        except Exception:
            pass
        try:
            no_btn.clicked.disconnect(_on_no)
        except Exception:
            pass
        try:
            dlg.finished.disconnect(_cleanup)
        except Exception:
            pass

    def _call_callback(result: bool) -> None:
        """Safely call the user callback."""
        if _callback_called[0]:
            return  # Already called

        _callback_called[0] = True
        _trace("show_confirmation: calling callback result={}", result)

        if on_result is not None:
            try:
                on_result(result)
            except Exception as e:
                _trace("show_confirmation: callback error: {}", str(e))

    def _on_yes() -> None:
        _trace("show_confirmation: on_yes")
        try:
            # Call callback FIRST
            _call_callback(True)
            # Let dialog close naturally by accepting it
            dlg.accept()
            # Cleanup after dialog is closed
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, _cleanup)
        except Exception as e:
            _trace("show_confirmation: on_yes error: {}", str(e))

    def _on_no() -> None:
        _trace("show_confirmation: on_no")
        try:
            # Call callback FIRST
            _call_callback(False)
            # Let dialog close naturally by rejecting it
            dlg.reject()
            # Cleanup after dialog is closed
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, _cleanup)
        except Exception as e:
            _trace("show_confirmation: on_no error: {}", str(e))

    yes_btn.clicked.connect(_on_yes)
    no_btn.clicked.connect(_on_no)
    dlg.finished.connect(_cleanup)

    try:
        dlg.setModal(True)
        dlg.open()
        _trace("show_confirmation: dialog opened")
    except Exception as e:
        _trace("show_confirmation: open error: {}", str(e))


def show_info(
    parent,
    title: str,
    text: str,
    on_result: Optional[Callable[[], None]] = None,
) -> None:
    """Show a non-blocking information dialog.

    Args:
        parent: Parent widget
        title: Dialog title
        text: Dialog message
        on_result: Callback function called when dialog is closed
    """
    _trace("show_info: creating dialog title={}", title)

    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setAttribute(Qt.WA_QuitOnClose, False)
    dlg.setMinimumWidth(360)

    layout = QVBoxLayout(dlg)
    row = QHBoxLayout()
    dark = QApplication.palette().color(QPalette.Window).value() < 128
    icon = QLabel()
    pm = message_dialog_pixmap("warning", dark=dark, size=48)
    if not pm.isNull():
        icon.setPixmap(pm)
        icon.setFixedSize(48, 48)
        dlg.setWindowIcon(QIcon(pm))
    row.addWidget(icon, 0, Qt.AlignTop)

    msg_label = QLabel(text)
    msg_label.setWordWrap(True)
    row.addWidget(msg_label, 1)
    layout.addLayout(row)

    btn_box = QDialogButtonBox(QDialogButtonBox.Ok)
    layout.addWidget(btn_box)

    def _cleanup() -> None:
        """Safely cleanup dialog and signals."""
        _trace("show_info: cleanup")
        try:
            btn_box.accepted.disconnect(_on_close)
        except Exception:
            pass
        try:
            dlg.finished.disconnect(_cleanup)
        except Exception:
            pass

    def _on_close() -> None:
        _trace("show_info: on_close")
        try:
            _cleanup()
            if on_result:
                on_result()
        except Exception as e:
            _trace("show_info: on_close error: {}", str(e))
        finally:
            try:
                dlg.setParent(None)
                dlg.deleteLater()
            except Exception:
                pass

    btn_box.accepted.connect(_on_close)
    dlg.finished.connect(_cleanup)

    try:
        dlg.setModal(True)
        dlg.open()
        _trace("show_info: dialog opened")
    except Exception as e:
        _trace("show_info: open error: {}", str(e))


def show_warning(
    parent,
    title: str,
    text: str,
    on_result: Optional[Callable[[], None]] = None,
) -> None:
    """Show a non-blocking warning dialog.

    Args:
        parent: Parent widget
        title: Dialog title
        text: Dialog message
        on_result: Callback function called when dialog is closed
    """
    _trace("show_warning: creating dialog title={}", title)

    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setAttribute(Qt.WA_QuitOnClose, False)
    dlg.setMinimumWidth(360)

    layout = QVBoxLayout(dlg)

    msg_label = QLabel(text)
    msg_label.setWordWrap(True)
    layout.addWidget(msg_label)

    btn_box = QDialogButtonBox(QDialogButtonBox.Ok)
    layout.addWidget(btn_box)

    def _cleanup() -> None:
        """Safely cleanup dialog and signals."""
        _trace("show_warning: cleanup")
        try:
            btn_box.accepted.disconnect(_on_close)
        except Exception:
            pass
        try:
            dlg.finished.disconnect(_cleanup)
        except Exception:
            pass

    def _on_close() -> None:
        _trace("show_warning: on_close")
        try:
            _cleanup()
            if on_result:
                on_result()
        except Exception as e:
            _trace("show_warning: on_close error: {}", str(e))
        finally:
            try:
                dlg.setParent(None)
                dlg.deleteLater()
            except Exception:
                pass

    btn_box.accepted.connect(_on_close)
    dlg.finished.connect(_cleanup)

    try:
        dlg.setModal(True)
        dlg.open()
        _trace("show_warning: dialog opened")
    except Exception as e:
        _trace("show_warning: open error: {}", str(e))
