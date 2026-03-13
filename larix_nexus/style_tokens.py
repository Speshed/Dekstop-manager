"""Shared visual tokens for Larix UI styling.

This module keeps cross-app style constants in one place so multiple
applications can stay visually consistent while still allowing local overrides.
"""

from __future__ import annotations

from typing import Mapping


FONT_FAMILY = '"Segoe UI","Arial",sans-serif'
FONT_SIZE_PT = 10

ACCENT_PRIMARY = "#F7921E"
ACCENT_HOVER = "#FFE3C2"
ACCENT_PRESSED = "#FFC37A"
ACCENT_BORDER_HOVER = "#FFA74B"
ACCENT_BORDER_PRESSED = "#E07E12"

TEXT_PRIMARY_LIGHT = "#222222"
TEXT_PRIMARY_DARK = "#e0e0e0"

BUTTON_RADIUS_MD = 14
BUTTON_PADDING_Y = 6
BUTTON_PADDING_X = 12

CHIP_RADIUS = 16
CHIP_PADDING_Y = 8
CHIP_PADDING_X = 20

SURFACE_RADIUS_LG = 12
SURFACE_RADIUS_MD = 8


BASE_DARK_COLOR_REPLACEMENTS: dict[str, str] = {
    "#FFFFFF": "#121212",
    "#FFF": "#121212",
    "#F5F5F5": "#121212",
    "#FAFAFA": "#121212",
    "#F0F0F0": "#121212",
    "#EFEFEF": "#121212",
    "#EAEAEA": "#121212",
    "#E6E6E6": "#121212",
    "#EEEEEE": "#121212",
    "#F2F2F2": "#121212",
    "#DCDCDC": "#404040",
    "#C9C9C9": "#505050",
    "#222222": "#e0e0e0",
    "#222": "#e0e0e0",
    "#000000": "#e0e0e0",
    "#000": "#e0e0e0",
    "#333": "#d0d0d0",
    "#444": "#c0c0c0",
    "#555": "#b0b0b0",
    "#666": "#a0a0a0",
    "#777": "#909090",
    "#888": "#808080",
    "#999": "#707070",
    "#AAA": "#666666",
    "#B5B5B5": "#666666",
    "#9B9B9B": "#777777",
    "#FFE3C2": "#FFE3C2",
    "#FFC37A": "#FFC37A",
    "#FFE8D1": "#3a2b1a",
    "#FFF0DC": "#3f2f1f",
    "#FFF3E6": "#3e2d1c",
    "#FFD1A0": "#71451f",
    "#FFCA91": "#6a3f18",
    "#FFF9F0": "#30251c",
    "#FFF7EC": "#31241a",
    "#E8F0FE": "#2c3a4f",
    "#1A73E8": "#8ab4f8",
    "#010101": "#fefefe",
}


def build_dark_color_replacements(overrides: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return normalized dark-theme color map with optional overrides."""
    merged = dict(BASE_DARK_COLOR_REPLACEMENTS)
    if overrides:
        merged.update({k.upper(): v for k, v in overrides.items()})
    return merged


def apply_shared_qss_tokens(qss: str) -> str:
    """Apply shared style tokens to raw QSS text.

    This keeps cross-app typography, accent colors and common sizing aligned.
    """
    if not qss:
        return qss

    replacements = {
        '* { font-family: "Segoe UI","Arial",sans-serif; color: #222; font-size: 10pt; }': (
            f'* {{ font-family: {FONT_FAMILY}; color: {TEXT_PRIMARY_LIGHT}; font-size: {FONT_SIZE_PT}pt; }}'
        ),
        "background: #F7921E; border: 1px solid #F7921E;": (
            f"background: {ACCENT_PRIMARY}; border: 1px solid {ACCENT_PRIMARY};"
        ),
        "background: #FFE3C2; border-color: #FFA74B;": (
            f"background: {ACCENT_HOVER}; border-color: {ACCENT_BORDER_HOVER};"
        ),
        "background: #FFC37A; border-color: #E07E12;": (
            f"background: {ACCENT_PRESSED}; border-color: {ACCENT_BORDER_PRESSED};"
        ),
        "border-radius: 14px; padding: 6px 12px;": (
            f"border-radius: {BUTTON_RADIUS_MD}px; padding: {BUTTON_PADDING_Y}px {BUTTON_PADDING_X}px;"
        ),
        "border-radius: 12px;": f"border-radius: {SURFACE_RADIUS_LG}px;",
        "border-radius: 8px;": f"border-radius: {SURFACE_RADIUS_MD}px;",
        "padding: 8px 20px;": f"padding: {CHIP_PADDING_Y}px {CHIP_PADDING_X}px;",
        "border-top-left-radius: 16px;": f"border-top-left-radius: {CHIP_RADIUS}px;",
        "border-top-right-radius: 16px;": f"border-top-right-radius: {CHIP_RADIUS}px;",
        "border-bottom-right-radius: 16px;": f"border-bottom-right-radius: {CHIP_RADIUS}px;",
        "border-bottom-left-radius: 16px;": f"border-bottom-left-radius: {CHIP_RADIUS}px;",
    }

    out = qss
    for old, new in replacements.items():
        out = out.replace(old, new)
    return out
