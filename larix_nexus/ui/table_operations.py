# -*- coding: utf-8 -*-
"""Table widget operations for Larix Nexus."""

import os
from PySide6.QtCore import Qt, QModelIndex, QTimer
from PySide6.QtWidgets import QMessageBox
from ..constants import THEME_LIGHT, THEME_DARK, INSERT_ICON_PATH
from ..utils.helpers import normalize_id
from .widgets import WaitDialog


def update_table(self):
    """Update table with current files."""
    files = getattr(self, "files_current", [])
    print(f"[update_table] Updating table with {len(files)} files")
    try:
        print(f"[update_table] Starting model update")
        self.files_model.set_items(files)
        print(f"[update_table] Model updated successfully")
    except Exception as e:
        print(f"[update_table] ERROR setting items: {e}")
        import traceback
        traceback.print_exc()
        return

    # Apply filters and recalc on next tick to avoid re-entrancy during model reset.
    def _apply_and_recalc():
        try:
            # Bail out if the UI was destroyed (common when a modal dialog runs and the window closes).
            try:
                from shiboken6 import isValid  # type: ignore
                tbl = getattr(self, "table", None)
                if tbl is None or not isValid(tbl):
                    return
            except Exception:
                pass

            print(f"[update_table] _apply_and_recalc: starting")
            try:
                self.apply_table_filters()
                print(f"[update_table] _apply_and_recalc: filters applied")
            except Exception as e:
                print(f"[update_table] _apply_and_recalc: ERROR in apply_table_filters: {e}")
                import traceback
                traceback.print_exc()

            # DISABLED: auto_hide_empty_columns() - keep all columns visible by default
            # self.auto_hide_empty_columns()
            try:
                print(f"[update_table] _apply_and_recalc: starting _recalc_columns")
                self._recalc_columns()
                print(f"[update_table] _apply_and_recalc: _recalc_columns completed")
            except Exception as e:
                print(f"[update_table] _apply_and_recalc: ERROR in _recalc_columns: {e}")
                import traceback
                traceback.print_exc()

            try:
                print(f"[update_table] Table updated, rowCount={self.files_model.rowCount()}")
            except Exception:
                pass

            # Print column visibility status
            try:
                for col in range(self.files_model.columnCount()):
                    is_hidden = self.table.isColumnHidden(col)
                    header = self.files_model.headerData(col, Qt.Horizontal)
                    print(f"[update_table] Column {col} ('{header}'): visible={not is_hidden}")
            except Exception:
                pass

            print(f"[update_table] _apply_and_recalc: completed")
        except Exception as e:
            print(f"[update_table] _apply_and_recalc: FATAL ERROR: {e}")
            import traceback
            traceback.print_exc()

    try:
        print(f"[update_table] Scheduling _apply_and_recalc")
        QTimer.singleShot(0, _apply_and_recalc)
    except Exception:
        print(f"[update_table] ERROR scheduling timer, calling directly")
        _apply_and_recalc()
    return


def _on_selection_changed(self, *args):
    """Handle table selection change."""
    self._update_actions_enabled()
    items = self.get_selected_items()
    if items:
        item = items[0]
        try:
            fid = item.get("folderId") or item.get("folder_id")
            if fid and fid in self.folder_item_by_id:
                self.tree.setCurrentItem(self.folder_item_by_id[fid])
        except Exception:
            pass


def _on_model_data_changed(self, *args):
    """Handle model data change."""
    self._recalc_columns()
    # IMPORTANT: Update actions when checkboxes change
    self._update_actions_enabled()


