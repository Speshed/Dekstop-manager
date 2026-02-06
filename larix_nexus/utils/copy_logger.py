# -*- coding: utf-8 -*-
"""Copy/Move operations logger."""

import os
from datetime import datetime
from pathlib import Path

COPY_LOG_FILE = None

def _get_log_dir() -> str:
    """Get directory for log files (APPDATA on Windows)."""
    try:
        app_data = os.getenv("APPDATA") or os.getenv("LOCALAPPDATA") or os.path.expanduser("~/.config")
        log_dir = os.path.join(app_data, "LarixNexus")
        os.makedirs(log_dir, exist_ok=True)
        return log_dir
    except Exception:
        return os.getcwd()

def get_copy_log_file() -> str:
    """Get path to copy log file in APPDATA."""
    global COPY_LOG_FILE
    if COPY_LOG_FILE is not None:
        return COPY_LOG_FILE

    try:
        log_dir = _get_log_dir()
        log_file = os.path.join(log_dir, "copy_logs.txt")
        COPY_LOG_FILE = str(log_file)
        return COPY_LOG_FILE
    except Exception:
        # Fallback to current directory
        return os.path.join(os.getcwd(), "copy_logs.txt")

def copy_log(msg: str, *args, **kwargs):
    """Write log message to copy log file."""
    try:
        log_file = get_copy_log_file()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Extract component if provided
        component = kwargs.pop('component', '')
        if args:
            try:
                msg = msg.format(*args)
            except Exception:
                pass
        
        # Add component prefix if provided
        if component:
            line = f"[{timestamp}] [{component}] {msg}\n"
        else:
            line = f"[{timestamp}] {msg}\n"
        
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(line)
            f.flush()
    except Exception:
        pass

def clear_copy_log():
    """Clear copy log file."""
    try:
        log_file = get_copy_log_file()
        if os.path.exists(log_file):
            os.remove(log_file)
    except Exception:
        pass
