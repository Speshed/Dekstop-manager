from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from larix_nexus.ui import download_operations, main_window


def _download_window(local_path):
    wait = Mock()
    window = SimpleNamespace(
        ensure_downloaded=Mock(return_value=str(local_path)),
        _set_progress_visible=Mock(),
        progress=SimpleNamespace(setRange=Mock()),
        status=SimpleNamespace(showMessage=Mock(), clearMessage=Mock()),
        _force_mode=None,
    )
    window._copy_file_atomically = download_operations._copy_file_atomically
    return window, wait


def test_download_file_plain_copy_error_keeps_existing_destination(monkeypatch, tmp_path):
    source = tmp_path / "source.bin"
    destination = tmp_path / "destination.bin"
    source.write_text("new-content", encoding="utf-8")
    destination.write_text("old-content", encoding="utf-8")
    window, wait = _download_window(source)
    messages = []

    monkeypatch.setattr(download_operations.QFileDialog, "getSaveFileName", lambda *args: (str(destination), ""))
    monkeypatch.setattr(download_operations, "WaitDialog", lambda *args: wait)
    monkeypatch.setattr(download_operations.QApplication, "processEvents", lambda: None)
    monkeypatch.setattr(download_operations.shutil, "copyfile", Mock(side_effect=OSError("copy failed")))
    monkeypatch.setattr("builtins.print", lambda message="": messages.append(str(message)))

    download_operations.download_file_plain(window, {"type": "file", "name": "source.bin"})

    assert destination.read_text(encoding="utf-8") == "old-content"
    assert not list(tmp_path.glob(f".{destination.name}.*.tmp"))
    assert any("WARNING" in message for message in messages)
    assert not any("INFO" in message for message in messages)


def test_download_checked_copy_error_keeps_existing_destination_and_resets_busy(monkeypatch, tmp_path):
    source = tmp_path / "source.bin"
    destination = tmp_path / "destination.bin"
    source.write_text("new-content", encoding="utf-8")
    destination.write_text("old-content", encoding="utf-8")
    warnings = []
    information = []
    window = SimpleNamespace(
        _dl_busy=False,
        get_checked_visible_items=Mock(return_value=[{"type": "file", "id": 1, "name": "source.bin"}]),
        ensure_downloaded=Mock(return_value=str(source)),
        _set_progress_visible=Mock(),
        progress=SimpleNamespace(setRange=Mock()),
        status=SimpleNamespace(showMessage=Mock(), clearMessage=Mock()),
        _force_mode=None,
        _chosen_items_for_download=Mock(return_value=[{"type": "file", "id": 1, "name": "source.bin"}]),
        _copy_file_atomically=download_operations._copy_file_atomically,
    )

    monkeypatch.setattr(main_window.QFileDialog, "getSaveFileName", lambda *args: (str(destination), ""))
    monkeypatch.setattr(main_window.QMessageBox, "warning", lambda *args: warnings.append(args))
    monkeypatch.setattr(main_window.QMessageBox, "information", lambda *args: information.append(args))
    monkeypatch.setattr(main_window.QApplication, "processEvents", lambda: None)
    monkeypatch.setattr(main_window, "t", lambda key, **kwargs: key)
    monkeypatch.setattr(main_window.shutil, "copyfile", Mock(side_effect=OSError("copy failed")))

    main_window.MainWindow.action_download_files(window)

    assert destination.read_text(encoding="utf-8") == "old-content"
    assert not list(tmp_path.glob(f".{destination.name}.*.tmp"))
    assert information == []
    assert warnings
    assert window._dl_busy is False
