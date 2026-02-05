# -*- coding: utf-8 -*-
"""Column visibility operations for Larix Nexus."""

from PySide6.QtCore import QSettings, Qt
from ..constants import SETTINGS_ORG, SETTINGS_APP
from ..utils.settings import _app_settings


def _save_columns_visibility(self) -> None:
    """Save column visibility to settings."""
    try:
        model = self.table.model() or self.files_model
        if model is None:
            return
        try:
            count = model.columnCount()
        except Exception:
            # Fallback to default 10 columns if model is not available
            count = 10
        hidden = []
        for i in range(count):
            try:
                if self.table.isColumnHidden(i):
                    hidden.append(str(i))
            except Exception:
                continue
        s = _app_settings()
        s.beginGroup("table")
        try:
            s.setValue("cols_hidden", ",".join(hidden))
            s.sync()
        finally:
            s.endGroup()
    except Exception:
        pass


def _load_columns_visibility(self) -> None:
    """Load column visibility from settings."""
    try:
        model = self.table.model() or self.files_model
        if model is None:
            return
        try:
            count = model.columnCount()
        except Exception:
            # Fallback to default 10 columns if model is not available
            count = 10
        s = _app_settings()
        s.beginGroup("table")
        try:
            raw = s.value("cols_hidden", "") or ""
        finally:
            s.endGroup()

        print(f"[_load_columns_visibility] Loading column visibility, count={count}, raw='{raw}'")

        applied = False
        if isinstance(raw, str) and raw.strip():
            parts = [p.strip() for p in str(raw).split(",") if p.strip().isdigit()]
            idxs = {int(p) for p in parts}
            for i in range(count):
                try:
                    self.table.setColumnHidden(i, i in idxs)
                    header = model.headerData(i, Qt.Horizontal)
                    print(f"[_load_columns_visibility] Column {i} ('{header}'): visible={not (i in idxs)}")
                except Exception:
                    pass
            applied = True
        if not applied:
            # default: show specific columns only (0=checkbox, 1=name, 2=version, 3=type, 4=format, 5=created_by, 6=created, 9=status)
            visible_by_default = {0, 1, 2, 3, 4, 5, 6, 9}
            for i in range(count):
                try:
                    self.table.setColumnHidden(i, i not in visible_by_default)
                    header = model.headerData(i, Qt.Horizontal)
                    print(f"[_load_columns_visibility] Column {i} ('{header}'): visible={i in visible_by_default} (default)")
                except Exception:
                    pass
        # IMPORTANT: Always ensure column 0 (checkboxes) is visible
        try:
            if count > 0:
                self.table.setColumnHidden(0, False)
                print(f"[_load_columns_visibility] Column 0 (checkboxes) set to visible (forced)")
        except Exception:
            pass
    except Exception as e:
        print(f"[_load_columns_visibility] ERROR: {e}")


def inject_column_ops_to_main_window(MainWindowClass):
    """Inject column operations into MainWindow class."""
    MainWindowClass._save_columns_visibility = _save_columns_visibility
    MainWindowClass._load_columns_visibility = _load_columns_visibility
