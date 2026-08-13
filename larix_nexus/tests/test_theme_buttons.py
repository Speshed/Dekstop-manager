from pathlib import Path


def test_light_button_base_is_neutral():
    source = Path(__file__).parents[1].joinpath("utils", "theme.py").read_text(encoding="utf-8")
    start = source.index("/* КНОПКИ - общие стили */")
    block = source[start:source.index("/* Белые кнопки", start)]
    assert "background: #F7921E" not in block
    assert "background: #FFFFFF" in block
    assert "color: #222222" in block
    assert "border: 1px solid #dcdcdc" in block
