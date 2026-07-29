import json

import larix_nexus.utils.atomic_json as atomic_json
import larix_nexus.utils.settings as settings_module


def _use_tmp_settings(monkeypatch, tmp_path):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(settings_module, "_settings_path", lambda: str(path))
    monkeypatch.setattr(
        settings_module,
        "_legacy_settings_path",
        lambda: str(tmp_path / "legacy-settings.json"),
    )
    return path


def test_load_settings_reads_valid_json_without_changing_values(monkeypatch, tmp_path):
    path = _use_tmp_settings(monkeypatch, tmp_path)
    expected = {
        "version": 1,
        "theme": "dark",
        "remember_me": True,
        "last_username": "user@example.test",
        "auto_login": True,
        "ui": {"window_geometry": "geometry", "splitter_state": None, "column_widths": {}},
        "sync": {
            "auto_sync_interval": 120,
            "notification_refresh_interval": 60,
            "conflict_resolution": "local",
            "mass_delete_threshold": 10,
        },
        "unrelated": {"keep": True},
    }
    path.write_text(json.dumps(expected), encoding="utf-8")

    assert settings_module.load_settings() == expected


def test_load_settings_returns_defaults_for_corrupt_json_without_overwriting(monkeypatch, tmp_path, caplog):
    path = _use_tmp_settings(monkeypatch, tmp_path)
    original = "{broken settings with secret user@example.test}"
    path.write_text(original, encoding="utf-8")

    result = settings_module.load_settings()

    assert result["theme"] == "light"
    assert result["remember_me"] is False
    assert result["last_username"] == ""
    assert result["auto_login"] is False
    assert result["sync"]["auto_sync_interval"] == 300
    assert result["sync"]["notification_refresh_interval"] == 300
    assert path.read_text(encoding="utf-8") == original
    assert str(path) not in " ".join(record.getMessage() for record in caplog.records)


def test_load_settings_returns_defaults_for_empty_file(monkeypatch, tmp_path):
    path = _use_tmp_settings(monkeypatch, tmp_path)
    path.write_text("", encoding="utf-8")

    result = settings_module.load_settings()

    assert result["theme"] == "light"
    assert "auto_sync_interval" in result["sync"]
    assert "notification_refresh_interval" in result["sync"]


def test_atomic_write_failure_preserves_existing_file_and_removes_temp(monkeypatch, tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"keep": true}', encoding="utf-8")

    def fail_replace(_source, _destination):
        raise OSError("replacement failed with secret path")

    monkeypatch.setattr(atomic_json.os, "replace", fail_replace)

    assert atomic_json.atomic_write_json(str(path), {"new": True}) is False
    assert path.read_text(encoding="utf-8") == '{"keep": true}'
    assert not list(tmp_path.glob("settings.json.tmp.*"))


def test_update_settings_preserves_unrelated_keys(monkeypatch, tmp_path):
    path = _use_tmp_settings(monkeypatch, tmp_path)
    path.write_text(
        json.dumps({"theme": "dark", "unrelated": {"keep": "yes"}}),
        encoding="utf-8",
    )

    assert settings_module.update_settings(
        lambda current: {**current, "theme": "light"}
    ) is True

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["theme"] == "light"
    assert saved["unrelated"] == {"keep": "yes"}
