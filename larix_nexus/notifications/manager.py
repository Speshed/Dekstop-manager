# -*- coding: utf-8 -*-

import os
import json
import sys
import time
import logging
import threading
from typing import Optional, Dict, Any, Callable
from PySide6.QtCore import QSettings

from larix_nexus.utils.paths import (
    notifications_path as _new_notifications_path,
    app_data_dir,
    logs_dir as _logs_dir,
)

# --- Path helpers -------------------------------------------------------------

def program_dir() -> str:
    """Return the directory where the program is running from.
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

def _sync_logger() -> logging.Logger:
    global _SYNC_LOGGER
    if _SYNC_LOGGER is not None:
        return _SYNC_LOGGER
    logger = logging.getLogger("sync")
    logger.setLevel(logging.DEBUG)
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

def normalize_id(value) -> str:
    """Normalize document/folder identifiers to opaque strings."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return str(value).strip()

def normalize_project_id(value) -> str:
    """Normalize project identifiers to opaque strings."""
    return normalize_id(value)

# --- JSON atomic operations ---------------------------------------------------

# Global in-process locks per file path
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
    start = time.time()
    while time.time() - start < timeout:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.close(fd)
            return True
        except FileExistsError:
            time.sleep(0.1)
        except Exception:
            return False
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
    lock = _get_json_lock(path)
    lock_path = path + ".lock"
    
    with lock:
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
    lock = _get_json_lock(path)
    lock_path = path + ".lock"
    
    with lock:
        if ensure_dir:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
            except Exception:
                return False
        
        if not _acquire_file_lock(lock_path, timeout=10.0):
            sync_log("ATOMIC_WRITE_JSON: Failed to acquire lock for '{}'", path)
            return False
        try:
            tmp_path = path + f".tmp.{os.getpid()}.{int(time.time() * 1000)}"
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
            return True
        except Exception as e:
            sync_exc(f"ATOMIC_WRITE_JSON failed for '{path}': {e}")
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
    lock = _get_json_lock(path)
    lock_path = path + ".lock"
    
    with lock:
        if not _acquire_file_lock(lock_path, timeout=10.0):
            return False
        try:
            current = default.copy() if default else {}
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        current = json.load(f)
                except Exception:
                    pass
            
            updated = updater(current)
            
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

# --- Constants ----------------------------------------------------------------

SETTINGS_ORG = "Larix"
SETTINGS_APP = "NexusDesktop"
NOTIFY_DB_PATH = os.path.join(program_dir(), "notifications.db")
NOTIFY_SETTINGS_GROUP = "notifications/folder_subscriptions"

# --- Notifications storage (JSON-based) ---------------------------------------

def _notifications_path() -> str:
    """Get path to notifications JSON file (new location)."""
    return _new_notifications_path()


def _legacy_notifications_path() -> str:
    return os.path.join(app_data_dir(), "notifications.json")

def load_notifications() -> Dict:
    """Load all notifications. Returns empty structure if not found."""
    path = _notifications_path()
    default = {"version": 1, "subscriptions": {}}
    data = atomic_read_json(path, default=None)
    if data is not None:
        return data

    legacy = _legacy_notifications_path()
    if legacy != path and os.path.exists(legacy):
        sync_log("NOTIFY: legacy fallback read from '{}'", legacy)
        return atomic_read_json(legacy, default=default)

    return default

def save_notifications(notifications: Dict) -> bool:
    """Save all notifications."""
    path = _notifications_path()
    return atomic_write_json(path, notifications, ensure_dir=True)

def _notification_key(project_id: int | str, folder_id: int | str) -> str:
    return f"{normalize_project_id(project_id)}:{normalize_id(folder_id)}"


def init_notifications_db():
    """Initialize notifications storage (migrates legacy SQLite and QSettings if present)."""
    try:
        if os.path.exists(NOTIFY_DB_PATH):
            os.remove(NOTIFY_DB_PATH)
            sync_log("NOTIFY storage: removed legacy file '{}'", NOTIFY_DB_PATH)
    except Exception as e:
        sync_exc(f"Failed to remove legacy notifications db: {e}")
    
    try:
        old_settings = _app_settings()
        old_settings.beginGroup(NOTIFY_SETTINGS_GROUP)
        old_keys = old_settings.childKeys()
        
        if old_keys:
            sync_log("NOTIFY: migrating {} subscriptions from QSettings to JSON", len(old_keys))
            notifications = load_notifications()
            
            for key in old_keys:
                raw = old_settings.value(key)
                if raw:
                    try:
                        item = json.loads(str(raw))
                        if isinstance(item, dict):
                            notifications["subscriptions"][key] = item
                    except Exception:
                        pass
            
            save_notifications(notifications)
            
            old_settings.remove("")
        
        old_settings.endGroup()
    except Exception as e:
        sync_exc(f"Failed to migrate notifications: {e}")


