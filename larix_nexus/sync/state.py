# -*- coding: utf-8 -*-

import os
import time
import typing
from typing import Dict, Any, Callable

# Import from utils modules
from larix_nexus.utils.paths import program_dir
from larix_nexus.utils.logging import sync_log, sync_exc
from larix_nexus.utils.helpers import normalize_id
from larix_nexus.utils.atomic_json import (
    atomic_read_json,
    atomic_write_json,
    atomic_update_json
)

SYNC_STATE_FILE = "sync_state.json"

# ============================================================================
# SYNC STATE MANAGEMENT
# ============================================================================

def _sync_state_path() -> str:
    """Get path to sync state file in AppData."""
    try:
        app_data = os.getenv("APPDATA") or os.path.expanduser("~/.config")
        sync_dir = os.path.join(app_data, "LarixNexus")
        os.makedirs(sync_dir, exist_ok=True)
        return os.path.join(sync_dir, SYNC_STATE_FILE)
    except Exception:
        return os.path.abspath(SYNC_STATE_FILE)


def load_sync_state() -> tuple[Dict[str, Dict[str, Any]], bool]:
    """Load sync state from file. Returns (files_dict, initial_sync_done)"""
    path = _sync_state_path()
    if not os.path.exists(path):
        return {}, False
    
    try:
        import json
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get("files", {}), data.get("initial_sync_done", False)
    except Exception as e:
        sync_log("Ошибка загрузки sync_state.json: {}", str(e))
        return {}, False


def save_sync_state(files_state: Dict[str, Dict[str, Any]]) -> bool:
    """Save sync state to file."""
    path = _sync_state_path()
    state = {
        "version": 1,
        "last_sync": time.time(),
        "initial_sync_done": True,
        "files": files_state
    }
    try:
        import time
        import json
        temp_path = path + ".tmp"
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        if os.path.exists(path):
            os.remove(path)
        os.rename(temp_path, path)
        return True
    except Exception as e:
        sync_log("Ошибка сохранения sync_state.json: {}", str(e))
        return False


# ============================================================================
# STATE STORAGE (per sync root)
# ============================================================================

def _state_path(project_id: int | str, folder_id) -> str:
    """Get path to state JSON file for a sync root."""
    app_data = os.getenv("APPDATA") or os.path.expanduser("~/.config")
    state_dir = os.path.join(app_data, "LarixNexus", "state")
    return os.path.join(state_dir, f"{project_id}-{normalize_id(folder_id)}.json")


def load_state(project_id: int | str, folder_id) -> Dict:
    """Load state for a sync root. Returns empty state if not found."""
    path = _state_path(project_id, folder_id)
    default = {
        "version": 1,
        "project_id": int(project_id),
        "folder_id": normalize_id(folder_id),
        "root_path": "",
        "device_id": "",
        "seq": 0,
        "last_sync_at": "",
        "snapshot": {},
        "tombstones": []
    }
    return atomic_read_json(path, default=default)


def save_state(project_id: int | str, folder_id, state: Dict) -> bool:
    """Save state for a sync root."""
    path = _state_path(project_id, folder_id)
    return atomic_write_json(path, state, ensure_dir=True)


def update_state(project_id: int | str, folder_id, updater: Callable[[Dict], Dict]) -> bool:
    """Atomically update state using updater function."""
    path = _state_path(project_id, folder_id)
    default = {
        "version": 1,
        "project_id": int(project_id),
        "folder_id": normalize_id(folder_id),
        "root_path": "",
        "device_id": "",
        "seq": 0,
        "last_sync_at": "",
        "snapshot": {},
        "tombstones": []
    }
    return atomic_update_json(path, updater, default=default)


# ============================================================================
# SUBSCRIPTIONS STORAGE (global, shared)
# ============================================================================

def _subscriptions_path() -> str:
    """Get path to subscriptions JSON file."""
    app_data = os.getenv("APPDATA") or os.path.expanduser("~/.config")
    settings_dir = os.path.join(app_data, "LarixNexus", "settings")
    return os.path.join(settings_dir, "subscriptions.json")


def load_subscriptions() -> Dict:
    """Load global subscriptions. Returns empty structure if not found."""
    path = _subscriptions_path()
    default = {"version": 1, "roots": {}}
    return atomic_read_json(path, default=default)


def save_subscriptions(subs: Dict) -> bool:
    """Save global subscriptions."""
    path = _subscriptions_path()
    return atomic_write_json(path, subs, ensure_dir=True)


def update_subscription(project_id: int | str, folder_id: int | str, rel_path: str,
                        subscribed: bool, last_seen_rev: int = 0) -> bool:
    """Atomically update subscription for a specific folder path."""
    path = _subscriptions_path()
    
    def updater(data: Dict) -> Dict:
        if "roots" not in data:
            data["roots"] = {}
        root_key = f"{project_id}-{folder_id}"
        if root_key not in data["roots"]:
            data["roots"][root_key] = {}
        
        if subscribed:
            data["roots"][root_key][rel_path] = {
                "subscribed": True,
                "last_seen_rev": int(last_seen_rev)
            }
        else:
            data["roots"][root_key].pop(rel_path, None)
        
        return data
    
    return atomic_update_json(path, updater, default={"version": 1, "roots": {}})
