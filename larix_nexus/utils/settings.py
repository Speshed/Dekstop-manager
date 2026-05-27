# -*- coding: utf-8 -*-
"""Settings management for Larix Nexus Desktop."""

import os
import logging
from typing import Callable

from PySide6.QtCore import QSettings

from .atomic_json import atomic_read_json, atomic_write_json, atomic_update_json
from .paths import settings_path as _new_settings_path, app_data_dir

# ============================================================================
# JSON SETTINGS STORAGE
# New path:  %APPDATA%\LarixNexus\config\settings.json
# Legacy:    %APPDATA%\LarixNexus\settings.json
# ============================================================================

def _settings_dir() -> str:
    """Get settings directory path."""
    # Kept for compatibility with older callers.
    return app_data_dir()

def _settings_path() -> str:
    """Get path to settings JSON file (new location)."""
    return _new_settings_path()


def _legacy_settings_path() -> str:
    return os.path.join(_settings_dir(), "settings.json")

def load_settings() -> dict:
    """Load global settings from JSON.
    
    Returns:
        Settings dict with defaults
    """
    path = _settings_path()
    default = {
        "version": 1,
        "theme": "light",
        "remember_me": False,
        "last_username": "",
        "auto_login": False,
        "ui": {
            "window_geometry": None,
            "splitter_state": None,
            "column_widths": {}
        },
        "sync": {
            "auto_sync_interval": 300,  # 5 minutes (in seconds)
            "notification_refresh_interval": 300,  # 5 minutes (in seconds)
            "conflict_resolution": "newer",  # "newer", "local", "cloud"
            "mass_delete_threshold": 20  # percent
        }
    }
    data = atomic_read_json(path, default=None)
    if data is not None:
        return data

    legacy = _legacy_settings_path()
    if legacy != path and os.path.exists(legacy):
        try:
            logging.getLogger("app").warning("settings: legacy fallback read from %s", legacy)
        except Exception:
            pass
        return atomic_read_json(legacy, default=default)

    return default

def save_settings(settings: dict) -> bool:
    """Save global settings to JSON."""
    path = _settings_path()
    return atomic_write_json(path, settings, ensure_dir=True)

def update_settings(updater: Callable[[dict], dict]) -> bool:
    """Atomically update settings using updater function."""
    path = _settings_path()
    default = {
        "version": 1,
        "theme": "light",
        "remember_me": False,
        "last_username": "",
        "auto_login": False,
        "ui": {},
        "sync": {}
    }
    return atomic_update_json(path, updater, default=default)

# Local constants (to avoid circular dependency with constants.py)
SETTINGS_ORG = "Larix"
SETTINGS_APP = "NexusDesktop"

def _app_settings() -> QSettings:
    """Legacy QSettings accessor. Use load_settings()/save_settings() for new code."""
    return QSettings(SETTINGS_ORG, SETTINGS_APP)
