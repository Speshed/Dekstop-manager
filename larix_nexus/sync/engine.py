# -*- coding: utf-8 -*-

import os
import hashlib
import shutil
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Callable

# Import from utils modules
from larix_nexus.utils.paths import program_dir
from larix_nexus.utils.logging import sync_log, sync_exc, new_trace_id, is_debug_sync, is_dry_run
from larix_nexus.utils.helpers import normalize_id
from larix_nexus.utils.atomic_json import (
    atomic_read_json,
    atomic_write_json,
    atomic_update_json
)
from larix_nexus.utils.theme import _cloud_tz_offset_minutes

# State & subscriptions storage lives in sync/state.py.
# Keep the same public helpers here for backwards-compatibility.
from .state import (
    load_sync_state,
    save_sync_state,
    load_state,
    save_state,
    update_state,
    load_subscriptions,
    save_subscriptions,
    update_subscription,
)


# ============================================================================
# CORE SYNC FUNCTIONS
# ============================================================================

def get_local_files(local_root: str, trace_id: str = "") -> Dict[str, Dict[str, Any]]:
    """Get list of local files AND folders with metadata.
    Returns: {relative_path: {"createTime": timestamp, "lastModified": timestamp, "size": bytes, "is_folder": bool}}
    """
    files = {}
    if not os.path.exists(local_root):
        sync_log("Local root does not exist", path=local_root, component="FS", op="scan", trace_id=trace_id, result="fail", reason="not_found")
        return files
    
    sync_log("Starting local file scan", path=local_root, component="FS", op="scan", trace_id=trace_id, result="ok")
    
    for root, dirs, filenames in os.walk(local_root):
        for dirname in dirs:
            full_path = os.path.join(root, dirname)
            rel_path = os.path.relpath(full_path, local_root).replace("\\", "/")
            try:
                stat = os.stat(full_path)
                files[rel_path] = {
                    "createTime": stat.st_ctime,
                    "lastModified": stat.st_mtime,
                    "size": 0,
                    "is_folder": True
                }
                if is_debug_sync():
                    sync_log("Scanned local directory", path=rel_path, component="FS", op="scan", trace_id=trace_id, result="ok", extra=f"mtime={stat.st_mtime}")
            except Exception as e:
                sync_log("Failed to read folder metadata", path=full_path, component="FS", op="scan", trace_id=trace_id, result="fail", reason=str(e))
        for filename in filenames:
            full_path = os.path.join(root, filename)
            rel_path = os.path.relpath(full_path, local_root).replace("\\", "/")
            try:
                stat = os.stat(full_path)
                files[rel_path] = {
                    "createTime": stat.st_ctime,
                    "lastModified": stat.st_mtime,
                    "size": stat.st_size
                }
                if is_debug_sync():
                    sync_log("Scanned local file", path=rel_path, component="FS", op="scan", trace_id=trace_id, result="ok", extra=f"size={stat.st_size} mtime={stat.st_mtime}")
            except Exception as e:
                sync_log("Failed to read file metadata", path=full_path, component="FS", op="scan", trace_id=trace_id, result="fail", reason=str(e))
    
    sync_log("Local file scan completed", component="FS", op="scan", trace_id=trace_id, result="ok", extra=f"total={len(files)} files={len([f for f in files.values() if not f.get('is_folder')])} folders={len([f for f in files.values() if f.get('is_folder')])}")
    return files


def _parse_timestamp(value: Any, field_name: str = "") -> float:
    """Parse timestamp from various formats."""
    if not value:
        return 0.0
    
    if isinstance(value, (int, float)):
        if value > 1e12:
            return value / 1000.0
        return float(value)
    
    s = str(value).strip()
    
    try:
        val = float(s)
        if val > 1e12:
            return val / 1000.0
        return val
    except:
        pass
    
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        pass
    
    return 0.0


