# -*- coding: utf-8 -*-
"""Table widget operations for Larix Nexus."""

import os
from PySide6.QtCore import Qt, QModelIndex, QTimer
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QHeaderView, QMessageBox
from ..constants import THEME_LIGHT, THEME_DARK, INSERT_ICON_PATH, CHECKBOX_COLUMN_WIDTH
from ..utils.helpers import normalize_id
from ..utils.i18n import t
from .widgets import WaitDialog


_CONNECTOR_MIN_WIDTHS = {
    0: CHECKBOX_COLUMN_WIDTH,
    1: 200,
    2: 70,
    3: 80,
    4: 70,
    5: 110,
    6: 110,
    7: 110,
    8: 110,
    9: 110,
}

_CONNECTOR_MAX_WIDTHS = {
    0: CHECKBOX_COLUMN_WIDTH,
    1: 700,
    2: 100,
    3: 130,
    4: 110,
    5: 220,
    6: 180,
    7: 180,
    8: 220,
    9: 180,
}

_CONNECTOR_DEFAULT_WIDTHS = {
    0: CHECKBOX_COLUMN_WIDTH,
    1: 280,
    2: 70,
    3: 85,
    4: 80,
    5: 130,
    6: 130,
    7: 130,
    8: 130,
    9: 120,
}

# Comfortable target widths for auto-fill expansion (keeps service columns compact).
# Must satisfy: min <= default <= target <= max.
_CONNECTOR_EXPAND_TARGET_WIDTHS = {
    0: CHECKBOX_COLUMN_WIDTH,
    1: 420,  # Название
    2: 80,   # Версия
    3: 100,  # Тип
    4: 95,   # Формат
    5: 170,  # Кем создан
    6: 155,  # Создано
    7: 155,  # Изменено
    8: 170,  # Кем изменено
    9: 155,  # Статус
}

_CONNECTOR_FILL_WEIGHTS = {
    1: 3.5,  # Название
    2: 0.8,  # Версия
    3: 0.9,  # Тип
    4: 0.9,  # Формат
    5: 1.4,  # Кем создан
    6: 1.3,  # Создано
    7: 1.3,  # Изменено
    8: 1.4,  # Кем изменено
    9: 1.4,  # Статус
}

_NAME_COLUMN_INDEX = 1
_NAME_COLUMN_MAX_WIDTH = 450
_COLUMN_CONTENT_PADDING = 24
_CONTENT_AWARE_MAX_ROWS = 200


def update_table(self):
    """Update table with current files."""
    files = getattr(self, "files_current", [])
    print(f"[update_table] Updating table with {len(files)} files")

    self.files_model.set_items(files)
    try:
        self._schedule_public_link_checks()
    except Exception:
        pass
    # Apply filters and recalc on next tick to avoid re-entrancy during model reset.
    def _apply_and_recalc():
        try:
            self.apply_table_filters()
        except Exception:
            pass
        # DISABLED: auto_hide_empty_columns() - keep all columns visible by default
        # self.auto_hide_empty_columns()
        try:
            self._recalc_columns()
        except Exception:
            pass
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

    try:
        QTimer.singleShot(0, _apply_and_recalc)
    except Exception:
        _apply_and_recalc()
    return


def _on_selection_changed(self, *args):
    """Handle table selection change."""
    self._update_actions_enabled()
    if getattr(self, "_selection_mode_active", None) and self._selection_mode_active():
        return
    items = self.get_selected_items()
    if items:
        item = items[0]
        try:
            fid = item.get("folderId") or item.get("folder_id")
            fid_key = normalize_id(fid)
            if fid_key and fid_key in self.folder_item_by_id:
                self.tree.setCurrentItem(self.folder_item_by_id[fid_key])
        except Exception:
            pass


def _schedule_recalc_columns(self):
    """Defer column width recalculation to the next event-loop tick."""
    def _run():
        try:
            self._recalc_columns()
        except Exception:
            pass

    try:
        QTimer.singleShot(0, _run)
    except Exception:
        _run()


