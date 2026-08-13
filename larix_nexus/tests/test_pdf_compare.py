import ast
import os
import sys
from concurrent.futures import Future
import queue
import threading
import time
import importlib
from types import SimpleNamespace
from unittest.mock import Mock
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtWidgets import QApplication, QScrollArea, QMessageBox
from larix_nexus.utils import messagebox as messagebox_utils
from larix_nexus.utils.theme import enable_msgbox_autosize

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(1, str(Path(__file__).resolve().parents[1]))

from pdf.PDF_Compare import (
    ImageView,
    PDFCompareWindow,
    build_page_pair_plan,
    _diff_layer_offsets,
    colorize_diff_masks,
    normalize_diff_drag_delta,
)


def test_mapping_plan_fills_compatible_interval_without_rendering():
    plan = build_page_pair_plan(
        [(4, 5), (14, 15)], [(4, 5), (14, 15)], 20, 20, revision=3
    )
    assert plan.candidates == tuple((i, i + 1) for i in range(5, 14))
    assert plan.stop_reason == "complete"
    assert plan.mappings_revision == 3


def test_mapping_plan_stops_at_first_left_or_right_conflict():
    left = build_page_pair_plan(
        [(4, 5), (7, 8), (14, 15)], [(4, 5), (14, 15)], 20, 20
    )
    right = build_page_pair_plan(
        [(4, 5), (8, 7), (14, 15)], [(4, 5), (14, 15)], 20, 20
    )
    assert left.candidates == ((5, 6), (6, 7))
    assert left.stop_reason == "conflict"
    assert right.candidates == ((5, 6),)
    assert right.stop_reason == "conflict"


def test_mapping_plan_continues_only_explicitly_and_stops_at_short_document():
    plan = build_page_pair_plan(
        [(2, 3)], [(2, 3)], 6, 5, continue_from=True
    )
    assert plan.candidates == ((3, 4),)
    assert plan.stop_reason == "boundary"


def test_mapping_plan_rejects_incompatible_anchors_and_duplicate_restart():
    incompatible = build_page_pair_plan(
        [(2, 3), (8, 10)], [(2, 3), (8, 10)], 20, 20
    )
    duplicate = build_page_pair_plan(
        [(2, 3), (3, 4), (8, 9)], [(2, 3), (8, 9)], 20, 20
    )
    assert incompatible.stop_reason == "incompatible"
    assert duplicate.candidates == ()
    assert duplicate.stop_reason == "conflict"


def test_saved_mapping_refresh_builds_one_list_row_per_mapping():
    source = (Path(__file__).resolve().parents[1] / "pdf" / "PDF_Compare.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    open_mapping = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "open_mapping_window"
    )
    nested = {
        node.name: node
        for node in ast.walk(open_mapping)
        if isinstance(node, ast.FunctionDef)
        and node.name in {"refresh_saved", "_refresh_saved_rows", "_del_pair"}
    }

    refresh_source = ast.get_source_segment(source, nested["refresh_saved"])
    rows_source = ast.get_source_segment(source, nested["_refresh_saved_rows"])
    delete_source = ast.get_source_segment(source, nested["_del_pair"])

    assert "_refresh_saved_rows()" in refresh_source
    assert "for (p1, p2) in self.mappings" in rows_source
    assert "saved_list.addItem(it)" in rows_source
    assert "self._remove_mapping_pair(pair)" in delete_source
    assert 'QPushButton("⋯")' not in rows_source
    assert "actions_layout.setSpacing(4)" in rows_source
    assert 'QPushButton(t("pdf.mapping_continue_from"))' in rows_source
    assert "continue_from=True" in rows_source
    assert "btn_del.setFixedSize(28, 28)" in rows_source
    assert "row.setMinimumHeight(40)" in rows_source


