# -*- coding: utf-8 -*-

import os
import hashlib
import shutil
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Callable, Tuple

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
        sync_log("Local root scan aborted", path=local_root, component="FS", op="scan", trace_id=trace_id, result="fail", reason="not_found")
        return files
    if not os.path.isdir(local_root):
        sync_log("Local root scan aborted", path=local_root, component="FS", op="scan", trace_id=trace_id, result="fail", reason="not_directory")
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
        sync_log(f"_parse_timestamp({field_name}): value is None/empty, returning 0.0", component="API", op="parse")
        return 0.0

    original_value = value

    if isinstance(value, (int, float)):
        result = value / 1000.0 if value > 1e12 else float(value)
        sync_log(f"_parse_timestamp({field_name}): int/float input={value} result={result}", component="API", op="parse")
        return result

    s = str(value).strip()

    try:
        val = float(s)
        result = val / 1000.0 if val > 1e12 else val
        sync_log(f"_parse_timestamp({field_name}): float_string input={s} result={result}", component="API", op="parse")
        return result
    except:
        pass

    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        result = dt.timestamp()
        sync_log(f"_parse_timestamp({field_name}): iso_string input={original_value} result={result}", component="API", op="parse")
        return result
    except Exception as e:
        sync_log(f"_parse_timestamp({field_name}): iso_string FAILED input={original_value} error={e}", component="API", op="parse")
        pass

    sync_log(f"_parse_timestamp({field_name}): ALL METHODS FAILED input={original_value}", component="API", op="parse")
    return 0.0


