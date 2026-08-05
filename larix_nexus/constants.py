from PySide6 import QtCore, QtGui, QtWidgets
import os

from larix_nexus.utils.paths import rsrc_path, program_dir
from larix_nexus.style_tokens import build_dark_color_replacements
from larix_nexus.app_style_overrides import get_main_app_dark_color_overrides

# единный бокс для иконок
ICON_BOX = QtCore.QSize(20, 20)  # 20-24 обычно идеально под высоту строки ~28

# --- Константы/настройки ---
BASE_URL = os.environ.get("LARIX_BASE_URL", "https://platform-api.larix.ru").rstrip("/")
DOWNLOAD_DIR = os.path.abspath(os.environ.get("LARIX_DOWNLOAD_DIR", "./Nexus_downloads"))
CACHE_TTL_SEC = 600
APP_TITLE = "Larix Nexus Desktop"

# UI constants
CHECKBOX_COLUMN_WIDTH = 36  # Фиксированная ширина первого столбца с чекбоксами (18px чекбокс + отступы для удобства)

# Notifications database
NOTIFY_DB_PATH = os.path.join(program_dir(), "notifications.db")
NOTIFY_SETTINGS_GROUP = "notifications/folder_subscriptions"

SETTINGS_ORG = "Larix"
SETTINGS_APP = "NexusDesktop"
SETTINGS_THEME_KEY = "ui/theme"
THEME_LIGHT = "light"
THEME_DARK = "dark"

LIGHT_THEME_QSS = ""

# Notification icons (alarm)
ALARM_ICON_PATH = rsrc_path("icon", "alarm.png")
ALARM1_ICON_PATH = rsrc_path("icon", "alarm(1).png")

# Login icons
LOGIN_ICON_PATH = rsrc_path("icon", "free-icon-login-2623062.png")
CHOICE_ICON_PATH = rsrc_path("icon", "choice.png")
EYE_OPEN_ICON_PATH = rsrc_path("icon", "free-icon-eye-2455724.png")
EYE_CLOSED_ICON_PATH = rsrc_path("icon", "free-icon-hide-11238328.png")

# Toolbar icons
TOOLBAR_REFRESH_ICON = rsrc_path("icon", "free-icon-refresh-5234214.png")
TOOLBAR_UPLOAD_ICON = rsrc_path("icon", "upload.png")
TOOLBAR_DOWNLOAD_ICON = rsrc_path("icon", "free-icon-download-126488.png")
TOOLBAR_NEW_FOLDER_ICON = rsrc_path("icon", "free-icon-plus-3303893.png")
TOOLBAR_SETTINGS_ICON = rsrc_path("icon", "free-icon-setting-3288004.png")

# Tree icons
FOLDER_ICON_PATH = rsrc_path("icon", "folder_icon_variant_1.png").replace("\\", "/")

# Common UI icons (normalized paths)
SORT_ICON_UP_PATH = rsrc_path("icon", "arrow-up.png").replace("\\", "/")
SORT_ICON_DOWN_PATH = rsrc_path("icon", "arrow-down.png").replace("\\", "/")
ARROW_LEFT_PATH = rsrc_path("icon", "arrow-left.png").replace("\\", "/")
ARROW_RIGHT_PATH = rsrc_path("icon", "arrow-right.png").replace("\\", "/")

