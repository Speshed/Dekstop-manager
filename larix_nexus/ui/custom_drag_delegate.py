# -*- coding: utf-8 -*-
"""Custom drag delegate for improved drag preview with icons only."""

from __future__ import annotations

from typing import Optional, List
from PySide6.QtCore import Qt, QPoint, QModelIndex
from PySide6.QtGui import QPixmap, QDrag
from PySide6.QtWidgets import QStyledItemDelegate


# Constants
ICON_SIZE = 32
ICON_GAP = 8
PAD = 10
MAX_ICONS = 5


class CustomDragDelegate(QStyledItemDelegate):
    """Custom delegate that provides improved drag preview with icons only."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_rows = []  # Store rows being dragged
        
    def set_drag_rows(self, rows: List[int]):
        """Set rows that are being dragged."""
        self._drag_rows = rows
    
    def startDrag(self, supportedActions, model):
        """Override to provide custom drag preview."""
        from PySide6.QtCore import QMimeData, QByteArray
        import json
        
        # Get selected indexes
        selected = self.parent().selectionModel().selectedIndexes()
        if not selected:
            return
        
        # Get source model
        source_model = model
        if hasattr(source_model, 'sourceModel'):
            source_model = source_model.sourceModel()
        
        # Create MIME data with items
        rows = sorted({idx.row() for idx in selected})
        items = []
        
        icon_provider = None
        if hasattr(source_model, '_icon_provider'):
            icon_provider = source_model._icon_provider
        
        for row in rows:
            if hasattr(source_model, '_data') and row < len(source_model._data):
                item = source_model._data[row]
                items.append({
                    "id": item.get("id"),
                    "type": item.get("type"),
                    "name": item.get("name") or item.get("originalName") or item.get("title") or "",
                    "folderId": item.get("folderId") or item.get("folder_id") or item.get("parent"),
                    "projectId": item.get("projectId") or item.get("project_id"),
                })
        
        payload = {"source": "table", "items": items}
        md = QMimeData()
        try:
            raw = json.dumps(payload, ensure_ascii=True).encode("utf-8")
            md.setData("application/x-larix-nexus-items", QByteArray(raw))
        except Exception:
            pass
        
        # Create drag
        drag = QDrag(self.parent())
        drag.setMimeData(md)
        
        # Create custom preview with icons only
        pixmap = self._create_drag_preview(rows, source_model, icon_provider)
        if not pixmap.isNull():
            drag.setPixmap(pixmap)
            # Hot spot at bottom-right
            drag.setHotSpot(QPoint(pixmap.width() - 5, pixmap.height() - 5))
            print(f"[CustomDragDelegate] Preview: {pixmap.width()}x{pixmap.height()}")
        else:
            print("[CustomDragDelegate] Warning: Preview pixmap is null")
        
        # Execute drag
        result = drag.exec_(supportedActions)
        print(f"[CustomDragDelegate] Drag completed: {result}")
        
        return result
    
    def _create_drag_preview(self, rows: List[int], source_model, icon_provider) -> QPixmap:
        """Create drag preview with icons only (no text), softer border."""
        from PySide6.QtGui import QPainter, QColor, QPen
        from PySide6.QtCore import Qt, QRectF, QPoint
        
        count = len(rows)
        show = min(count, MAX_ICONS)
        
        # Calculate dimensions
        w = PAD * 2 + ICON_SIZE * show + ICON_GAP * (show - 1)
        h = PAD * 2 + ICON_SIZE
        
        pm = QPixmap(w, h)
        pm.fill(Qt.transparent)
        
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        
        # Softer background
        bg = QColor(247, 146, 30, 200)  # Lower opacity
        border = QColor(219, 122, 10, 150)  # Softer border
        shadow = QColor(0, 0, 0, 40)
        
        # Draw shadow
        p.setPen(Qt.NoPen)
        p.setBrush(shadow)
        p.drawRoundedRect(QRectF(2, 2, w, h), 8, 8)
        
        # Draw main background
        p.setPen(QPen(border, 1))
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(0, 0, w, h), 8, 8)
        
        # Draw icons only
        for i, row in enumerate(rows[:show]):
            x = PAD + i * (ICON_SIZE + ICON_GAP)
            y = PAD
            
            if hasattr(source_model, '_data') and row < len(source_model._data):
                item = source_model._data[row]
                
                if icon_provider:
                    try:
                        icon = icon_provider.get_icon(item)
                        pm_icon = icon.pixmap(ICON_SIZE, ICON_SIZE)
                        if not pm_icon.isNull():
                            # Draw icon with subtle shadow
                            p.setPen(Qt.NoPen)
                            p.setBrush(QColor(0, 0, 0, 30))
                            p.drawRoundedRect(QRectF(x + 2, y + 2, ICON_SIZE, ICON_SIZE), 4, 4)
                            # Draw icon
                            p.drawPixmap(x, y, pm_icon)
                    except Exception as e:
                        print(f"[CustomDragDelegate] Icon draw error: {e}")
                        pass
        
        # Draw count badge if more than MAX_ICONS
        if count > MAX_ICONS:
            badge_x = PAD + MAX_ICONS * (ICON_SIZE + ICON_GAP) - 15
            badge_y = PAD + ICON_SIZE - 20
            
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 180))
            p.drawRoundedRect(QRectF(badge_x, badge_y, 28, 20), 10, 10)
            
            p.setPen(QColor(255, 255, 255))
            font = p.font()
            font.setBold(True)
            font.setPointSize(9)
            p.setFont(font)
            p.drawText(QRectF(badge_x, badge_y, 28, 20), Qt.AlignCenter, f"+{count - MAX_ICONS}")
        
        p.end()
        return pm
