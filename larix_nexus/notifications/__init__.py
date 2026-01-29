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
    save_user_actions_log,
    load_user_actions_log,
)

__all__ = [
    "init_notifications_db",
    "save_folder_notification",
    "remove_folder_notification",
    "load_folder_notifications",
    "is_folder_notification_enabled",
    "save_pending_notifications",
    "load_pending_notifications",
    "save_user_actions_log",
    "load_user_actions_log",
]