def _schedule_resize_table_rows(self):
    """Debounced row height refresh after column width changes."""
    try:
        timer = getattr(self, "_resize_rows_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(50)
            timer.timeout.connect(self._resize_table_rows_to_contents)
            self._resize_rows_timer = timer
        timer.start()
    except Exception:
        try:
            self._resize_table_rows_to_contents()
        except Exception:
            pass


def _resize_table_rows_to_contents(self):
    try:
        self.table.resizeRowsToContents()
    except Exception:
        pass


def _on_model_data_changed(self, *args):
    """Handle model data change."""
    self._schedule_recalc_columns()
    # IMPORTANT: Update actions when checkboxes change
    self._update_actions_enabled()
    try:
        self._update_selection_mode_panel()
    except Exception:
        pass


def _connector_column_min_width(self, col):
    return _CONNECTOR_MIN_WIDTHS.get(col, 80)


def _connector_column_max_width(self, col):
    # No max-width limit: user must be able to expand columns freely.
    return 10**9


def _connector_column_default_width(self, col):
    return _CONNECTOR_DEFAULT_WIDTHS.get(col, self._connector_column_min_width(col))


def _connector_column_expand_target_width(self, col):
    target = _CONNECTOR_EXPAND_TARGET_WIDTHS.get(col)
    if target is None:
        target = self._connector_column_default_width(col)
    mn = int(self._connector_column_min_width(col))
    try:
        target = int(target)
    except Exception:
        target = int(self._connector_column_default_width(col))
    if target < mn:
        return mn
    return target


def _connector_visible_columns(self):
    try:
        table = self.table
        model = table.model()
        if not model:
            return []
        return [i for i in range(model.columnCount()) if not table.isColumnHidden(i)]
    except Exception:
        return []


def _connector_column_fill_weight(self, col):
    if col == 0:
        return 0
    return _CONNECTOR_FILL_WEIGHTS.get(col, 0)


def _connector_auto_fill_columns(self, visible_cols):
    return [c for c in visible_cols if c != 0 and self._connector_column_fill_weight(c) > 0]


def _distribute_fill_width(self, table, header, visible_cols, extra_space):
    """Legacy no-op: layout is handled by Qt Stretch resize mode."""
    return


def _table_source_model(self):
    """Source model behind the table proxy (for headers)."""
    try:
        proxy = getattr(self, "proxy", None)
        if proxy is not None:
            return proxy.sourceModel()
    except Exception:
        pass
    try:
        return self.files_model
    except Exception:
        return None


def _table_cell_text(self, model, row, col):
    try:
        idx = model.index(int(row), int(col))
        if not idx.isValid():
            return ""
        val = model.data(idx, Qt.DisplayRole)
        return "" if val is None else str(val)
    except Exception:
        return ""


def _apply_connector_content_widths(self):
    """Measure column widths from header + visible rows (proxy-aware)."""
    table = self.table
    model = table.model()
    if not model:
        return {}

    try:
        cell_fm = QFontMetrics(table.font())
    except Exception:
        return {}

    header = table.horizontalHeader()
    try:
        header_fm = QFontMetrics(header.font())
    except Exception:
        header_fm = cell_fm

    src_model = self._table_source_model() or model
    visible_cols = self._connector_visible_columns()
    row_limit = min(int(model.rowCount()), _CONTENT_AWARE_MAX_ROWS)

    icon_extra = 0
    if _NAME_COLUMN_INDEX in visible_cols:
        try:
            icon_extra = int(table.iconSize().width()) + 10
        except Exception:
            icon_extra = 34

    widths = {}
    for col in visible_cols:
        if col == 0:
            widths[col] = CHECKBOX_COLUMN_WIDTH
            continue

        max_w = 0
        try:
            header_text = src_model.headerData(col, Qt.Horizontal, Qt.DisplayRole)
            header_text = "" if header_text is None else str(header_text)
        except Exception:
            header_text = ""
        max_w = max(max_w, header_fm.horizontalAdvance(header_text))

        for row in range(row_limit):
            text = self._table_cell_text(model, row, col)
            w = cell_fm.horizontalAdvance(text)
            if col == _NAME_COLUMN_INDEX:
                w += icon_extra
            max_w = max(max_w, w)

        width = max_w + _COLUMN_CONTENT_PADDING
        mn = int(self._connector_column_min_width(col))
        width = max(width, mn)

        if col == _NAME_COLUMN_INDEX:
            width = min(width, _NAME_COLUMN_MAX_WIDTH)

        widths[col] = int(width)

    return widths


def _on_connector_section_resized(self, logical, old_size, new_size):
    """Keep checkbox column fixed; other columns stay at content width (Fixed)."""
    if getattr(self, '_syncing_connector_columns', False):
        return
    try:
        header = self.table.horizontalHeader()
        if int(logical) == 0:
            self._syncing_connector_columns = True
            try:
                header.resizeSection(0, CHECKBOX_COLUMN_WIDTH)
            finally:
                self._syncing_connector_columns = False
            return
    except Exception:
        try:
            self._syncing_connector_columns = False
        except Exception:
            pass


def _recalc_columns(self, *args):
    """Set column widths from content (Fixed); horizontal scroll if wider than viewport."""
    try:
        table = self.table
        model = table.model()
        if not model:
            return

        if int(model.columnCount()) == 0:
            return

        if getattr(self, '_syncing_connector_columns', False):
            return
        self._syncing_connector_columns = True
        try:
            header = table.horizontalHeader()
            visible_cols = self._connector_visible_columns()
            if not visible_cols:
                return

            widths = self._apply_connector_content_widths()
            if not widths:
                return

            for col in visible_cols:
                w = int(widths.get(col, self._connector_column_default_width(col)))
                header.setSectionResizeMode(col, QHeaderView.Fixed)
                header.resizeSection(col, w)

            self._connector_columns_initialized = True
            self._schedule_resize_table_rows()
        finally:
            self._syncing_connector_columns = False
    except Exception:
        pass


def _update_actions_enabled(self):
    """Update enabled state of actions."""
    # Check for selected rows OR checked items (checkboxes)
    try:
        action_items = self.get_action_selected_items() or []
    except Exception:
        action_items = []
    has_selection = bool(action_items)
    
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
    file_name = next(
        (
            selected_item.get(key)
            for key in ("name", "originalName", "fileName")
            if selected_item.get(key)
        ),
        "",
    )
    is_pdf_file = is_file and str(file_name).strip().lower().endswith(".pdf")

    # Move is allowed only for files (including mixed selection via checkboxes).
    all_selected_are_files = False
    if has_selection:
        items = []
        try:
            items = self.get_checked_visible_items() or []
        except Exception:
            items = []
        if not items:
            try:
                items = self.get_selected_items() or []
            except Exception:
                items = []
        items = action_items
        if items:
            try:
                dict_items = [it for it in items if isinstance(it, dict)]
                all_selected_are_files = bool(dict_items) and all(
                    str((it or {}).get("type") or "").lower() not in ("folder", "dir", "directory", "папка")
                    for it in dict_items
                )
            except Exception:
                all_selected_are_files = False
    
    try:
        if hasattr(self, "btn_download"):
            self.btn_download.setEnabled(has_selection)
        if hasattr(self, "btn_upload"):
            self.btn_upload.setEnabled(has_project)
        if hasattr(self, "btn_rename"):
            self.btn_rename.setEnabled(has_selection)
        if hasattr(self, "btn_compare"):
            self.btn_compare.setEnabled(has_selection and is_pdf_file)
        if hasattr(self, "btn_move"):
            self.btn_move.setEnabled(has_selection and all_selected_are_files)
        if hasattr(self, "btn_copy"):
            self.btn_copy.setEnabled(has_selection)
        if hasattr(self, "btn_delete"):
            self.btn_delete.setEnabled(has_selection)
    except Exception:
        pass

    try:
        if hasattr(self, "btn_move"):
            self.btn_move.setToolTip(
                t("folder.move_unavailable")
                if has_selection and not all_selected_are_files
                else t("toolbar.move")
            )
    except Exception:
        pass


def _bind_table_selection_signals(self):
    """Bind table selection signals and header checkbox update signals."""
    selection = self.table.selectionModel()
    selection.selectionChanged.connect(self._on_selection_changed)
    
    try:
        model = self.table.model()
        model.dataChanged.connect(self._on_model_data_changed)
        
        # IMPORTANT: Coalesce frequent signals; avoid calling into widgets during model reset.
        def _sched():
            try:
                fn = getattr(self, "schedule_update_header_checkbox", None)
                if callable(fn):
                    fn()
                else:
                    self.update_header_checkbox()
            except Exception:
                pass

        model.dataChanged.connect(lambda *_: _sched())
        model.rowsInserted.connect(lambda *_: _sched())
        model.rowsRemoved.connect(lambda *_: _sched())
        model.modelReset.connect(lambda *_: _sched())
        
        print(f"[_bind_table_selection_signals] Connected signals to model type: {type(model).__name__}")
    except Exception as e:
        print(f"[_bind_table_selection_signals] ERROR: {e}")
        import traceback
        traceback.print_exc()


def _on_table_cell_clicked(self, index: QModelIndex):
    """Handle table cell click."""
    if index.column() == 0:
        return
    
    item = self.selected_item()
    if not item:
        return
    
    if item.get("type") == "folder":
        fid = item.get("id")
        fid_key = normalize_id(fid)
        if fid_key and fid_key in self.folder_item_by_id:
            self.tree.setCurrentItem(self.folder_item_by_id[fid_key])
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
            if col in [0] or col in user_hidden:
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

        try:
            if header.isSectionHidden(0):
                cb.hide()
                return
        except Exception:
            pass

        box_size = getattr(cb, "BOX", 18)
        try:
            cb.resize(box_size, box_size)
        except Exception:
            pass

        try:
            section_pos = int(header.sectionViewportPosition(0))
            section_size = int(header.sectionSize(0))
            viewport_width = int(viewport.width())
        except Exception:
            # If we cannot compute geometry reliably, hide to avoid overlaying other headers.
            try:
                cb.hide()
            except Exception:
                pass
            return

        # Hide when the first section is fully outside the header viewport.
        if (section_pos + section_size) <= 0 or section_pos >= viewport_width:
            cb.hide()
            return

        cb.show()
        x = section_pos + (section_size - box_size) // 2
        y = (viewport.height() - box_size) // 2
        cb.move(x, y)
        cb.raise_()
    except Exception:
        pass


def schedule_update_header_checkbox(self):
    """Schedule a safe header checkbox refresh on next event loop tick."""
    if getattr(self, "_hdr_cb_update_scheduled", False):
        return
    self._hdr_cb_update_scheduled = True

    def _run():
        try:
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
        self.table.setColumnWidth(0, 40)
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
    try:
        self._selection_mode_anchor_row = None
        self._update_selection_mode_panel()
    except Exception:
        pass


def on_header_cb_state_changed(self, state: int):
    """Handle header checkbox state change."""
    print(f"[on_header_cb_state_changed] Called with state={state}")

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
    try:
        self._selection_mode_anchor_row = None
        self._update_selection_mode_panel()
    except Exception:
        pass


def on_sort_changed(self, column: int, _order: Qt.SortOrder):
    """Handle sort change."""
    try:
        hdr = self.table.horizontalHeader()
        if column == 0:
            hdr.setSortIndicatorShown(False)
            return
        if not getattr(self, "_sorting_armed", False):
            self._sorting_armed = True
            hdr.setSortIndicatorShown(True)
    except Exception:
        pass
    try:
        self._update_header_checkbox_pos()
    except Exception:
        pass


def _name_col_index(self) -> int:
    """Get name column index."""
    return 1  # Column index 1 is always the name column


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
    """Refresh column widths from cell/header content."""
    try:
        self._schedule_recalc_columns()
    except Exception:
        pass


def _resize_columns_to_contents_and_fill(self):
    """Refresh column widths from cell/header content."""
    try:
        self._schedule_recalc_columns()
    except Exception:
        pass


def inject_table_operations_to_main_window(MainWindowClass):
    """Inject table operations into MainWindow class."""
    MainWindowClass.update_table = update_table
    MainWindowClass._on_selection_changed = _on_selection_changed
    MainWindowClass._on_model_data_changed = _on_model_data_changed
    MainWindowClass._recalc_columns = _recalc_columns
    MainWindowClass._connector_column_min_width = _connector_column_min_width
    MainWindowClass._connector_column_max_width = _connector_column_max_width
    MainWindowClass._connector_column_default_width = _connector_column_default_width
    MainWindowClass._connector_column_expand_target_width = _connector_column_expand_target_width
    MainWindowClass._connector_visible_columns = _connector_visible_columns
    MainWindowClass._connector_column_fill_weight = _connector_column_fill_weight
    MainWindowClass._connector_auto_fill_columns = _connector_auto_fill_columns
    MainWindowClass._distribute_fill_width = _distribute_fill_width
    MainWindowClass._apply_connector_content_widths = _apply_connector_content_widths
    MainWindowClass._schedule_recalc_columns = _schedule_recalc_columns
    MainWindowClass._schedule_resize_table_rows = _schedule_resize_table_rows
    MainWindowClass._resize_table_rows_to_contents = _resize_table_rows_to_contents
    MainWindowClass._table_source_model = _table_source_model
    MainWindowClass._table_cell_text = _table_cell_text
    MainWindowClass._on_connector_section_resized = _on_connector_section_resized
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
