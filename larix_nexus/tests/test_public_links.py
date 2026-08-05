from types import SimpleNamespace
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem

import requests

from larix_nexus.api.client import APIClient
from larix_nexus.api.request_specs import (
    build_public_link_delete_payload,
    build_public_link_generate_payload,
)
from larix_nexus.ui.main_window import MainWindow, _FileVersionPublicLinkDelegate
from larix_nexus.models.files_table import FilesTableModel, IconProvider


def _client():
    api = APIClient.__new__(APIClient)
    api.base_url = "https://platform-api.larix.ru"
    api.token = "access"
    api.refresh_token = None
    api.cache = {"versions:12": (1, []), "docver:12": (1, [])}
    return api


class _Signal:
    def emit(self, *args):
        pass


class _FilesModel:
    def __init__(self):
        self._data = [{"id": 12, "name": "file.txt"}]
        self.dataChanged = _Signal()

    def index(self, row, column):
        return (row, column)


def _synced_file_item(registry):
    state = type("State", (), {})()
    state._public_links_by_target = registry
    state.files_model = _FilesModel()
    MainWindow._sync_public_link_file_state(state, 12)
    return state.files_model._data[0]


def test_file_and_version_public_links_have_separate_file_badge_state():
    file_only = _synced_file_item({
        "12": {"scope": "file", "parent_file_id": 12, "url": "file-url"},
    })
    assert file_only["has_public_link"] is True
    assert file_only["public_link_url"] == "file-url"

    version_only = _synced_file_item({
        "1201": {"scope": "version", "parent_file_id": 12, "url": "version-url"},
    })
    assert version_only["has_public_link"] is False
    assert version_only["public_link_state"] == "absent"
    assert "public_link_url" not in version_only

    both = _synced_file_item({
        "12": {"scope": "file", "parent_file_id": 12, "url": "file-url"},
        "1201": {"scope": "version", "parent_file_id": 12, "url": "version-url"},
    })
    assert both["has_public_link"] is True
    assert both["public_link_url"] == "file-url"


def test_file_level_badge_is_returned_by_files_model():
    app = QApplication.instance() or QApplication([])
    item = {
        "id": 12,
        "type": "file",
        "name": "file.txt",
        "has_public_link": True,
        "public_link_state": "exists",
    }
    model = FilesTableModel([item], IconProvider(app.style()), set())
    file_icon = model.data(model.index(0, 1), Qt.DecorationRole)
    assert file_icon is not None and not file_icon.isNull()
    assert model.data(model.index(0, 2), Qt.DecorationRole) is None


def test_version_only_file_row_has_no_version_column_badge():
    app = QApplication.instance() or QApplication([])
    item = {"id": 12, "type": "file", "name": "file.txt", "has_public_link": False}
    model = FilesTableModel([item], IconProvider(app.style()), set())
    assert model.data(model.index(0, 2), Qt.DecorationRole) is None


def test_version_link_delegate_paints_only_current_file_link():
    app = QApplication.instance() or QApplication([])
    delegate = _FileVersionPublicLinkDelegate()
    image = QImage(160, 24, QImage.Format_ARGB32)
    image.fill(0)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 160, 24)

    current = FilesTableModel([{
        "id": 12, "type": "file", "name": "file.txt",
        "version": 3, "has_public_link": True, "public_link_state": "exists",
    }], IconProvider(app.style()), set())
    painter = QPainter(image)
    delegate.paint(painter, option, current.index(0, 2))
    painter.end()

    historical = FilesTableModel([{
        "id": 12, "type": "file", "name": "file.txt",
        "version": 3, "has_public_link": False,
    }], IconProvider(app.style()), set())
    painter = QPainter(image)
    delegate.paint(painter, option, historical.index(0, 2))
    painter.end()


def test_version_lookup_result_after_dialog_destruction_is_ignored():
    class _DestroyedDialog:
        def isVisible(self):
            raise RuntimeError("wrapped C++ object has been deleted")

    state = type("State", (), {})()
    state._version_link_checks = {
        "version:1201": (1201, _DestroyedDialog(), None, None, "version")
    }
    result = SimpleNamespace(status="ok", value="https://example.test/version")
    MainWindow._on_version_link_check_finished(state, 1201, result)


def test_generate_payload_supports_all_periods_and_version_id():
    for period in ("Day", "Week", "Month", "NeverExpires"):
        payload = build_public_link_generate_payload(22180, True, period, "View")
        assert payload["linkValidityPeriod"] == period
        assert payload["grantedAccess"] == "View"
        assert payload["files"] == [22180]
        assert payload["isVersion"] is True


def test_link_info_distinguishes_not_found_and_forbidden(monkeypatch):
    api = _client()
    monkeypatch.setattr(requests, "get", lambda *a, **k: SimpleNamespace(status_code=404))
    assert api.get_public_link_info_result(12).status == "not_found"
    monkeypatch.setattr(requests, "get", lambda *a, **k: SimpleNamespace(status_code=403))
    assert api.get_public_link_info_result(12).status == "forbidden"


def test_link_info_retries_once_after_refresh(monkeypatch):
    api = _client()
    calls = []
    monkeypatch.setattr(api, "_handle_401", lambda: True)
    def get(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return SimpleNamespace(status_code=401)
        return SimpleNamespace(status_code=200, json=lambda: {"data": "https://platform.larix.ru/public_link/x"})
    monkeypatch.setattr(requests, "get", get)
    result = api.get_public_link_info_result(12)
    assert result.status == "ok"
    assert len(calls) == 2


def test_link_info_reports_timeout_and_invalid_json(monkeypatch):
    api = _client()
    def timeout(*args, **kwargs):
        raise requests.Timeout()
    monkeypatch.setattr(requests, "get", timeout)
    assert api.get_public_link_info_result(12).status == "timeout"
    monkeypatch.setattr(requests, "get", lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: []))
    assert api.get_public_link_info_result(12).status == "invalid_response"


def test_delete_payload_and_related_cache_invalidation(monkeypatch):
    api = _client()
    assert build_public_link_delete_payload(12) == {"folder_id": [], "document_id": [12]}
    monkeypatch.setattr(requests, "delete", lambda *a, **k: SimpleNamespace(status_code=200))
    assert api.delete_public_link_result(12).ok
    assert "versions:12" not in api.cache
    assert "docver:12" not in api.cache
