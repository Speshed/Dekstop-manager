import json

from larix_nexus.notifications import manager


def test_sync_errors_round_trip_and_deduplicate_only_within_batch(tmp_path, monkeypatch):
    path = tmp_path / "sync_errors.json"
    monkeypatch.setattr(manager, "_sync_errors_path", lambda: str(path))

    first = {"timestamp": "1", "mode": "auto", "error": "HTTP 500"}
    second = {"timestamp": "2", "mode": "auto", "error": "HTTP 500"}
    assert manager.add_sync_errors([first, first]) == [first]
    assert manager.add_sync_errors([second, second]) == [first, second]
    assert manager.load_sync_errors() == [first, second]


def test_sync_errors_corrupted_json_returns_empty_and_can_recover(tmp_path, monkeypatch):
    path = tmp_path / "sync_errors.json"
    path.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(manager, "_sync_errors_path", lambda: str(path))

    assert manager.load_sync_errors() == []
    record = {"error": "mapping_missing"}
    assert manager.add_sync_errors([record]) == [record]
    assert json.loads(path.read_text(encoding="utf-8"))["errors"] == [record]


def test_sync_errors_cap_keeps_newest_records(tmp_path, monkeypatch):
    path = tmp_path / "sync_errors.json"
    monkeypatch.setattr(manager, "_sync_errors_path", lambda: str(path))

    records = [{"id": index} for index in range(4)]
    assert manager.add_sync_errors(records, max_entries=2) == records[-2:]


def test_clear_sync_errors_does_not_remove_log_file(tmp_path, monkeypatch):
    path = tmp_path / "sync_errors.json"
    log_path = tmp_path / "sync.log"
    log_path.write_text("diagnostic log", encoding="utf-8")
    monkeypatch.setattr(manager, "_sync_errors_path", lambda: str(path))

    manager.add_sync_errors([{"error": "boom"}])
    assert manager.clear_sync_errors() is True
    assert manager.load_sync_errors() == []
    assert log_path.read_text(encoding="utf-8") == "diagnostic log"
