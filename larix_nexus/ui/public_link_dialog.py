from PySide6.QtCore import QObject, QThread, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from larix_nexus.constants import COPY_FOLDER_ICON_PATH
from larix_nexus.utils.i18n import t
from larix_nexus.utils.theme import themed_icon


class PublicLinkLookupWorker(QObject):
    finished = Signal(object, object)

    def __init__(self, api, target_id):
        super().__init__()
        self.api = api
        self.target_id = target_id

    @Slot()
    def run(self):
        try:
            result = self.api.get_public_link_info_result(self.target_id)
        except Exception:
            result = type("LookupResult", (), {"status": "network_error", "value": None})()
        self.finished.emit(self.target_id, result)


class PublicLinkOperationWorker(QObject):
    finished = Signal(object)

    def __init__(self, api, operation, target_id, is_version=False,
                 validity_period=None, granted_access=None):
        super().__init__()
        self.api = api
        self.operation = operation
        self.target_id = target_id
        self.is_version = bool(is_version)
        self.validity_period = validity_period
        self.granted_access = granted_access

    @Slot()
    def run(self):
        try:
            if self.operation == "create":
                result = self.api.generate_public_link_result(
                    self.target_id, self.is_version,
                    self.validity_period, self.granted_access
                )
                if not result:
                    self.finished.emit({"operation": "create", "status": result.status, "value": None})
                    return
                info = self.api.get_public_link_info_result(self.target_id)
                self.finished.emit({"operation": "create", "status": info.status, "value": info.value})
                return
            result = self.api.delete_public_link_result(self.target_id)
            self.finished.emit({"operation": "delete", "status": result.status, "value": result.value})
        except Exception:
            self.finished.emit({"operation": self.operation, "status": "network_error", "value": None})


class _PublicLinkGuiRelay(QObject):
    result_ready = Signal(object)


