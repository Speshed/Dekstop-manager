# -*- coding: utf-8 -*-

import os
from datetime import datetime, timedelta
from typing import Dict

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QPalette
from PySide6.QtWidgets import QApplication, QStyle

from larix_nexus.utils.paths import rsrc_path


def file_ext(name: str) -> str:
    return os.path.splitext(name)[1].lstrip(".").lower()


def parse_date_like(s: str, tz_offset_min: int | None = None) -> float:
    """Parse a cloud datetime into UTC epoch seconds.
    - If s is numeric (seconds or ms), return as seconds.
    - If ISO string with explicit TZ or 'Z' suffix, respect it.
    - If naive string (no TZ), add tz_offset_min minutes to the naive time, then treat as UTC.
      Example: offset +180, '07:00' -> 07:00 + 03:00 => 10:00 UTC.
    """
    if not s:
        return 0.0
    # Numeric epochs
    try:
        if isinstance(s, (int, float)) or (isinstance(s, str) and s.strip().isdigit()):
            val = float(s)
            if val > 1e12:
                val = val / 1000.0
            return float(val)
    except Exception:
        pass
    s = str(s).strip()
    # ISO and similar
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        from datetime import timezone, timedelta
        if dt.tzinfo is None:
            ofs = int(tz_offset_min or 0)
            dt2 = dt + timedelta(minutes=ofs)
            return dt2.replace(tzinfo=timezone.utc).timestamp()
        return dt.timestamp()
    except Exception:
        pass
    # Fallback known formats without TZ -> interpret in cloud TZ by shifting
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            from datetime import timezone, timedelta
            ofs = int(tz_offset_min or 0)
            dt2 = dt + timedelta(minutes=ofs)
            return dt2.replace(tzinfo=timezone.utc).timestamp()
        except (ValueError, TypeError):
            continue
    return 0.0


def _app_settings():
    """Get QSettings instance for the application."""
    from PySide6.QtCore import QSettings
    return QSettings()


def _user_display_datetime(ts: float) -> str:
    """Format epoch seconds according to user timezone settings.
    - If auto: use system local time
    - Else: UTC + offset_minutes
    """
    try:
        from datetime import timedelta
        s = _app_settings(); s.beginGroup("time")
        try:
            use_auto = bool(int(s.value("auto", 1) or 1))
            offset = int(s.value("offset_minutes", 0) or 0)
        finally:
            s.endGroup()
        if use_auto:
            dt = datetime.fromtimestamp(float(ts))
        else:
            dt = datetime.utcfromtimestamp(float(ts)) + timedelta(minutes=offset)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        try:
            return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return ""


def _is_dark_mode():
    """Check if the current theme is dark."""
    try:
        app = QApplication.instance()
        if app:
            palette = app.palette()
            text_color = palette.color(QPalette.WindowText)
            bg_color = palette.color(QPalette.Window)
            return text_color.lightness() > bg_color.lightness()
    except Exception:
        pass
    return False


def _icon_from_pixmap_variants(pm: QPixmap) -> QIcon:
    """Create QIcon with multiple pixmap sizes."""
    icon = QIcon()
    sizes = [16, 20, 24, 28, 32, 40, 48]
    for size in sizes:
        scaled = pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        icon.addPixmap(scaled)
    return icon


def load_white_icon(path: str) -> QIcon:
    """Load icon and tint it white for dark theme."""
    try:
        icon = QIcon(path)
        pm = icon.pixmap(24, 24)
        if not pm.isNull():
            pm = _tint_pixmap(pm, QColor(Qt.white))
            return QIcon(pm)
    except Exception:
        pass
    return QIcon(path)


def _tint_pixmap(pm: QPixmap, color: QColor) -> QPixmap:
    """Tint pixmap with given color."""
    result = QPixmap(pm.size())
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    painter.fillRect(result.rect(), color)
    painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
    painter.drawPixmap(0, 0, pm)
    painter.end()
    return result


def _app_settings():
    """Get QSettings instance."""
    from PySide6.QtCore import QSettings
    return QSettings()


CUSTOM_ICONS_DIR = rsrc_path("icon")
CUSTOM_FOLDER_ICON_PATH = rsrc_path("icon", "folder_icon_variant_1.png")


