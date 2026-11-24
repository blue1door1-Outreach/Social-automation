"""Branded 1080x1350 editorial graphic.

Two renderers share one public entry point, :func:`render`:

* **Headless Chrome** (primary) draws the HTML template. It is the only one that
  can shape Bengali correctly, and it is what places the photo. Chrome must be
  installed; ``CHROME_PATH`` overrides auto-detection.
* **Pillow** (fallback) draws the text-only editorial layout. It has no Bengali
  shaping, so it is only used when every string is plain ASCII and no photo was
  requested.

Design goals: warm-white paper, sand and taupe accents, deep-brown text, a serif
Bangla headline, a real photo band with no people in it, generous white space.
"""

from __future__ import annotations

import base64
import hashlib
import html as html_module
import os
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import Brand

CANVAS = (1080, 1350)
MARGIN = 88
MAX_BYTES = 8 * 1024 * 1024
ROOT = Path(__file__).resolve().parent.parent

CHROME_CANDIDATES = (
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)
CHROME_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome")


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


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


def _is_ascii(text: str) -> bool:
    return all(ord(char) < 128 for char in text)


def _rgb(value: str) -> tuple[int, int, int]:
    text = value.lstrip("#")
    return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _meta(out_path: Path) -> ImageMeta:
    payload = Path(out_path).read_bytes()
    meta = ImageMeta(
        path=Path(out_path),
        width=CANVAS[0],
        height=CANVAS[1],
        bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )
    if meta.bytes > MAX_BYTES:
        raise GraphicsError(f"image is {meta.bytes} bytes, above the 8 MB Instagram limit")
    return meta


# --------------------------------------------------------------------------- #
# Chrome renderer
# --------------------------------------------------------------------------- #


def find_chrome() -> str | None:
    override = os.environ.get("CHROME_PATH", "").strip()
    if override and Path(override).exists():
        return override
    for name in CHROME_NAMES:
        found = shutil.which(name)
        if found:
            return found
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


@lru_cache(maxsize=4)
def _font_data_uri(filename: str) -> str:
    path = ROOT / "assets" / "fonts" / filename
    if not path.exists():
        raise GraphicsError(
            f"missing Bengali font {path}. It must be committed under assets/fonts."
        )
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:font/ttf;base64,{encoded}"


def _headline_size(headline: str) -> int:
    length = len(headline)
    if length <= 16:
        return 92
    if length <= 26:
        return 78
    if length <= 38:
        return 66
    return 58


_CSS = """
@font-face { font-family: 'BNSerif'; src: url(__SERIF__) format('truetype'); font-weight: 700; font-display: block; }
@font-face { font-family: 'BNSans'; src: url(__SANS__) format('truetype'); font-weight: 400; font-display: block; }
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { width: 1080px; height: 1350px; overflow: hidden; background: __PAPER__; }
.post { position: relative; width: 1080px; height: 1350px; overflow: hidden; background: __PAPER__;
        font-family: 'BNSans', 'Segoe UI', Roboto, 'DejaVu Sans', Arial, sans-serif; color: __INK__; }
.photo { position: absolute; top: 0; left: 0; width: 1080px; height: 600px; overflow: hidden; background: __TAUPE__; }
.photo img { width: 100%; height: 100%; object-fit: cover; display: block; }
.scrim { position: absolute; top: 0; left: 0; width: 1080px; height: 300px;
         background: linear-gradient(to bottom, rgba(28,20,9,.68), rgba(28,20,9,.30) 55%, rgba(28,20,9,0)); }
.fade { position: absolute; top: 430px; left: 0; width: 1080px; height: 170px;
        background: linear-gradient(to bottom, rgba(255,251,249,0), __PAPER__); }
.head { position: absolute; left: __MARGIN__px; right: __MARGIN__px; display: flex;
        justify-content: space-between; align-items: baseline; font-size: 21px;
        letter-spacing: 6px; text-transform: uppercase; }
.body { position: absolute; left: __MARGIN__px; right: __MARGIN__px; }
.kicker { font-size: 20px; letter-spacing: 3px; color: __MUTED__; text-transform: uppercase; }
.pill { display: inline-block; margin-top: 16px; background: __SAND__; color: __INK__;
        font-size: 21px; padding: 11px 26px; border-radius: 999px; }
h1 { position: relative; font-family: 'BNSerif', Georgia, serif; font-weight: 700;
     color: __INK__; margin-top: 26px; }
h1::before { content: ''; position: absolute; left: -34px; top: .18em; width: 6px;
             height: 1.05em; background: __SAND__; border-radius: 3px; }
.note { margin-top: 20px; font-size: 32px; line-height: 1.6; color: __MUTED__; max-width: 900px; }
.foot { position: absolute; left: __MARGIN__px; right: __MARGIN__px; bottom: 66px; }
.footrule { height: 2px; background: __RULE__; margin-bottom: 24px; }
.chips { display: flex; gap: 10px; margin-bottom: 22px; }
.chip { width: 18px; height: 18px; border-radius: 5px; }
.row { display: flex; justify-content: space-between; align-items: baseline; }
.brand { font-family: 'BNSerif', Georgia, serif; font-size: 34px; }
.cta { font-size: 26px; }
.follow { font-size: 20px; color: __MUTED__; margin-top: 8px; }
"""