def get_cloud_files(api, project_id: int | str, folder_id: int | str, trace_id: str = "") -> Dict[str, Dict[str, Any]]:
    """Get list of cloud files with metadata.
    Returns: {relative_path: {"createTime": timestamp, "lastModified": timestamp, "size": bytes, "id": file_id}}
    """
    files = {}
    try:
        sync_log("Fetching cloud files", path=f"project={project_id} folder={folder_id}", component="NET", op="list", trace_id=trace_id, result="ok")
        
        tree_root = None
        try:
            sync_log("Trying method 1: list_folders", component="NET", op="list", trace_id=trace_id)
            folders_tree = api.list_folders(project_id, force=True)
            if folders_tree:
                sync_log("list_folders returned tree", component="NET", op="list", trace_id=trace_id, result="ok", extra=f"items={len(folders_tree)}")
                def find_folder_in_tree(tree, target_id):
                    if not isinstance(tree, list):
                        return None
                    for item in tree:
                        if item.get("id") == target_id:
                            return item
                        children = item.get("children") or item.get("folders") or []
                        result = find_folder_in_tree(children, target_id)
                        if result:
                            return result
                    return None
                tree_root = find_folder_in_tree(folders_tree, folder_id)
                if tree_root:
                    sync_log("Found folder in project tree", component="NET", op="list", trace_id=trace_id, result="ok", extra=f"folder_id={folder_id}")
                else:
                    sync_log("Folder not found in tree, trying alternative method", component="NET", op="list", trace_id=trace_id, result="skip", reason="not_in_tree")
            else:
                sync_log("list_folders returned empty result", component="NET", op="list", trace_id=trace_id, result="fail", reason="empty_response")
        except Exception as e:
            sync_log("list_folders failed", component="NET", op="list", trace_id=trace_id, result="fail", reason=str(e))
        
        if not tree_root:
            sync_log("Trying method 2: get_folder_details", component="NET", op="list", trace_id=trace_id)
            folder_details = api.get_folder_details(folder_id, force=True)
            if not folder_details:
                sync_log("get_folder_details returned empty result", component="NET", op="list", trace_id=trace_id, result="fail", reason="empty_response")
                return files
            sync_log("Got folder details", component="NET", op="list", trace_id=trace_id, result="ok", extra=f"folder_id={folder_id} keys={list(folder_details.keys())}")
            tree_root = folder_details
        
        def _process_tree(tree, parent_path="", level=0):
            if not isinstance(tree, list):
                sync_log("Tree is not a list", component="NET", op="process", trace_id=trace_id, result="fail", reason=f"level={level} path={parent_path} type={type(tree).__name__}")
                return
            sync_log("Processing tree level", component="NET", op="process", trace_id=trace_id, result="ok", extra=f"level={level} items={len(tree)} path='{parent_path}'")
            for item in tree:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("type", "").lower()
                item_name = item.get("name") or item.get("title") or item.get("folderName") or item.get("originalName") or ""
                if item_type == "file":
                    if parent_path:
                        rel_path = f"{parent_path}/{item_name}"
                    else:
                        rel_path = item_name
                    file_id = normalize_id(item.get("id"))
                    if file_id:
                        try:
                            doc_details = api.get_document_details(file_id)
                            if doc_details:
                                if is_debug_sync():
                                    sync_log("Got document details", component="NET", op="fetch", trace_id=trace_id, result="ok", extra=f"file_id={file_id}")
                                raw_time = doc_details.get("createTime") or doc_details.get("createdAt") or doc_details.get("created") or doc_details.get("modifTime")
                                create_ts = _parse_timestamp(raw_time, "createTime")
                                modif_raw = doc_details.get("modifTime") or doc_details.get("updatedAt") or raw_time
                                modif_ts = _parse_timestamp(modif_raw, "modifTime")
                                file_size = int(doc_details.get("size") or item.get("size") or 0)
                                files[rel_path] = {
                                    "createTime": create_ts,
                                    "lastModified": modif_ts,
                                    "size": file_size,
                                    "id": file_id
                                }
                        except Exception as e:
                            sync_log("Failed to get document details", component="NET", op="fetch", trace_id=trace_id, result="fail", reason=str(e), extra=f"file_id={file_id}")
                elif item_type == "folder":
                    folder_name = item.get("name") or item.get("title") or item.get("folderName") or ""
                    new_path = f"{parent_path}/{folder_name}" if parent_path else folder_name
                    files[new_path] = {
                        "createTime": 0,
                        "lastModified": 0,
                        "size": 0,
                        "is_folder": True
                    }
                    children = None
                    for key in ("children", "folders", "items", "subFolders"):
                        potential_children = item.get(key)
                        if isinstance(potential_children, list):
                            children = potential_children
                            break
                    if children:
                        _process_tree(children, new_path, level + 1)
        
        tree = None
        for key in ("children", "folders", "items", "documents", "content", "subFolders"):
            potential_tree = tree_root.get(key)
            if isinstance(potential_tree, list):
                tree = potential_tree
                break
        if tree:
            _process_tree(tree)
    except Exception as e:
        sync_log("Failed to fetch cloud files", component="NET", op="list", trace_id=trace_id, result="fail", reason=str(e))
    
    total_files = len([f for f in files.values() if not f.get("is_folder")])
    total_folders = len([f for f in files.values() if f.get("is_folder")])
    sync_log("Cloud files fetched", component="NET", op="list", trace_id=trace_id, result="ok", extra=f"files={total_files} folders={total_folders} total={len(files)}")
    return files


def get_cloud_folder_structure(api, project_id: int | str, folder_id: int | str) -> Dict[str, str]:
    """Get folder structure in cloud. Returns: {relative_path: folder_id}"""
    folders = {"": normalize_id(folder_id)}
    try:
        tree_root = None
        try:
            folders_tree = api.list_folders(project_id, force=True)
            if folders_tree:
                target_id_norm = normalize_id(folder_id)
                def find_folder_in_tree(tree, target_id_norm):
                    if not isinstance(tree, list):
                        return None
                    for item in tree:
                        if normalize_id(item.get("id")) == target_id_norm:
                            return item
                        children = item.get("children") or item.get("folders") or []
                        result = find_folder_in_tree(children, target_id_norm)
                        if result:
                            return result
                    return None
                tree_root = find_folder_in_tree(folders_tree, target_id_norm)
        except Exception:
            pass
        if not tree_root:
            folder_details = api.get_folder_details(folder_id, force=True)
            if not folder_details:
                return folders
            tree_root = folder_details
        def _process_tree(tree, parent_path=""):
            if not isinstance(tree, list):
                return
            for item in tree:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("type", "").lower()
                if item_type == "folder":
                    folder_name = item.get("name") or item.get("title") or item.get("folderName") or ""
                    new_path = f"{parent_path}/{folder_name}" if parent_path else folder_name
                    folders[new_path] = normalize_id(item.get("id"))
                    children = None
                    for key in ("children", "folders", "items", "subFolders"):
                        potential_children = item.get(key)
                        if isinstance(potential_children, list):
                            children = potential_children
                            break
                    if children:
                        _process_tree(children, new_path)
        tree = None
        for key in ("children", "folders", "items", "documents", "content", "subFolders"):
            potential_tree = tree_root.get(key)
            if isinstance(potential_tree, list):
                tree = potential_tree
                break
        if tree:
            _process_tree(tree)
    except Exception as e:
        sync_log("Ошибка получения структуры папок: {}", str(e))
    return folders