def _recalc_columns(self, *args):
    """Recalculate column widths with better sizing."""
    try:
        print(f"[_recalc_columns] Starting column recalculation")
        table = self.table
        model = table.model()
        if not model:
            print(f"[_recalc_columns] No model, returning")
            return

        count = model.columnCount()
        if count == 0:
            print(f"[_recalc_columns] Column count is 0, returning")
            return

        # Get header (QHeaderView has setColumnMinimumWidth)
        header = table.horizontalHeader()
        if not header:
            print(f"[_recalc_columns] No header, returning")
            return

        print(f"[_recalc_columns] Header type: {type(header).__name__}")

        # Check if header has the required methods (SortHeader may not expose them)
        has_set_min = hasattr(header, 'setColumnMinimumWidth')
        has_set_width = hasattr(header, 'setColumnWidth')
        print(f"[_recalc_columns] header.setColumnMinimumWidth: {has_set_min}")
        print(f"[_recalc_columns] header.setColumnWidth: {has_set_width}")

        if not (has_set_min or has_set_width):
            print(f"[_recalc_columns] Header doesn't have column methods, skipping")
            return

        print(f"[_recalc_columns] Processing {count} columns")
        # Resize all columns to fit their content
        for i in range(count):
            try:
                table.resizeColumnToContents(i)
                # Set minimum widths for columns to prevent them from being too narrow
                if i == 1:  # "Название" - should be wider
                    min_width = max(150, table.columnWidth(i))
                    if has_set_min:
                        header.setColumnMinimumWidth(i, min_width)
                    elif has_set_width:
                        # Fallback: just set the width directly
                        pass
                elif i == 0:  # Checkbox column
                    if has_set_min:
                        header.setColumnMinimumWidth(i, 40)
                    elif has_set_width:
                        header.setColumnWidth(i, 40)
                else:  # Other columns
                    min_width = max(80, table.columnWidth(i))
                    if has_set_min:
                        header.setColumnMinimumWidth(i, min_width)
                print(f"[_recalc_columns] Column {i} resized")
            except Exception as e:
                print(f"[_recalc_columns] ERROR resizing column {i}: {e}")

        print(f"[_recalc_columns] Starting width distribution")
        # Distribute remaining width to "Название" column (index 1)
        try:
            viewport_width = table.viewport().width()
            current_width = sum(table.columnWidth(i) for i in range(count))
            if current_width < viewport_width:
                diff = viewport_width - current_width
                name_col_width = table.columnWidth(1)
                if has_set_width:
                    header.setColumnWidth(1, name_col_width + diff)
        except Exception:
            pass
    except Exception:
        pass


def _update_actions_enabled(self):
    """Update enabled state of actions."""
    # Check for selected rows OR checked items (checkboxes)
    has_selection = bool(self.table.selectionModel().selectedRows())
    
    # Also check for any checked items (checkboxes that might be clicked but not selected as rows)
    if not has_selection:
        try:
            fm = getattr(self, "files_model", None)
            if fm and hasattr(fm, "checked"):
                has_selection = bool(fm.checked)
        except Exception:
            pass
    
    has_project = self.current_project_id() is not None
    
    # Get selected item for type-specific logic
    selected_item = {}
    if has_selection:
        try:
            selected_item = self.selected_item()
        except Exception:
            pass
    
    # Check if selected item can be compared (file, not folder)
    item_type = str(selected_item.get("type", "")).lower()
    is_file = item_type not in ("folder", "dir", "directory", "папка")
    
    try:
        if hasattr(self, "btn_download"):
            self.btn_download.setEnabled(has_selection)
        if hasattr(self, "btn_upload"):
            self.btn_upload.setEnabled(has_project)
        if hasattr(self, "btn_rename"):
            self.btn_rename.setEnabled(has_selection)
        if hasattr(self, "btn_compare"):
            self.btn_compare.setEnabled(has_selection and is_file)
        if hasattr(self, "btn_move"):
            self.btn_move.setEnabled(has_selection)
        if hasattr(self, "btn_copy"):
            self.btn_copy.setEnabled(has_selection)
        if hasattr(self, "btn_delete"):
            self.btn_delete.setEnabled(has_selection)
    except Exception:
        pass


