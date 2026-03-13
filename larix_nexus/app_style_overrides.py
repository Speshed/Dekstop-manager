"""Per-app style overrides on top of shared style tokens.

Keep shared defaults in style_tokens.py and put only local exceptions here.
"""

from __future__ import annotations


def get_main_app_dark_color_overrides() -> dict[str, str]:
    """Main desktop app dark-theme color exceptions."""
    return {
        "#222222": "#FFFFFF",
    }


def get_pdf_compare_dark_color_overrides() -> dict[str, str]:
    """PDF Compare dark-theme color exceptions."""
    return {
        "#F0F0F0": "#1e1e1e",
        "#F9F9F9": "#1e1e1e",
        "#DCDCDC": "#606060",
        "#C0C0C0": "#404040",
        "#D0D0D0": "#4a4a4a",
        "#E0E0E0": "#2a2a2a",
        "#000000": "#FFFFFF",
        "#000": "#FFFFFF",
        "#0a0a0a": "#0a0a0a",
    }
