# -*- coding: utf-8 -*-
"""Crash diagnostics helpers.

This app sometimes exits without a Python exception (native crash / Qt abort).
We install:
- faulthandler to dump Python stacks on fatal errors
- sys/threading exception hooks
- optional Qt message handler

Logs go to %APPDATA%/LarixNexus/crash_diagnostics.log on Windows.
"""

from __future__ import annotations

import atexit
import faulthandler
import os
import sys
import threading
import traceback
from datetime import datetime

_FH = None
_LOG_PATH = None
_INSTALLED = False


def _get_log_dir() -> str:
    try:
        app_data = os.getenv("APPDATA") or os.path.expanduser("~/.config")
        log_dir = os.path.join(app_data, "LarixNexus")
        os.makedirs(log_dir, exist_ok=True)
        return log_dir
    except Exception:
        return os.getcwd()


def _get_log_path() -> str:
    return os.path.join(_get_log_dir(), "crash_diagnostics.log")


def _ts() -> str:
    try:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def _write(line: str) -> None:
    global _LOG_PATH
    try:
        if not _LOG_PATH:
            _LOG_PATH = _get_log_path()
        with open(_LOG_PATH, "a", encoding="utf-8", buffering=1) as f:
            f.write(line.rstrip("\n") + "\n")
            f.flush()
    except Exception:
        pass


def _install_faulthandler() -> None:
    global _FH, _LOG_PATH
    if _FH is not None:
        return
    _LOG_PATH = _get_log_path()
    try:
        _FH = open(_LOG_PATH, "a", encoding="utf-8", buffering=1)
    except Exception:
        _FH = None
        return

    try:
        _FH.write(f"\n{'='*70}\n{_ts()} - crash diagnostics enabled\n{'='*70}\n")
        _FH.flush()
    except Exception:
        pass

    try:
        faulthandler.enable(file=_FH, all_threads=True)
    except Exception:
        pass

    # Best-effort registration for common fatal signals
    try:
        import signal

        for sig_name in ("SIGABRT", "SIGSEGV", "SIGFPE", "SIGILL"):
            sig = getattr(signal, sig_name, None)
            if sig is not None:
                try:
                    faulthandler.register(sig, file=_FH, all_threads=True)
                except Exception:
                    pass
    except Exception:
        pass


def _install_exception_hooks() -> None:
    prev_sys_hook = getattr(sys, "excepthook", None)

    def _sys_excepthook(exc_type, exc, tb):
        try:
            _write(f"[{_ts()}] UNHANDLED EXCEPTION: {exc_type.__name__}: {exc}")
            _write("".join(traceback.format_exception(exc_type, exc, tb)))
        except Exception:
            pass
        if callable(prev_sys_hook):
            try:
                prev_sys_hook(exc_type, exc, tb)
            except Exception:
                pass

    sys.excepthook = _sys_excepthook

    # Thread exceptions (Python 3.8+)
    if hasattr(threading, "excepthook"):
        prev_thr_hook = threading.excepthook

        def _thr_excepthook(args):
            try:
                _write(
                    f"[{_ts()}] UNHANDLED THREAD EXCEPTION in {getattr(args, 'thread', None)}: "
                    f"{args.exc_type.__name__}: {args.exc_value}"
                )
                _write("".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))
            except Exception:
                pass
            try:
                prev_thr_hook(args)
            except Exception:
                pass

        threading.excepthook = _thr_excepthook


def _install_qt_message_handler() -> None:
    try:
        from PySide6 import QtCore

        def _handler(mode, context, message):
            try:
                cat = "QT"
                try:
                    # QtMsgType enums stringify differently across versions
                    cat = str(mode)
                except Exception:
                    pass
                _write(f"[{_ts()}] {cat}: {message}")
            except Exception:
                pass

        QtCore.qInstallMessageHandler(_handler)
    except Exception:
        pass


def install_crash_diagnostics(app=None) -> str:
    """Install crash diagnostics and return the log path."""
    global _INSTALLED, _LOG_PATH
    if _INSTALLED:
        return _LOG_PATH or _get_log_path()

    _install_faulthandler()
    _install_exception_hooks()
    _install_qt_message_handler()

    try:
        _write(f"[{_ts()}] install_crash_diagnostics: pid={os.getpid()} python={sys.version.split()[0]}")
    except Exception:
        pass

    if app is not None:
        try:
            def _on_about_to_quit():
                _write(f"[{_ts()}] Qt aboutToQuit")

            app.aboutToQuit.connect(_on_about_to_quit)
        except Exception:
            pass

    def _on_exit():
        _write(f"[{_ts()}] atexit: normal shutdown")
        try:
            if _FH is not None:
                _FH.flush()
        except Exception:
            pass

    try:
        atexit.register(_on_exit)
    except Exception:
        pass

    _INSTALLED = True
    return _LOG_PATH or _get_log_path()
