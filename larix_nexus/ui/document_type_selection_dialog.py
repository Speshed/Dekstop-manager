import typing

from PySide6 import QtCore
from PySide6.QtCore import Qt, QRect
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QHeaderView,
    QSizePolicy,
    QStyle,
    QStyleOptionButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from larix_nexus.utils.theme import _is_dark_mode
from larix_nexus.utils.helpers import _set_window_theme_dark


class DocumentTypeSelectionDialog(QDialog):
    def __init__(self, parent: QWidget | None, tasks: list[dict], types_map: dict):
        super().__init__(parent)
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.setModal(True)
        self.setWindowTitle("Выбор типа документа")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(640)
        self.setMinimumHeight(360)
        self.resize(720, 420)

        try:
            if _is_dark_mode():
                _set_window_theme_dark(self, dark=True)
        except Exception:
            pass

        self.tasks = tasks
        self.types_map = types_map
        self.combos: dict[str, QComboBox] = {}
        self.checkboxes: dict[str, QCheckBox] = {}
        self._bulk_toggle_guard = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 8)
        layout.setSpacing(8)

        info_label = QLabel("Выберите тип документа для файлов:")
        layout.addWidget(info_label)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["", "Файл", "Тип документа"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setWordWrap(False)

        class _SelectAllHeader(QHeaderView):
            toggled = QtCore.Signal(bool)

            def __init__(self, parent=None):
                super().__init__(Qt.Horizontal, parent)
                self.setSectionsClickable(True)
                self._state = Qt.CheckState.Unchecked

            def set_state(self, state: Qt.CheckState) -> None:
                if state != self._state:
                    self._state = state
                    self.viewport().update()

            def _checkbox_rect(self) -> QRect:
                rect = self.sectionRect(0)
                size = 16
                return QRect(
                    rect.center().x() - size // 2,
                    rect.center().y() - size // 2,
                    size,
                    size,
                )

            def paintSection(self, painter, rect, logicalIndex):
                super().paintSection(painter, rect, logicalIndex)
                if logicalIndex != 0:
                    return
                opt = QStyleOptionButton()
                opt.rect = self._checkbox_rect()
                opt.state = QStyle.State_Enabled
                if self._state == Qt.CheckState.Checked:
                    opt.state |= QStyle.State_On
                elif self._state == Qt.CheckState.PartiallyChecked:
                    opt.state |= QStyle.State_NoChange
                else:
                    opt.state |= QStyle.State_Off
                self.style().drawControl(QStyle.CE_CheckBox, opt, painter, self)

            def mousePressEvent(self, event):
                if self.logicalIndexAt(event.pos()) == 0 and self._checkbox_rect().contains(event.pos()):
                    new_checked = self._state != Qt.CheckState.Checked
                    self.toggled.emit(bool(new_checked))
                    event.accept()
                    return
                super().mousePressEvent(event)

        header = _SelectAllHeader(self.table)
        self.table.setHorizontalHeader(header)

        header.setStretchLastSection(False)
        header.setHighlightSections(False)
        header.setMinimumSectionSize(60)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 34)
        self.table.setColumnWidth(2, 240)
        self.table.verticalHeader().setVisible(False)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setStyleSheet(
            """
            QTableWidget::section {
                background-color: transparent;
                border: none;
                color: #888888;
                padding: 4px;
            }
            QTableWidget::section:hover {
                background-color: transparent;
            }
        """
        )
        layout.addWidget(self.table)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._populate_table()

        try:
            header.toggled.connect(self._toggle_all_rows)
        except Exception:
            pass

    def _populate_table(self):
        self.table.setRowCount(len(self.tasks))

        type_names: list[tuple[int, str]] = []
        for k, v in self.types_map.items():
            try:
                kid = int(str(k).strip())
            except Exception:
                continue
            type_names.append((kid, str(v)))
        type_names.sort(key=lambda x: x[0])

        for row, task in enumerate(self.tasks):
            checkbox_widget = QWidget()
            checkbox_layout = QHBoxLayout(checkbox_widget)
            checkbox_layout.setContentsMargins(0, 0, 0, 0)
            checkbox_layout.setAlignment(Qt.AlignCenter)
            checkbox = QCheckBox()
            checkbox.stateChanged.connect(self._sync_header_checkbox)
            checkbox_layout.addWidget(checkbox)
            checkbox_widget.setLayout(checkbox_layout)
            self.table.setCellWidget(row, 0, checkbox_widget)
            self.checkboxes[task["key"]] = checkbox

            name_item = QTableWidgetItem(task["name"])
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            name_item.setToolTip(task["name"])
            self.table.setItem(row, 1, name_item)

            combo = QComboBox()
            for kid, name in type_names:
                combo.addItem(f"{name} ({kid})", kid)
            combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            combo.currentIndexChanged.connect(lambda idx, r=row, t=task: self._on_combo_changed(r, t))
            self.table.setCellWidget(row, 2, combo)
            self.combos[task["key"]] = combo

        self.table.resizeRowsToContents()
        self._sync_header_checkbox()

    def _toggle_all_rows(self, checked: bool) -> None:
        if self._bulk_toggle_guard:
            return
        self._bulk_toggle_guard = True
        try:
            for cb in self.checkboxes.values():
                if isinstance(cb, QCheckBox):
                    cb.setChecked(bool(checked))
        finally:
            self._bulk_toggle_guard = False
            self._sync_header_checkbox()

    def _sync_header_checkbox(self) -> None:
        if self._bulk_toggle_guard:
            return
        try:
            header = self.table.horizontalHeader()
            if not hasattr(header, "set_state"):
                return
            boxes = [cb for cb in self.checkboxes.values() if isinstance(cb, QCheckBox)]
            if not boxes:
                header.set_state(Qt.CheckState.Unchecked)
                return
            checked = sum(1 for cb in boxes if cb.isChecked())
            if checked == 0:
                header.set_state(Qt.CheckState.Unchecked)
            elif checked == len(boxes):
                header.set_state(Qt.CheckState.Checked)
            else:
                header.set_state(Qt.CheckState.PartiallyChecked)
        except Exception:
            pass

    def _on_combo_changed(self, row: int, task: dict):
        combo = self.table.cellWidget(row, 2)
        if not isinstance(combo, QComboBox) or combo.currentIndex() < 0:
            return

        selected_type_id = combo.currentData()

        for r in range(self.table.rowCount()):
            checkbox = self.table.cellWidget(r, 0).findChild(QCheckBox)
            if isinstance(checkbox, QCheckBox) and checkbox.isChecked():
                row_combo = self.table.cellWidget(r, 2)
                if isinstance(row_combo, QComboBox) and row_combo != combo:
                    for i in range(row_combo.count()):
                        if row_combo.itemData(i) == selected_type_id:
                            row_combo.blockSignals(True)
                            row_combo.setCurrentIndex(i)
                            row_combo.blockSignals(False)
                            break

    def get_document_types(self) -> dict[str, int | None]:
        result: dict[str, int | None] = {}
        for task in self.tasks:
            combo = self.combos.get(task["key"])
            if isinstance(combo, QComboBox):
                result[task["key"]] = typing.cast(int | None, combo.currentData())
            else:
                result[task["key"]] = None
        return result
