# -*- coding: utf-8 -*-
"""Drag & drop helpers.

Supports moving items from the files table to a folder in the tree by dragging
with LMB and dropping onto the destination folder.
"""

from __future__ import annotations

import json

from PySide6.QtCore import QObject, Qt


MIME_ITEMS = "application/x-larix-nexus-items"


class TreeDropFilter(QObject):
    def __init__(self, owner):
        super().__init__(owner)
        self._w = owner

    def eventFilter(self, obj, ev):
        try:
            t = ev.type()
        except Exception:
            return False

        try:
            from PySide6.QtCore import QEvent
        except Exception:
            return False

        if t == QEvent.DragEnter or t == QEvent.DragMove:
            try:
                md = ev.mimeData()
                if md and md.hasFormat(MIME_ITEMS):
                    ev.acceptProposedAction()
                    return True
            except Exception:
                return False
            return False

        if t == QEvent.Drop:
            try:
                md = ev.mimeData()
                if not md or not md.hasFormat(MIME_ITEMS):
                    return False

                raw = md.data(MIME_ITEMS)
                data = {}
                try:
                    data = json.loads(bytes(raw).decode("utf-8", errors="replace"))
                except Exception:
                    data = {}

                items = data.get("items") or []
                if not isinstance(items, list) or not items:
                    return False

                tree = getattr(self._w, "tree", None)
                if tree is None:
                    return False

                # Determine destination folder from cursor
                pos = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
                dst_item = tree.itemAt(pos)
                dest_folder_id = None
                if dst_item is not None:
                    try:
                        dest_folder_id = dst_item.data(0, Qt.UserRole + 1)
                    except Exception:
                        dest_folder_id = None
                    if not dest_folder_id:
                        try:
                            node = dst_item.data(0, Qt.UserRole)
                            if isinstance(node, dict):
                                dest_folder_id = node.get("id")
                        except Exception:
                            dest_folder_id = None

                if not dest_folder_id:
                    try:
                        dest_folder_id = self._w.current_project_id()
                    except Exception:
                        dest_folder_id = None

                project_id = None
                try:
                    project_id = self._w.current_project_id()
                except Exception:
                    project_id = None

                # Normalize items to dicts compatible with _do_move
                norm = []
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    norm.append(
                        {
                            "id": it.get("id"),
                            "type": it.get("type"),
                            "name": it.get("name") or "",
                            "title": it.get("name") or "",
                            "folderId": it.get("folderId"),
                            "projectId": it.get("projectId"),
                        }
                    )

                if not norm:
                    return False

                # Execute move without dialog
                try:
                    self._w._do_move(norm, {"id": dest_folder_id, "path": ""}, project_id)
                except Exception:
                    try:
                        fn = getattr(self._w, "move_selected_action", None)
                        if callable(fn):
                            fn()
                    except Exception:
                        pass

                ev.acceptProposedAction()
                return True
            except Exception:
                return False

        return False


class TableDropFilter(QObject):
    """Handle dropping app items onto folder rows in the files table."""

    def __init__(self, owner):
        super().__init__(owner)
        self._w = owner

    def eventFilter(self, obj, ev):
        try:
            from PySide6.QtCore import QEvent
        except Exception:
            return False

        try:
            t = ev.type()
        except Exception:
            return False

        if t == QEvent.DragEnter or t == QEvent.DragMove:
            try:
                md = ev.mimeData()
                if md and md.hasFormat(MIME_ITEMS):
                    ev.acceptProposedAction()
                    return True
            except Exception:
                return False
            return False

        if t == QEvent.Drop:
            try:
                md = ev.mimeData()
                if not md or not md.hasFormat(MIME_ITEMS):
                    return False

                raw = md.data(MIME_ITEMS)
                data = {}
                try:
                    data = json.loads(bytes(raw).decode("utf-8", errors="replace"))
                except Exception:
                    data = {}

                items = data.get("items") or []
                if not isinstance(items, list) or not items:
                    return False

                table = getattr(self._w, "table", None)
                if table is None:
                    return False

                pos = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
                idx = table.indexAt(pos)

                dest_folder_id = None
                if idx.isValid():
                    try:
                        src_idx = self._w.proxy.mapToSource(idx) if hasattr(self._w, "proxy") else idx
                        row = src_idx.row()
                        it = self._w.files_model.item_at(row)
                        if isinstance(it, dict):
                            if (it.get("type") or "").lower() in ("folder", "dir", "directory", "папка"):
                                dest_folder_id = it.get("id")
                    except Exception:
                        dest_folder_id = None

                if not dest_folder_id:
                    # Fallback: current folder in tree
                    try:
                        cur = self._w.tree.currentItem() if getattr(self._w, "tree", None) is not None else None
                        if cur is not None:
                            dest_folder_id = cur.data(0, Qt.UserRole + 1)
                    except Exception:
                        dest_folder_id = None

                if not dest_folder_id:
                    try:
                        dest_folder_id = self._w.current_project_id()
                    except Exception:
                        dest_folder_id = None

                project_id = None
                try:
                    project_id = self._w.current_project_id()
                except Exception:
                    project_id = None

                norm = []
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    norm.append(
                        {
                            "id": it.get("id"),
                            "type": it.get("type"),
                            "name": it.get("name") or "",
                            "title": it.get("name") or "",
                            "folderId": it.get("folderId"),
                            "projectId": it.get("projectId"),
                        }
                    )

                if not norm:
                    return False

                try:
                    self._w._do_move(norm, {"id": dest_folder_id, "path": ""}, project_id)
                except Exception:
                    pass

                ev.acceptProposedAction()
                return True
            except Exception:
                return False

        return False
