from types import SimpleNamespace
from unittest.mock import Mock

from larix_nexus.ui.theme_operations import _on_theme_toggled


def test_theme_toggle_restores_tree_arrow_from_tree_visibility(monkeypatch):
    window = SimpleNamespace(
        _current_theme="light", tree=SimpleNamespace(isVisible=lambda: False),
        tree_panel=SimpleNamespace(isVisible=lambda: True),
        _set_tree_panel_arrow=Mock(), _apply_icon_theme=Mock(),
        _update_notify_icon=Mock(),
    )
    monkeypatch.setattr("larix_nexus.ui.theme_operations.QApplication.instance", lambda: None)
    _on_theme_toggled(window, False)
    assert window._set_tree_panel_arrow.call_args.kwargs == {"collapsed": True}
    assert window._update_notify_icon.called

    window.tree.isVisible = lambda: True
    _on_theme_toggled(window, False)
    assert window._set_tree_panel_arrow.call_args.kwargs == {"collapsed": False}
