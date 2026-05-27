import os
import sys

def rsrc_path(*parts: str) -> str:
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        # This file lives in <root>/larix_nexus/utils/paths.py
        # We want resources relative to <root>/
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, *parts)
ICON_PATH = os.environ.get("LARIX_ICON_PATH", rsrc_path("icon", "logo_transparent_multi.ico"))

def program_dir() -> str:
    """Legacy alias for app_data_dir()."""
    return app_data_dir()


def app_data_dir() -> str:
    """Base app data directory.

    Windows: %APPDATA%\\LarixNexus
    Linux/Mac: ~/.config/larix_nexus
    """
    import platform

    if platform.system() == "Windows":
        app_data = os.getenv("APPDATA")
        if app_data:
            return os.path.join(app_data, "LarixNexus")
        return os.path.expanduser("~/.config/LarixNexus")

    return os.path.expanduser("~/.config/larix_nexus")


def config_dir() -> str:
    return os.path.join(app_data_dir(), "config")


def sync_dir() -> str:
    return os.path.join(app_data_dir(), "sync")


def sync_states_dir() -> str:
    return os.path.join(sync_dir(), "states")


def logs_dir() -> str:
    return os.path.join(app_data_dir(), "logs")


def logs_archive_dir() -> str:
    return os.path.join(logs_dir(), "archive")


def temp_dir() -> str:
    return os.path.join(app_data_dir(), "temp")


def settings_path() -> str:
    return os.path.join(config_dir(), "settings.json")


def notifications_path() -> str:
    return os.path.join(config_dir(), "notifications.json")


def sync_mappings_path() -> str:
    return os.path.join(sync_dir(), "mappings.json")


def sync_subscriptions_path() -> str:
    return os.path.join(sync_dir(), "subscriptions.json")


def readme_path() -> str:
    return os.path.join(app_data_dir(), "README.txt")


def sync_readme_path() -> str:
    return os.path.join(sync_dir(), "README.txt")


def ensure_appdata_layout() -> None:
    """Best-effort create app data folder layout and readmes.

    This is intentionally non-destructive: it only creates missing directories/files.
    """
    try:
        for d in (
            app_data_dir(),
            config_dir(),
            sync_dir(),
            sync_states_dir(),
            logs_dir(),
            logs_archive_dir(),
            temp_dir(),
        ):
            try:
                os.makedirs(d, exist_ok=True)
            except Exception:
                pass
    except Exception:
        return

    _readme = (
        "Larix Nexus Desktop - App Data Folder\n"
        "\n"
        "Folders and files:\n"
        "- config\\settings.json - application settings\n"
        "- config\\notifications.json - local notifications and subscriptions\n"
        "- sync\\mappings.json - cloud folder to local path mappings\n"
        "- sync\\subscriptions.json - active sync roots/subscriptions (if used)\n"
        "- sync\\states\\*.sync-state.json - per-folder sync snapshots\n"
        "- logs\\ - diagnostic logs (ui_trace.log, sync.log, etc.)\n"
        "- logs\\archive\\ - rotated/archived logs (if rotation is enabled)\n"
        "- temp\\ - temporary files\n"
        "\n"
        "Do not edit these files while the application is running.\n"
    )
    _sync_readme = (
        "Larix Nexus Desktop - Sync Data\n"
        "\n"
        "- mappings.json - cloud folder to local path mappings\n"
        "- subscriptions.json - active sync roots/subscriptions (if used)\n"
        "- states\\project_<project_id>__folder_<folder_id>.sync-state.json - per-folder snapshots\n"
        "\n"
        "Do not edit these files while the application is running.\n"
    )

    for path, content in ((readme_path(), _readme), (sync_readme_path(), _sync_readme)):
        try:
            if os.path.exists(path):
                continue
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception:
            pass


def report_legacy_files() -> list[str]:
    """Return a list of legacy paths detected on disk.

    Non-destructive helper for diagnostics.
    """
    base = app_data_dir()
    candidates = [
        os.path.join(base, "settings.json"),
        os.path.join(base, "notifications.json"),
        os.path.join(base, "sync_mappings.json"),
        os.path.join(base, "sync_state.json"),
        os.path.join(base, "state"),
        os.path.join(base, "settings", "subscriptions.json"),
        # logs that used to live in base dir
        os.path.join(base, "larix_nexus.log"),
        os.path.join(base, "errors.log"),
        os.path.join(base, "crash_diagnostics.log"),
        os.path.join(base, "ui_trace.log"),
        os.path.join(base, "_sync_debug.log"),
        os.path.join(base, "copy_logs.txt"),
    ]

    found: list[str] = []
    for p in candidates:
        try:
            if os.path.exists(p):
                found.append(p)
        except Exception:
            pass
    return found