def _mix_hex(a: str, b: str, t: float) -> str:
    ca, cb = _rgb(a), _rgb(b)
    mixed = tuple(round(ca[i] + (cb[i] - ca[i]) * t) for i in range(3))
    return "#{:02X}{:02X}{:02X}".format(*mixed)


# Runs inside headless Chrome before the screenshot. Chrome measures real Bengali
# text, so this is the only place that can shrink a long headline or takeaway
# until it clears the footer. Without it, a 60-character headline plus a long
# takeaway could overlap the footer rule.
_FIT_JS = """
(function () {
  var body = document.querySelector('.body');
  var foot = document.querySelector('.foot');
  var h1 = document.querySelector('.body h1');
  var note = document.querySelector('.body .note');
  if (!body || !foot || !h1) return;
  var limit = foot.getBoundingClientRect().top - 26;
  for (var guard = 0; guard < 60; guard++) {
    if (body.getBoundingClientRect().bottom <= limit) break;
    var hs = parseFloat(getComputedStyle(h1).fontSize);
    if (hs > 34) { h1.style.fontSize = (hs - 3) + 'px'; continue; }
    if (note) {
      var ns = parseFloat(getComputedStyle(note).fontSize);
      if (ns > 22) {
        note.style.fontSize = (ns - 1.5) + 'px';
        note.style.lineHeight = '1.5';
        continue;
      }
    }
    break;
  }
})();
"""


def _build_html(
    *,
    brand: Brand,
    headline: str,
    subline: str,
    kicker: str,
    label: str,
    follow: str,
    cta: str,
    place: str,
    photo_path: Path | None,
) -> str:
    ink = brand.color("ink", "#594E38")
    muted = brand.color("muted", "#7E7363")
    sand = brand.color("accent", "#E3CAA5")
    taupe = brand.color("secondary", "#ADB7B3")
    paper = brand.color("surface", "#FFFBF9")
    rule = _mix_hex(taupe, paper, 0.45)

    css = (
        _CSS.replace("__SERIF__", _font_data_uri("NotoSerifBengali-Bold.ttf"))
        .replace("__SANS__", _font_data_uri("NotoSansBengali-Regular.ttf"))
        .replace("__MARGIN__", str(MARGIN))
        .replace("__INK__", ink)
        .replace("__MUTED__", muted)
        .replace("__SAND__", sand)
        .replace("__TAUPE__", taupe)
        .replace("__PAPER__", paper)
        .replace("__RULE__", rule)
    )

    if photo_path is not None:
        encoded = base64.b64encode(Path(photo_path).read_bytes()).decode("ascii")
        photo_block = (
            f'<div class="photo"><img src="data:image/jpeg;base64,{encoded}" alt=""></div>'
            '<div class="scrim"></div><div class="fade"></div>'
        )
        head_style = (
            "top: 44px; color: #FFFBF9; "
            "text-shadow: 0 1px 4px rgba(18,12,4,.9), 0 2px 18px rgba(18,12,4,.6);"
        )
        body_top = 656
    else:
        photo_block = ""
        head_style = f"top: 84px; color: {ink}; text-shadow: none;"
        body_top = 210

    pill = f'<div class="pill">{html_module.escape(label)}</div>' if label.strip() else ""
    note = (
        f'<div class="note">{html_module.escape(subline)}</div>' if subline.strip() else ""
    )
    follow_html = (
        f'<div class="follow">{html_module.escape(follow)}</div>' if follow.strip() else ""
    )
    cta_html = f'<div class="cta">{html_module.escape(cta)}</div>' if cta.strip() else ""

    return f"""<!doctype html><html lang="bn"><head><meta charset="utf-8">
<title>post</title><style>{css}</style></head><body>
<div class="post">
  {photo_block}
  <div class="head" style="{head_style}"><div>{html_module.escape(brand.name.upper())}</div><div>{html_module.escape(place.upper())}</div></div>
  <div class="body" style="top: {body_top}px;">
    <div class="kicker">{html_module.escape(kicker.upper())}</div>
    {pill}
    <h1 style="font-size: {_headline_size(headline)}px; line-height: 1.45;">{html_module.escape(headline)}</h1>
    {note}
  </div>
  <div class="foot">
    <div class="footrule"></div>
    <div class="chips"><div class="chip" style="background:{sand}"></div><div class="chip" style="background:{taupe}"></div><div class="chip" style="background:{ink}"></div></div>
    <div class="row"><div class="brand">{html_module.escape(brand.name)}</div>{cta_html}</div>
    {follow_html}
  </div>
  <script>{_FIT_JS}</script>
</div></body></html>"""


