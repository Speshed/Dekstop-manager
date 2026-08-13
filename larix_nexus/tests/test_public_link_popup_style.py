import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QFrame

from larix_nexus.utils.ui_patches import patch_combobox_popup_border


def test_combo_popup_styles_root_and_view_are_separate():
    app = QApplication.instance() or QApplication([])
    patch_combobox_popup_border()

    combo = QComboBox()
    combo.setObjectName("publicLinkValidityCombo")
    combo.addItems(["placeholder", "one", "two", "three", "four"])
    combo.show()
    combo.showPopup()
    app.processEvents()

    view = combo.view()
    assert view.isVisible()
    root = view.window()
    assert isinstance(root, QFrame)
    assert root.objectName() == "_larix_combo_popup"
    assert root.windowFlags() & Qt.Popup
    assert "QFrame#_larix_combo_popup" in root.styleSheet()
    assert "QWidget { background: #FFFFFF; border: none; }" in root.styleSheet()
    assert "QFrame#qt_combobox_popup { background: #FFFFFF; border: none; }" in root.styleSheet()
    assert root.testAttribute(Qt.WA_TranslucentBackground) is False
    assert type(view.itemDelegate()).__name__ == "_PublicLinkComboPopupDelegate"
    assert "QWidget {" not in view.styleSheet()
    assert "QAbstractItemView::item:selected" in view.styleSheet()
    assert view.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert combo.maxVisibleItems() == combo.count() == 5
    last_rect = view.visualRect(view.model().index(4, 0))
    assert last_rect.isValid()
    assert last_rect.bottom() <= view.viewport().rect().bottom()
    assert not view.verticalScrollBar().isVisible()

    combo.hidePopup()
    combo.deleteLater()
    app.processEvents()
