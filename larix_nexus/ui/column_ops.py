# -*- coding: utf-8 -*-
"""Column visibility operations for Larix Nexus."""

from PySide6.QtCore import QSettings, Qt
from ..constants import SETTINGS_ORG, SETTINGS_APP
from ..utils.settings import _app_settings

_COLUMNS_VISIBILITY_VERSION = 2
_DEFAULT_VISIBLE_COLUMNS = {0, 1, 2, 3, 4, 5, 6, 9}


def _save_columns_visibility(self) -> None:
    """Save column visibility to settings."""
    try:
        model = self.table.model() or self.files_model
        if model is None:
            return
        try:
            count = model.columnCount()
        except Exception:
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
            s.setValue("columns_visibility_version", _COLUMNS_VISIBILITY_VERSION)
            s.sync()
        finally:
            s.endGroup()
    except Exception:
        pass


def _migrate_columns_visibility(s, count):
    """Migrate legacy column visibility settings to current version.

    If settings are missing or from an older version, forces columns 7 and 8
    hidden and writes the current version key. Returns sanitized hidden set.
    """
    raw = s.value("cols_hidden", "") or ""
    version = s.value("columns_visibility_version", 0)
    try:
        version = int(version)
    except Exception:
        version = 0

    if isinstance(raw, str) and raw.strip():
        parts = [p.strip() for p in str(raw).split(",") if p.strip().isdigit()]
        idxs = {int(p) for p in parts}
    else:
        idxs = set()

    if version < _COLUMNS_VISIBILITY_VERSION:
        if 7 not in idxs:
            idxs.add(7)
        if 8 not in idxs:
            idxs.add(8)
        s.setValue("cols_hidden", ",".join(str(i) for i in sorted(idxs)))
        s.setValue("columns_visibility_version", _COLUMNS_VISIBILITY_VERSION)
        s.sync()

    return idxs


def _load_columns_visibility(self) -> None:
    """Load column visibility from settings with migration/sanitize support."""
    try:
        model = self.table.model() or self.files_model
        if model is None:
            return
        try:
            count = model.columnCount()
        except Exception:
            count = 10
        s = _app_settings()
        s.beginGroup("table")
        try:
            idxs = _migrate_columns_visibility(s, count)
        finally:
            s.endGroup()

        print(f"[_load_columns_visibility] Loading column visibility, count={count}, hidden={idxs}")

        for i in range(count):
            try:
                self.table.setColumnHidden(i, i in idxs)
                header = model.headerData(i, Qt.Horizontal)
                print(f"[_load_columns_visibility] Column {i} ('{header}'): visible={not (i in idxs)}")
            except Exception:
                pass

        if count > 0:
            try:
                self.table.setColumnHidden(0, False)
                print(f"[_load_columns_visibility] Column 0 (checkboxes) set to visible (forced)")
            except Exception:
                pass
        try:
            if hasattr(self, '_apply_connector_column_width_policy') and callable(self._apply_connector_column_width_policy):
                self._apply_connector_column_width_policy(preserve_user_widths=False)
        except Exception:
            pass
    except Exception as e:
        print(f"[_load_columns_visibility] ERROR: {e}")


def inject_column_ops_to_main_window(MainWindowClass):
    """Inject column operations into MainWindow class."""
    MainWindowClass._save_columns_visibility = _save_columns_visibility
    MainWindowClass._load_columns_visibility = _load_columns_visibility
    MainWindowClass._migrate_columns_visibility = _migrate_columns_visibility