class IconProvider:
    EXT_ICON_MAP = {
        "pdf":  "PDF_file_icon.svg",
        "txt":  "txt_icon_variant_1.png",
        "png":"Image.png","jpg":"Image.png","jpeg":"Image.png",
        "gif":"Image.png","bmp":"Image.png","tif":"Image.png",
        "tiff":"Image.png","webp":"Image.png","svg":"Image.png",
        "svgz":"Image.png","ico":"Image.png","icns":"Image.png",
        "heic":"Image.png","heif":"Image.png","avif":"Image.png",
        "apng":"Image.png","jfif":"Image.png","jp2":"Image.png",
        "j2k":"Image.png","jpf":"Image.png","jpx":"Image.png",
        "jpm":"Image.png","tga":"Image.png","dds":"Image.png",
        "wbmp":"Image.png","psd":"Image.png","ai":"Image.png",
        "eps":"Image.png","raw":"Image.png","dng":"Image.png",
        "cr2":"Image.png","cr3":"Image.png","nef":"Image.png",
        "arw":"Image.png","orf":"Image.png","rw2":"Image.png",
        "raf":"Image.png","sr2":"Image.png","pef":"Image.png",
        "docx":"Word.svg","doc":"Word.svg","docm":"Word.svg",
        "dotx":"Word.svg","dotm":"Word.svg","dot":"Word.svg",
        "rtf":"Word.svg","docb":"Word.svg","mht":"Word.svg",
        "mhtml":"Word.svg","wbk":"Word.svg","xps":"Word.svg",
        "xlsx":"Excel.svg","xls":"Excel.svg","xlsm":"Excel.svg",
        "xlsb":"Excel.svg","xltx":"Excel.svg","xltm":"Excel.svg",
        "xlt":"Excel.svg","xlam":"Excel.svg","xla":"Excel.svg",
        "xlw":"Excel.svg","xll":"Excel.svg","crtx":"Excel.svg",
        "csv":"Excel.svg",
        "pptx":"PPTX.png","ppt":"PPTX.png","pptm":"PPTX.png",
        "potx":"PPTX.png","potm":"PPTX.png","pot":"PPTX.png",
        "ppsx":"PPTX.png","ppsm":"PPTX.png","pps":"PPTX.png",
        "ppam":"PPTX.png","ppa":"PPTX.png","thmx":"PPTX.png",
        "pst":"outlook_icon_variant_1.png","ost":"outlook_icon_variant_1.png","msg":"outlook_icon_variant_1.png",
        "oft":"outlook_icon_variant_1.png","olm":"outlook_icon_variant_1.png","nk2":"outlook_icon_variant_1.png",
        "one":"onenote_icon_variant_1.png","onepkg":"onenote_icon_variant_1.png","onetoc2":"onenote_icon_variant_1.png",
        "accdb":"access_icon_variant_1.png","mdb":"access_icon_variant_1.png","accde":"access_icon_variant_1.png",
        "mde":"access_icon_variant_1.png","accdt":"access_icon_variant_1.png","accda":"access_icon_variant_1.png",
        "accdr":"access_icon_variant_1.png","accdc":"access_icon_variant_1.png","adp":"access_icon_variant_1.png",
        "ade":"access_icon_variant_1.png","mdw":"access_icon_variant_1.png",
        "pub":"publisher_icon_variant_1.png",
        "vsdx":"visio_icon_variant_1.png","vsd":"visio_icon_variant_1.png","vsdm":"visio_icon_variant_1.png",
        "vssx":"visio_icon_variant_1.png","vssm":"visio_icon_variant_1.png","vss":"visio_icon_variant_1.png",
        "vstx":"visio_icon_variant_1.png","vstm":"visio_icon_variant_1.png","vst":"visio_icon_variant_1.png",
        "vdx":"visio_icon_variant_1.png","vsx":"visio_icon_variant_1.png","vtx":"visio_icon_variant_1.png",
        "vdw":"visio_icon_variant_1.png",
        "mpp":"project_icon_variant_1.png","mpt":"project_icon_variant_1.png",
        "mpd":"project_icon_variant_1.png","mpx":"project_icon_variant_1.png",
        "dwg":"Autocad.png","dxf":"Autocad.png",
        "step":"cad.png","stp":"cad.png",
        "iges":"cad.png","igs":"cad.png",
        "ifc":"IFC.png","rvt":"Autodesk Revit.ico",
        "nwf":"NWF.png","nwc":"NWC.png","nwd":"NWD.png", "cad":"cad.png", "imc":"ImcFile.ico",
    }
    FOLDER_ICON_CANDIDATES = ["folder_icon_variant_1.png", "folder.svg"]

    def __init__(self, style: QStyle):
        self._style = style
        self._cache = {
            "folder": self._style.standardIcon(QStyle.SP_DirIcon),
            "__default__": self._style.standardIcon(QStyle.SP_FileIcon)
        }
        self._badge_cache = {}

    def _overlay_badge(self, base: QIcon, badge_path: str) -> QIcon:
        """Compose a small badge at bottom-right of the base icon.

        Returns a QIcon with multiple pixmap sizes for crisp rendering.
        Falls back to base icon on any error.
        """
        try:
            if not badge_path or not os.path.exists(badge_path):
                return base
            badge_pm_orig = QPixmap(badge_path)
            if badge_pm_orig.isNull():
                return base
            try:
                if _is_dark_mode():
                    badge_pm_orig = _tint_pixmap(badge_pm_orig, QColor(Qt.white))
            except Exception:
                pass
            out = QIcon()
            for size in (16, 20, 24, 28, 32, 40, 48):
                base_pm = base.pixmap(size, size)
                if base_pm.isNull():
                    continue
                canvas = QPixmap(size, size)
                canvas.fill(Qt.transparent)
                p = QPainter(canvas)
                try:
                    p.setRenderHint(QPainter.Antialiasing, True)
                    p.drawPixmap(0, 0, base_pm)
                    b = max(8, int(size * 0.45))
                    badge_pm = badge_pm_orig.scaled(b, b, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    m = max(1, int(size * 0.08))
                    x = size - badge_pm.width() - m
                    y = size - badge_pm.height() - m
                    p.drawPixmap(x, y, badge_pm)
                finally:
                    p.end()
                out.addPixmap(canvas)
            return out if not out.isNull() else base
        except Exception:
            return base

    def get_icon(self, item: dict) -> QIcon:
        if item.get("type") == "folder":
            overlay_enabled = not getattr(self, "_disable_sync_overlay", False)
            
            try:
                if CUSTOM_FOLDER_ICON_PATH and os.path.exists(CUSTOM_FOLDER_ICON_PATH):
                    base_ic = QIcon(CUSTOM_FOLDER_ICON_PATH)
                    self._cache["folder"] = base_ic
                    if overlay_enabled and bool(item.get("sync")):
                        badge = os.path.join(CUSTOM_ICONS_DIR, "sync.png")
                        return self._overlay_badge(base_ic, badge)
                    return base_ic
            except Exception:
                pass
            
            try:
                for name in self.FOLDER_ICON_CANDIDATES:
                    p = os.path.join(CUSTOM_ICONS_DIR, name)
                    if os.path.exists(p):
                        base_ic = QIcon(p)
                        self._cache["folder"] = base_ic
                        if overlay_enabled and bool(item.get("sync")):
                            badge = os.path.join(CUSTOM_ICONS_DIR, "sync.png")
                            return self._overlay_badge(base_ic, badge)
                        return base_ic
            except Exception:
                pass
            base_ic = self._cache["folder"]
            if overlay_enabled and bool(item.get("sync")):
                badge = os.path.join(CUSTOM_ICONS_DIR, "sync.png")
                return self._overlay_badge(base_ic, badge)
            return base_ic

        name = item.get("originalName") or item.get("name") or ""
        ext = file_ext(name)

        if not ext: return self._cache["__default__"]
        if ext in self._cache: return self._cache[ext]
        
        try:
            fname = getattr(self, "EXT_ICON_MAP", {}).get(ext)
            if fname:
                p = os.path.join(CUSTOM_ICONS_DIR, fname)
                if os.path.exists(p):
                    ic = QIcon(p)
                    self._cache[ext] = ic
                    return ic
        except Exception:
            pass
        
        try:
            for cand in (f"{ext}.png", f"{ext}.svg"):
                p = os.path.join(CUSTOM_ICONS_DIR, cand)
                if os.path.exists(p):
                    ic = QIcon(p)
                    self._cache[ext] = ic
                    return ic
        except Exception:
            pass

        color_map = {
            'pdf': '#D92D20', 'docx': '#1D6F93', 'doc': '#1D6F93',
            'xlsx': '#1D6F42', 'xls': '#1D6F42', 'csv': '#1D6F42',
            'pptx': '#C1421D', 'ppt': '#C1421D',
            'jpg': '#F7921E', 'jpeg': '#F7921E', 'png': '#F7921E', 'gif': '#F7921E',
            'zip': '#6E6E6E', 'rar': '#6E6E6E', '7z': '#6E6E6E',
            'txt': '#555555', 'cad': '#2F6BFF', 'dwg': '#2F6BFF', 'dxf': '#2F6BFF'
        }
        color = QColor(color_map.get(ext, '#888888'))
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(pixmap.rect().adjusted(1, 1, -1, -1), 5, 5)
        text_color = Qt.white if color.lightness() < 160 else QColor("#222222")
        painter.setPen(text_color)
        font = painter.font(); font.setBold(True); font.setPointSize(9); painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignCenter, ext[:3].upper())
        painter.end()
        icon = _icon_from_pixmap_variants(pixmap)
        self._cache[ext] = icon
        return icon