# Aliases for compatibility
ARROW_LEFT_ICON_PATH = ARROW_LEFT_PATH
ARROW_RIGHT_ICON_PATH = ARROW_RIGHT_PATH
FILTER_ICON_PATH = rsrc_path("icon", "filter.png").replace("\\", "/")
REFRESH_ICON_PATH = rsrc_path("icon", "free-icon-refresh-5234214.png").replace("\\", "/")
INSERT_ICON_PATH = rsrc_path("icon", "insert.png").replace("\\", "/")
EDIT_ICON_PATH = rsrc_path("icon", "edit.png").replace("\\", "/")
DELETE_ICON_PATH = rsrc_path("icon", "delete.png").replace("\\", "/")
STRUCTURE_ICON_PATH = rsrc_path("icon", "structure.png").replace("\\", "/")
SYNC_ICON_PATH = rsrc_path("icon", "sync.png").replace("\\", "/")
COMPARISON_ICON_PATH = rsrc_path("icon", "comparison.png").replace("\\", "/")
MOVE_FOLDER_ICON_PATH = rsrc_path("icon", "move_folder.png").replace("\\", "/")
COPY_FOLDER_ICON_PATH = rsrc_path("icon", "copyfolder.png").replace("\\", "/")
PUBLIC_LINK_ICON_PATH = rsrc_path("icon", "links.png").replace("\\", "/")
BACK_ICON_PATH = rsrc_path("icon", "back.png").replace("\\", "/")
CUSTOM_FOLDER_ICON_PATH = rsrc_path("icon", "folder_icon_variant_1.png").replace("\\", "/")
NO_FOLDER_ICON_PATH = rsrc_path("icon", "no folder.png").replace("\\", "/")
EYE_OPEN_ICON_PATH = rsrc_path("icon", "free-icon-eye-2455724.png").replace("\\", "/")
EYE_CLOSED_ICON_PATH = rsrc_path("icon", "free-icon-hide-11238328.png").replace("\\", "/")
CUSTOM_SAVE_ICON_PATH = rsrc_path("icon", "free-icon-download-126488.png").replace("\\", "/")
CUSTOM_PLUS_ICON_PATH = rsrc_path("icon", "free-icon-plus-3303893.png").replace("\\", "/")
DOWN_ARROW_ICON_PATH = rsrc_path("icon", "free-icon-down-arrow-3889508.png").replace("\\", "/")
FLASH_ICON_PATH = rsrc_path("icon", "flash.png").replace("\\", "/")
LOGIN_ICON_PATH = rsrc_path("icon", "free-icon-login-2623062.png").replace("\\", "/")
CHOICE_ICON_PATH = rsrc_path("icon", "choice.png").replace("\\", "/")
CAD_ICON_PATH = rsrc_path("icon", "free-icon-cad-8304395.png").replace("\\", "/")
GEAR_ICON_NAME = rsrc_path("icon", "free-icon-setting-3288004.png").replace("\\", "/")
CHECK_ICON_OFF_PATH = rsrc_path("icon", "check.png").replace("\\", "/")
CHECK_ICON_ON_PATH = rsrc_path("icon", "select.png").replace("\\", "/")
CHECK_ICON_MID_PATH = rsrc_path("icon", "poloska.png").replace("\\", "/")

# Radio check icons (for PDF Compare)
RCHECK_ICON_OFF_PATH = rsrc_path("icon", "circle2.png").replace("\\", "/")
RCHECK_ICON_ON_PATH = rsrc_path("icon", "circle dot.png").replace("\\", "/")

# Warning icon
WARNING_ICON_PATH = rsrc_path("icon", "warning.png").replace("\\", "/")
ALERT_ICON_PATH = rsrc_path("icon", "alert.png").replace("\\", "/")

# Drag & drop icon
DRAG_FILE_ICON_PATH = rsrc_path("icon", "file.png").replace("\\", "/")

# White themed icons (for dark theme in PDF Compare)
DOWN_ARROW_WHITE_ICON_PATH = rsrc_path("icon", "white", "arrow-down.png").replace("\\", "/")

DARK_THEME_QSS = ""

EXTRA_QSS = (
    "QSplitter::handle:horizontal { width: 2px; background: rgba(0,0,0,0.06); border-radius: 10px; margin: 4px 0; }\n"
    "QSplitter::handle:horizontal:hover { background: rgba(247,146,30,0.12); }\n"
    "QSplitter::handle:vertical { border-radius: 10px; }\n"
    "QTreeWidget#docsTree, QTreeWidget#docsTree:focus, QTreeWidget#docsTree::item, "
    "QTreeWidget#docsTree::item:selected:active, QTreeWidget#docsTree::item:selected:!active, "
    "QTreeWidget#docsTree::item:focus { outline: 0; }\n"
    "\n"
    "/* Cancel buttons in status bar (copy/move) - secondary style */\n"
    "QPushButton#copyCancelBtn, QPushButton#moveCancelBtn {\n"
    "    padding: 4px 12px;\n"
    "    min-height: 24px;\n"
    "    border-radius: 12px;\n"
    "    font-size: 12px;\n"
    "}\n"
    "\n"
    "/* Keep 'без папок' icon button compact */\n"
    "QToolButton#btnNoFolders, QToolButton#btnNoFolders:hover, QToolButton#btnNoFolders:pressed, QToolButton#btnNoFolders:checked {\n"
    "    padding: 0 8px;\n"
    "    margin: 0;\n"
    "    min-width: 32px;\n"
    "    max-width: 32px;\n"
    "    border-radius: 12px;\n"
    "}\n"
    "/* Scrollbar background - override QWidget rule */\n"
    "QScrollBar { background-color: #FFFFFF !important; }\n"
    "QScrollBar::add-line { background-color: #FFFFFF !important; }\n"
    "QScrollBar::sub-line { background-color: #FFFFFF !important; }\n"
    "QScrollBar::add-page { background-color: #FFFFFF !important; }\n"
    "QScrollBar::sub-page { background-color: #FFFFFF !important; }\n"
)


_COLOR_REPLACEMENTS = build_dark_color_replacements(
    get_main_app_dark_color_overrides()
)

# SYNC_ROLE for the sync badge on the RIGHT of the text, without overlaying the folder icon.
SYNC_ROLE = QtCore.Qt.UserRole + 1111

# Custom role: notifications subscription status for tree items (0=subscribed, 1=pending)
NOTIFY_ROLE = QtCore.Qt.UserRole + 2222
