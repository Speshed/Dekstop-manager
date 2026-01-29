# -*- coding: utf-8 -*-
"""Larix Nexus Desktop - Main entry point."""

import sys
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QIcon

from larix_nexus.ui import MainWindow, ScrollbarProxyStyle
from larix_nexus.api import APIClient
from larix_nexus.sync import sync_files_new
from larix_nexus.utils import (
    rsrc_path,
    ICON_PATH,
    program_dir,
    load_settings,
    _cleanup_sync_log_file,
    apply_light_theme,
    apply_dark_theme,
    load_saved_theme,
    install_russian_ui,
    install_warning_icon_for_messageboxes,
    enable_msgbox_autosize,
    _patch_messagebox_texts_fixed,
    patch_qfiledialog_initial_dir,
    patch_dir_picker_binding,
    patch_combobox_popup_border,
    patch_messagebox_texts,
)
from larix_nexus.utils.app_logging import start_logging, stop_logging
from larix_nexus.utils.crash_diagnostics import install_crash_diagnostics
from larix_nexus.notifications import init_notifications_db
from larix_nexus.constants import (
    BASE_URL,
    APP_TITLE,
    SETTINGS_ORG,
    SETTINGS_APP,
    SETTINGS_THEME_KEY,
    THEME_LIGHT,
    THEME_DARK,
)


