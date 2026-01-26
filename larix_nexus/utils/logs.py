# -*- coding: utf-8 -*-
"""Centralized logging system for Larix Nexus Desktop.

Logs are stored in: %APPDATA%\\LarixNexus\\logs.json
Log file is cleared on each application start.

Usage:
    from larix_nexus.utils.logs import sync_log, sync_exc, clear_logs
    sync_log("Message")  # Write to logs.json
    sync_exc("Error message")  # Write exception traceback
    clear_logs()  # Clear logs.json
"""

import os
import sys
import json
import traceback
from datetime import datetime
from typing import Any, Dict
from threading import Lock

# Import settings directory
from .settings import _settings_dir


# ============================================================================
# LOG FILE PATHS
# ============================================================================

def _logs_path() -> str:
    """Get path to logs.json file."""
    logs_dir = _settings_dir()
    return os.path.join(logs_dir, "logs.json")


# ============================================================================
# LOCK AND BUFFER
# ============================================================================

_log_lock = Lock()
_log_buffer: list[Dict[str, Any]] = []
_max_buffer_size = 100  # Flush buffer every 100 entries


# ============================================================================
# LOG FUNCTIONS
# ============================================================================

def _flush_buffer():
    """Flush log buffer to file."""
    global _log_buffer
    
    if not _log_buffer:
        return
    
    try:
        path = _logs_path()
        logs = []
        
        # Load existing logs
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    logs = json.load(f)
            except Exception:
                logs = []
        
        # Append buffered logs
        logs.extend(_log_buffer)
        
        # Write all logs
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(logs, f, indent=2, ensure_ascii=False)
        
        _log_buffer = []
    except Exception:
        pass


def _write_log(level: str, message: str, category: str = "APP"):
    """Write a single log entry to buffer."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "level": level,
        "category": category,
        "message": message
    }
    
    with _log_lock:
        _log_buffer.append(entry)
        if len(_log_buffer) >= _max_buffer_size:
            _flush_buffer()


def sync_log(msg: str, *args):
    """Write SYNC log entry.
    
    Args:
        msg: Log message with placeholders
        *args: Values for placeholders
    """
    try:
        formatted = msg.format(*args) if args else msg
        _write_log("DEBUG", formatted, "SYNC")
    except Exception:
        pass


def sync_info(msg: str, *args):
    """Write INFO log entry."""
    try:
        formatted = msg.format(*args) if args else msg
        _write_log("INFO", formatted, "SYNC")
    except Exception:
        pass


def sync_warn(msg: str, *args):
    """Write WARNING log entry."""
    try:
        formatted = msg.format(*args) if args else msg
        _write_log("WARN", formatted, "SYNC")
    except Exception:
        pass


def sync_error(msg: str, *args):
    """Write ERROR log entry."""
    try:
        formatted = msg.format(*args) if args else msg
        _write_log("ERROR", formatted, "SYNC")
    except Exception:
        pass


def sync_exc(msg: str, exc: Exception | None = None):
    """Write EXCEPTION log entry with traceback.
    
    Args:
        msg: Error message
        exc: Exception object (if not provided, uses sys.exc_info())
    """
    try:
        if exc is None:
            exc_info = sys.exc_info()
            if exc_info and exc_info[0] is not None:
                exc = exc_info[1]
        
        if exc is None:
            error_msg = f"{msg}: No exception available"
            tb_str = "No traceback available"
        else:
            error_msg = f"{msg}: {type(exc).__name__}: {str(exc)}"
            tb_str = traceback.format_exc()
        
        _write_log("ERROR", error_msg, "SYNC")
        
        # Write traceback as separate entry
        with _log_lock:
            _log_buffer.append({
                "timestamp": datetime.now().isoformat(),
                "level": "ERROR",
                "category": "SYNC",
                "message": f"TRACEBACK for {msg}",
                "traceback": tb_str
            })
            if len(_log_buffer) >= _max_buffer_size:
                _flush_buffer()
    except Exception:
        pass


def app_log(msg: str, *args):
    """Write APP log entry."""
    try:
        formatted = msg.format(*args) if args else msg
        _write_log("DEBUG", formatted, "APP")
    except Exception:
        pass


def app_info(msg: str, *args):
    """Write APP INFO log entry."""
    try:
        formatted = msg.format(*args) if args else msg
        _write_log("INFO", formatted, "APP")
    except Exception:
        pass


def app_error(msg: str, *args):
    """Write APP ERROR log entry."""
    try:
        formatted = msg.format(*args) if args else msg
        _write_log("ERROR", formatted, "APP")
    except Exception:
        pass


# ============================================================================
# LOG MANAGEMENT
# ============================================================================

def clear_logs():
    """Clear logs.json file on application start."""
    try:
        path = _logs_path()
        if os.path.exists(path):
            with open(path, 'w', encoding='utf-8') as f:
                json.dump([], f)
    except Exception:
        pass


def get_logs() -> list:
    """Get all logs from file."""
    try:
        path = _logs_path()
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        return []


def finalize():
    """Flush remaining logs and close file."""
    _flush_buffer()


# Auto-flush on import
def _on_import():
    """Clear logs when module is imported (application start)."""
    clear_logs()

_on_import()