def _bind_table_selection_signals(self):
    """Bind table selection signals and header checkbox update signals."""
    # Avoid native crashes caused by duplicate signal connections and stale QObjects.
    try:
        from shiboken6 import isValid  # type: ignore

        def _qvalid(o) -> bool:
            try:
                return o is not None and isValid(o)
            except Exception:
                return o is not None
    except Exception:
        def _qvalid(o) -> bool:
            return o is not None

    try:
        table = getattr(self, "table", None)
        if not _qvalid(table):
            return
    except Exception:
        return

    try:
        selection = table.selectionModel()
        model = table.model()
    except Exception:
        return

    # If we're already bound to this model/selection, do nothing.
    try:
        if _qvalid(getattr(self, "_bound_selection_model", None)) and getattr(self, "_bound_selection_model", None) is selection:
            if _qvalid(getattr(self, "_bound_table_model", None)) and getattr(self, "_bound_table_model", None) is model:
                return
    except Exception:
        pass

    # Disconnect previous bindings (best-effort).
    try:
        prev_sel = getattr(self, "_bound_selection_model", None)
        if _qvalid(prev_sel):
            try:
                prev_sel.selectionChanged.disconnect(self._on_selection_changed)
            except Exception:
                pass
    except Exception:
        pass

    try:
        prev_model = getattr(self, "_bound_table_model", None)
        if _qvalid(prev_model):
            try:
                prev_model.dataChanged.disconnect(self._on_model_data_changed)
            except Exception:
                pass
            try:
                prev_model.dataChanged.disconnect(self._on_table_model_mutated)
            except Exception:
                pass
            try:
                prev_model.rowsInserted.disconnect(self._on_table_model_mutated)
            except Exception:
                pass
            try:
                prev_model.rowsRemoved.disconnect(self._on_table_model_mutated)
            except Exception:
                pass
            try:
                prev_model.modelReset.disconnect(self._on_table_model_mutated)
            except Exception:
                pass
    except Exception:
        pass

    # Connect signals (prefer UniqueConnection where supported).
    try:
        try:
            selection.selectionChanged.connect(self._on_selection_changed, type=Qt.ConnectionType.UniqueConnection)
        except Exception:
            selection.selectionChanged.connect(self._on_selection_changed)
    except Exception:
        pass

    try:
        if model is not None:
            try:
                model.dataChanged.connect(self._on_model_data_changed, type=Qt.ConnectionType.UniqueConnection)
            except Exception:
                model.dataChanged.connect(self._on_model_data_changed)

            # Coalesce frequent signals; avoid calling into widgets during model reset.
            try:
                model.dataChanged.connect(self._on_table_model_mutated, type=Qt.ConnectionType.UniqueConnection)
                model.rowsInserted.connect(self._on_table_model_mutated, type=Qt.ConnectionType.UniqueConnection)
                model.rowsRemoved.connect(self._on_table_model_mutated, type=Qt.ConnectionType.UniqueConnection)
                model.modelReset.connect(self._on_table_model_mutated, type=Qt.ConnectionType.UniqueConnection)
            except Exception:
                try:
                    model.dataChanged.connect(self._on_table_model_mutated)
                    model.rowsInserted.connect(self._on_table_model_mutated)
                    model.rowsRemoved.connect(self._on_table_model_mutated)
                    model.modelReset.connect(self._on_table_model_mutated)
                except Exception:
                    pass

        self._bound_selection_model = selection
        self._bound_table_model = model
        try:
            print(f"[_bind_table_selection_signals] Connected signals to model type: {type(model).__name__}")
        except Exception:
            pass
    except Exception as e:
        try:
            print(f"[_bind_table_selection_signals] ERROR: {e}")
            import traceback
            traceback.print_exc()
        except Exception:
            pass


def _on_table_model_mutated(self, *args):
    """Coalesce model-change signals into a safe header checkbox refresh."""
    try:
        fn = getattr(self, "schedule_update_header_checkbox", None)
        if callable(fn):
            fn()
        else:
            self.update_header_checkbox()
    except Exception:
        pass


def _on_table_cell_clicked(self, index: QModelIndex):
    """Handle table cell click."""
    if index.column() == 0:
        return
    
    item = self.selected_item()
    if not item:
        return
    
    if item.get("type") == "folder":
        fid = item.get("id")
        if fid in self.folder_item_by_id:
            self.tree.setCurrentItem(self.folder_item_by_id[fid])
        self.open_folder_node(item)
        return


def auto_hide_empty_columns(self):
    """Auto-hide empty columns, but respect user settings."""
    try:
        model = self.table.model()
        if not model:
            return
        
        count = model.columnCount()
        rows = model.rowCount()
        
        # Don't hide columns if table is empty (no rows)
        if rows == 0:
            # Make all columns visible when table is empty
            for col in range(count):
                self.table.setColumnHidden(col, False)
            return
        
        # Load user's column visibility settings to respect them
        from PySide6.QtCore import QSettings
        from ..constants import SETTINGS_ORG, SETTINGS_APP
        from ..utils.settings import _app_settings
        
        s = _app_settings()
        s.beginGroup("table")
        try:
            raw = s.value("cols_hidden", "") or ""
        finally:
            s.endGroup()
        
        user_hidden = set()
        if isinstance(raw, str) and raw.strip():
            parts = [p.strip() for p in str(raw).split(",") if p.strip().isdigit()]
            user_hidden = {int(p) for p in parts}
        
        for col in range(count):
            # Skip checkbox column and columns user explicitly hid
            if col == 0 or col in user_hidden:
                continue
            
            has_data = False
            for row in range(rows):
                idx = model.index(row, col)
                if idx.isValid():
                    data = model.data(idx)
                    if data:
                        has_data = True
                        break
            
            # Only hide if empty AND user hasn't explicitly shown it
            if not has_data:
                self.table.setColumnHidden(col, True)
    except Exception:
        pass


