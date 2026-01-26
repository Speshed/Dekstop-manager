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
    """Return directory where application data should be stored.
    
    Windows: %APPDATA%\LarixNexus
    Linux/Mac: ~/.config/larix_nexus
    """
    import platform
    
    # On Windows, use APPDATA for all app data
    if platform.system() == "Windows":
        app_data = os.getenv("APPDATA")
        if app_data:
            return os.path.join(app_data, "LarixNexus")
        # Fallback
        return os.path.expanduser("~/.config/LarixNexus")
    
    # On Linux/Mac, use ~/.config for compatibility
    return os.path.expanduser("~/.config/larix_nexus")
