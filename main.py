# -*- coding: utf-8 -*-
"""Larix Nexus Desktop - Main entry point."""

import sys
import os

# ============================================================================
# IMPORTANT: Apply SSL patching BEFORE any imports of requests or urllib3
# This prevents access violation crashes on Windows + Python 3.13 in Qt threads
# ============================================================================
from larix_nexus.utils.ssl_patch import *  # noqa: F401,F403

def main():
    """Main entry point for Larix Nexus Desktop application."""
    # Cleanup old logs BEFORE any heavy imports (Qt can crash during import).
    reset_result = None
    try:
        from larix_nexus.utils.app_logging import reset_log_files

        reset_result = reset_log_files()
    except Exception:
        reset_result = None

    # Redirect all logging (including print statements) to file.
    from larix_nexus.utils.app_logging import start_logging, stop_logging

    start_logging(log_to_file=True, keep_console=False)

    # Capture native/Qt crashes and unhandled exceptions (faulthandler, hooks).
    install_cd = None
    try:
        from larix_nexus.utils.crash_diagnostics import install_crash_diagnostics as _install_crash_diagnostics

        install_cd = _install_crash_diagnostics
        install_cd(app=None)
    except Exception:
        install_cd = None

    # Additional per-line crash-safe trace (separate file).
    try:
        from larix_nexus.utils.ui_trace import trace as ui_trace

        ui_trace("main: logging started")
    except Exception:
        ui_trace = None

    import logging
    log = logging.getLogger("app")
    try:
        log.info("Larix Nexus starting (pid=%s, platform=%s)", os.getpid(), sys.platform)
    except Exception:
        pass
    if reset_result is not None:
        try:
            log.info(
                "log reset: skipped=%s deleted=%s failed=%s dir=%s",
                reset_result.get("skipped"),
                len(reset_result.get("deleted") or []),
                len(reset_result.get("failed") or []),
                reset_result.get("log_dir"),
            )
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

        from larix_nexus.constants import SETTINGS_ORG, SETTINGS_APP, BASE_URL
        from larix_nexus.api import APIClient

        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        api = APIClient(BASE_URL)
        api._load_auth()
        
        if not api.token:
            print("\nERROR: No valid authentication token found.")
            print("Please login through GUI first, or set LARIX_TOKEN environment variable.")
            sys.exit(1)
        
        try:
            folder_id = int(args.dry_run)
            from larix_nexus.sync import sync_files_new

            result = sync_files_new(api, args.project_id, folder_id, args.local_root, dry_run=True)
            
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

    # Heavy imports after logging setup.
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtGui import QIcon

    from larix_nexus.ui import MainWindow, ScrollbarProxyStyle
    from larix_nexus.utils import (
        rsrc_path,
        ICON_PATH,
        load_settings,
        _cleanup_sync_log_file,
        apply_light_theme,
        apply_dark_theme,
        load_saved_theme,
        install_warning_icon_for_messageboxes,
        enable_msgbox_autosize,
        _patch_messagebox_texts_fixed,
        patch_qfiledialog_initial_dir,
        patch_dir_picker_binding,
        patch_combobox_popup_border,
        patch_messagebox_texts,
    )
    from larix_nexus.utils.i18n import initialize_i18n
    from larix_nexus.notifications import init_notifications_db
    from larix_nexus.constants import (
        APP_TITLE,
        SETTINGS_ORG,
        SETTINGS_APP,
        THEME_LIGHT,
        THEME_DARK,
    )

    # On Windows, ensure COM is initialized on the GUI thread.
    # Native file dialogs use COM (IFileDialog) and can hard-crash if the
    # apartment isn't initialized correctly.
    try:
        if sys.platform == "win32":
            import ctypes
            COINIT_APARTMENTTHREADED = 2
            try:
                ctypes.windll.ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
                if ui_trace:
                    ui_trace("main: CoInitializeEx OK")
            except Exception:
                pass
    except Exception:
        pass
    
    # Initialize notifications database
    init_notifications_db()
    
    if ui_trace:
        ui_trace("main: creating QApplication")
    app = QApplication(sys.argv)
    if ui_trace:
        ui_trace("main: QApplication created")
    try:
        if install_cd is not None:
            install_cd(app=app)
    except Exception:
        pass
    try:
        app.setQuitOnLastWindowClosed(False)
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
    initialize_i18n(app)
    
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
 
    if ui_trace:
        ui_trace("main: creating MainWindow")
    w = MainWindow()
    if ui_trace:
        ui_trace("main: MainWindow created")
    # Sync UI toggle and visuals to saved theme (без повторного переключения)
    try:
        dark = (_saved_theme == THEME_DARK)
        if hasattr(w, "theme_toggle"):
            try:
                w.theme_toggle.blockSignals(True)
                w.theme_toggle.setChecked(dark, animate=False)
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
    if ui_trace:
        ui_trace("main: showing MainWindow")
    w.show()
    
    # Try auto-login with saved credentials
    log.debug("auth: checking auto-login")
    auto_login_success = False
    try:
        settings = load_settings()
        last_user = settings.get("last_username")
        remember_me = settings.get("remember_me", True)

        log.info("auth: settings last_username=%s remember_me=%s", bool(last_user), bool(remember_me))
 
        # Only try auto-login if remember_me is True
        if last_user and remember_me:
            log.info("auth: attempting auto-login")
            # Try to load and refresh tokens (includes password fallback)
            if w.api._load_auth():
                # Verify token is valid
                log.info("auth: token loaded, verifying via API")
                try:
                    projects = w.api.list_projects()
                    if projects is not None:  # None indicates network error, empty list is OK
                        log.info("auth: API verification OK projects=%s", len(projects))
                        auto_login_success = True
                    else:
                        log.warning("auth: API verification returned None")
                except Exception as e:
                    log.exception("auth: API verification error: %s", e)
            else:
                log.info("auth: _load_auth returned False")
        elif last_user and not remember_me:
            log.info("auth: skipping auto-login (remember_me=False)")
        else:
            log.info("auth: no last_username, skipping auto-login")
    except Exception as e:
        log.exception("auth: auto-login exception: %s", e)
    
    # If auto-login failed or not configured, prompt for login
    if not auto_login_success and not w.api.token:
        log.info("auth: showing login dialog")
        if ui_trace:
            ui_trace("main: opening login dialog")
        w.open_login_dialog()
    else:
        log.info("auth: calling on_logged_in()")
        if ui_trace:
            ui_trace("main: calling on_logged_in")
        try:
             w.on_logged_in()
        except Exception:
            pass

    exit_code = 0
    try:
        if ui_trace:
            ui_trace("main: entering Qt event loop")
        exit_code = app.exec()
        return exit_code
    finally:
        # Flush/close logs on shutdown.
        try:
            _cleanup_sync_log_file()
        except Exception:
            pass
        try:
            stop_logging()
        except Exception:
            pass
        try:
            if ui_trace:
                ui_trace("main: exiting (code={})", exit_code)
        except Exception:
            pass


if __name__ == '__main__':
    try:
        code = main()
    except SystemExit:
        raise
    except Exception:
        # Best-effort fallback: ensure we still exit non-zero on unexpected failure.
        code = 1
    sys.exit(0 if code is None else int(code))