def _update_header_checkbox_pos(self, *args):
    """Update header checkbox position."""
    # Блокируем обновление если идёт изменение состояния чекбокса
    if getattr(self, '_updating_checkbox_state', False):
        return
    
    try:
        header = self.table.horizontalHeader()
        viewport = header.viewport()
        
        cb = getattr(self, "hdrcb", None)
        if cb is None:
            return
        # Avoid native crash if underlying QObject was deleted (PySide6)
        try:
            from shiboken6 import isValid  # type: ignore
            if not isValid(cb):
                return
        except Exception:
            pass

        if cb:
            geom = self.hdrcb.geometry()
            box_size = getattr(self.hdrcb, "BOX", 18)
            from ..constants import CHECKBOX_COLUMN_WIDTH
            
            # Calculate x-offset to center checkbox in column 0 (36px wide)
            # Matches CheckBoxDelegate: offset = (36 - 18) // 2 = 9px
            x_offset = (CHECKBOX_COLUMN_WIDTH - box_size) // 2
            
            # Use sectionPosition to align with cell checkboxes
            # sectionPosition returns the position of the section (column) in the header
            x = x_offset  # Default fallback
            try:
                # sectionPosition accounts for hidden columns but not horizontal scroll
                # This should align with how cells are positioned
                section_pos = header.sectionPosition(0)
                x = section_pos + x_offset
            except Exception:
                pass

            y = (viewport.height() - geom.height()) // 2
            self.hdrcb.move(x, y)
    except Exception:
        pass


def schedule_update_header_checkbox(self):
    """Schedule a safe header checkbox refresh on next event loop tick."""
    # Skip if the table was already destroyed (can happen during shutdown / modal loops).
    try:
        from shiboken6 import isValid  # type: ignore
        tbl = getattr(self, "table", None)
        if tbl is None or not isValid(tbl):
            return
    except Exception:
        pass

    if getattr(self, "_hdr_cb_update_scheduled", False):
        return
    self._hdr_cb_update_scheduled = True

    def _run():
        try:
            try:
                from shiboken6 import isValid  # type: ignore
                tbl = getattr(self, "table", None)
                if tbl is None or not isValid(tbl):
                    self._hdr_cb_update_scheduled = False
                    return
            except Exception:
                pass
            self._hdr_cb_update_scheduled = False
            self.update_header_checkbox()
        except Exception:
            self._hdr_cb_update_scheduled = False

    try:
        QTimer.singleShot(0, _run)
    except Exception:
        _run()


def _fix_first_column_width(self):
    """Fix first column width to accommodate checkbox."""
    try:
        # IMPORTANT: setColumnWidth is a method of QHeaderView, not QTableView
        self.table.horizontalHeader().setColumnWidth(0, 40)
    except Exception:
        pass


def set_all_visible_checked(self, on: bool):
    """Set all visible items checked state."""
    try:
        model = self.table.model()
        if not model:
            return

        # Use the model returned by table - it might be FilesTableModel or QSortFilterProxyModel
        is_proxy = hasattr(model, 'sourceModel')
        print(f"[set_all_visible_checked] model type: {type(model).__name__}, is_proxy: {is_proxy}")

        # Convert boolean to Qt.CheckState
        check_state = Qt.Checked if on else Qt.Unchecked

        if is_proxy:
            # QSortFilterProxyModel - get source model and iterate through all source rows
            source_model = model.sourceModel()
            if not source_model:
                print("[set_all_visible_checked] ERROR: source_model is None")
                return

            print(f"[set_all_visible_checked] Using proxy: source rows={source_model.rowCount()}, proxy rows={model.rowCount()}")
            
            # Iterate through all source rows and check if they're visible in proxy
            for source_row in range(source_model.rowCount()):
                source_idx = source_model.index(source_row, 0)
                if not source_idx.isValid():
                    continue
                
                # Map to proxy index to check if visible
                proxy_idx = model.mapFromSource(source_idx)
                if not proxy_idx.isValid():
                    continue  # This row is filtered out
                
                # Set data on source model
                source_model.setData(source_idx, check_state, Qt.CheckStateRole)
        else:
            # FilesTableModel - use directly without proxy
            print(f"[set_all_visible_checked] Using source model directly: rowCount={model.rowCount()}")
            for row in range(model.rowCount()):
                source_idx = model.index(row, 0)
                if source_idx.isValid():
                    model.setData(source_idx, check_state, Qt.CheckStateRole)
        
        # Force table viewport update to refresh checkboxes
        print("[set_all_visible_checked] Forcing viewport update")
        try:
            self.table.viewport().update()
        except Exception as e:
            print(f"[set_all_visible_checked] Viewport update failed: {e}")
    except Exception as e:
        print(f"[set_all_visible_checked] ERROR: {e}")
        import traceback
        traceback.print_exc()


