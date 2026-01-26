import platform
from typing import Optional, Callable, Dict, Any, List

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

def compare_file_states(old_files: List[Dict[str, Any]], new_files: List[Dict[str, Any]], filter_func: Optional[Callable] = None) -> List[Dict[str, Any]]:
    """Compare two file states and return list of changes

    Intelligently detects:
    - New files
    - Modified files (version updates - same name, different ID/timestamp)
    - Deleted files
    - Renamed files (same ID, different name)

    Args:
        old_files: Previous state
        new_files: Current state
        filter_func: Optional callable(change_type, file_id, file_name) -> bool
                    Returns True if change should be EXCLUDED (filtered out)
    """
    def _norm_id(value):
        try:
            if value is None:
                return ""
            return normalize_id(value)
        except Exception:
            return str(value).strip()

    def _norm_name_key(f):
        try:
            name = str(f.get("name", "")).strip()
            path = str(f.get("path", "")).replace("\\", "/").strip("/")
            ftype = f.get("type", "file")
            return (name, path, ftype)
        except Exception:
            return ("", "", f.get("type", "file"))

    old_dict_by_id = {_norm_id(f.get("id")): f for f in old_files}
    new_dict_by_id = {_norm_id(f.get("id")): f for f in new_files}

    print(f"[COMPARE] old_dict_by_id has {len(old_dict_by_id)} entries, new_dict_by_id has {len(new_dict_by_id)} entries")

    # Also index by name+path for detecting version updates
    old_dict_by_name = {}
    for f in old_files:
        key = _norm_name_key(f)
        old_dict_by_name[key] = f

    new_dict_by_name = {}
    for f in new_files:
        key = _norm_name_key(f)
        new_dict_by_name[key] = f

    print(f"[COMPARE] old_dict_by_name has {len(old_dict_by_name)} entries, new_dict_by_name has {len(new_dict_by_name)} entries")

    changes = []
    processed_old_ids = set()
    processed_new_ids = set()

    # First pass: detect modifications by ID and renames
    for fid, new_file in new_dict_by_id.items():
        if fid in old_dict_by_id:
            old_file = old_dict_by_id[fid]
            processed_old_ids.add(fid)
            processed_new_ids.add(fid)

            # Check for rename (same ID, different name)
            if new_file.get("name") != old_file.get("name"):
                change = {"type": "renamed", "file": new_file, "old_name": old_file.get("name")}
                print(f"[COMPARE] RENAMED: {old_file.get('name')} -> {new_file.get('name')} (id={fid})")
                if not (filter_func and filter_func("renamed", fid, new_file.get("name", ""))):
                    changes.append(change)
                continue

            # Check for modification (same ID and name, different timestamp)
            if new_file.get("updatedAt") != old_file.get("updatedAt"):
                change = {"type": "modified", "file": new_file}
                print(f"[COMPARE] MODIFIED (same ID): {new_file.get('name')} (id={fid}), old_ts={old_file.get('updatedAt')}, new_ts={new_file.get('updatedAt')}")
                if filter_func and filter_func("modified", fid, new_file.get("name", "")):
                    print(f"[FILTER] Skipping user-initiated MODIFIED: {new_file.get('name')}")
                    continue
                changes.append(change)

    # Second pass: detect new files and version updates
    for fid, new_file in new_dict_by_id.items():
        if fid in processed_new_ids:
            continue

        name_key = _norm_name_key(new_file)

        # Check if file with same name existed (version update)
        if name_key in old_dict_by_name:
            old_file = old_dict_by_name[name_key]
            processed_old_ids.add(old_file["id"])
            processed_new_ids.add(fid)

            # This is a version update (same name/path, different ID)
            change = {"type": "modified", "file": new_file, "version_update": True}
            print(f"[COMPARE] MODIFIED (version update): {new_file.get('name')} old_id={old_file.get('id')}, new_id={fid}")
            if filter_func and filter_func("modified", fid, new_file.get("name", "")):
                print(f"[FILTER] Skipping user-initiated MODIFIED (version update): {new_file.get('name')}")
                continue
            changes.append(change)
        else:
            # Truly new file
            change = {"type": "new", "file": new_file}
            print(f"[COMPARE] NEW FILE: {new_file.get('name')} (id={fid})")
            if filter_func and filter_func("new", fid, new_file.get("name", "")):
                print(f"[FILTER] Skipping user-initiated NEW: {new_file.get('name')}")
                continue
            changes.append(change)
            processed_new_ids.add(fid)

    # Third pass: detect deleted files
    print(f"[COMPARE] Checking for deleted files, processed_old_ids has {len(processed_old_ids)} entries")
    for fid, old_file in old_dict_by_id.items():
        if fid in processed_old_ids:
            continue

        name_key = _norm_name_key(old_file)

        # Check if file with same name still exists with different ID (version update - already handled)
        if name_key in new_dict_by_name:
            # This old ID was replaced by a new version - don't show as deleted
            processed_old_ids.add(fid)
            print(f"[COMPARE] DELETED (version update): {old_file.get('name')} (old_id={fid}), new_id={new_dict_by_name[name_key].get('id')}")
            continue

        # Truly deleted
        print(f"[COMPARE] DELETED: {old_file.get('name')} (id={fid}), path={old_file.get('path')}")
        change = {"type": "deleted", "file": old_file}
        if filter_func and filter_func("deleted", fid, old_file.get("name", "")):
            print(f"[FILTER] Skipping user-initiated DELETED: {old_file.get('name')}")
            continue
        changes.append(change)

    print(f"[COMPARE] Total changes detected: {len(changes)}")
    for change in changes:
        print(f"[COMPARE]   - {change.get('type')}: {change.get('file', {}).get('name')}")

    return changes

def _set_window_theme_dark(window, dark: bool = False) -> None:
    """Set Windows title bar theme (light/dark) for a window on Windows."""
    if platform.system() != "Windows":
        return
    try:
        import ctypes
        from ctypes import c_int, byref, sizeof
        hwnd = window.winId().__int__()
        # DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        value = c_int(1 if dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, byref(value), sizeof(value)
        )
        # Title bar colors (Windows 11+)
        caption_color = 0x202020 if dark else 0xFFFFFF
        text_color = 0xFFFFFF if dark else 0x000000
        for attr, color in ((35, caption_color), (36, text_color)):
            try:
                cval = c_int(color)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, byref(cval), sizeof(cval))
            except Exception:
                pass
    except Exception:
        pass
    except Exception:
        pass
