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