def save_folder_notification(
    project_id: int | str,
    folder_id: int | str,
    folder_path: str,
    file_state: list,
    workspace_id: int | str | None = None,
) -> bool:
    """Save or update folder notification subscription."""
    project_id_norm = normalize_project_id(project_id)
    key = _notification_key(project_id_norm, folder_id)
    payload = {
        "project_id": project_id_norm,
        "workspace_id": normalize_id(workspace_id) if workspace_id is not None else "",
        "folder_id": normalize_id(folder_id),
        "folder_path": str(folder_path or ""),
        "file_state": list(file_state or []),
        "created_at": float(time.time()),
    }
    
    
    try:
        notifications = load_notifications()
        notifications["subscriptions"][key] = payload
        saved = save_notifications(notifications)
        if not saved:
            sync_log("NOTIFY save folder failed; operation=save_notifications")
        return bool(saved)
    except Exception as e:
        sync_log("NOTIFY save folder failed; error_type={}", type(e).__name__)
        return False


def remove_folder_notification(project_id: int | str, folder_id: int | str) -> bool:
    """Remove folder notification subscription."""
    key = _notification_key(project_id, folder_id)
    
    try:
        notifications = load_notifications()
        if key in notifications.get("subscriptions", {}):
            del notifications["subscriptions"][key]
            return bool(save_notifications(notifications))
    except Exception as e:
        sync_log("NOTIFY remove folder failed; error_type={}", type(e).__name__)
    return False


def load_folder_notifications() -> list[dict]:
    """Load all folder notification subscriptions."""
    init_notifications_db()
    
    try:
        notifications = load_notifications()
        subs = list(notifications.get("subscriptions", {}).values())
        for sub in subs:
            folder_id = sub.get("folder_id")
            folder_path = sub.get("folder_path")
            file_state = sub.get("file_state", [])
        return subs
    except Exception as e:
        sync_log("NOTIFY load folder subscriptions failed; error_type={}", type(e).__name__)
        return []


def is_folder_notification_enabled(project_id: int | str, folder_id: int | str) -> bool:
    """Check if notification is enabled for a folder."""
    key = _notification_key(project_id, folder_id)
    
    try:
        notifications = load_notifications()
        return key in notifications.get("subscriptions", {})
    except Exception:
        return False


def save_pending_notifications(pending_dict: dict) -> bool:
    """Save pending (unread) notifications to persistent storage."""
    try:
        notifications = load_notifications()
        pending_list = []
        for folder_id, notif_data in pending_dict.items():
            pending_list.append({
                "folder_id": normalize_id(folder_id),
                "project_id": normalize_project_id(notif_data.get("project_id", 0)),
                "workspace_id": normalize_id(notif_data.get("workspace_id") or ""),
                "folder_path": str(notif_data.get("folder_path", "")),
                "changes": list(notif_data.get("changes", [])),
                "current_files": list(notif_data.get("current_files", [])),
            })
        
        notifications["pending"] = pending_list
        saved = save_notifications(notifications)
        if not saved:
            sync_log("NOTIFY save pending failed; operation=save_notifications")
        return bool(saved)
    except Exception as e:
        sync_log("NOTIFY save pending failed; error_type={}", type(e).__name__)
        return False


def load_pending_notifications() -> dict:
    """Load pending (unread) notifications from persistent storage."""
    init_notifications_db()
    
    try:
        notifications = load_notifications()
        pending_list = notifications.get("pending", [])
        
        pending_dict = {}
        for item in pending_list:
            folder_id = item.get("folder_id")
            if folder_id:
                pending_dict[folder_id] = {
                    "project_id": item.get("project_id", 0),
                    "workspace_id": normalize_id(item.get("workspace_id") or ""),
                    "folder_path": item.get("folder_path", ""),
                    "changes": item.get("changes", []),
                    "current_files": item.get("current_files", []),
                }
        
        return pending_dict
    except Exception as e:
        sync_exc(f"Failed to load pending notifications: {e}")
        return {}


def save_user_actions_log(actions_log: list) -> bool:
    """Save user actions log to persistent storage."""
    try:
        notifications = load_notifications()
        notifications["user_actions"] = actions_log
        saved = save_notifications(notifications)
        if not saved:
            sync_log("NOTIFY save user actions failed; operation=save_notifications")
        return bool(saved)
    except Exception as e:
        sync_log("NOTIFY save user actions failed; error_type={}", type(e).__name__)
        return False


def load_user_actions_log() -> list:
    """Load user actions log from persistent storage."""
    try:
        notifications = load_notifications()
        return notifications.get("user_actions", [])
    except Exception as e:
        sync_exc(f"Failed to load user actions log: {e}")
        return []


def _app_settings() -> QSettings:
    """Legacy QSettings accessor. Use load_settings()/save_settings() for new code."""
    return QSettings(SETTINGS_ORG, SETTINGS_APP)
