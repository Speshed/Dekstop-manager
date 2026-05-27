# -*- coding: utf-8 -*-

import os
from typing import Optional

from PySide6.QtCore import (
    Qt, QSize, QModelIndex, QRect, QRectF, QPoint
)
from PySide6.QtGui import (
    QIcon, QPixmap, QPainter, QColor, QPen, QBrush, QCursor, QFontMetrics
)
from PySide6.QtWidgets import (
    QApplication, QTableView, QStyledItemDelegate, QStyleOptionViewItem,
    QStyle, QStyleOptionHeader, QAbstractItemView, QTreeView, QTreeWidget
)
from PySide6.QtGui import QPalette
from PySide6 import QtCore, QtGui, QtWidgets

# Imports from widgets module
from .widgets import (
    _is_dark_mode, load_white_icon, _tint_pixmap,
    CHECK_ICON_OFF_PATH, CHECK_ICON_ON_PATH, CHECK_ICON_MID_PATH,
    CHECKBOX_COLUMN_WIDTH, _branch_arrow_icon
)


# Row highlight style should match button hover/pressed visuals from QSS.
_BTN_HOVER_BG = QColor(247, 146, 30, int(255 * 0.10))
_BTN_SELECTED_BG = QColor(247, 146, 30, int(255 * 0.28))
_BTN_PRESSED_BG = QColor(247, 146, 30, int(255 * 0.20))
_BTN_BORDER = QColor("#FFA74B")
_BTN_BORDER_PRESSED = QColor("#E07E12")
_TRANSPARENT_BRUSH = QBrush(QColor(0, 0, 0, 0))


def _opaque_over_base(top: QColor, base: QColor) -> QColor:
    """Return opaque color equivalent to drawing `top` over `base` once."""
    try:
        a = float(top.alphaF())
        if a >= 1.0:
            return QColor(top.red(), top.green(), top.blue(), 255)
        ia = 1.0 - a
        return QColor(
            int(round(top.red() * a + base.red() * ia)),
            int(round(top.green() * a + base.green() * ia)),
            int(round(top.blue() * a + base.blue() * ia)),
            255,
        )
    except Exception:
        return QColor(top.red(), top.green(), top.blue(), 255)


class RowHighlightEventFilter(QtCore.QObject):
    """Event filter that paints row backgrounds on viewport before Qt processes paint."""
    
    def __init__(self, view, parent=None):
        super().__init__(parent)
        self._view = view
        self._transparent = QColor(0, 0, 0, 0)
    
    def eventFilter(self, obj, event):
        # Paint our backgrounds BEFORE Qt processes the paint event
        if event.type() == QtCore.QEvent.Type.Paint:
            # Set transparent highlight
            pal = obj.palette()
            pal.setColor(QPalette.Active, QPalette.Highlight, self._transparent)
            pal.setColor(QPalette.Inactive, QPalette.Highlight, self._transparent)
            pal.setColor(QPalette.Disabled, QPalette.Highlight, self._transparent)
            obj.setPalette(pal)
            
            # Paint row backgrounds - the painter is already active from Qt
            _paint_row_backgrounds_on_viewport(self._view, obj)
        
        return super().eventFilter(obj, event)


def install_viewport_row_highlighter(view):
    """Install row highlight painting on a QTableView or QTreeView."""
    transparent = QColor(0, 0, 0, 0)
    
    # Set transparent highlight on view palette
    view_pal = view.palette()
    view_pal.setColor(QPalette.Active, QPalette.Highlight, transparent)
    view_pal.setColor(QPalette.Inactive, QPalette.Highlight, transparent)
    view_pal.setColor(QPalette.Disabled, QPalette.Highlight, transparent)
    view.setPalette(view_pal)
    
    # Install event filter on viewport
    viewport = view.viewport()
    try:
        vp_pal = viewport.palette()
        vp_pal.setColor(QPalette.Active, QPalette.Highlight, transparent)
        vp_pal.setColor(QPalette.Inactive, QPalette.Highlight, transparent)
        vp_pal.setColor(QPalette.Disabled, QPalette.Highlight, transparent)
        viewport.setPalette(vp_pal)
    except Exception:
        pass
    filter_obj = RowHighlightEventFilter(view, viewport)
    viewport.installEventFilter(filter_obj)
    
    # Store reference to prevent GC
    view._row_highlight_filter = filter_obj


