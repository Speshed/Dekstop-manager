# -*- coding: utf-8 -*-
"""Drag & drop helpers.

Supports moving items from files table to a folder in the tree by dragging
with LMB and dropping onto the destination folder.
"""

from __future__ import annotations

import json

from PySide6.QtCore import QObject, Qt, QPoint, QSize, QRectF, QModelIndex
from PySide6.QtGui import QPixmap, QPainter, QColor, QPen, QDrag
from PySide6.QtWidgets import QTableView
from larix_nexus.constants import DRAG_FILE_ICON_PATH

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
        """Create drag preview pixmap with single file icon (no text), softer border."""
        print(f"[_create_preview] Called with {len(rows)} rows")
        
        count = len(rows)
        
        icon_size = 32
        pad = 10
        w = pad * 2 + icon_size
        h = pad * 2 + icon_size
        
        pm = QPixmap(w, h)
        pm.fill(Qt.transparent)
        
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        
        # Softer background with shadow
        bg = QColor(247, 146, 30, 200)
        border = QColor(219, 122, 10, 150)
        shadow = QColor(0, 0, 0, 40)
        
        # Draw shadow
        p.setPen(Qt.NoPen)
        p.setBrush(shadow)
        p.drawRoundedRect(QRectF(2, 2, w, h), 8, 8)
        
        # Draw main background
        p.setPen(QPen(border, 1))
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(0, 0, w, h), 8, 8)
        
        # Load single file icon
        try:
            pm_icon = QPixmap(DRAG_FILE_ICON_PATH)
            if not pm_icon.isNull():
                pm_icon = pm_icon.scaled(icon_size, icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                # Draw with subtle shadow
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(0, 0, 0, 30))
                p.drawRoundedRect(QRectF(pad + 2, pad + 2, icon_size, icon_size), 4, 4)
                # Draw icon centered
                x = pad + (icon_size - pm_icon.width()) // 2
                y = pad + (icon_size - pm_icon.height()) // 2
                p.drawPixmap(x, y, pm_icon)
            else:
                print(f"[_create_preview] Failed to load icon from {DRAG_FILE_ICON_PATH}")
        except Exception as e:
            print(f"[_create_preview] Error loading file icon: {e}")
        
        # Draw count badge if multiple files
        if count > 1:
            badge_size = 20
            badge_x = w - badge_size - 4
            badge_y = 4
            
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 180))
            p.drawRoundedRect(QRectF(badge_x, badge_y, badge_size, badge_size), 10, 10)
            
            p.setPen(QColor(255, 255, 255))
            font = p.font()
            font.setBold(True)
            font.setPointSize(10)
            p.setFont(font)
            p.drawText(QRectF(badge_x, badge_y, badge_size, badge_size), Qt.AlignCenter, str(count))
            
        p.end()
        
        print(f"[_create_preview] Created pixmap: {w}x{h} for {count} file(s)")
        return pm


class TreeDropFilter(QObject):
    def __init__(self, owner):
        super().__init__(owner)
        self._w = owner
        self._hovered_item = None

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
                    tree = getattr(self._w, "tree", None)
                    if tree:
                        pos = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
                        item = tree.itemAt(pos)
                        
                        if item is not None:
                            if self._hovered_item is None or item != self._hovered_item:
                                self._set_hovered_item(item, tree)
                        elif self._hovered_item is not None:
                            self._clear_hovered_item(tree)
                    
                    ev.acceptProposedAction()
                    return True
            except Exception:
                return False
            return False

        if t == QEvent.DragLeave:
            tree = getattr(self._w, "tree", None)
            if tree and self._hovered_item is not None:
                self._clear_hovered_item(tree)
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

                # Determine drop action: Move (default) or Copy (Ctrl held)
                # Check keyboard modifiers - Ctrl = Copy, otherwise Move
                modifiers = ev.modifiers()
                use_copy = bool(modifiers & Qt.ControlModifier)
                
                # Also check dropAction returned from drag.exec_()
                drop_action = ev.dropAction()
                if drop_action == Qt.CopyAction:
                    use_copy = True
                elif drop_action == Qt.MoveAction:
                    use_copy = False

                # Normalize items to dicts compatible with _do_move/_do_copy
                norm = []
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    norm.append(
                        {
                            "id": it.get("id"),
                            "type": it.get("type"),
                            "name": it.get("name") or it.get("fileName") or it.get("originalName") or "",
                            "fileName": it.get("fileName") or "",
                            "originalName": it.get("originalName") or "",
                            "title": it.get("name") or it.get("fileName") or it.get("originalName") or "",
                            "folderId": it.get("folderId"),
                            "projectId": it.get("projectId"),
                        }
                    )

                if not norm:
                    return False

                result = {"id": dest_folder_id, "path": ""}
                
                try:
                    if use_copy:
                        # Copy operation
                        fn = getattr(self._w, "_do_copy", None)
                        if callable(fn):
                            fn(norm, result)
                        else:
                            # Fallback to move_selected_action
                            fn = getattr(self._w, "copy_selected_action", None)
                            if callable(fn):
                                fn()
                    else:
                        # Move operation (default)
                        fn = getattr(self._w, "_do_move", None)
                        if callable(fn):
                            fn(norm, result, project_id)
                        else:
                            # Fallback to move_selected_action
                            fn = getattr(self._w, "move_selected_action", None)
                            if callable(fn):
                                fn()
                except Exception:
                    pass

                # Set the drop action that was actually performed
                if use_copy:
                    ev.setDropAction(Qt.CopyAction)
                else:
                    ev.setDropAction(Qt.MoveAction)
                ev.accept()
                
                if tree and self._hovered_item is not None:
                    self._clear_hovered_item(tree)
                
                return True
            except Exception:
                return False

        return False

    def _set_hovered_item(self, item, tree):
        """Set hover highlight on the given tree item."""
        if self._hovered_item is not None and self._hovered_item != item:
            self._clear_hovered_item(tree)
        
        self._hovered_item = item
        try:
            tree._hover_index = tree.indexFromItem(item) if item is not None else QModelIndex()
            tree.viewport().update()
        except Exception:
            pass

    def _clear_hovered_item(self, tree):
        """Clear hover highlight."""
        if self._hovered_item is not None:
            self._hovered_item = None
        try:
            tree._hover_index = QModelIndex()
            tree.viewport().update()
        except Exception:
            pass