class PublicLinkDialog(QDialog):
    """Create or manage exactly one public link."""
    def __init__(self, api, target_id, *, is_version=False, version_number=None,
        existing_url=None, parent=None, on_changed=None, parent_file_id=None, version_item=None):
        super().__init__(parent)
        self.api = api
        self.target_id = target_id
        self.is_version = bool(is_version)
        self.on_changed = on_changed
        self.parent_file_id = parent_file_id
        self.version_item = version_item
        self._busy = False
        self._closed = False
        self._operation_thread = None
        self._operation_worker = None
        self._mode = "manage" if existing_url else "checking_existing"
        self._create_interacted = False
        self._operation_relay = _PublicLinkGuiRelay(self)
        self._operation_relay.result_ready.connect(self._on_operation_finished, Qt.QueuedConnection)
        self.finished.connect(self._on_dialog_finished)
        self.setWindowTitle(t("public_link.title"))
        self.setMinimumWidth(430)
        self._root = QVBoxLayout(self)
        self._pages = QStackedWidget(self)
        self._create_page = QWidget(self._pages)
        self._manage_page = QWidget(self._pages)
        self._create_layout = QVBoxLayout(self._create_page)
        self._manage_layout = QVBoxLayout(self._manage_page)
        self._pages.addWidget(self._create_page)
        self._pages.addWidget(self._manage_page)
        self._root.addWidget(self._pages)
        self._build_create(version_number)
        self._build_manage(str(existing_url or ""))
        if existing_url:
            self.show_manage_mode(existing_url)
        else:
            self.show_create_mode(checking=True)

    def _build_create(self, version_number):
        form = QFormLayout()
        self.validity = QComboBox(self)
        self.validity.setObjectName("publicLinkValidityCombo")
        for code, label in (("Day", "public_link.day"), ("Week", "public_link.week"),
                            ("Month", "public_link.month"), ("NeverExpires", "public_link.never")):
            self.validity.addItem(t(label), code)
        self.validity.insertItem(0, t("public_link.validity_placeholder"), None)
        self.validity.setCurrentIndex(0)
        self.access = QComboBox(self)
        self.access.setObjectName("publicLinkAccessCombo")
        self.access.addItem(t("public_link.access_view"), "View")
        self.access.addItem(t("public_link.access_download"), "Download")
        self.access.insertItem(0, t("public_link.access_placeholder"), None)
        self.access.setCurrentIndex(0)
        self.validity.currentIndexChanged.connect(self._mark_create_interacted)
        self.access.currentIndexChanged.connect(self._mark_create_interacted)
        self.validity.currentIndexChanged.connect(self._update_create_button)
        self.access.currentIndexChanged.connect(self._update_create_button)
        self.version = QLineEdit(
            t("public_link.version_number", number=version_number)
            if self.is_version else t("public_link.version_current"), self
        )
        self.version.setReadOnly(True)
        form.addRow(t("public_link.activity"), self.validity)
        form.addRow(t("public_link.access"), self.access)
        form.addRow(t("public_link.version_available"), self.version)
        self._create_layout.addLayout(form)
        self.operation_status = QLabel("", self)
        self.operation_status.setObjectName("publicLinkOperationStatus")
        self._create_layout.addWidget(self.operation_status)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel, parent=self)
        self._cancel_button = buttons.button(QDialogButtonBox.Cancel)
        self.create_button = QPushButton(t("public_link.create_button"), self)
        self.create_button.setObjectName("btn_primary")
        self.create_button.setEnabled(False)
        self.create_button.setDefault(True)
        self.create_button.clicked.connect(self._create)
        buttons.addButton(self.create_button, QDialogButtonBox.AcceptRole)
        buttons.rejected.connect(self.reject)
        self._create_layout.addWidget(buttons)

    def _build_manage(self, url):
        self.url = QLineEdit(url, self)
        self.url.setReadOnly(True)
        self._manage_layout.addWidget(QLabel(t("public_link.url"), self._manage_page))
        self._manage_layout.addWidget(self.url)
        row = QDialogButtonBox(parent=self)
        self.open_button = row.addButton(t("public_link.open"), QDialogButtonBox.ActionRole)
        self.copy_button = row.addButton(t("public_link.copy"), QDialogButtonBox.ActionRole)
        self.copy_button.setIcon(themed_icon(COPY_FOLDER_ICON_PATH))
        self.delete_button = row.addButton(t("public_link.delete"), QDialogButtonBox.DestructiveRole)
        self.open_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.url.text())))
        self.copy_button.clicked.connect(self._copy_url)
        self.delete_button.clicked.connect(self._delete)
        self._manage_layout.addWidget(row)
        close = QDialogButtonBox(QDialogButtonBox.Close, parent=self)
        self._cancel_button = close.button(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        self._manage_layout.addWidget(close)

    def _mark_create_interacted(self, *_args):
        if self._mode == "checking_existing":
            self._mode = "create"
        self._create_interacted = True

    def _update_create_button(self, *_args):
        if hasattr(self, "create_button"):
            self.create_button.setEnabled(
                not self._busy and self.validity.currentData() is not None and
                self.access.currentData() is not None
            )

    def show_create_mode(self, checking=False):
        if self._closed:
            return
        self._pages.setCurrentWidget(self._create_page)
        self._mode = "checking_existing" if checking else "create"
        self._update_create_button()
        self.adjustSize()

    def show_manage_mode(self, url):
        if self._closed:
            return
        self.url.setText(str(url or ""))
        self._pages.setCurrentWidget(self._manage_page)
        self._mode = "manage"
        self.adjustSize()

    @Slot(object)
    def apply_existing_link(self, url):
        """Apply a late lookup result only before the user touched create mode."""
        if (self._closed or not self.isVisible() or self._busy or
                self._mode not in ("checking_existing", "create") or self._create_interacted):
            return False
        self.show_manage_mode(url)
        return True

    @Slot()
    def finish_existing_lookup_without_link(self):
        if not self._closed and not self._busy and self._mode == "checking_existing":
            self._mode = "create"

    def _set_busy(self, busy):
        self._busy = bool(busy)
        for button in self.findChildren(QPushButton):
            if button is not getattr(self, "_cancel_button", None):
                button.setEnabled(not busy)
        status = getattr(self, "operation_status", None)
        if status is not None:
            status.setText(t("public_link.creating" if busy and hasattr(self, "create_button")
                             else "public_link.deleting" if busy else "public_link.ready"))
            status.setVisible(bool(busy))

    def _start_operation(self, operation, *, validity_period=None, granted_access=None):
        if self._operation_thread is not None or self._closed:
            return
        self._mode = "creating" if operation == "create" else "deleting"
        thread = QThread(self)
        worker = PublicLinkOperationWorker(
            self.api, operation, self.target_id, self.is_version,
            validity_period, granted_access
        )
        worker.moveToThread(thread)
        self._operation_thread = thread
        self._operation_worker = worker

        worker.finished.connect(self._operation_relay.result_ready, Qt.QueuedConnection)
        worker.finished.connect(thread.quit)
        thread.started.connect(worker.run)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._operation_cleanup)
        thread.start()

    @Slot(object)
    def _on_operation_finished(self, result):
        if self._closed or not self.isVisible():
            return
        self._operation_result(result)

    @Slot(int)
    def _on_dialog_finished(self, _result):
        self._closed = True

    @Slot()
    def _operation_cleanup(self):
        self._operation_thread = None
        self._operation_worker = None

    def _operation_result(self, result):
        if self._closed or not self.isVisible():
            return
        operation = result.get("operation")
        status = result.get("status")
        if status != "ok":
            self._set_busy(False)
            self._mode = "manage" if operation == "delete" and hasattr(self, "url") else "create"
            self._error(type("Result", (), {"status": status})())
            return
        if operation == "create":
            url = result.get("value")
            self._notify_changed(True, url)
            self._set_busy(False)
            self.show_manage_mode(url)
            return
        self._notify_changed(False)
        self._set_busy(False)
        self.accept()

    def _notify_changed(self, state, url=None):
        if not self.on_changed:
            return
        try:
            self.on_changed(
                self.target_id, state, url, self.parent_file_id, self.version_item
            )
        except TypeError:
            try:
                self.on_changed(self.target_id, state, url)
            except TypeError:
                self.on_changed(self.target_id, state)

    def _error(self, result):
        key = {
            "forbidden": "public_link.error_forbidden", "auth_error": "public_link.error_auth",
            "network_error": "public_link.error_network", "timeout": "public_link.error_timeout",
            "server_error": "public_link.error_server",
        }.get(getattr(result, "status", ""), "public_link.error_invalid")
        QMessageBox.warning(self, t("public_link.title"), t(key))

    def _create(self):
        if self._busy or self._closed:
            return
        if self.validity.currentData() is None or self.access.currentData() is None:
            return
        self._create_interacted = True
        self._set_busy(True)
        self._start_operation(
            "create", validity_period=self.validity.currentData(),
            granted_access=self.access.currentData()
        )

    def _copy_url(self):
        QApplication.clipboard().setText(self.url.text())

    def _delete(self):
        if self._busy or self._closed:
            return
        if QMessageBox.question(self, t("public_link.title"), t("public_link.delete_confirm")) != QMessageBox.Yes:
            return
        self._set_busy(True)
        self._start_operation("delete")