def _paint_row_backgrounds_on_viewport(view, viewport):
    hover_row = getattr(view, "_hover_row", -1)
    pressed_row = getattr(view, "_pressed_row", -1)
    hover_index = getattr(view, "_hover_index", QModelIndex())
    pressed_index = getattr(view, "_pressed_index", QModelIndex())
    
    model = view.model()
    if model is None:
        return
    
    sm = view.selectionModel()
    selected_rows = set()
    selected_indexes = []
    if sm:
        for idx in sm.selectedRows():
            if idx.isValid():
                selected_rows.add(idx.row())
                selected_indexes.append(idx)
    
    painter = QPainter(viewport)
    painter.setPen(Qt.NoPen)
    painter.setRenderHint(QPainter.Antialiasing, True)
    
    is_tree = isinstance(view, (QTreeView, QTreeWidget))
    
    if is_tree:
        _paint_tree_rows(view, viewport, painter, hover_index, pressed_index, selected_indexes)
    else:
        _paint_table_rows(view, viewport, painter, hover_row, pressed_row, selected_rows)
    
    painter.end()


def _paint_table_rows(view, viewport, painter, hover_row, pressed_row, selected_rows):
    model = view.model()
    if model is None:
        return
    
    count = model.rowCount()
    painted = 0
    for row in range(count):
        if row in selected_rows:
            bg = _BTN_SELECTED_BG
        elif row == pressed_row:
            bg = _BTN_PRESSED_BG
        elif row == hover_row:
            bg = _BTN_HOVER_BG
        else:
            continue
        
        try:
            y = view.rowViewportPosition(row)
            h = view.rowHeight(row)
            
            if y + h < 0 or y > viewport.height():
                continue
            
            row_rect = QRectF(0, y, viewport.width(), h)
            r = min(14.0, (h - 2) / 2.0)
            painter.setBrush(QBrush(bg))
            painter.drawRoundedRect(row_rect, r, r)
        except:
            pass


def _paint_tree_rows(view, viewport, painter, hover_index, pressed_index, selected_indexes):
    if not hasattr(view, 'topLevelItemCount'):
        return

    for i in range(view.topLevelItemCount()):
        _paint_tree_item_rows(view, viewport, painter, view.topLevelItem(i), 
                              hover_index, pressed_index, selected_indexes)


def _paint_tree_item_rows(view, viewport, painter, item, hover_index, pressed_index, selected_indexes):
    if item is None:
        return
    
    try:
        index = view.indexFromItem(item)
        is_selected = False
        for sidx in selected_indexes:
            try:
                if sidx.isValid() and sidx == index:
                    is_selected = True
                    break
            except Exception:
                continue
        is_pressed = pressed_index.isValid() and (index == pressed_index)
        is_hovered = hover_index.isValid() and (index == hover_index)
        
        if is_selected:
            bg = _BTN_SELECTED_BG
        elif is_pressed:
            bg = _BTN_PRESSED_BG
        elif is_hovered:
            bg = _BTN_HOVER_BG
        else:
            bg = None
        
        if bg is not None:
            rect = view.visualRect(index)
            if rect.isValid():
                base_col = viewport.palette().color(QPalette.Base)
                if not base_col.isValid():
                    base_col = viewport.palette().color(QPalette.Window)
                fill_col = _opaque_over_base(bg, base_col)
                row_rect = QRectF(0, rect.y(), viewport.width(), rect.height())
                r = min(14.0, (rect.height() - 2) / 2.0)
                painter.setBrush(QBrush(fill_col))
                painter.drawRoundedRect(row_rect, r, r)
                # Mask possible native seams both at viewport and item edges.
                painter.fillRect(QRect(0, rect.y(), 2, rect.height()), QBrush(fill_col))
                painter.fillRect(QRect(max(0, viewport.width() - 2), rect.y(), 2, rect.height()), QBrush(fill_col))
                painter.fillRect(QRect(max(0, rect.left() - 1), rect.y(), 2, rect.height()), QBrush(fill_col))
                painter.fillRect(QRect(rect.right(), rect.y(), 2, rect.height()), QBrush(fill_col))
        
        for c in range(item.childCount()):
            _paint_tree_item_rows(view, viewport, painter, item.child(c), 
                                  hover_index, pressed_index, selected_indexes)
    except:
        pass


