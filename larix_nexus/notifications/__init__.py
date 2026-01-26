# -*- coding: utf-8 -*-
"""Notifications module for Larix Nexus Desktop."""

from .manager import (
    init_notifications_db,
    save_folder_notification,
    remove_folder_notification,
    load_folder_notifications,
    is_folder_notification_enabled,
    save_pending_notifications,
    load_pending_notifications,
)

__all__ = [
    "init_notifications_db",
    "save_folder_notification",
    "remove_folder_notification",
    "load_folder_notifications",
    "is_folder_notification_enabled",
    "save_pending_notifications",
    "load_pending_notifications",
]
