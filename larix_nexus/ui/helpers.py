# -*- coding: utf-8 -*-
"""Helper functions for UI operations in Larix Nexus."""

import os
import sys
import re
import subprocess
import ctypes
from typing import Dict

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFileDialog, QMessageBox

from ..utils.i18n import t


def normalize_size(item: dict) -> int:
    """Extract size from item dict."""
    for key in ("size", "fileSize", "sizeBytes", "length", "contentLength"):
        if key in item and item.get(key) not in (None, ""):
            try:
                return int(float(item.get(key)))
            except (ValueError, TypeError):
                try:
                    return int(item.get(key))
                except (ValueError, TypeError):
                    pass
    return 0


def open_in_os(path: str) -> bool:
    """Open file/folder in OS default application."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False


def _is_file(item) -> bool:
    """Check if item is a file."""
    if not isinstance(item, dict):
        return False
    t = str(item.get("type", "")).lower()
    is_file = t in ("file", "файл", "document")
    return is_file


def _is_folder(item) -> bool:
    """Check if item is a folder."""
    if not isinstance(item, dict):
        return False
    t = str(item.get("type", "")).lower()
    is_folder = t in ("folder", "dir", "directory", "папка")
    return is_folder


def _sanitize_filename(name: str) -> str:
    """Sanitize filename by removing/replacing invalid characters."""
    return re.sub(r"[\\/:*?\"<>|]+", "_", str(name or ""))


def get_title(node: dict) -> str:
    """Get title/name from node dict."""
    return (node or {}).get("name") or (node or {}).get("title") or t("common.no_name")


def _choose_directory(parent, title: str) -> str:
    """Helper to choose directory using file dialog."""
    start_dir = ""
    if sys.platform == "win32":
        # Use GUID to get system dialog on Windows
        try:
            import ctypes.wintypes as wintypes

            class GUID(ctypes.Structure):
                _fields_ = [
                    ("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", wintypes.BYTE * 8),
                ]

            # Folder selection GUID
            CLSID_Folder = GUID.from_bytes(
                b"\x0F\x44\xE5\x4C\xFA\xD5\x11\xB2\xF8\x00\xAA\x00\x6F\xD9"
            )

            # COM function to open folder dialog
            ole32 = ctypes.windll.ole32
            CoInitializeEx = ole32.CoInitializeEx
            CoTaskMemFree = ole32.CoTaskMemFree

            class COMMethods:
                def __init__(self):
                    self.vtbl = {}

                def _vtbl(obj, idx, restype, *argtypes):
                    def wrapper(*args):
                        return restype(obj, *args)

                    return wrapper

            # Simplified approach - fall back to native dialog
            pass
        except Exception:
            pass

    result = QFileDialog.getExistingDirectory(parent, title, start_dir)
    return result or ""
