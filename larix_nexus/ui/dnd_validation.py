# -*- coding: utf-8 -*-
"""Drag & Drop validation and utilities.

This module provides validation logic, constants, and helper functions
for drag-and-drop operations in Larix Nexus.
"""

from __future__ import annotations
from typing import Optional, List, Dict, Set
from PySide6.QtCore import Qt, QPoint


# ============================================================================
# Constants
# ============================================================================

MIME_ITEMS = "application/x-larix-nexus-items"

# Animation/Delay constants (in milliseconds)
AUTO_EXPAND_DELAY = 500
HOVER_DEBOUNCE_DELAY = 100

# Drop operation types
class DropOp:
    MOVE = "move"
    COPY = "copy"
    INVALID = "invalid"


# Visual feedback colors (can be overridden by theme)
class DnDColors:
    HOVER_VALID = (76, 175, 80, 40)      # Green with alpha
    HOVER_INVALID = (244, 67, 54, 40)    # Red with alpha
    HOVER_BORDER_VALID = (76, 175, 80, 180)
    HOVER_BORDER_INVALID = (244, 67, 54, 180)


# ============================================================================
# Validation Functions
# ============================================================================

def validate_drop_target(
    dest_folder_id: int,
    items: List[Dict],
    project_id: int,
    tree_folder_map: Optional[Dict[int, List[int]]] = None
) -> tuple[str, str]:
    """Validate if items can be dropped to destination folder.

    Args:
        dest_folder_id: Destination folder ID
        items: List of items being dragged
        project_id: Current project ID
        tree_folder_map: Optional map of folder_id -> descendant folder IDs

    Returns:
        Tuple of (DropOp, error_message)
        - DropOp.MOVE if valid
        - DropOp.COPY if copy operation preferred (Ctrl held)
        - DropOp.INVALID with error message if invalid
    """
    print(f"[validate_drop_target] START: dest_folder_id={dest_folder_id} (type={type(dest_folder_id)}), items={len(items)}")
    
    if dest_folder_id is None:
        print("[validate_drop_target] FAIL: dest_folder_id is None")
        return DropOp.INVALID, "Не выбрана папка назначения"

    # Check if dropping to same folder
    for i, item in enumerate(items):
        item_folder_id = item.get("folderId")
        print(f"[validate_drop_target] Item {i}: id={item.get('id')}, folderId={item_folder_id} (type={type(item_folder_id)})")
        
        # Convert both to same type for comparison
        # Handle both int and str types
        try:
            item_folder_id_norm = int(item_folder_id) if item_folder_id is not None else None
            dest_folder_id_norm = int(dest_folder_id) if dest_folder_id is not None else None
            
            if item_folder_id_norm is not None and dest_folder_id_norm is not None:
                if item_folder_id_norm == dest_folder_id_norm:
                    print(f"[validate_drop_target] FAIL: Same folder! {item_folder_id_norm} == {dest_folder_id_norm}")
                    return DropOp.INVALID, "Нельзя переместить в ту же папку"
        except Exception as e:
            print(f"[validate_drop_target] Type conversion error: {e}")

    # Check if dropping folder into itself or its descendants
    if tree_folder_map:
        for item in items:
            item_id = item.get("id")
            item_type = item.get("type", "").lower()
            
            if item_type in ("folder", "dir", "directory", "папка"):
                if item_id == dest_folder_id:
                    return DropOp.INVALID, "Нельзя переместить папку в саму себя"
                
                # Check if destination is a descendant of source folder
                descendants = tree_folder_map.get(item_id, [])
                if dest_folder_id in descendants:
                    return DropOp.INVALID, "Нельзя переместить папку в её подпапку"

    return DropOp.MOVE, ""


def get_drop_operation(modifiers: Qt.KeyboardModifiers, default_op: str = DropOp.MOVE) -> str:
    """Determine drop operation based on keyboard modifiers.

    Args:
        modifiers: Qt.KeyboardModifiers from event
        default_op: Default operation if no modifiers

    Returns:
        DropOp.MOVE or DropOp.COPY
    """
    # Ctrl = Copy
    if modifiers & Qt.KeyboardModifier.ControlModifier:
        return DropOp.COPY
    # Shift = Move (explicit)
    if modifiers & Qt.KeyboardModifier.ShiftModifier:
        return DropOp.MOVE
    return default_op


