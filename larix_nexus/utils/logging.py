# -*- coding: utf-8 -*-

import os
import sys
import logging
from typing import Any, Callable

def program_dir() -> str:
    """Return directory where program is running from.
    - If frozen (PyInstaller), use the executable's directory.
    - Else, use the directory of this file; fallback to CWD.
    """
    try:
        if getattr(sys, "frozen", False):
            d = os.path.dirname(sys.executable) or os.getcwd()
            return os.path.abspath(d)
    except Exception:
        pass
    try:
        return os.path.abspath(os.path.dirname(__file__))
    except Exception:
        return os.getcwd()

_SYNC_LOGGER = None  # type: ignore[var-annotated]

def _sync_log_path() -> str:
    try:
        base = program_dir()
    except Exception:
        base = os.getcwd()
    # write into a predictable folder near the app
    path = os.path.join(base, "sync", "_sync_debug.log")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except Exception:
        pass
    return path

def _sync_logger() -> logging.Logger:
    global _SYNC_LOGGER
    if _SYNC_LOGGER is not None:
        return _SYNC_LOGGER
    logger = logging.getLogger("sync")
    logger.setLevel(logging.DEBUG)
    # avoid duplicate handlers on reload
    if not logger.handlers:
        try:
            fh = logging.FileHandler(_sync_log_path(), mode="a", encoding="utf-8")
            fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
            fh.setFormatter(fmt)
            logger.addHandler(fh)
        except Exception:
            pass
    _SYNC_LOGGER = logger
    return logger

def sync_log(msg: str, *args):
    try:
        _sync_logger().debug(msg.format(*args))
    except Exception:
        pass

def sync_exc(msg: str):
    try:
        _sync_logger().exception(msg)
    except Exception:
        pass

def _cleanup_sync_log_file() -> None:
    """Flush sync debug log on app shutdown.

    ВАЖНО: лог не удаляем, чтобы история синхронизаций
    (включая список синхронизированных папок) сохранялась между запусками.
    """
    try:
        logger = _sync_logger()
        # Detach and close our handlers
        for h in list(logger.handlers):
            try:
                h.flush()
            except Exception:
                pass
            try:
                h.close()
            except Exception:
                pass
            try:
                logger.removeHandler(h)
            except Exception:
                pass
    except Exception:
        pass
