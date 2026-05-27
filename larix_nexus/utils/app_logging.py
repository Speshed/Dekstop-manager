# -*- coding: utf-8 -*-
"""
Central logging configuration for Larix Nexus.
Redirects all logging (including print statements) to file.
"""

import sys
import os
import logging
from datetime import datetime
from typing import TextIO, Optional

from larix_nexus.utils.paths import logs_dir


def _get_env_bool(name: str, default: bool = False) -> bool:
    try:
        v = (os.getenv(name) or "").strip().lower()
        if v in ("1", "true", "yes", "y", "on"):
            return True
        if v in ("0", "false", "no", "n", "off"):
            return False
    except Exception:
        pass
    return default

def _get_log_dir() -> str:
    """Get the directory for log files."""
    try:
        log_dir = logs_dir()
        os.makedirs(log_dir, exist_ok=True)
        return log_dir
    except Exception:
        return os.getcwd()

def _get_main_log_path() -> str:
    """Get the main application log file path."""
    log_dir = _get_log_dir()
    return os.path.join(log_dir, "larix_nexus.log")

def _get_errors_log_path() -> str:
    """Get the errors-only log file path."""
    log_dir = _get_log_dir()
    return os.path.join(log_dir, "errors.log")


def reset_log_files() -> dict:
    """Delete existing log files so each run starts fresh.

    Controlled by env var `LARIX_KEEP_LOGS=1` to skip deletion.
    Returns dict with keys: deleted, failed, skipped, log_dir.
    """
    res = {"deleted": [], "failed": [], "skipped": False, "log_dir": ""}
    if _get_env_bool("LARIX_KEEP_LOGS", False):
        res["skipped"] = True
        try:
            res["log_dir"] = _get_log_dir()
        except Exception:
            pass
        return res

    try:
        log_dir = _get_log_dir()
        res["log_dir"] = log_dir
    except Exception:
        log_dir = os.getcwd()
        res["log_dir"] = log_dir

    base_files = [
        os.path.join(log_dir, "larix_nexus.log"),
        os.path.join(log_dir, "errors.log"),
        os.path.join(log_dir, "crash_diagnostics.log"),
        os.path.join(log_dir, "ui_trace.log"),
        os.path.join(log_dir, "sync.log"),
        os.path.join(log_dir, "copy_logs.txt"),
    ]

    # Rotated log files produced by RotatingFileHandler: <name>.1, <name>.2, ...
    rotated = []
    for base in ("larix_nexus.log",):
        for i in range(1, 21):
            rotated.append(os.path.join(log_dir, f"{base}.{i}"))

    for p in base_files + rotated:
        try:
            if p and os.path.exists(p):
                os.remove(p)
                res["deleted"].append(p)
        except Exception as e:
            res["failed"].append(f"{p}: {e}")

    # Best-effort recreate empty files so other code can assume they exist.
    for p in base_files:
        try:
            if not p:
                continue
            d = os.path.dirname(p)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write("")
        except Exception:
            pass

    return res

class FileAndConsoleRedirector:
    """Redirect sys.stdout and sys.stderr to both file and console."""
    
    def __init__(self, file_path: str, keep_console: bool = False):
        self.file_path = file_path
        self.keep_console = keep_console
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        self.log_file: Optional[TextIO] = None
        
    def start(self):
        """Start redirecting output."""
        try:
            # Open log file
            self.log_file = open(self.file_path, 'a', encoding='utf-8', buffering=1)
            
            # Create custom TextIO that writes to both file and optionally console
            if self.keep_console:
                class TeeOutput:
                    def __init__(self, file_obj, console_obj):
                        self.file_obj = file_obj
                        self.console_obj = console_obj
                    
                    def write(self, text):
                        self.file_obj.write(text)
                        self.file_obj.flush()
                        self.console_obj.write(text)
                        return len(text)
                    
                    def flush(self):
                        self.file_obj.flush()
                        self.console_obj.flush()
                
                self.tee = TeeOutput(self.log_file, self.original_stdout)
                sys.stdout = self.tee
                sys.stderr = self.tee
            else:
                # Redirect ONLY to file (not console)
                sys.stdout = self.log_file
                sys.stderr = self.log_file
        except Exception as e:
            print(f"[LOGGING ERROR] Failed to start redirection: {e}", file=self.original_stderr)
    
    def stop(self):
        """Stop redirecting output."""
        try:
            sys.stdout = self.original_stdout
            sys.stderr = self.original_stderr
            if self.log_file:
                self.log_file.close()
        except Exception:
            pass

def setup_logging(log_to_file: bool = True, keep_console: bool = False) -> FileAndConsoleRedirector | None:
    """
    Setup logging for the application.
    
    Args:
        log_to_file: If True, redirect all logging to file
        keep_console: If True, also show output in console (for debugging)
    
    Returns:
        FileAndConsoleRedirector instance (call stop() on app shutdown)
    """
    if not log_to_file:
        return None
    
    # Get main log path
    log_path = _get_main_log_path()
    
    # Configure root logger to log to file
    try:
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        
        # Remove all existing handlers
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # Add file handler with rotation
        from logging.handlers import RotatingFileHandler
        
        file_handler = RotatingFileHandler(
            log_path,
            mode='a',
            encoding='utf-8',
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5
        )
        
        # Simple format for main log
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

        errors_log_path = _get_errors_log_path()
        errors_handler = RotatingFileHandler(
            errors_log_path,
            mode='a',
            encoding='utf-8',
            maxBytes=10 * 1024 * 1024,
            backupCount=3
        )
        errors_handler.setLevel(logging.ERROR)
        errors_handler.setFormatter(formatter)
        root_logger.addHandler(errors_handler)
        
        # Also add console handler if keep_console is True
        if keep_console:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(formatter)
            root_logger.addHandler(console_handler)
        else:
            # When keep_console is False we still want logs (including sync/UI diagnostics)
            # to be written to the main log file. stdout/stderr are redirected to file,
            # so disabling propagation here only makes diagnostics harder.
            try:
                logging.getLogger("sync").propagate = True
            except Exception:
                pass
        
    except Exception as e:
        print(f"[LOGGING ERROR] Failed to setup logging: {e}")
    
    # Redirect stdout/stderr to capture print() statements
    redirector = FileAndConsoleRedirector(log_path, keep_console=keep_console)
    redirector.start()
    
    # Write startup message
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    separator = "=" * 70
    startup_msg = f"\n{separator}\n{timestamp} - Larix Nexus starting\n{separator}\n"
    
    try:
        if redirector.log_file:
            redirector.log_file.write(startup_msg)
            redirector.log_file.flush()
    except Exception:
        pass
    
    return redirector

# Global instance of redirector
_redirector: Optional[FileAndConsoleRedirector] = None

def start_logging(log_to_file: bool = True, keep_console: bool = False):
    """Start logging redirection (call at app startup)."""
    global _redirector
    if _redirector is None:
        _redirector = setup_logging(log_to_file=log_to_file, keep_console=keep_console)

def stop_logging():
    """Stop logging redirection (call at app shutdown)."""
    global _redirector
    if _redirector is not None:
        _redirector.stop()
        _redirector = None