def _render_chrome(
    out_path: Path,
    *,
    brand: Brand,
    headline: str,
    subline: str,
    kicker: str,
    label: str,
    follow: str,
    cta: str,
    place: str,
    photo_path: Path | None,
    chrome: str,
    timeout: int = 90,
) -> ImageMeta:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    page = out_path.parent / "_render.html"
    page.write_text(
        _build_html(
            brand=brand,
            headline=headline,
            subline=subline,
            kicker=kicker,
            label=label,
            follow=follow,
            cta=cta,
            place=place,
            photo_path=photo_path,
        ),
        encoding="utf-8",
    )

    shot = out_path.resolve()
    if shot.exists():
        shot.unlink()
    command = [
        chrome,
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--hide-scrollbars",
        "--force-device-scale-factor=1",
        "--run-all-compositor-stages-before-draw",
        "--virtual-time-budget=4000",
        f"--window-size={CANVAS[0]},{CANVAS[1]}",
        f"--screenshot={shot}",
        page.resolve().as_uri(),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise GraphicsError(f"headless Chrome timed out after {timeout}s") from exc
    except OSError as exc:
        raise GraphicsError(f"could not run headless Chrome ({chrome}): {exc}") from exc

    if not shot.exists() or shot.stat().st_size == 0:
        tail = (result.stderr or result.stdout or "").strip()[-400:]
        raise GraphicsError(f"headless Chrome produced no screenshot. {tail}")

    paper = _rgb(brand.color("surface", "#FFFBF9"))
    with Image.open(shot) as image:
        image = image.convert("RGB")
        if image.size != CANVAS:
            canvas = Image.new("RGB", CANVAS, paper)
            canvas.paste(image.crop((0, 0, CANVAS[0], CANVAS[1])), (0, 0))
            image = canvas
        image.save(shot, format="PNG", optimize=True)

    return _meta(shot)


# --------------------------------------------------------------------------- #
# Pillow renderer (text-only, ASCII)
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=6)
def font_path(weight: str) -> Path:
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
        ROOT / "assets" / "fonts",
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


def _mix(
    a: tuple[int, int, int], b: tuple[int, int, int], t: float
) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def _wrap(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int
) -> list[str]:
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
    text_width = sum(draw.textlength(char, font=font) for char in label) + tracking * max(
        len(label) - 1, 0
    )
    width = int(text_width + 48)
    height = 46
    draw.rounded_rectangle((x, y, x + width, y + height), radius=23, fill=fill)
    cursor = x + 24
    for char in label:
        draw.text((cursor, y + 11), char, font=font, fill=ink, anchor="la")
        cursor += draw.textlength(char, font=font) + tracking
    return y + height


def _render_pillow(
    out_path: Path,
    *,
    brand: Brand,
    headline: str,
    subline: str,
    kicker: str,
    label: str,
    follow: str,
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
    image = Image.alpha_composite(image, _soft_circle((width, height), (1090, 30), 300, sand, 60, 70))
    image = Image.alpha_composite(image, _soft_circle((width, height), (-40, 1310), 260, taupe, 42, 70))
    image = Image.alpha_composite(image, _soft_circle((width, height), (1120, 1120), 360, sand, 48, 80))
    draw = ImageDraw.Draw(image)

    bold = font_path("bold")
    regular = font_path("regular")
    serif = font_path("serif")

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

    footer_rule_y = 1050
    draw.line((MARGIN, footer_rule_y, width - MARGIN, footer_rule_y), fill=rule, width=2)

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
    return _meta(out_path)


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


def render(
    out_path: Path,
    *,
    brand: Brand,
    headline: str,
    subline: str = "",
    kicker: str = "WINTER STYLE NOTES",
    label: str = "",
    follow: str = "",
    photo: Path | None = None,
    cta: str = "",
    place: str = "",
) -> ImageMeta:
    """Render the daily graphic and return its metadata.

    Bengali text (or a photo) is routed to headless Chrome. Plain ASCII with no
    photo uses the Pillow layout so previews still work on a machine without
    Chrome.
    """
    out_path = Path(out_path)
    cta = cta or brand.cta_text
    place = place or brand.location.split(",")[0].strip()

    texts = (headline, subline, kicker, label, follow, cta, place)
    has_non_ascii = any(not _is_ascii(text) for text in texts)

    if has_non_ascii:
        chrome = find_chrome()
        if not chrome:
            raise GraphicsError(
                "Bengali text needs headless Chrome (it has no Bengali shaping in Pillow). "
                "Install Chrome or set CHROME_PATH."
            )
        return _render_chrome(
            out_path,
            brand=brand,
            headline=headline,
            subline=subline,
            kicker=kicker,
            label=label,
            follow=follow,
            cta=cta,
            place=place,
            photo_path=photo,
            chrome=chrome,
        )

    if photo is not None:
        chrome = find_chrome()
        if chrome:
            return _render_chrome(
                out_path,
                brand=brand,
                headline=headline,
                subline=subline,
                kicker=kicker,
                label=label,
                follow=follow,
                cta=cta,
                place=place,
                photo_path=photo,
                chrome=chrome,
            )

    return _render_pillow(
        out_path,
        brand=brand,
        headline=headline,
        subline=subline,
        kicker=kicker,
        label=label,
        follow=follow,
    )