def compare_and_plan_sync(
    old_state: Dict[str, Dict[str, Any]],
    local_files: Dict[str, Dict[str, Any]],
    cloud_files: Dict[str, Dict[str, Any]],
    tolerance: float = 2.0,
    is_initial_sync: bool = False,
    trace_id: str = ""
) -> list:
    """Compare old state with current and plan sync operations."""
    operations = []
    all_paths = set(old_state.keys()) | set(local_files.keys()) | set(cloud_files.keys())
    
    sync_log("Starting comparison", component="SYNC", op="compare", trace_id=trace_id, result="ok", extra=f"paths={len(all_paths)} old={len(old_state)} local={len(local_files)} cloud={len(cloud_files)}")
    
    for path in all_paths:
        was_in_old = path in old_state
        in_local = path in local_files
        in_cloud = path in cloud_files
        is_folder_local = local_files.get(path, {}).get("is_folder", False)
        is_folder_cloud = cloud_files.get(path, {}).get("is_folder", False)
        is_folder = is_folder_local or is_folder_cloud
        
        if in_cloud and not in_local and not was_in_old:
            if is_debug_sync():
                sync_log("New in cloud only", component="SYNC", op="compare", trace_id=trace_id, result="ok", path=path, extra=f"action=download is_folder={is_folder}")
            op = {
                "action": "download",
                "path": path,
                "cloud_id": cloud_files[path]["id"],
                "cloud_mtime": cloud_files[path].get("createTime")
            }
            if cloud_files[path].get("is_folder"):
                op["is_folder"] = "true"
            operations.append(op)
        elif in_local and not in_cloud and not was_in_old:
            if is_debug_sync():
                sync_log("New local only", component="SYNC", op="compare", trace_id=trace_id, result="ok", path=path, extra=f"action=upload is_folder={is_folder}")
            operations.append({
                "action": "upload",
                "path": path
            })
        elif was_in_old and in_local and not in_cloud:
            if is_debug_sync():
                sync_log("Deleted in cloud, delete local", component="SYNC", op="compare", trace_id=trace_id, result="ok", path=path, extra=f"action=delete_local is_folder={is_folder}")
            op = {
                "action": "delete_local",
                "path": path
            }
            if local_files[path].get("is_folder"):
                op["is_folder"] = "true"
            else:
                op["is_folder"] = "false"
            operations.append(op)
        elif was_in_old and in_cloud and not in_local:
            if is_initial_sync:
                if is_debug_sync():
                    sync_log("Initial sync: exists in cloud, download", component="SYNC", op="compare", trace_id=trace_id, result="ok", path=path, extra=f"action=download is_folder={is_folder}")
                op = {
                    "action": "download",
                    "path": path,
                    "cloud_id": cloud_files[path]["id"],
                    "cloud_mtime": cloud_files[path].get("createTime")
                }
                if cloud_files[path].get("is_folder"):
                    op["is_folder"] = "true"
                operations.append(op)
            else:
                if is_debug_sync():
                    sync_log("Deleted locally, delete in cloud", component="SYNC", op="compare", trace_id=trace_id, result="ok", path=path, extra=f"action=delete_cloud is_folder={is_folder}")
                op = {
                    "action": "delete_cloud",
                    "path": path,
                    "cloud_id": cloud_files[path]["id"]
                }
                if is_folder:
                    op["is_folder"] = "true"
                operations.append(op)
        elif in_local and in_cloud:
            local_mtime = local_files[path].get("lastModified", 0)
            cloud_mtime = cloud_files[path].get("createTime", 0)
            if abs(local_mtime - cloud_mtime) > tolerance:
                if local_mtime > cloud_mtime:
                    if is_debug_sync():
                        sync_log("Local is newer, upload", component="SYNC", op="compare", trace_id=trace_id, result="ok", path=path, extra=f"action=upload local_mtime={local_mtime} cloud_mtime={cloud_mtime}")
                    operations.append({
                        "action": "upload",
                        "path": path
                    })
                else:
                    if is_debug_sync():
                        sync_log("Cloud is newer, download", component="SYNC", op="compare", trace_id=trace_id, result="ok", path=path, extra=f"action=download local_mtime={local_mtime} cloud_mtime={cloud_mtime}")
                    op = {
                        "action": "download",
                        "path": path,
                        "cloud_id": cloud_files[path]["id"],
                        "cloud_mtime": cloud_mtime
                    }
                    if cloud_files[path].get("is_folder"):
                        op["is_folder"] = "true"
                    operations.append(op)
        elif not in_local and not in_cloud and was_in_old:
            if is_debug_sync():
                sync_log("Deleted from both sides", component="SYNC", op="compare", trace_id=trace_id, result="ok", path=path, extra=f"action=skip reason=both_deleted")
    
    # Count operations by action
    by_action = {}
    for op in operations:
        action = op["action"]
        by_action[action] = by_action.get(action, 0) + 1
    
    sync_log("Plan built", component="SYNC", op="plan", trace_id=trace_id, result="ok", extra=f"total={len(operations)} {by_action}")
    return operations