class FilesTableModel(QAbstractTableModel):
    HEADERS = ["", "Название", "Версия", "Тип", "Формат", "Кем создан", "Создано", "Изменено", "Кем изменено"]
    SORT_ROLE = Qt.UserRole + 1


    def __init__(self, items: list, icon_provider: IconProvider, checked: set):
        super().__init__()
        self._data = items or []
        self._icon_provider = icon_provider
        self.checked = checked  # общее множество отмеченных ключей
        
    def _cb_key(self, item: dict) -> tuple:
        """Генерирует ключ для чекбокса независимо от наличия id"""
        return (item.get("type"), item.get("id") or f"tmp:{id(item)}")
        

    def rowCount(self, parent=QModelIndex()): 
        return len(self._data)

    def columnCount(self, parent=QModelIndex()): 
        return len(self.HEADERS)

    def item_at(self, row: int) -> dict:
        if 0 <= row < len(self._data): 
            return self._data[row]
        return {}

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            try: return self.HEADERS[section]
            except IndexError: return ""
        return None

    def _sort_key(self, item: dict, col: int):
        t = (item.get("type") or "").lower()
        name = (item.get("originalName") or item.get("name") or "")
        ext = file_ext(name)
        if col == 0:
            return 0
        if col == 1:
            return name.lower()
        if col == 2:
            try:
                return float(item.get("version") or 0)
            except (ValueError, TypeError):
                return 0.0
        if col == 3:
            return 0 if t == "folder" else 1
        if col == 4:
            return ext
        if col == 5:
            return (item.get("createdBy") or "").lower()
        if col == 6:
            return parse_date_like(item.get("createTime") or item.get("createdAt"))
        if col == 7:
            return parse_date_like(item.get("modifTime") or item.get("updatedAt") or item.get("modifiedDate"))
        if col == 8:
            return item.get("modifiedBy") or item.get("author") or ""
        return 0


    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        item = self._data[index.row()]
        col = index.column()

        if role == Qt.UserRole:
            return item

        if role == Qt.DecorationRole and col == 1:
            return self._icon_provider.get_icon(item)

        if role == Qt.CheckStateRole and col == 0:
            key = self._cb_key(item)
            current_state = Qt.Checked if key in self.checked else Qt.Unchecked
            return current_state

        if role == Qt.DisplayRole:
            if col == 0:
                return ""
            if col == 1:
                return item.get("originalName") or item.get("name") or "Без имени"
            if col == 2:
                return str(item.get("version") or "")
            if col == 3:
                return "Папка" if (item.get("type") == "folder") else "Файл"
            if col == 4:
                name = item.get("originalName") or item.get("name") or ""
                return file_ext(name).upper()
            if col == 5:
                return item.get("createdBy") or ""
            if col == 6:
                val = item.get("createTime") or item.get("createdAt") or ""
                ts = parse_date_like(val)
                return _user_display_datetime(ts) if ts > 0 else val
            if col == 7:
                val = item.get("modifTime") or item.get("updatedAt") or item.get("modifiedDate") or ""
                ts = parse_date_like(val)
                return _user_display_datetime(ts) if ts > 0 else val
            if col == 8: 
                return (item.get("modifiedBy") or item.get("author") or "")
            return ""

        if role == FilesTableModel.SORT_ROLE:
            item = self._data[index.row()]
            return self._sort_key(item, index.column())

        return None

    def flags(self, index):
        if not index.isValid(): return Qt.ItemIsEnabled
        item = self._data[index.row()]; col = index.column()
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if col == 0:
            return base | Qt.ItemIsUserCheckable
        return base

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid(): return False
        item = self._data[index.row()]; col = index.column()
        if role == Qt.CheckStateRole and col == 0:
            key = self._cb_key(item)
            if value == Qt.Checked: self.checked.add(key)
            else: self.checked.discard(key)
            self.dataChanged.emit(index, index, [Qt.CheckStateRole])
            return True
        return False

    def set_items(self, items: list):
        """Update model data and emit layout change signals."""
        self.beginResetModel()
        self._data = items or []
        self.endResetModel()
