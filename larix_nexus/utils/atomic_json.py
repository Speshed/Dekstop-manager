# -*- coding: utf-8 -*-

import os
import json
import time
import threading
from typing import Any, Callable, Dict

_JSON_LOCKS: Dict[str, threading.Lock] = {}
_JSON_LOCKS_LOCK = threading.Lock()

def _get_json_lock(path: str) -> threading.Lock:
    """Get or create in-process lock for a JSON file path."""
    with _JSON_LOCKS_LOCK:
        if path not in _JSON_LOCKS:
            _JSON_LOCKS[path] = threading.Lock()
        return _JSON_LOCKS[path]

def _acquire_file_lock(lock_path: str, timeout: float = 15.0) -> bool:
    """Acquire file lock by creating .lock file. Windows-compatible retry loop."""
    import time
    start = time.time()
    while time.time() - start < timeout:
        try:
            # Try to create lock file exclusively (Windows doesn't support fcntl)
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.close(fd)
            return True
        except FileExistsError:
            time.sleep(0.1)  # Increased from 0.05
        except Exception:
            return False
    # Last attempt - try to remove stale lock and retry once
    try:
        if os.path.exists(lock_path):
            os.remove(lock_path)
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.close(fd)
            return True
    except Exception:
        pass
    return False

def _release_file_lock(lock_path: str) -> None:
    """Release file lock by removing .lock file."""
    try:
        if os.path.exists(lock_path):
            os.remove(lock_path)
    except Exception:
        pass

def atomic_read_json(path: str, default: Any = None) -> Any:
    """Atomically read JSON file with locking.
    
    Args:
        path: Absolute path to JSON file
        default: Value to return if file doesn't exist or is invalid
    
    Returns:
        Parsed JSON data or default
    """
    from .logging import sync_log, sync_exc
    lock = _get_json_lock(path)
    lock_path = path + ".lock"
    
    with lock:  # In-process lock
        if not _acquire_file_lock(lock_path):
            sync_log("ATOMIC_READ_JSON: Failed to acquire lock for '{}'", path)
            return default
        try:
            if not os.path.exists(path):
                return default
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data
        except Exception as e:
            sync_exc(f"ATOMIC_READ_JSON failed for '{path}': {e}")
            return default
        finally:
            _release_file_lock(lock_path)

def atomic_write_json(path: str, data: Any, ensure_dir: bool = True) -> bool:
    """Atomically write JSON file with tmp→os.replace + locking.
    
    Args:
        path: Absolute path to JSON file
        data: Data to serialize to JSON
        ensure_dir: Create parent directory if needed
    
    Returns:
        True on success, False on failure
    """
    from .logging import sync_log, sync_exc
    lock = _get_json_lock(path)
    lock_path = path + ".lock"
    
    with lock:  # In-process lock
        # Ensure parent directory exists BEFORE trying to acquire file lock
        if ensure_dir:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
            except Exception:
                return False
        
        if not _acquire_file_lock(lock_path, timeout=10.0):
            sync_log("ATOMIC_WRITE_JSON: Failed to acquire lock for '{}'", path)
            return False
        try:
            # Write to temp file first
            tmp_path = path + f".tmp.{os.getpid()}.{int(time.time() * 1000)}"
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            # Atomic replace
            os.replace(tmp_path, path)
            return True
        except Exception as e:
            sync_exc(f"ATOMIC_WRITE_JSON failed for '{path}': {e}")
            # Clean up temp file
            try:
                if 'tmp_path' in locals() and os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            return False
        finally:
            _release_file_lock(lock_path)

def atomic_update_json(path: str, updater: Callable[[Dict], Dict], default: Dict = None) -> bool:
    """Atomically update JSON file using updater function.
    
    Args:
        path: Absolute path to JSON file
        updater: Function that takes current data dict and returns updated dict
        default: Default dict if file doesn't exist
    
    Returns:
        True on success, False on failure
    """
    from .logging import sync_exc
    lock = _get_json_lock(path)
    lock_path = path + ".lock"
    
    with lock:
        if not _acquire_file_lock(lock_path, timeout=10.0):
            return False
        try:
            # Read current data
            current = default.copy() if default else {}
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        current = json.load(f)
                except Exception:
                    pass
            
            # Apply updater
            updated = updater(current)
            
            # Write atomically
            tmp_path = path + f".tmp.{os.getpid()}.{int(time.time() * 1000)}"
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(updated, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
            return True
        except Exception as e:
            sync_exc(f"ATOMIC_UPDATE_JSON failed for '{path}': {e}")
            try:
                if 'tmp_path' in locals() and os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            return False
        finally:
            _release_file_lock(lock_path)
