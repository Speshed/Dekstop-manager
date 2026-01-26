# -*- coding: utf-8 -*-

import os
from typing import Optional

from PySide6.QtCore import (
    Qt, QSize, QModelIndex, QRect, QRectF, QPoint
)
from PySide6.QtGui import (
    QIcon, QPixmap, QPainter, QColor, QPen, QBrush, QCursor
)
from PySide6.QtWidgets import (
    QApplication, QTableView, QStyledItemDelegate, QStyleOptionViewItem,
    QStyle, QStyleOptionHeader, QAbstractItemView
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
# Selected should read stronger than hover.
_BTN_SELECTED_BG = QColor(247, 146, 30, int(255 * 0.28))
_BTN_PRESSED_BG = QColor(247, 146, 30, int(255 * 0.20))
_BTN_BORDER = QColor("#FFA74B")
_BTN_BORDER_PRESSED = QColor("#E07E12")
_TRANSPARENT_BRUSH = QBrush(QColor(0, 0, 0, 0))


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


def _paint_row_segment(
    painter: QtGui.QPainter,
    rect: QtCore.QRectF,
    *,
    is_first: bool,
    is_last: bool,
    fill: QColor,
    border: QColor | None,
    radius: float,
) -> None:
    """Paint a row highlight segment clipped to a single cell rect."""
    r = max(0.0, float(radius))

    # Fill: paint within the cell; cover column separators explicitly (below).
    fill_rr = QtCore.QRectF(rect)

    # Border: keep crisp and mostly inside the cell.
    rr = QtCore.QRectF(rect)
    rr.adjust(0.5, 0.5, -0.5, -0.5)

    painter.save()

    # Fill: keep it non-AA for middle cells to avoid hairline seams.
    painter.setPen(Qt.NoPen)
    grad = QtGui.QLinearGradient(fill_rr.topLeft(), fill_rr.bottomLeft())
    top = QColor(fill).lighter(106)
    bottom = QColor(fill).darker(102)
    grad.setColorAt(0.0, top)
    grad.setColorAt(1.0, bottom)
    painter.setBrush(QBrush(grad))
    if is_first or is_last:
        painter.setRenderHint(QPainter.Antialiasing, True)
    else:
        painter.setRenderHint(QPainter.Antialiasing, False)

    if is_first and is_last:
        painter.drawRoundedRect(fill_rr, r, r)
    elif is_first:
        path = QtGui.QPainterPath()
        path.moveTo(fill_rr.right(), fill_rr.top())
        path.lineTo(fill_rr.left() + r, fill_rr.top())
        path.arcTo(QtCore.QRectF(fill_rr.left(), fill_rr.top(), 2 * r, 2 * r), 90, 90)
        path.lineTo(fill_rr.left(), fill_rr.bottom() - r)
        path.arcTo(QtCore.QRectF(fill_rr.left(), fill_rr.bottom() - 2 * r, 2 * r, 2 * r), 180, 90)
        path.lineTo(fill_rr.right(), fill_rr.bottom())
        path.closeSubpath()
        painter.drawPath(path)
    elif is_last:
        path = QtGui.QPainterPath()
        path.moveTo(fill_rr.left(), fill_rr.top())
        path.lineTo(fill_rr.right() - r, fill_rr.top())
        path.arcTo(QtCore.QRectF(fill_rr.right() - 2 * r, fill_rr.top(), 2 * r, 2 * r), 90, -90)
        path.lineTo(fill_rr.right(), fill_rr.bottom() - r)
        path.arcTo(QtCore.QRectF(fill_rr.right() - 2 * r, fill_rr.bottom() - 2 * r, 2 * r, 2 * r), 0, -90)
        path.lineTo(fill_rr.left(), fill_rr.bottom())
        path.closeSubpath()
        painter.drawPath(path)
    else:
        painter.fillRect(fill_rr, painter.brush())

    # Border: avoid per-column seams by slightly overlapping segments.
    if border is None:
        painter.restore()
        return

    painter.setBrush(Qt.NoBrush)
    pen = QPen(border, 1)
    try:
        pen.setCosmetic(True)
    except Exception:
        pass
    painter.setPen(pen)

    if is_first and is_last:
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.drawRoundedRect(rr, r, r)
        painter.restore()
        return

    # Outer sides
    painter.setRenderHint(QPainter.Antialiasing, True)
    if is_first:
        left = QtGui.QPainterPath()
        left.moveTo(rr.left() + r, rr.top())
        left.arcTo(QtCore.QRectF(rr.left(), rr.top(), 2 * r, 2 * r), 90, 90)
        left.lineTo(rr.left(), rr.bottom() - r)
        left.arcTo(QtCore.QRectF(rr.left(), rr.bottom() - 2 * r, 2 * r, 2 * r), 180, 90)
        left.moveTo(rr.left() + r, rr.bottom())
        painter.drawPath(left)

    if is_last:
        right = QtGui.QPainterPath()
        right.moveTo(rr.right() - r, rr.top())
        right.arcTo(QtCore.QRectF(rr.right() - 2 * r, rr.top(), 2 * r, 2 * r), 90, -90)
        right.lineTo(rr.right(), rr.bottom() - r)
        right.arcTo(QtCore.QRectF(rr.right() - 2 * r, rr.bottom() - 2 * r, 2 * r, 2 * r), 0, -90)
        right.moveTo(rr.right() - r, rr.bottom())
        painter.drawPath(right)

    painter.restore()


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

            # Draw PNG indicator icons and return early
            state = index.model().data(index, Qt.CheckStateRole)
            if state == Qt.Checked:
                _icon_path = CHECK_ICON_ON_PATH
            elif state == Qt.PartiallyChecked:
                _icon_path = CHECK_ICON_MID_PATH
            else:
                _icon_path = CHECK_ICON_OFF_PATH

            _dark = _is_dark_mode()
            try:
                if _dark:
                    _icon = load_white_icon(_icon_path)
                    _pm = _icon.pixmap(size, size)
                else:
                    _icon = QIcon(_icon_path)
                    _pm = _icon.pixmap(size, size)
            except Exception:
                _pm = QPixmap()

            if _pm.isNull() and _icon_path:
                try:
                    _base = QPixmap(_icon_path)
                    if not _base.isNull():
                        if _dark:
                            _base = _tint_pixmap(_base, QColor(Qt.white))
                        _pm = _base.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                except Exception:
                    pass

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

                # On hover/selection, force black icon (light theme only)
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
                            state = model.data(index, Qt.CheckStateRole)
                            new_state = Qt.Unchecked if state == Qt.Checked else Qt.Checked

                            widget = option.widget
                            selected_rows = set()
                            if widget:
                                sm = widget.selectionModel()
                                if sm:
                                    selected_indexes = sm.selectedIndexes()
                                    for idx in selected_indexes:
                                        if idx.column() == 0:
                                            selected_rows.add(idx.row())

                            selected_rows.add(index.row())
                            for row in selected_rows:
                                idx0 = model.index(row, 0)
                                model.setData(idx0, new_state, Qt.CheckStateRole)
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

            try:
                model = view.model() if view is not None and hasattr(view, "model") else None
                first_col, last_col = _visible_col_bounds(view, model) if view is not None else (0, 0)
                is_first = (index.column() == first_col)
                is_last = (index.column() == last_col)
            except Exception:
                is_first = (index.column() == 0)
                is_last = False

            r = min(14.0, (option.rect.height() - 2) / 2.0)
            _paint_row_segment(
                painter,
                QRectF(option.rect),
                is_first=is_first,
                is_last=is_last,
                fill=bg,
                border=None,
                radius=r,
            )

        if bg is not None and not _is_dark_mode():
            for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
                opt.palette.setColor(group, QPalette.Text, QColor("#000000"))
                opt.palette.setColor(group, QPalette.HighlightedText, QColor("#000000"))
                opt.palette.setColor(group, QPalette.WindowText, QColor("#000000"))
                opt.palette.setColor(group, QPalette.ButtonText, QColor("#000000"))
                opt.palette.setColor(group, QPalette.BrightText, QColor("#000000"))

        self.inner.paint(painter, opt, index)

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
            # Prevent per-cell default background from wiping our paint.
            try:
                opt.backgroundBrush = _TRANSPARENT_BRUSH
            except Exception:
                pass

            try:
                model = view.model() if view is not None and hasattr(view, "model") else None
                first_col, last_col = _visible_col_bounds(view, model)
                is_first = (index.column() == first_col)
                is_last = (index.column() == last_col)
            except Exception:
                is_first = (index.column() == 0)
                is_last = False

            r = min(14.0, (option.rect.height() - 2) / 2.0)
            _paint_row_segment(
                painter,
                QRectF(option.rect),
                is_first=is_first,
                is_last=is_last,
                fill=bg,
                border=None,
                radius=r,
            )

        self.inner.paint(painter, opt, index) if hasattr(self, 'inner') else super().paint(painter, opt, index)

    def sizeHint(self, option, index):
        sz = super().sizeHint(option, index)
        min_h = self._icon_size.height() + 6
        if sz.height() < min_h:
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
        opt.state &= ~QStyle.State_HasFocus
        opt.state &= ~QStyle.State_Selected
        opt.state &= ~QStyle.State_MouseOver

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
            painter.save()

            vp = option.widget.viewport() if (hasattr(option.widget, "viewport") and option.widget.viewport()) else None
            full_w = (vp.width() if vp is not None else (option.widget.width() if option.widget else opt.rect.width()))
            highlight_rect = QRectF(0, float(opt.rect.y()), float(full_w), float(opt.rect.height()))

            r = min(14.0, (opt.rect.height() - 2) / 2.0)
            _paint_row_segment(
                painter,
                highlight_rect,
                is_first=True,
                is_last=True,
                fill=fill,
                border=None,
                radius=r,
            )

            painter.restore()

            # Ensure the inner delegate doesn't paint over the highlight.
            try:
                opt.backgroundBrush = _TRANSPARENT_BRUSH
            except Exception:
                pass

            if not _is_dark_mode():
                for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
                    opt.palette.setColor(group, QPalette.Text, QColor("#000000"))
                    opt.palette.setColor(group, QPalette.HighlightedText, QColor("#000000"))
                    opt.palette.setColor(group, QPalette.WindowText, QColor("#000000"))
                    opt.palette.setColor(group, QPalette.ButtonText, QColor("#000000"))
                    opt.palette.setColor(group, QPalette.BrightText, QColor("#000000"))

        self.inner.paint(painter, opt, index)

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
