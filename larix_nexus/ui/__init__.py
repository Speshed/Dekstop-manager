# -*- coding: utf-8 -*-
"""UI module for Larix Nexus Desktop."""

from .main_window import MainWindow
from .widgets import ScrollbarProxyStyle
from .dialogs import (
    FileDetailsDialog,
    FolderDetailsDialog,
    BatchDownloadDialog,
    SingleDownloadDialog,
    BatchUploadDialog,
)

__all__ = [
    "MainWindow",
    "ScrollbarProxyStyle",
    "FileDetailsDialog",
    "FolderDetailsDialog",
    "BatchDownloadDialog",
    "SingleDownloadDialog",
    "BatchUploadDialog",
]

from .folder_actions import inject_folder_actions_to_main_window
inject_folder_actions_to_main_window(MainWindow)

from .sync_handlers import inject_sync_handlers_to_main_window
inject_sync_handlers_to_main_window(MainWindow)

from .notification_handlers import inject_notification_handlers_to_main_window
inject_notification_handlers_to_main_window(MainWindow)

from .context_menus import inject_context_menus_to_main_window
inject_context_menus_to_main_window(MainWindow)

from .table_filters import inject_table_filters_to_main_window
inject_table_filters_to_main_window(MainWindow)

from .download_operations import inject_download_operations_to_main_window
inject_download_operations_to_main_window(MainWindow)

from .upload_operations import inject_upload_operations_to_main_window
inject_upload_operations_to_main_window(MainWindow)

from .theme_operations import inject_theme_operations_to_main_window
inject_theme_operations_to_main_window(MainWindow)

from .tree_operations import inject_tree_operations_to_main_window
inject_tree_operations_to_main_window(MainWindow)

from .table_operations import inject_table_operations_to_main_window
inject_table_operations_to_main_window(MainWindow)

from .ui_helpers import inject_ui_helpers_to_main_window
inject_ui_helpers_to_main_window(MainWindow)

from .header_menu import inject_header_menu_to_main_window
inject_header_menu_to_main_window(MainWindow)

from .column_ops import inject_column_ops_to_main_window
inject_column_ops_to_main_window(MainWindow)

from .file_ops import inject_file_ops_to_main_window
inject_file_ops_to_main_window(MainWindow)

from .tree_search import inject_tree_search_to_main_window
inject_tree_search_to_main_window(MainWindow)