class TableDropFilter(QObject):
    """Handle dropping app items onto folder rows in the files table."""

    def __init__(self, owner):
        super().__init__(owner)
        self._w = owner
        self._hovered_index = None
        self._original_background = None

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
                    table = getattr(self._w, "table", None)
                    if table:
                        pos = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
                        idx = table.indexAt(pos)
                        
                        if idx.isValid():
                            if self._hovered_index is None or idx != self._hovered_index:
                                self._set_hovered_row(idx, table)
                        elif self._hovered_index is not None:
                            self._clear_hovered_row(table)
                    
                    ev.acceptProposedAction()
                    return True
            except Exception:
                return False
            return False

        if t == QEvent.DragLeave:
            table = getattr(self._w, "table", None)
            if table and self._hovered_index is not None:
                self._clear_hovered_row(table)
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

                # Determine drop action: Move (default) or Copy (Ctrl held)
                modifiers = ev.modifiers()
                use_copy = bool(modifiers & Qt.ControlModifier)
                
                # Also check dropAction returned from drag.exec_()
                drop_action = ev.dropAction()
                if drop_action == Qt.CopyAction:
                    use_copy = True
                elif drop_action == Qt.MoveAction:
                    use_copy = False

                norm = []
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    norm.append(
                        {
                            "id": it.get("id"),
                            "type": it.get("type"),
                            "name": it.get("name") or it.get("fileName") or it.get("originalName") or "",
                            "fileName": it.get("fileName") or "",
                            "originalName": it.get("originalName") or "",
                            "title": it.get("name") or it.get("fileName") or it.get("originalName") or "",
                            "folderId": it.get("folderId"),
                            "projectId": it.get("projectId"),
                        }
                    )

                if not norm:
                    return False

                result = {"id": dest_folder_id, "path": ""}
                
                try:
                    if use_copy:
                        # Copy operation
                        fn = getattr(self._w, "_do_copy", None)
                        if callable(fn):
                            fn(norm, result)
                        else:
                            fn = getattr(self._w, "copy_selected_action", None)
                            if callable(fn):
                                fn()
                    else:
                        # Move operation (default)
                        fn = getattr(self._w, "_do_move", None)
                        if callable(fn):
                            fn(norm, result, project_id)
                        else:
                            fn = getattr(self._w, "move_selected_action", None)
                            if callable(fn):
                                fn()
                except Exception:
                    pass

                # Set the drop action that was actually performed
                if use_copy:
                    ev.setDropAction(Qt.CopyAction)
                else:
                    ev.setDropAction(Qt.MoveAction)
                ev.accept()
                
                if table and self._hovered_index is not None:
                    self._clear_hovered_row(table)
                
                return True
            except Exception:
                return False

        return False

    def _set_hovered_row(self, idx, table):
        """Set hover highlight on the given row index."""
        if self._hovered_index is not None and self._hovered_index != idx:
            self._clear_hovered_row(table)
        
        self._hovered_index = idx
        table._hover_row = idx.row()
        table.viewport().update()

    def _clear_hovered_row(self, table):
        """Clear hover highlight."""
        if self._hovered_index is not None:
            self._hovered_index = None
        try:
            table._hover_row = -1
            table.viewport().update()
        except Exception:
            pass