def execute_sync_operations(
    api,
    project_id: int | str,
    folder_id: int | str,
    local_root: str,
    operations: list,
    dry_run: bool = False,
    trace_id: str = ""
) -> Dict[str, Any]:
    """Execute sync operations. Returns statistics."""
    import time
    
    stats = {
        "downloaded": 0,
        "uploaded": 0,
        "deleted_local": 0,
        "deleted_cloud": 0,
        "errors": []
    }
    
    sync_log("Starting operations execution", component="SYNC", op="execute", trace_id=trace_id, result="ok", extra=f"total={len(operations)} dry_run={dry_run}")
    cloud_folders = get_cloud_folder_structure(api, project_id, normalize_id(folder_id))
    def ensure_cloud_folder(path: str) -> Optional[str]:
        """Ensure folder exists in cloud. Returns folder_id or None."""
        if path in cloud_folders:
            return cloud_folders[path]
        parts = path.split("/")
        current_path = ""
        current_folder_id = normalize_id(folder_id)
        for part in parts:
            if current_path:
                current_path = f"{current_path}/{part}"
            else:
                current_path = part
            if current_path in cloud_folders:
                current_folder_id = cloud_folders[current_path]
            else:
                if dry_run:
                    sync_log("[DRY RUN] Создать папку: {}", current_path)
                    cloud_folders[current_path] = "-1"
                    current_folder_id = "-1"
                else:
                    sync_log("Создаю папку: {}", current_path)
                    try:
                        result = api.create_folder(project_id, current_folder_id, part)
                        if isinstance(result, dict) and "id" in result:
                            new_folder_id = normalize_id(result["id"])
                            cloud_folders[current_path] = new_folder_id
                            current_folder_id = new_folder_id
                        else:
                            return None
                    except Exception as e:
                        sync_log("Ошибка создания папки {}: {}", current_path, str(e))
                        return None
        return normalize_id(current_folder_id)
    
    sync_log("Processing folders (first pass)", component="SYNC", op="execute_folders", trace_id=trace_id, result="ok")
    try:
        for idx, op in enumerate(operations, 1):
            if op.get("is_folder") and op["action"] in ("download", "conflict_download"):
                path = op["path"]
                if dry_run or is_dry_run():
                    sync_log("[DRY RUN] Create local folder", component="FS", op="create", trace_id=trace_id, result="skip", path=path, reason="dry_run")
                else:
                    local_path = os.path.join(local_root, path.replace("/", os.sep))
                    try:
                        os.makedirs(local_path, exist_ok=True)
                        sync_log("Created local folder", component="FS", op="create", trace_id=trace_id, result="ok", path=path)
                    except Exception as e:
                        sync_log("Failed to create folder", component="FS", op="create", trace_id=trace_id, result="fail", path=path, reason=str(e))
                        stats["errors"].append(f"Failed to create folder {path}: {e}")
        sync_log("First pass completed", component="SYNC", op="execute_folders", trace_id=trace_id, result="ok")
    except Exception as e:
        sync_log("First pass failed", component="SYNC", op="execute_folders", trace_id=trace_id, result="fail", reason=str(e))
        stats["errors"].append(f"First pass error: {e}")
    
    sync_log("Processing files (second pass)", component="SYNC", op="execute_files", trace_id=trace_id, result="ok")
    
    for idx, op in enumerate(operations, 1):
        try:
            action = op.get("action")
            path = op["path"]
            
            if op.get("is_folder") and action in ("download", "conflict_download"):
                continue
            
            sync_log("Processing operation", component="SYNC", op="execute", trace_id=trace_id, result="ok", path=path, extra=f"idx={idx}/{len(operations)} action={action}")
            
            start_time = time.time()
            
            if action == "download" or action == "conflict_download":
                if dry_run or is_dry_run():
                    sync_log("[DRY RUN] Download file", component="NET", op="download", trace_id=trace_id, result="skip", path=path, reason="dry_run")
                else:
                    local_path = os.path.join(local_root, path.replace("/", os.sep))
                    dir_path = os.path.dirname(local_path)
                    if dir_path:
                        try:
                            os.makedirs(dir_path, exist_ok=True)
                        except Exception as e:
                            sync_log("Failed to create parent directory", component="FS", op="mkdir", trace_id=trace_id, result="fail", path=dir_path, reason=str(e))
                    
                    cloud_id = op["cloud_id"]
                    try:
                        with open(local_path, 'wb') as f:
                            success = api.write_file_to(cloud_id, f)
                    except Exception as e:
                        sync_log("Download failed", component="NET", op="download", trace_id=trace_id, result="fail", path=path, reason=str(e))
                        success = False
                    
                    duration_ms = int((time.time() - start_time) * 1000)
                    
                    if success:
                        stats["downloaded"] += 1
                        sync_log("Downloaded file", component="NET", op="download", trace_id=trace_id, result="ok", path=path, duration_ms=duration_ms)
                    else:
                        stats["errors"].append(f"Download failed: {path}")
                        sync_log("Download failed", component="NET", op="download", trace_id=trace_id, result="fail", path=path, duration_ms=duration_ms, reason="api_returned_false")
            
            elif action == "upload":
                if dry_run or is_dry_run():
                    sync_log("[DRY RUN] Upload file", component="NET", op="upload", trace_id=trace_id, result="skip", path=path, reason="dry_run")
                else:
                    local_path_full = os.path.join(local_root, path.replace("/", os.sep))
                    parent_dir = os.path.dirname(path)
                    parent_folder_id = folder_id
                    
                    if parent_dir:
                        parent_folder_id = ensure_cloud_folder(parent_dir)
                        if parent_folder_id is None:
                            stats["errors"].append(f"Failed to create parent folder: {parent_dir}")
                            sync_log("Failed to create parent folder", component="NET", op="mkdir", trace_id=trace_id, result="fail", path=parent_dir, reason="parent_creation_failed")
                            continue
                    
                    try:
                        result = api.upload_file(
                            parent_folder_id,
                            local_path_full,
                            os.path.basename(path)
                        )
                        duration_ms = int((time.time() - start_time) * 1000)
                        
                        if result:
                            stats["uploaded"] += 1
                            sync_log("Uploaded file", component="NET", op="upload", trace_id=trace_id, result="ok", path=path, duration_ms=duration_ms)
                        else:
                            stats["errors"].append(f"Upload failed: {path}")
                            sync_log("Upload failed", component="NET", op="upload", trace_id=trace_id, result="fail", path=path, duration_ms=duration_ms, reason="api_returned_false")
                    except Exception as e:
                        stats["errors"].append(f"Upload error {path}: {e}")
                        sync_log("Upload error", component="NET", op="upload", trace_id=trace_id, result="fail", path=path, duration_ms=int((time.time() - start_time) * 1000), reason=str(e))
            
            elif action == "delete_local":
                if dry_run or is_dry_run():
                    sync_log("[DRY RUN] Delete local file", component="FS", op="delete", trace_id=trace_id, result="skip", path=path, reason="dry_run")
                else:
                    local_path = os.path.join(local_root, path.replace("/", os.sep))
                    try:
                        if os.path.isdir(local_path):
                            shutil.rmtree(local_path)
                        else:
                            os.remove(local_path)
                        duration_ms = int((time.time() - start_time) * 1000)
                        stats["deleted_local"] += 1
                        sync_log("Deleted local file", component="FS", op="delete", trace_id=trace_id, result="ok", path=path, duration_ms=duration_ms)
                    except Exception as e:
                        stats["errors"].append(f"Delete local error {path}: {e}")
                        sync_log("Delete local failed", component="FS", op="delete", trace_id=trace_id, result="fail", path=path, duration_ms=int((time.time() - start_time) * 1000), reason=str(e))
            
            elif action == "delete_cloud":
                if dry_run or is_dry_run():
                    sync_log("[DRY RUN] Delete cloud file", component="NET", op="delete", trace_id=trace_id, result="skip", path=path, reason="dry_run")
                else:
                    cloud_id = op.get("cloud_id")
                    if cloud_id:
                        try:
                            api.delete_document(cloud_id)
                            duration_ms = int((time.time() - start_time) * 1000)
                            stats["deleted_cloud"] += 1
                            sync_log("Deleted cloud file", component="NET", op="delete", trace_id=trace_id, result="ok", path=path, duration_ms=duration_ms)
                        except Exception as e:
                            stats["errors"].append(f"Delete cloud error {path}: {e}")
                            sync_log("Delete cloud failed", component="NET", op="delete", trace_id=trace_id, result="fail", path=path, duration_ms=int((time.time() - start_time) * 1000), reason=str(e))
        
        except Exception as e:
            stats["errors"].append(f"Operation error {op.get('action')} for {op.get('path')}: {e}")
            sync_log("Operation exception", component="SYNC", op="execute", trace_id=trace_id, result="fail", path=op.get('path'), reason=str(e))
    
    return stats


