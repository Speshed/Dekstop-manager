import os
import sys
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from larix_nexus.ui.main_window import MainWindow
from larix_nexus.ui import download_operations
from PySide6.QtCore import QObject, QThread, Qt, Slot
from PySide6.QtWidgets import QApplication


class _Api:
    def write_file_to(self, file_id, target):
        if file_id == "bad":
            return False
        target.write(file_id.encode("ascii"))
        return True


def test_zip_worker_reports_download_pack_and_packed(tmp_path):
    archive = tmp_path / "result.zip"
    tasks = [{"key": "one", "file_id": "one", "archive_name": "nested/one.txt"}]
    worker = MainWindow._BatchZipDownloadWorker(_Api(), tasks, str(archive))
    events = []
    worker.sig_item_started.connect(lambda key, index, total: events.append((key, "downloading")))
    worker.sig_item_packed.connect(lambda key: events.append((key, "packed")))
    worker.sig_finished.connect(lambda ok, total, errors, cancelled, saved: events.append(("finished", saved)))

    worker.run()

    assert events == [("one", "downloading"), ("one", "packed"), ("finished", True)]
    assert archive.exists()


def test_zip_worker_does_not_mark_packed_while_write_is_in_progress(tmp_path):
    archive = tmp_path / "large.zip"
    packed = []

    class SlowApi:
        def write_file_to(self, file_id, target):
            assert packed == []
            target.write(b"large-data")
            assert packed == []
            return True

    worker = MainWindow._BatchZipDownloadWorker(
        SlowApi(), [{"key": "large", "file_id": "large", "archive_name": "large.bin"}], str(archive)
    )
    worker.sig_item_packed.connect(lambda key: packed.append(key))

    worker.run()

    assert packed == ["large"]
    assert archive.exists()


def test_zip_worker_keeps_next_file_after_error_and_reports_partial(tmp_path):
    archive = tmp_path / "partial.zip"
    tasks = [
        {"key": "bad", "file_id": "bad", "archive_name": "bad.txt"},
        {"key": "good", "file_id": "good", "archive_name": "good.txt"},
    ]
    worker = MainWindow._BatchZipDownloadWorker(_Api(), tasks, str(archive))
    result = []
    worker.sig_finished.connect(lambda ok, total, errors, cancelled, saved: result.append((ok, errors, saved)))

    worker.run()

    assert result[0][0] == 1
    assert result[0][1]
    assert result[0][2] is True
    assert archive.exists()


def test_zip_worker_cancel_removes_part_file(tmp_path):
    archive = tmp_path / "cancelled.zip"
    worker = MainWindow._BatchZipDownloadWorker(
        _Api(), [{"key": "one", "file_id": "one", "archive_name": "one.txt"}], str(archive)
    )
    worker.cancel()
    result = []
    worker.sig_finished.connect(lambda ok, total, errors, cancelled, saved: result.append((cancelled, saved)))

    worker.run()

    assert result == [(True, False)]
    assert not archive.exists()
    assert not (tmp_path / "cancelled.zip.part").exists()


def test_zip_worker_qthread_delivers_process_start_before_blocked_api(tmp_path):
    app = QApplication.instance() or QApplication([])
    started = threading.Event()
    release = threading.Event()
    statuses = []

    class BlockingApi:
        def write_file_to(self, file_id, target):
            started.set()
            release.wait(2)
            target.write(b"data")
            return True

    class Receiver(QObject):
        @Slot(str, int, int)
        def on_started(self, key, index, total):
            statuses.append((key, "process"))

    worker = MainWindow._BatchZipDownloadWorker(
        BlockingApi(), [{"key": "large", "file_id": "large", "archive_name": "large.bin"}], str(tmp_path / "thread.zip")
    )
    thread = QThread()
    receiver = Receiver()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.sig_item_started.connect(receiver.on_started, Qt.QueuedConnection)
    worker.sig_finished.connect(thread.quit, Qt.QueuedConnection)
    thread.start()

    deadline = time.time() + 2
    while not statuses and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert started.is_set()
    assert statuses == [("large", "process")]
    release.set()
    while thread.isRunning():
        app.processEvents()
        time.sleep(0.01)
    thread.wait(1000)


