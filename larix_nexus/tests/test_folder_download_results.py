import zipfile

from larix_nexus.ui import download_operations as ops
from larix_nexus.ui import main_window


class _ZipApi:
    def write_file_to(self, file_id, output):
        if file_id == "bad":
            return False
        output.write(b"ok")
        return True


class _DownloadStub:
    api = _ZipApi()

    def _unique_name(self, _folder, name):
        return name

    def ensure_downloaded(self, item):
        return item.get("local", "")


def test_zip_folder_omits_failed_entry(tmp_path):
    archive = tmp_path / "result.zip"
    node = {
        "type": "folder",
        "name": "folder",
        "children": [
            {"type": "file", "id": "ok", "name": "ok.txt"},
            {"type": "file", "id": "bad", "name": "bad.txt"},
        ],
    }

    with zipfile.ZipFile(archive, "w") as zf:
        result = ops._zip_folder_into(_DownloadStub(), node, zf)

    assert result["total"] == 2
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert zipfile.ZipFile(archive).namelist() == ["folder/ok.txt"]


def test_copy_folder_counts_empty_download(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"ok")
    destination = tmp_path / "out"
    node = {
        "type": "folder",
        "name": "folder",
        "children": [
            {"type": "file", "id": "ok", "name": "ok.bin", "local": str(source)},
            {"type": "file", "id": "missing", "name": "missing.bin", "local": ""},
        ],
    }

    result = ops._copy_folder_into(_DownloadStub(), node, str(destination))

    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert (destination / "folder" / "ok.bin").read_bytes() == b"ok"
    assert not (destination / "folder" / "missing.bin").exists()


def test_report_download_result_partial_uses_warning(monkeypatch):
    calls = []
    monkeypatch.setattr(main_window.QMessageBox, "information", lambda *args: calls.append(("info", args)))
    monkeypatch.setattr(main_window.QMessageBox, "warning", lambda *args: calls.append(("warning", args)))

    main_window.MainWindow._report_download_result(
        object(), {"total": 2, "succeeded": 1, "failed": 1, "errors": []}, "structure.title", "structure.done"
    )

    assert [kind for kind, _ in calls] == ["warning"]


def test_report_download_result_full_failure_removes_zip(monkeypatch, tmp_path):
    calls = []
    archive = tmp_path / "failed.zip"
    archive.write_bytes(b"empty")
    monkeypatch.setattr(main_window.QMessageBox, "information", lambda *args: calls.append("info"))
    monkeypatch.setattr(main_window.QMessageBox, "warning", lambda *args: calls.append("warning"))

    main_window.MainWindow._report_download_result(
        object(), {"total": 1, "succeeded": 0, "failed": 1, "errors": []}, "zip.title", "zip.created", str(archive)
    )

    assert calls == ["warning"]
    assert not archive.exists()


class _BatchZipWindow:
    class _Progress:
        def setRange(self, *_args):
            pass

        def setValue(self, *_args):
            pass

    progress = _Progress()


def _batch_zip_window(items, local_paths):
    window = _BatchZipWindow()
    window._chosen_items_for_download = lambda: items
    window._set_progress_visible = lambda _visible: None
    window._new_download_result = ops._new_download_result
    window._merge_download_result = ops._merge_download_result
    window._download_failure = ops._download_failure
    window._report_download_result = main_window.MainWindow._report_download_result.__get__(window)
    window.ensure_downloaded = lambda item: local_paths.get(item["id"], "")
    return window


def test_action_download_zip_first_failed_file_keeps_successful_entry(monkeypatch, tmp_path):
    archive = tmp_path / "partial.zip"
    good_file = tmp_path / "good.txt"
    good_file.write_text("good", encoding="utf-8")
    items = [
        {"type": "file", "id": "bad", "name": "bad.txt"},
        {"type": "file", "id": "good", "name": "good.txt"},
    ]
    window = _batch_zip_window(items, {"good": str(good_file)})
    messages = []
    monkeypatch.setattr(main_window.QFileDialog, "getSaveFileName", lambda *args: (str(archive), "ZIP"))
    monkeypatch.setattr(main_window.QMessageBox, "information", lambda *args: messages.append("info"))
    monkeypatch.setattr(main_window.QMessageBox, "warning", lambda *args: messages.append("warning"))

    main_window.MainWindow.action_download_zip(window)

    with zipfile.ZipFile(archive) as zf:
        assert zf.namelist() == ["good.txt"]
    assert messages == ["warning"]


def test_action_download_zip_single_failed_file_removes_empty_zip(monkeypatch, tmp_path):
    archive = tmp_path / "failed.zip"
    items = [{"type": "file", "id": "bad", "name": "bad.txt"}]
    window = _batch_zip_window(items, {})
    messages = []
    monkeypatch.setattr(main_window.QFileDialog, "getSaveFileName", lambda *args: (str(archive), "ZIP"))
    monkeypatch.setattr(main_window.QMessageBox, "information", lambda *args: messages.append("info"))
    monkeypatch.setattr(main_window.QMessageBox, "warning", lambda *args: messages.append("warning"))

    main_window.MainWindow.action_download_zip(window)

    assert not archive.exists()
    assert messages == ["warning"]


def test_download_checked_mixed_zip_first_failed_file_keeps_successful_entry(monkeypatch, tmp_path):
    archive = tmp_path / "checked-mixed.zip"
    good_file = tmp_path / "good.txt"
    good_file.write_text("good", encoding="utf-8")
    items = [
        {"type": "file", "id": "bad", "name": "bad.txt"},
        {"type": "file", "id": "good", "name": "good.txt"},
        {"type": "folder", "id": "folder", "name": "empty", "children": []},
    ]
    window = _batch_zip_window(items, {"good": str(good_file)})
    window.get_checked_visible_items = lambda: items
    window._ask_mode = lambda *_args: "B"
    window._zip_folder_into = lambda *_args, **_kwargs: ops._new_download_result()
    messages = []
    monkeypatch.setattr(main_window.QFileDialog, "getSaveFileName", lambda *args: (str(archive), "ZIP"))
    monkeypatch.setattr(main_window.QMessageBox, "information", lambda *args: messages.append("info"))
    monkeypatch.setattr(main_window.QMessageBox, "warning", lambda *args: messages.append("warning"))

    main_window.MainWindow.download_checked(window)

    with zipfile.ZipFile(archive) as zf:
        assert zf.namelist() == ["good.txt"]
    assert messages == ["warning"]
