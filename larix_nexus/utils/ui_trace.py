# -*- coding: utf-8 -*-
"""UI trace logger.

Writes lightweight diagnostics to a dedicated log file to help debug native
crashes (access violations) where Python exceptions are not available.

Log path (Windows): %APPDATA%/LarixNexus/ui_trace.log
"""

from __future__ import annotations

import os
import threading
from datetime import datetime

from larix_nexus.utils.paths import logs_dir

_LOG_PATH = None


def _get_log_dir() -> str:
    try:
        log_dir = logs_dir()
        os.makedirs(log_dir, exist_ok=True)
        return log_dir
    except Exception:
        return os.getcwd()


def log_path() -> str:
    global _LOG_PATH
    if _LOG_PATH is None:
        _LOG_PATH = os.path.join(_get_log_dir(), "ui_trace.log")
    return _LOG_PATH


def _ts() -> str:
    try:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    except Exception:
        return ""


def _thread_tag() -> str:
    try:
        t = threading.current_thread()
        return f"tid={t.ident} name={t.name}"
    except Exception:
        return "tid=?"


def _qt_thread_tag() -> str:
    try:
        from PySide6.QtCore import QThread
        # currentThreadId returns sip.voidptr-ish; stringify is fine
        return f"qt_tid={QThread.currentThreadId()}"
    except Exception:
        return "qt_tid=?"


def trace(msg: str, *args) -> None:
    """Append a single line to ui_trace.log."""
    try:
        if args:
            try:
                msg = msg.format(*args)
            except Exception:
                pass
        line = f"[{_ts()}] [{_thread_tag()}] [{_qt_thread_tag()}] {msg}\n"
        with open(log_path(), "a", encoding="utf-8", buffering=1) as f:
            f.write(line)
            f.flush()
    except Exception:
        pass
