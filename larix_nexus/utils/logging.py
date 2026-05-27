# -*- coding: utf-8 -*-

import os
import sys
import logging
import logging.handlers
import uuid
import time
from typing import Any, Callable, Optional

from larix_nexus.utils.paths import app_data_dir, logs_dir as _logs_dir, logs_archive_dir as _logs_archive_dir

def program_dir() -> str:
    """Return directory where program is running from."""
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

def _settings_dir() -> str:
    r"""Get settings directory path (%APPDATA%\LarixNexus)."""
    return app_data_dir()

def _main_log_path() -> str:
    r"""Main application log path (%APPDATA%\LarixNexus\logs\larix_nexus.log)."""
    try:
        base = _logs_dir()
    except Exception:
        base = os.getcwd()
    try:
        os.makedirs(base, exist_ok=True)
    except Exception:
        pass
    return os.path.join(base, "larix_nexus.log")

_SYNC_LOGGER = None
_SYNC_CONTEXT = {}
_MAX_LOG_SIZE = 10 * 1024 * 1024
_MAX_LOG_FILES = 10

def _get_env_bool(var_name: str, default: bool = False) -> bool:
    """Get boolean environment variable."""
    try:
        val = os.getenv(var_name, "").strip().lower()
        if val in ("1", "true", "yes", "on"):
            return True
        elif val in ("0", "false", "no", "off"):
            return False
    except Exception:
        pass
    return default

def _sync_log_path() -> str:
    try:
        base = _logs_dir()
    except Exception:
        base = os.getcwd()
    path = os.path.join(base, "sync.log")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except Exception:
        pass
    return path

def _mask_secrets(msg: str) -> str:
    """Mask sensitive information in log messages."""
    try:
        if not msg:
            return msg
        
        import re
        # Mask Bearer tokens
        msg = re.sub(r'Bearer\s+[A-Za-z0-9\-._~+/]+=*', 'Bearer ***', msg)
        # Mask long alphanumeric sequences that look like tokens (32+ chars)
        msg = re.sub(r'\b[A-Za-z0-9]{32,}\b', '***', msg)
        # Mask authorization headers
        msg = re.sub(r'["\']Authorization["\']:\s*["\'][^"\']+["\']', '"Authorization": "***"', msg)
        # Mask password fields
        msg = re.sub(r'["\']password["\']:\s*["\'][^"\']+["\']', '"password": "***"', msg)
        # Mask token fields
        msg = re.sub(r'["\']token["\']:\s*["\'][^"\']+["\']', '"token": "***"', msg)
        
        return msg
    except Exception:
        return msg

class StructuredFormatter(logging.Formatter):
    """Custom formatter for structured logging."""
    
    def __init__(self):
        super().__init__()
        
    def format(self, record: logging.LogRecord) -> str:
        try:
            ts = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(record.created))
            ms = f"{int(record.created * 1000) % 1000:03d}"
            
            level = record.levelname
            if level == "DEBUG" and _get_env_bool("DEBUG_SYNC"):
                level = "TRACE"
            
            component = getattr(record, 'component', 'GEN')
            op = getattr(record, 'op', '')
            trace_id = getattr(record, 'trace_id', '')
            path = getattr(record, 'path', '')
            result = getattr(record, 'result', '')
            reason = getattr(record, 'reason', '')
            duration_ms = getattr(record, 'duration_ms', '')
            extra = getattr(record, 'extra', '')
            
            parts = [
                f"ts={ts}.{ms}",
                f"level={level}",
                f"component={component}"
            ]
            
            if op:
                parts.append(f"op={op}")
            if trace_id:
                parts.append(f"trace_id={trace_id}")
            if path:
                # Mask secrets in path
                safe_path = _mask_secrets(path)[:200]
                parts.append(f"path={safe_path}")
            if result:
                parts.append(f"result={result}")
            if reason:
                safe_reason = _mask_secrets(reason)[:200]
                parts.append(f"reason={safe_reason}")
            if duration_ms:
                parts.append(f"duration_ms={duration_ms}")
            if extra:
                safe_extra = _mask_secrets(str(extra))[:500]
                parts.append(f"extra={safe_extra}")
            
            msg = _mask_secrets(record.getMessage())[:1000]
            parts.append(f"msg={msg}")
            
            return " ".join(parts)
        except Exception:
            return f"ERROR_FORMATTING: {record.getMessage()}"

