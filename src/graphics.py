"""Branded 1080x1350 editorial graphic with Pillow.

Design goals: warm-white paper, sand and taupe accents, deep-brown text, a serif
headline, generous white space. Text only - no people, no product photos. Text is
measured and shrunk to fit; if it cannot fit, rendering fails instead of
cropping.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import Brand

CANVAS = (1080, 1350)
MARGIN = 88
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


@lru_cache(maxsize=6)
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
        "serif": (
            "Georgia.ttf",
            "georgia.ttf",
            "DejaVuSerif-Bold.ttf",
            "LiberationSerif-Bold.ttf",
            "timesbd.ttf",
            "Times New Roman Bold.ttf",
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
        f"no usable {weight} font found. Add assets/fonts or install DejaVu fonts."
    )


def _rgb(value: str) -> tuple[int, int, int]:
    text = value.lstrip("#")
    return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


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
        line_height = int(size * 1.12)
        if any(draw.textlength(line, font=font) > max_width + 1 for line in lines):
            continue
        if len(lines) * line_height > max_height:
            continue

        # Avoid an orphan word in a badly balanced two-line wrap.
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


def _draw_left_lines(
    draw: ImageDraw.ImageDraw,
    lines: tuple[str, ...],
    font: ImageFont.FreeTypeFont,
    x: int,
    top: int,
    line_height: int,
    fill: tuple[int, int, int],
) -> int:
    y = top
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill, anchor="la")
        y += line_height
    return y


def _draw_tracked_left(
    draw: ImageDraw.ImageDraw,
    x: int,
    top: int,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    tracking: int,
) -> None:
    cursor = x
    for char in text:
        draw.text((cursor, top), char, font=font, fill=fill, anchor="la")
        cursor += draw.textlength(char, font=font) + tracking


def _draw_tracked_right(
    draw: ImageDraw.ImageDraw,
    x: int,
    top: int,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    tracking: int,
) -> None:
    widths = [draw.textlength(char, font=font) for char in text]
    total = sum(widths) + tracking * max(len(text) - 1, 0)
    cursor = x - total
    for char, width in zip(text, widths):
        draw.text((cursor, top), char, font=font, fill=fill, anchor="la")
        cursor += width + tracking


def _soft_circle(
    size: tuple[int, int],
    center: tuple[int, int],
    radius: int,
    color: tuple[int, int, int],
    alpha: int,
    blur: int,
) -> Image.Image:
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    x, y = center
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(*color, alpha))
    return layer.filter(ImageFilter.GaussianBlur(blur))


def _pill(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    label: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    ink: tuple[int, int, int],
) -> int:
    tracking = 3
    text_width = sum(draw.textlength(char, font=font) for char in label) + tracking * max(len(label) - 1, 0)
    width = int(text_width + 48)
    height = 46
    draw.rounded_rectangle((x, y, x + width, y + height), radius=23, fill=fill)
    cursor = x + 24
    for char in label:
        draw.text((cursor, y + 11), char, font=font, fill=ink, anchor="la")
        cursor += draw.textlength(char, font=font) + tracking
    return y + height


def render(
    out_path: Path,
    *,
    brand: Brand,
    headline: str,
    subline: str = "",
    kicker: str = "WINTER STYLE NOTES",
    label: str = "",
    follow: str = "",
) -> ImageMeta:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    ink = _rgb(brand.color("ink", "#594E38"))
    muted = _rgb(brand.color("muted", "#7E7363"))
    sand = _rgb(brand.color("accent", "#E3CAA5"))
    taupe = _rgb(brand.color("secondary", "#ADB7B3"))
    paper = _rgb(brand.color("surface", "#FFFBF9"))

    width, height = CANVAS
    image = Image.new("RGBA", (width, height), (*paper, 255))

    # Soft colour washes, kept low-contrast so the paper still reads as paper.
    image = Image.alpha_composite(image, _soft_circle((width, height), (1090, 30), 300, sand, 60, 70))
    image = Image.alpha_composite(image, _soft_circle((width, height), (-40, 1310), 260, taupe, 42, 70))
    image = Image.alpha_composite(image, _soft_circle((width, height), (1120, 1120), 360, sand, 48, 80))
    draw = ImageDraw.Draw(image)

    bold = font_path("bold")
    regular = font_path("regular")
    serif = font_path("serif")

    # Header.
    wordmark_font = ImageFont.truetype(str(bold), 24)
    _draw_tracked_left(draw, MARGIN, 92, brand.name.upper(), wordmark_font, ink, 6)
    place_font = ImageFont.truetype(str(regular), 19)
    place = brand.location.split(",")[0].strip().upper()
    _draw_tracked_right(draw, width - MARGIN, 96, place, place_font, muted, 4)

    rule = _mix(taupe, paper, 0.45)
    draw.line((MARGIN, 152, width - MARGIN, 152), fill=rule, width=2)

    cursor = 200
    if kicker:
        kicker_font = ImageFont.truetype(str(bold), 19)
        _draw_tracked_left(draw, MARGIN, cursor, kicker.upper(), kicker_font, muted, 4)
        cursor += 52

    if label:
        label_font = ImageFont.truetype(str(bold), 19)
        cursor = _pill(draw, MARGIN, cursor, label.upper(), label_font, sand, ink) + 54
    else:
        cursor += 20

    head_top = cursor
    inner_w = width - MARGIN * 2

    head_fit = fit_text(draw, headline, "serif", inner_w, 400, 5, max_size=104, min_size=56)
    sub_fit = (
        fit_text(draw, subline, "regular", inner_w - 40, 160, 3, max_size=36, min_size=27)
        if subline.strip()
        else None
    )

    block_height = len(head_fit.lines) * head_fit.line_height
    gap = 42 if sub_fit else 0
    if sub_fit:
        block_height += gap + len(sub_fit.lines) * sub_fit.line_height

    region_top, region_bottom = head_top + 10, 1010
    centered = region_top + max(0, (region_bottom - region_top - block_height) // 2)
    block_top = max(head_top + 40, centered - 80)

    # Small sand accent beside the headline.
    accent_height = min(max(int(head_fit.line_height * 0.9), 64), 118)
    draw.rounded_rectangle(
        (MARGIN - 40, block_top + 8, MARGIN - 34, block_top + 8 + accent_height),
        radius=3,
        fill=sand,
    )

    cursor = _draw_left_lines(
        draw, head_fit.lines, head_fit.font, MARGIN, block_top, head_fit.line_height, ink
    )
    if sub_fit:
        cursor += gap
        _draw_left_lines(
            draw, sub_fit.lines, sub_fit.font, MARGIN, cursor, sub_fit.line_height, muted
        )

    # Footer rule.
    footer_rule_y = 1050
    draw.line((MARGIN, footer_rule_y, width - MARGIN, footer_rule_y), fill=rule, width=2)

    # Palette signature: sand, taupe, deep brown.
    chip_y = footer_rule_y + 26
    chip = 18
    for index, color in enumerate((sand, taupe, ink)):
        x = MARGIN + index * (chip + 10)
        draw.rounded_rectangle((x, chip_y, x + chip, chip_y + chip), radius=5, fill=color)

    brand_font = ImageFont.truetype(str(serif), 34)
    cta_font = ImageFont.truetype(str(regular), 26)
    follow_font = ImageFont.truetype(str(regular), 21)

    brand_y = chip_y + 44
    draw.text((MARGIN, brand_y), brand.name, font=brand_font, fill=ink, anchor="la")
    if brand.cta_text:
        draw.text(
            (width - MARGIN, brand_y + 7),
            brand.cta_text,
            font=cta_font,
            fill=ink,
            anchor="ra",
        )
    if follow:
        draw.text((MARGIN, brand_y + 52), follow, font=follow_font, fill=muted, anchor="la")

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