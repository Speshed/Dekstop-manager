# -*- coding: utf-8 -*-
"""Column visibility operations for Larix Nexus."""

from PySide6.QtCore import QSettings
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
            # Fallback to default 9 columns if model is not available
            count = 9
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
            # Fallback to default 9 columns if model is not available
            count = 9
        s = _app_settings()
        s.beginGroup("table")
        try:
            raw = s.value("cols_hidden", "") or ""
        finally:
            s.endGroup()
        applied = False
        if isinstance(raw, str) and raw.strip():
            parts = [p.strip() for p in str(raw).split(",") if p.strip().isdigit()]
            idxs = {int(p) for p in parts}
            # Always show column 0 (checkboxes)
            idxs.discard(0)
            for i in range(count):
                try:
                    self.table.setColumnHidden(i, i in idxs)
                except Exception:
                    pass
            applied = True
        if not applied:
            # default: ensure Modified column visible
            try:
                if 0 <= 7 < count:
                    self.table.setColumnHidden(7, False)
            except Exception:
                pass
        # IMPORTANT: Always ensure column 0 (checkboxes) is visible
        try:
            if count > 0:
                self.table.setColumnHidden(0, False)
        except Exception:
            pass
    except Exception:
        pass


def inject_column_ops_to_main_window(MainWindowClass):
    """Inject column operations into MainWindow class."""
    MainWindowClass._save_columns_visibility = _save_columns_visibility
    MainWindowClass._load_columns_visibility = _load_columns_visibility