def sync_files_new(
    api,
    project_id: int | str,
    folder_id: int | str,
    local_root: str,
    dry_run: bool = False,
    is_initial_sync: bool = False
) -> Dict[str, Any]:
    """Main sync function."""
    import time
    
    trace_id = new_trace_id()
    effective_dry_run = dry_run or is_dry_run()
    
    sync_log("Sync started", component="SYNC", op="start", trace_id=trace_id, result="ok", extra=f"project_id={project_id} folder_id={folder_id} local_root='{local_root}' dry_run={effective_dry_run} is_initial_sync={is_initial_sync}")
    
    if is_initial_sync:
        sync_log("Initial sync mode: old_state will be ignored", component="SYNC", op="state", trace_id=trace_id, result="ok")
    
    sync_log("Loading previous state", component="DB", op="load", trace_id=trace_id, result="ok")
    old_state, initial_sync_done = load_sync_state()
    if is_initial_sync:
        old_state = {}
        sync_log("Initial sync: old_state cleared", component="DB", op="load", trace_id=trace_id, result="ok", extra=f"was={len(old_state)}")
    elif initial_sync_done:
        sync_log("Continuing sync: previous state loaded", component="DB", op="load", trace_id=trace_id, result="ok", extra=f"items={len(old_state)}")
    else:
        sync_log("Previous state loaded", component="DB", op="load", trace_id=trace_id, result="ok", extra=f"items={len(old_state)}")
    
    sync_log("Scanning local filesystem", component="SYNC", op="scan_local", trace_id=trace_id, result="ok")
    local_files = get_local_files(local_root, trace_id=trace_id)
    local_folders = sum(1 for f in local_files.values() if f.get("is_folder"))
    local_regular = len(local_files) - local_folders
    sync_log("Local scan complete", component="SYNC", op="scan_local", trace_id=trace_id, result="ok", extra=f"files={local_regular} folders={local_folders} total={len(local_files)}")
    
    sync_log("Scanning cloud", component="SYNC", op="scan_cloud", trace_id=trace_id, result="ok")
    cloud_files = get_cloud_files(api, project_id, folder_id, trace_id=trace_id)
    cloud_folders = sum(1 for f in cloud_files.values() if f.get("is_folder"))
    cloud_regular = len(cloud_files) - cloud_folders
    sync_log("Cloud scan complete", component="SYNC", op="scan_cloud", trace_id=trace_id, result="ok", extra=f"files={cloud_regular} folders={cloud_folders} total={len(cloud_files)}")
    
    sync_log("Planning sync operations", component="SYNC", op="plan", trace_id=trace_id, result="ok")
    operations = compare_and_plan_sync(old_state, local_files, cloud_files, is_initial_sync=is_initial_sync, trace_id=trace_id)
    
    sync_log("Executing operations", component="SYNC", op="execute", trace_id=trace_id, result="ok", extra=f"dry_run={effective_dry_run}")
    stats = execute_sync_operations(api, project_id, folder_id, local_root, operations, effective_dry_run, trace_id=trace_id)
    
    sync_log("Saving new state", component="DB", op="save", trace_id=trace_id, result="ok")
    if not effective_dry_run:
        new_state = {}
        for path, info in local_files.items():
            new_state[path] = {
                "createTime": info["createTime"],
                "lastModified": info["lastModified"],
                "is_folder": info.get("is_folder", False)
            }
        for path, info in cloud_files.items():
            if path in new_state:
                new_state[path]["createTime"] = info["createTime"]
                if info["lastModified"] > new_state[path]["lastModified"]:
                    new_state[path]["lastModified"] = info["lastModified"]
                if info.get("is_folder"):
                    new_state[path]["is_folder"] = True
            else:
                new_state[path] = {
                    "createTime": info["createTime"],
                    "lastModified": info["lastModified"],
                    "is_folder": info.get("is_folder", False)
                }
        saved_folders = sum(1 for f in new_state.values() if f.get("is_folder"))
        saved_regular = len(new_state) - saved_folders
        save_sync_state(new_state)
        sync_log("State saved", component="DB", op="save", trace_id=trace_id, result="ok", extra=f"files={saved_regular} folders={saved_folders} total={len(new_state)}")
    else:
        sync_log("State save skipped (dry run)", component="DB", op="save", trace_id=trace_id, result="skip", reason="dry_run")
    
    success = len(stats["errors"]) == 0
    sync_log("Sync completed", component="SYNC", op="finish", trace_id=trace_id, result="ok" if success else "fail", extra=f"downloaded={stats['downloaded']} uploaded={stats['uploaded']} deleted_local={stats['deleted_local']} deleted_cloud={stats['deleted_cloud']} errors={len(stats['errors'])}")
    
    if stats["errors"]:
        sync_log("Sync errors", component="SYNC", op="errors", trace_id=trace_id, result="fail", extra=str(stats["errors"][:10]))
    
    return {
        "success": success,
        "stats": stats,
        "errors": stats["errors"]
    }


