from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from src.config import Brand
from src.graphics import GraphicsError, fit_text, render
from src.validator import errors, validate_image


def test_render_produces_instagram_ready_png(tmp_path: Path, brand: Brand) -> None:
    out = tmp_path / "image.png"
    meta = render(out, brand=brand, headline="The quilted puffer jacket", subline=brand.tagline)
    assert out.exists()
    assert (meta.width, meta.height) == (1080, 1350)
    assert meta.bytes < 8 * 1024 * 1024
    assert len(meta.sha256) == 64
    with Image.open(out) as image:
        assert image.format == "PNG"
        assert image.size == (1080, 1350)
    assert errors(validate_image(out, meta.sha256)) == []


def test_render_shrinks_long_headline(tmp_path: Path, brand: Brand) -> None:
    out = tmp_path / "image.png"
    meta = render(
        out,
        brand=brand,
        headline="Cold mornings in Dhaka need a layer that actually works",
        subline="Winter essentials, found for you.",
    )
    assert meta.width == 1080


def test_render_rejects_impossible_headline(tmp_path: Path, brand: Brand) -> None:
    words = " ".join(["unbreakable"] * 40)
    with pytest.raises(GraphicsError):
        render(tmp_path / "image.png", brand=brand, headline=words)


def test_fit_text_respects_bounds() -> None:
    from PIL import ImageDraw

    canvas = Image.new("RGB", (800, 600))
    draw = ImageDraw.Draw(canvas)
    fit = fit_text(draw, "A short headline", "bold", 700, 300, 3, 92, 54)
    assert 1 <= len(fit.lines) <= 3
    assert fit.size >= 54


def test_validate_image_detects_hash_mismatch(tmp_path: Path, brand: Brand) -> None:
    out = tmp_path / "image.png"
    render(out, brand=brand, headline="Winter layers", subline=brand.tagline)
    issues = validate_image(out, "0" * 64)
    assert "image_hash" in {issue.code for issue in issues}


def test_validate_image_missing_file(tmp_path: Path) -> None:
    issues = validate_image(tmp_path / "nope.png", "0" * 64)
    assert issues[0].code == "image_missing"
