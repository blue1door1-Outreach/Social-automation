"""Content and image checks that run before anything is queued.

Every rule here exists because of a concrete failure mode in the plan:
invented prices, unsupported stock claims, banned phrases, captions that are
too long for Instagram, corrupt or wrongly sized images, and an image URL that
is not actually serving the file we generated.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from PIL import Image, UnidentifiedImageError

from .config import Brand, Catalog
from .writer import Draft

INSTAGRAM_CAPTION_LIMIT = 2196  # UTF-16 code units, newline = 2
INSTAGRAM_MAX_BYTES = 8 * 1024 * 1024
IMAGE_SIZE = (1080, 1350)


def utf16_units(text: str) -> int:
    """Instagram counts UTF-16 code units, and every line break counts as 2.

    Buffer's character-limit guide (checked 2026-11-23) states: Instagram uses
    UTF-16 code units, and every line break counts as 2. Emoji outside the BMP
    also cost 2 each, so plain len() understates the payload.
    """
    total = 0
    for char in text:
        if char == "\n":
            total += 2
        else:
            total += len(char.encode("utf-16-le")) // 2
    return total

PRICE_RE = re.compile(
    r"(?:৳|\$|£|€|\btk\.?\b|\btaka\b|\bbdt\b)\s?\d"
    r"|\b\d[\d,]*\s?(?:tk|taka|bdt)\b"
    r"|\b\d+\s?(?:%|percent)\b"
    r"|\b(?:price|prices|pricing)\b",
    re.IGNORECASE,
)
STOCK_RE = re.compile(
    r"\b(?:in stock|out of stock|sold out|limited stock|pre-?order|restock(?:ed)?)\b"
    r"|স্টক"
    r"|স্টকে",
    re.IGNORECASE,
)
HASHTAG_RE = re.compile(r"^#[A-Za-z0-9_]+$")


@dataclass(frozen=True)
class Issue:
    code: str
    severity: str  # "error" | "warning"
    message: str


def errors(issues: Sequence[Issue]) -> list[Issue]:
    return [issue for issue in issues if issue.severity == "error"]


def warnings(issues: Sequence[Issue]) -> list[Issue]:
    return [issue for issue in issues if issue.severity == "warning"]


def _contains_phrase(text: str, phrase: str) -> bool:
    lowered = text.lower()
    phrase = phrase.lower().strip()
    if not phrase:
        return False
    if re.fullmatch(r"[a-z0-9 ]+", phrase):
        return re.search(rf"\b{re.escape(phrase)}\b", lowered) is not None
    return phrase in lowered


def _sentences(text: str) -> list[str]:
    return [
        part.strip().lower()
        for part in re.split(r"(?<=[.!?।])\s+", text)
        if part.strip()
    ]


def _bangla_words(text: str) -> list[str]:
    """Count words that carry Bangla script, ignoring hashtags and the tagline."""
    words = []
    for token in text.split():
        if token.startswith("#"):
            continue
        if any("\u0980" <= char <= "\u09ff" for char in token):
            words.append(token)
    return words


def validate_draft(draft: Draft, brand: Brand, catalog: Catalog) -> list[Issue]:
    issues: list[Issue] = []
    caption = draft.caption.strip()
    full_text = draft.full_text()
    is_story = draft.format == "story"

    min_chars = brand.caption.story_min_chars if is_story else brand.caption.min_chars
    max_chars = brand.caption.story_max_chars if is_story else brand.caption.max_chars

    if not caption:
        issues.append(Issue("caption_empty", "error", "caption is empty"))
    if len(caption) < min_chars:
        issues.append(
            Issue(
                "caption_short",
                "error",
                f"caption is {len(caption)} chars, below the {min_chars} minimum",
            )
        )
    if len(caption) > max_chars:
        issues.append(
            Issue(
                "caption_long",
                "error",
                f"caption is {len(caption)} chars, above the {max_chars} maximum",
            )
        )

    if is_story:
        words = _bangla_words(caption)
        if len(words) < brand.caption.story_min_words:
            issues.append(
                Issue(
                    "story_short",
                    "error",
                    f"story is {len(words)} Bangla words, below the "
                    f"{brand.caption.story_min_words} minimum",
                )
            )
        if len(words) > brand.caption.story_max_words:
            issues.append(
                Issue(
                    "story_long",
                    "error",
                    f"story is {len(words)} Bangla words, above the "
                    f"{brand.caption.story_max_words} maximum",
                )
            )
        paragraphs = [part for part in re.split(r"\n\s*\n", caption) if part.strip()]
        if not 10 <= len(paragraphs) <= 22:
            issues.append(
                Issue(
                    "story_paragraphs",
                    "error",
                    f"story has {len(paragraphs)} paragraphs, expected 10-22 short ones",
                )
            )
        title = draft.image_headline.strip()
        if title and not caption.startswith(title):
            issues.append(
                Issue(
                    "story_title",
                    "error",
                    "story must open with the title hook as its first line",
                )
            )
        if "?" not in caption.split("\n\n")[-1]:
            issues.append(
                Issue(
                    "story_question",
                    "error",
                    "story must end with a question that invites comments",
                )
            )
    if utf16_units(full_text) > INSTAGRAM_CAPTION_LIMIT:
        issues.append(
            Issue(
                "caption_platform_limit",
                "error",
                f"caption plus hashtags is {utf16_units(full_text)} UTF-16 units, "
                f"above Instagram's {INSTAGRAM_CAPTION_LIMIT}",
            )
        )

    tags = list(draft.hashtags)
    if not (brand.caption.min_hashtags <= len(tags) <= brand.caption.max_hashtags):
        issues.append(
            Issue(
                "hashtag_count",
                "error",
                f"{len(tags)} hashtags, expected {brand.caption.min_hashtags}-{brand.caption.max_hashtags}",
            )
        )
    for tag in tags:
        if not HASHTAG_RE.match(tag):
            issues.append(Issue("hashtag_format", "error", f"invalid hashtag: {tag!r}"))
    lowered_tags = {tag.lower() for tag in tags}
    for required in brand.required_hashtags:
        if required.lower() not in lowered_tags:
            issues.append(Issue("hashtag_required", "error", f"missing required hashtag {required}"))

    if brand.price_policy == "never" and PRICE_RE.search(caption):
        issues.append(
            Issue("price_claim", "error", "caption mentions a price or pricing, which is never allowed")
        )
    if brand.stock_policy == "never" and STOCK_RE.search(caption):
        issues.append(
            Issue("stock_claim", "error", "caption mentions stock status, which is never allowed")
        )

    for phrase in brand.banned_phrases:
        if _contains_phrase(caption, phrase):
            issues.append(Issue("banned_phrase", "error", f"caption contains banned phrase {phrase!r}"))

    if caption.count("!") > 1:
        issues.append(Issue("punctuation", "error", "more than one exclamation mark"))
    if not 2 <= len(draft.image_headline.strip()) <= 60:
        issues.append(
            Issue("headline_length", "error", "image headline must be 2-60 characters")
        )
    if len(draft.image_subline.strip()) > 90:
        issues.append(Issue("subline_length", "error", "image subline must be at most 90 characters"))

    if not is_story:
        sentences = _sentences(caption)
        if len(sentences) != len(set(sentences)):
            issues.append(Issue("repetition", "error", "caption repeats a sentence"))

    ctas = [text for text in (brand.cta_text, brand.cta_text_bn) if text]
    if not is_story and ctas and not any(text.lower() in caption.lower() for text in ctas):
        issues.append(Issue("cta_missing", "warning", "caption does not include the configured CTA"))

    if draft.product_ids:
        known = {product.id for product in catalog.products if product.enabled}
        for product_id in draft.product_ids:
            if product_id not in known:
                issues.append(
                    Issue("unknown_product", "error", f"draft references unknown product {product_id!r}")
                )

    return issues


def validate_image(path: Path, expected_sha: str = "") -> list[Issue]:
    issues: list[Issue] = []
    path = Path(path)
    if not path.exists():
        return [Issue("image_missing", "error", f"image not found at {path}")]
    if path.stat().st_size > INSTAGRAM_MAX_BYTES:
        issues.append(Issue("image_size", "error", "image exceeds the 8 MB Instagram limit"))

    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            if image.format not in ("PNG", "JPEG"):
                issues.append(Issue("image_format", "error", f"unsupported format {image.format}"))
            if image.size != IMAGE_SIZE:
                issues.append(
                    Issue("image_dimensions", "error", f"expected {IMAGE_SIZE}, got {image.size}")
                )
            image.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        issues.append(Issue("image_decode", "error", f"image does not decode: {exc}"))
        return issues

    if expected_sha:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected_sha:
            issues.append(Issue("image_hash", "error", "image changed on disk after rendering"))

    return issues


def check_public_image(
    url: str,
    expected_sha: str,
    fetch: Callable[[str], tuple[str, bytes]],
    *,
    attempts: int = 4,
    delays: Sequence[int] = (5, 15, 30),
    sleep: Callable[[float], None] | None = None,
) -> list[Issue]:
    """Confirm the URL serves our exact bytes, not a cached or placeholder page."""
    if not url:
        return [Issue("image_url", "error", "no public image URL configured")]
    if sleep is None:
        import time

        sleep = time.sleep

    last_error = "not checked"
    for attempt in range(attempts):
        try:
            content_type, payload = fetch(url)
            if not content_type.lower().startswith("image/"):
                raise ValueError(f"unexpected content-type {content_type!r}")
            if len(payload) < 1024:
                raise ValueError(f"response is only {len(payload)} bytes")
            digest = hashlib.sha256(payload).hexdigest()
            if digest != expected_sha:
                raise ValueError("served image does not match the generated file (still deploying?)")
            return []
        except Exception as exc:  # network, HTTP, content and hash errors all retry
            last_error = str(exc)
            if attempt < attempts - 1:
                sleep(delays[min(attempt, len(delays) - 1)])

    return [Issue("image_url", "error", f"public image check failed: {last_error}")]