# ============================================================================
# DIFF ENGINE & CONFLICT RESOLUTION
# ============================================================================

def compute_file_hash(path: str) -> str:
    """Compute SHA256 hash of a file for conflict resolution."""
    try:
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            while chunk := f.read(8192):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def resolve_conflict(local_entry: Dict, cloud_entry: Dict, local_path: str = "") -> str:
    """Resolve conflict using etag > mtime > size priority (last-writer-wins)."""
    cloud_etag = cloud_entry.get("etag", "")
    local_hash = local_entry.get("hash")
    if not local_hash and local_path and os.path.exists(local_path):
        local_hash = compute_file_hash(local_path)
        local_entry["hash"] = local_hash
    
    if cloud_etag and local_hash:
        if cloud_etag == local_hash:
            return "skip"
    
    local_mtime = int(local_entry.get("mtime", 0) or 0)
    cloud_mtime = int(cloud_entry.get("mtime", 0) or 0)
    
    if abs(local_mtime - cloud_mtime) > 2:
        if local_mtime > cloud_mtime:
            return "upload"
        else:
            return "download"
    
    local_size = int(local_entry.get("size", 0) or 0)
    cloud_size = int(cloud_entry.get("size", 0) or 0)
    
    if local_size != cloud_size:
        if local_size > cloud_size:
            return "upload"
        else:
            return "download"
    
    return "skip"


def diff_snapshots(prev_snapshot: Dict[str, Dict],
                   curr_local: Dict[str, Dict],
                   curr_cloud: Dict[str, Dict],
                   local_root: str = "") -> list[Dict[str, Any]]:
    """Compute sync operations based on previous and current snapshots."""
    operations = []
    all_paths = set(prev_snapshot.keys()) | set(curr_local.keys()) | set(curr_cloud.keys())
    for rel_path in sorted(all_paths):
        prev = prev_snapshot.get(rel_path, {})
        prev_local = prev.get("local", {})
        prev_cloud = prev.get("cloud", {})
        curr_l = curr_local.get(rel_path, {"exists": False})
        curr_c = curr_cloud.get(rel_path, {"exists": False})
        local_exists = curr_l.get("exists", False)
        cloud_exists = curr_c.get("exists", False)
        prev_local_existed = prev_local.get("exists", False)
        prev_cloud_existed = prev_cloud.get("exists", False)
        if local_exists and cloud_exists:
            local_changed = (curr_l.get("mtime") != prev_local.get("mtime") or
                           curr_l.get("size") != prev_local.get("size"))
            cloud_changed = (curr_c.get("etag") != prev_cloud.get("etag") or
                           curr_c.get("mtime") != prev_cloud.get("mtime"))
            if local_changed and cloud_changed:
                local_path = os.path.join(local_root, rel_path.replace("/", os.sep)) if local_root else ""
                action = resolve_conflict(curr_l, curr_c, local_path)
                operations.append({
                    "action": action,
                    "rel_path": rel_path,
                    "reason": "conflict_both_modified"
                })
            elif local_changed:
                operations.append({
                    "action": "upload",
                    "rel_path": rel_path,
                    "reason": "local_newer"
                })
            elif cloud_changed:
                operations.append({
                    "action": "download",
                    "rel_path": rel_path,
                    "reason": "cloud_newer"
                })
            else:
                operations.append({
                    "action": "noop",
                    "rel_path": rel_path,
                    "reason": "unchanged"
                })
        elif local_exists and not cloud_exists:
            if prev_cloud_existed:
                operations.append({
                    "action": "delete_local",
                    "rel_path": rel_path,
                    "reason": "cloud_deleted"
                })
            else:
                operations.append({
                    "action": "upload",
                    "rel_path": rel_path,
                    "reason": "new_local"
                })
        elif cloud_exists and not local_exists:
            if prev_local_existed or (prev.get("local") and prev["local"] != {"exists": False}):
                operations.append({
                    "action": "delete_cloud",
                    "rel_path": rel_path,
                    "reason": "local_deleted"
                })
            else:
                operations.append({
                    "action": "download",
                    "rel_path": rel_path,
                    "reason": "new_cloud"
                })
        else:
            if prev_local_existed or prev_cloud_existed:
                operations.append({
                    "action": "noop",
                    "rel_path": rel_path,
                    "reason": "both_deleted"
                })
    return operations


