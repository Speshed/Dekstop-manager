# -*- coding: utf-8 -*-
"""Utilities module for Larix Nexus Desktop."""

from .paths import rsrc_path, program_dir, ICON_PATH
from .logging import sync_log, sync_exc, _cleanup_sync_log_file, _sync_log_path
from .logs import (
    sync_log as sync_log_new,
    sync_exc as sync_exc_new,
    sync_info,
    sync_warn,
    sync_error,
    app_log,
    app_info,
    app_error,
    clear_logs,
    get_logs,
    finalize,
)
from .keyring import (
    save_credential,
    get_credential,
    delete_credential,
    clear_all_credentials,
    debug_credentials_status,
)
from .settings import load_settings, save_settings, update_settings
from .theme import (
    apply_light_theme,
    apply_dark_theme,
    _is_dark_mode,
    load_saved_theme,
    install_russian_ui,
    install_warning_icon_for_messageboxes,
    enable_msgbox_autosize,
    _patch_messagebox_texts_fixed,
    white_tinted_icon,
    load_white_icon,
    _cloud_tz_offset_minutes,
)
from .helpers import normalize_id, normalize_project_id, _set_window_theme_dark, compare_file_states
from .atomic_json import atomic_read_json, atomic_write_json, atomic_update_json
from .ui_patches import (
    patch_qfiledialog_initial_dir,
    patch_dir_picker_binding,
    patch_combobox_popup_border,
)
from .messagebox import patch_messagebox_texts

# Use new logging functions for sync (deprecated old logging module)
sync_log = sync_log_new
sync_exc = sync_exc_new

__all__ = [
    "rsrc_path",
    "program_dir",
    "ICON_PATH",
    "sync_log",
    "sync_exc",
    "_cleanup_sync_log_file",
    "_sync_log_path",
    "sync_info",
    "sync_warn",
    "sync_error",
    "app_log",
    "app_info",
    "app_error",
    "clear_logs",
    "get_logs",
    "finalize",
    "save_credential",
    "get_credential",
    "delete_credential",
    "clear_all_credentials",
    "debug_credentials_status",
    "load_settings",
    "save_settings",
    "update_settings",
    "apply_light_theme",
    "apply_dark_theme",
    "_is_dark_mode",
    "load_saved_theme",
    "install_russian_ui",
    "install_warning_icon_for_messageboxes",
    "enable_msgbox_autosize",
    "_patch_messagebox_texts_fixed",
    "white_tinted_icon",
    "load_white_icon",
    "_cloud_tz_offset_minutes",
    "normalize_id",
    "normalize_project_id",
    "_set_window_theme_dark",
    "compare_file_states",
    "atomic_read_json",
    "atomic_write_json",
    "atomic_update_json",
    "patch_qfiledialog_initial_dir",
    "patch_dir_picker_binding",
    "patch_combobox_popup_border",
    "patch_messagebox_texts",
]