@pytest.mark.parametrize(
    "stop_reason",
    ["boundary", "conflict", "complete", "empty", "incompatible"],
)
def test_mapping_preview_has_friendly_stop_reason_and_scrollable_pair_layout(stop_reason):
    source = (Path(__file__).resolve().parents[1] / "pdf" / "PDF_Compare.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    window_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "PDFCompareWindow")
    preview = [
        node for node in window_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "_show_mapping_plan_preview"
    ][-1]
    preview_source = ast.get_source_segment(source, preview)

    assert f'"{stop_reason}": t("pdf.mapping_stop_{stop_reason}_friendly")' in preview_source
    assert "QScrollArea()" in preview_source
    assert "ScrollBarAlwaysOff" in preview_source
    assert "ARROW_RIGHT_ICON_PATH" in preview_source
    assert "QComboBox()" in preview_source
    assert "edited_pairs" in preview_source
    assert "_validate_mapping_pair" in preview_source
    assert "INFORMATION_ICON_PATH" in preview_source
    assert 'QLabel("i")' not in preview_source
    assert "continue_from=True" not in preview_source
    assert "AddPagePairsCommand" in preview_source


def test_mapping_preview_buttons_share_neutral_theme_style():
    source = (Path(__file__).resolve().parents[1] / "pdf" / "PDF_Compare.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    window_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "PDFCompareWindow")
    preview = [
        node for node in window_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "_show_mapping_plan_preview"
    ][-1]
    preview_source = ast.get_source_segment(source, preview)

    assert 'create.setObjectName("mappingPreviewCreate")' in preview_source
    assert 'cancel.setObjectName("mappingPreviewButton")' in preview_source
    assert "background:rgba(247, 146, 30, 0.10)" in preview_source
    assert "background:rgba(247, 146, 30, 0.20)" in preview_source
    assert "border:1px solid #FFA74B" in preview_source
    assert "border:1px solid #E07E12" in preview_source
    assert "background:#F7921E" not in preview_source


def test_rotate_buttons_do_not_attach_icon_rasterizing_hover():
    source = (Path(__file__).resolve().parents[1] / "pdf" / "PDF_Compare.py").read_text(
        encoding="utf-8"
    )
    assert "_attach_dark_hover(self.btn_rot_l" not in source
    assert "_attach_dark_hover(self.btn_rot_r" not in source

    app = QApplication.instance() or QApplication([])
    button = QtWidgets.QPushButton()
    pixmap = QtGui.QPixmap(16, 16)
    pixmap.fill(QtGui.QColor("white"))
    button.setIcon(QtGui.QIcon(pixmap))
    button.setIconSize(QtCore.QSize(16, 16))
    before = button.icon().pixmap(16, 16).toImage()

    PDFCompareWindow._attach_dark_hover(SimpleNamespace(), button, None, 14)

    assert button.iconSize() == QtCore.QSize(16, 16)
    assert button.icon().pixmap(16, 16).toImage() == before
    button.close()
from larix_nexus.ui import widgets as ui_widgets

pdf_compare = importlib.import_module("pdf.PDF_Compare")
main_window_module = importlib.import_module("larix_nexus.ui.main_window")


class _Timer:
    def __init__(self):
        self.stop_calls = 0

    def stop(self):
        self.stop_calls += 1


def test_close_lifecycle_invalidates_render_and_shuts_down_pool_without_waiting():
    timers = [_Timer(), _Timer(), _Timer()]
    zoom_timer = _Timer()
    pool = Mock()
    window = SimpleNamespace(
        _closing=False,
        _render_seq=7,
        _ui_timer=timers[0],
        _diff_final_timer=timers[1],
        _hq_render_timer=timers[2],
        view=SimpleNamespace(_zoom_timer=zoom_timer),
        _pool=pool,
    )

    PDFCompareWindow._shutdown_background_tasks(window)

    assert window._closing is True
    assert window._render_seq == 8
    assert all(timer.stop_calls == 1 for timer in timers)
    assert zoom_timer.stop_calls == 1
    pool.shutdown.assert_called_once_with(wait=False, cancel_futures=True)


def test_stale_diff_callback_does_not_update_ui_or_release_current_render():
    view = Mock()
    window = SimpleNamespace(
        _closing=False,
        _render_seq=12,
        _ui_queue=queue.Queue(),
        _diff_busy=True,
        _diff_pending=None,
        mode="diff",
        view=view,
    )
    window._ui_queue.put(("diff_ready", 11, Mock(), 300, False))
    window._ui_queue.put(("diff_done", 11))

    PDFCompareWindow._process_ui_queue(window)

    view.setPixmap.assert_not_called()
    assert window._diff_busy is True


def test_background_task_is_not_submitted_after_close_started():
    pool = Mock()
    window = SimpleNamespace(_closing=True, _pool=pool)

    PDFCompareWindow._start_background_task(window, Mock())

    pool.submit.assert_not_called()


def test_pdf_compare_window_restores_toolbar_method_before_construction():
    app = QApplication.instance() or QApplication([])

    assert callable(getattr(PDFCompareWindow, "__dedented__apply_toolbar_icons", None))

    window = PDFCompareWindow()
    assert window is not None
    window.close()
    app.processEvents()


def test_open_two_pdf_paths_starts_deferred_precache_without_name_error(tmp_path):
    app = QApplication.instance() or QApplication([])
    paths = []
    for name in ("one.pdf", "two.pdf"):
        path = tmp_path / name
        document = pdf_compare.fitz.open()
        document.new_page()
        document.save(str(path))
        document.close()
        paths.append(path)

    window = PDFCompareWindow()
    window.open_pdf_path(1, str(paths[0]))
    window.open_pdf_path(2, str(paths[1]))

    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(150, loop.quit)
    loop.exec()

    assert window.pdf1 is not None
    assert window.pdf2 is not None
    window.close()
    window.pdf1.close()
    window.pdf2.close()
    app.processEvents()


def test_two_pdf_load_renders_thumbnails_for_both_columns(tmp_path):
    app = QApplication.instance() or QApplication([])
    paths = []
    for name, color in (("left.pdf", (0.86, 0.16, 0.16)), ("right.pdf", (0.16, 0.31, 0.86))):
        path = tmp_path / name
        document = pdf_compare.fitz.open()
        for page_number in range(2):
            page = document.new_page()
            page.insert_text((72, 100), f"{name} page {page_number + 1}", fontsize=24, color=color)
        document.save(str(path))
        document.close()
        paths.append(path)

    window = PDFCompareWindow()
    try:
        window.open_pdf_path(1, str(paths[0]))
        window.open_pdf_path(2, str(paths[1]))

        def rendered(label):
            pixmap = label.pixmap()
            if pixmap is None or pixmap.isNull():
                return False
            image = pixmap.toImage()
            # The placeholder is completely white; rendered pages contain text.
            for y in range(image.height()):
                for x in range(image.width()):
                    if image.pixelColor(x, y) != QtGui.QColor("#ffffff"):
                        return True
            return False

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            app.processEvents()
            if (
                len(window.thumbs1) == 2
                and len(window.thumbs2) == 2
                and all(rendered(label) for label in (*window.thumbs1, *window.thumbs2))
            ):
                break
            time.sleep(0.02)

        assert all(rendered(label) for label in (*window.thumbs1, *window.thumbs2))
    finally:
        window.close()
        for document in (getattr(window, "pdf1", None), getattr(window, "pdf2", None)):
            if document is not None:
                document.close()
        app.processEvents()


def test_thumbnail_workers_capture_page_index_for_both_pdf_sides():
    source = (Path(__file__).resolve().parents[1] / "pdf" / "PDF_Compare.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Lambda):
            continue
        for child in ast.walk(node.body):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) and child.func.attr == "_thumb_worker":
                calls.append({kw.arg for kw in child.keywords})

    assert any({"which", "page_index", "TW", "TH", "PAD_W", "PAD_H"}.issubset(call) for call in calls)
    assert len(calls) >= 2


def test_mapping_thumbnail_declares_render_side_and_passes_it_to_both_pdf_calls():
    source = (Path(__file__).resolve().parents[1] / "pdf" / "PDF_Compare.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    page_thumb = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "page_thumb")
    assert [arg.arg for arg in page_thumb.args.args][-1] == "side"
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "page_thumb"
    ]
    assert {kw.value.value for call in calls for kw in call.keywords if kw.arg == "side"} == {1, 2}


def test_navigation_pixmap_falls_back_to_visible_mirrored_arrow(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ui_widgets, "rsrc_path", lambda *_parts: "missing-navigation.png")

    normal = ui_widgets.navigation_pixmap(size=18, dark=False)
    mirrored = ui_widgets.navigation_pixmap(mirrored=True, size=18, dark=True)

    assert not normal.isNull()
    assert not mirrored.isNull()
    assert normal.size() == mirrored.size()


def test_saved_pair_hover_uses_theme_aware_text_and_restores_it_on_leave():
    source = (Path(__file__).resolve().parents[1] / "pdf" / "PDF_Compare.py").read_text(encoding="utf-8")

    assert 'hover_text = "#000" if self._is_light_theme() else "#fff"' in source
    assert 'lbl_l.setStyleSheet("color:#fff;")' in source
    assert 'lbl_r.setStyleSheet("color:#fff;")' in source


def test_main_window_keeps_pdf_compare_window_reference(monkeypatch):
    class _Signal:
        def connect(self, callback):
            self.callback = callback

    class _FakeWindow:
        def __init__(self):
            self.theme_switch = SimpleNamespace(toggledTheme=_Signal())
            self.cmb_mode = SimpleNamespace(findText=lambda _text: -1)
            self.destroyed = _Signal()
            self.visible = False

        def apply_theme_state(self, _is_dark, persist=False):
            assert persist is False

        def setWindowModality(self, _modality):
            pass

        def open_pdf_path(self, _which, _path):
            pass

        def _apply_toolbar_icons(self):
            pass

        def show(self):
            self.visible = True

        def isVisible(self):
            return self.visible

    monkeypatch.setattr(main_window_module, "PDFCompareWindow", _FakeWindow)
    window = SimpleNamespace(
        _current_theme=main_window_module.THEME_LIGHT,
        _pdf_compare_windows=[],
        _on_theme_toggled=Mock(),
    )

    main_window_module.MainWindow.open_pdf_compare_window(window)

    assert len(window._pdf_compare_windows) == 1
    assert window._pdf_compare_windows[0].visible is True


def test_main_startup_does_not_call_list_projects_synchronously():
    tree = ast.parse((Path(__file__).resolve().parents[2] / "main.py").read_text(encoding="utf-8"))

    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "list_projects"
    ]
    assert calls == []


def test_zoom_anchor_preserves_cursor_content_when_scrollbars_appear():
    app = QApplication.instance() or QApplication([])
    scroll = QScrollArea()
    view = ImageView()
    pixmap = QtGui.QPixmap(200, 200)
    pixmap.fill(QtCore.Qt.white)
    view.setPixmap(pixmap)
    view.resize(pixmap.size())
    scroll.setWidget(view)
    scroll.resize(220, 220)
    scroll.setAlignment(QtCore.Qt.AlignCenter)
    scroll.show()
    app.processEvents()

    viewport = scroll.viewport()
    cursor = QtCore.QPoint(viewport.width() // 2, viewport.height() // 2)
    old_origin = QtCore.QPoint(
        max(0, (viewport.width() - view.width()) // 2),
        max(0, (viewport.height() - view.height()) // 2),
    )
    old_content = (
        (cursor.x() - old_origin.x()) / view.width(),
        (cursor.y() - old_origin.y()) / view.height(),
    )

    window = SimpleNamespace(view=view, view_scroll=scroll)
    window._apply_zoom_anchor = lambda size: PDFCompareWindow._apply_zoom_anchor(window, size)
    PDFCompareWindow._apply_fast_zoom_preview(window, 2.0, 1.0, cursor)
    app.processEvents()
    app.processEvents()

    new_origin = QtCore.QPoint(
        -scroll.horizontalScrollBar().value()
        if scroll.horizontalScrollBar().maximum() > 0
        else max(0, (viewport.width() - view.width()) // 2),
        -scroll.verticalScrollBar().value()
        if scroll.verticalScrollBar().maximum() > 0
        else max(0, (viewport.height() - view.height()) // 2),
    )
    new_content = (
        (cursor.x() - new_origin.x()) / view.width(),
        (cursor.y() - new_origin.y()) / view.height(),
    )

    assert scroll.horizontalScrollBar().maximum() > 0
    assert scroll.verticalScrollBar().maximum() > 0
    assert new_content == pytest.approx(old_content, abs=0.01)
    scroll.close()


def test_fast_zoom_preview_does_not_start_heavy_render():
    app = QApplication.instance() or QApplication([])
    scroll = QScrollArea()
    view = ImageView()
    pixmap = QtGui.QPixmap(80, 80)
    pixmap.fill(QtCore.Qt.white)
    view.setPixmap(pixmap)
    view.resize(pixmap.size())
    scroll.setWidget(view)
    scroll.resize(180, 180)
    scroll.show()
    app.processEvents()

    window = SimpleNamespace(
        view=view,
        view_scroll=scroll,
        scale=1.0,
        _hq_render_timer=Mock(),
        _request_diff_render=Mock(),
    )
    window._apply_zoom_anchor = lambda size: PDFCompareWindow._apply_zoom_anchor(window, size)
    window._apply_fast_zoom_preview = lambda zoom, previous, pos: PDFCompareWindow._apply_fast_zoom_preview(
        window, zoom, previous, pos
    )
    PDFCompareWindow.on_zoom_changed(window, 1.2)

    window._request_diff_render.assert_not_called()
    scroll.close()


def test_diff_colors_and_drag_layer_direction_are_explicit():
    mask1 = np.array([[True, True, False, False]], dtype=bool)
    mask2 = np.array([[True, False, True, False]], dtype=bool)
    colors = colorize_diff_masks(mask1, mask2)

    assert tuple(colors[0, 0]) == (0, 0, 0)
    assert tuple(colors[0, 1]) == (255, 0, 0)
    assert tuple(colors[0, 2]) == (0, 0, 255)
    assert tuple(colors[0, 3]) == (255, 255, 255)
    assert _diff_layer_offsets(100, 20) == ((100, 20), (0, 0))
    assert _diff_layer_offsets(-100, -20) == ((-100, -20), (0, 0))
    assert _diff_layer_offsets(0, 0) == ((0, 0), (0, 0))

    view = ImageView()
    base = QtGui.QPixmap(16, 16)
    red = QtGui.QPixmap(16, 16)
    view.set_diff_preview_layers(base, red)
    view.set_diff_drag_delta(7, -3)
    assert view._diff_base_pixmap is base
    assert view._diff_red_pixmap is red
    assert view._diff_drag_delta == QtCore.QPoint(7, -3)


def test_image_view_has_one_active_paint_event_with_scale_logic():
    tree = ast.parse(Path("larix_nexus/pdf/PDF_Compare.py").read_text(encoding="utf-8"))
    image_view = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "ImageView")
    paint_events = [node for node in image_view.body if isinstance(node, ast.FunctionDef) and node.name == "paintEvent"]

    assert len(paint_events) == 1
    source = ast.get_source_segment(Path("larix_nexus/pdf/PDF_Compare.py").read_text(encoding="utf-8"), paint_events[0])
    assert "painter.scale(self._visual_scale, self._visual_scale)" in source
    assert "_diff_base_pixmap" in source
    assert "_diff_red_pixmap" in source
    assert "_diff_drag_delta" in source


def test_pdf_button_normal_styles_are_neutral():
    source = (Path(__file__).resolve().parents[1] / "pdf" / "PDF_Compare.py").read_text(encoding="utf-8")
    assert "QToolButton#btn_primary" in source
    assert "background: #F7921E" not in source
    assert "background: #FFFFFF" in source
    assert "border: 1px solid #dcdcdc" in source


def test_image_view_paints_scaled_pixmap_and_dragged_diff_layers():
    app = QApplication.instance() or QApplication([])

    view = ImageView()
    view.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
    base = QtGui.QPixmap(4, 4)
    base.fill(QtGui.QColor("blue"))
    red = QtGui.QPixmap(2, 2)
    red.fill(QtGui.QColor("red"))
    view.set_diff_preview_layers(base, red)
    view.set_visual_scale(2.0)
    view.set_diff_drag_delta(4, 0)
    view.resize(12, 8)

    image = QtGui.QImage(12, 8, QtGui.QImage.Format_ARGB32)
    image.fill(QtCore.Qt.transparent)
    view.render(image)

    assert image.pixelColor(1, 1).blue() > 200
    assert image.pixelColor(5, 1).red() > 200

    view.clear_diff_preview_layers()
    view.setPixmap(red)
    view.setAlignment(QtCore.Qt.AlignCenter)
    view.resize(8, 8)
    image.fill(QtCore.Qt.transparent)
    view.render(image)
    assert image.pixelColor(3, 3).red() > 200
    app.processEvents()


def test_high_priority_render_cancels_pending_low_priority_work():
    high_pool = Mock()
    low_pool = Mock()
    low_future = Mock()
    low_pool.submit.return_value = low_future
    window = SimpleNamespace(
        _closing=False,
        _diff_busy=False,
        _zoom_active=False,
        _high_pool=high_pool,
        _low_pool=low_pool,
        _pool=high_pool,
    _low_futures={low_future},
    )

    PDFCompareWindow._start_background_task(window, Mock(), kind="prefetch")
    PDFCompareWindow._start_background_task(window, Mock(), kind="high")

    low_future.cancel.assert_called_once_with()
    low_pool.submit.assert_called_once()
    high_pool.submit.assert_called_once()


def test_low_priority_work_is_not_submitted_during_zoom():
    low_pool = Mock()
    window = SimpleNamespace(
        _closing=False,
        _zoom_active=True,
        _diff_busy=False,
        _low_pool=low_pool,
        _pool=Mock(),
    )

    PDFCompareWindow._start_background_task(window, Mock(), kind="thumb")

    low_pool.submit.assert_called_once()


def test_shutdown_closes_high_and_low_priority_pools():
    high_pool = Mock()
    low_pool = Mock()
    window = SimpleNamespace(
        _closing=False,
        _render_seq=1,
        _high_pool=high_pool,
        _low_pool=low_pool,
        _pool=high_pool,
    )

    PDFCompareWindow._shutdown_background_tasks(window)

    high_pool.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
    low_pool.shutdown.assert_called_once_with(wait=False, cancel_futures=True)


def test_stale_low_priority_task_does_not_run_after_close():
    low_pool = Mock()
    submitted = Mock()
    low_pool.submit.return_value = submitted
    work = Mock()
    window = SimpleNamespace(
        _closing=False,
        _zoom_active=False,
        _diff_busy=False,
        _low_pool=low_pool,
        _pool=Mock(),
        _low_futures=set(),
    )

    PDFCompareWindow._start_background_task(window, work, kind="precache")
    wrapped = low_pool.submit.call_args.args[0]
    window._closing = True
    wrapped()

    work.assert_not_called()


def test_cancelled_precache_reports_exact_caching_completion_count():
    low_pool = Mock()
    high_pool = Mock()
    low_future = Future()
    low_pool.submit.return_value = low_future
    window = SimpleNamespace(
        _closing=False,
        _zoom_active=False,
        _diff_busy=False,
        _low_pool=low_pool,
        _high_pool=high_pool,
        _pool=high_pool,
        _low_futures=set(),
        _low_task_meta={},
        _ui_queue=queue.Queue(),
    )

    PDFCompareWindow._start_background_task(window, Mock(), kind="precache", caching=True, caching_count=2)
    PDFCompareWindow._start_background_task(window, Mock(), kind="high")
    window._end_caching = Mock()

    PDFCompareWindow._process_ui_queue(window)

    assert low_future.cancelled()
    window._end_caching.assert_called_once_with(2)


def test_running_low_task_is_not_compensated_when_cancel_returns_false():
    low_pool = Mock()
    high_pool = Mock()
    low_future = Mock()
    low_future.cancel.return_value = False
    low_pool.submit.return_value = low_future
    window = SimpleNamespace(
        _closing=False,
        _zoom_active=False,
        _diff_busy=False,
        _low_pool=low_pool,
        _high_pool=high_pool,
        _pool=high_pool,
        _low_futures=set(),
        _low_task_meta={},
        _ui_queue=queue.Queue(),
    )

    PDFCompareWindow._start_background_task(window, Mock(), kind="thumb", caching=True)
    PDFCompareWindow._start_background_task(window, Mock(), kind="high")
    window._end_caching = Mock()

    PDFCompareWindow._process_ui_queue(window)

    window._end_caching.assert_not_called()


def test_worker_thumbnail_completion_decrements_caching_once():
    window = SimpleNamespace(
        _closing=False,
        _ui_queue=queue.Queue(),
        _end_caching=Mock(),
    )
    window._ui_queue.put(("thumb_cancelled", 1, 0))

    PDFCompareWindow._process_ui_queue(window)

    window._end_caching.assert_called_once_with(1)


def test_completed_precache_is_not_compensated_by_cancellation_path():
    low_pool = Mock()
    completed = Future()
    completed.set_result(None)
    low_pool.submit.return_value = completed
    window = SimpleNamespace(
        _closing=False,
        _zoom_active=False,
        _diff_busy=False,
        _low_pool=low_pool,
        _pool=Mock(),
        _low_futures=set(),
        _low_task_meta={},
        _ui_queue=queue.Queue(),
    )

    PDFCompareWindow._start_background_task(
        window, Mock(), kind="precache", caching=True, caching_count=2
    )
    window._end_caching = Mock()
    PDFCompareWindow._process_ui_queue(window)

    window._end_caching.assert_not_called()


def test_same_page_key_is_rendered_once_and_then_served_from_cache(monkeypatch):
    class _Doc:
        page_count = 1

        def load_page(self, _index):
            return object()

    started = threading.Event()
    release = threading.Event()
    render_count = 0

    def render(_page, **_kwargs):
        nonlocal render_count
        render_count += 1
        started.set()
        release.wait(timeout=2)
        return Image.new("RGB", (2, 2))

    monkeypatch.setattr(pdf_compare, "fitz_page_to_pil", render)
    window = PDFCompareWindow.__new__(PDFCompareWindow)
    window._page_cache = {}
    window._binary_cache = {}
    window.pdf1 = _Doc()
    window.pdf2 = None
    window._closing = False
    results = []

    first = threading.Thread(target=lambda: results.append(
        PDFCompareWindow._get_page_image(window, 1, 0, 300, 0)))
    first.start()
    assert started.wait(timeout=2)
    second = threading.Thread(target=lambda: results.append(
        PDFCompareWindow._get_page_image(window, 1, 0, 300, 0)))
    second.start()
    release.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert render_count == 1
    assert len(results) == 2
    assert results[0] is results[1]
    assert PDFCompareWindow._get_page_image(window, 1, 0, 300, 0) is results[0]


def test_low_priority_prefetch_is_skipped_while_diff_is_active():
    pool = Mock()
    window = SimpleNamespace(_closing=False, _diff_busy=True, _pool=pool)

    PDFCompareWindow._start_background_task(window, lambda: None, kind="prefetch")
    PDFCompareWindow._start_background_task(window, lambda: None, kind="thumb")

    assert pool.submit.call_count == 1
    assert pool.submit.call_args_list[0].args


def test_zoom_changed_does_not_call_synchronous_update_view():
    timer = Mock()
    window = SimpleNamespace(
        scale=1.0,
        _closing=False,
        _hq_render_timer=timer,
        update_view=Mock(),
    )

    PDFCompareWindow.on_zoom_changed(window, 1.5)

    assert window.scale == 1.5
    window.update_view.assert_not_called()
    timer.start.assert_called_once_with(pdf_compare.ZOOM_RENDER_DEBOUNCE_MS)


def test_hq_zoom_debounce_dispatches_one_final_request():
    timer = Mock()
    window = SimpleNamespace(
        _closing=False,
        mode="pdf1",
        pdf1=object(),
        pdf2=None,
        scale=1.0,
        _hq_render_timer=timer,
        _request_single_render=Mock(),
    )

    # Wheel events only restart the timer; one timeout is the single HQ edge.
    PDFCompareWindow.on_zoom_changed(window, 1.1)
    PDFCompareWindow.on_zoom_changed(window, 1.2)
    PDFCompareWindow.on_zoom_changed(window, 1.3)
    PDFCompareWindow._on_hq_render_timeout(window)

    assert timer.start.call_count == 3
    assert window._request_single_render.call_count == 1


def test_stale_single_render_result_is_ignored():
    window = SimpleNamespace(
        _closing=False,
        _render_seq=4,
        _ui_queue=queue.Queue(),
        mode="pdf1",
        page1=0,
        page2=0,
        rotation=0,
        scale=1.0,
        view=Mock(),
        _fitted_once=True,
        _single_render_busy=True,
    )
    window._ui_queue.put((
        "single_ready", 3, ("pdf1", 1, 0, 0, 1.0), Image.new("RGB", (2, 2)), 300
    ))

    PDFCompareWindow._process_ui_queue(window)

    window.view.setPixmap.assert_not_called()


def test_drag_moves_visual_red_layer_without_rendering_full_diff(monkeypatch):
    scheduled = []
    monkeypatch.setattr(
        QtCore.QTimer,
        "singleShot",
        lambda interval, callback: scheduled.append((interval, callback)),
    )
    window = SimpleNamespace(
        mode="diff",
        pdf1=object(),
        pdf2=object(),
        scale=1.0,
        _last_render_dpi_used=300,
        _drag_accum=QtCore.QPoint(0, 0),
        _drag_visual_delta=QtCore.QPoint(0, 0),
        _drag_scheduled=False,
        view=Mock(),
        _diff_final_timer=Mock(),
        _request_diff_render=Mock(),
        _apply_drag_coalesced=Mock(),
    )

    PDFCompareWindow.on_drag(window, 12, -7, True)

    window._request_diff_render.assert_not_called()
    window._diff_final_timer.start.assert_not_called()
    window.view.set_diff_drag_delta.assert_called_once_with(12, -7)
    assert scheduled and scheduled[0][0] == pdf_compare.DIFF_DRAG_INTERVAL_MS


def test_normal_drag_uses_scrollbars_even_when_source_pixmap_is_smaller():
    app = QApplication.instance() or QApplication([])
    scroll = QScrollArea()
    view = ImageView()
    pixmap = QtGui.QPixmap(20, 20)
    pixmap.fill(QtCore.Qt.white)
    view.setPixmap(pixmap)
    view.resize(100, 100)
    scroll.setWidget(view)
    scroll.resize(60, 60)
    scroll.show()
    app.processEvents()

    event = QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseButtonPress,
        QtCore.QPointF(10, 10),
        QtCore.QPointF(view.mapToGlobal(QtCore.QPoint(10, 10))),
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    view.mousePressEvent(event)

    assert view._dragging is True
    view._dragging = False
    scroll.close()


def test_normal_drag_pans_scrollbars_without_changing_page_offsets():
    hbar = Mock()
    vbar = Mock()
    hbar.value.return_value = 100
    vbar.value.return_value = 50
    window = SimpleNamespace(
        mode="diff",
        pdf1=object(),
        pdf2=object(),
        page_offsets={},
        view_scroll=SimpleNamespace(horizontalScrollBar=lambda: hbar, verticalScrollBar=lambda: vbar),
        view=Mock(),
    )

    PDFCompareWindow.on_drag(window, 12, -7, False)

    hbar.setValue.assert_called_once_with(88)
    vbar.setValue.assert_called_once_with(57)
    assert window.page_offsets == {}
    window.view.set_diff_drag_delta.assert_not_called()


def test_offset_drag_does_not_pan_scrollbars_and_commits_red_layer_offset(monkeypatch):
    scheduled = []
    monkeypatch.setattr(QtCore.QTimer, "singleShot", lambda interval, callback: scheduled.append((interval, callback)))
    hbar = Mock()
    vbar = Mock()
    hbar.value.return_value = 100
    vbar.value.return_value = 50
    window = SimpleNamespace(
        mode="diff",
        pdf1=object(),
        pdf2=object(),
        page1=0,
        page2=1,
        scale=1.0,
        _last_render_dpi_used=300,
        _drag_accum=QtCore.QPoint(0, 0),
        _drag_visual_delta=QtCore.QPoint(0, 0),
        _drag_scheduled=False,
        page_offsets={},
        view=Mock(),
        view_scroll=SimpleNamespace(horizontalScrollBar=lambda: hbar, verticalScrollBar=lambda: vbar),
        _diff_final_timer=Mock(),
        _clamp_offset_for_pair=lambda _key, point: point,
        _request_diff_render=Mock(),
        _apply_drag_coalesced=Mock(),
    )

    PDFCompareWindow.on_drag(window, 12, -7, True)
    assert hbar.setValue.call_count == 0
    assert vbar.setValue.call_count == 0
    window.view.set_diff_drag_delta.assert_called_once_with(12, -7)
    window.view.set_drag_indicator.assert_called_once()
    assert "PDF 1" in window.view.set_drag_indicator.call_args.args[0]

    window._drag_scheduled = True
    PDFCompareWindow._apply_drag_coalesced(window)
    assert window.page_offsets[(0, 1)] == QtCore.QPoint(12, -7)


def test_offset_release_requests_final_render_with_same_direction():
    window = SimpleNamespace(
        mode="diff",
        pdf1=object(),
        pdf2=object(),
        page_offsets={(0, 1): QtCore.QPoint(12, 0)},
        page1=0,
        page2=1,
        view=SimpleNamespace(_drag_offset_mode=True, set_drag_indicator=Mock()),
        _drag_scheduled=False,
        _diff_final_timer=Mock(),
        _request_diff_render=Mock(),
    )

    pdf_compare._on_pan_end(window)

    window._request_diff_render.assert_called_once_with(low_quality=False)
    assert window.page_offsets[(0, 1)] == QtCore.QPoint(12, 0)


def test_offset_preview_survives_release_until_current_full_diff_ready():
    view = Mock()
    view._drag_offset_mode = True
    view._dragging = False
    window = SimpleNamespace(
        _closing=False,
        _render_seq=4,
        _ui_queue=queue.Queue(),
        mode="diff",
        pdf1=object(),
        pdf2=object(),
        view=view,
        view_scroll=Mock(),
        _drag_scheduled=False,
        _drag_visual_delta=QtCore.QPoint(12, 0),
        _diff_final_timer=Mock(),
        _request_diff_render=Mock(),
        _fitted_once=True,
        scale=1.0,
        _last_render_dpi_used=300,
        _apply_zoom_anchor=Mock(),
    )

    PDFCompareWindow._on_pan_end(window)

    window._request_diff_render.assert_called_once_with(low_quality=False)
    view.set_diff_drag_delta.assert_not_called()

    image = Image.new("RGB", (2, 2), "white")
    layer = Image.new("RGBA", (2, 2), (255, 0, 0, 255))
    window._ui_queue.put(("diff_ready", 4, image, 300, True, True, image, layer))
    PDFCompareWindow._process_ui_queue(window)
    view.set_diff_drag_delta.assert_not_called()

    window._ui_queue.put(("diff_ready", 4, image, 300, False, True, image, layer))
    PDFCompareWindow._process_ui_queue(window)
    view.set_diff_drag_delta.assert_called_once_with(0, 0)
    assert window._drag_visual_delta == QtCore.QPoint(0, 0)


def test_offset_drag_ignores_diff_ready_until_mouse_release():
    view = Mock()
    view._dragging = True
    view._drag_offset_mode = True
    window = SimpleNamespace(
        _closing=False,
        _render_seq=4,
        _ui_queue=queue.Queue(),
        _diff_busy=True,
        _diff_pending=None,
        mode="diff",
        view=view,
        _fitted_once=True,
        scale=1.0,
        _last_render_dpi_used=300,
        _drag_visual_delta=QtCore.QPoint(12, 0),
        _apply_zoom_anchor=Mock(),
    )
    image = Image.new("RGB", (2, 2), "white")
    layer = Image.new("RGBA", (2, 2), (255, 0, 0, 255))
    window._ui_queue.put(("diff_ready", 4, image, 300, False, True, image, layer))
    window._ui_queue.put(("diff_done", 4))

    PDFCompareWindow._process_ui_queue(window)

    view.setPixmap.assert_not_called()
    view.resize.assert_not_called()
    view.set_diff_preview_layers.assert_not_called()
    view.set_diff_drag_delta.assert_not_called()
    assert window._diff_busy is False


def test_offset_release_invalidates_busy_render_and_ignores_old_result():
    view = SimpleNamespace(
        _drag_offset_mode=True,
        _dragging=False,
        set_drag_indicator=Mock(),
    )
    window = SimpleNamespace(
        mode="diff",
        pdf1=object(),
        pdf2=object(),
        page1=0,
        page2=1,
        page_offsets={(0, 1): QtCore.QPoint(12, 0)},
        view=view,
        view_scroll=Mock(),
        _drag_scheduled=False,
        _diff_final_timer=Mock(),
        _diff_busy=True,
        _diff_pending="low",
        _render_seq=4,
        _request_diff_render=Mock(),
        _ui_queue=queue.Queue(),
    )

    PDFCompareWindow._on_pan_end(window)

    assert window._render_seq == 5
    assert window._diff_busy is False
    assert window._diff_pending is None
    window._request_diff_render.assert_called_once_with(low_quality=False)

    image = Image.new("RGB", (2, 2), "white")
    window._ui_queue.put(("diff_ready", 4, image, 300, False, True, image, image))
    window._fitted_once = True
    window.scale = 1.0
    window._last_render_dpi_used = 300
    window._apply_zoom_anchor = Mock()
    PDFCompareWindow._process_ui_queue(window)

    assert not hasattr(view, "setPixmap") or not view.setPixmap.called


def test_fast_zoom_uses_qt_painter_transform_instead_of_pixmap_scaled():
    old_pixmap = Mock()
    old_pixmap.isNull.return_value = False
    old_pixmap.size.return_value = QtCore.QSize(100, 80)
    view = SimpleNamespace(
        _visual_base_pixmap=old_pixmap,
        _visual_scale=1.0,
        set_visual_scale=Mock(),
        resize=Mock(),
    )
    window = SimpleNamespace(
        view=view,
        view_scroll=SimpleNamespace(setAlignment=Mock()),
        _apply_zoom_anchor=Mock(),
    )

    PDFCompareWindow._apply_fast_zoom_preview(window, 1.1, 1.0, QtCore.QPoint(5, 5))

    old_pixmap.scaled.assert_not_called()
    view.set_visual_scale.assert_called_once_with(1.1)


def test_drag_commit_updates_page_offsets_without_low_quality_diff():
    window = SimpleNamespace(
        mode="diff",
        pdf1=object(),
        pdf2=None,
        page1=0,
        page2=0,
        page_offsets={},
        _drag_accum=QtCore.QPoint(12, -7),
        _drag_scheduled=True,
        _request_diff_render=Mock(),
    )

    PDFCompareWindow._apply_drag_coalesced(window)

    assert window.page_offsets[(0, -1)].x() == 12
    assert window.page_offsets[(0, -1)].y() == -7
    window._request_diff_render.assert_not_called()


def test_unexpected_diff_setup_error_is_logged(monkeypatch):
    logged = Mock()
    monkeypatch.setattr(pdf_compare, "_pdf_log_exception", logged)
    submitted = []
    window = SimpleNamespace(
        _closing=False,
        mode="diff",
        pdf1=object(),
        pdf2=object(),
        _diff_busy=False,
        _diff_pending=None,
        page1=0,
        page2=1,
        scale=1.0,
        rotation=0,
        _render_seq=0,
        _ui_queue=queue.Queue(),
        _get_adaptive_max_dpi=lambda *_args: 300,
        _get_page_image=Mock(side_effect=ValueError("render failure")),
        _start_background_task=lambda fn: submitted.append(fn),
    )

    PDFCompareWindow._request_diff_render(window)
    submitted[0]()
    PDFCompareWindow._process_ui_queue(window)

    logged.assert_called_once()
    assert logged.call_args.args[0] == "diff_render"
    assert window._diff_busy is False


def test_diff_page_raster_is_deferred_until_worker_runs():
    submitted = []
    page_image = Mock(return_value=Image.new("RGB", (2, 2)))
    window = SimpleNamespace(
        _closing=False,
        mode="diff",
        pdf1=object(),
        pdf2=object(),
        _diff_busy=False,
        _diff_pending=None,
        page1=0,
        page2=1,
        page_offsets={},
        scale=1.0,
        rotation=0,
        _render_seq=0,
        _ui_queue=queue.Queue(),
        _get_adaptive_max_dpi=lambda *_args: 300,
        _get_page_image=page_image,
        _get_binary_mask=Mock(return_value=np.ones((2, 2), dtype=np.uint8)),
        _start_background_task=lambda fn: submitted.append(fn),
    )

    PDFCompareWindow._request_diff_render(window)

    page_image.assert_not_called()
    assert submitted
    submitted[0]()
    assert page_image.call_count == 2
    assert window._ui_queue.get_nowait()[0] == "diff_ready"


def test_unexpected_worker_error_is_logged(monkeypatch):
    logged = Mock()
    monkeypatch.setattr(pdf_compare, "_pdf_log_exception", logged)
    submitted = []
    window = SimpleNamespace(
        _closing=False,
        mode="diff",
        pdf1=object(),
        pdf2=object(),
        _diff_busy=False,
        _diff_pending=None,
        page1=0,
        page2=1,
        page_offsets={(0, 1): QtCore.QPoint(0, 0)},
        scale=1.0,
        rotation=0,
        _render_seq=0,
        _ui_queue=queue.Queue(),
        _get_adaptive_max_dpi=lambda *_args: 300,
        _get_page_image=lambda *_args, **_kwargs: Image.new("RGB", (2, 2)),
        _get_binary_mask=Mock(side_effect=ValueError("worker failure")),
        _start_background_task=lambda fn: submitted.append(fn),
    )

    PDFCompareWindow._request_diff_render(window)
    submitted[0]()

    assert any(call.args[0] == "diff_render" for call in logged.call_args_list)
    assert window._ui_queue.get_nowait()[0] == "diff_done"


def test_closing_diff_setup_error_is_not_logged(monkeypatch):
    logged = Mock()
    monkeypatch.setattr(pdf_compare, "_pdf_log_exception", logged)
    window = SimpleNamespace(_closing=True)

    PDFCompareWindow._request_diff_render(window)

    logged.assert_not_called()


def test_stale_diff_result_is_not_logged_as_error(monkeypatch):
    logged = Mock()
    monkeypatch.setattr(pdf_compare, "_pdf_log_exception", logged)
    view = Mock()
    window = SimpleNamespace(
        _closing=False,
        _render_seq=12,
        _ui_queue=queue.Queue(),
        _diff_busy=True,
        _diff_pending=None,
        mode="diff",
        view=view,
    )
    window._ui_queue.put(("diff_ready", 11, Mock(), 300, False))
    window._ui_queue.put(("diff_done", 11))

    PDFCompareWindow._process_ui_queue(window)

    logged.assert_not_called()
    view.setPixmap.assert_not_called()


def test_ui_queue_error_is_logged_and_next_tick_can_run(monkeypatch):
    logged = Mock()

    class QueueWithTransientError:
        def __init__(self):
            self.calls = 0

        def get_nowait(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("queue failure")
            raise queue.Empty

    monkeypatch.setattr(pdf_compare, "_pdf_log_exception", logged)
    window = SimpleNamespace(
        _closing=False,
        _ui_queue=QueueWithTransientError(),
    )

    PDFCompareWindow._process_ui_queue(window)
    PDFCompareWindow._process_ui_queue(window)

    logged.assert_called_once()
    assert logged.call_args.args[0] == "ui_queue"


def test_drag_delta_is_normalized_by_zoom_and_actual_dpi():
    assert normalize_diff_drag_delta(20, -10, 2.0, 300, 150) == (20.0, -10.0)


def test_offset_drag_uses_pdf1_canonical_offset_vector():
    assert normalize_diff_drag_delta(12, -7, 1.0) == (12.0, -7.0)


def test_offset_drag_is_not_limited_by_canvas_bounds():
    window = SimpleNamespace(
        mode="diff",
        pdf1=object(),
        pdf2=object(),
        page1=0,
        page2=1,
        scale=1.0,
        rotation=0,
        page_offsets={},
        _drag_accum=QtCore.QPoint(0, 0),
    )

    for delta, expected in (
        ((-100000, 0), QtCore.QPoint(-100000, 0)),
        ((200000, 0), QtCore.QPoint(100000, 0)),
        ((0, -100000), QtCore.QPoint(100000, -100000)),
        ((0, 200000), QtCore.QPoint(100000, 100000)),
    ):
        window._drag_accum = QtCore.QPoint(*delta)
        PDFCompareWindow._apply_drag_coalesced(window)
        assert window.page_offsets[(0, 1)] == expected


@pytest.mark.parametrize("offset", [(0, 0), (3, -7), (1000, 1000), (-1000, -1000)])
def test_final_diff_renderer_keeps_fixed_canvas_when_pdf1_moves(offset):
    images = {1: Image.new("RGB", (8, 5), "black"), 2: Image.new("RGB", (4, 9), "black")}
    window = SimpleNamespace(
        pdf1=object(),
        pdf2=object(),
        rotation=0,
        page_offsets={(0, 1): QtCore.QPoint(*offset)},
        _get_page_image=lambda which, *_args, **_kwargs: images[which],
    )

    result = PDFCompareWindow._render_diff_pair_to_image(window, 0, 1, 150)

    assert result is not None
    assert result.size == (8, 9)
    if offset == (1000, 1000):
        # PDF 1 is completely outside the fixed canvas; it must not create
        # a red region or enlarge the returned image.
        assert not np.any(np.all(np.asarray(result) == (255, 0, 0), axis=2))


@pytest.mark.parametrize("offset", [(0, 0), (1000, 1000), (-1000, -1000)])
def test_preview_diff_renderer_keeps_fixed_canvas_when_pdf1_moves(offset):
    images = {1: Image.new("RGB", (8, 5), "black"), 2: Image.new("RGB", (4, 9), "black")}
    masks = {1: np.ones((5, 8), dtype=np.uint8), 2: np.ones((9, 4), dtype=np.uint8)}
    submitted = []
    window = SimpleNamespace(
        _closing=False,
        mode="diff",
        pdf1=object(),
        pdf2=object(),
        _diff_busy=False,
        _diff_pending=None,
        page1=0,
        page2=1,
        page_offsets={(0, 1): QtCore.QPoint(*offset)},
        scale=1.0,
        rotation=0,
        _render_seq=0,
        _ui_queue=queue.Queue(),
        _get_adaptive_max_dpi=lambda *_args: 300,
        _get_page_image=lambda which, *_args, **_kwargs: images[which],
        _get_binary_mask=lambda which, *_args, **_kwargs: masks[which],
        _start_background_task=lambda fn, **_kwargs: submitted.append(fn),
    )

    PDFCompareWindow._request_diff_render(window)
    submitted[0]()
    ready = window._ui_queue.get_nowait()

    assert ready[0] == "diff_ready"
    assert ready[2].size == (8, 9)
    assert ready[6].size == (8, 9)
    assert ready[7].size == (8, 9)


def test_image_view_preview_keeps_fixed_pixmap_and_widget_bounds_during_drag():
    app = QApplication.instance() or QApplication([])
    view = ImageView()
    canvas_size = QtCore.QSize(80, 60)
    base = QtGui.QPixmap(canvas_size)
    red = QtGui.QPixmap(canvas_size)
    base.fill(QtGui.QColor("white"))
    red.fill(QtGui.QColor("red"))
    view.set_diff_preview_layers(base, red)
    view.setPixmap(base)
    view.resize(canvas_size)

    for delta in ((-200, 0), (200, 0), (0, -200), (0, 200)):
        view.set_diff_drag_delta(*delta)
        app.processEvents()
        assert view.size() == canvas_size
        assert view.pixmap().size() == canvas_size

    view.close()


def test_final_rerender_queue_keeps_real_view_bounds_after_far_left_drag():
    app = QApplication.instance() or QApplication([])
    view = ImageView()
    scroll = QScrollArea()
    scroll.setWidget(view)
    scroll.resize(200, 200)
    scroll.show()
    app.processEvents()
    submitted = []
    images = {1: Image.new("RGB", (80, 50), "black"), 2: Image.new("RGB", (40, 90), "black")}
    masks = {1: np.ones((50, 80), dtype=np.uint8), 2: np.ones((90, 40), dtype=np.uint8)}
    window = SimpleNamespace(
        _closing=False,
        mode="diff",
        pdf1=object(),
        pdf2=object(),
        _diff_busy=False,
        _diff_pending=None,
        page1=0,
        page2=1,
        page_offsets={(0, 1): QtCore.QPoint(0, 0)},
        scale=1.0,
        rotation=0,
        _render_seq=0,
        _ui_queue=queue.Queue(),
        _get_adaptive_max_dpi=lambda *_args: 300,
        _get_page_image=lambda which, *_args, **kwargs: (
            Image.new("RGB", (images[which].width // 2, images[which].height // 2), "black")
            if kwargs.get("low_quality")
            else images[which]
        ),
        _get_binary_mask=lambda which, *_args, **_kwargs: masks[which],
        _start_background_task=lambda fn, **_kwargs: submitted.append(fn),
        view=view,
        _fitted_once=True,
        _drag_visual_delta=QtCore.QPoint(0, 0),
        _drag_scheduled=False,
        _diff_final_timer=Mock(),
        _apply_zoom_anchor=Mock(),
        view_scroll=scroll,
    )
    window._request_diff_render = lambda low_quality=False: PDFCompareWindow._request_diff_render(
        window, low_quality=low_quality
    )

    fixed_size = QtCore.QSize(80, 90)
    initial_pixmap = QtGui.QPixmap(fixed_size)
    initial_pixmap.fill(QtGui.QColor("white"))
    view.setPixmap(initial_pixmap)
    view.resize(fixed_size)
    app.processEvents()
    view._drag_offset_mode = True
    PDFCompareWindow._on_pan_start(window)
    initial_view_size = view.size()
    initial_scroll_range = (
        scroll.horizontalScrollBar().maximum(),
        scroll.verticalScrollBar().maximum(),
    )
    initial_minimum = view.minimumSize()
    initial_maximum = view.maximumSize()

    for offset in (-1, -1000, -100000, 100000, 0):
        window.page_offsets[(0, 1)] = QtCore.QPoint(offset, 0)
        for low_quality in (True, False):
            PDFCompareWindow._request_diff_render(window, low_quality=low_quality)
            submitted.pop(0)()
            PDFCompareWindow._process_ui_queue(window)
            assert view.pixmap().size() == fixed_size
            assert view.size() == fixed_size
            assert view.minimumSize() == initial_minimum
            assert view.maximumSize() == initial_maximum
            assert (
                scroll.horizontalScrollBar().maximum(),
                scroll.verticalScrollBar().maximum(),
            ) == initial_scroll_range

    PDFCompareWindow._on_pan_end(window)
    submitted.pop(0)()
    PDFCompareWindow._process_ui_queue(window)
    assert view.size() == initial_view_size
    assert view.minimumSize() == QtCore.QSize(0, 0)
    assert view.maximumSize() == QtCore.QSize(16777215, 16777215)
    assert window._drag_diff_canvas_size is None

    scroll.close()
    view.close()


def test_identical_content_is_black_on_white_background():
    mask = np.array([[False, True], [False, False]])

    result = colorize_diff_masks(mask, mask)

    assert tuple(result[0, 0]) == (255, 255, 255)
    assert tuple(result[0, 1]) == (0, 0, 0)


def test_content_only_in_first_pdf_is_red():
    first = np.array([[True, False]])
    second = np.array([[False, False]])

    result = colorize_diff_masks(first, second)

    assert tuple(result[0, 0]) == (255, 0, 0)
    assert tuple(result[0, 1]) == (255, 255, 255)


def test_content_only_in_second_pdf_is_blue():
    first = np.array([[False, False]])
    second = np.array([[False, True]])

    result = colorize_diff_masks(first, second)

    assert tuple(result[0, 1]) == (0, 0, 255)


def test_source_colors_do_not_affect_same_geometry():
    first = np.array([[True, False], [False, True]])
    second = np.array([[True, False], [False, True]])

    result = colorize_diff_masks(first, second)

    assert np.array_equal(
        result,
        np.array(
            [
                [[0, 0, 0], [255, 255, 255]],
                [[255, 255, 255], [0, 0, 0]],
            ],
            dtype=np.uint8,
        ),
    )


def test_messagebox_standard_types_get_shared_brand_pixmaps():
    app = QApplication.instance() or QApplication([])
    enable_msgbox_autosize(app)
    cases = ((QMessageBox.Information, "alert"), (QMessageBox.Warning, "warning"), (QMessageBox.Critical, "warning"))
    for icon, kind in cases:
        box = QMessageBox()
        box.setIcon(icon)
        assert messagebox_utils.set_message_dialog_pixmap(box, kind)
        assert not box.iconPixmap().isNull()
        assert box.iconPixmap().toImage() == messagebox_utils.message_dialog_pixmap(kind).toImage()


def test_pdf_pair_saved_notification_uses_information_common_path():
    source = (Path(__file__).resolve().parents[1] / "pdf" / "PDF_Compare.py").read_text(encoding="utf-8")
    assert 'QMessageBox.information(dlg, t("pdf.success")' in source


def test_messagebox_pixmap_missing_asset_keeps_qt_fallback(monkeypatch):
    box = QMessageBox()
    box.setIcon(QMessageBox.Information)
    monkeypatch.setattr(messagebox_utils, "message_dialog_pixmap", lambda *args, **kwargs: QtGui.QPixmap())

    assert messagebox_utils.set_message_dialog_pixmap(box, "alert") is False
    assert box.icon() == QMessageBox.Information