def _sync_logger() -> logging.Logger:
    global _SYNC_LOGGER
    if _SYNC_LOGGER is not None:
        return _SYNC_LOGGER
    logger = logging.getLogger("sync")
    logger.setLevel(logging.DEBUG)

    # Write all sync diagnostics to separate log file at:
    # %APPDATA%\LarixNexus\logs\sync.log
    try:
        logger.propagate = False
    except Exception:
        pass

    # Always use separate file handler for sync logs
    try:
        path = _sync_log_path()
        try:
            os.makedirs(_logs_archive_dir(), exist_ok=True)
        except Exception:
            pass
        handler = logging.handlers.RotatingFileHandler(
            path,
            mode='a',
            encoding='utf-8',
            maxBytes=_MAX_LOG_SIZE,
            backupCount=_MAX_LOG_FILES,
        )
        # Move rotated files into logs\archive\
        try:
            handler.namer = lambda name: os.path.join(_logs_archive_dir(), os.path.basename(name))
        except Exception:
            pass
        handler.setFormatter(StructuredFormatter())
        logger.addHandler(handler)
    except Exception:
        pass
    
    _SYNC_LOGGER = logger
    return logger

def sync_log(msg: str, *args, **kwargs):
    """Structured sync logging."""
    try:
        logger = _sync_logger()
        
        # Extract structured fields from kwargs
        component = kwargs.pop('component', 'GEN')
        op = kwargs.pop('op', '')
        trace_id = kwargs.pop('trace_id', '')
        path = kwargs.pop('path', '')
        result = kwargs.pop('result', '')
        reason = kwargs.pop('reason', '')
        duration_ms = kwargs.pop('duration_ms', '')
        extra = kwargs.pop('extra', '')
        
        # Format message with args
        formatted = msg.format(*args) if args else msg
        
        # Create record with custom fields
        record = logger.makeRecord(
            logger.name,
            logging.DEBUG,
            '',
            0,
            formatted,
            (),
            None
        )
        
        # Add custom fields
        record.component = component
        record.op = op
        record.trace_id = trace_id
        record.path = path
        record.result = result
        record.reason = reason
        record.duration_ms = duration_ms
        record.extra = extra
        
        logger.handle(record)
        
        # Flush for immediate visibility
        for handler in logger.handlers:
            handler.flush()
    except Exception:
        # Silent fail - don't print to console
        pass

def sync_exc(msg: str, **kwargs):
    """Log exception with traceback."""
    try:
        logger = _sync_logger()
        formatted_exc = msg.format(**kwargs) if kwargs else msg
        extra_msg = kwargs.get('extra', '')
        
        # Create record
        record = logger.makeRecord(
            logger.name,
            logging.ERROR,
            '',
            0,
            formatted_exc,
            (),
            None
        )
        
        record.component = kwargs.get('component', 'GEN')
        record.op = kwargs.get('op', '')
        record.trace_id = kwargs.get('trace_id', '')
        record.path = kwargs.get('path', '')
        record.result = 'fail'
        record.reason = kwargs.get('reason', 'exception')
        record.extra = extra_msg
        
        logger.handle(record)
        
        # Print traceback
        import traceback
        tb_lines = traceback.format_exc()
        for line in tb_lines.split('\n'):
            if line.strip():
                sync_log("{}", line, component='EXC', trace_id=kwargs.get('trace_id', ''))
        
        for handler in logger.handlers:
            handler.flush()
    except Exception:
        # Silent fail - don't print to console
        pass

def new_trace_id() -> str:
    """Generate new trace ID for sync operation."""
    return str(uuid.uuid4())[:8]

def is_debug_sync() -> bool:
    """Check if DEBUG_SYNC mode is enabled."""
    return _get_env_bool("DEBUG_SYNC", False)

def is_dry_run() -> bool:
    """Check if DRY_RUN mode is enabled."""
    return _get_env_bool("DRY_RUN", False)

def _cleanup_sync_log_file() -> None:
    """Flush sync debug log on app shutdown."""
    try:
        logger = _sync_logger()
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
