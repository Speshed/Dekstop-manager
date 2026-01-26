# -*- coding: utf-8 -*-

import time
from datetime import datetime

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex


class TombstoneTableModel(QAbstractTableModel):
    """Table model for displaying tombstones."""
    
    HEADERS = ["Файл", "Сторона", "Дата удаления", "Статус", "Истекает через (дней)"]
    
    def __init__(self, tombstones, parent=None):
        super().__init__(parent)
        self.tombstones = tombstones
    
    def set_tombstones(self, tombstones):
        self.beginResetModel()
        self.tombstones = tombstones
        self.endResetModel()
    
    def rowCount(self, parent=QModelIndex()):
        return len(self.tombstones)
    
    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)
    
    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None
    
    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        
        if role != Qt.DisplayRole:
            return None
        
        ts = self.tombstones[index.row()]
        col = index.column()
        
        if col == 0:  # Файл
            return ts.get('relpath', '')
        elif col == 1:  # Сторона
            side = ts.get('side', '')
            return "Локально" if side == 'local' else "Облако" if side == 'remote' else side
        elif col == 2:  # Дата удаления
            ts_time = ts.get('ts', 0)
            if ts_time:
                return datetime.fromtimestamp(ts_time).strftime('%Y-%m-%d %H:%M')
            return ""
        elif col == 3:  # Статус
            is_dir = bool(ts.get('is_dir', False))
            if is_dir:
                return ""
            
            pending = ts.get('pending_op', '')
            if pending == 'delete_remote':
                return "Ожидает удаления в облаке"
            elif pending == 'delete_local':
                return "Ожидает удаления локально"
            elif pending == 'delete_remote_folder':
                return ""
            elif pending == 'delete_local_folder':
                return ""
            elif not pending:
                return "Выполнено"
            return pending
        elif col == 4:  # Истекает через
            retained = ts.get('retained_until', 0)
            if retained:
                days_left = int((retained - time.time()) / 86400)
                return str(max(0, days_left))
            return "?"
        
        return None
