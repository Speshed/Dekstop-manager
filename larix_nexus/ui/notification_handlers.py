# -*- coding: utf-8 -*-
"""Notification-related UI handlers injected into MainWindow.

Keep notification UI logic out of main_window.py while preserving behavior.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QObject, QEvent, QRectF, QTimer
from PySide6.QtGui import (
    QColor,
    QBrush,
    QPainter,
    QPainterPath,
    QPalette,
    QIcon,
    QGuiApplication,
)
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QStyledItemDelegate,
    QStyle,
    QStyleOptionViewItem,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from larix_nexus.constants import (
    APP_TITLE,
    ALARM_ICON_PATH,
    ALARM1_ICON_PATH,
    NOTIFY_ROLE,
    FILTER_ICON_PATH, EDIT_ICON_PATH, DELETE_ICON_PATH,
    CUSTOM_FOLDER_ICON_PATH, CUSTOM_PLUS_ICON_PATH
)
from larix_nexus.notifications import (
    load_folder_notifications,
    save_folder_notification,
    remove_folder_notification,
    save_pending_notifications,
    is_folder_notification_enabled,
)
from larix_nexus.models.files_table import IconProvider
from larix_nexus.ui.helpers import open_in_os
from larix_nexus.utils.helpers import normalize_id, normalize_project_id, compare_file_states
from larix_nexus.utils.settings import load_settings, save_settings
from larix_nexus.utils.logging import sync_log
from larix_nexus.utils.theme import _is_dark_mode, themed_icon
from larix_nexus.utils.i18n import t


def get_title(node: dict) -> str:
    return (node or {}).get("name") or (node or {}).get("title") or t("common.no_name")


def _sync_notify_tree_badges(self, project_id=None) -> None:
    """Re-apply notify badges on the folder tree from persisted state."""
    try:
        pid = project_id if project_id is not None else self.current_project_id()
        if pid and hasattr(self, "_restore_tree_badges"):
            self._restore_tree_badges(pid)
            return
    except Exception:
        pass
    try:
        if hasattr(self, "tree") and self.tree is not None:
            self.tree.viewport().update()
    except Exception:
        pass


def _pending_folder_key(folder_id) -> str:
    return normalize_id(folder_id)


def _folder_tree_path(self, folder_id, fallback: str = "") -> str:
    """Build a human-readable path for a folder from the project tree."""
    try:
        item = self.get_folder_tree_item(folder_id)
        if item is None:
            return str(fallback or "")
        parts: list[str] = []
        while item is not None:
            try:
                root = self.tree.invisibleRootItem()
            except Exception:
                root = None
            if root is not None and item == root:
                break
            try:
                name = str(item.text(0) or "").strip()
                if name:
                    parts.append(name)
            except Exception:
                pass
            try:
                item = item.parent()
            except Exception:
                break
        parts.reverse()
        if parts:
            return " / ".join(parts)
    except Exception:
        pass
    return str(fallback or "")


def _current_workspace_id(self) -> str:
    try:
        ws = getattr(self.api, "selected_workspace_id", None)
        if ws not in (None, "", 0, "0"):
            return normalize_id(ws)
    except Exception:
        pass
    try:
        settings = load_settings()
        return normalize_id(settings.get("workspace_id") or "")
    except Exception:
        return ""


def _switch_workspace_for_navigation(self, workspace_id) -> bool:
    ws_target = normalize_id(workspace_id)
    if not ws_target:
        sync_log("NOTIFY_NAV: switched workspace ok (legacy no workspace_id)")
        return True
    try:
        ws_current = _current_workspace_id(self)
    except Exception:
        ws_current = ""
    if ws_current == ws_target:
        sync_log("NOTIFY_NAV: switched workspace ok (already selected={})", ws_target)
        return True
    try:
        changed = bool(self.api.change_workspace(ws_target))
        if not changed:
            sync_log("NOTIFY_NAV: switched workspace fail workspace_id={}", ws_target)
            return False
        try:
            self.api.selected_workspace_id = ws_target
        except Exception:
            pass
        try:
            settings = load_settings()
            settings["workspace_id"] = ws_target
            save_settings(settings)
        except Exception:
            pass
        projects = self.api.list_projects() or []
        self.cb_projects.blockSignals(True)
        self.cb_projects.clear()
        self.cb_projects.addItem(t("common.select_project"), userData=None)
        for p in projects:
            p_id = p.get("id") or p.get("project_id") or p.get("projectId")
            self.cb_projects.addItem(get_title(p), userData=p_id)
        self.cb_projects.setCurrentIndex(0)
        self.cb_projects.blockSignals(False)
        try:
            self.cb_projects.setEnabled(True)
        except Exception:
            pass
        sync_log("NOTIFY_NAV: switched workspace ok workspace_id={} projects={}", ws_target, len(projects))
        return True
    except Exception as e:
        sync_log("NOTIFY_NAV: switched workspace fail workspace_id={} error={}", ws_target, e)
        return False


def _notify_nav_failed(
    self,
    reason: str,
    message: str,
    *,
    workspace_id: str = "",
    project_id: str = "",
    folder_id: str = "",
    path: str = "",
) -> None:
    sync_log(
        "NOTIFY_NAV failed reason={} workspace_id={} project_id={} folder_id={} path={}",
        reason,
        workspace_id or "—",
        project_id or "—",
        folder_id or "—",
        path or "—",
    )
    QMessageBox.warning(self, t("notifications.navigation"), message)


def _select_project_for_navigation(self, project_id) -> bool:
    pid_target = normalize_project_id(project_id)
    if not pid_target:
        sync_log("NOTIFY_NAV: project selected fail project_id=empty")
        return False

    def _find_project_index() -> int:
        for i in range(self.cb_projects.count()):
            p = self.cb_projects.itemData(i)
            if normalize_project_id(p) == pid_target:
                return i
        return -1

    idx = _find_project_index()
    if idx < 0:
        try:
            projects = self.api.list_projects() or []
            self.cb_projects.blockSignals(True)
            self.cb_projects.clear()
            self.cb_projects.addItem(t("common.select_project"), userData=None)
            for p in projects:
                p_id = p.get("id") or p.get("project_id") or p.get("projectId")
                self.cb_projects.addItem(get_title(p), userData=p_id)
            self.cb_projects.setCurrentIndex(0)
            self.cb_projects.blockSignals(False)
        except Exception:
            pass
        idx = _find_project_index()

    if idx < 0:
        sync_log("NOTIFY_NAV: project selected fail project_id={}", pid_target)
        return False

    try:
        self.cb_projects.blockSignals(True)
        self.cb_projects.setCurrentIndex(idx)
        self.cb_projects.blockSignals(False)
        ok = bool(self.load_tree_for_project(project_id))
        sync_log("NOTIFY_NAV: project selected {} project_id={}", "ok" if ok else "fail", pid_target)
        return ok
    except Exception as e:
        sync_log("NOTIFY_NAV: project selected fail project_id={} error={}", pid_target, e)
        return False


def _navigate_to_folder(
    self,
    workspace_id,
    project_id: int | str,
    folder_id: int | str,
    folder_path_fallback: str = "",
) -> bool:
    """Open the subscribed folder in the tree without clearing pending notifications."""
    ws_norm = normalize_id(workspace_id or "")
    pid_norm = normalize_project_id(project_id)
    fid_norm = normalize_id(folder_id)
    path_hint = str(folder_path_fallback or "").strip()
    busy_started = False
    try:
        if hasattr(self, "_begin_busy_status"):
            self._begin_busy_status(t("status.loading"))
            busy_started = True

        sync_log(
            "NOTIFY_NAV: target workspace_id={} project_id={} folder_id={} path={}",
            ws_norm or "—",
            pid_norm or "—",
            fid_norm or "—",
            path_hint or "—",
        )

        if not _switch_workspace_for_navigation(self, workspace_id):
            _notify_nav_failed(
                self,
                "workspace_not_found",
                t("notifications.navigate_workspace_failed", workspace_id=ws_norm or "—"),
                workspace_id=ws_norm,
                project_id=pid_norm,
                folder_id=fid_norm,
                path=path_hint,
            )
            return False
        if not _select_project_for_navigation(self, project_id):
            _notify_nav_failed(
                self,
                "project_not_found",
                t("notifications.navigate_project_failed", project_id=pid_norm or "—"),
                workspace_id=ws_norm,
                project_id=pid_norm,
                folder_id=fid_norm,
                path=path_hint,
            )
            return False

        folder_item = self.get_folder_tree_item(folder_id)
        if not folder_item:
            tree_ok = bool(self.load_tree_for_project(project_id))
            sync_log("NOTIFY_NAV: tree loaded {} project_id={}", "ok" if tree_ok else "fail", pid_norm)
            folder_item = self.get_folder_tree_item(folder_id)

        if not folder_item:
            display_path = path_hint or "—"
            _notify_nav_failed(
                self,
                "folder_not_found",
                t(
                    "notifications.navigate_target_unavailable",
                    path=display_path,
                    project_id=pid_norm or "—",
                    folder_id=fid_norm or "—",
                ),
                workspace_id=ws_norm,
                project_id=pid_norm,
                folder_id=fid_norm,
                path=display_path,
            )
            return False

        self.tree.setCurrentItem(folder_item)
        folder_node = folder_item.data(0, Qt.UserRole)
        if not isinstance(folder_node, dict):
            _notify_nav_failed(
                self,
                "open_failed",
                t(
                    "notifications.navigate_target_unavailable",
                    path=path_hint or "—",
                    project_id=pid_norm or "—",
                    folder_id=fid_norm or "—",
                ),
                workspace_id=ws_norm,
                project_id=pid_norm,
                folder_id=fid_norm,
                path=path_hint,
            )
            return False

        if not (folder_node.get("projectId") or folder_node.get("project_id")):
            folder_node["projectId"] = project_id
        opened = bool(self.open_folder_node(folder_node))
        QApplication.processEvents()
        if not opened:
            _notify_nav_failed(
                self,
                "open_failed",
                t(
                    "notifications.navigate_target_unavailable",
                    path=path_hint or "—",
                    project_id=pid_norm or "—",
                    folder_id=fid_norm or "—",
                ),
                workspace_id=ws_norm,
                project_id=pid_norm,
                folder_id=fid_norm,
                path=path_hint,
            )
            return False

        try:
            self.update_path_label()
        except Exception:
            pass
        sync_log("NOTIFY_NAV: folder opened folder_id={}", fid_norm)
        return True
    except Exception as e:
        _notify_nav_failed(
            self,
            "error",
            t("navigation.error", error=e),
            workspace_id=ws_norm,
            project_id=pid_norm,
            folder_id=fid_norm,
            path=path_hint,
        )
        return False
    finally:
        if busy_started and hasattr(self, "_end_busy_status"):
            try:
                self._end_busy_status()
            except Exception:
                pass


def _append_unsubscribe_all_menu_item(self) -> None:
    """Add bulk-unsubscribe action when folder subscriptions exist."""
    try:
        subs = load_folder_notifications()
        if not subs:
            return
        self.menu_notify.addSeparator()
        act = self.menu_notify.addAction(t("notifications.unsubscribe_all"))
        act.triggered.connect(self._confirm_unsubscribe_all_notifications)
    except Exception:
        pass


def _confirm_unsubscribe_all_notifications(self) -> None:
    try:
        subscriptions = load_folder_notifications()
        if not subscriptions:
            try:
                self.status.showMessage(t("notifications.unsubscribe_all_empty"), 3500)
            except Exception:
                pass
            return
        reply = QMessageBox.question(
            self,
            t("notifications.title"),
            t("notifications.unsubscribe_all_confirm"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._on_unsubscribe_all_notifications()
    except Exception:
        pass


def _on_unsubscribe_all_notifications(self) -> None:
    removed_count = 0
    failed_count = 0
    removed_folder_ids = set()
    try:
        subscriptions = list(load_folder_notifications() or [])
        for sub in subscriptions:
            try:
                project_id = sub.get("project_id")
                folder_id = sub.get("folder_id")
                if project_id is None or folder_id is None:
                    continue
                removed = remove_folder_notification(project_id, folder_id)
                if removed:
                    removed_count += 1
                    removed_folder_ids.add(normalize_id(folder_id))
                else:
                    failed_count += 1
                    sync_log("NOTIFY bulk unsubscribe failed; operation=remove_folder")
            except Exception:
                failed_count += 1
                sync_log("NOTIFY bulk unsubscribe failed; error_type=exception")

        try:
            if hasattr(self, "_subscriptions") and isinstance(self._subscriptions, dict):
                for folder_id in removed_folder_ids:
                    self._subscriptions.pop(folder_id, None)
        except Exception:
            pass

        try:
            pending = getattr(self, "_pending_notifications", {}) or {}
            for folder_id in removed_folder_ids:
                pending.pop(_pending_folder_key(folder_id), None)
                pending.pop(folder_id, None)
            self._pending_notifications = pending
            save_pending_notifications(self._pending_notifications)
        except Exception:
            pass

        try:
            for _fid, item in (getattr(self, "folder_item_by_id", {}) or {}).items():
                if normalize_id(_fid) not in removed_folder_ids:
                    continue
                try:
                    item.setData(0, NOTIFY_ROLE, None)
                except Exception:
                    pass
        except Exception:
            pass

        try:
            self._update_notify_icon()
        except Exception:
            pass
        try:
            self._build_notify_menu()
        except Exception:
            pass
        _sync_notify_tree_badges(self)
        try:
            if hasattr(self, "tree") and self.tree is not None:
                self.tree.viewport().update()
        except Exception:
            pass
        try:
            if failed_count:
                if removed_count:
                    self.status.showMessage(
                        t("notifications.unsubscribe_all_done", count=removed_count),
                        4500,
                    )
                    QMessageBox.warning(
                        self,
                        t("common.error"),
                        t("notifications.enable_error", error=t("common.error")),
                    )
                else:
                    QMessageBox.warning(
                        self,
                        t("common.error"),
                        t("notifications.enable_error", error=t("common.error")),
                    )
            else:
                self.status.showMessage(
                    t("notifications.unsubscribe_all_done", count=removed_count),
                    4500,
                )
        except Exception:
            pass
    except Exception:
        pass


def toggle_folder_notifications(self, node: dict):
    """Toggle notifications for a folder"""
    pid = self.current_project_id()
    fid = node.get("id")
    if not pid or not fid:
        return

    folder_path = _folder_tree_path(self, fid, get_title(node))
    workspace_id = _current_workspace_id(self)
    is_subscribed = is_folder_notification_enabled(pid, fid)

    if is_subscribed:
        # Отключить уведомления - удалить из persistent storage и из памяти
        removed = remove_folder_notification(pid, fid)
        if not removed:
            QMessageBox.warning(
                self,
                t("common.error"),
                t("notifications.enable_error", error=t("common.error")),
            )
            return
        try:
            fid_str = normalize_id(fid)
            if fid_str in self._subscriptions:
                del self._subscriptions[fid_str]
        except Exception:
            pass
        QMessageBox.information(
            self,
            t("notifications.title"),
            t("notifications.disabled_for_folder", folder=folder_path),
        )
    else:
        # Включить уведомления - сохранить текущее состояние файлов
        try:
            # Получить текущее состояние файлов через API (не полагаться на ключ children в дереве)
            files = self._build_notification_file_state(pid, fid, folder_path, force_fresh=True)

            # Сохранить состояние в persistent storage
            saved = save_folder_notification(
                pid, fid, folder_path, files, workspace_id=workspace_id
            )
            if not saved:
                QMessageBox.warning(
                    self,
                    t("common.error"),
                    t("notifications.enable_error", error=t("common.error")),
                )
                return

            # Также добавить в память (_subscriptions) для polling
            try:
                fid_str = normalize_id(fid)
                # Получить базовое состояние из облака
                try:
                    state = self._cloud_state_for_folder(pid, fid_str)
                except Exception:
                    state = {}
                self._subscriptions[fid_str] = {
                    "workspace_id": workspace_id,
                    "project_id": pid,
                    "state": state,
                    "pending": False,
                    "title": folder_path,
                }
            except Exception:
                pass

            QMessageBox.information(
                self,
                t("notifications.title"),
                t("notifications.enabled_for_folder", folder=folder_path),
            )
        except Exception as e:
            QMessageBox.warning(self, t("common.error"), t("notifications.enable_error", error=e))

    # Обновить notify button/menu и бейджи в дереве
    try:
        self._update_notify_icon()
        self._build_notify_menu()
    except Exception:
        pass
    try:
        QTimer.singleShot(0, lambda p=pid: _sync_notify_tree_badges(self, p))
    except Exception:
        _sync_notify_tree_badges(self, pid)


def _check_notifications(self):
    """Periodic check for file changes in subscribed folders"""
    try:
        # During app startup (or after logout) API may be unavailable; avoid false
        # "everything deleted" notifications when cloud scan returns empty.
        try:
            if not getattr(self.api, "token", None):
                return
        except Exception:
            return

        subscriptions = load_folder_notifications()
        if not subscriptions:
            self._update_global_notification_badge()
            return


        for sub in subscriptions:
            project_id = sub["project_id"]
            folder_id = sub["folder_id"]
            folder_key = _pending_folder_key(folder_id)
            folder_path = sub["folder_path"]
            saved_state = sub["file_state"]
            workspace_id = normalize_id(sub.get("workspace_id") or "")

            # Migrate legacy/buggy baselines where ids were missing/0 and thus
            # broke change detection.
            try:
                fixed = False
                if isinstance(saved_state, list):
                    for f in saved_state:
                        if not isinstance(f, dict):
                            continue
                        fid = f.get("id")
                        if fid in (None, "", 0, "0", False):
                            name = str(f.get("name") or "").strip()
                            p = str(f.get("path") or "").replace("\\\\", "/").strip("/")
                            new_id = f"{p}/{name}" if (p and name) else (name or p)
                            if new_id:
                                f["id"] = new_id
                                fixed = True
                if fixed:
                    try:
                        save_folder_notification(
                            project_id,
                            folder_id,
                            folder_path,
                            saved_state,
                            workspace_id=workspace_id,
                        )
                    except Exception:
                        pass
            except Exception:
                pass


            current_files = self._build_notification_file_state(project_id, folder_id, folder_path, force_fresh=True)


            # Guard against transient empty scans (startup/network/API hiccup).
            # Require 2 consecutive empty scans before treating it as a real
            # "all deleted" situation.
            try:
                if not hasattr(self, "_notify_empty_hits") or getattr(self, "_notify_empty_hits") is None:
                    self._notify_empty_hits = {}
                hits = getattr(self, "_notify_empty_hits", {})
                hit_key = f"{normalize_project_id(project_id)}:{normalize_id(folder_id)}"

                if (
                    isinstance(saved_state, list)
                    and len(saved_state) > 0
                    and (not isinstance(current_files, list) or len(current_files) == 0)
                ):
                    prev_hits = int(hits.get(hit_key, 0) or 0)
                    new_hits = prev_hits + 1
                    hits[hit_key] = new_hits
                    self._notify_empty_hits = hits
                    try:
                        sync_log("NOTIFY empty scan guarded; hits={} saved={}", new_hits, len(saved_state))
                    except Exception:
                        pass
                    if new_hits < 2:
                        continue
                else:
                    # Reset counter on any successful/non-empty scan
                    try:
                        if hit_key in hits:
                            hits.pop(hit_key, None)
                            self._notify_empty_hits = hits
                    except Exception:
                        pass
            except Exception:
                pass

            # Heal legacy/empty baselines
            try:
                if (
                    (not isinstance(saved_state, list) or len(saved_state) == 0)
                    and isinstance(current_files, list)
                    and len(current_files) > 0
                ):
                    try:
                        save_folder_notification(
                            project_id,
                            folder_id,
                            folder_path,
                            current_files,
                            workspace_id=workspace_id,
                        )
                    except Exception:
                        pass
                    # Use the freshly initialized baseline for this run (no notification).
                    continue
            except Exception:
                pass

            # Cleanup expired user actions before filtering
            self._cleanup_expired_user_actions()

            # Show all changes
            changes = compare_file_states(saved_state, current_files, filter_func=None)

            try:
                sync_log(
                    "NOTIFY check completed; saved={} current={} changes={}",
                    len(saved_state) if isinstance(saved_state, list) else -1,
                    len(current_files) if isinstance(current_files, list) else -1,
                    len(changes) if isinstance(changes, list) else -1,
                )
            except Exception:
                pass


            if changes:
                existing_notif = self._pending_notifications.get(folder_key)
                if existing_notif is None and folder_id != folder_key:
                    existing_notif = self._pending_notifications.pop(folder_id, None)

                # Toast only on new/changed payload
                try:
                    sig_parts = []
                    for ch in (changes or [])[:20]:
                        try:
                            ctype = str((ch or {}).get("type") or "")
                            f = (ch or {}).get("file") or {}
                            fid = normalize_id(f.get("id"))
                            fname = str(f.get("name") or "")
                            sig_parts.append(f"{ctype}:{fid}:{fname}")
                        except Exception:
                            continue
                    new_sig = "|".join(sig_parts)
                except Exception:
                    new_sig = ""
                try:
                    prev_sig = str((existing_notif or {}).get("_sig") or "")
                except Exception:
                    prev_sig = ""
                should_toast = (not existing_notif) or (new_sig and new_sig != prev_sig)

                self._pending_notifications[folder_key] = {
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "folder_path": folder_path,
                    "changes": changes,
                    "current_files": current_files,
                    "_sig": new_sig,
                }
                if folder_id != folder_key:
                    self._pending_notifications.pop(folder_id, None)
                save_pending_notifications(self._pending_notifications)

                self._update_global_notification_badge()
                try:
                    self._update_notify_icon()
                    self._build_notify_menu()
                except Exception:
                    pass

                if should_toast:
                    try:
                        self._toast_changes(folder_path, changes)
                    except Exception:
                        pass
            else:
                # No changes
                self._pending_notifications.pop(folder_key, None)
                if folder_id != folder_key:
                    self._pending_notifications.pop(folder_id, None)
                save_pending_notifications(self._pending_notifications)
                self._update_global_notification_badge()
                try:
                    self._update_notify_icon()
                    self._build_notify_menu()
                except Exception:
                    pass

        self._update_global_notification_badge()
        _sync_notify_tree_badges(self)

    except Exception as e:
        sync_log("NOTIFY polling failed; error_type={}", type(e).__name__)


def _update_global_notification_badge(self):
    """Disabled per UX: hide the floating bell in the window corner."""
    try:
        self.global_notify_btn.setVisible(False)
        return
    except Exception as e:
        sync_log("NOTIFY global badge hide failed; error_type={}", type(e).__name__)


def _show_notifications_menu(self):
    """Show dropdown menu with list of folders that have changes"""
    try:
        if not self._pending_notifications:
            return

        menu = QMenu(self)
        is_dark = _is_dark_mode()
        bg_color = "#1e1e1e" if is_dark else "white"
        border_color = "#505050" if is_dark else "#ddd"
        text_color = "#e0e0e0" if is_dark else "#222"
        hover_bg = "rgba(247, 146, 30, 0.15)" if is_dark else "#FFE3C2"
        menu.setStyleSheet(
            f"""
                QMenu {{
                    background-color: {bg_color};
                    border:1px solid {border_color};
                    border-radius:6px;
                    padding:4px;
                    color: {text_color};
                }}
                QMenu::item {{
                    padding: 8px 24px 8px 12px;
                    border-radius:4px;
                }}
                QMenu::item:selected {{
                    background-color: {hover_bg};
                }}
            """
        )

        for folder_id, notif_data in self._pending_notifications.items():
            folder_path = notif_data["folder_path"]
            display_path = _folder_tree_path(self, folder_id, folder_path) or folder_path
            changes_count = len(notif_data["changes"])
            action = menu.addAction(f"📁 {display_path} ({changes_count})")
            action.setData(folder_id)
            action.triggered.connect(lambda checked=False, fid=folder_id: self._show_changes_dialog(fid))

        menu.exec_(self.global_notify_btn.mapToGlobal(self.global_notify_btn.rect().bottomLeft()))
    except Exception as e:
        sync_log("NOTIFY menu display failed; error_type={}", type(e).__name__)


def _show_changes_dialog(self, folder_id):
    """Show detailed changes dialog for a specific folder with navigation"""
    try:
        folder_key = _pending_folder_key(folder_id)
        if folder_key not in self._pending_notifications:
            if folder_id in self._pending_notifications:
                self._pending_notifications[folder_key] = self._pending_notifications.pop(folder_id)
            else:
                return

        notif_data = self._pending_notifications[folder_key]
        folder_path = notif_data["folder_path"]
        changes = notif_data["changes"]
        current_files = notif_data["current_files"]
        project_id = notif_data["project_id"]
        workspace_id = normalize_id(notif_data.get("workspace_id") or "")
        display_path = _folder_tree_path(self, folder_id, folder_path)

        dialog = QDialog(self)
        dialog.setAttribute(Qt.WA_QuitOnClose, False)
        dialog.setWindowTitle(t("notifications.changes_in_folder", folder=display_path or folder_path))
        dialog.setMinimumSize(400, 250)
        dialog.resize(480, 350)
        is_dark = _is_dark_mode()
        if is_dark:
            dialog.setStyleSheet(
                """
                    QDialog {
                        background-color: #121212;
                        color: #e0e0e0;
                    }
                    QLabel {
                        color: #e0e0e0;
                    }
                    QTableWidget {
                        background-color: #1e1e1e;
                        color: #e0e0e0;
                    }
                    QTableWidget::item {
                        color: #e0e0e0;
                        padding: 6px 8px;
                    }
                    QTableWidget::item:selected {
                        background-color: rgba(247, 146, 30, 0.22);
                        color: #e0e0e0;
                    }
                    QHeaderView::section {
                        background-color: #1e1e1e;
                        color: #e0e0e0;
                        border: none;
                        padding: 6px 8px;
                    }
                    QTableWidget::viewport {
                        background-color: #1e1e1e;
                    }
                """
            )

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        top_layout = QHBoxLayout()
        label = QLabel(t("notifications.changes_found", count=len(changes)))
        text_color = "#e0e0e0" if is_dark else "#000000"
        label.setStyleSheet(f"font-weight: bold; font-size: 12px; padding: 4px; color: {text_color};")
        top_layout.addWidget(label)
        top_layout.addStretch()

        search_box = QLineEdit()
        search_box.setPlaceholderText(t("notifications.search_placeholder"))
        search_box.setMaximumWidth(200)
        bg_color = "#1e1e1e" if is_dark else "white"
        border_color = "#505050" if is_dark else "#dcdcdc"
        text_color2 = "#e0e0e0" if is_dark else "#222"
        search_box.setStyleSheet(
            f"""
                QLineEdit {{
                    padding: 6px 12px;
                    border: 1px solid {border_color};
                    border-radius: 14px;
                    background: {bg_color};
                    color: {text_color2};
                }}
            """
        )
        top_layout.addWidget(search_box)
        layout.addLayout(top_layout)

        path_label = QLabel(t("notifications.folder_path", path=display_path or folder_path or "—"))
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        path_muted = "#a0a0a0" if is_dark else "#555555"
        path_label.setStyleSheet(f"font-size: 11px; padding: 0 4px 4px 4px; color: {path_muted};")
        path_label.setToolTip(display_path or folder_path or "")
        layout.addWidget(path_label)

        table = QTableWidget()
        table.setObjectName("changesTable")
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels([t("notifications.operation"), t("notifications.type"), t("notifications.name")])
        table.setRowCount(len(changes))
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setAlternatingRowColors(False)
        table.verticalHeader().setVisible(False)
        table.setSortingEnabled(True)
        table.setShowGrid(False)
        table.setContextMenuPolicy(Qt.CustomContextMenu)

        header = table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setContextMenuPolicy(Qt.CustomContextMenu)

        table.setMouseTracking(True)
        table._hover_row = -1
        table._pressed_row = -1

        class UnifiedRowDelegate(QStyledItemDelegate):
            def paint(self, painter, option, index):
                view = option.widget
                row = index.row()
                col = index.column()

                opt = QStyleOptionViewItem(option)
                opt.state &= ~QStyle.State_HasFocus
                opt.state &= ~QStyle.State_Selected
                opt.state &= ~QStyle.State_MouseOver

                is_selected = bool(option.state & QStyle.State_Selected)
                hover_row = getattr(view, "_hover_row", -1)
                pressed_row = getattr(view, "_pressed_row", -1)
                is_hovered = row == hover_row
                is_pressed = row == pressed_row

                is_dark2 = _is_dark_mode()

                if is_dark2:
                    hover_color = QColor(247, 146, 30, int(255 * 0.15))
                    selected_color = QColor(247, 146, 30, int(255 * 0.22))
                    pressed_color = QColor(247, 146, 30, int(255 * 0.28))
                    tcol = QColor("#e0e0e0")
                else:
                    hover_color = QColor("#FFE3C2")
                    selected_color = QColor("#FFC37A")
                    pressed_color = QColor("#FFCA91")
                    tcol = QColor("#000000")

                bg = None
                if is_selected:
                    bg = selected_color
                elif is_pressed:
                    bg = pressed_color
                elif is_hovered and not is_selected:
                    bg = hover_color

                if bg is not None:
                    painter.save()
                    painter.setRenderHint(QPainter.Antialiasing, True)
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QBrush(bg))

                    if col == 0:
                        rect = QRectF(option.rect)
                        path = QPainterPath()
                        path.moveTo(rect.left() + 8, rect.top())
                        path.lineTo(rect.right(), rect.top())
                        path.lineTo(rect.right(), rect.bottom())
                        path.lineTo(rect.left() + 8, rect.bottom())
                        path.arcTo(rect.left(), rect.bottom() - 16, 16, 16, 270, -90)
                        path.lineTo(rect.left(), rect.top() + 8)
                        path.arcTo(rect.left(), rect.top(), 16, 16, 180, -90)
                        path.closeSubpath()
                        painter.drawPath(path)
                    elif col == view.columnCount() - 1:
                        rect = QRectF(option.rect)
                        path = QPainterPath()
                        path.moveTo(rect.left(), rect.top())
                        path.lineTo(rect.right() - 8, rect.top())
                        path.arcTo(rect.right() - 16, rect.top(), 16, 16, 90, -90)
                        path.lineTo(rect.right(), rect.bottom() - 8)
                        path.arcTo(rect.right() - 16, rect.bottom() - 16, 16, 16, 0, -90)
                        path.lineTo(rect.left(), rect.bottom())
                        path.closeSubpath()
                        painter.drawPath(path)
                    else:
                        painter.drawRect(option.rect)

                    painter.restore()

                if bg is not None:
                    for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
                        opt.palette.setColor(group, QPalette.Text, tcol)
                        opt.palette.setColor(group, QPalette.HighlightedText, tcol)
                        opt.palette.setColor(group, QPalette.WindowText, tcol)

                super().paint(painter, opt, index)

        # IMPORTANT: keep strong refs to Python delegates/filters.
        # If a Python QObject used by Qt (delegate/eventFilter) gets GC'ed while
        # Qt still calls into it, PySide can crash with an access violation.
        delegate = UnifiedRowDelegate(table)
        table._unified_row_delegate = delegate
        table.setItemDelegate(delegate)

        class TableEventFilter(QObject):
            def eventFilter(self, obj, event):
                if obj != table.viewport():
                    return False
                t = event.type()
                if t == QEvent.MouseButtonPress:
                    idx = table.indexAt(event.pos())
                    if idx.isValid():
                        table._pressed_row = idx.row()
                        table.viewport().update()
                    return False
                if t == QEvent.MouseButtonRelease:
                    if getattr(table, "_pressed_row", -1) != -1:
                        table._pressed_row = -1
                        table.viewport().update()
                    return False
                return False

        event_filter = TableEventFilter(table)
        table._unified_row_event_filter = event_filter
        table.viewport().installEventFilter(event_filter)

        # Style is preserved from original
        if is_dark:
            table.setStyleSheet(
                """
                    QTableWidget {
                        border: 1px solid #505050;
                        border-radius:4px;
                        background-color: #1e1e1e;
                        gridline-color: transparent;
                    }
                    QTableWidget::item {
                        padding: 6px 8px;
                        border: none;
                        background: transparent;
                        color: #e0e0e0;
                    }
                    QTableWidget::item:selected {
                        background: transparent;
                        color: #e0e0e0;
                    }
                    QHeaderView::section {
                        background-color: #1e1e1e;
                        padding: 8px;
                        border: none;
                        font-weight: 600;
                        font-size: 12px;
                        text-align: left;
                        color: #e0e0e0;
                    }
                    QHeaderView::section:hover {
                        background-color: rgba(247, 146, 30, 0.15);
                    }
                """
            )
        else:
            table.setStyleSheet(
                """
                    QTableWidget {
                        border: 1px solid #dcdcdc;
                        border-radius:4px;
                        background-color: white;
                        gridline-color: transparent;
                    }
                    QTableWidget::item {
                        padding: 6px 8px;
                        border: none;
                        background: transparent;
                    }
                    QTableWidget::item:selected {
                        background: transparent;
                        color: #000000;
                    }
                    QHeaderView::section {
                        background-color: transparent;
                        padding: 8px;
                        border: none;
                        font-weight: 600;
                        font-size: 12px;
                        text-align: left;
                    }
                    QHeaderView::section:hover {
                        background-color: #FFE3C2;
                    }
                """
            )

        for row, change in enumerate(changes):
            op_type = change["type"]
            file_data = change["file"]

            op_item = QTableWidgetItem()
            if op_type == "new":
                op_item.setIcon(themed_icon(CUSTOM_PLUS_ICON_PATH))
                op_item.setText(t("notifications.op_new"))
            elif op_type == "modified":
                op_item.setIcon(themed_icon(EDIT_ICON_PATH))
                op_item.setText(t("notifications.op_version_update") if change.get("version_update") else t("notifications.op_modified"))
            elif op_type == "renamed":
                op_item.setIcon(themed_icon(EDIT_ICON_PATH))
                op_item.setText(t("notifications.op_renamed"))
            elif op_type == "deleted":
                op_item.setIcon(themed_icon(DELETE_ICON_PATH))
                op_item.setText(t("notifications.op_deleted"))
            op_item.setFlags(op_item.flags() & ~Qt.ItemIsEditable)

            type_item = QTableWidgetItem()
            item_type = file_data.get("type", "file")
            if item_type == "folder":
                type_item.setIcon(themed_icon(CUSTOM_FOLDER_ICON_PATH))
                type_item.setText(t("common.folder"))
            else:
                file_name = file_data.get("name", "")
                temp_item = {"name": file_name, "type": "file"}
                try:
                    if hasattr(self, "icon_prov") and self.icon_prov:
                        icon = self.icon_prov.get_icon(temp_item)
                    else:
                        temp_prov = IconProvider(QApplication.style())
                        icon = temp_prov.get_icon(temp_item)
                except Exception:
                    icon = QApplication.style().standardIcon(QStyle.SP_FileIcon)
                type_item.setIcon(icon)
                type_item.setText(t("common.file"))
            type_item.setFlags(type_item.flags() & ~Qt.ItemIsEditable)

            name_item = QTableWidgetItem()
            file_name = file_data.get("name", t("common.unknown"))
            if op_type == "renamed" and "old_name" in change:
                name_item.setText(f"{change['old_name']} → {file_name}")
            else:
                name_item.setText(file_name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            name_item.setData(Qt.UserRole, change)

            table.setItem(row, 0, op_item)
            table.setItem(row, 1, type_item)
            table.setItem(row, 2, name_item)

        header.setStretchLastSection(True)
        header.setMinimumSectionSize(48)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)

        def on_cell_entered(row, col):
            try:
                table._hover_row = row
            except Exception:
                pass
            table.viewport().update()

        def on_leave():
            try:
                table._hover_row = -1
            except Exception:
                pass
            table.viewport().update()

        table.cellEntered.connect(on_cell_entered)
        original_leave_event = table.leaveEvent

        def leave_event_wrapper(event):
            on_leave()
            if original_leave_event:
                original_leave_event(event)

        table.leaveEvent = leave_event_wrapper

        active_filter = {"column": -1, "value": ""}

        def update_header_icon():
            for col in range(table.columnCount()):
                header_item = table.horizontalHeaderItem(col)
                if header_item:
                    if col == active_filter["column"]:
                        header_item.setIcon(themed_icon(FILTER_ICON_PATH))
                    else:
                        header_item.setIcon(QIcon())

        def search_by_name(text):
            search_text = text.lower()
            is_filtering = bool(text.strip())
            for r in range(table.rowCount()):
                name_item = table.item(r, 2)
                if name_item:
                    should_show = search_text in name_item.text().lower()
                    table.setRowHidden(r, not should_show)

            if is_filtering:
                active_filter["column"] = 2
                active_filter["value"] = text
            elif active_filter["column"] == 2:
                active_filter["column"] = -1
                active_filter["value"] = ""
            update_header_icon()

        search_box.textChanged.connect(search_by_name)

        def go_to_file():
            """Open the notified folder in the tree (does not mark notifications as read)."""
            ok = _navigate_to_folder(
                self,
                workspace_id,
                project_id,
                folder_id,
                display_path or folder_path,
            )
            if ok:
                try:
                    dialog.hide()
                except Exception:
                    pass

        def copy_folder_path():
            text = display_path or folder_path or ""
            if not text:
                return
            try:
                QGuiApplication.clipboard().setText(text)
            except Exception:
                pass

        def on_double_click(_item):
            go_to_file()

        table.itemDoubleClicked.connect(on_double_click)

        def show_table_context_menu(pos):
            menu = QMenu(table)
            menu.setObjectName("changesTableMenu")
            act_go = menu.addAction(t("notifications.go_to_file"))
            act_go.triggered.connect(go_to_file)
            act_copy = menu.addAction(t("notifications.copy_folder_path"))
            act_copy.triggered.connect(copy_folder_path)
            menu.exec_(table.viewport().mapToGlobal(pos))

        table.customContextMenuRequested.connect(show_table_context_menu)

        def show_header_context_menu(pos):
            col = header.logicalIndexAt(pos)
            if col < 0:
                return
            menu = QMenu(table)
            menu.setObjectName("changesHeaderMenu")
            values = set()
            for r in range(table.rowCount()):
                item = table.item(r, col)
                if item:
                    text = item.text()
                    if text and text.strip():
                        values.add(text)

            def filter_by_column(c, text):
                search_box.clear()
                active_filter["column"] = c
                active_filter["value"] = text
                for r in range(table.rowCount()):
                    item = table.item(r, c)
                    if item:
                        table.setRowHidden(r, item.text() != text)
                update_header_icon()

            for value in sorted(values):
                action = menu.addAction(t("notifications.show_only", value=value))
                action.triggered.connect(lambda _=False, c=col, v=value: filter_by_column(c, v))

            if values:
                menu.addSeparator()

            def reset_filter():
                search_box.clear()
                active_filter["column"] = -1
                active_filter["value"] = ""
                for r in range(table.rowCount()):
                    table.setRowHidden(r, False)
                update_header_icon()

            act_reset = menu.addAction(t("notifications.show_all"))
            act_reset.triggered.connect(reset_filter)
            menu.exec_(header.mapToGlobal(pos))

        header.customContextMenuRequested.connect(show_header_context_menu)
        layout.addWidget(table, 1)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_go_file = btn_box.addButton(t("notifications.go_to_file"), QDialogButtonBox.ActionRole)
        btn_go_file.clicked.connect(go_to_file)
        btn_box.accepted.connect(dialog.accept)
        btn_box.rejected.connect(dialog.reject)
        layout.addWidget(btn_box)

        # IMPORTANT: Use non-blocking dialog (open/show) instead of exec_()
        # to avoid nested event loop which can cause access violation crashes
        def _on_dialog_finished(code: int):
            try:
                from larix_nexus.utils.ui_trace import trace as ui_trace
                if ui_trace:
                    ui_trace("notification._on_dialog_finished: code={}", int(code))
            except Exception:
                pass

            try:
                btn_box.accepted.disconnect()
                btn_box.rejected.disconnect()
                dialog.finished.disconnect(_on_dialog_finished)
            except Exception:
                pass

        if int(code) == int(QDialog.Accepted):
            self._acknowledge_pending_notifications([folder_id])
            _sync_notify_tree_badges(self, project_id)
            self._update_global_notification_badge()

            # CRITICAL: Do NOT call setParent(None) - it breaks Qt's object tree
            # and causes access violations when deleteLater() runs.
            # Just call deleteLater() and let Qt handle cleanup properly.
            try:
                dialog.deleteLater()
            except Exception:
                pass

        dialog.finished.connect(_on_dialog_finished)
        dialog.open()

    except Exception as e:
        QMessageBox.warning(self, t("common.error"), t("notifications.show_changes_error", error=e))


def _navigate_to_file(self, project_id: int | str, folder_id: int | str, file_id: int | str, file_name: str):
    try:
        current_pid = self.current_project_id()
        if normalize_project_id(current_pid) != normalize_project_id(project_id):
            for i in range(self.cb_projects.count()):
                p = self.cb_projects.itemData(i)
                if isinstance(p, dict) and normalize_project_id(p.get("id")) == normalize_project_id(project_id):
                    self.cb_projects.setCurrentIndex(i)
                    QApplication.processEvents()
                    break

        folder_item = self.get_folder_tree_item(folder_id)
        if not folder_item:
            QMessageBox.warning(self, t("notifications.navigation"), t("notifications.folder_not_found", file=file_name))
            return

        self.tree.setCurrentItem(folder_item)
        folder_node = folder_item.data(0, Qt.UserRole)
        if folder_node:
            self.open_folder_node(folder_node)
            QApplication.processEvents()

        model = self.table.model()
        rows = model.rowCount() if model else 0
        found = False
        for row in range(rows):
            try:
                if not model:
                    break
                index = model.index(row, 0)
                item_data = model.data(index, Qt.UserRole)
                if not isinstance(item_data, dict):
                    continue
                item_id = item_data.get("id")
                item_name = item_data.get("name") or item_data.get("originalName") or ""
                if (item_id and item_id == file_id) or (item_name.lower() == file_name.lower()):
                    self.table.selectRow(row)
                    self.table.scrollTo(index, QAbstractItemView.PositionAtCenter)
                    found = True
                    break
            except Exception:
                continue

        if not found:
            QMessageBox.information(
                self,
                t("navigation.title"),
                t("navigation.file_not_found", file=file_name),
            )
    except Exception as e:
        QMessageBox.warning(self, t("navigation.title"), t("navigation.error", error=e))


def _update_notify_icon(self) -> None:
    try:
        has_pending = False
        try:
            has_pending = bool(getattr(self, "_pending_notifications", {}))
        except Exception:
            has_pending = False
        try:
            if not has_pending and any(bool(v.get("pending")) for v in getattr(self, "_subscriptions", {}).values()):
                has_pending = True
        except Exception:
            pass
        if not has_pending:
            has_pending = bool(getattr(self, "_notifications", []))
        path = ALARM1_ICON_PATH if has_pending else ALARM_ICON_PATH
        try:
            self.btn_notify.setIcon(self._themed_icon(path))
        except Exception:
            self.btn_notify.setIcon(QIcon(path))
    except Exception:
        pass


def _toast_changes(self, folder_path: str, changes: list) -> None:
    """Show an OS-level notification (system tray) if available."""
    try:
        from PySide6.QtWidgets import QSystemTrayIcon
    except Exception:
        return

    try:
        tray = getattr(self, "_notify_tray", None)
        if tray is None:
            return
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        cnt = len(changes) if isinstance(changes, list) else 0
        if cnt <= 0:
            return
        lines = []
        if isinstance(changes, list):
            for ch in changes[:3]:
                try:
                    ctype = str((ch or {}).get("type") or "")
                    fname = str(((ch or {}).get("file") or {}).get("name") or "")
                    if fname:
                        lines.append(f"{ctype}: {fname}")
                except Exception:
                    continue
        msg = f"{folder_path}: {cnt} изменений"
        if lines:
            msg = msg + "\n" + "\n".join(lines)
        tray.showMessage(APP_TITLE, msg, QSystemTrayIcon.Information, 8000)
    except Exception:
        return


def _acknowledge_pending_notifications(self, folder_ids=None) -> bool:
    """Refresh baselines before marking pending notification changes read."""
    pending = getattr(self, "_pending_notifications", {}) or {}
    wanted = None if folder_ids is None else {normalize_id(fid) for fid in folder_ids}
    selected = []
    for key, data in pending.items():
        folder_id = normalize_id(data.get("folder_id") or key)
        if wanted is None or folder_id in wanted or normalize_id(key) in wanted:
            selected.append((key, data))

    refreshed = {}
    try:
        for key, data in selected:
            project_id = data.get("project_id")
            folder_id = data.get("folder_id") or key
            folder_path = data.get("folder_path", "")
            workspace_id = data.get("workspace_id")
            files = self._build_notification_file_state(
                project_id,
                folder_id,
                folder_path,
                force_fresh=True,
                strict=True,
            )
            if not save_folder_notification(
                project_id,
                folder_id,
                folder_path,
                files,
                workspace_id=workspace_id,
            ):
                raise RuntimeError("Unable to persist notification baseline")
            refreshed[key] = True
    except Exception as exc:
        try:
            self.status.showMessage(
                t("notifications.refresh_error", error=str(exc)),
                5000,
            )
        except Exception:
            pass
        return False

    for key in refreshed:
        pending.pop(key, None)
    save_pending_notifications(pending)
    self._pending_notifications = pending
    try:
        self._update_notify_icon()
        self._build_notify_menu()
        _sync_notify_tree_badges(self)
        self._update_global_notification_badge()
    except Exception:
        pass
    return True


def _build_notify_menu(self) -> None:
    try:
        self.menu_notify.clear()
        try:
            _pending = getattr(self, "_pending_notifications", {}) or {}
        except Exception:
            _pending = {}
        if _pending:
            try:
                for folder_id, notif in list(_pending.items()):
                    try:
                        folder_path = str((notif or {}).get("folder_path", ""))
                        display_path = _folder_tree_path(self, folder_id, folder_path) or folder_path
                        changes = (notif or {}).get("changes", [])
                        cnt = len(changes) if isinstance(changes, (list, tuple)) else 0
                        act = self.menu_notify.addAction(f"{display_path} ({cnt})")
                        act.setData(folder_id)
                        act.triggered.connect(lambda _=False, fid=folder_id: self._show_changes_dialog(fid))
                    except Exception:
                        pass
            except Exception:
                pass
            self.menu_notify.addSeparator()
            act_clear2 = self.menu_notify.addAction(t("notifications.clear"))

            def _clear2():
                self._acknowledge_pending_notifications()

            act_clear2.triggered.connect(_clear2)
            _append_unsubscribe_all_menu_item(self)
            return

        if not self._notifications:
            act = self.menu_notify.addAction(t("notifications.no_notifications"))
            act.setEnabled(False)
        else:
            for note in list(self._notifications)[-20:][::-1]:
                title = str(note.get("title") or "")
                path = str(note.get("path") or "")
                text = str(note.get("text") or "")
                act = self.menu_notify.addAction(f"{title}: {text}")
                if path:
                    act.triggered.connect(lambda _=False, p=path: self._open_path_in_os(p))

        self.menu_notify.addSeparator()
        act_clear = self.menu_notify.addAction(t("notifications.clear"))

        def _clear():
            try:
                if not self._acknowledge_pending_notifications():
                    return
                self._notifications.clear()
                for v in self._subscriptions.values():
                    v["pending"] = False
                self._update_notify_icon()
                self._build_notify_menu()
                _sync_notify_tree_badges(self)
            except Exception:
                pass

        act_clear.triggered.connect(_clear)
        _append_unsubscribe_all_menu_item(self)
    except Exception:
        pass


def _open_path_in_os(self, p: str) -> None:
    try:
        open_in_os(p)
    except Exception:
        pass


def inject_notification_handlers_to_main_window(MainWindowClass) -> None:
    MainWindowClass.toggle_folder_notifications = toggle_folder_notifications
    MainWindowClass._current_workspace_id = _current_workspace_id
    MainWindowClass._switch_workspace_for_navigation = _switch_workspace_for_navigation
    MainWindowClass._select_project_for_navigation = _select_project_for_navigation
    MainWindowClass._sync_notify_tree_badges = _sync_notify_tree_badges
    MainWindowClass._check_notifications = _check_notifications
    MainWindowClass._update_global_notification_badge = _update_global_notification_badge
    MainWindowClass._show_notifications_menu = _show_notifications_menu
    MainWindowClass._acknowledge_pending_notifications = _acknowledge_pending_notifications
    MainWindowClass._show_changes_dialog = _show_changes_dialog
    MainWindowClass._navigate_to_file = _navigate_to_file
    MainWindowClass._navigate_to_folder = _navigate_to_folder
    MainWindowClass._folder_tree_path = _folder_tree_path
    MainWindowClass._update_notify_icon = _update_notify_icon
    MainWindowClass._toast_changes = _toast_changes
    MainWindowClass._build_notify_menu = _build_notify_menu
    MainWindowClass._confirm_unsubscribe_all_notifications = _confirm_unsubscribe_all_notifications
    MainWindowClass._on_unsubscribe_all_notifications = _on_unsubscribe_all_notifications
    MainWindowClass._open_path_in_os = _open_path_in_os