def _visible_col_bounds(view: QtWidgets.QWidget, model: QtCore.QAbstractItemModel | None) -> tuple[int, int]:
    """Return (first_visible_col, last_visible_col) for table-like views."""
    try:
        if model is None:
            return (0, 0)
        count = int(model.columnCount())
        if count <= 0:
            return (0, 0)
        if not hasattr(view, "isColumnHidden"):
            return (0, max(0, count - 1))
        first = 0
        last = max(0, count - 1)
        for c in range(count):
            try:
                if not view.isColumnHidden(c):
                    first = c
                    break
            except Exception:
                continue
        for c in range(count - 1, -1, -1):
            try:
                if not view.isColumnHidden(c):
                    last = c
                    break
            except Exception:
                continue
        return (first, last)
    except Exception:
        return (0, 0)


class CheckBoxDelegate(QStyledItemDelegate):
    BOX = 18
    RADIUS = 3
    BORDER_W = 2
    FIXED_WIDTH = CHECKBOX_COLUMN_WIDTH

    def paint(self, painter, option, index):
        if index.column() != 0:
            return super().paint(painter, option, index)

        r = option.rect
        size = self.BOX
        actual_width = min(r.width(), self.FIXED_WIDTH)
        x = r.x() + (actual_width - size) // 2
        y = r.y() + (r.height() - size) // 2

        painter.save()
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

            state = index.model().data(index, Qt.CheckStateRole)
            if state == Qt.Checked:
                _icon_path = CHECK_ICON_ON_PATH
            elif state == Qt.PartiallyChecked:
                _icon_path = CHECK_ICON_MID_PATH
            else:
                _icon_path = CHECK_ICON_OFF_PATH

            _dark = _is_dark_mode()
            _pm = QPixmap()
            try:
                if _dark:
                    _icon = load_white_icon(_icon_path)
                    _pm = _icon.pixmap(size, size)
                    if _pm.isNull():
                        _base = QPixmap(_icon_path)
                        if not _base.isNull():
                            _base = _tint_pixmap(_base, QColor(Qt.white))
                            _pm = _base.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                else:
                    _base = QPixmap(_icon_path)
                    if not _base.isNull():
                        _pm = _base.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            except Exception:
                _pm = QPixmap()

            if not _pm.isNull():
                row_hover = getattr(option.widget, "_hover_row", -1)
                is_row_hover = (index.row() == row_hover)

                is_selected = bool(option.state & QStyle.State_Selected)
                if not is_selected and option.widget:
                    try:
                        sm = option.widget.selectionModel()
                        if sm and sm.isRowSelected(index.row(), QModelIndex()):
                            is_selected = True
                    except Exception:
                        pass

                if not _dark and (is_row_hover or is_selected):
                    temp_pm = QPixmap(_pm.size())
                    temp_pm.fill(Qt.transparent)
                    p = QPainter(temp_pm)
                    p.drawPixmap(0, 0, _pm)
                    p.setCompositionMode(QPainter.CompositionMode_SourceIn)
                    p.fillRect(temp_pm.rect(), QColor("#000000"))
                    p.end()
                    _pm = temp_pm

                _dx = x + (size - _pm.width()) // 2
                _dy = y + (size - _pm.height()) // 2
                painter.drawPixmap(int(_dx), int(_dy), _pm)
                return

            rect = QRectF(x, y, size, size)
            dark = bool(getattr(option.widget, "_dark_theme", False))

            hover_idx = getattr(option.widget, "_hover_index", QModelIndex())
            pressed_idx = getattr(option.widget, "_pressed_index", QModelIndex())
            row_hover = getattr(option.widget, "_hover_row", -1)
            is_hover = hover_idx.isValid() and index == hover_idx
            is_pressed = pressed_idx.isValid() and index == pressed_idx
            is_selected = bool(option.state & QStyle.State_Selected)
            is_row_hover = (index.row() == row_hover)

            hover_fill = _BTN_HOVER_BG
            selected_fill = _BTN_SELECTED_BG
            pressed_fill = _BTN_PRESSED_BG
            checked_tick = QColor("#FFFFFF") if dark else QColor("#000000")
            border_col = QColor("#FFFFFF") if dark else QColor("#222")

            state = index.model().data(index, Qt.CheckStateRole)
            fill_brush = Qt.NoBrush
            if state == Qt.Checked:
                fill_brush = Qt.NoBrush
            elif is_hover and state != Qt.Checked:
                fill_brush = QBrush(hover_fill)
            else:
                fill_brush = Qt.NoBrush

            if is_pressed:
                fill_brush = QBrush(pressed_fill)
            elif is_selected:
                fill_brush = QBrush(selected_fill)
            elif is_row_hover or is_hover:
                fill_brush = QBrush(hover_fill)
            if dark and (is_row_hover or is_hover or is_selected or is_pressed):
                border_col = QColor("#222222")

            painter.setPen(QPen(border_col, max(1, int(self.BORDER_W))))
            if isinstance(fill_brush, QBrush) and not fill_brush.style() == Qt.NoBrush:
                painter.setBrush(fill_brush)
            else:
                painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect, self.RADIUS, self.RADIUS)

            if state == Qt.Checked:
                if dark and (is_row_hover or is_hover or is_selected or is_pressed):
                    checked_tick = QColor("#222222")
                path = QtGui.QPainterPath()
                path.moveTo(rect.left() + 0.22 * size, rect.top() + 0.55 * size)
                path.lineTo(rect.left() + 0.44 * size, rect.top() + 0.75 * size)
                path.lineTo(rect.left() + 0.80 * size, rect.top() + 0.30 * size)
                painter.setPen(QPen(checked_tick, max(2, int(size * 0.12)), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                painter.setBrush(Qt.NoBrush)
                painter.drawPath(path)
        finally:
            painter.restore()

    def sizeHint(self, option, index):
        if index.column() == 0:
            return QSize(self.FIXED_WIDTH, 28)
        return super().sizeHint(option, index)

    def editorEvent(self, event, model, option, index):
        if index.column() == 0 and index.flags() & Qt.ItemIsUserCheckable:
            et = event.type()
            if et == QtCore.QEvent.MouseButtonPress or et == QtCore.QEvent.MouseButtonRelease:
                mouse_btn = getattr(event, "button", lambda: Qt.NoButton)()
                if mouse_btn == Qt.LeftButton:
                    rect = option.rect
                    size = self.BOX
                    actual_width = min(rect.width(), self.FIXED_WIDTH)
                    x = rect.x() + (actual_width - size) // 2
                    y = rect.y() + (rect.height() - size) // 2
                    checkbox_rect = QRect(x, y, size, size)

                    cursor_pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
                    if checkbox_rect.contains(cursor_pos):
                        if et == QtCore.QEvent.MouseButtonRelease:
                            widget = option.widget
                            view = widget if hasattr(widget, "selectionModel") else None
                            window = view.window() if view and hasattr(view, "window") else None
                            helper = getattr(window, "_toggle_checked_from_checkbox_click", None)
                            if callable(helper) and helper(index):
                                return True
                            state = model.data(index, Qt.CheckStateRole)
                            new_state = Qt.Unchecked if state == Qt.Checked else Qt.Checked
                            model.setData(index, new_state, Qt.CheckStateRole)
                            return True
                        return True
        return False


class CheckBoxDelegateBg(QStyledItemDelegate):
    """Фон строки для колонки с галочками: hover - pressed - selected, затем рисуем исходный чекбокс."""
    def __init__(self, table, inner_delegate=None):
        super().__init__(table)
        self.inner = inner_delegate or CheckBoxDelegate(table)
        self.table = table

    def paint(self, painter, option, index):
        view = option.widget
        row = index.row()

        opt = QStyleOptionViewItem(option)
        opt.state &= ~QStyle.State_HasFocus
        opt.state &= ~QStyle.State_Selected
        opt.state &= ~QStyle.State_MouseOver
        
        transparent_highlight = QColor(0, 0, 0, 0)
        for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
            opt.palette.setColor(group, QPalette.Highlight, transparent_highlight)
            opt.palette.setColor(group, QPalette.HighlightedText, opt.palette.color(group, QPalette.Text))

        is_selected = bool(option.state & QStyle.State_Selected)
        hover_row = getattr(view, "_hover_row", -1)
        pressed_row = getattr(view, "_pressed_row", -1)
        is_hovered = (row == hover_row)
        is_pressed = (row == pressed_row)

        hover_color = _BTN_HOVER_BG
        selected_color = _BTN_SELECTED_BG
        pressed_color = _BTN_PRESSED_BG

        bg = None
        if is_selected:
            bg = selected_color
        elif is_pressed:
            bg = pressed_color
        elif is_hovered and not is_selected:
            bg = hover_color

        if bg is not None:
            try:
                opt.backgroundBrush = _TRANSPARENT_BRUSH
            except Exception:
                pass
            opt.showDecorationSelected = False

        # Let inner delegate draw cell content, then mask possible native seam on cell border.
        
        if bg is not None and not _is_dark_mode():
            for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
                opt.palette.setColor(group, QPalette.Text, QColor("#000000"))
                opt.palette.setColor(group, QPalette.HighlightedText, QColor("#000000"))
                opt.palette.setColor(group, QPalette.WindowText, QColor("#000000"))
                opt.palette.setColor(group, QPalette.ButtonText, QColor("#000000"))
                opt.palette.setColor(group, QPalette.BrightText, QColor("#000000"))

        self.inner.paint(painter, opt, index)

        if bg is not None:
            try:
                base_col = opt.palette.color(QPalette.Base)
                if not base_col.isValid():
                    base_col = opt.palette.color(QPalette.Window)
                seam_col = _opaque_over_base(bg, base_col)
                painter.save()
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(seam_col))
                r = option.rect
                painter.fillRect(QRect(r.left(), r.top(), 1, r.height()), QBrush(seam_col))
                painter.fillRect(QRect(r.right(), r.top(), 1, r.height()), QBrush(seam_col))
                painter.restore()
            except Exception:
                pass

    def editorEvent(self, event, model, option, index):
        if self.inner:
            return self.inner.editorEvent(event, model, option, index)
        return super().editorEvent(event, model, option, index)


class RowHoverDelegate(QStyledItemDelegate):
    """
    Делегат для таблиц/деревьев:
    - Рисует фон всей строки при hover/pressed/selected в фирменных цветах.


    - Принудительно задаёт единый размер иконок (логотипов) через option.decorationSize.
    - Берёт служебные атрибуты из вида: _hover_row и _pressed_row (если есть).
      Если их нет — просто игнорирует.

    Пример инициализации:
        delegate = RowHoverDelegate(icon_size=QtCore.QSize(22, 22), parent=self.table)
        self.table.setItemDelegate(delegate)
        self.table.setIconSize(delegate.icon_size())

    Цвета по умолчанию согласованы со стилем проекта:
        hover    #FFE3C2
        selected #FFC37A
        pressed  #FFCA91
    """

    def __init__(
        self,
        icon_size: QtCore.QSize = QtCore.QSize(22, 22),
        hover_color: QtGui.QColor = _BTN_HOVER_BG,
        selected_color: QtGui.QColor = _BTN_SELECTED_BG,
        pressed_color: QtGui.QColor = _BTN_PRESSED_BG,
        parent: QtWidgets.QWidget | None = None,
    ):
        super().__init__(parent)
        self._icon_size = QSize(icon_size)
        self._hover_color = QColor(hover_color)
        self._selected_color = QColor(selected_color)
        self._pressed_color = QColor(pressed_color)

    def icon_size(self) -> QtCore.QSize:
        return QSize(self._icon_size)

    def initStyleOption(self, option: QStyleOptionViewItem, index: QtCore.QModelIndex) -> None:
        super().initStyleOption(option, index)
        option.decorationSize = QSize(self._icon_size)
        option.state &= ~QStyle.State_HasFocus

    def paint(self, painter: QtGui.QPainter, option: QStyleOptionViewItem, index: QtCore.QModelIndex) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        
        transparent_highlight = QColor(0, 0, 0, 0)
        for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
            opt.palette.setColor(group, QPalette.Highlight, transparent_highlight)
            opt.palette.setColor(group, QPalette.HighlightedText, opt.palette.color(group, QPalette.Text))

        view = opt.widget
        row = index.row()

        is_selected = bool(opt.state & QStyle.State_Selected)
        hover_row = getattr(view, "_hover_row", -1)
        pressed_row = getattr(view, "_pressed_row", -1)
        is_hovered = (row == hover_row)
        is_pressed = (row == pressed_row)

        opt.state &= ~QStyle.State_MouseOver
        opt.state &= ~QStyle.State_Selected

        bg = None
        if is_selected:
            bg = self._selected_color
        elif is_pressed:
            bg = self._pressed_color
        elif is_hovered and not is_selected:
            bg = self._hover_color

        if bg is not None and not _is_dark_mode():
            for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
                opt.palette.setColor(group, QPalette.Text, QColor("#000000"))
                opt.palette.setColor(group, QPalette.HighlightedText, QColor("#000000"))
                opt.palette.setColor(group, QPalette.WindowText, QColor("#000000"))
                opt.palette.setColor(group, QPalette.ButtonText, QColor("#000000"))
                opt.palette.setColor(group, QPalette.BrightText, QColor("#000000"))

        if bg is not None:
            try:
                opt.backgroundBrush = _TRANSPARENT_BRUSH
            except Exception:
                pass
            opt.showDecorationSelected = False

        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)

        if bg is not None:
            try:
                base_col = opt.palette.color(QPalette.Base)
                if not base_col.isValid():
                    base_col = opt.palette.color(QPalette.Window)
                seam_col = _opaque_over_base(bg, base_col)
                painter.save()
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(seam_col))
                r = option.rect
                painter.fillRect(QRect(r.left(), r.top(), 1, r.height()), QBrush(seam_col))
                painter.fillRect(QRect(r.right(), r.top(), 1, r.height()), QBrush(seam_col))
                painter.restore()
            except Exception:
                pass

    def sizeHint(self, option, index):
        sz = super().sizeHint(option, index)
        min_h = self._icon_size.height() + 6
        if index.column() != 1:
            if sz.height() < min_h:
                sz.setHeight(min_h)
            return sz

        view = option.widget
        col_w = 0
        if view is not None:
            try:
                col_w = int(view.columnWidth(1))
            except Exception:
                col_w = 0
        if col_w <= 0 and option.rect.width() > 0:
            col_w = int(option.rect.width())

        text = index.data(Qt.DisplayRole)
        if text:
            fm = QFontMetrics(option.font)
            icon_w = self._icon_size.width() + 10
            text_w = max(40, col_w - icon_w - 8) if col_w > 0 else 320
            rect = fm.boundingRect(
                QRect(0, 0, text_w, 2000),
                Qt.AlignLeft | Qt.TextWordWrap,
                str(text),
            )
            line_h = fm.lineSpacing()
            text_h = min(rect.height(), line_h * 2 + 4)
            sz.setHeight(max(min_h, text_h + 8))
        elif sz.height() < min_h:
            sz.setHeight(min_h)
        return sz


