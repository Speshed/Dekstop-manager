# -*- coding: utf-8 -*-
"""Drag & drop helpers.

Supports moving items from the files table to a folder in the tree by dragging
with LMB and dropping onto the destination folder.
"""

from __future__ import annotations

import json

from PySide6.QtCore import QObject, Qt, QPoint, QSize, QRectF
from PySide6.QtGui import QPixmap, QPainter, QColor, QPen, QDrag
from PySide6.QtWidgets import QTableView


MIME_ITEMS = "application/x-larix-nexus-items"


class DragEventFilter(QObject):
    """Event filter for handling mouse drag on table viewport."""
    
    def __init__(self, table, main_window):
        super().__init__(table)
        self._table = table
        self._main_window = main_window
        self._drag_start_pos = QPoint()
        self._is_dragging = False
        
    def eventFilter(self, obj, event):
        ev_type = event.type()
        
        # Mouse press - store start position
        if ev_type == 2:  # QEvent.MouseButtonPress
            if event.button() == Qt.LeftButton:
                self._drag_start_pos = event.pos()
                # Check if click was on checkbox column
                idx = self._table.indexAt(event.pos())
                if idx.isValid() and idx.column() == 0:
                    self._drag_start_pos = QPoint()  # Don't start drag from checkbox
            return False
            
        # Mouse move - check for drag
        elif ev_type == 5:  # QEvent.MouseMove
            if not (event.buttons() & Qt.LeftButton):
                return False
                
            if self._drag_start_pos.isNull() or self._is_dragging:
                return False
                
            dist = (event.pos() - self._drag_start_pos).manhattanLength()
            if dist >= 10:
                self._is_dragging = True
                self._start_drag()
                return True
            return False
            
        # Mouse release - reset
        elif ev_type == 3:  # QEvent.MouseButtonRelease
            if event.button() == Qt.LeftButton:
                self._drag_start_pos = QPoint()
                self._is_dragging = False
            return False
            
        return False
        
    def _start_drag(self):
        """Start drag operation with selected/checked items."""
        try:
            # Get checked items
            checked = []
            model = self._table.model()
            
            if model:
                src_model = model.sourceModel() if hasattr(model, 'sourceModel') else model
                checked_set = getattr(src_model, 'checked', set())
                if checked_set and hasattr(src_model, '_data'):
                    for row, item in enumerate(src_model._data):
                        if hasattr(src_model, '_cb_key'):
                            key = src_model._cb_key(item)
                            if key in checked_set:
                                checked.append(row)
            
            # Use checked or selected
            if checked:
                rows = checked
            else:
                sel = self._table.selectionModel().selectedRows()
                rows = [idx.row() for idx in sel]
                
            if not rows:
                self._is_dragging = False
                return
                
            # Create drag
            drag = QDrag(self._table)
            
            # Create mime data
            indices = []
            for row in rows:
                try:
                    pidx = model.index(row, 0)
                    if pidx.isValid():
                        sidx = model.mapToSource(pidx) if hasattr(model, 'mapToSource') else pidx
                        if sidx.isValid():
                            indices.append(sidx)
                except:
                    continue
                    
            src = model.sourceModel() if hasattr(model, 'sourceModel') else model
            mime = src.mimeData(indices) if indices else None
            if not mime:
                self._is_dragging = False
                return
                
            drag.setMimeData(mime)
            
            # Create preview pixmap
            pixmap = self._create_preview(rows)
            drag.setPixmap(pixmap)
            drag.setHotSpot(QPoint(pixmap.width() // 2, 20))
            
            # Execute
            drag.exec_(Qt.MoveAction | Qt.CopyAction)
            
        except Exception as e:
            print(f"[DragEventFilter] Error: {e}")
        finally:
            self._is_dragging = False
            self._drag_start_pos = QPoint()
            
    def _create_preview(self, rows):
        """Create drag preview pixmap."""
        count = len(rows)
        max_show = 5
        show = min(count, max_show)
        
        row_h = 36
        pad = 8
        w = 220
        h = pad * 2 + show * row_h + (20 if count > max_show else 0)
        
        pm = QPixmap(w, h)
        pm.fill(Qt.transparent)
        
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        
        # Orange background
        bg = QColor(247, 146, 30, 230)
        border = QColor(247, 146, 30, 255)
        
        p.setPen(QPen(border, 2))
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(0, 0, w, h), 8, 8)
        
        # Draw items
        p.setPen(QColor(0, 0, 0))
        font = p.font()
        font.setPointSize(9)
        p.setFont(font)
        
        model = self._table.model()
        src = model.sourceModel() if hasattr(model, 'sourceModel') else model
        
        for i, row in enumerate(rows[:max_show]):
            y = pad + i * row_h
            if hasattr(src, '_data') and row < len(src._data):
                item = src._data[row]
                name = item.get('originalName') or item.get('name') or 'File'
                # Truncate if too long
                metrics = p.fontMetrics()
                text = metrics.elidedText(name, Qt.ElideRight, w - 20)
                p.drawText(10, y + 24, text)
            
        if count > max_show:
            p.drawText(10, h - 15, f"+ {count - max_show} ещё")
            
        p.end()
        return pm


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