def update_header_checkbox(self):
    """Update header checkbox state based on selection."""
    try:
        cb = getattr(self, "hdrcb", None)
        if cb is None:
            return
        # Avoid native crash if underlying QObject was deleted (PySide6)
        try:
            from shiboken6 import isValid  # type: ignore
            if not isValid(cb):
                return
        except Exception:
            pass

        # Avoid native crash if the underlying table QObject was deleted.
        try:
            from shiboken6 import isValid  # type: ignore
            if not isValid(self.table):
                return
        except Exception:
            pass

        model = self.table.model()
        if not model:
            return

        # Use the model returned by table - it might be FilesTableModel or QSortFilterProxyModel
        is_proxy = hasattr(model, 'sourceModel')

        if is_proxy:
            # QSortFilterProxyModel - get source model and iterate through all source rows
            source_model = model.sourceModel()
            if not source_model:
                return

            print(f"[update_header_checkbox] Using proxy: source rows={source_model.rowCount()}, proxy rows={model.rowCount()}")

            total = model.rowCount()  # Only count visible rows
            checked = 0

            # Iterate through all source rows and check if they're visible in proxy
            for source_row in range(source_model.rowCount()):
                source_idx = source_model.index(source_row, 0)
                if not source_idx.isValid():
                    continue

                # Map to proxy index to check if visible
                proxy_idx = model.mapFromSource(source_idx)
                if not proxy_idx.isValid():
                    continue  # This row is filtered out

                # Get data from source model
                state = source_model.data(source_idx, Qt.CheckStateRole)
                if state == Qt.Checked:
                    checked += 1
        else:
            # FilesTableModel - use directly without proxy
            print(f"[update_header_checkbox] Using source model directly: rowCount={model.rowCount()}")
            total = model.rowCount()
            checked = 0

            for row in range(total):
                source_idx = model.index(row, 0)
                if source_idx.isValid():
                    state = model.data(source_idx, Qt.CheckStateRole)
                    if state == Qt.Checked:
                        checked += 1

        if checked == 0:
            state = Qt.Unchecked
        elif checked == total:
            state = Qt.Checked
        else:
            state = Qt.PartiallyChecked

        print(f"[update_header_checkbox] checked={checked}, total={total}, state={state}")

        if cb:
            try:
                cb.blockSignals(True)
                cb.setCheckState(state)
            finally:
                try:
                    cb.blockSignals(False)
                except Exception:
                    pass
    except Exception:
        pass


def on_header_cb_clicked(self, checked: bool):
    """Handle header checkbox click."""
    print(f"[on_header_cb_clicked] Called with checked={checked}")
    try:
        cb = getattr(self, "hdrcb", None)
        if cb is not None:
            try:
                from shiboken6 import isValid  # type: ignore
                if not isValid(cb):
                    return
            except Exception:
                pass
    except Exception:
        pass
    self.set_all_visible_checked(checked)
    self._update_actions_enabled()


def on_header_cb_state_changed(self, state: int):
    """Handle header checkbox state change."""
    print(f"[on_header_cb_state_changed] Called with state={state}")

    # Some signals emit bool (toggled) which is a subclass of int (True == 1).
    # Treat those as non-authoritative here to avoid accidentally triggering the
    # PartiallyChecked branch.
    try:
        if type(state) is bool:
            return
    except Exception:
        pass

    try:
        cb = getattr(self, "hdrcb", None)
        if cb is not None:
            try:
                from shiboken6 import isValid  # type: ignore
                if not isValid(cb):
                    return
            except Exception:
                pass
    except Exception:
        pass
    
    # Блокируем обновление позиции чекбокса во время изменения состояния
    self._updating_checkbox_state = True
    try:
        # Сравниваем с целыми числами вместо enum
        if state == 1:  # Qt.PartiallyChecked
            # при клике по "полоске" включаем все видимые строки и фиксируем заголовок как Checked
            self.set_all_visible_checked(True)
            try:
                self.hdrcb.blockSignals(True)
                self.hdrcb.setCheckState(Qt.Checked)
            finally:
                try:
                    self.hdrcb.blockSignals(False)
                except Exception:
                    pass
        elif state == 2:  # Qt.Checked
            self.set_all_visible_checked(True)
        elif state == 0:  # Qt.Unchecked
            self.set_all_visible_checked(False)
    finally:
        self._updating_checkbox_state = False