def normalize_dnd_items(items: List[Dict]) -> List[Dict]:
    """Normalize DnD items to standard format.

    Args:
        items: Raw items from MIME data

    Returns:
        Normalized items with required fields
    """
    norm = []
    for it in items:
        if not isinstance(it, dict):
            continue
        norm.append({
            "id": it.get("id"),
            "type": it.get("type"),
            "name": it.get("name") or "",
            "title": it.get("name") or "",
            "folderId": it.get("folderId"),
            "projectId": it.get("projectId"),
        })
    return norm


def parse_mime_data(raw_data: bytes) -> tuple[List[Dict], str]:
    """Parse MIME data from drag operation.

    Args:
        raw_data: Raw bytes from QMimeData

    Returns:
        Tuple of (items, source) where items is list and source is string
    """
    import json
    
    try:
        data = json.loads(raw_data.decode("utf-8", errors="replace"))
    except Exception:
        return [], ""
    
    items = data.get("items") or []
    if not isinstance(items, list):
        items = []
    
    source = data.get("source", "table")
    return items, source


# ============================================================================
# Tree Helpers
# ============================================================================

def build_folder_descendants_map(tree_widget) -> Dict[int, List[int]]:
    """Build a map of folder_id to its descendant folder IDs.

    Args:
        tree_widget: QTreeWidget containing folder hierarchy

    Returns:
        Dictionary mapping folder_id -> list of descendant folder IDs
    """
    descendants_map = {}
    
    def _collect_descendants(item: int):
        """Recursively collect all descendant folder IDs."""
        from PySide6.QtWidgets import QTreeWidgetItem
        
        child_count = item.childCount()
        descendants = []
        
        for i in range(child_count):
            child = item.child(i)
            child_id = child.data(0, Qt.UserRole)
            if child_id:
                descendants.append(child_id)
                # Add grandchildren recursively
                descendants.extend(_collect_descendants(child))
        
        return descendants
    
    from PySide6.QtWidgets import QTreeWidgetItem
    root = tree_widget.invisibleRootItem()
    
    # Collect all top-level items
    def _process_item(item: QTreeWidgetItem):
        item_id = item.data(0, Qt.UserRole)
        if item_id:
            descendants_map[item_id] = _collect_descendants(item)
        
        # Process children
        for i in range(item.childCount()):
            _process_item(item.child(i))
    
    for i in range(root.childCount()):
        _process_item(root.child(i))
    
    return descendants_map


# ============================================================================
# Visual Feedback Helpers
# ============================================================================

def create_drop_highlight_pixmap(width: int, height: int, is_valid: bool) -> 'QPixmap':
    """Create a pixmap for drop target highlighting.

    Args:
        width: Pixmap width
        height: Pixmap height
        is_valid: Whether the drop target is valid

    Returns:
        QPixmap with appropriate color overlay
    """
    from PySide6.QtGui import QPixmap, QPainter, QColor, QPen
    from PySide6.QtCore import Qt
    
    pm = QPixmap(width, height)
    pm.fill(Qt.transparent)
    
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    
    if is_valid:
        bg_color = QColor(*DnDColors.HOVER_VALID)
        border_color = QColor(*DnDColors.HOVER_BORDER_VALID)
    else:
        bg_color = QColor(*DnDColors.HOVER_INVALID)
        border_color = QColor(*DnDColors.HOVER_BORDER_INVALID)
    
    # Draw background
    p.fillRect(0, 0, width, height, bg_color)
    
    # Draw border
    pen = QPen(border_color, 2)
    p.setPen(pen)
    p.drawRect(1, 1, width - 3, height - 3)
    
    p.end()
    return pm


def get_drop_action_label(operation: str, count: int) -> str:
    """Get human-readable label for drop action.

    Args:
        operation: DropOp.MOVE or DropOp.COPY
        count: Number of items being dragged

    Returns:
        Human-readable string
    """
    if count <= 0:
        return ""
    
    if operation == DropOp.COPY:
        if count == 1:
            return "Копировать"
        else:
            return f"Копировать {count} элемент"
    else:  # MOVE
        if count == 1:
            return "Переместить"
        else:
            return f"Переместить {count} элемент"
