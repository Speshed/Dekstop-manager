from types import SimpleNamespace

from larix_nexus.ui import sync_handlers


class _FakeDialog:
    instances = []

    def __init__(self, parent, local_path, guard, callback):
        self.local_path = local_path
        self.guard = guard
        self.callback = callback
        self.opened = False
        self.__class__.instances.append(self)

    def open(self):
        self.opened = True


def _guard(path, count, total):
    return {
        "delete_count": count,
        "total_files": total,
        "delete_percent": count / total * 100,
        "sample_paths": [path + "/removed.pdf"],
    }


def test_auto_mass_delete_decisions_are_sequential(monkeypatch):
    _FakeDialog.instances = []
    started = []
    window = SimpleNamespace(
        _trigger_sync_now=lambda folder_id, **kwargs: started.append((folder_id, kwargs)),
    )
    window._show_next_auto_mass_delete_confirmation = lambda: sync_handlers._show_next_auto_mass_delete_confirmation(window)
    window._handle_auto_mass_delete_decision = lambda *args: sync_handlers._handle_auto_mass_delete_decision(window, *args)
    monkeypatch.setattr(sync_handlers, "MassDeleteConfirmationDialog", _FakeDialog)
    monkeypatch.setattr(sync_handlers.QTimer, "singleShot", lambda _delay, callback: callback())

    first = {"folder_id": "one", "local_root": "C:/one", "guard": _guard("C:/one", 4, 4)}
    second = {"folder_id": "two", "local_root": "C:/two", "guard": _guard("C:/two", 3, 5)}
    window._auto_mass_delete_results = [first, second]

    sync_handlers._start_auto_mass_delete_confirmations(window)
    assert len(_FakeDialog.instances) == 1
    assert started == []

    _FakeDialog.instances[0].callback(True, False)
    assert len(_FakeDialog.instances) == 2
    assert started == []

    _FakeDialog.instances[1].callback(False, False)
    assert started == [("one", {"allow_mass_delete": True, "sync_mode": "manual"})]


def test_auto_mass_delete_apply_all_cancel_is_safe(monkeypatch):
    _FakeDialog.instances = []
    started = []
    window = SimpleNamespace(
        _trigger_sync_now=lambda folder_id, **kwargs: started.append((folder_id, kwargs)),
    )
    window._show_next_auto_mass_delete_confirmation = lambda: sync_handlers._show_next_auto_mass_delete_confirmation(window)
    window._handle_auto_mass_delete_decision = lambda *args: sync_handlers._handle_auto_mass_delete_decision(window, *args)
    monkeypatch.setattr(sync_handlers, "MassDeleteConfirmationDialog", _FakeDialog)
    monkeypatch.setattr(sync_handlers.QTimer, "singleShot", lambda _delay, callback: callback())
    window._auto_mass_delete_results = [
        {"folder_id": "one", "local_root": "C:/one", "guard": _guard("C:/one", 4, 4)},
        {"folder_id": "two", "local_root": "C:/two", "guard": _guard("C:/two", 3, 5)},
    ]

    sync_handlers._start_auto_mass_delete_confirmations(window)
    _FakeDialog.instances[0].callback(False, True)

    assert started == []
    assert window._auto_mass_delete_queue_active is False


def test_cancel_finishes_status_cleanup_once(monkeypatch):
    _FakeDialog.instances = []
    cleanup = []
    window = SimpleNamespace(
        _trigger_sync_now=lambda *_args, **_kwargs: False,
        _set_progress_cancel_handler=lambda value: cleanup.append(("cancel", value)),
        _end_sync_status=lambda message, timeout: cleanup.append(("end", message, timeout)),
    )
    window._show_next_auto_mass_delete_confirmation = lambda: sync_handlers._show_next_auto_mass_delete_confirmation(window)
    window._handle_auto_mass_delete_decision = lambda *args: sync_handlers._handle_auto_mass_delete_decision(window, *args)
    monkeypatch.setattr(sync_handlers, "MassDeleteConfirmationDialog", _FakeDialog)
    monkeypatch.setattr(sync_handlers.QTimer, "singleShot", lambda _delay, callback: callback())
    window._auto_mass_delete_results = [
        {"folder_id": "one", "local_root": "C:/one", "guard": _guard("C:/one", 4, 4)},
    ]

    sync_handlers._start_auto_mass_delete_confirmations(window)
    _FakeDialog.instances[0].callback(False, False)
    _FakeDialog.instances[0].callback(False, False)

    assert [entry[0] for entry in cleanup] == ["cancel", "end"]


def test_confirmation_cleanup_hides_progress_when_counter_is_stale():
    class Progress:
        def __init__(self):
            self.visible = True
            self.range = None
            self.value = None

        def setVisible(self, value): self.visible = value
        def setRange(self, minimum, maximum): self.range = (minimum, maximum)
        def setValue(self, value): self.value = value

    progress = Progress()
    window = SimpleNamespace(
        _mass_delete_confirmation_finished=False,
        _mass_delete_confirmation_reruns_pending=0,
        _active_sync_count=2,
        progress=progress,
        _set_progress_cancel_handler=lambda value: None,
        _end_sync_status=lambda message, timeout: None,
    )
    sync_handlers._finish_mass_delete_confirmation_flow(window, "Готово")
    assert progress.visible is False
    assert progress.range == (0, 0)
    assert progress.value == 0
