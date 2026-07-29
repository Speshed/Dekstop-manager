import sys
from concurrent.futures import Future
import queue
import threading
import importlib
from types import SimpleNamespace
from unittest.mock import Mock
from pathlib import Path

import numpy as np
from PIL import Image
from PySide6 import QtCore

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdf.PDF_Compare import PDFCompareWindow, colorize_diff_masks, normalize_diff_drag_delta

pdf_compare = importlib.import_module("pdf.PDF_Compare")


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

    low_pool.submit.assert_not_called()


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

    pool.submit.assert_not_called()


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
        _request_diff_render=Mock(),
        _apply_drag_coalesced=Mock(),
    )

    PDFCompareWindow.on_drag(window, 12, -7, True)

    window._request_diff_render.assert_not_called()
    window.view.set_diff_drag_delta.assert_called_once_with(12, -7)
    assert scheduled and scheduled[0][0] == pdf_compare.DIFF_DRAG_INTERVAL_MS


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
