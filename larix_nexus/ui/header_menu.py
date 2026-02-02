# -*- coding: utf-8 -*-
"""Header context menu operations for Larix Nexus."""

from PySide6.QtCore import Qt, QDate, QDateTime
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QCalendarWidget, QFrame, QLabel, QWidget
from ..constants import THEME_LIGHT, THEME_DARK
from ..utils.helpers import normalize_id


def header_context_menu_legacy(self, pos):
    """Show context menu for table header (legacy, replaced by context_menus version)."""
    # Эта функция больше не используется, заменена на версию из context_menus.py
    # Оставлена для обратной совместимости
    pass


def _populate_columns_menu(self) -> QMenu:
    """Build columns visibility menu."""
    menu = QMenu("Столбцы", self)
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
    """)
    
    try:
        model = self.table.model()
        if hasattr(model, "HEADERS"):
            headers = list(model.HEADERS)
        else:
            headers = []
        
        for i, header in enumerate(headers):
            act = QAction(header, self)
            act.setCheckable(True)
            act.setChecked(not self.table.isColumnHidden(i))
            # IMPORTANT: Prevent hiding critical columns (checkbox, createdBy, createTime, modifTime, modifiedBy)
            if i in [0, 5, 6, 7, 8]:
                act.setEnabled(False)
                act.setChecked(True)
            act.triggered.connect(lambda checked, idx=i: self._toggle_column_visibility(idx, checked))
            menu.addAction(act)
    except Exception:
        pass
    
    return menu


def _toggle_column_visibility(self, col: int, visible: bool):
    """Toggle column visibility."""
    try:
        self.table.setColumnHidden(col, not visible)
        self._save_columns_visibility()
    except Exception:
        pass


def _build_date_filter_menu(self) -> QMenu:
    """Build date filter submenu."""
    menu = QMenu("Фильтр по дате", self)
    
    # Today
    act_today = QAction("Сегодня", self)
    act_today.triggered.connect(lambda: self._apply_date_filter("today"))
    menu.addAction(act_today)
    
    # This week
    act_week = QAction("Эта неделя", self)
    act_week.triggered.connect(lambda: self._apply_date_filter("week"))
    menu.addAction(act_week)
    
    # This month
    act_month = QAction("Этот месяц", self)
    act_month.triggered.connect(lambda: self._apply_date_filter("month"))
    menu.addAction(act_month)
    
    # Custom range
    act_custom = QAction("Период...", self)
    act_custom.triggered.connect(self._show_custom_date_dialog)
    menu.addAction(act_custom)
    
    # Clear filter
    menu.addSeparator()
    act_clear = QAction("Сбросить фильтр", self)
    act_clear.triggered.connect(lambda: self._apply_date_filter(None))
    menu.addAction(act_clear)
    
    return menu


def _apply_date_filter(self, period: str | None):
    """Apply date filter to table."""
    try:
        if period is None:
            # Clear filter
            self.proxy.setFilterKeyColumn(-1)
            self.proxy.setFilterRegularExpression("")
            return
        
        now = QDateTime.currentDateTime()
        start_date = None
        
        if period == "today":
            start_date = now.date()
        elif period == "week":
            start_date = now.date().addDays(-7)
        elif period == "month":
            start_date = now.date().addDays(-30)
        
        if start_date:
            date_str = start_date.toString("yyyy-MM-dd")
            self.proxy.setFilterKeyColumn(self._find_col("Изменён"))
            self.proxy.setFilterRegularExpression(f"^\\[{date_str},.*\\]$")
    except Exception:
        pass


def _show_custom_date_dialog(self):
    """Show custom date range dialog."""
    dialog = QFrame(self)
    dialog.setWindowTitle("Выберите период")
    dialog.setFrameShape(QFrame.StyledPanel)
    
    layout = QVBoxLayout(dialog)
    
    # Date picker
    calendar = QCalendarWidget(dialog)
    calendar.setMaximumDate(QDateTime.currentDateTime().date())
    layout.addWidget(calendar)
    
    # Info label
    info = QLabel("Выберите дату:", dialog)
    layout.addWidget(info)
    
    dialog.show()


def _build_type_filter_menu(self) -> QMenu:
    """Build file type filter submenu."""
    menu = QMenu("Фильтр по типу", self)
    
    # Get unique types from current files
    types = set()
    try:
        files = getattr(self, "files_current", [])
        for item in files:
            if isinstance(item, dict):
                ext = item.get("extension") or ""
                if ext:
                    types.add(ext.lower())
    except Exception:
        pass
    
    # Add menu items for each type
    for ext in sorted(types):
        act = QAction(f".{ext}", self)
        act.triggered.connect(lambda e, x=ext: self._apply_type_filter(x))
        menu.addAction(act)
    
    # Show all
    menu.addSeparator()
    act_all = QAction("Все файлы", self)
    act_all.triggered.connect(lambda: self._apply_type_filter(None))
    menu.addAction(act_all)
    
    return menu


def _apply_type_filter(self, ext: str | None):
    """Apply type filter to table."""
    try:
        if ext is None:
            self.proxy.setFilterKeyColumn(-1)
            self.proxy.setFilterRegularExpression("")
        else:
            self.proxy.setFilterKeyColumn(self._find_col("Тип"))
            self.proxy.setFilterRegularExpression(f"\\.{ext}$")
    except Exception:
        pass


def inject_header_menu_to_main_window(MainWindowClass):
    """Inject header menu operations into MainWindow class."""
    # ВАЖНО: НЕ переопределяем header_context_menu!
    # Используется полноценная версия из context_menus.py с полной фильтрацией
    
    # Эти функции больше не нужны, так как context_menus.py реализует полную фильтрацию
    # Если они нужны другому коду, можно добавить их обратно selectively
