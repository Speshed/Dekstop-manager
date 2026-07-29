from unittest.mock import Mock, call
from types import SimpleNamespace

import larix_nexus.api.client as client_module
import larix_nexus.utils.keyring as keyring_module
from larix_nexus.ui.main_window import MainWindow


def _client(monkeypatch):
    monkeypatch.setattr(client_module.APIClient, "_load_auth", lambda self: False)
    api = client_module.APIClient("https://example.test")
    api.current_username = "user@example.test"
    api.token = "access-secret"
    api.refresh_token = "refresh-secret"
    api.cache["projects"] = ["cached"]
    return api


def test_logout_removes_all_credentials_and_clears_session(monkeypatch):
    api = _client(monkeypatch)
    delete_credential = Mock(return_value=True)
    settings = {
        "last_username": "user@example.test",
        "remember_me": True,
        "auto_login": True,
        "theme": "dark",
    }
    monkeypatch.setattr(keyring_module, "delete_credential", delete_credential)
    monkeypatch.setattr(client_module, "load_settings", lambda: settings)
    save_settings = Mock(return_value=True)
    monkeypatch.setattr(client_module, "save_settings", save_settings)

    api.logout()

    assert delete_credential.call_args_list == [
        call("user@example.test", "password"),
        call("user@example.test", "refresh_token"),
        call("user@example.test", "access_token"),
    ]
    assert api.token is None
    assert api.refresh_token is None
    assert api.current_username is None
    assert api.cache == {}
    assert settings["last_username"] == ""
    assert settings["remember_me"] is False
    assert settings["auto_login"] is False
    assert settings["theme"] == "dark"
    save_settings.assert_called_once_with(settings)


def test_logout_clears_session_and_settings_when_keyring_fails(monkeypatch, caplog):
    api = _client(monkeypatch)
    settings = {
        "last_username": "user@example.test",
        "remember_me": True,
        "auto_login": True,
    }
    secret_error = RuntimeError("credential secret and user@example.test")
    monkeypatch.setattr(client_module, "clear_all_credentials", Mock(side_effect=secret_error))
    monkeypatch.setattr(client_module, "load_settings", lambda: settings)
    monkeypatch.setattr(client_module, "save_settings", Mock(return_value=True))

    api.logout()

    assert api.token is None
    assert api.refresh_token is None
    assert api.current_username is None
    assert api.cache == {}
    assert settings["last_username"] == ""
    assert settings["remember_me"] is False
    assert settings["auto_login"] is False
    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "credential cleanup failed" in messages
    assert "RuntimeError" in messages
    assert "credential secret" not in messages
    assert "user@example.test" not in messages


def test_logout_and_relogin_resets_user_controls_without_real_qt_window():
    owner = SimpleNamespace(
        api=SimpleNamespace(logout=Mock()),
        cb_projects=SimpleNamespace(clear=Mock()),
        btn_user=SimpleNamespace(setVisible=Mock()),
        btn_login=SimpleNamespace(setVisible=Mock()),
        status=SimpleNamespace(showMessage=Mock()),
        set_initial_view=Mock(),
        _ensure_default_column_visibility=Mock(),
        do_login=Mock(),
    )

    MainWindow.logout_and_relogin(owner)

    owner.api.logout.assert_called_once_with()
    owner.cb_projects.clear.assert_called_once_with()
    owner.btn_user.setVisible.assert_called_once_with(False)
    owner.btn_login.setVisible.assert_called_once_with(True)
