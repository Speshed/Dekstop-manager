# -*- coding: utf-8 -*-
"""Settings management for Larix Nexus Desktop."""

import os
from typing import Callable

from PySide6.QtCore import QSettings

from .atomic_json import atomic_read_json, atomic_write_json, atomic_update_json

# ============================================================================
# JSON SETTINGS STORAGE (%APPDATA%\LarixNexus\settings.json)
# ============================================================================

def _settings_dir() -> str:
    """Get settings directory path."""
    app_data = os.getenv("APPDATA") or os.path.expanduser("~/.config")
    return os.path.join(app_data, "LarixNexus")

def _settings_path() -> str:
    """Get path to settings JSON file."""
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
    return atomic_read_json(path, default=default)

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
