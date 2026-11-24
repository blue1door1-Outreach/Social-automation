"""Branded 1080x1350 graphic with Pillow.

The design is deliberately plain: gradient background, one light card, a short
headline, a subline, a footer. Text is measured and shrunk to fit; if it cannot
fit within the limits, rendering fails rather than cropping.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import Brand

CANVAS = (1080, 1350)
CARD = (70, 236, 1010, 1116)  # left, top, right, bottom
PADDING = 64
MAX_BYTES = 8 * 1024 * 1024


class GraphicsError(RuntimeError):
    pass


@dataclass(frozen=True)
class ImageMeta:
    path: Path
    width: int
    height: int
    bytes: int
    sha256: str


@dataclass(frozen=True)
class Fit:
    lines: tuple[str, ...]
    font: ImageFont.FreeTypeFont
    size: int
    line_height: int


@lru_cache(maxsize=4)
def font_path(weight: str) -> Path:
    root = Path(__file__).resolve().parent.parent
    names = {
        "bold": (
            "Inter-Bold.ttf",
            "DejaVuSans-Bold.ttf",
            "arialbd.ttf",
            "Arial Bold.ttf",
            "LiberationSans-Bold.ttf",
            "segoeuib.ttf",
        ),
        "regular": (
            "Inter-Regular.ttf",
            "DejaVuSans.ttf",
            "arial.ttf",
            "Arial.ttf",
            "LiberationSans-Regular.ttf",
            "segoeui.ttf",
        ),
    }[weight]
    directories = [
        root / "assets" / "fonts",
        Path("C:/Windows/Fonts"),
        Path("/usr/share/fonts/truetype/dejavu"),
        Path("/usr/share/fonts/truetype/liberation"),
        Path("/usr/share/fonts/truetype/noto"),
        Path("/System/Library/Fonts/Supplemental"),
        Path("/Library/Fonts"),
    ]
    for directory in directories:
        for name in names:
            candidate = directory / name
            if candidate.exists():
                return candidate
    raise GraphicsError(
        "no usable font found. Add assets/fonts/Inter-Bold.ttf and Inter-Regular.ttf "
        "or install DejaVu fonts."
    )


def _rgb(value: str) -> tuple[int, int, int]:
    text = value.lstrip("#")
    return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def _background(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    width, height = size
    strip = Image.new("RGB", (1, height))
    pixels = strip.load()
    for y in range(height):
        pixels[0, y] = _mix(top, bottom, y / max(height - 1, 1))
    return strip.resize((width, height), Image.BILINEAR)


def _glow(size: tuple[int, int], center: tuple[int, int], radius: int, color: tuple[int, int, int], alpha: int) -> Image.Image:
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    x, y = center
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(*color, alpha))
    return layer.filter(ImageFilter.GaussianBlur(radius // 2))


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    weight: str,
    max_width: int,
    max_height: int,
    max_lines: int,
    max_size: int,
    min_size: int,
) -> Fit:
    if not text.strip():
        raise GraphicsError("empty text block")
    path = font_path(weight)
    for size in range(max_size, min_size - 1, -3):
        font = ImageFont.truetype(str(path), size)
        lines = _wrap(draw, text, font, max_width)
        if not lines or len(lines) > max_lines:
            continue
        line_height = int(size * 1.16)
        if sum(draw.textlength(line, font=font) > max_width + 1 for line in lines):
            continue
        if len(lines) * line_height > max_height:
            continue

        # Avoid an orphan word when a two-line wrap is badly unbalanced
        # ("The quilted puffer" / "jacket"). Re-wrap narrower and keep it if
        # both lines still fit.
        if len(lines) == 2:
            first_width = draw.textlength(lines[0], font=font)
            second_width = draw.textlength(lines[1], font=font)
            if second_width < first_width * 0.6:
                balanced = _wrap(draw, text, font, int(first_width * 0.82))
                if len(balanced) == 2 and all(
                    draw.textlength(line, font=font) <= max_width for line in balanced
                ):
                    lines = balanced

        return Fit(tuple(lines), font, size, line_height)
    raise GraphicsError(
        f"text does not fit ({text!r}: max {max_lines} lines, {max_width}px, {min_size}-{max_size}px)"
    )


def _draw_lines(
    draw: ImageDraw.ImageDraw,
    lines: tuple[str, ...],
    font: ImageFont.FreeTypeFont,
    center_x: int,
    top: int,
    line_height: int,
    fill: tuple[int, int, int],
) -> int:
    y = top
    for line in lines:
        draw.text((center_x, y), line, font=font, fill=fill, anchor="ma")
        y += line_height
    return y


def _draw_tracked(
    draw: ImageDraw.ImageDraw,
    center_x: int,
    top: int,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    tracking: int,
) -> None:
    widths = [draw.textlength(char, font=font) for char in text]
    total = sum(widths) + tracking * max(len(text) - 1, 0)
    x = center_x - total / 2
    for char, width in zip(text, widths):
        draw.text((x, top), char, font=font, fill=fill, anchor="la")
        x += width + tracking


def render(
    out_path: Path,
    *,
    brand: Brand,
    headline: str,
    subline: str = "",
    kicker: str = "WINTER EDIT",
) -> ImageMeta:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    primary = _rgb(brand.color("primary", "#0B2239"))
    secondary = _rgb(brand.color("secondary", "#1F4E6B"))
    accent = _rgb(brand.color("accent", "#CFE6F2"))
    surface = _rgb(brand.color("surface", "#F8FBFD"))
    ink = _rgb(brand.color("ink", "#0B2239"))
    muted = _rgb(brand.color("muted", "#5A7382"))

    width, height = CANVAS
    image = _background((width, height), primary, secondary).convert("RGBA")
    image = Image.alpha_composite(image, _glow((width, height), (930, 160), 430, accent, 34))
    image = Image.alpha_composite(image, _glow((width, height), (120, 1240), 360, secondary, 40))
    draw = ImageDraw.Draw(image)

    bold = font_path("bold")
    regular = font_path("regular")

    # Wordmark, outside the card.
    wordmark_font = ImageFont.truetype(str(bold), 26)
    _draw_tracked(draw, width // 2, 84, brand.name.upper(), wordmark_font, accent, 6)

    left, top, right, bottom = CARD
    card_w, card_h = right - left, bottom - top

    shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        (left, top + 26, right, bottom + 26), radius=40, fill=(0, 0, 0, 96)
    )
    image = Image.alpha_composite(image, shadow.filter(ImageFilter.GaussianBlur(38)))
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle((left, top, right, bottom), radius=40, fill=surface)
    center_x = left + card_w // 2
    inner_w = card_w - PADDING * 2

    kicker_font = ImageFont.truetype(str(bold), 24)
    _draw_tracked(draw, center_x, top + 74, kicker.upper(), kicker_font, secondary, 7)

    divider_color = _mix(surface, secondary, 0.35)
    draw.line((center_x - 46, top + 126, center_x + 46, top + 126), fill=divider_color, width=3)

    head_fit = fit_text(
        draw, headline, "bold", inner_w, 372, 3, max_size=92, min_size=54
    )
    sub_fit = (
        fit_text(draw, subline, "regular", inner_w, 150, 2, max_size=42, min_size=30)
        if subline.strip()
        else None
    )

    block_height = len(head_fit.lines) * head_fit.line_height
    gap = 46 if sub_fit else 0
    if sub_fit:
        block_height += gap + len(sub_fit.lines) * sub_fit.line_height

    region_top, region_bottom = top + 190, bottom - 190
    cursor = region_top + max(0, (region_bottom - region_top - block_height) // 2)
    cursor = _draw_lines(draw, head_fit.lines, head_fit.font, center_x, cursor, head_fit.line_height, ink)
    if sub_fit:
        cursor += gap
        _draw_lines(draw, sub_fit.lines, sub_fit.font, center_x, cursor, sub_fit.line_height, muted)

    hairline_y = bottom - 132
    draw.line((left + PADDING, hairline_y, right - PADDING, hairline_y), fill=divider_color, width=2)

    footer_y = hairline_y + 34
    brand_font = ImageFont.truetype(str(bold), 30)
    cta_font = ImageFont.truetype(str(regular), 27)
    draw.text((left + PADDING, footer_y), brand.name, font=brand_font, fill=ink, anchor="la")
    if brand.cta_text:
        draw.text(
            (right - PADDING, footer_y + 2),
            brand.cta_text,
            font=cta_font,
            fill=muted,
            anchor="ra",
        )

    # Footer outside the card.
    footer_color = _mix(primary, accent, 0.78)
    place_font = ImageFont.truetype(str(regular), 22)
    place = brand.location.split(",")[0].strip().upper()
    _draw_tracked(draw, width // 2, 1206, place, place_font, footer_color, 6)

    image.convert("RGB").save(out_path, format="PNG", optimize=True)

    payload = out_path.read_bytes()
    meta = ImageMeta(
        path=out_path,
        width=width,
        height=height,
        bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )
    if meta.bytes > MAX_BYTES:
        raise GraphicsError(f"image is {meta.bytes} bytes, above the 8 MB Instagram limit")
    return meta