def test_structure_worker_qthread_delivers_statuses_in_gui_thread(tmp_path):
    app = QApplication.instance() or QApplication([])
    api_started = threading.Event()
    release = threading.Event()
    events = []
    gui_thread_id = threading.get_ident()
    worker_thread_ids = []

    class BlockingApi:
        def write_file_to(self, file_id, target):
            worker_thread_ids.append(threading.get_ident())
            if file_id == "one":
                api_started.set()
                release.wait(2)
            target.write(file_id.encode("ascii"))
            return True

    class Receiver(QObject):
        @Slot(str, int, int)
        def on_started(self, key, index, total):
            events.append((key, "process", index, threading.get_ident()))

        @Slot(str, str)
        def on_done(self, key, target_name):
            events.append((key, "ok", threading.get_ident()))

        @Slot(int, int, list, bool)
        def on_finished(self, ok_count, total, errors, cancelled):
            events.append(("finished", ok_count, threading.get_ident()))

    tasks = [
        {
            "key": "one",
            "file_id": "one",
            "target_name": os.path.join("folder", "one.txt"),
            "target_path": str(tmp_path / "folder" / "one.txt"),
        },
        {
            "key": "two",
            "file_id": "two",
            "target_name": os.path.join("folder", "nested", "two.txt"),
            "target_path": str(tmp_path / "folder" / "nested" / "two.txt"),
        },
    ]
    worker = MainWindow._BatchDownloadWorker(_Api(), tasks, str(tmp_path))
    assert worker._dest_dir == str(tmp_path)
    # Use the blocking API for this test, while keeping the worker implementation unchanged.
    worker._api = BlockingApi()
    thread = QThread()
    receiver = Receiver()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.sig_item_started.connect(receiver.on_started, Qt.QueuedConnection)
    worker.sig_item_done.connect(receiver.on_done, Qt.QueuedConnection)
    worker.sig_finished.connect(receiver.on_finished, Qt.QueuedConnection)
    worker.sig_finished.connect(thread.quit, Qt.QueuedConnection)
    thread.start()

    deadline = time.time() + 2
    while not api_started.is_set() or not events:
        app.processEvents()
        if time.time() >= deadline:
            break
        time.sleep(0.01)
    assert api_started.is_set()
    assert events == [("one", "process", 1, gui_thread_id)]
    release.set()

    deadline = time.time() + 2
    while thread.isRunning() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    thread.wait(1000)
    app.processEvents()

    assert [(event[0], event[1]) for event in events] == [
        ("one", "process"),
        ("one", "ok"),
        ("two", "process"),
        ("two", "ok"),
        ("finished", 2),
    ]
    assert all(event[-1] == gui_thread_id for event in events)
    assert worker_thread_ids and all(thread_id != gui_thread_id for thread_id in worker_thread_ids)
    assert (tmp_path / "folder" / "one.txt").read_bytes() == b"one"
    assert (tmp_path / "folder" / "nested" / "two.txt").read_bytes() == b"two"


def test_download_folder_plain_builds_structure_tasks_for_shared_batch_dialog(tmp_path):
    captured = []

    class Window:
        def _pick_directory_showing_files(self, _title):
            return str(tmp_path)

        def _start_structure_download_batch(self, tasks, dest_dir):
            captured.append((tasks, dest_dir))

    node = {
        "type": "folder",
        "children": [
            {"type": "file", "id": "root", "name": "root.txt"},
            {"type": "folder", "name": "nested", "children": [
                {"type": "file", "id": "child", "name": "child.txt"},
            ]},
        ],
    }

    download_operations.download_folder_plain(Window(), node)

    tasks, destination = captured[0]
    assert destination == str(tmp_path)
    assert [task["target_name"] for task in tasks] == ["root.txt", os.path.join("nested", "child.txt")]
    assert all(task["target_path"].startswith(str(tmp_path)) for task in tasks)


def test_action_download_folder_uses_structure_batch_not_legacy_download_checked(tmp_path):
    calls = []
    folder = {"type": "folder", "name": "docs", "children": [
        {"type": "file", "id": "one", "name": "one.txt"},
    ]}

    class Window:
        def _chosen_items_for_download(self):
            return [folder]

        def _pick_directory_showing_files(self, _title):
            return str(tmp_path)

        def _build_structure_download_tasks(self, items, destination):
            calls.append(("build", items, destination))
            return [{"key": "one", "target_name": "docs/one.txt"}]

        def _start_structure_download_batch(self, tasks, destination):
            calls.append(("start", tasks, destination))

        def download_checked(self):
            raise AssertionError("legacy download_checked route was used")

    MainWindow.action_download_folder(Window())

    assert [call[0] for call in calls] == ["build", "start"]