def main():
    """Main entry point for Larix Nexus Desktop application."""
    
    # ========================================================================
    # LOGGING REDIRECTION TO FILE
    # ========================================================================
    # Redirect all logging (including print statements) to file
    start_logging(log_to_file=True, keep_console=False)

    # Capture native/Qt crashes and unhandled exceptions.
    try:
        install_crash_diagnostics(app=None)
    except Exception:
        pass
    
    # ========================================================================
    # COMMAND LINE SUPPORT FOR TESTS AND DRY-RUN
    # ========================================================================
    import argparse
    
    parser = argparse.ArgumentParser(description="Larix Nexus Desktop")
    parser.add_argument("--dry-run", metavar="FOLDER_ID",
                       help="Run dry-run sync for specified folder ID and exit")
    parser.add_argument("--project-id", type=int, default=None,
                       help="Project ID for dry-run (required with --dry-run)")
    parser.add_argument("--local-root", type=str, default=None,
                       help="Local root path for dry-run (required with --dry-run)")
    
    args = parser.parse_args()
    
    # Run dry-run if requested
    if args.dry_run:
        if not args.project_id or not args.local_root:
            print("ERROR: --dry-run requires --project-id and --local-root")
            sys.exit(1)
        
        print("=" * 70)
        print(f"RUNNING DRY-RUN SYNC")
        print(f"  Project ID: {args.project_id}")
        print(f"  Folder ID:  {args.dry_run}")
        print(f"  Local Root: {args.local_root}")
        print("=" * 70)
        
        # Initialize minimal API client (needs authentication)
        # For dry-run, user should have valid session or provide credentials
        from PySide6.QtCore import QSettings
        
        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        api = APIClient(BASE_URL)
        api._load_auth()
        
        if not api.token:
            print("\nERROR: No valid authentication token found.")
            print("Please login through GUI first, or set LARIX_TOKEN environment variable.")
            sys.exit(1)
        
        try:
            folder_id = int(args.dry_run)
            # Use integrated sync module
            result = sync_files_new(api, args.project_id, folder_id, 
                                args.local_root, dry_run=True)
            
            print("\n" + "=" * 70)
            print("DRY-RUN RESULTS:")
            print(f"  Success: {result['success']}")
            print(f"  Stats: {result['stats']}")
            
            if result.get("errors"):
                print(f"  Errors: {result['errors']}")
            
            print("=" * 70)
            
            sys.exit(0 if result["success"] else 1)
            
        except Exception as e:
            print(f"\nERROR: Dry-run failed: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
    
    # ========================================================================
    # NORMAL GUI APPLICATION STARTUP
    # ========================================================================

    # On Windows, ensure COM is initialized on the GUI thread.
    # Native file dialogs use COM (IFileDialog) and can hard-crash if the
    # apartment isn't initialized correctly.
    try:
        if sys.platform == "win32":
            import ctypes
            COINIT_APARTMENTTHREADED = 2
            try:
                ctypes.windll.ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
            except Exception:
                pass
    except Exception:
        pass
    
    # Initialize notifications database
    init_notifications_db()
    
    app = QApplication(sys.argv)
    try:
        install_crash_diagnostics(app=app)
    except Exception:
        pass
    try:
        QCoreApplication.setOrganizationName(SETTINGS_ORG)
        QCoreApplication.setApplicationName(APP_TITLE)
    except Exception:
        pass
    base_style = app.style()
    app.setStyle(ScrollbarProxyStyle(base_style))
     # общий значок приложения
    icon_file = ICON_PATH or rsrc_path("icon", "logo_transparent_multi.ico")
    if icon_file and os.path.exists(icon_file):
        app.setWindowIcon(QIcon(icon_file))
    install_russian_ui(app)
    
    # Загружаем сохраненную тему ПЕРЕД применением
    try:
        _saved_theme = load_saved_theme()
    except Exception:
        _saved_theme = THEME_LIGHT
    # Применяем нужную тему сразу
    if _saved_theme == THEME_DARK:
        apply_dark_theme(app)
    else:
        apply_light_theme(app)
    install_warning_icon_for_messageboxes()
    enable_msgbox_autosize(app)
    patch_qfiledialog_initial_dir()
    patch_dir_picker_binding()
    patch_combobox_popup_border()
    # Use a safer version of messagebox text normalizer to avoid corrupted strings
    try:
        _patch_messagebox_texts_fixed()
    except Exception:
        try:
            patch_messagebox_texts()
        except Exception:
            pass
    # Ensure sync debug log is flushed when app exits
    try:
        app.aboutToQuit.connect(_cleanup_sync_log_file)
    except Exception:
        pass
 
    w = MainWindow()
    # Sync UI toggle and visuals to saved theme (без повторного переключения)
    try:
        dark = (_saved_theme == THEME_DARK)
        if hasattr(w, "theme_toggle"):
            try:
                w.theme_toggle.blockSignals(True)
                w.theme_toggle.setChecked(dark)
                w.theme_toggle.snap_to_state()
            finally:
                w.theme_toggle.blockSignals(False)
        # Устанавливаем текущую тему без вызова _on_theme_toggled (он уже применен)
        try:
            w._current_theme = THEME_DARK if dark else THEME_LIGHT
            w._apply_icon_theme(w._current_theme)
            # Устанавливаем тему title bar и устанавливаем hover фильтры для темной темы
            if dark:
                try:
                    w._install_hover_black_icons()
                except Exception:
                    pass
                try:
                    from larix_nexus.utils.helpers import _set_window_theme_dark
                    _set_window_theme_dark(w, dark=True)
                except Exception:
                    pass
        except Exception:
            pass
    except Exception:
        pass
    w.show()
    
    # Try auto-login with saved credentials
    print("[AUTH DEBUG] main: checking auto-login...")
    auto_login_success = False
    try:
        settings = load_settings()
        last_user = settings.get("last_username")
        remember_me = settings.get("remember_me", True)
 
        print(f"[AUTH DEBUG] main: settings - last_username='{last_user}', remember_me={remember_me}")
 
        # Only try auto-login if remember_me is True
        if last_user and remember_me:
            print(f"[AUTH DEBUG] main: attempting auto-login for '{last_user}'...")
            # Try to load and refresh tokens (includes password fallback)
            if w.api._load_auth():
                # Verify token is valid
                print("[AUTH DEBUG] main: token loaded, verifying with API...")
                try:
                    projects = w.api.list_projects()
                    if projects is not None:  # None indicates network error, empty list is OK
                        print(f"[AUTH DEBUG] main: API verification SUCCESS - got {len(projects)} projects")
                        auto_login_success = True
                    else:
                        print("[AUTH DEBUG] main: API verification FAILED - got None")
                except Exception as e:
                    print(f"[AUTH DEBUG] main: API verification ERROR - {e}")
            else:
                print("[AUTH DEBUG] main: _load_auth returned False")
        elif last_user and not remember_me:
            print("[AUTH DEBUG] main: skipping auto-login because remember_me=False")
        else:
            print("[AUTH DEBUG] main: no last_username, skipping auto-login")
    except Exception as e:
        print(f"[AUTH DEBUG] main: auto-login exception - {e}")
    
    # If auto-login failed or not configured, prompt for login
    if not auto_login_success and not w.api.token:
        print("[AUTH DEBUG] main: showing login dialog")
        w.open_login_dialog()
    else:
        print("[AUTH DEBUG] main: auto-login successful, calling on_logged_in()")
        try:
             w.on_logged_in()
        except Exception:
            pass
    
    # Flush logs before exit
    try:
        _cleanup_sync_log_file()
    except Exception:
        pass
    
    # Stop logging redirection
    try:
        stop_logging()
    except Exception:
        pass
    
    sys.exit(app.exec())
 

if __name__ == '__main__':
    main()
