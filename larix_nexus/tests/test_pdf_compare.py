import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdf.PDF_Compare import colorize_diff_masks, normalize_diff_drag_delta


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