def on_sort_changed(self, column: int, _order: Qt.SortOrder):
    """Handle sort change."""
    try:
        self._update_header_checkbox_pos()
    except Exception:
        pass


def _name_col_index(self) -> int:
    """Get name column index."""
    try:
        model = self.table.model()
        if hasattr(model, "HEADERS"):
            try:
                return list(model.HEADERS).index("Имя")
            except ValueError:
                pass
    except Exception:
        pass
    return 1  # Default


def _update_name_search_icon(self):
    """Update name column search icon."""
    try:
        name_col = self._name_col_index()
        header = self.table.horizontalHeader()
        
        if hasattr(self, "_filter_icon_pm") and self._filter_icon_pm:
            header.setSectionIndicator(name_col, self._filter_icon_pm)
    except Exception:
        pass


def _find_col(self, title: str) -> int:
    """Find column index by title."""
    try:
        model = self.table.model()
        if hasattr(model, "HEADERS"):
            try:
                return list(model.HEADERS).index(title)
            except ValueError:
                pass
    except Exception:
        pass
    return -1


def _tune_columns(self):
    """Tune column widths."""
    try:
        self._fill_table_width_to_viewport()
    except Exception:
        pass


def _fill_table_width_to_viewport(self):
    """Fill table width to viewport."""
    try:
        table = self.table
        viewport = table.viewport()
        width = viewport.width()
        
        total_width = sum(table.columnWidth(i) for i in range(table.columnCount()))

        if total_width < width:
            diff = width - total_width
            name_col = self._name_col_index()
            if name_col >= 0:
                # IMPORTANT: setColumnWidth is a method of QHeaderView, not QTableView
                table.horizontalHeader().setColumnWidth(name_col, table.columnWidth(name_col) + diff)
    except Exception:
        pass


def _resize_columns_to_contents_and_fill(self):
    """Resize columns to contents and fill width."""
    try:
        table = self.table
        for i in range(table.columnCount()):
            table.resizeColumnToContents(i)
        
        self._fill_table_width_to_viewport()
    except Exception:
        pass


def inject_table_operations_to_main_window(MainWindowClass):
    """Inject table operations into MainWindow class."""
    MainWindowClass.update_table = update_table
    MainWindowClass._on_selection_changed = _on_selection_changed
    MainWindowClass._on_model_data_changed = _on_model_data_changed
    MainWindowClass._on_table_model_mutated = _on_table_model_mutated
    MainWindowClass._recalc_columns = _recalc_columns
    MainWindowClass._update_actions_enabled = _update_actions_enabled
    MainWindowClass._bind_table_selection_signals = _bind_table_selection_signals
    MainWindowClass._on_table_cell_clicked = _on_table_cell_clicked
    MainWindowClass.auto_hide_empty_columns = auto_hide_empty_columns
    MainWindowClass._update_header_checkbox_pos = _update_header_checkbox_pos
    MainWindowClass._fix_first_column_width = _fix_first_column_width
    MainWindowClass.set_all_visible_checked = set_all_visible_checked
    MainWindowClass.update_header_checkbox = update_header_checkbox
    MainWindowClass.schedule_update_header_checkbox = schedule_update_header_checkbox
    MainWindowClass.on_header_cb_clicked = on_header_cb_clicked
    MainWindowClass.on_header_cb_state_changed = on_header_cb_state_changed
    MainWindowClass.on_sort_changed = on_sort_changed
    MainWindowClass._name_col_index = _name_col_index
    MainWindowClass._update_name_search_icon = _update_name_search_icon
    MainWindowClass._find_col = _find_col
    MainWindowClass._tune_columns = _tune_columns
    MainWindowClass._fill_table_width_to_viewport = _fill_table_width_to_viewport
    MainWindowClass._resize_columns_to_contents_and_fill = _resize_columns_to_contents_and_fill