def get_cloud_files(api, project_id: int | str, folder_id: int | str, trace_id: str = "", force: bool = False) -> Dict[str, Dict[str, Any]]:
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
                target_id_norm = normalize_id(folder_id)
                def find_folder_in_tree(tree, target_id):
                    if not isinstance(tree, list):
                        return None
                    for item in tree:
                        if normalize_id(item.get("id")) == target_id:
                            return item
                        children = item.get("children") or item.get("folders") or []
                        result = find_folder_in_tree(children, target_id)
                        if result:
                            return result
                    return None
                tree_root = find_folder_in_tree(folders_tree, target_id_norm)
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
                                sync_log("Got document details", component="NET", op="fetch", trace_id=trace_id, result="ok", extra=f"file_id={file_id} keys={list(doc_details.keys())[:10]}")
                                raw_time = doc_details.get("createTime") or doc_details.get("createdAt") or doc_details.get("created") or doc_details.get("modifTime") or doc_details.get("created_ts")
                                modif_raw = doc_details.get("modifTime") or doc_details.get("updatedAt") or doc_details.get("modified_ts") or raw_time
                                sync_log(f"Raw time fields", component="API", op="parse", trace_id=trace_id, result="ok", extra=f"createTime={doc_details.get('createTime')} createdAt={doc_details.get('createdAt')} created={doc_details.get('created')} modifTime={doc_details.get('modifTime')} created_ts={doc_details.get('created_ts')} modified_ts={doc_details.get('modified_ts')} raw_time={raw_time} modif_raw={modif_raw}")
                                create_ts = _parse_timestamp(raw_time, "createTime")
                                modif_ts = _parse_timestamp(modif_raw, "modifTime")
                                file_size = int(doc_details.get("size") or doc_details.get("file_size") or item.get("size") or 0)
                                files[rel_path] = {
                                    "createTime": create_ts,
                                    "createdAt": doc_details.get("createdAt") or doc_details.get("createTime") or "",
                                    "modifTime": modif_ts,
                                    "updatedAt": doc_details.get("updatedAt") or doc_details.get("modifTime") or "",
                                    "lastModified": modif_ts,
                                    "size": file_size,
                                    "id": file_id,
                                    "createdBy": doc_details.get("createdBy") or "",
                                    "modifiedBy": doc_details.get("modifiedBy") or "",
                                    "version": doc_details.get("version") or 0
                                }
                                sync_log("File added to cloud_files", component="NET", op="list", trace_id=trace_id, result="ok", extra=f"path={rel_path} file_id={file_id} create_ts={create_ts} modif_ts={modif_ts} lastModified={modif_ts} size={file_size}")
                        except Exception as e:
                            sync_log("Failed to get document details", component="NET", op="fetch", trace_id=trace_id, result="fail", reason=str(e), extra=f"file_id={file_id}")
                elif item_type == "folder":
                    folder_name = item.get("name") or item.get("title") or item.get("folderName") or ""
                    new_path = f"{parent_path}/{folder_name}" if parent_path else folder_name
                    folder_id = normalize_id(item.get("id"))
                    raw_time = item.get("createTime") or item.get("createdAt") or item.get("created") or item.get("modifTime")
                    create_ts = _parse_timestamp(raw_time, "createTime")
                    modif_raw = item.get("modifTime") or item.get("updatedAt") or raw_time
                    modif_ts = _parse_timestamp(modif_raw, "modifTime")
                    if is_debug_sync():
                        sync_log("Found folder in tree", component="NET", op="list", trace_id=trace_id, result="ok", extra=f"path={new_path} id={folder_id} create_ts={create_ts} modif_ts={modif_ts}")
                    files[new_path] = {
                        "createTime": create_ts,
                        "createdAt": item.get("createdAt") or item.get("createTime") or "",
                        "modifTime": modif_ts,
                        "updatedAt": item.get("updatedAt") or item.get("modifTime") or "",
                        "lastModified": modif_ts,
                        "size": 0,
                        "is_folder": True,
                        "id": folder_id
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
        sync_log("Looking for children in tree_root", component="NET", op="list", trace_id=trace_id, result="ok", extra=f"keys={list(tree_root.keys())}")
        for key in ("children", "folders", "items", "documents", "content", "subFolders"):
            potential_tree = tree_root.get(key)
            if isinstance(potential_tree, list):
                tree = potential_tree
                sync_log("Found children in key", component="NET", op="list", trace_id=trace_id, result="ok", extra=f"key={key} items={len(tree)}")
                if is_debug_sync() and len(tree) > 0:
                    first_item_type = tree[0].get("type", "unknown") if isinstance(tree[0], dict) else type(tree[0]).__name__
                    sync_log("First item type in tree", component="NET", op="list", trace_id=trace_id, result="ok", extra=f"type={first_item_type}")
                break

        if tree:
            _process_tree(tree)
        else:
            sync_log("No children found in tree_root, trying to fetch documents directly", component="NET", op="list", trace_id=trace_id, result="ok")
            try:
                documents = api.list_documents_in_folder(folder_id, force=True)
                if documents:
                    sync_log("Got documents from folder", component="NET", op="list", trace_id=trace_id, result="ok", extra=f"documents={len(documents)}")
                    for doc in documents:
                        if not isinstance(doc, dict):
                            continue
                        doc_type = doc.get("type", "").lower()
                        if doc_type != "file":
                            continue
                        doc_name = doc.get("name") or doc.get("title") or doc.get("originalName") or ""
                        if not doc_name:
                            continue
                        file_id = normalize_id(doc.get("id"))
                        if not file_id:
                            continue
                        try:
                            doc_details = api.get_document_details(file_id)
                            if doc_details:
                                sync_log("Got document details (method 2)", component="NET", op="fetch", trace_id=trace_id, result="ok", extra=f"file_id={file_id} keys={list(doc_details.keys())[:10]}")
                                raw_time = doc_details.get("createTime") or doc_details.get("createdAt") or doc_details.get("created") or doc_details.get("modifTime") or doc_details.get("created_ts")
                                modif_raw = doc_details.get("modifTime") or doc_details.get("updatedAt") or doc_details.get("modified_ts") or raw_time
                                sync_log(f"Raw time fields (method 2)", component="API", op="parse", trace_id=trace_id, result="ok", extra=f"createTime={doc_details.get('createTime')} createdAt={doc_details.get('createdAt')} created={doc_details.get('created')} modifTime={doc_details.get('modifTime')} created_ts={doc_details.get('created_ts')} modified_ts={doc_details.get('modified_ts')} raw_time={raw_time} modif_raw={modif_raw}")
                                create_ts = _parse_timestamp(raw_time, "createTime")
                                modif_ts = _parse_timestamp(modif_raw, "modifTime")
                                file_size = int(doc_details.get("size") or doc_details.get("file_size") or doc.get("size") or 0)
                                files[doc_name] = {
                                    "createTime": create_ts,
                                    "createdAt": doc_details.get("createdAt") or doc_details.get("createTime") or "",
                                    "modifTime": modif_ts,
                                    "updatedAt": doc_details.get("updatedAt") or doc_details.get("modifTime") or "",
                                    "lastModified": modif_ts,
                                    "size": file_size,
                                    "id": file_id,
                                    "createdBy": doc_details.get("createdBy") or "",
                                    "modifiedBy": doc_details.get("modifiedBy") or "",
                                    "version": doc_details.get("version") or 0
                                }
                                sync_log("File added to cloud_files (method 2)", component="NET", op="list", trace_id=trace_id, result="ok", extra=f"path={doc_name} file_id={file_id} create_ts={create_ts} modif_ts={modif_ts} lastModified={modif_ts} size={file_size}")
                        except Exception as e:
                            sync_log("Failed to get document details", component="NET", op="fetch", trace_id=trace_id, result="fail", reason=str(e), extra=f"file_id={file_id}")
                else:
                    sync_log("No documents in folder", component="NET", op="list", trace_id=trace_id, result="skip", reason="no_documents")
            except Exception as e:
                sync_log("Failed to fetch documents from folder", component="NET", op="list", trace_id=trace_id, result="fail", reason=str(e))
    except Exception as e:
        sync_log("Failed to fetch cloud files", component="NET", op="list", trace_id=trace_id, result="fail", reason=str(e))
    
    total_files = len([f for f in files.values() if not f.get("is_folder")])
    total_folders = len([f for f in files.values() if f.get("is_folder")])
    sync_log("Cloud files fetched", component="NET", op="list", trace_id=trace_id, result="ok", extra=f"files={total_files} folders={total_folders} total={len(files)} force={force}")
    if total_files > 0 and is_debug_sync():
        for path, info in list(files.items())[:5]:
            if not info.get("is_folder"):
                sync_log("Cloud file sample", component="NET", op="list", trace_id=trace_id, result="ok", extra=f"path={path} id={info.get('id')} size={info.get('size')}")
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

    # Safety check: if cloud_files is empty but we have local files, warn and skip deletions
    has_local_files = any(not f.get("is_folder", False) for f in local_files.values())
    has_cloud_files = any(not f.get("is_folder", False) for f in cloud_files.values())
    if has_local_files and not has_cloud_files and not is_initial_sync and old_state:
        sync_log("WARNING: Cloud returned empty but local files exist - this may be an API error", component="SYNC", op="compare", trace_id=trace_id, result="warn", extra=f"local={len(local_files)} cloud={len(cloud_files)} old_state={len(old_state)}")
        sync_log("Skipping sync to prevent accidental deletion", component="SYNC", op="compare", trace_id=trace_id, result="skip")
        return []

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
            cloud_mtime_val = cloud_files[path].get("lastModified")
            op = {
                "action": "download",
                "path": path,
                "cloud_id": cloud_files[path]["id"],
                "cloud_mtime": cloud_mtime_val
            }
            if is_debug_sync():
                sync_log("Creating download operation", component="SYNC", op="compare", trace_id=trace_id, result="ok", path=path, extra=f"cloud_mtime={cloud_mtime_val} cloud_files_keys={list(cloud_files[path].keys())}")
            if cloud_files[path].get("is_folder"):
                op["is_folder"] = "true"
            operations.append(op)
        elif in_local and not in_cloud and not was_in_old:
            if is_debug_sync():
                sync_log("New local only", component="SYNC", op="compare", trace_id=trace_id, result="ok", path=path, extra=f"action=upload is_folder={is_folder}")
            operations.append({
                "action": "upload",
                "path": path,
                "is_folder": "true" if is_folder else "false"
            })
        elif was_in_old and in_local and not in_cloud:
            old_id = old_state.get(path, {}).get("id")
            if old_id:
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
            else:
                if is_debug_sync():
                    sync_log("Was in old_state but no cloud id - retry upload", component="SYNC", op="compare", trace_id=trace_id, result="ok", path=path, extra=f"action=upload is_folder={is_folder}")
                operations.append({
                    "action": "upload",
                    "path": path,
                    "is_folder": "true" if is_folder else "false"
                })
        elif was_in_old and in_cloud and not in_local:
            if is_initial_sync:
                if is_debug_sync():
                    sync_log("Initial sync: exists in cloud, download", component="SYNC", op="compare", trace_id=trace_id, result="ok", path=path, extra=f"action=download is_folder={is_folder}")
                op = {
                    "action": "download",
                    "path": path,
                    "cloud_id": cloud_files[path]["id"],
                    "cloud_mtime": cloud_files[path].get("lastModified"),
                    "cloud_ctime": cloud_files[path].get("createTime")
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
            cloud_mtime = cloud_files[path].get("lastModified", 0)
            sync_log("Comparing file times", component="SYNC", op="compare", trace_id=trace_id, result="ok", path=path, extra=f"local_mtime={local_mtime} cloud_mtime={cloud_mtime} tolerance={tolerance} diff={abs(local_mtime - cloud_mtime)}")
            action = None
            if abs(local_mtime - cloud_mtime) > tolerance:
                if local_mtime > cloud_mtime:
                    sync_log("Local lastModified is newer, upload", component="SYNC", op="compare", trace_id=trace_id, result="ok", path=path, extra=f"action=upload local_mtime={local_mtime} cloud_mtime={cloud_mtime}")
                    action = "upload"
                else:
                    sync_log("Cloud lastModified is newer, download", component="SYNC", op="compare", trace_id=trace_id, result="ok", path=path, extra=f"action=download local_mtime={local_mtime} cloud_mtime={cloud_mtime}")
                    action = "download"
            if action:
                op = {
                    "action": action,
                    "path": path
                }
                if action == "download":
                    op["cloud_id"] = cloud_files[path]["id"]
                    op["cloud_mtime"] = cloud_mtime
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


def _compose_ui_transfer_hooks(ui_hooks: Optional[Dict[str, Any]], folder_id: int | str) -> Optional[Dict[str, Any]]:
    """Build throttled execute-level hooks from optional UI ``ui_hooks`` (thread callbacks)."""
    if not ui_hooks:
        return None
    raw_begin = ui_hooks.get("on_file_begin")
    raw_prog = ui_hooks.get("on_transfer_progress")
    if not raw_begin and not raw_prog:
        return None
    fid_norm = normalize_id(folder_id)
    last_t = [-1e9]
    import time as _time

    def wrapped_begin(action: str, rel_path: str, _fid_arg: str) -> None:
        last_t[0] = -1e9
        if raw_begin:
            try:
                raw_begin(action, rel_path, fid_norm)
            except Exception:
                pass

    def throttled_progress(action: str, rel_path: str, _fid_arg: str, done: int, total: int) -> None:
        if not raw_prog:
            return
        now = _time.time()
        if int(total or 0) > 0:
            if int(done) < int(total) and (now - last_t[0]) < 0.2:
                return
        else:
            if (now - last_t[0]) < 0.2:
                return
        last_t[0] = now
        try:
            raw_prog(action, rel_path, fid_norm, int(done), int(total))
        except Exception:
            pass

    return {
        "on_file_begin": wrapped_begin if (raw_begin or raw_prog) else None,
        "on_transfer_progress": throttled_progress if raw_prog else None,
    }


_FOLDER_LISTING_TYPES = frozenset(s.casefold() for s in ("folder", "dir", "directory", "папка"))
_FILE_LIKE_TYPES = frozenset(s.casefold() for s in ("file", "document", "файл"))


def _cloud_list_item_matches_upload(child: dict, wanted_base: str, local_size: int) -> bool:
    """Best-effort: listing row looks like the uploaded document (not a same-named folder)."""
    if not isinstance(child, dict):
        return False
    typ_raw = str(child.get("type", "") or "").strip()
    typ = typ_raw.casefold()
    if typ in _FOLDER_LISTING_TYPES:
        return False
    if child.get("isFolder") or child.get("is_folder"):
        return False
    cloud_name = (
        child.get("name")
        or child.get("originalName")
        or child.get("fileName")
        or child.get("title")
        or ""
    )
    if not cloud_name:
        return False
    if os.name == "nt":
        same = str(cloud_name).casefold() == str(wanted_base).casefold()
    else:
        same = str(cloud_name) == str(wanted_base)
    if not same:
        return False
    try:
        cloud_sz = int(child.get("size") or child.get("file_size") or 0)
    except Exception:
        cloud_sz = 0
    if cloud_sz > 0 and local_size > 0 and cloud_sz != local_size:
        return False

    idish = any(bool(child.get(k)) for k in ("id", "fileUid", "documentId"))
    dtype = any(
        child.get(k) not in (None, "", 0)
        for k in ("documentType", "documentTypeId")
    )
    size_confirms = local_size > 0 and cloud_sz > 0 and cloud_sz == local_size
    if not (idish or dtype or (size_confirms and (not typ_raw or typ in _FILE_LIKE_TYPES))):
        return False
    return True


def _cloud_list_has_uploaded_file(children, wanted_base: str, local_size: int) -> bool:
    if not isinstance(children, list):
        return False
    for child in children:
        if _cloud_list_item_matches_upload(child, wanted_base, local_size):
            return True
    return False


def _first_child_list_from_folder_payload(fd: Any) -> Tuple[list, str]:
    """Pick first non-empty listing array from get_folder_details / tree node shape."""
    if not isinstance(fd, dict):
        return [], ""
    for key in ("children", "files", "documents", "items", "content", "folders"):
        ch = fd.get(key)
        if isinstance(ch, list) and ch:
            return ch, key
    return [], ""


def _invalidate_upload_verify_caches(api, folder_id_norm: str) -> None:
    """Best-effort: drop tree/folder/doc list caches so verify reads fresh data."""
    try:
        c = getattr(api, "cache", None)
        if not isinstance(c, dict):
            return
        fid = str(folder_id_norm or "")
        if fid:
            c.pop(f"folder:{fid}", None)
            c.pop(f"folder_docs:{fid}", None)
        for k in list(c.keys()):
            if isinstance(k, str) and k.startswith("tree:"):
                try:
                    c.pop(k, None)
                except Exception:
                    pass
    except Exception:
        pass


def _invalidate_tree_cache_after_upload_recovered(api) -> None:
    """Align with upload_file success: drop project tree cache entries."""
    try:
        c = getattr(api, "cache", None)
        if not isinstance(c, dict):
            return
        for k in list(c.keys()):
            if isinstance(k, str) and k.startswith("tree:"):
                try:
                    c.pop(k, None)
                except Exception:
                    pass
    except Exception:
        pass


def _verify_uploaded_file_visible_in_cloud(
    api,
    project_id: int | str,
    parent_folder_id: int | str,
    base_name: str,
    local_size: int,
    trace_id: str,
) -> bool:
    """After transient upload failure: retries + list_files_result + folder details + documents list."""
    import time as _time

    pid_s = str(project_id) if project_id is not None else ""
    fid_s = normalize_id(parent_folder_id)
    delays_before = (0.0, 1.0, 2.0)

    for attempt in range(3):
        if delays_before[attempt] > 0:
            try:
                _time.sleep(float(delays_before[attempt]))
            except Exception:
                pass

        _invalidate_upload_verify_caches(api, fid_s)

        lr = None
        children: list = []
        source = ""

        lf = getattr(api, "list_files_result", None)
        if callable(lf):
            try:
                lr = lf(parent_folder_id, project_id=project_id)
            except Exception:
                lr = None
            if lr is not None and getattr(lr, "ok", False):
                raw = getattr(lr, "data", None)
                if isinstance(raw, list):
                    children = raw
                    source = "list_files_result"

        n = len(children)
        sync_log(
            "upload_verify transient",
            component="NET",
            op="upload_verify",
            trace_id=trace_id,
            result="ok",
            extra=(
                f"attempt={attempt + 1}/3 parent_folder_id={fid_s} project_id={pid_s} "
                f"base_name={base_name!r} local_size={local_size} source={source!r} children={n}"
            ),
        )

        if _cloud_list_has_uploaded_file(children, base_name, local_size):
            return True

        gd = getattr(api, "get_folder_details", None)
        if callable(gd):
            try:
                fd = gd(parent_folder_id, force=True)
            except Exception:
                fd = None
            ch2, key2 = _first_child_list_from_folder_payload(fd if isinstance(fd, dict) else {})
            sync_log(
                "upload_verify transient",
                component="NET",
                op="upload_verify",
                trace_id=trace_id,
                result="ok",
                extra=(
                    f"attempt={attempt + 1}/3 parent_folder_id={fid_s} project_id={pid_s} "
                    f"base_name={base_name!r} local_size={local_size} source=get_folder_details:{key2!r} children={len(ch2)}"
                ),
            )
            if _cloud_list_has_uploaded_file(ch2, base_name, local_size):
                return True

        ld = getattr(api, "list_documents_in_folder", None)
        if callable(ld):
            try:
                docs = ld(parent_folder_id, force=True)
            except Exception:
                docs = []
            if not isinstance(docs, list):
                docs = []
            sync_log(
                "upload_verify transient",
                component="NET",
                op="upload_verify",
                trace_id=trace_id,
                result="ok",
                extra=(
                    f"attempt={attempt + 1}/3 parent_folder_id={fid_s} project_id={pid_s} "
                    f"base_name={base_name!r} local_size={local_size} source=list_documents_in_folder children={len(docs)}"
                ),
            )
            if _cloud_list_has_uploaded_file(docs, base_name, local_size):
                return True

    return False


def execute_sync_operations(
    api,
    project_id: int | str,
    folder_id: int | str,
    local_root: str,
    operations: list,
    dry_run: bool = False,
    trace_id: str = "",
    *,
    ui_transfer_hooks: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Execute sync operations. Returns statistics."""
    import time
    
    stats = {
        "downloaded": 0,
        "uploaded": 0,
        "deleted_local": 0,
        "deleted_cloud": 0,
        "errors": [],
        "failed_uploads": [],
        "failed_downloads": [],
        "failed_deletes_local": [],
        "failed_deletes_cloud": []
    }
    
    sync_doc_type_id: int | None = None
    try:
        types_map = api.get_document_types() or {}
        if isinstance(types_map, dict):
            ids: list[int] = []
            for k in types_map.keys():
                try:
                    ids.append(int(str(k).strip()))
                except Exception:
                    continue
            ids = sorted(set(ids))
            
            if ids:
                try:
                    from larix_nexus.utils.settings import load_settings
                    settings = load_settings()
                    last = settings.get("last_document_type_id")
                    try:
                        last_int = int(str(last).strip()) if last is not None else None
                    except Exception:
                        last_int = None
                    
                    if last_int is not None and last_int in ids:
                        sync_doc_type_id = last_int
                    else:
                        sync_doc_type_id = ids[0]
                    
                    sync_log("Sync will use document_type_id={}", sync_doc_type_id, component="SYNC", op="init", trace_id=trace_id)
                except Exception:
                    if ids:
                        sync_doc_type_id = ids[0]
                    sync_log("Sync using fallback document_type_id={}", sync_doc_type_id, component="SYNC", op="init", trace_id=trace_id)
    except Exception as e:
        sync_log("Failed to get document types, upload may fail: {}", str(e), component="SYNC", op="init", trace_id=trace_id, result="warn")
    
    sync_log("Starting operations execution", component="SYNC", op="execute", trace_id=trace_id, result="ok", extra=f"total={len(operations)} dry_run={dry_run}")
    cloud_folders = get_cloud_folder_structure(api, project_id, normalize_id(folder_id))

    def _extract_created_folder_id(result, context=""):
        if result is True:
            sync_log("Folder creation returned True without id",
                     component="NET", op="mkdir", trace_id=trace_id,
                     result="warn", path=context,
                     reason="no_folder_id")
            return None
        if result is False:
            sync_log("Folder creation returned False",
                     component="NET", op="mkdir", trace_id=trace_id,
                     result="fail", path=context,
                     reason="api_returned_false")
            return None
        if isinstance(result, dict):
            fid = normalize_id(result.get("id"))
            return fid if fid else None
        if isinstance(result, (int, float)) and not isinstance(result, bool):
            fid = normalize_id(result)
            return fid if fid else None
        if isinstance(result, str):
            s = result.strip()
            if s:
                fid = normalize_id(s)
                return fid if fid else None
        sync_log("Folder creation returned invalid result",
                 component="NET", op="mkdir", trace_id=trace_id,
                 result="fail", path=context,
                 extra=f"result_type={type(result).__name__}")
        return None

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
                        new_folder_id = _extract_created_folder_id(result, current_path)

                        if new_folder_id:
                            cloud_folders[current_path] = new_folder_id
                            current_folder_id = new_folder_id
                        else:
                            sync_log("Folder creation did not return valid id",
                                     component="NET", op="mkdir", trace_id=trace_id,
                                     result="fail", path=current_path,
                                     extra=f"result_type={type(result).__name__}")
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
                    cloud_mtime = op.get("cloud_mtime", 0)
                    try:
                        os.makedirs(local_path, exist_ok=True)
                        if cloud_mtime > 0:
                            try:
                                os.utime(local_path, (float(cloud_mtime), float(cloud_mtime)))
                            except Exception as e:
                                sync_log("Failed to set folder mtime", component="FS", op="utime", trace_id=trace_id, result="warn", path=path, reason=str(e))
                        sync_log("Created local folder", component="FS", op="create", trace_id=trace_id, result="ok", path=path, extra=f"mtime={cloud_mtime}")
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
                    sync_log("[DRY RUN] Download file", component="SYNC", op="download", trace_id=trace_id, result="skip", path=path, reason="dry_run")
                else:
                    local_path = os.path.join(local_root, path.replace("/", os.sep))
                    part_path = f"{local_path}.part"
                    dir_path = os.path.dirname(local_path)
                    if dir_path:
                        try:
                            os.makedirs(dir_path, exist_ok=True)
                        except Exception as e:
                            sync_log("Failed to create parent directory", component="FS", op="mkdir", trace_id=trace_id, result="fail", path=dir_path, reason=str(e))

                    cloud_id = op["cloud_id"]
                    cloud_mtime = op.get("cloud_mtime", 0)
                    sync_log("About to download file", component="SYNC", op="execute", trace_id=trace_id, result="ok", path=path, extra=f"cloud_id={cloud_id} cloud_mtime={cloud_mtime} cloud_mtime_type={type(cloud_mtime)}")
                    file_existed_before = os.path.exists(local_path)
                    success = False
                    uhooks = ui_transfer_hooks or {}
                    uh_begin = uhooks.get("on_file_begin")
                    uh_prog = uhooks.get("on_transfer_progress")
                    ui_action = "download"
                    if uh_begin:
                        try:
                            uh_begin(ui_action, path, normalize_id(folder_id))
                        except Exception:
                            pass

                    def _dl_prog(d: int, tot: int) -> None:
                        if uh_prog:
                            try:
                                uh_prog(ui_action, path, normalize_id(folder_id), d, tot)
                            except Exception:
                                pass

                    _prog_cb = _dl_prog if uh_prog else None
                    try:
                        if os.path.exists(part_path):
                            os.remove(part_path)
                        with open(part_path, 'wb') as f:
                            success = api.write_file_to(cloud_id, f, progress_cb=_prog_cb)
                        if success:
                            os.replace(part_path, local_path)
                    except Exception as e:
                        sync_log("Download failed", component="NET", op="download", trace_id=trace_id, result="fail", path=path, reason=str(e))
                        success = False

                    duration_ms = int((time.time() - start_time) * 1000)

                    if success:
                        sync_log("Download succeeded, setting mtime", component="SYNC", op="download", trace_id=trace_id, result="ok", path=path, extra=f"cloud_mtime={cloud_mtime}")

                        initial_mtime = os.path.getmtime(local_path)
                        sync_log("File initial mtime", component="FS", op="utime", trace_id=trace_id, result="ok", path=path, extra=f"initial={initial_mtime}")

                        if cloud_mtime and cloud_mtime > 0:
                            try:
                                import time as time_module
                                time_module.sleep(0.01)
                                mtime_float = float(cloud_mtime)
                                os.utime(local_path, (mtime_float, mtime_float))
                                actual_mtime = os.path.getmtime(local_path)
                                sync_log("Set file mtime successfully", component="FS", op="utime", trace_id=trace_id, result="ok", path=path, extra=f"requested={cloud_mtime} requested_float={mtime_float} actual={actual_mtime} diff={abs(actual_mtime - mtime_float)}")
                            except Exception as e:
                                sync_log("Failed to set file mtime", component="FS", op="utime", trace_id=trace_id, result="warn", path=path, reason=str(e))
                                import traceback
                                sync_log("UTime exception traceback", component="FS", op="utime", trace_id=trace_id, result="warn", path=path, reason=traceback.format_exc())
                        else:
                            sync_log("Skipping mtime set - cloud_mtime is 0 or negative", component="FS", op="utime", trace_id=trace_id, result="skip", path=path, reason=f"cloud_mtime={cloud_mtime}")

                        final_mtime = os.path.getmtime(local_path)
                        sync_log("File final mtime", component="FS", op="utime", trace_id=trace_id, result="ok", path=path, extra=f"final={final_mtime} changed={final_mtime != initial_mtime}")

                        stats["downloaded"] += 1
                        sync_log("Downloaded file", component="NET", op="download", trace_id=trace_id, result="ok", path=path, duration_ms=duration_ms, extra=f"mtime={cloud_mtime}")
                    else:
                        stats["errors"].append(f"Download failed: {path}")
                        stats["failed_downloads"].append(path)
                        sync_log("Download failed", component="NET", op="download", trace_id=trace_id, result="fail", path=path, duration_ms=duration_ms, reason="api_returned_false")
                        try:
                            if os.path.exists(part_path):
                                os.remove(part_path)
                                sync_log("Removed partial temp file after failed download", component="FS", op="cleanup", trace_id=trace_id, result="ok", path=f"{path}.part")
                        except Exception as cleanup_err:
                            sync_log("Failed to remove partial temp file after failed download", component="FS", op="cleanup", trace_id=trace_id, result="warn", path=f"{path}.part", reason=str(cleanup_err))
                        if file_existed_before:
                            sync_log("Download target existed before operation, existing file preserved", component="FS", op="cleanup", trace_id=trace_id, result="warn", path=path, reason="file_existed_before")
            
            elif action == "upload":
                is_folder = op.get("is_folder") == "true"
                if dry_run or is_dry_run():
                    sync_log("[DRY RUN] Upload {}", component="NET", op="upload", trace_id=trace_id, result="skip", path=path, reason="dry_run", extra="folder" if is_folder else "file")
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
                        if is_folder:
                            if path in cloud_folders:
                                sync_log("Folder already exists in cloud, skipping", component="NET", op="mkdir", trace_id=trace_id, result="skip", path=path, extra=f"folder_id={cloud_folders[path]}")
                                stats["uploaded"] += 1
                            else:
                                folder_name = os.path.basename(path)
                                result = api.create_folder(project_id, parent_folder_id, folder_name)
                                duration_ms = int((time.time() - start_time) * 1000)
                                
                                new_fid = _extract_created_folder_id(result, path)

                                if new_fid:
                                    cloud_folders[path] = new_fid
                                    stats["uploaded"] += 1
                                    sync_log("Created folder", component="NET", op="mkdir", trace_id=trace_id, result="ok", path=path, duration_ms=duration_ms, extra=f"folder_id={new_fid}")
                                else:
                                    stats["errors"].append(f"Create folder failed: {path}")
                                    sync_log("Create folder failed", component="NET", op="mkdir", trace_id=trace_id, result="fail", path=path, duration_ms=duration_ms, reason="no_valid_folder_id")
                        else:
                            uhooks = ui_transfer_hooks or {}
                            uh_begin = uhooks.get("on_file_begin")
                            uh_prog = uhooks.get("on_transfer_progress")
                            if uh_begin:
                                try:
                                    uh_begin("upload", path, normalize_id(folder_id))
                                except Exception:
                                    pass

                            def _up_prog(d: int, tot: int) -> None:
                                if uh_prog:
                                    try:
                                        uh_prog("upload", path, normalize_id(folder_id), d, tot)
                                    except Exception:
                                        pass

                            _up_cb = _up_prog if uh_prog else None
                            result = api.upload_file(
                                parent_folder_id,
                                local_path_full,
                                os.path.basename(path),
                                document_type_id=sync_doc_type_id,
                                progress_cb=_up_cb,
                            )
                            duration_ms = int((time.time() - start_time) * 1000)
                            
                            if result:
                                stats["uploaded"] += 1
                                sync_log("Uploaded file", component="NET", op="upload", trace_id=trace_id, result="ok", path=path, duration_ms=duration_ms)
                            else:
                                recovered = False
                                try:
                                    transient = bool(getattr(api, "_last_upload_transient", False))
                                except Exception:
                                    transient = False
                                if transient:
                                    try:
                                        base_name = os.path.basename(path.replace("\\", "/"))
                                        try:
                                            loc_sz = int(os.path.getsize(local_path_full))
                                        except Exception:
                                            loc_sz = 0
                                        recovered = _verify_uploaded_file_visible_in_cloud(
                                            api,
                                            project_id,
                                            parent_folder_id,
                                            base_name,
                                            loc_sz,
                                            trace_id,
                                        )
                                    except Exception:
                                        recovered = False
                                if recovered:
                                    stats["uploaded"] += 1
                                    try:
                                        _invalidate_tree_cache_after_upload_recovered(api)
                                    except Exception:
                                        pass
                                    sync_log(
                                        "Upload response lost but file exists in cloud",
                                        component="NET",
                                        op="upload",
                                        trace_id=trace_id,
                                        result="ok",
                                        path=path,
                                        duration_ms=duration_ms,
                                    )
                                else:
                                    err_note = ""
                                    try:
                                        err_note = str(getattr(api, "_last_upload_error", "") or "").strip()
                                    except Exception:
                                        err_note = ""
                                    if transient:
                                        stats["errors"].append(
                                            f"Upload failed: {path} "
                                            "(соединение прервалось; в облаке файл не найден — будет повтор при следующей синхронизации)"
                                        )
                                    elif err_note:
                                        stats["errors"].append(f"Upload failed: {path} ({err_note[:400]})")
                                    else:
                                        stats["errors"].append(f"Upload failed: {path}")
                                    stats["failed_uploads"].append(path)
                                    sync_log(
                                        "Upload failed",
                                        component="NET",
                                        op="upload",
                                        trace_id=trace_id,
                                        result="fail",
                                        path=path,
                                        duration_ms=duration_ms,
                                        reason="api_returned_false",
                                        extra=err_note[:200] if err_note else "",
                                    )
                    except Exception as e:
                        stats["errors"].append(f"Upload error {path}: {e}")
                        stats["failed_uploads"].append(path)
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
                        stats["failed_deletes_local"].append(path)
                        sync_log("Delete local failed", component="FS", op="delete", trace_id=trace_id, result="fail", path=path, duration_ms=int((time.time() - start_time) * 1000), reason=str(e))
            
            elif action == "delete_cloud":
                if dry_run or is_dry_run():
                    sync_log("[DRY RUN] Delete cloud file", component="NET", op="delete", trace_id=trace_id, result="skip", path=path, reason="dry_run")
                else:
                    cloud_id = op.get("cloud_id")
                    is_folder = str(op.get("is_folder", "")).lower() == "true" or bool(op.get("is_folder") is True)
                    if cloud_id:
                        try:
                            if is_folder:
                                api.delete_folder(cloud_id)
                            else:
                                api.delete_document(cloud_id)
                            duration_ms = int((time.time() - start_time) * 1000)
                            stats["deleted_cloud"] += 1
                            sync_log("Deleted cloud item", component="NET", op="delete", trace_id=trace_id, result="ok", path=path, duration_ms=duration_ms, extra="folder" if is_folder else "file")
                        except Exception as e:
                            stats["errors"].append(f"Delete cloud error {path}: {e}")
                            stats["failed_deletes_cloud"].append(path)
                            sync_log("Delete cloud failed", component="NET", op="delete", trace_id=trace_id, result="fail", path=path, duration_ms=int((time.time() - start_time) * 1000), reason=str(e), extra="folder" if is_folder else "file")
        
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
    is_initial_sync: bool = False,
    *,
    allow_mass_delete: bool = False,
    sync_mode: str = "auto",
    ui_hooks: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Main sync function."""
    import time
    
    trace_id = new_trace_id()
    effective_dry_run = dry_run or is_dry_run()
    
    sync_log(
        "Sync started",
        component="SYNC",
        op="start",
        trace_id=trace_id,
        result="ok",
        extra=(
            f"project_id={project_id} folder_id={folder_id} local_root='{local_root}' "
            f"dry_run={effective_dry_run} is_initial_sync={is_initial_sync} "
            f"sync_mode={sync_mode} allow_mass_delete={bool(allow_mass_delete)}"
        ),
    )
    
    if is_initial_sync:
        sync_log("Initial sync mode: old_state will be ignored", component="SYNC", op="state", trace_id=trace_id, result="ok")
    
    sync_log("Loading previous state", component="DB", op="load", trace_id=trace_id, result="ok")
    old_state, initial_sync_done = load_sync_state(project_id, folder_id)
    if is_initial_sync:
        old_state = {}
        sync_log("Initial sync: old_state cleared", component="DB", op="load", trace_id=trace_id, result="ok", extra=f"was={len(old_state)}")
    elif initial_sync_done:
        sync_log("Continuing sync: previous state loaded", component="DB", op="load", trace_id=trace_id, result="ok", extra=f"items={len(old_state)}")
    else:
        sync_log("Previous state loaded", component="DB", op="load", trace_id=trace_id, result="ok", extra=f"items={len(old_state)}")

    if not os.path.exists(local_root) or not os.path.isdir(local_root):
        reason = "local_root_not_found" if not os.path.exists(local_root) else "local_root_not_directory"
        sync_log(
            "SYNC SAFETY ABORT: local root unavailable; preserving cloud",
            component="SYNC",
            op="safety_abort",
            trace_id=trace_id,
            result="fail",
            path=local_root,
            reason=reason,
        )
        abort_errors = [f"Safety abort: {reason}: {local_root}"]
        abort_stats = {
            "downloaded": 0,
            "uploaded": 0,
            "deleted_local": 0,
            "deleted_cloud": 0,
            "errors": abort_errors,
            "failed_uploads": [],
            "failed_downloads": [],
            "failed_deletes_local": [],
            "failed_deletes_cloud": [],
        }
        return {
            "success": False,
            "blocked_by_guard": False,
            "guard": None,
            "safety_abort": True,
            "reason": reason,
            "stats": abort_stats,
            "errors": abort_errors,
        }
    
    sync_log("Scanning local filesystem", component="SYNC", op="scan_local", trace_id=trace_id, result="ok")
    local_files = get_local_files(local_root, trace_id=trace_id)
    local_folders = sum(1 for f in local_files.values() if f.get("is_folder"))
    local_regular = len(local_files) - local_folders
    sync_log("Local scan complete", component="SYNC", op="scan_local", trace_id=trace_id, result="ok", extra=f"files={local_regular} folders={local_folders} total={len(local_files)}")
    
    sync_log("Scanning cloud", component="SYNC", op="scan_cloud", trace_id=trace_id, result="ok")
    cloud_files = get_cloud_files(api, project_id, folder_id, trace_id=trace_id, force=True)
    cloud_folders = sum(1 for f in cloud_files.values() if f.get("is_folder"))
    cloud_regular = len(cloud_files) - cloud_folders
    sync_log("Cloud scan complete", component="SYNC", op="scan_cloud", trace_id=trace_id, result="ok", extra=f"files={cloud_regular} folders={cloud_folders} total={len(cloud_files)}")
    
    sync_log("Planning sync operations", component="SYNC", op="plan", trace_id=trace_id, result="ok")
    operations = compare_and_plan_sync(old_state, local_files, cloud_files, is_initial_sync=is_initial_sync, trace_id=trace_id)

    guard_snapshot = {}
    try:
        all_guard_paths = set(old_state.keys()) | set(local_files.keys()) | set(cloud_files.keys())
        for guard_path in all_guard_paths:
            guard_snapshot[guard_path] = {
                "local": {"exists": guard_path in local_files},
                "cloud": {"exists": guard_path in cloud_files},
            }
    except Exception:
        guard_snapshot = {}

    guard = check_mass_delete_guard(
        operations,
        guard_snapshot,
        allow_mass_delete=bool(allow_mass_delete),
        sync_mode=str(sync_mode or "auto"),
        trace_id=trace_id,
    )
    if not guard.get("ok"):
        guard_reason = str(guard.get("reason") or "mass_delete_guard")
        sync_log(
            "SYNC SAFETY ABORT: mass delete guard triggered",
            component="SYNC",
            op="safety_abort",
            trace_id=trace_id,
            result="fail",
            reason=guard_reason,
            extra=f"operations={len(operations)} delete_count={guard.get('delete_count')} total_files={guard.get('total_files')} delete_percent={guard.get('delete_percent')}",
        )
        abort_errors = [f"Safety abort: {guard_reason}"]
        abort_stats = {
            "downloaded": 0,
            "uploaded": 0,
            "deleted_local": 0,
            "deleted_cloud": 0,
            "errors": abort_errors,
            "failed_uploads": [],
            "failed_downloads": [],
            "failed_deletes_local": [],
            "failed_deletes_cloud": [],
        }
        return {
            "success": False,
            "blocked_by_guard": bool(guard.get("blocked_by_guard")),
            "guard": guard,
            "stats": abort_stats,
            "errors": abort_errors,
        }
    
    sync_log("Executing operations", component="SYNC", op="execute", trace_id=trace_id, result="ok", extra=f"dry_run={effective_dry_run}")
    transfer_hooks = _compose_ui_transfer_hooks(ui_hooks, folder_id)
    stats = execute_sync_operations(
        api,
        project_id,
        folder_id,
        local_root,
        operations,
        effective_dry_run,
        trace_id=trace_id,
        ui_transfer_hooks=transfer_hooks,
    )
    
    sync_log("Saving new state", component="DB", op="save", trace_id=trace_id, result="ok")
    if not effective_dry_run:
        failed_uploads = set(stats.get("failed_uploads", []))
        failed_downloads = set(stats.get("failed_downloads", []))
        failed_deletes_local = set(stats.get("failed_deletes_local", []))
        failed_deletes_cloud = set(stats.get("failed_deletes_cloud", []))
        
        if failed_uploads:
            sync_log("Marking failed uploads for retry", component="DB", op="save", trace_id=trace_id, result="ok", extra=f"paths={list(failed_uploads)[:10]}")
        if failed_downloads:
            sync_log("Excluding failed downloads from state", component="DB", op="save", trace_id=trace_id, result="ok", extra=f"paths={list(failed_downloads)[:10]}")
        
        had_operations = len(operations) > 0
        if had_operations:
            sync_log("Rescanning after sync operations for accurate state", component="SYNC", op="rescan", trace_id=trace_id, result="ok")
            local_files = get_local_files(local_root, trace_id=trace_id)
            cloud_files = get_cloud_files(api, project_id, folder_id, trace_id=trace_id, force=True)
            local_folders = sum(1 for f in local_files.values() if f.get("is_folder"))
            local_regular = len(local_files) - local_folders
            cloud_folders = sum(1 for f in cloud_files.values() if f.get("is_folder"))
            cloud_regular = len(cloud_files) - cloud_folders
            sync_log("Post-sync scan complete", component="SYNC", op="rescan", trace_id=trace_id, result="ok", extra=f"local_files={local_regular} local_folders={local_folders} cloud_files={cloud_regular} cloud_folders={cloud_folders}")
        
        new_state = {}
        for path, info in local_files.items():
            if path in failed_uploads:
                new_state[path] = {
                    "lastModified": info["lastModified"],
                    "is_folder": info.get("is_folder", False),
                    "upload_failed": True
                }
                continue
            if path in failed_downloads:
                continue
            if path in failed_deletes_local:
                old_entry = old_state.get(path, {})
                entry = {
                    "lastModified": info.get("lastModified", old_entry.get("lastModified", 0)),
                    "is_folder": info.get("is_folder", old_entry.get("is_folder", False)),
                    "delete_failed": True
                }
                if old_entry.get("id"):
                    entry["id"] = old_entry["id"]
                new_state[path] = entry
                continue
            new_state[path] = {
                "lastModified": info["lastModified"],
                "is_folder": info.get("is_folder", False)
            }
        for path, info in cloud_files.items():
            if path in failed_uploads:
                continue
            if path in failed_downloads:
                continue
            if path in failed_deletes_cloud:
                if path not in new_state:
                    new_state[path] = {
                        "createdAt": info.get("createdAt") or info["createTime"],
                        "modifTime": info["modifTime"],
                        "updatedAt": info.get("updatedAt") or info["modifTime"],
                        "lastModified": info["lastModified"],
                        "is_folder": info.get("is_folder", False),
                        "id": info.get("id", ""),
                        "createdBy": info.get("createdBy") or "",
                        "modifiedBy": info.get("modifiedBy") or "",
                        "version": info.get("version") or 0,
                        "delete_failed": True
                    }
                continue
            if path in new_state:
                new_state[path]["createdAt"] = info.get("createdAt") or info["createTime"]
                new_state[path]["modifTime"] = info["modifTime"]
                new_state[path]["updatedAt"] = info.get("updatedAt") or info["modifTime"]
                if info["lastModified"] > new_state[path]["lastModified"]:
                    new_state[path]["lastModified"] = info["lastModified"]
                new_state[path]["id"] = info["id"]
                new_state[path]["createdBy"] = info.get("createdBy") or ""
                new_state[path]["modifiedBy"] = info.get("modifiedBy") or ""
                new_state[path]["version"] = info.get("version") or 0
                if info.get("is_folder"):
                    new_state[path]["is_folder"] = True
            else:
                new_state[path] = {
                    "createdAt": info.get("createdAt") or info["createTime"],
                    "modifTime": info["modifTime"],
                    "updatedAt": info.get("updatedAt") or info["modifTime"],
                    "lastModified": info["lastModified"],
                    "is_folder": info.get("is_folder", False),
                    "id": info.get("id", ""),
                    "createdBy": info.get("createdBy") or "",
                    "modifiedBy": info.get("modifiedBy") or "",
                    "version": info.get("version") or 0
                }
        saved_folders = sum(1 for f in new_state.values() if f.get("is_folder"))
        saved_regular = len(new_state) - saved_folders
        save_sync_state(new_state, project_id, folder_id)
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
        "errors": stats["errors"],
        "blocked_by_guard": False,
        "guard": guard,
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


def check_mass_delete_guard(
    operations: list[Dict],
    snapshot: Dict,
    threshold_percent: float = 20.0,
    min_files: int = 10,
    *,
    allow_mass_delete: bool = False,
    sync_mode: str = "auto",
    trace_id: str = "",
    sample_limit: int = 8,
) -> Dict[str, Any]:
    """Mass-delete protection.

    Returns a structured result dict with fields used by UI and callers.
    Bypassed when sync_mode is ``auto`` or allow_mass_delete=True for this run.
    """
    try:
        ops_total = len(operations or [])
        actions_by_type: Dict[str, int] = {}
        delete_cloud_paths: list[str] = []
        delete_local_paths: list[str] = []
        for op in operations or []:
            try:
                act = str(op.get("action") or "")
            except Exception:
                act = ""
            if not act:
                continue
            actions_by_type[act] = actions_by_type.get(act, 0) + 1
            if act == "delete_cloud":
                try:
                    delete_cloud_paths.append(str(op.get("path") or ""))
                except Exception:
                    pass
            elif act == "delete_local":
                try:
                    delete_local_paths.append(str(op.get("path") or ""))
                except Exception:
                    pass

        total_files = 0
        try:
            total_files = len([
                p for p in (snapshot or {}).keys()
                if (snapshot[p].get("local", {}).get("exists") or snapshot[p].get("cloud", {}).get("exists"))
            ])
        except Exception:
            total_files = 0

        delete_count = int(actions_by_type.get("delete_local", 0) + actions_by_type.get("delete_cloud", 0))
        delete_percent = (delete_count / max(1, total_files)) * 100.0

        # Prefer showing cloud-deletion sample paths because that's the scary side-effect.
        sample_paths: list[str] = []
        try:
            sample_paths = [p for p in (delete_cloud_paths or delete_local_paths) if p][:sample_limit]
        except Exception:
            sample_paths = []

        sync_log(
            "GUARD: total_files={} delete_count={} min_files={} threshold={}%% allow_mass_delete={} sync_mode={} ops_total={} actions_by_type={}",
            total_files,
            delete_count,
            min_files,
            threshold_percent,
            bool(allow_mass_delete),
            sync_mode,
            ops_total,
            actions_by_type,
            component="SYNC",
            op="guard",
            trace_id=trace_id,
            result="ok",
        )

        # Small sets: allow deletions.
        if total_files < int(min_files or 0):
            return {
                "ok": True,
                "blocked_by_guard": False,
                "reason": "below_min_files",
                "delete_count": delete_count,
                "total_files": total_files,
                "delete_percent": delete_percent,
                "sample_paths": sample_paths,
                "actions_by_type": actions_by_type,
                "threshold_percent": float(threshold_percent),
                "min_files": int(min_files),
            }
        if delete_count <= 0:
            return {
                "ok": True,
                "blocked_by_guard": False,
                "reason": "no_deletions",
                "delete_count": 0,
                "total_files": total_files,
                "delete_percent": 0.0,
                "sample_paths": [],
                "actions_by_type": actions_by_type,
                "threshold_percent": float(threshold_percent),
                "min_files": int(min_files),
            }

        over = delete_percent > float(threshold_percent)
        if (
            over
            and not allow_mass_delete
            and str(sync_mode or "auto").strip().lower() == "auto"
            and delete_count > 0
        ):
            sync_log(
                "GUARD_BYPASS: auto sync allows mass delete",
                component="SYNC",
                op="guard",
                trace_id=trace_id,
                result="bypass",
                extra=(
                    f"delete_count={delete_count} total_files={total_files} "
                    f"delete_percent={delete_percent:.1f}% actions_by_type={actions_by_type} "
                    f"sample_paths={sample_paths}"
                ),
            )
            return {
                "ok": True,
                "blocked_by_guard": False,
                "reason": "auto_sync_delete_allowed",
                "delete_count": delete_count,
                "total_files": total_files,
                "delete_percent": delete_percent,
                "sample_paths": sample_paths,
                "actions_by_type": actions_by_type,
                "threshold_percent": float(threshold_percent),
                "min_files": int(min_files),
            }

        if over and not allow_mass_delete:
            reason = f"mass_delete_detected_{delete_count}_of_{total_files}_files_{delete_percent:.1f}%"
            sync_log(
                "GUARD_BLOCK: {}",
                reason,
                component="SYNC",
                op="guard",
                trace_id=trace_id,
                result="block",
                extra=f"sample_paths={sample_paths}",
            )
            return {
                "ok": False,
                "blocked_by_guard": True,
                "reason": reason,
                "delete_count": delete_count,
                "total_files": total_files,
                "delete_percent": delete_percent,
                "sample_paths": sample_paths,
                "actions_by_type": actions_by_type,
                "threshold_percent": float(threshold_percent),
                "min_files": int(min_files),
            }

        if over and allow_mass_delete:
            sync_log(
                "GUARD_BYPASS: allowing mass delete for this run",
                component="SYNC",
                op="guard",
                trace_id=trace_id,
                result="bypass",
                extra=f"delete_count={delete_count} total_files={total_files} delete_percent={delete_percent:.1f}% sync_mode={sync_mode}",
            )

        return {
            "ok": True,
            "blocked_by_guard": False,
            "reason": "ok" if not over else "bypass_allowed",
            "delete_count": delete_count,
            "total_files": total_files,
            "delete_percent": delete_percent,
            "sample_paths": sample_paths,
            "actions_by_type": actions_by_type,
            "threshold_percent": float(threshold_percent),
            "min_files": int(min_files),
        }
    except Exception as e:
        # Fail closed: if guard itself errors, block deletions.
        sync_log(
            "GUARD_ERROR: {}",
            str(e),
            component="SYNC",
            op="guard",
            trace_id=trace_id,
            result="fail",
        )
        return {
            "ok": False,
            "blocked_by_guard": True,
            "reason": f"guard_error:{e}",
            "delete_count": 0,
            "total_files": 0,
            "delete_percent": 0.0,
            "sample_paths": [],
            "actions_by_type": {},
            "threshold_percent": float(threshold_percent),
            "min_files": int(min_files),
        }


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
