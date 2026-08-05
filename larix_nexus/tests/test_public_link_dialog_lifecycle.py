import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThread, Qt
from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QMainWindow

from larix_nexus.ui.public_link_dialog import PublicLinkDialog


class _Api:
    def generate_public_link_result(self, *args):
        return type("Result", (), {"status": "ok", "value": "token", "__bool__": lambda self: True})()

    def get_public_link_info_result(self, target_id):
        return type("Result", (), {"status": "ok", "value": "https://example.test/public", "__bool__": lambda self: True})()


def _app():
    return QApplication.instance() or QApplication([])


def test_public_link_dialog_non_blocking_close_releases_modality():
    app = _app()
    parent = QMainWindow()
    parent.show()
    dialog = PublicLinkDialog(_Api(), 12, parent=parent)
    dialog.setWindowModality(Qt.WindowModal)
    dialog.open()
    app.processEvents()
    assert dialog.isVisible()
    assert app.activeModalWidget() is dialog
    dialog.reject()
    app.processEvents()
    assert not dialog.isVisible()
    assert app.activeModalWidget() is not dialog
    parent.close()


def test_create_runs_off_gui_thread_and_keeps_dialog_visible():
    app = _app()
    gate = threading.Event()
    ticks = []

    class BlockingApi(_Api):
        def generate_public_link_result(self, *args):
            gate.wait(2)
            return super().generate_public_link_result(*args)

    parent = QMainWindow()
    dialog = PublicLinkDialog(BlockingApi(), 12, parent=parent)
    dialog.show()
    dialog.validity.setCurrentIndex(1)
    dialog.access.setCurrentIndex(1)
    dialog.create_button.click()
    assert dialog._busy is True
    assert dialog.isVisible()
    from PySide6.QtCore import QTimer
    QTimer.singleShot(20, lambda: ticks.append(True))
    deadline = time.time() + 0.4
    while time.time() < deadline and not ticks:
        app.processEvents()
        time.sleep(0.01)
    assert ticks
    gate.set()
    deadline = time.time() + 1.0
    while time.time() < deadline and not hasattr(dialog, "url"):
        app.processEvents()
        time.sleep(0.01)
    assert hasattr(dialog, "url")
    deadline = time.time() + 1.0
    while time.time() < deadline and dialog._operation_thread is not None:
        app.processEvents()
        time.sleep(0.01)
    dialog.reject()
    parent.close()


def test_operation_finished_slot_runs_on_gui_thread():
    app = _app()

    class TrackingDialog(PublicLinkDialog):
        from PySide6.QtCore import Slot

        @Slot(object)
        def _on_operation_finished(self, result):
            self.callback_thread = QThread.currentThread()
            super()._on_operation_finished(result)

    parent = QMainWindow()
    dialog = TrackingDialog(_Api(), 12, parent=parent)
    dialog.show()
    dialog.validity.setCurrentIndex(1)
    dialog.access.setCurrentIndex(1)
    dialog.create_button.click()
    deadline = time.time() + 1.0
    while time.time() < deadline and not hasattr(dialog, "callback_thread"):
        app.processEvents()
        time.sleep(0.01)
    assert dialog.callback_thread is app.thread()
    assert hasattr(dialog, "url")
    while dialog._operation_thread is not None:
        app.processEvents()
    dialog.reject()
    parent.close()


def test_late_lookup_only_switches_untouched_create_dialog():
    app = _app()
    parent = QMainWindow()
    dialog = PublicLinkDialog(_Api(), 12, parent=parent)
    dialog.show()
    app.processEvents()
    assert dialog._mode == "checking_existing"
    assert dialog.apply_existing_link("https://example.test/public")
    assert dialog._mode == "manage"
    dialog.reject()

    dialog = PublicLinkDialog(_Api(), 12, parent=parent)
    dialog.show()
    dialog.validity.setCurrentIndex(1)
    assert dialog._mode == "create"
    assert not dialog.apply_existing_link("https://example.test/public")
    assert dialog._mode == "create"
    dialog.reject()
    parent.close()


def test_create_and_manage_pages_do_not_overlap_or_duplicate_widgets():
    app = _app()
    parent = QMainWindow()
    dialog = PublicLinkDialog(_Api(), 12, parent=parent)
    dialog.show()
    app.processEvents()
    assert dialog.create_button.isVisible()
    assert dialog.validity.currentIndex() == 0
    assert dialog.validity.currentData() is None
    assert dialog.access.currentIndex() == 0
    assert dialog.access.currentData() is None
    assert not dialog.create_button.isEnabled()
    assert dialog.validity.isVisible()
    assert dialog.access.isVisible()
    assert not dialog.url.isVisible()
    assert len([w for w in dialog.findChildren(QLineEdit) if w.isVisible()]) == 1

    assert dialog.apply_existing_link("https://example.test/public")
    app.processEvents()
    assert dialog.url.isVisible()
    assert not dialog.create_button.isVisible()
    assert not dialog.validity.isVisible()
    assert not dialog.access.isVisible()
    assert len([w for w in dialog.findChildren(QLineEdit) if w.isVisible()]) == 1
    assert dialog.delete_button.isVisible()
    assert dialog.open_button.isVisible()
    assert dialog.copy_button.isVisible()

    first_url = dialog.url
    dialog.show_manage_mode("https://example.test/second")
    dialog.show_manage_mode("https://example.test/third")
    assert dialog.url is first_url
    assert len(dialog.findChildren(QComboBox)) == 2
    dialog.reject()
    parent.close()


def test_create_requires_both_explicit_selections():
    app = _app()
    parent = QMainWindow()
    dialog = PublicLinkDialog(_Api(), 12, parent=parent)
    dialog.show()
    app.processEvents()
    dialog.validity.setCurrentIndex(1)
    assert not dialog.create_button.isEnabled()
    dialog.access.setCurrentIndex(1)
    assert dialog.create_button.isEnabled()
    dialog.validity.setCurrentIndex(0)
    assert not dialog.create_button.isEnabled()
    assert dialog.version.isReadOnly()
    assert dialog.version.text()
    dialog.reject()
    parent.close()
