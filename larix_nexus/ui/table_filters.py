# -*- coding: utf-8 -*-
"""Table filtering logic injected into MainWindow.

This keeps main_window.py smaller while preserving behavior.
"""

from __future__ import annotations

from PySide6 import QtCore
from PySide6.QtCore import Qt, QDate, QDateTime, QSortFilterProxyModel
from PySide6.QtWidgets import QMessageBox

from larix_nexus.models.files_table import FilesTableModel, file_ext


def apply_table_filters(self):
    try:
        # --- 0) нициализация хранилищ ---
        if not hasattr(self, "_flt_type"):
            self._flt_type = None
        if not hasattr(self, "_flt_formats"):
            self._flt_formats = set()
        if not hasattr(self, "_flt_created"):
            self._flt_created = (None, None)
        if not hasattr(self, "_flt_modified"):
            self._flt_modified = (None, None)
        if not hasattr(self, "column_text_filters"):
            self.column_text_filters = {}
        if not hasattr(self, "column_filters"):
            self.column_filters = {}

        # Поиск по имени
        try:
            query = (self.search.text() or "").strip().lower()
        except Exception:
            query = ""
        # глубокий поиск по имени во вложенных папках
        deep_needed = bool(query) and getattr(self, "_search_recursive", False)

        if deep_needed != getattr(self, "_search_uses_recursive", False):
            # базовый узел для выборки: корень или текущая папка
            if self._is_root_open():
                base = {"children": self.full_tree}  # корень проекта
            else:
                base = (self.current_path_nodes[-1] if self.current_path_nodes else None)

            if base:
                if deep_needed:
                    # глубоко: по всему поддереву
                    if self.cb_flat.isChecked():
                        # только файлы
                        self.files_current = self.collect_all_files_recursive(base)
                    else:
                        # файлы + папки
                        if hasattr(self, "collect_all_items_recursive"):
                            self.files_current = self.collect_all_items_recursive(base)
                        else:
                            self.files_current = self._collect_all_items_recursive(base)
                else:
                    # неглубоко: только текущий уровень
                    if self.cb_flat.isChecked():
                        ch = (base.get("children") or [])
                        self.files_current = [c for c in ch if isinstance(c, dict) and c.get("type") == "file"]
                    else:
                        self.files_current = self.collect_direct_level(base)

                # пересоздать модель как у тебя было
                self.files_model = FilesTableModel(self.files_current, self.icon_provider, self.checked)
                self._search_uses_recursive = deep_needed
                self.lazy_enrich_current_files(limit_per_folder=300)

        # --- 1) Хелперы для доступа к данным и колоночным индексам ---
        def _display_val_for(source_row: int, col: int) -> str:
            try:
                idx = self.files_model.index(source_row, col)
                v = self.files_model.data(idx)
                return "" if v is None else str(v)
            except Exception:
                return ""

        def _name_col_index() -> int:
            try:
                return next(
                    i
                    for i, h in enumerate(FilesTableModel.HEADERS)
                    if str(h).strip().lower() in ("наименование", "название", "имя", "имя файла")
                )
            except Exception:
                return 1

        def _col_idx(title: str) -> int:
            t = title.strip().lower()
            for i, h in enumerate(FilesTableModel.HEADERS):
                if str(h).strip().lower() == t:
                    return i
            return -1

        name_col = _name_col_index()
        created_col = _col_idx("создано")
        modified_col = _col_idx("изменено")

        def _parse_dt(s: str):
            s = (s or "").strip()
            if not s:
                return None
            dt = QDateTime.fromString(s, Qt.ISODate)
            if not dt.isValid():
                dt = QDateTime.fromString(s, "yyyy-MM-dd HH:mm")
            if not dt.isValid():
                dt = QDateTime.fromString(s, "yyyy-MM-dd")
            if not dt.isValid():
                dt = QDateTime.fromString(s, "dd.MM.yyyy HH:mm")
            if not dt.isValid():
                dt = QDateTime.fromString(s, "dd.MM.yyyy")
            return dt if dt.isValid() else None

        created_from, created_to = self._flt_created
        modified_from, modified_to = self._flt_modified
        if isinstance(created_from, QDate) and created_from.isValid():
            created_from_dt = QDateTime(created_from, QtCore.QTime(0, 0, 0))
        else:
            created_from_dt = None
        if isinstance(created_to, QDate) and created_to.isValid():
            created_to_dt = QDateTime(created_to, QtCore.QTime(23, 59, 59))
        else:
            created_to_dt = None
        if isinstance(modified_from, QDate) and modified_from.isValid():
            modified_from_dt = QDateTime(modified_from, QtCore.QTime(0, 0, 0))
        else:
            modified_from_dt = None
        if isinstance(modified_to, QDate) and modified_to.isValid():
            modified_to_dt = QDateTime(modified_to, QtCore.QTime(23, 59, 59))
        else:
            modified_to_dt = None

        # --- 2) Предикат допуска строки ---
        def _accept_row(source_row: int) -> bool:
            try:
                item = self.files_model.item_at(source_row)
            except Exception:
                item = {}
            if self._flt_formats and (item.get("type") or "").lower() == "folder":
                return False

            if self._flt_type:
                t = (item.get("type") or "").lower()
                if t not in self._flt_type:
                    return False

            if query:
                hay = (_display_val_for(source_row, name_col) or "").lower()
                if query not in hay:
                    return False

            if self._flt_formats and (item.get("type") or "").lower() == "file":
                name = (item.get("originalName") or item.get("name") or "")
                ext = file_ext(name)
                if ext not in self._flt_formats:
                    return False

            for c, needle in (self.column_text_filters or {}).items():
                if not str(needle):
                    continue
                val = _display_val_for(source_row, int(c)).lower()
                if str(needle).lower() not in val:
                    return False

            for c, allowed in (self.column_filters or {}).items():
                if not allowed:
                    continue
                val = _display_val_for(source_row, int(c))
                if val not in allowed:
                    return False

            if created_col >= 0 and (created_from_dt or created_to_dt):
                dt = _parse_dt(_display_val_for(source_row, created_col))
                if dt is None:
                    return False
                if created_from_dt and dt < created_from_dt:
                    return False
                if created_to_dt and dt > created_to_dt:
                    return False

            if modified_col >= 0 and (modified_from_dt or modified_to_dt):
                dt = _parse_dt(_display_val_for(source_row, modified_col))
                if dt is None:
                    return False
                if modified_from_dt and dt < modified_from_dt:
                    return False
                if modified_to_dt and dt > modified_to_dt:
                    return False

            return True

        # --- 3) Прокси-модель с нашим фильтром ---
        class _Proxy(QSortFilterProxyModel):
            def __init__(self, mw):
                super().__init__(mw)
                self.mw = mw
                self.setDynamicSortFilter(True)

            def filterAcceptsRow(self, source_row, source_parent):
                try:
                    return _accept_row(source_row)
                except Exception:
                    return True

            def lessThan(self, left, right):
                try:
                    if getattr(self.mw, "_freeze_visible_order", False) and getattr(self.mw, "_frozen_order", None):
                        l_item = self.sourceModel().data(left, Qt.UserRole) or {}
                        r_item = self.sourceModel().data(right, Qt.UserRole) or {}
                        lk = ((l_item.get("type") or None), l_item.get("id"))
                        rk = ((r_item.get("type") or None), r_item.get("id"))
                        lpos = self.mw._frozen_order.get(lk, 10**9)
                        rpos = self.mw._frozen_order.get(rk, 10**9)
                        return lpos < rpos
                except Exception:
                    pass
                try:
                    role = getattr(FilesTableModel, "SORT_ROLE", Qt.UserRole)
                    l = self.sourceModel().data(left, role)
                    r = self.sourceModel().data(right, role)
                    if l is None:
                        l = ""
                    if r is None:
                        r = ""
                    return l < r
                except Exception:
                    return super().lessThan(left, right)

        # --- 4) Сохранение состояния представления до смены модели ---
        header = self.table.horizontalHeader()
        try:
            sort_col = header.sortIndicatorSection()
            sort_ord = header.sortIndicatorOrder()
        except Exception:
            sort_col, sort_ord = 0, Qt.AscendingOrder

        src_model = self.table.model() or self.files_model
        try:
            col_count = src_model.columnCount()
        except Exception:
            col_count = len(getattr(FilesTableModel, "HEADERS", []))

        # NOTE: avoid calling QTableView.columnWidth() here; on Windows/PySide6
        # it can occasionally trigger a native crash during rapid model swaps.
        saved_widths = []
        try:
            max_cols = int(col_count)
        except Exception:
            max_cols = 0
        try:
            max_cols = max(0, min(max_cols, int(header.count())))
        except Exception:
            max_cols = max(0, max_cols)
        for i in range(max_cols):
            try:
                saved_widths.append(int(header.sectionSize(i)))
            except Exception:
                saved_widths.append(0)
        # НЕ сохраняем visible state здесь, потому что load_columns_visibility() восстановит его из настроек

        # --- 5) Назначаем новую прокси-модель ---
        proxy = _Proxy(self)
        proxy.setSourceModel(self.files_model)
        try:
            proxy.setSortRole(FilesTableModel.SORT_ROLE)
        except Exception:
            pass
        self.proxy = proxy
        self.table.setModel(self.proxy)
        self._bind_table_selection_signals()
        
        # Загружаем сохраненную видимость колонок ДО auto_hide_empty_columns()
        try:
            self._load_columns_visibility()
        except Exception:
            pass
        try:
            modified_col_default = 7
            if 0 <= modified_col_default < self.proxy.columnCount():
                self.table.setColumnHidden(modified_col_default, False)
        except Exception:
            pass

        # --- 6) Восстановление ширины колонок и сортировки ---
        # Видимость уже восстановлена через _load_columns_visibility()
        new_cols = self.proxy.columnCount()
        for c in range(min(new_cols, len(saved_widths))):
            try:
                w = int(saved_widths[c])
                if w > 0:
                    try:
                        header.resizeSection(c, w)
                    except Exception:
                        self.table.setColumnWidth(c, w)
            except Exception:
                pass

        try:
            header.setSortIndicatorShown(self._sorting_armed)
            if self._sorting_armed:
                header.setSortIndicator(sort_col, sort_ord)
                self.table.sortByColumn(sort_col, sort_ord)
            sort_col = max(0, min(sort_col, new_cols - 1))
        except Exception:
            pass

        # --- 7) Обновляем связанные элементы UI ---
        try:
            self.update_header_checkbox()
        except Exception:
            pass
        try:
            self._update_actions_enabled()
        except Exception:
            pass
        try:
            if hasattr(self, "header_filter_icons_update"):
                self.header_filter_icons_update()
        except Exception:
            pass
        try:
            if hasattr(self, "_bind_table_selection_signals"):
                self._bind_table_selection_signals()
        except Exception:
            pass

    except Exception as e:
        try:
            QMessageBox.warning(self, "Фильтр", f"Не удалось применить фильтр:\n{e}")
        except Exception:
            pass


def inject_table_filters_to_main_window(MainWindowClass) -> None:
    MainWindowClass.apply_table_filters = apply_table_filters
