# -*- coding: utf-8 -*-
"""UI helpers and folder operations for Larix Nexus."""

from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu, QTreeWidgetItem
from ..utils.helpers import normalize_id
from ..constants import THEME_LIGHT, THEME_DARK


def set_initial_view(self):
    """Set initial view state."""
    project_id = self.current_project_id()
    if project_id:
        # Make all columns visible when loading a project
        try:
            for i in range(self.files_model.columnCount()):
                self.table.setColumnHidden(i, False)
        except Exception:
            pass
        self.load_tree_for_project(project_id)
        self.go_to_project_root()


def _toggle_first_col_on_scroll(self, value: int):
    """Toggle first column visibility on scroll."""
    threshold = 100
    try:
        self.table.setColumnHidden(0, value < threshold)
    except Exception:
        pass


def _style_projects_combo_popup(self):
    """Style projects combo box popup."""
    try:
        combo = getattr(self, "combo_projects", None)
        if not combo:
            return
        
        view = combo.view()
        if view:
            view.setStyleSheet("""
                QListView {
                    background-color: #2D2D2D;
                    color: #FFFFFF;
                    border: 1px solid #404040;
                }
                QListView::item {
                    padding: 5px;
                }
                QListView::item:hover {
                    background-color: #3D3D3D;
                }
                QListView::item:selected {
                    background-color: #0078D7;
                }
            """)
    except Exception:
        pass


def _menu_exec(self, menu, global_pos):
    """Execute menu with proper styling."""
    dark = getattr(self, "_current_theme", THEME_LIGHT) == THEME_DARK
    if dark:
        try:
            menu.setStyleSheet("""
                QMenu {
                    background-color: #2D2D2D;
                    color: #FFFFFF;
                    border: 1px solid #404040;
                }
                QMenu::item {
                    padding: 5px 30px 5px 20px;
                }
                QMenu::item:selected {
                    background-color: #0078D7;
                }
                QMenu::separator {
                    height: 1px;
                    background-color: #404040;
                }
            """)
            except Exception:
                pass
    
    menu.exec(global_pos)
    
    return result


def _win_ifiledialog_pick_folder(self, title: str, start_dir: str = "") -> str:
        import ctypes
        from ctypes import wintypes
        
        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", wintypes.BYTE * 8)
            ]
            
            def __str__(self):
                return "{{{:08x}-{:04x}-{:04x}-{:02x}{:02x}-{:02x}{:02x}{:02x}{:02x}}".format(
                    self.Data1, self.Data2, self.Data3,
                    self.Data4[0], self.Data4[1], self.Data4[2], self.Data4[3],
                    self.Data4[4], self.Data4[5], self.Data4[6], self.Data4[7]
                )
        
        IID_IFileOpenDialog = GUID(0xd57c7288, 0xd4ad, 0x4768, 
            0xbe, 0x02, 0x9d, 0x96, 0x95, 0x32, 0xd9, 0x60)
        
        CLSID_FileOpenDialog = GUID(0xdc1c5a9c, 0xe88a, 0x4dfe,
            0xa0, 0xa1, 0x60, 0xd8, 0x2f, 0x8e, 0x47, 0x7a)
        
        ole32 = ctypes.windll.ole32
        
        hr = ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
        
        dialog = ctypes.c_void_p()
        try:
            hr = ole32.CoCreateInstance(
                ctypes.byref(CLSID_FileOpenDialog),
                None,
                1,  # CLSCTX_ALL
                ctypes.byref(IID_IFileOpenDialog),
                ctypes.byref(dialog)
            )
            
            if hr != 0:
                print(f"[_win_ifiledialog_pick_folder] ERROR: CoCreateInstance failed with hr={hr} (0x{hr:08x})")
                return ""
            
            # Set to pick folder
            FOS_PICKFOLDERS = 0x00000020
            ole32.IFileOpenDialog_SetOptions(dialog, FOS_PICKFOLDERS)
            
            # Set title
            if title:
                title_w = title.encode('utf-16-le')
                ole32.IFileOpenDialog_SetTitle(dialog, title_w)
            
            # Show dialog with parent window to ensure it's visible and focused
            # Get parent window handle
            parent_hwnd = 0
            if hasattr(self, 'winId'):
                try:
                    parent_hwnd = int(self.winId())
                    print(f"[_win_ifiledialog_pick_folder] Parent HWND: {parent_hwnd}")
                except Exception as e:
                    print(f"[_win_ifiledialog_pick_folder] ERROR getting parent HWND: {e}")
                    pass
            
            print(f"[_win_ifiledialog_pick_folder] Calling IFileOpenDialog_Show with parent_hwnd={parent_hwnd}, title='{title}'")
            
            # Try to center dialog by showing it at center of parent
            hr = ole32.IFileOpenDialog_Show(dialog, parent_hwnd)
            
            print(f"[_win_ifiledialog_pick_folder] IFileOpenDialog_Show returned hr={hr} (0x{hr:08x})")
            
            if hr == 0:  # S_OK - user selected something
                result = ctypes.c_void_p()
                hr = ole32.IFileOpenDialog_GetResult(dialog, ctypes.byref(result))
                
                print(f"[_win_ifiledialog_pick_folder] IFileOpenDialog_GetResult returned hr={hr} (0x{hr:08x})")
                
                if hr == 0:
                    path = ctypes.create_unicode_buffer(260)
                    hr = ole32.IShellItem_GetDisplayName(result, 0x80058000, path)  # SIGDN_FILESYSPATH
                    
                    print(f"[_win_ifiledialog_pick_folder] IShellItem_GetDisplayName returned hr={hr} (0x{hr:08x})")
                    
                    if hr == 0:
                        path_str = path.value
                        print(f"[_win_ifiledialog_pick_folder] SUCCESS: Selected path='{path_str}'")
                        return path_str
                    else:
                        print(f"[_win_ifiledialog_pick_folder] ERROR: GetDisplayName failed")
                else:
                    print(f"[_win_ifiledialog_pick_folder] User cancelled or error in GetResult")
            else:
                print(f"[_win_ifiledialog_pick_folder] User cancelled or error in Show (hr={hr})")
            
            return ""
        except Exception as e:
            print(f"[_win_ifiledialog_pick_folder] EXCEPTION: {e}")
            import traceback
            traceback.print_exc()
            return ""
        finally:
            ole32.CoUninitialize()


