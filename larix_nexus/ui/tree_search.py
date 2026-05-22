# -*- coding: utf-8 -*-
"""Tree search operations for Larix Nexus."""

from PySide6.QtWidgets import QTreeWidgetItem
from ..utils.helpers import normalize_id


def _find_node_by_id_in_tree(self, tree_widget, node_id: int | str):
    """Find node in tree by ID."""
    node_id = normalize_id(node_id)
    
    def walk(item: QTreeWidgetItem):
        if not item:
            return None
        
        # Check current item
        try:
            item_data = item.data(0, Qt.UserRole)
            if isinstance(item_data, dict):
                item_id = normalize_id(item_data.get("id") or item_data.get("folderId"))
                if item_id == node_id:
                    return item
        except Exception:
            pass
        
        # Walk children
        for i in range(item.childCount()):
            result = walk(item.child(i))
            if result:
                return result
        
        return None
    
    root = tree_widget.invisibleRootItem()
    for i in range(root.childCount()):
        result = walk(root.child(i))
        if result:
            return result
    
    return None


def _find_folder_in_tree(self, nodes: list, folder_id: int | str) -> dict | None:
    """Find folder node in tree by ID."""
    folder_id = normalize_id(folder_id)
    
    def walk(items: list) -> dict | None:
        for item in items:
            if not isinstance(item, dict):
                continue
            
            item_id = normalize_id(item.get("id") or item.get("folderId"))
            if item_id == folder_id:
                return item
            
            # API trees may nest folders under either "children" or "folders".
            children = item.get("children") or item.get("folders") or []
            if children:
                result = walk(children)
                if result:
                    return result
        
        return None
    
    return walk(nodes)


def collect_all_items_recursive(self, node: dict) -> list:
    """Collect all items recursively from node."""
    if not isinstance(node, dict):
        return []
    
    items = [node]
    
    children = node.get("children") or node.get("folders") or []
    for child in children:
        items.extend(self.collect_all_items_recursive(child))
    
    return items


def collect_direct_level(self, node: dict) -> list:
    """Collect items at direct level only."""
    if not isinstance(node, dict):
        return []
    
    return node.get("children") or node.get("folders") or []


def inject_tree_search_to_main_window(MainWindowClass):
    """Inject tree search operations into MainWindow class."""
    MainWindowClass._find_node_by_id_in_tree = _find_node_by_id_in_tree
    MainWindowClass._find_folder_in_tree = _find_folder_in_tree
    MainWindowClass.collect_all_items_recursive = collect_all_items_recursive
    MainWindowClass.collect_direct_level = collect_direct_level