# ============================================================================
# TOMBSTONES & SOFT DELETION
# ============================================================================

class TombstoneStore:
    """Stub for old tombstone system - does nothing."""

    def __init__(self, settings: Any, folder_id: Any) -> None:
        self.settings = settings
        self.folder_id = folder_id

    def is_tombstoned(self, relpath: str) -> bool:
        return False

    def list_all_tombstones(self) -> list[dict]:
        return []

    def remove_tombstone(self, relpath: str) -> None:
        return None

    def add_tombstone(self, *args: Any, **kwargs: Any) -> None:
        return None

    def update_tombstone(self, *args: Any, **kwargs: Any) -> None:
        return None


class PendingQueue:
    """Stub for old pending queue - does nothing."""

    def __init__(self, settings: Any, folder_id: Any) -> None:
        self.settings = settings
        self.folder_id = folder_id

    def get_operations(self) -> list[dict]:
        return []

    def has_pending(self, relpath: str, op_type: str) -> bool:
        return False

    def remove_operation(self, *args: Any, **kwargs: Any) -> None:
        return None

    def update_operation(self, *args: Any, **kwargs: Any) -> None:
        return None


class SignatureCache:
    """Stub for old signature cache - does nothing."""

    def __init__(self, settings: Any, folder_id: Any) -> None:
        self.settings = settings
        self.folder_id = folder_id

    def get_all_local(self) -> dict:
        return {}

    def store_signature(self, *args: Any, **kwargs: Any) -> None:
        return None

    def remove_signature(self, *args: Any, **kwargs: Any) -> None:
        return None


