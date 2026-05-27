# -*- coding: utf-8 -*-

import os
import time
import json
import typing
from typing import Dict, Any, Callable

from larix_nexus.utils.paths import (
    app_data_dir,
    sync_states_dir,
    sync_subscriptions_path as _new_subscriptions_path,
)
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
    """Legacy global sync state file path (deprecated)."""
    try:
        base = app_data_dir()
        os.makedirs(base, exist_ok=True)
        return os.path.join(base, SYNC_STATE_FILE)
    except Exception:
        return os.path.abspath(SYNC_STATE_FILE)


def _legacy_state_path(project_id: int | str, folder_id) -> str:
    """Legacy per-folder state path: %APPDATA%\\LarixNexus\\state\\<project>-<folder>.json"""
    return os.path.join(app_data_dir(), "state", f"{project_id}-{normalize_id(folder_id)}.json")


def _safe_id_component(value) -> str:
    s = str(value or "").strip()
    if not s:
        return ""
    # Keep readable, avoid path separators and characters that are awkward on Windows.
    out = []
    for ch in s:
        if ch.isalnum() or ch in ("-", "_"):
            out.append(ch)
        else:
            out.append("_")
    return "".join(out)


def load_sync_state(project_id: int | str = "", folder_id: int | str = "") -> tuple[Dict[str, Dict[str, Any]], bool]:
    """Load sync state from file. Returns (files_dict, initial_sync_done).
    
    If project_id and folder_id are provided, loads per-folder state.
    Otherwise loads global state (deprecated, for backward compatibility).
    """
    if project_id and folder_id:
        new_path = _state_path(project_id, folder_id)
        legacy_path = _legacy_state_path(project_id, folder_id)
        path = new_path if os.path.exists(new_path) else legacy_path
        if not os.path.exists(path):
            return {}, False
        if path == legacy_path and legacy_path != new_path:
            sync_log("STATE: legacy fallback read from {}", legacy_path)
        try:
            data = atomic_read_json(path, default={})
            if not isinstance(data, dict):
                return {}, False
            snapshot = data.get("snapshot")
            if isinstance(snapshot, dict):
                return snapshot, len(snapshot) > 0
            # Older formats stored plain mapping directly
            if isinstance(data.get("files"), dict):
                files = data.get("files") or {}
                return files, len(files) > 0
            if isinstance(data, dict):
                return {}, False
        except Exception as e:
            sync_log("Ошибка загрузки per-folder state: {}", str(e))
        return {}, False
    
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


def save_sync_state(files_state: Dict[str, Dict[str, Any]], project_id: int | str = "", folder_id: int | str = "") -> bool:
    """Save sync state to file.
    
    If project_id and folder_id are provided, saves per-folder state.
    Otherwise saves global state (deprecated, for backward compatibility).
    """
    if project_id and folder_id:
        path = _state_path(project_id, folder_id)
        state = {
            "version": 1,
            "project_id": str(project_id),
            "folder_id": normalize_id(folder_id),
            "root_path": "",
            "device_id": "",
            "seq": 0,
            "last_sync_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "snapshot": files_state,
            "tombstones": []
        }
        try:
            return atomic_write_json(path, state, ensure_dir=True)
        except Exception as e:
            sync_log("Ошибка сохранения per-folder state: {}", str(e))
            return False
    
    path = _sync_state_path()
    try:
        sync_log("SYNC_STATE: writing deprecated global state to {}", path)
    except Exception:
        pass
    state = {
        "version":1,
        "last_sync": time.time(),
        "initial_sync_done": True,
        "files": files_state
    }
    try:
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
    """New per-folder state path.

    %APPDATA%\\LarixNexus\\sync\\states\\project_<project_id>__folder_<folder_id>.sync-state.json
    """
    pid = _safe_id_component(project_id)
    fid = _safe_id_component(normalize_id(folder_id))
    fname = f"project_{pid}__folder_{fid}.sync-state.json"
    return os.path.join(sync_states_dir(), fname)


def _remove_path_best_effort(path: str) -> bool:
    if not path or not os.path.exists(path):
        return False
    try:
        os.remove(path)
        return True
    except Exception:
        try:
            tmp = path + ".old"
            if os.path.exists(tmp):
                os.remove(tmp)
            os.rename(path, tmp)
            os.remove(tmp)
            return True
        except Exception:
            return False


def clear_sync_state(project_id: int | str, folder_id: int | str) -> bool:
    """Remove per-folder sync state file (forces next run to be initial sync).

    This is intentionally best-effort: failure should not block UI workflows.
    """
    try:
        paths = [_state_path(project_id, folder_id), _legacy_state_path(project_id, folder_id)]
        for path in paths:
            _remove_path_best_effort(path)
        return True
    except Exception:
        return False