class MenuLikeTreeDelegate(QStyledItemDelegate):
    def __init__(self, parent=None, inner_delegate=None):
        super().__init__(parent)
        self.inner = inner_delegate or QStyledItemDelegate(parent)

    def paint(self, painter, option, index):
        hover_idx   = getattr(option.widget, "_hover_index", QModelIndex())
        pressed_idx = getattr(option.widget, "_pressed_index", QModelIndex())

        is_hover    = hover_idx.isValid() and index == hover_idx
        is_pressed  = pressed_idx.isValid() and index == pressed_idx
        is_selected = bool(option.state & QStyle.State_Selected)

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.state &= ~QStyle.State_HasFocus
        opt.state &= ~QStyle.State_Selected
        opt.state &= ~QStyle.State_MouseOver
        opt.showDecorationSelected = False

        transparent_highlight = QColor(0, 0, 0, 0)
        for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
            opt.palette.setColor(group, QPalette.Highlight, transparent_highlight)
            opt.palette.setColor(group, QPalette.HighlightedText, opt.palette.color(group, QPalette.Text))

        hover_color = _BTN_HOVER_BG
        selected_color = _BTN_SELECTED_BG
        pressed_color = _BTN_PRESSED_BG

        fill = None
        if is_pressed:
            fill = pressed_color
        elif is_selected:
            fill = selected_color
        elif is_hover and not is_selected:
            fill = hover_color

        if fill is not None:
            opt.showDecorationSelected = False
            opt.backgroundBrush = _TRANSPARENT_BRUSH

            try:
                vp = option.widget.viewport() if (option.widget is not None and hasattr(option.widget, "viewport")) else None
                full_w = vp.width() if vp is not None else option.rect.width()
                base_col = opt.palette.color(QPalette.Base)
                if not base_col.isValid():
                    base_col = opt.palette.color(QPalette.Window)
                fill_col = _opaque_over_base(fill, base_col)
                painter.save()
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(fill_col))
                row_rect = QRectF(0, float(opt.rect.y()), float(full_w), float(opt.rect.height()))
                r = min(14.0, (opt.rect.height() - 2) / 2.0)
                painter.drawRoundedRect(row_rect, r, r)
                painter.restore()
            except Exception:
                pass

            if _is_dark_mode():
                for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
                    opt.palette.setColor(group, QPalette.Text, QColor("#FFFFFF"))
                    opt.palette.setColor(group, QPalette.HighlightedText, QColor("#FFFFFF"))
                    opt.palette.setColor(group, QPalette.WindowText, QColor("#FFFFFF"))
                    opt.palette.setColor(group, QPalette.ButtonText, QColor("#FFFFFF"))
                    opt.palette.setColor(group, QPalette.BrightText, QColor("#FFFFFF"))
            else:
                for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
                    opt.palette.setColor(group, QPalette.Text, QColor("#000000"))
                    opt.palette.setColor(group, QPalette.HighlightedText, QColor("#000000"))
                    opt.palette.setColor(group, QPalette.WindowText, QColor("#000000"))
                    opt.palette.setColor(group, QPalette.ButtonText, QColor("#000000"))
                    opt.palette.setColor(group, QPalette.BrightText, QColor("#000000"))

        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)

        if fill is not None:
            try:
                base_col = opt.palette.color(QPalette.Base)
                if not base_col.isValid():
                    base_col = opt.palette.color(QPalette.Window)
                seam_col = _opaque_over_base(fill, base_col)
                seam_rect = option.widget.visualRect(index) if option.widget is not None else option.rect
                painter.save()
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(seam_col))
                painter.fillRect(QRect(max(0, seam_rect.left() - 1), seam_rect.top(), 2, seam_rect.height()), QBrush(seam_col))
                painter.fillRect(QRect(seam_rect.right(), seam_rect.top(), 2, seam_rect.height()), QBrush(seam_col))
                painter.restore()
            except Exception:
                pass

        if hasattr(option.widget, 'itemFromIndex'):
            try:
                item = option.widget.itemFromIndex(index)
                if item:
                    tree = option.widget
                    indent = tree.indentation() if hasattr(tree, 'indentation') else 20
                    level = 0
                    parent = item.parent()
                    while parent:
                        level += 1
                        parent = parent.parent()

                    if item.childCount() > 0:
                        arrow_x = level * indent
                        arrow_y = opt.rect.y()
                        arrow_size = 10
                        arrow_rect = QRect(arrow_x, arrow_y, arrow_size + 4, opt.rect.height())

                        is_expanded = item.isExpanded()
                        direction = "down" if is_expanded else "right"
                        arrow_color = QColor("#FFFFFF") if _is_dark_mode() else QColor("#000000")

                        pm = _branch_arrow_icon(direction, arrow_color, arrow_size)
                        if not pm.isNull():
                            painter.save()
                            painter.setRenderHint(QPainter.Antialiasing, True)
                            x = arrow_rect.x() + (arrow_rect.width() - pm.width()) // 2
                            y = arrow_rect.y() + (arrow_rect.height() - pm.height()) // 2
                            painter.drawPixmap(int(x), int(y), pm)
                            painter.restore()

                    # Repaint folder icon as black for selected rows (light theme only)
                    if is_selected and not _is_dark_mode():
                        icon = item.icon(0)
                        if not icon.isNull():
                            icon_size = tree.iconSize() if hasattr(tree, 'iconSize') else QSize(16, 16)
                            original_pm = icon.pixmap(icon_size)
                            if not original_pm.isNull():
                                black_pm = _tint_pixmap(original_pm, QColor("#000000"))
                                icon_x = opt.rect.x() - icon_size.width() - 4
                                icon_y = opt.rect.y() + (opt.rect.height() - icon_size.height()) / 2
                                painter.save()
                                painter.setRenderHint(QPainter.Antialiasing, True)
                                painter.drawPixmap(int(icon_x), int(icon_y), black_pm)
                                painter.restore()
            except Exception:
                pass