def current_folder_node(self) -> dict:
    """Get current folder node."""
    current_item = self.tree.currentItem()
    if not current_item:
        return {}
    
    node = current_item.data(0, Qt.UserRole)
    if isinstance(node, dict):
        return node
    
    return {}


def _get_item_relative_path(self, item: dict) -> str:
    """Get relative path for item."""
    if not isinstance(item, dict):
        return ""
    
    path = item.get("path") or item.get("name") or ""
    return str(path)


def _child_folder_id_by_name(self, project_tree: list, parent_id: int | None, name: str) -> int | None:
    """Find child folder ID by name."""
    if not isinstance(project_tree, list) or not name:
        return None
    
    name_lower = name.casefold()
    
    def search(nodes: list, parent: int | None) -> int | None:
        for node in nodes:
            if not isinstance(node, dict):
                continue
            
            node_parent = node.get("folderId") or node.get("parentId") or node.get("parent_id") or node.get("folder_id")
            if normalize_id(node_parent) != normalize_id(parent):
                continue
            
            node_name = node.get("name") or node.get("title") or ""
            if node_name.casefold() == name_lower:
                return node.get("id")
            
            children = node.get("children") or []
            result = search(children, node.get("id"))
            if result is not None:
                return result
        
        return None
    
    return search(project_tree, parent_id)


def _collect_cloud_dirs(self, folder_node: dict, rel_path: str = "") -> list[str]:
    """Collect all cloud directories from folder node."""
    if not isinstance(folder_node, dict):
        return []
    
    dirs = []
    name = folder_node.get("name") or folder_node.get("title") or ""
    new_rel = f"{rel_path}/{name}" if rel_path else name
    
    typ = folder_node.get("type", "").lower()
    if typ in ("folder", "dir", "directory", "папка"):
        dirs.append(new_rel)
        
        children = folder_node.get("children") or []
        for child in children:
            dirs.extend(self._collect_cloud_dirs(child, new_rel))
    
    return dirs


def _ensure_cloud_path(self, project_id: int | str, root_folder_id: int | str, rel_path: str) -> int | str | None:
    """Ensure cloud path exists, return folder ID."""
    project_id = normalize_id(project_id)
    root_folder_id = normalize_id(root_folder_id)
    
    if not rel_path:
        return root_folder_id
    
    parts = rel_path.split('/')
    current_id = root_folder_id
    
    try:
        tree = self.api.list_folders(project_id) or []
    except Exception:
        return None
    
    for part in parts:
        if not part:
            continue
        
        tree_id = self._child_folder_id_by_name(tree, current_id, part)
        if tree_id:
            current_id = tree_id
        else:
            new_id = self._ensure_subfolder(project_id, current_id, part)
            if not new_id:
                return None
            current_id = new_id
    
    return current_id


def _ensure_subfolder(self, project_id: int | str, parent_folder_id: int | str, name: str) -> int | str | None:
    """Ensure subfolder exists, create if needed."""
    project_id = normalize_id(project_id)
    parent_folder_id = normalize_id(parent_folder_id)
    
    # Check if folder already exists
    try:
        tree = self.api.list_folders(project_id) or []
        existing_id = self._child_folder_id_by_name(tree, parent_folder_id, name)
        if existing_id:
            return existing_id
    except Exception:
        pass
    
    # Create new folder
    try:
        new_id = self.api.create_folder(parent_folder_id, name)
        return new_id
    except Exception:
        return None


def inject_ui_helpers_to_main_window(MainWindowClass):
    """Inject UI helpers into MainWindow class."""
    MainWindowClass.set_initial_view = set_initial_view
    MainWindowClass._toggle_first_col_on_scroll = _toggle_first_col_on_scroll
    MainWindowClass._style_projects_combo_popup = _style_projects_combo_popup
    MainWindowClass._menu_exec = _menu_exec
    MainWindowClass._win_ifiledialog_pick_folder = _win_ifiledialog_pick_folder
    MainWindowClass.current_folder_node = current_folder_node
    MainWindowClass._get_item_relative_path = _get_item_relative_path
    MainWindowClass._child_folder_id_by_name = _child_folder_id_by_name
    MainWindowClass._collect_cloud_dirs = _collect_cloud_dirs
    MainWindowClass._ensure_cloud_path = _ensure_cloud_path
    MainWindowClass._ensure_subfolder = _ensure_subfolder