def _expected_state_paths_for_mapping(project_id, folder_id) -> set[str]:
    """Paths that belong to one active sync mapping."""
    out: set[str] = set()
    for path in (_state_path(project_id, folder_id), _legacy_state_path(project_id, folder_id)):
        if path:
            out.add(os.path.normcase(os.path.normpath(path)))
    return out


def purge_orphan_sync_state_files(active_mappings: Dict[str, Dict[str, Any]] | None = None) -> int:
    """Delete per-folder state files not referenced by active sync mappings.

    Called after remove_sync and on startup so stale snapshots do not linger on disk.
    """
    active_mappings = active_mappings or {}
    expected: set[str] = set()
    for folder_id, cfg in active_mappings.items():
        if not isinstance(cfg, dict):
            continue
        project_id = cfg.get("project_id")
        if project_id in (None, "", 0):
            continue
        expected |= _expected_state_paths_for_mapping(project_id, folder_id)

    removed = 0
    try:
        states_dir = sync_states_dir()
        if os.path.isdir(states_dir):
            for name in os.listdir(states_dir):
                if not name.endswith(".sync-state.json"):
                    continue
                path = os.path.join(states_dir, name)
                if os.path.normcase(os.path.normpath(path)) in expected:
                    continue
                if _remove_path_best_effort(path):
                    removed += 1
                    sync_log("PURGE_STATE: removed orphan {}", path)
    except Exception as e:
        sync_log("PURGE_STATE: failed scanning states dir: {}", str(e))

    try:
        legacy_dir = os.path.join(app_data_dir(), "state")
        if os.path.isdir(legacy_dir):
            for name in os.listdir(legacy_dir):
                if not name.lower().endswith(".json"):
                    continue
                path = os.path.join(legacy_dir, name)
                if os.path.normcase(os.path.normpath(path)) in expected:
                    continue
                if _remove_path_best_effort(path):
                    removed += 1
                    sync_log("PURGE_STATE: removed legacy orphan {}", path)
            try:
                if not os.listdir(legacy_dir):
                    os.rmdir(legacy_dir)
            except Exception:
                pass
    except Exception as e:
        sync_log("PURGE_STATE: failed scanning legacy state dir: {}", str(e))

    return removed


def purge_legacy_global_sync_state() -> bool:
    """Remove deprecated global sync_state.json when no per-folder mappings remain."""
    path = _sync_state_path()
    return _remove_path_best_effort(path)


def load_state(project_id: int | str, folder_id) -> Dict:
    """Load state for a sync root. Returns empty state if not found."""
    path = _state_path(project_id, folder_id)
    default = {
        "version":1,
        "project_id": str(project_id),
        "folder_id": normalize_id(folder_id),
        "root_path": "",
        "device_id": "",
        "seq": 0,
        "last_sync_at": "",
        "snapshot": {},
        "tombstones": []
    }
    data = atomic_read_json(path, default=None)
    if data is not None:
        return data

    legacy = _legacy_state_path(project_id, folder_id)
    if legacy != path and os.path.exists(legacy):
        sync_log("STATE: legacy fallback read from {}", legacy)
        return atomic_read_json(legacy, default=default)

    return default


def save_state(project_id: int | str, folder_id, state: Dict) -> bool:
    """Save state for a sync root."""
    path = _state_path(project_id, folder_id)
    return atomic_write_json(path, state, ensure_dir=True)


def update_state(project_id: int | str, folder_id, updater: Callable[[Dict], Dict]) -> bool:
    """Atomically update state using updater function."""
    path = _state_path(project_id, folder_id)
    default = {
        "version": 1,
        "project_id": str(project_id),
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
    """Get path to subscriptions JSON file (new location)."""
    return _new_subscriptions_path()


def _legacy_subscriptions_path() -> str:
    return os.path.join(app_data_dir(), "settings", "subscriptions.json")


def load_subscriptions() -> Dict:
    """Load global subscriptions. Returns empty structure if not found."""
    path = _subscriptions_path()
    default = {"version": 1, "roots": {}}
    data = atomic_read_json(path, default=None)
    if data is not None:
        return data

    legacy = _legacy_subscriptions_path()
    if legacy != path and os.path.exists(legacy):
        sync_log("SUBSCRIPTIONS: legacy fallback read from {}", legacy)
        return atomic_read_json(legacy, default=default)

    return default


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
