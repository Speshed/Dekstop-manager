# -*- coding: utf-8 -*-
"""Context menu handlers injected into MainWindow.

This module exists to keep main_window.py smaller while preserving runtime
behavior. The functions are bound to MainWindow via inject_*.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QSize, QDate, QTimer, QPoint, QUrl, QEvent, QObject
from PySide6.QtGui import QAction, QPixmap, QIcon, QTextCharFormat, QColor, QPalette, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCalendarWidget,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from larix_nexus.models.files_table import FilesTableModel
from larix_nexus.utils.copy_logger import copy_log
from larix_nexus.utils.i18n import t
from larix_nexus.constants import SORT_ICON_UP_PATH, SORT_ICON_DOWN_PATH, STRUCTURE_ICON_PATH, OPEN_ICON_PATH, OPEN_LINK_ICON_PATH, EDIT_ICON_PATH, DELETE_ICON_PATH, TOOLBAR_DOWNLOAD_ICON, MOVE_FOLDER_ICON_PATH, COPY_ICON_PATH, VERSION_ICON_PATH, PUBLIC_LINK_ICON_PATH, PROPERTIES_ICON_PATH, INFORMATION_ICON_PATH

from .widgets import StickyMenu, CHECK_ICON_OFF_PATH, CHECK_ICON_ON_PATH
from .helpers import _is_folder

def build_folder_context_menu(self, node):
    try:
        menu = QMenu(self)
    except TypeError:
        menu = QMenu()
    menu.setObjectName("popupMenu")
    compact_menu_qss = "QMenu#popupMenu::item { padding-left: 6px; padding-right: 6px; }"
    menu.setStyleSheet(compact_menu_qss)
    actions = {}
    actions["open"] = menu.addAction(t("context.open"))
    icon = getattr(self, "_themed_icon", lambda path: QIcon(path))
    def set_icon(action, path):
        try: action.setIcon(icon(path))
        except Exception: pass
    set_icon(actions["open"], OPEN_ICON_PATH)
    actions["rename"] = menu.addAction(t("context.rename"))
    set_icon(actions["rename"], EDIT_ICON_PATH)
    actions["delete"] = menu.addAction(t("context.delete"))
    set_icon(actions["delete"], DELETE_ICON_PATH)
    menu.addSeparator()
    download = menu.addMenu(t("context.download"))
    set_icon(download.menuAction(), TOOLBAR_DOWNLOAD_ICON)
    actions["zip"] = download.addAction(t("context.download_as_zip"))
    actions["structure"] = download.addAction(t("context.download_structure"))
    menu.addSeparator()
    actions["copy"] = menu.addAction(t("context.copy_folder"))
    actions["move"] = menu.addAction(t("context.move_folder"))
    set_icon(actions["copy"], COPY_ICON_PATH)
    set_icon(actions["move"], MOVE_FOLDER_ICON_PATH)
    return menu, actions


class _CalendarNoBlueSelectionDelegate(QStyledItemDelegate):
    """Local delegate for date-filter calendars: suppress native focus/blue highlight."""

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        # Windows style can draw a blue focus/selection overlay on top of QSS.
        opt.state &= ~QStyle.State_HasFocus
        if opt.state & QStyle.State_Selected:
            try:
                opt.palette.setColor(QPalette.Highlight, QColor(0, 0, 0, 0))
                opt.palette.setColor(QPalette.HighlightedText, QColor("#000000"))
            except Exception:
                pass
        super().paint(painter, opt, index)


class _TableContextMenuWindowFilter(QObject):
    """Close one table popup when its owning window is deactivated or hidden."""

    def __init__(self, owner, menu):
        super().__init__(menu)
        self._owner = owner
        self._menu = menu

    def eventFilter(self, obj, event):
        if obj is self._owner:
            event_type = event.type()
            should_close = event_type in (QEvent.WindowDeactivate, QEvent.Hide)
            if event_type == QEvent.WindowStateChange:
                should_close = bool(self._owner.windowState() & Qt.WindowMinimized)
            if should_close:
                self._menu.close()
        return False


def table_context_menu(self, pos):
    idx = self.table.indexAt(pos)
    if not idx.isValid():
        return

    # выделим строку под курсором
    try:
        self.table.selectRow(idx.row())
    except Exception:
        pass

    # попытка понять - папка это или файл
    node = None
    try:
        node = self._node_from_index(idx)
    except Exception:
        pass

    is_folder = _is_folder(node) if isinstance(node, dict) else False
    if not is_folder:
        # запасной способ - по колонке "Тип"
        model = self.table.model()
        type_col = getattr(self, "_col_type", None)
        if type_col is None:
            try:
                for i in range(model.columnCount()):
                    hd = (model.headerData(i, Qt.Horizontal, Qt.DisplayRole) or "").strip().lower()
                    if hd in ("тип", "type"):
                        self._col_type = i
                        break
            except Exception:
                self._col_type = None
            type_col = getattr(self, "_col_type", None)
        if type_col is not None:
            try:
                tval = (model.index(idx.row(), type_col).data() or "")
                is_folder = "папк" in tval.lower() or "folder" in tval.lower()
            except Exception:
                pass

    menu = QMenu(self)
    menu.setObjectName("popupMenu")
    compact_menu_qss = "QMenu#popupMenu::item { padding-left: 6px; padding-right: 6px; }"
    menu.setStyleSheet(compact_menu_qss)

    act_open = menu.addAction(t("context.open"))
    act_open.setIcon(self._themed_icon(OPEN_ICON_PATH))
    act_ren = menu.addAction(t("context.rename"))
    act_ren.setIcon(self._themed_icon(EDIT_ICON_PATH))
    act_del = menu.addAction(t("context.delete"))
    act_del.setIcon(self._themed_icon(DELETE_ICON_PATH))
    menu.addSeparator()

    m_download = QMenu(t("context.download"), self)
    m_download.setObjectName("popupMenu")
    m_download.setStyleSheet(compact_menu_qss)
    act_download = menu.addMenu(m_download)
    act_download.setIcon(self._themed_icon(TOOLBAR_DOWNLOAD_ICON))

    if is_folder:
        act_d_zip = m_download.addAction(t("context.download_as_zip"))
        act_d_plain = m_download.addAction(t("context.download_structure"))
    else:
        act_d_file = m_download.addAction(t("context.download_as_file"))
        act_d_zip = m_download.addAction(t("context.download_as_zip"))

    act_copy_folder = None
    if is_folder:
        menu.addSeparator()
        act_copy_folder = menu.addAction(t("context.copy_folder"))
        act_copy_folder.setIcon(self._themed_icon(COPY_ICON_PATH))
    else:
        menu.addSeparator()
        act_move_file = menu.addAction(t("context.move_file"))
        act_move_file.setIcon(self._themed_icon(MOVE_FOLDER_ICON_PATH))
        act_copy_file = menu.addAction(t("context.copy_file"))
        act_copy_file.setIcon(self._themed_icon(COPY_ICON_PATH))

        # Flat mode only: jump to the real parent folder of this file.
        act_go_to_parent = None
        try:
            flat_on = bool(getattr(self, "cb_flat", None) is not None and self.cb_flat.isChecked())
        except Exception:
            flat_on = False
        try:
            is_file = isinstance(node, dict) and str(node.get("type") or "").lower() in ("file", "document", "doc", "файл", "документ")
        except Exception:
            is_file = False

        if flat_on and is_file:
            try:
                act_go_to_parent = menu.addAction("Перейти к папке файла")
            except Exception:
                act_go_to_parent = None

    if is_folder:
        # Folder table rows share the same action structure as the tree.
        folder_menu, folder_actions = build_folder_context_menu(self, node)
        folder_menu.setObjectName("popupMenu")
        folder_menu.setStyleSheet(compact_menu_qss)
        menu = folder_menu
        act_open = folder_actions["open"]
        act_ren = folder_actions["rename"]
        act_del = folder_actions["delete"]
        act_download = None
        act_d_zip = folder_actions["zip"]
        act_d_plain = folder_actions["structure"]
        act_copy_folder = folder_actions["copy"]
        act_move_file = folder_actions["move"]
    if not is_folder:
        act_versions = menu.addAction(t("context.open_versions"))
        act_versions.setIcon(self._themed_icon(VERSION_ICON_PATH))
    act_public = None
    act_open_link = None
    act_copy_link = None
    act_delete_link = None
    link_actions = {}
    if is_file:
        try:
            file_id = node.get("id") if isinstance(node, dict) else None
            if file_id is not None and str(file_id).strip().isdigit():
                link_url = node.get("public_link_url")
                link_state = node.get("public_link_state")
                entries = []
                try:
                    entries = self._public_link_entries_for_file(file_id)
                except Exception:
                    pass
                direct_file_entry = next(
                    (
                        entry for entry in entries
                        if entry.get("scope") == "file"
                        and str(entry.get("target_id")) == str(file_id)
                        and entry.get("url")
                    ),
                    None,
                )
                if (
                    direct_file_entry is None
                    and link_state == "exists"
                    and link_url
                ):
                    direct_file_entry = {
                        "target_id": file_id,
                        "scope": "file",
                        "url": link_url,
                    }
                if direct_file_entry:
                    link_state = "exists"
                    link_url = direct_file_entry.get("url")
                    node["_public_link_target_id"] = direct_file_entry.get("target_id")
                    node["_public_link_is_version"] = False
                else:
                    link_state = "absent"
                    link_url = None
                    node.pop("public_link_url", None)
                    node.pop("_public_link_target_id", None)
                    node.pop("_public_link_is_version", None)
                if link_state == "exists" and link_url and direct_file_entry:
                    act_open_link = menu.addAction(t("public_link.open_link"))
                    act_open_link.setIcon(self._themed_icon(OPEN_LINK_ICON_PATH))
                    act_copy_link = menu.addAction(t("public_link.copy_link"))
                    act_copy_link.setIcon(self._themed_icon(COPY_ICON_PATH))
                    act_delete_link = menu.addAction(t("public_link.delete_link"))
                    act_delete_link.setIcon(self._themed_icon(DELETE_ICON_PATH))
                elif link_state == "absent":
                    act_public = menu.addAction(t("public_link.create"))
                    act_public.setIcon(self._themed_icon(PUBLIC_LINK_ICON_PATH))
                elif link_state == "error":
                    self._show_status_message(t("public_link.state_error"), 3500)
                    act_public = None
                else:
                    try:
                        self._queue_public_link_menu_check(node, pos)
                    except Exception:
                        pass
                    act_public = None
        except Exception:
            act_public = None

    menu.addSeparator()
    act_props = menu.addAction(t("context.properties"))
    act_props.setIcon(self._themed_icon(INFORMATION_ICON_PATH))

    # показать меню
    gpos = self.table.viewport().mapToGlobal(pos)
    menu_filter = _TableContextMenuWindowFilter(self, menu)
    self.installEventFilter(menu_filter)
    try:
        try:
            chosen = self._menu_exec(menu, gpos)
        except Exception:
            chosen = menu.exec_(gpos)
    finally:
        self.removeEventFilter(menu_filter)
        menu_filter.deleteLater()
    if not chosen:
        menu.close()
        menu.deleteLater()
        return

    if chosen in link_actions:
        operation, entry = link_actions[chosen]
        menu.close()
        menu.hide()
        menu.deleteLater()
        entry_url = str(entry.get("url"))
        if operation == "open":
            QDesktopServices.openUrl(QUrl(entry_url))
        elif operation == "copy":
            QApplication.clipboard().setText(entry_url)
            self._show_status_message(t("public_link.copied"), 2000)
        else:
            if entry.get("scope") == "version":
                target_node = {
                    "version_id": entry.get("version_id") or entry.get("target_id"),
                    "parent_file_id": entry.get("parent_file_id"),
                    "version_number": entry.get("version_number"),
                    "public_link_state": "exists", "public_link_url": entry_url,
                }
                QTimer.singleShot(0, lambda: self._show_public_link_dialog(
                    target_node, is_version=True, version_number=entry.get("version_number")
                ))
            else:
                QTimer.singleShot(0, lambda: self._show_public_link_dialog(node, is_version=False))
        return

    # обработка
    # открыть диалог версий
    if "act_versions" in locals() and chosen is act_versions:
        try:
            self._show_versions_for_node(node)
        except Exception:
            pass
        return

    if act_public is not None and chosen is act_public:
        menu.close()
        menu.hide()
        menu.deleteLater()
        def _open_public_link():
            if self is None or getattr(self, "_active_public_link_dialog", None) is not None:
                return
            try:
                self._show_public_link_dialog(node, is_version=False)
            except Exception:
                pass
        QTimer.singleShot(0, _open_public_link)
        return

    if act_open_link is not None and chosen is act_open_link:
        menu.close()
        menu.hide()
        menu.deleteLater()
        QDesktopServices.openUrl(QUrl(str(node.get("public_link_url"))))
        return

    if act_copy_link is not None and chosen is act_copy_link:
        QApplication.clipboard().setText(str(node.get("public_link_url")))
        menu.close()
        menu.hide()
        menu.deleteLater()
        try:
            self._show_status_message(t("public_link.copied"), 2000)
        except Exception:
            pass
        return

    if act_delete_link is not None and chosen is act_delete_link:
        menu.close()
        menu.hide()
        menu.deleteLater()
        if node.get("_public_link_is_version"):
            version_node = {
                "version_id": node.get("_public_link_target_id"),
                "parent_file_id": node.get("id"),
                "public_link_state": "exists", "public_link_url": node.get("public_link_url"),
            }
            QTimer.singleShot(0, lambda: self._show_public_link_dialog(version_node, is_version=True))
        else:
            QTimer.singleShot(0, lambda: self._show_public_link_dialog(node, is_version=False))
        return


    if ("act_go_to_parent" in locals()) and (act_go_to_parent is not None) and chosen is act_go_to_parent:
        def _run_go_to_parent():
            try:
                fn = getattr(self, "_go_to_file_parent_folder", None)
                if callable(fn):
                    fn(node or {})
                    return
            except Exception:
                pass
            try:
                # Fallback status if helper isn't injected for some reason.
                if hasattr(self, "_show_status_message"):
                    self._show_status_message("Не удалось определить папку файла", 3500, owner="ui", force=True)
            except Exception:
                pass

        try:
            QTimer.singleShot(0, _run_go_to_parent)
        except Exception:
            _run_go_to_parent()
        return

    if chosen is act_open:
        # открываем так же, как двойным кликом, но безопасно - не из колонки 0
        m = self.table.model()
        cur = self.table.currentIndex()
        row = cur.row() if cur.isValid() else idx.row()
        col = 1 if m.columnCount() > 1 else 0
        safe_idx = m.index(row, col)
        try:
            self.on_table_double_clicked(safe_idx)
        except Exception:
            pass
        return

    if chosen is act_ren:
        try:
            self.rename_selected_item()
        except Exception:
            try:
                self.rename_selected_action()
            except Exception:
                pass
        return

    if chosen is act_del:
        try:
            self.delete_selected_action()
        except Exception:
            try:
                self.delete_selected_item()
            except Exception:
                pass
        return

    if chosen is act_props:
        try:
            self.show_properties_dialog_for_index(idx)
        except Exception:
            try:
                if is_folder and node:
                    self.show_folder_details(node)
                else:
                    self.show_details_for_selected()
            except Exception:
                pass
        return

    # копирование и перемещение папок
    if act_copy_folder and chosen is act_copy_folder:
        try:
            self.copy_folder_action()
        except Exception:
            pass
        return

    if chosen is act_move_file:
        try:
            self.move_selected_action()
        except Exception:
            pass
        return

    if chosen is act_copy_file:
        copy_log("[MENU] act_copy_file CLICKED", component="MENU")
        # Run on next tick so menu fully closes before dialogs/network.
        def _run_copy():
            try:
                fn = getattr(self, "_safe_copy_selected_action", None) or self.copy_selected_action
                fn()
                copy_log("[MENU] copy_selected_action finished successfully", component="MENU")
            except Exception as e:
                copy_log("[MENU] ERROR in copy_selected_action: {}", str(e), component="MENU")
                import traceback
                traceback.print_exc()
        try:
            QTimer.singleShot(0, _run_copy)
        except Exception:
            _run_copy()
        return

    try:
        if is_folder:
            if "act_d_zip" in locals() and chosen is act_d_zip:
                self.download_folder_as_zip(node or {})
            else:
                self.download_folder_plain(node or {})
        else:
            if "act_d_file" in locals() and chosen is act_d_file:
                self._download_file_plain_fixed(node or {})
            else:
                self.download_file_as_zip(node or {})
    except Exception:
        pass


def header_context_menu(self, pos):
    """
    ПКМ по заголовку:
    - Тип -> чекбоксы «Файл»/«Папка»
    - Формат -> чекбоксы DOCX/PDF/JPG/CAD
    - Кем создан / Кем изменено -> текстовый фильтр
    - Создано / изменено -> диапазон дат через два календаря
    - Наименование -> ничего не открываем
    """
    m = StickyMenu(self)
    m.setObjectName("nikHeaderMenu")
    try:
        hdr = self.table.horizontalHeader()
        col = hdr.logicalIndexAt(pos)
        if col < 0:
            return

        # Use column index instead of localized text for reliable filter type detection
        # Column indices based on FilesTableModel:
        # 0: checkbox, 1: name, 2: version, 3: type, 4: format,
        # 5: created by, 6: created, 7: modified, 8: modified by, 9: status
        col_type_map = {
            0: "checkbox",
            1: "name",
            2: "version",
            3: "type",
            4: "format",
            5: "created_by",
            6: "created",
            7: "modified",
            8: "modified_by",
            9: "status",
        }
        filter_type = col_type_map.get(col, "text")

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

        if filter_type == "name" or filter_type == "checkbox":
            return

        def _apply_and_close():
            try:
                self.apply_table_filters()
                if hasattr(self, "header_filter_icons_update"):
                    self.header_filter_icons_update()
            except Exception:
                pass

        if filter_type == "type":
            wrap = QWidget(m)
            layout = QVBoxLayout(wrap)
            layout.setContentsMargins(4, 4, 4, 4)
            layout.setSpacing(4)

            icon_off = self._themed_icon(CHECK_ICON_OFF_PATH)
            icon_on = self._themed_icon(CHECK_ICON_ON_PATH)

            checkboxes = {}
            rows = {}

            for lab, key in [(t("filter.file"), "file"), (t("filter.folder"), "folder")]:
                row = QWidget(wrap)
                row.setCursor(Qt.PointingHandCursor)
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(4, 4, 4, 4)
                row_layout.setSpacing(8)

                cb_icon = QLabel(row)
                cb_icon.setFixedSize(18, 18)
                cb_icon.setScaledContents(True)
                cb_icon.setPixmap(icon_off.pixmap(18, 18) if not icon_off.isNull() else QPixmap())
                cb_icon.setCursor(Qt.PointingHandCursor)

                lbl = QLabel(lab, row)
                lbl.setCursor(Qt.PointingHandCursor)

                row_layout.addWidget(cb_icon, 0)
                row_layout.addWidget(lbl, 1)

                checkboxes[key] = cb_icon
                rows[key] = row
                layout.addWidget(row)

            action = QWidgetAction(m)
            action.setDefaultWidget(wrap)
            m.addAction(action)

            cur = set() if self._flt_type is None else set(self._flt_type)
            checked_state = {}
            for key, cb in checkboxes.items():
                checked = key in cur
                checked_state[key] = checked
                pm = icon_on.pixmap(18, 18) if checked else icon_off.pixmap(18, 18)
                cb.setPixmap(pm if not pm.isNull() else QPixmap())

            for key, row in rows.items():
                def on_toggle(event, row=row, key=key):
                    checked_state[key] = not checked_state.get(key, False)
                    sel = set()
                    if checked_state.get("file", False):
                        sel.add("file")
                    if checked_state.get("folder", False):
                        sel.add("folder")
                    self._flt_type = None if len(sel) == 0 or len(sel) == 2 else sel
                    cb = checkboxes[key]
                    is_checked = checked_state[key]
                    pm = icon_on.pixmap(18, 18) if is_checked else icon_off.pixmap(18, 18)
                    cb.setPixmap(pm if not pm.isNull() else QPixmap())
                    _apply_and_close()

                row.mousePressEvent = on_toggle

            m.addSeparator()
            act_clear = m.addAction(t("filter.reset_filter"))

            def _clear_type():
                self._flt_type = None
                for cb in checkboxes.values():
                    pm = icon_off.pixmap(18, 18)
                    cb.setPixmap(pm if not pm.isNull() else QPixmap())
                for key in checked_state:
                    checked_state[key] = False
                _apply_and_close()

            act_clear.triggered.connect(_clear_type)

        # ----- Формат -----
        elif filter_type == "format":
            opts = ["DOCX", "PDF", "JPG", "CAD"]
            label2ext = {
                "DOCX": {
                    "docx",
                    "doc",
                    "docm",
                    "dotx",
                    "dotm",
                    "dot",
                    "rtf",
                    "docb",
                    "mht",
                    "mhtml",
                    "wbk",
                    "xlsx",
                    "xls",
                    "xlsm",
                    "xlsb",
                    "xltx",
                    "xltm",
                    "xlt",
                    "xlam",
                    "xla",
                    "xlw",
                    "xll",
                    "crtx",
                    "pptx",
                    "ppt",
                    "pptm",
                    "potx",
                    "potm",
                    "pot",
                    "ppsx",
                    "ppsm",
                    "pps",
                    "ppam",
                    "ppa",
                    "thmx",
                    "pst",
                    "ost",
                    "msg",
                    "oft",
                    "olm",
                    "nk2",
                    "one",
                    "onepkg",
                    "onetoc2",
                    "accdb",
                    "mdb",
                    "accde",
                    "mde",
                    "accdt",
                    "accda",
                    "accdr",
                    "accdc",
                    "adp",
                    "ade",
                    "mdw",
                    "pub",
                    "vsdx",
                    "vsd",
                    "vsdm",
                    "vssx",
                    "vssm",
                    "vss",
                    "vstx",
                    "vstm",
                    "vst",
                    "vdx",
                    "vsx",
                    "vtx",
                    "vdw",
                    "mpp",
                    "mpt",
                    "mpd",
                    "mpx",
                    "xps",
                },
                "PDF": {"pdf"},
                "JPG": {
                    "png",
                    "jpg",
                    "jpeg",
                    "gif",
                    "bmp",
                    "tif",
                    "tiff",
                    "webp",
                    "svg",
                    "svgz",
                    "ico",
                    "icns",
                    "heic",
                    "heif",
                    "avif",
                    "apng",
                    "jfif",
                    "jp2",
                    "j2k",
                    "jpf",
                    "jpx",
                    "jpm",
                    "tga",
                    "dds",
                    "wbmp",
                    "psd",
                    "ai",
                    "eps",
                    "raw",
                    "dng",
                    "cr2",
                    "cr3",
                    "nef",
                    "arw",
                    "orf",
                    "rw2",
                    "raf",
                    "sr2",
                    "pef",
                },
                "CAD": {"dwg", "dxf", "step", "stp", "iges", "igs", "ifc", "cad", "imc", "rvt", "nwf", "nwc"},
            }

            wrap = QWidget(m)
            layout = QVBoxLayout(wrap)
            layout.setContentsMargins(4, 4, 4, 4)
            layout.setSpacing(4)

            checkboxes = {}
            rows = {}

            for lab in opts:
                row = QWidget(wrap)
                row.setCursor(Qt.PointingHandCursor)
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(4, 4, 4, 4)
                row_layout.setSpacing(8)

                cb_icon = QLabel(row)
                cb_icon.setFixedSize(18, 18)
                cb_icon.setScaledContents(True)
                icon_off_tmp = self._themed_icon(CHECK_ICON_OFF_PATH)
                cb_icon.setPixmap(icon_off_tmp.pixmap(18, 18) if not icon_off_tmp.isNull() else QPixmap())
                cb_icon.setCursor(Qt.PointingHandCursor)

                lbl = QLabel(lab, row)
                lbl.setCursor(Qt.PointingHandCursor)

                row_layout.addWidget(cb_icon, 0)
                row_layout.addWidget(lbl, 1)

                checkboxes[lab] = cb_icon
                rows[lab] = row
                layout.addWidget(row)

            action = QWidgetAction(m)
            action.setDefaultWidget(wrap)
            m.addAction(action)

            icon_off = self._themed_icon(CHECK_ICON_OFF_PATH)
            icon_on = self._themed_icon(CHECK_ICON_ON_PATH)

            cur = set(self._flt_formats or set())
            checked_state = {}
            for lab, cb in checkboxes.items():
                exts = label2ext.get(lab, {lab.lower()})
                checked = bool(exts & cur)
                checked_state[lab] = checked
                pm = icon_on.pixmap(18, 18) if checked else icon_off.pixmap(18, 18)
                cb.setPixmap(pm if not pm.isNull() else QPixmap())

            for lab, row in rows.items():
                def on_toggle(event, row=row, lab=lab):
                    is_checked = not checked_state.get(lab, False)
                    checked_state[lab] = is_checked
                    s = set()
                    for l, checked in checked_state.items():
                        if checked:
                            exts = label2ext.get(l, {l.lower()})
                            s |= exts
                    self._flt_formats = s
                    cb = checkboxes[lab]
                    pm = icon_on.pixmap(18, 18) if is_checked else icon_off.pixmap(18, 18)
                    cb.setPixmap(pm if not pm.isNull() else QPixmap())
                    _apply_and_close()

                row.mousePressEvent = on_toggle

            m.addSeparator()
            act_clear = m.addAction(t("filter.reset"))

            def _clear_formats():
                self._flt_formats = set()
                for cb in checkboxes.values():
                    pm = icon_off.pixmap(18, 18)
                    cb.setPixmap(pm if not pm.isNull() else QPixmap())
                for lab in checked_state:
                    checked_state[lab] = False
                _apply_and_close()

            act_clear.triggered.connect(_clear_formats)

        elif filter_type in {"version", "created_by", "modified_by", "status"}:
            if not hasattr(self, "column_text_filters"):
                self.column_text_filters = {}
            if not hasattr(self, "column_filters"):
                self.column_filters = {}

            def _apply_and_refresh():
                try:
                    self.apply_table_filters()
                    if hasattr(self, "header_filter_icons_update"):
                        self.header_filter_icons_update()
                except Exception:
                    pass

            wrap = QWidget(m)
            vl = QVBoxLayout(wrap)
            vl.setContentsMargins(8, 8, 8, 8)
            vl.setSpacing(6)

            row_top = QWidget(wrap)
            ht = QHBoxLayout(row_top)
            ht.setContentsMargins(0, 0, 0, 0)
            ht.setSpacing(8)

            le = QLineEdit(row_top)
            le.setPlaceholderText(t("filter.enter_text"))
            le.setMinimumWidth(260)
            le.setText(self.column_text_filters.get(col, ""))
            ht.addWidget(le, 1)

            btn = QToolButton(row_top)
            btn.setObjectName("filterTrigger")
            btn.setIcon(self._themed_icon(STRUCTURE_ICON_PATH))
            btn.setIconSize(QSize(16, 16))
            btn.setCheckable(True)
            btn.setAutoRaise(False)
            btn.setProperty("secondary", True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(t("filter.variants"))
            btn.setStyleSheet("QToolButton::menu-indicator{ image: none; width:0; }")
            ht.addWidget(btn, 0)

            vl.addWidget(row_top)

            btn_reset_main = QPushButton(t("filter.reset"), wrap)
            btn_reset_main.setProperty("secondary", True)
            vl.addWidget(btn_reset_main, 0)

            uniq = []
            try:
                sm = self.files_model
                seen = set()
                for r in range(sm.rowCount()):
                    s = str(sm.data(sm.index(r, col)) or "").strip()
                    # Skip empty values for specific columns
                    if s == "" and filter_type in {"version", "created_by", "modified_by"}:
                        continue
                    k = s.lower()
                    if k not in seen:
                        seen.add(k)
                        uniq.append(s)
            except Exception:
                pass

            display2real = {}
            for s in sorted(uniq, key=lambda x: (x == "", x.lower())):
                disp = t("dialog.empty") if s == "" else s
                display2real[disp] = s

            # NOTE: do NOT try to expand the current header menu dynamically.
            # QWidgetAction + QMenu geometry updates are flaky on Windows and can
            # result in a visually "squeezed" popup. Instead we open a secondary
            # StickyMenu with checkable actions.
            values_menu = StickyMenu(m)
            values_menu.setObjectName("nikHeaderMenu")
            try:
                values_menu.setIconSize(QSize(18, 18))
            except Exception:
                pass
            # Hide native checkmark indicator; we render state via themed icons.
            try:
                values_menu.setStyleSheet("QMenu::indicator { width: 0px; height: 0px; }")
            except Exception:
                pass

            def _rebuild_values_menu():
                try:
                    values_menu.clear()
                except Exception:
                    pass

                icon_off = self._themed_icon(CHECK_ICON_OFF_PATH)
                icon_on = self._themed_icon(CHECK_ICON_ON_PATH)

                preselected = set(self.column_filters.get(col, set()))
                for disp, real in display2real.items():
                    act = QAction(disp, values_menu)
                    act.setCheckable(True)
                    checked_now = real in preselected
                    act.setChecked(checked_now)
                    try:
                        act.setIcon(icon_on if checked_now else icon_off)
                    except Exception:
                        pass

                    def _on_toggle(checked: bool, real=real, act=act, icon_on=icon_on, icon_off=icon_off):
                        selected = set(self.column_filters.get(col, set()))
                        if checked:
                            selected.add(real)
                        else:
                            selected.discard(real)
                        if selected:
                            self.column_filters[col] = selected
                        else:
                            self.column_filters.pop(col, None)
                        try:
                            act.setIcon(icon_on if checked else icon_off)
                        except Exception:
                            pass
                        _apply_and_refresh()

                    act.toggled.connect(_on_toggle)
                    values_menu.addAction(act)

                if display2real:
                    try:
                        values_menu.addSeparator()
                    except Exception:
                        pass

                act_clear_vals = QAction(t("filter.reset_variants"), values_menu)

                def _clear_vals():
                    self.column_filters.pop(col, None)
                    _apply_and_refresh()

                act_clear_vals.triggered.connect(_clear_vals)
                values_menu.addAction(act_clear_vals)

            def show_values_menu():
                _rebuild_values_menu()
                try:
                    p = btn.mapToGlobal(QPoint(0, int(btn.height())))
                    values_menu.popup(p)
                except Exception:
                    try:
                        values_menu.exec(btn.mapToGlobal(QPoint(0, int(btn.height()))))
                    except Exception:
                        pass

            btn.clicked.connect(show_values_menu)

            le.textChanged.connect(
                lambda _=None: (
                    self.column_text_filters.__setitem__(col, t) if (t := le.text().strip()) else self.column_text_filters.pop(col, None),
                    _apply_and_refresh(),
                )
            )

            def _reset_all():
                try:
                    le.blockSignals(True)
                    le.clear()
                    le.blockSignals(False)
                except Exception:
                    pass
                self.column_text_filters.pop(col, None)
                self.column_filters.pop(col, None)
                _apply_and_refresh()

            btn_reset_main.clicked.connect(_reset_all)

            wa = QWidgetAction(m)
            wa.setDefaultWidget(wrap)
            m.addAction(wa)

        # ----- Создано / изменено (диапазон дат) -----
        elif filter_type == "created" or filter_type == "modified":
            wrap = QWidget(m)
            vl = QVBoxLayout(wrap)
            vl.setContentsMargins(8, 8, 8, 8)
            vl.setSpacing(6)
            row = QWidget(wrap)
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(8)
            cal1 = QCalendarWidget(row)
            cal2 = QCalendarWidget(row)
            cal1.setGridVisible(True)
            cal2.setGridVisible(True)
            cy = QDate.currentDate().year()
            base_min = QDate(cy - 3, 1, 1)
            base_max = QDate(cy + 3, 12, 31)
            try:
                cal1.setMinimumWidth(230)
                cal2.setMinimumWidth(230)
            except Exception:
                pass

            for cal in (cal1, cal2):
                try:
                    cal.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
                    try:
                        cal.setFirstDayOfWeek(Qt.Monday)
                    except Exception:
                        pass
                    try:
                        cal.setHorizontalHeaderFormat(QCalendarWidget.ShortDayNames)
                    except Exception:
                        pass
                    cal.setDateRange(base_min, base_max)
                except Exception:
                    pass
                try:
                    prevy = cal.findChild(QToolButton, "qt_calendar_prevyear")
                    nexty = cal.findChild(QToolButton, "qt_calendar_nextyear")
                    if prevy and SORT_ICON_DOWN_PATH:
                        prevy.setIcon(self._themed_icon(SORT_ICON_DOWN_PATH))
                    if nexty and SORT_ICON_UP_PATH:
                        nexty.setIcon(self._themed_icon(SORT_ICON_UP_PATH))
                except Exception:
                    pass
                view = cal.findChild(QTableView, "qt_calendar_calendarview")
                if view:
                    view.setTextElideMode(Qt.ElideNone)
                    view.setWordWrap(False)
                    # Avoid native Windows focus/selection blue bars in the calendar grid.
                    try:
                        view.setFocusPolicy(Qt.NoFocus)
                    except Exception:
                        pass
                    try:
                        # If NoSelection breaks date picking, keep selection enabled and rely on QSS/delegate.
                        view.setSelectionMode(QAbstractItemView.NoSelection)
                    except Exception:
                        pass

                    delegate = _CalendarNoBlueSelectionDelegate(view)
                    view.setItemDelegate(delegate)
                    # Keep a ref so Python GC doesn't collect it.
                    view._date_filter_delegate = delegate

                    try:
                        view.setStyleSheet(
                            "QTableView#qt_calendar_calendarview {"
                            "outline: none;"
                            "border: none;"
                            "background: transparent;"
                            "selection-background-color: transparent;"
                            "selection-color: #000000;"
                            "}"
                            "QTableView#qt_calendar_calendarview::item {"
                            "border: none;"
                            "outline: none;"
                            "padding: 2px;"
                            "}"
                            "QTableView#qt_calendar_calendarview::item:selected,"
                            "QTableView#qt_calendar_calendarview::item:focus {"
                            "background: rgba(247, 146, 30, 0.20);"
                            "color: #000000;"
                            "border: 1px solid #E07E12;"
                            "border-radius: 6px;"
                            "outline: none;"
                            "}"
                        )
                    except Exception:
                        pass
                # Local fallback (only for these calendars) if global theme/QSS still leaks native focus highlight.
                try:
                    cal.setStyleSheet(
                        "QTableView#qt_calendar_calendarview {"
                        "outline: none;"
                        "border: none;"
                        "background: transparent;"
                        "selection-background-color: transparent;"
                        "selection-color: #000000;"
                        "}"
                        "QTableView#qt_calendar_calendarview::item {"
                        "border: none;"
                        "outline: none;"
                        "padding: 2px;"
                        "}"
                        "QTableView#qt_calendar_calendarview::item:selected,"
                        "QTableView#qt_calendar_calendarview::item:focus {"
                        "background: rgba(247, 146, 30, 0.20);"
                        "color: #000000;"
                        "border: 1px solid #E07E12;"
                        "border-radius: 6px;"
                        "outline: none;"
                        "}"
                    )
                except Exception:
                    pass

            hl.addWidget(cal1)
            hl.addWidget(cal2)
            vl.addWidget(row)

            def _enforce_single_month(cal: QCalendarWidget):
                try:
                    view = cal.findChild(QTableView, "qt_calendar_calendarview")
                    if view:
                        view.setItemDelegate(QStyledItemDelegate(view))
                except Exception:
                    pass

                try:
                    try:
                        yy = int(cal.yearShown())
                        mm = int(cal.monthShown())
                    except Exception:
                        d = cal.selectedDate()
                        yy, mm = int(d.year()), int(d.month())
                    first = QDate(yy, mm, 1)
                    try:
                        fd = cal.firstDayOfWeek()
                        fdow = int(getattr(fd, "value", fd))
                    except Exception:
                        fdow = 1
                    shift = (first.dayOfWeek() - fdow + 7) % 7
                    grid_start = first.addDays(-shift)
                    fmt_reset = QTextCharFormat()
                    for i in range(42):
                        cal.setDateTextFormat(grid_start.addDays(i), fmt_reset)
                except Exception:
                    pass
                try:
                    if not hasattr(cal, "_one_month_hooked"):
                        cal.currentPageChanged.connect(lambda _y, _m, c=cal: _enforce_single_month(c))
                        cal._one_month_hooked = True
                except Exception:
                    pass

            _enforce_single_month(cal1)
            _enforce_single_month(cal2)

            cur = self._flt_created if filter_type == "created" else self._flt_modified
            d1, d2 = cur

            _syncing_range = {"on": False}

            def _sync_date_range(changed: str | None = None):
                if _syncing_range.get("on"):
                    return
                _syncing_range["on"] = True
                try:
                    d_from = cal1.selectedDate()
                    d_to = cal2.selectedDate()
                    if d_to < d_from:
                        if changed == "from":
                            cal2.setSelectedDate(d_from)
                            d_to = d_from
                        elif changed == "to":
                            cal1.setSelectedDate(d_to)
                            d_from = d_to
                        else:
                            cal2.setSelectedDate(d_from)
                            d_to = d_from
                    cal1.setDateRange(base_min, d_to)
                    cal2.setDateRange(d_from, base_max)
                except Exception:
                    pass
                finally:
                    _syncing_range["on"] = False

            if d1 and d2 and d1 > d2:
                # Normalize persisted values in UI to keep from <= to.
                d1, d2 = d2, d1
            if d1:
                cal1.setSelectedDate(d1)
            if d2:
                cal2.setSelectedDate(d2)

            try:
                cal1.selectionChanged.connect(lambda: _sync_date_range("from"))
                cal2.selectionChanged.connect(lambda: _sync_date_range("to"))
            except Exception:
                pass

            _sync_date_range()

            def _attach_year_menu(cal):
                year_btn = cal.findChild(QToolButton, "qt_calendar_yearbutton")
                if not year_btn:
                    return
                menu = QMenu(year_btn)

                def rebuild_fixed():
                    try:
                        menu.clear()
                        cy = QDate.currentDate().year()

                        input_container = QWidget(menu)
                        input_layout = QHBoxLayout(input_container)
                        input_layout.setContentsMargins(5, 5, 5, 5)
                        input_layout.setSpacing(5)

                        year_input = QLineEdit(input_container)
                        year_input.setPlaceholderText(t("filter.enter_year"))
                        try:
                            current_year = cal.yearShown()
                            year_input.setText(str(current_year))
                        except Exception:
                            year_input.setText(str(cy))
                        year_input.setMaximumWidth(100)

                        apply_btn = QPushButton(t("common.ok"), input_container)
                        try:
                            apply_btn.setMinimumWidth(apply_btn.sizeHint().width())
                        except Exception:
                            apply_btn.setMinimumWidth(56)

                        def apply_year_input():
                            try:
                                y = int(year_input.text())
                                min_y = cy - 3
                                max_y = cy + 3
                                if min_y <= y <= max_y:
                                    cal.setCurrentPage(y, cal.monthShown())
                                    menu.close()
                                else:
                                    year_input.setStyleSheet("border: 1px solid red")
                                    QTimer.singleShot(1000, lambda: year_input.setStyleSheet(""))
                            except ValueError:
                                year_input.setStyleSheet("border: 1px solid red")
                                QTimer.singleShot(1000, lambda: year_input.setStyleSheet(""))

                        apply_btn.clicked.connect(apply_year_input)
                        year_input.returnPressed.connect(apply_year_input)

                        input_layout.addWidget(year_input)
                        input_layout.addWidget(apply_btn)

                        wa = QWidgetAction(menu)
                        wa.setDefaultWidget(input_container)
                        menu.addAction(wa)

                        menu.addSeparator()

                        for yy in range(cy - 3, cy + 4):
                            act = QAction(str(yy), menu)
                            act.setCheckable(True)
                            act.setChecked(yy == cal.yearShown())
                            act.triggered.connect(lambda _=False, yy=yy: cal.setCurrentPage(yy, cal.monthShown()))
                            menu.addAction(act)
                    except Exception:
                        pass

                try:
                    menu.aboutToShow.connect(rebuild_fixed)
                except Exception:
                    pass
                year_btn.setMenu(menu)
                year_btn.setPopupMode(QToolButton.InstantPopup)

            def _attach_month_menu(cal):
                month_btn = cal.findChild(QToolButton, "qt_calendar_monthbutton")
                if not month_btn:
                    return
                menu = QMenu(month_btn)

                def rebuild_month_menu():
                    try:
                        menu.clear()
                        input_container = QWidget(menu)
                        input_layout = QHBoxLayout(input_container)
                        input_layout.setContentsMargins(5, 5, 5, 5)
                        input_layout.setSpacing(5)

                        month_input = QLineEdit(input_container)
                        month_input.setPlaceholderText(t("filter.month_placeholder"))
                        try:
                            current_month = cal.monthShown()
                            month_input.setText(str(current_month))
                        except Exception:
                            month_input.setText(str(QDate.currentDate().month()))
                        month_input.setMaximumWidth(100)

                        apply_btn = QPushButton(t("common.ok"), input_container)
                        try:
                            apply_btn.setMinimumWidth(apply_btn.sizeHint().width())
                        except Exception:
                            apply_btn.setMinimumWidth(56)

                        def apply_month_input():
                            try:
                                m = int(month_input.text())
                                if 1 <= m <= 12:
                                    cal.setCurrentPage(cal.yearShown(), m)
                                    menu.close()
                                else:
                                    month_input.setStyleSheet("border: 1px solid red")
                                    QTimer.singleShot(1000, lambda: month_input.setStyleSheet(""))
                            except ValueError:
                                month_input.setStyleSheet("border: 1px solid red")
                                QTimer.singleShot(1000, lambda: month_input.setStyleSheet(""))

                        apply_btn.clicked.connect(apply_month_input)
                        month_input.returnPressed.connect(apply_month_input)

                        input_layout.addWidget(month_input)
                        input_layout.addWidget(apply_btn)

                        wa = QWidgetAction(menu)
                        wa.setDefaultWidget(input_container)
                        menu.addAction(wa)

                        menu.addSeparator()

                        month_names = [
                            t("months.january"),
                            t("months.february"),
                            t("months.march"),
                            t("months.april"),
                            t("months.may"),
                            t("months.june"),
                            t("months.july"),
                            t("months.august"),
                            t("months.september"),
                            t("months.october"),
                            t("months.november"),
                            t("months.december"),
                        ]
                        try:
                            current_month = cal.monthShown()
                        except Exception:
                            current_month = QDate.currentDate().month()

                        for i, month_name in enumerate(month_names, 1):
                            act = QAction(f"{i}. {month_name}", menu)
                            act.setCheckable(True)
                            act.setChecked(i == current_month)
                            act.triggered.connect(lambda _=False, m=i: cal.setCurrentPage(cal.yearShown(), m))
                            menu.addAction(act)
                    except Exception:
                        pass

                try:
                    menu.aboutToShow.connect(rebuild_month_menu)
                except Exception:
                    pass
                month_btn.setMenu(menu)
                month_btn.setPopupMode(QToolButton.InstantPopup)

            for _cal in (cal1, cal2):
                _attach_year_menu(_cal)
                _attach_month_menu(_cal)

            ctrl = QWidget(wrap)
            ctl = QHBoxLayout(ctrl)
            ctl.setContentsMargins(0, 0, 0, 0)
            ctl.setSpacing(8)

            btn_today = QPushButton(t("filter.today"), ctrl)
            btn_week = QPushButton(t("filter.week"), ctrl)
            btn_month = QPushButton(t("filter.month"), ctrl)
            btn_clear = QPushButton(t("filter.reset"), ctrl)
            btn_apply = QPushButton(t("filter.apply"), ctrl)

            for b in (btn_today, btn_week, btn_month, btn_clear, btn_apply):
                b.setProperty("secondary", True)

            ctl.addWidget(QLabel(t("filter.range")))
            ctl.addWidget(btn_today)
            ctl.addWidget(btn_week)
            ctl.addWidget(btn_month)
            ctl.addStretch(1)
            ctl.addWidget(btn_clear)
            ctl.addWidget(btn_apply)
            vl.addWidget(ctrl)

            def _set_week():
                today = QDate.currentDate()
                start = today.addDays(-6)
                cal1.setSelectedDate(start)
                cal2.setSelectedDate(today)
                _sync_date_range()

            def _set_month():
                def _shown_year_month(cal_widget: QCalendarWidget) -> tuple[int, int]:
                    try:
                        return int(cal_widget.yearShown()), int(cal_widget.monthShown())
                    except Exception:
                        d_local = cal_widget.selectedDate()
                        return int(d_local.year()), int(d_local.month())

                focus = QApplication.focusWidget()
                if isinstance(focus, QCalendarWidget):
                    year, month = _shown_year_month(focus)
                else:
                    year, month = _shown_year_month(cal2)

                start = QDate(year, month, 1)
                end = QDate(year, month, start.daysInMonth())

                for target in (cal1, cal2):
                    try:
                        target.setCurrentPage(year, month)
                    except Exception:
                        pass
                cal1.setSelectedDate(start)
                cal2.setSelectedDate(end)
                _sync_date_range()

            def _set_today():
                today = QDate.currentDate()
                cal1.setSelectedDate(today)
                cal2.setSelectedDate(today)
                _sync_date_range()

            def _apply_dates():
                d_from = cal1.selectedDate()
                d_to = cal2.selectedDate()
                if d_to < d_from:
                    d_from, d_to = d_to, d_from
                if filter_type == "created":
                    self._flt_created = (d_from, d_to)
                else:
                    self._flt_modified = (d_from, d_to)
                _apply_and_close()
                try:
                    m.close()
                except Exception:
                    pass

            def _clear_dates():
                if filter_type == "created":
                    self._flt_created = (None, None)
                else:
                    self._flt_modified = (None, None)
                _apply_and_close()
                try:
                    m.close()
                except Exception:
                    pass

            btn_today.clicked.connect(_set_today)
            btn_week.clicked.connect(_set_week)
            btn_month.clicked.connect(_set_month)
            btn_apply.clicked.connect(_apply_dates)
            btn_clear.clicked.connect(_clear_dates)

            wa = QWidgetAction(m)
            wa.setDefaultWidget(wrap)
            m.addAction(wa)

        else:
            # Text filter for columns like Version, Created by, Modified by, Status
            wrap = QWidget(m)
            layout = QVBoxLayout(wrap)
            layout.setContentsMargins(8, 8, 8, 8)
            layout.setSpacing(6)

            le = QLineEdit(wrap)
            le.setPlaceholderText(t("filter.enter_text_dots"))
            le.setMinimumWidth(220)
            le.setText(self.column_text_filters.get(col, ""))
            layout.addWidget(le)

            wa = QWidgetAction(m)
            wa.setDefaultWidget(wrap)
            m.addAction(wa)

            def _apply_text():
                text = le.text().strip()
                if text:
                    self.column_text_filters[col] = text
                else:
                    self.column_text_filters.pop(col, None)
                _apply_and_close()

            le.textChanged.connect(_apply_text)

            m.addSeparator()
            act_clear = m.addAction(t("filter.reset_filter"))
            act_clear.triggered.connect(lambda: [self.column_text_filters.pop(col, None), _apply_and_close()])

        try:
            m.exec(hdr.mapToGlobal(pos))
        except Exception:
            m.exec_(hdr.mapToGlobal(pos))
    except Exception:
        pass


def inject_context_menus_to_main_window(MainWindowClass) -> None:
    MainWindowClass.table_context_menu = table_context_menu
    MainWindowClass.header_context_menu = header_context_menu