class DeletionCoordinator:
    """Stub for old deletion coordinator - does nothing."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        return None

    def on_local_deletion(self, *args: Any, **kwargs: Any) -> None:
        return None

    def on_remote_deletion(self, *args: Any, **kwargs: Any) -> None:
        return None

    def on_local_folder_deletion(self, *args: Any, **kwargs: Any) -> None:
        return None

    def on_remote_folder_deletion(self, *args: Any, **kwargs: Any) -> None:
        return None

    def handle_local_rename(self, *args: Any, **kwargs: Any) -> None:
        return None

    def handle_remote_rename(self, *args: Any, **kwargs: Any) -> None:
        return None

    def process_pending_operations(self, *args: Any, **kwargs: Any) -> None:
        return None

    def cleanup_expired_tombstones(self) -> int:
        return 0


class RenameDetector:
    """Stub for old rename detection - does nothing"""
    @staticmethod
    def compute_signature(file_entry):
        """Compute signature for file (stub returns None)"""
        return None
    
    @staticmethod
    def detect_renames(deleted_paths, new_paths, signatures):
        """Detect renames based on signatures (stub returns empty dict)"""
        return {}


def create_tombstone(state: Dict, rel_path: str, origin: str, kind: str = "file") -> None:
    """Add tombstone entry to state."""
    if "tombstones" not in state:
        state["tombstones"] = []
    
    for ts in state["tombstones"]:
        if ts.get("path") == rel_path:
            ts["at"] = datetime.utcnow().isoformat() + "Z"
            ts["origin"] = origin
            ts["kind"] = kind
            return
    
    state["tombstones"].append({
        "path": rel_path,
        "kind": kind,
        "origin": origin,
        "at": datetime.utcnow().isoformat() + "Z"
    })


def is_tombstoned(state: Dict, rel_path: str, grace_period_minutes: float = 5.0) -> bool:
    """Check if path is tombstoned and within grace period."""
    import time
    tombstones = state.get("tombstones", [])
    now = time.time()
    for ts in tombstones:
        if ts.get("path") == rel_path:
            try:
                ts_time = datetime.fromisoformat(ts["at"].replace("Z", "+00:00")).timestamp()
                age_minutes = (now - ts_time) / 60.0
                if age_minutes <= grace_period_minutes:
                    return True
            except Exception:
                pass
    return False


def cleanup_tombstones(state: Dict, retention_days: int = 30) -> None:
    """Remove tombstones older than retention period."""
    if "tombstones" not in state:
        return
    now = datetime.utcnow().timestamp()
    cutoff = now - (retention_days * 86400)
    state["tombstones"] = [
        ts for ts in state["tombstones"]
        if datetime.fromisoformat(ts["at"].replace("Z", "+00:00")).timestamp() > cutoff
    ]


def check_mass_delete_guard(operations: list[Dict],
                            snapshot: Dict,
                            threshold_percent: float = 20.0,
                            min_files: int = 10) -> tuple[bool, str]:
    """Check if deletion operations exceed safety threshold."""
    total_files = len([p for p in snapshot.keys() if snapshot[p].get("local", {}).get("exists") or
                                                      snapshot[p].get("cloud", {}).get("exists")])
    delete_count = len([op for op in operations if op["action"] in ("delete_local", "delete_cloud")])
    sync_log("GUARD: total_files={}, delete_count={}, min_files={}, threshold={}%",
             total_files, delete_count, min_files, threshold_percent)
    if total_files < min_files:
        return (True, "below_threshold")
    if delete_count == 0:
        return (True, "no_deletions")
    delete_percent = (delete_count / total_files) * 100
    if delete_percent > threshold_percent:
        return (False, f"mass_delete_detected_{delete_count}_of_{total_files}_files_{delete_percent:.1f}%")
    return (True, "ok")


def scope_delete_guard(rel_path: str, sync_root_rel: str) -> bool:
    """Ensure deletion stays within sync scope."""
    if not sync_root_rel or sync_root_rel == "":
        return True
    norm_root = sync_root_rel.strip("/")
    norm_path = rel_path.strip("/")
    if norm_path == norm_root:
        return True
    if norm_path.startswith(norm_root + "/"):
        return True
    return False


def propagate_folder_tombstone(state: Dict, folder_rel: str, origin: str) -> None:
    """Create tombstones for all files/subfolders under a deleted folder."""
    snapshot = state.get("snapshot", {})
    folder_prefix = folder_rel.rstrip("/") + "/"
    for rel_path in snapshot.keys():
        if rel_path.startswith(folder_prefix) or rel_path == folder_rel:
            kind = "file" if "/" not in rel_path[len(folder_prefix):] else "dir"
            create_tombstone(state, rel_path, origin, kind)


def increment_folder_rev(state: Dict, rel_path: str = "") -> int:
    """Increment folder_rev for a folder path (including parent chain)."""
    if "snapshot" not in state:
        state["snapshot"] = {}
    folder_entry = state["snapshot"].get(rel_path, {})
    current_rev = folder_entry.get("folder_rev", 0)
    new_rev = current_rev + 1
    if rel_path not in state["snapshot"]:
        state["snapshot"][rel_path] = {}
    state["snapshot"][rel_path]["folder_rev"] = new_rev
    if rel_path:
        parts = rel_path.split("/")
        for i in range(len(parts) - 1):
            parent = "/".join(parts[:i+1])
            increment_folder_rev(state, parent)
    return new_rev


def get_folder_rev(state: Dict, rel_path: str = "") -> int:
    """Get current folder_rev for a folder path."""
    snapshot = state.get("snapshot", {})
    folder_entry = snapshot.get(rel_path, {})
    return folder_entry.get("folder_rev", 0)


def check_folder_notifications(project_id: int | str, folder_id: int | str) -> list[Dict]:
    """Check which subscribed folders have new changes."""
    subs = load_subscriptions()
    root_key = f"{project_id}-{folder_id}"
    root_subs = subs.get("roots", {}).get(root_key, {})
    state = load_state(project_id, folder_id)
    results = []
    for rel_path, sub_info in root_subs.items():
        if not isinstance(sub_info, dict) or not sub_info.get("subscribed"):
            continue
        current_rev = get_folder_rev(state, rel_path)
        last_seen = sub_info.get("last_seen_rev", 0)
        results.append({
            "rel_path": rel_path,
            "folder_rev": current_rev,
            "last_seen_rev": last_seen,
            "has_updates": current_rev > last_seen
        })
    return results


def mark_folder_seen(project_id: int | str, folder_id: int, rel_path: str) -> bool:
    """Mark folder as seen (update last_seen_rev to current folder_rev)."""
    state = load_state(project_id, folder_id)
    current_rev = get_folder_rev(state, rel_path)
    return update_subscription(project_id, folder_id, rel_path, 
                              subscribed=True, last_seen_rev=current_rev)


def decide_sync(doc, local_path, user_tz: str = "Europe/Moscow", tol: float = 2.0):
    """Decide sync direction based on cloud vs local times."""
    from datetime import datetime, timezone, timedelta
    from pathlib import Path
    try:
        from zoneinfo import ZoneInfo
    except Exception:
        ZoneInfo = None
    try:
        if not isinstance(doc, dict):
            return "skip"
        raw = doc.get("modifTime") or doc.get("createTime")
        if not raw:
            return "skip"
        cloud_dt = None
        if isinstance(raw, (int, float)):
            try:
                ts = float(raw)
                if ts > 1e12:
                    ts = ts / 1000.0
                cloud_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            except Exception:
                cloud_dt = None
        if cloud_dt is None:
            s = str(raw).strip()
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            try:
                dt = datetime.fromisoformat(s)
            except Exception:
                return "skip"
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            cloud_dt = dt
        try:
            if ZoneInfo is not None:
                tz = ZoneInfo(user_tz)
                cloud_ts = cloud_dt.astimezone(tz).timestamp()
            else:
                cloud_ts = cloud_dt.timestamp()
        except Exception:
            cloud_ts = cloud_dt.timestamp()
        try:
            lp = Path(local_path)
            local_ts = float(lp.stat().st_mtime)
        except Exception:
            local_ts = 0.0
        t = float(tol)
        if local_ts > cloud_ts + t:
            action = "upload"
        elif cloud_ts > local_ts + t:
            action = "download"
        else:
            action = "skip"
        return action
    except Exception as e:
        return "skip"


def parse_date_like(s: str, tz_offset_min: int | None = None) -> float:
    """Parse a cloud datetime into UTC epoch seconds."""
    if not s:
        return 0.0
    tz_offset = tz_offset_min or _cloud_tz_offset_minutes()
    try:
        if isinstance(s, (int, float)) or (isinstance(s, str) and s.strip().isdigit()):
            val = float(s)
            if val > 1e12:
                val = val / 1000.0
            return float(val)
    except Exception:
        pass
    s = str(s).strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            ofs = int(tz_offset)
            dt2 = dt + timedelta(minutes=ofs)
            return dt2.replace(tzinfo=timezone.utc).timestamp()
        return dt.timestamp()
    except Exception:
        pass
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            ofs = int(tz_offset)
            dt2 = dt + timedelta(minutes=ofs)
            return dt2.replace(tzinfo=timezone.utc).timestamp()
        except (ValueError, TypeError):
            continue
    return 0.0
