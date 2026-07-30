# -*- coding: utf-8 -*-
"""UI helpers and folder operations for Larix Nexus."""

import logging
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu, QTreeWidgetItem
from ..utils.helpers import normalize_id
from ..constants import THEME_LIGHT, THEME_DARK


logger = logging.getLogger("app")


def set_initial_view(self):
    """Set initial view state."""
    project_id = self.current_project_id()
    if project_id:
        try:
            if hasattr(self, '_ensure_default_column_visibility') and callable(self._ensure_default_column_visibility):
                self._ensure_default_column_visibility()
            else:
                visible_by_default = {0, 1, 2, 3, 4, 5, 6, 9}
                for i in range(self.files_model.columnCount()):
                    self.table.setColumnHidden(i, i not in visible_by_default)
        except Exception:
            pass
        self.load_tree_for_project(project_id)
        self.go_to_project_root()
    else:
        # "Выберите проект" / no project: drop stale tree, table, and selection state
        try:
            self.full_tree = []
            self.current_path_nodes = []
            self.files_current = []
            self.folder_item_by_id = {}
            self._current_folder_context = {}
            self._folder_history = []
            ch = getattr(self, "checked", None)
            if ch is not None:
                try:
                    ch.clear()
                except Exception:
                    pass
            if hasattr(self, "_selection_mode_anchor_row"):
                self._selection_mode_anchor_row = None
            tree = getattr(self, "tree", None)
            if tree is not None:
                try:
                    tree.clear()
                except Exception:
                    pass
                try:
                    tree.setCurrentItem(None)
                except Exception:
                    pass
            tbl = getattr(self, "table", None)
            if tbl is not None:
                try:
                    sm = tbl.selectionModel()
                    if sm is not None:
                        sm.clearSelection()
                except Exception:
                    pass
            if hasattr(self, "update_table") and callable(self.update_table):
                self.update_table()
            if hasattr(self, "update_path_label") and callable(self.update_path_label):
                self.update_path_label()
            if hasattr(self, "_update_actions_enabled") and callable(self._update_actions_enabled):
                self._update_actions_enabled()
            try:
                fn = getattr(self, "schedule_update_header_checkbox", None)
                if callable(fn):
                    fn()
                elif hasattr(self, "update_header_checkbox") and callable(self.update_header_checkbox):
                    self.update_header_checkbox()
            except Exception:
                pass
        except Exception:
            pass


def _toggle_first_col_on_scroll(self, value: int):
    """Toggle first column visibility on scroll."""
    threshold = 100
    try:
        self.table.setColumnHidden(0, value < threshold)
    except Exception:
        pass


def _style_combo_popup_view(
    combo,
    view_object_name: str,
    *,
    dark: bool = False,
    light_background: str = "#FFFFFF",
    light_foreground: str = "#000000",
    light_selected: str = "#FFE7D0",
    dark_background: str = "#1e1e1e",
    dark_foreground: str = "#e0e0e0",
    dark_selected: str = "rgba(247, 146, 30, 0.22)",
) -> None:
    """Configure the native popup view for application-level theme QSS."""
    if combo is None:
        return
    try:
        view = combo.view()
    except Exception:
        return
    if view is None:
        return

    view.setObjectName(view_object_name)
    viewport = view.viewport()
    if viewport is not None:
        viewport.setObjectName(f"{view_object_name}Viewport")
    try:
        view.setMouseTracking(True)
        view.setAttribute(Qt.WA_Hover, True)
        if viewport is not None:
            viewport.setMouseTracking(True)
            viewport.setAttribute(Qt.WA_Hover, True)
    except Exception:
        pass


def _style_projects_combo_popup(self):
    """Style projects combo box popup."""
    try:
        # Backward-compat: keep the public name, but delegate to the stable implementation.
        if hasattr(self, "_prepare_projects_combo_popup"):
            self._prepare_projects_combo_popup()
    except Exception:
        pass


def _prepare_projects_combo_popup(self) -> None:
    """Ensure projects combo popup has stable styling every time.

    The combobox popup view may live in a separate popup container and some global
    QSS rules for `QComboBox QAbstractItemView::item` can reintroduce borders.
    To make it deterministic we (re)apply a local stylesheet on the actual view
    on each open and after theme changes.
    """
    combo = getattr(self, "cb_projects", None)
    if combo is None:
        return

    try:
        view = combo.view()
    except Exception:
        view = None
    if view is None:
        return

    # Stable objectNames for theme-level QSS (and debugging).
    try:
        view.setObjectName("projectsComboView")
    except Exception:
        pass
    try:
        vp = view.viewport()
        if vp is not None:
            vp.setObjectName("projectsComboViewport")
    except Exception:
        vp = None

    # Ensure hover/selection updates reliably.
    try:
        view.setMouseTracking(True)
    except Exception:
        pass
    try:
        if vp is not None:
            vp.setMouseTracking(True)
    except Exception:
        pass
    try:
        view.setAttribute(Qt.WA_Hover, True)
        if vp is not None:
            vp.setAttribute(Qt.WA_Hover, True)
    except Exception:
        pass

    dark = getattr(self, "_current_theme", THEME_LIGHT) == THEME_DARK
    _style_combo_popup_view(
        combo,
        "projectsComboView",
        dark=dark,
        light_selected="#FFE7D0",
    )
    return

def _menu_exec(self, menu, global_pos):
    """Execute menu with proper styling."""
    return menu.exec(global_pos)


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
            (0xbe, 0x02, 0x9d, 0x96, 0x95, 0x32, 0xd9, 0x60))

        CLSID_FileOpenDialog = GUID(0xdc1c5a9c, 0xe88a, 0x4dfe,
            (0xa0, 0xa1, 0x60, 0xd8, 0x2f, 0x8e, 0x47, 0x7a))
        
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
        new_id = self.api.create_folder(project_id, parent_folder_id, name)
        return new_id
    except Exception as exc:
        logger.exception(
            "Failed to create subfolder '%s': %s",
            name,
            exc,
        )
        return None


def inject_ui_helpers_to_main_window(MainWindowClass):
    """Inject UI helpers into MainWindow class."""
    MainWindowClass.set_initial_view = set_initial_view
    MainWindowClass._toggle_first_col_on_scroll = _toggle_first_col_on_scroll
    MainWindowClass._style_projects_combo_popup = _style_projects_combo_popup
    MainWindowClass._prepare_projects_combo_popup = _prepare_projects_combo_popup
    MainWindowClass._menu_exec = _menu_exec
    MainWindowClass._win_ifiledialog_pick_folder = _win_ifiledialog_pick_folder
    MainWindowClass.current_folder_node = current_folder_node
    MainWindowClass._get_item_relative_path = _get_item_relative_path
    MainWindowClass._child_folder_id_by_name = _child_folder_id_by_name
    MainWindowClass._collect_cloud_dirs = _collect_cloud_dirs
    MainWindowClass._ensure_cloud_path = _ensure_cloud_path
    MainWindowClass._ensure_subfolder = _ensure_subfolder
