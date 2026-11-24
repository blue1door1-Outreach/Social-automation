"""Caption and headline generation.

Two paths:

* ``build_offline`` - deterministic, template based, used when there is no API
  key or the network is off. Safe but repetitive.
* ``generate`` - Gemini with a JSON response schema. On quota/network trouble it
  retries a few times, then raises ``WriterError`` so the run stops instead of
  publishing something half-finished.

Neither path is allowed to invent product facts. The only inputs are the topic,
the product's name/category, and the brand config.
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from dataclasses import dataclass, replace
from datetime import date
from typing import Any, Sequence

import requests

from .config import Brand, Catalog, Product
from .topic_filter import Topic

LOG = logging.getLogger("khuje.writer")

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
# Checked 2026-11-24: 2.5 Flash is closed to new users; 3.8 Flash is current.
DEFAULT_MODEL = "gemini-3.8-flash"

HOOKS: dict[str, tuple[str, ...]] = {
    "hoodie": ("Hoodie weather.", "Easy layer, all day.", "Cold mornings, covered."),
    "outerwear": ("Winter, sorted.", "Cold mornings, handled.", "One layer, done."),
    "shirt-jacket": ("Shacket season.", "Checks and layers.", "Between shirt and jacket."),
    "denim": ("Denim, layered.", "Cold-day denim.", "The everyday overshirt."),
    "polo": ("Polo, but warmer.", "Full sleeves, clean look.", "Smart and simple."),
    "sweatshirt": ("Sweatshirt weather.", "Easy layer, all day.", "Soft and simple."),
    "knitwear": ("Knit weather.", "Soft layers, easy days.", "A warmer kind of basic."),
    "base layer": ("The hidden layer.", "Warmth starts underneath.", "First layer, best layer."),
    "set": ("Winter, head to toe.", "Little layers, sorted.", "One set, ready."),
    "accessories": ("Small pieces, big difference.", "Details that warm you up.", "The finishing layer."),
}
DEFAULT_HOOKS = ("Winter, sorted.", "Layer up, simply.", "Cold outside, easy inside.")

# Safe benefit lines. They describe the category, never a material, price,
# stock level or delivery promise.
LINES: dict[str, tuple[str, ...]] = {
    "hoodie": (
        "A soft layer for school runs and evening walks.",
        "Easy to pull on when the morning turns cold.",
    ),
    "outerwear": (
        "A warm layer for the foggy morning commute.",
        "Made for the cold snap, easy to wear every day.",
    ),
    "shirt-jacket": (
        "A check layer that works over a tee.",
        "Between a shirt and a jacket, right for Dhaka winter.",
    ),
    "denim": (
        "Denim that layers without the bulk.",
        "An easy overshirt for cooler afternoons.",
    ),
    "polo": (
        "Full sleeves for the cooler days.",
        "A clean collar for winter mornings.",
    ),
    "sweatshirt": (
        "A soft layer for school runs and evening walks.",
        "Easy to pull on when the morning turns cold.",
    ),
    "knitwear": (
        "A soft knit for the cooler evenings.",
        "Easy warmth for the office and the ride home.",
    ),
    "base layer": (
        "The layer that keeps the cold out.",
        "Warmth that starts under everything.",
    ),
    "set": (
        "A matching winter set for the little ones.",
        "Everything for a cold morning, in one set.",
    ),
    "accessories": (
        "A small piece that changes the whole outfit.",
        "The finishing touch for a cold morning.",
    ),
}
DEFAULT_LINES = (
    "A winter basic that earns its place.",
    "An easy pick for the colder days.",
)


class WriterError(RuntimeError):
    pass


class WriterUnavailable(WriterError):
    """Gemini could not be reached (5xx, timeout). Safe to use templates instead."""


@dataclass(frozen=True)
class Draft:
    hook: str
    caption: str
    hashtags: tuple[str, ...]
    image_headline: str
    image_subline: str
    product_ids: tuple[str, ...]
    source: str

    def full_text(self) -> str:
        if not self.hashtags:
            return self.caption
        return f"{self.caption}\n\n{' '.join(self.hashtags)}"


def _ensure_sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    if text[-1] in ".!?":
        return text
    return f"{text}."


def _audience_pool(brand: Brand, product: Product | None) -> list[str]:
    pool: list[str] = []
    if product:
        for group in product.audience:
            pool.extend(brand.hashtag_pools.get(group.lower(), ()))
    return list(dict.fromkeys(pool))


def _hashtags(brand: Brand, product: Product | None, rng: random.Random) -> tuple[str, ...]:
    limit = brand.caption.max_hashtags
    chosen: list[str] = []

    def add(tag: str) -> None:
        tag = tag.strip()
        if not tag.startswith("#") or " " in tag:
            return
        if tag.lower() in {item.lower() for item in chosen}:
            return
        if len(chosen) < limit:
            chosen.append(tag)

    for tag in brand.required_hashtags:
        add(tag)

    audience = _audience_pool(brand, product)
    winter = list(brand.hashtag_pools.get("winter", ()))
    local = list(brand.hashtag_pools.get("local", ()))

    plan: list[tuple[list[str], int]] = []
    if audience:
        plan.append((audience, 2))
    plan.append((winter, 4))
    plan.append((local, 2))

    for pool, quota in plan:
        rng.shuffle(pool)
        for tag in pool[:quota]:
            add(tag)

    filler = audience + winter + local
    rng.shuffle(filler)
    for tag in filler:
        add(tag)

    return tuple(chosen[:limit])


def build_offline(
    topic: Topic,
    product: Product | None,
    brand: Brand,
    day: date,
) -> Draft:
    rng = random.Random(f"{day.isoformat()}|{topic.title}")

    hooks = HOOKS.get(product.category.lower(), DEFAULT_HOOKS) if product else DEFAULT_HOOKS
    hook = rng.choice(hooks)
    lines = LINES.get(product.category.lower(), DEFAULT_LINES) if product else DEFAULT_LINES
    line = rng.choice(lines)

    if product:
        sentence = f"{line} {product.name} from {brand.name}, part of the winter edit."
        headline = f"The {product.name.lower()}"
    else:
        sentence = f"Winter basics from {brand.name}, part of the winter edit."
        headline = "Winter, layer by layer"

    parts = [hook, sentence]
    if brand.cta_text:
        parts.append(_ensure_sentence(brand.cta_text))
    caption = " ".join(parts).strip()

    if len(caption) < brand.caption.min_chars:
        caption = f"{caption} {brand.tagline}".strip()
    if len(caption) > brand.caption.max_chars:
        sentence = f"{product.name if product else 'Winter basics'} from {brand.name}."
        parts = [hook, sentence]
        if brand.cta_text:
            parts.append(_ensure_sentence(brand.cta_text))
        caption = " ".join(parts).strip()

    return Draft(
        hook=hook,
        caption=caption,
        hashtags=_hashtags(brand, product, rng),
        image_headline=headline,
        image_subline=brand.tagline,
        product_ids=(product.id,) if product else (),
        source="offline",
    )


def _system_prompt(brand: Brand) -> str:
    return (
        f"You write short English social captions for {brand.name}, "
        f"{brand.description} Audience: {brand.audience}. "
        f"Tone: {brand.tone}. Location: {brand.location}.\n"
        "Hard rules:\n"
        "- Use only the product names and categories given by the user. Invent nothing.\n"
        "- Never mention price, discount, sale, stock level, delivery time, warranty, "
        "origin, or material composition.\n"
        "- Never state a news headline as a fact. The topic is only an angle.\n"
        "- The graphic is text only: never mention people, models, or photos of women.\n"
        "- No emoji. At most one exclamation mark. Plain, concrete language.\n"
        "- Return JSON only, matching the schema. No code fences, no commentary."
    )


def _allowed_tags(brand: Brand, product: Product | None) -> list[str]:
    pool: list[str] = []
    groups = ["winter", "local"]
    if product:
        groups.extend(product.audience)
    for group in groups:
        pool.extend(brand.hashtag_pools.get(group.lower(), ()))
    return list(dict.fromkeys(pool))


def _user_prompt(topic: Topic, product: Product | None, brand: Brand) -> str:
    products = []
    if product:
        products.append(f"- id={product.id}; name={product.name}; category={product.category}")
    else:
        products.append("- (no specific product)")

    tag_pool = ", ".join(_allowed_tags(brand, product)[:30])
    requirements = (
        f"caption: {brand.caption.min_chars}-{brand.caption.max_chars} characters, 1-2 sentences.\n"
        f"hashtags: {brand.caption.min_hashtags}-{brand.caption.max_hashtags} tags, each starting with #, "
        f"must include {', '.join(brand.required_hashtags) or 'none'}. "
        f"Prefer tags from this pool: {tag_pool or 'none'}.\n"
        "image_headline: 2-6 words, no punctuation at the end.\n"
        "image_subline: under 70 characters.\n"
        "hook: 3-6 words, the first thing a reader sees."
    )
    return (
        f"Topic angle: {topic.title}\n"
        f"Topic source: {topic.source}\n"
        f"Products you may mention:\n{chr(10).join(products)}\n"
        f"CTA to use: {brand.cta_text or 'none'}\n"
        f"Phrases that are forbidden: {', '.join(brand.banned_phrases) or 'none'}\n\n"
        f"{requirements}\n\n"
        'Return {"hook","caption","hashtags","image_headline","image_subline","product_ids"}.'
    )


_SCHEMA = {
    "type": "object",
    "properties": {
        "hook": {"type": "string"},
        "caption": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "image_headline": {"type": "string"},
        "image_subline": {"type": "string"},
        "product_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["hook", "caption", "hashtags", "image_headline", "image_subline", "product_ids"],
}


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise WriterError("model returned no JSON object")
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise WriterError(f"model returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise WriterError("model returned JSON that is not an object")
    return data


def _merge_hashtags(
    model_tags: Sequence[str],
    brand: Brand,
    product: Product | None,
    rng: random.Random,
) -> tuple[str, ...]:
    limit = brand.caption.max_hashtags
    ordered: list[str] = []

    def add(tag: str) -> None:
        tag = tag.strip()
        if not tag.startswith("#") or " " in tag:
            return
        if tag.lower() in {item.lower() for item in ordered}:
            return
        if len(ordered) < limit:
            ordered.append(tag)

    for tag in brand.required_hashtags:
        add(tag)
    for tag in list(model_tags)[:3]:
        add(tag)
    for tag in _hashtags(brand, product, rng):
        add(tag)
    for tag in list(model_tags)[3:]:
        add(tag)
    return tuple(ordered[:limit])


def _post_process(data: dict[str, Any], topic: Topic, product: Product | None, brand: Brand) -> Draft:
    caption = str(data.get("caption", "")).strip()
    if not caption:
        raise WriterError("model returned an empty caption")

    if len(caption) > brand.caption.max_chars:
        trimmed = caption[: brand.caption.max_chars]
        cut = max(trimmed.rfind(". "), trimmed.rfind("! "), trimmed.rfind("? "))
        caption = trimmed[: cut + 1] if cut > 40 else trimmed.rsplit(" ", 1)[0].rstrip(",;:") + "."
        LOG.warning("trimmed model caption from %d to %d chars", len(data.get("caption", "")), len(caption))

    raw_tags: Sequence[Any] = data.get("hashtags") or []
    model_tags = [str(raw).strip() for raw in raw_tags]
    tags = _merge_hashtags(
        model_tags,
        brand,
        product,
        random.Random(f"{caption}|{product.id if product else 'none'}"),
    )

    headline = str(data.get("image_headline", "")).strip().rstrip(".!?")
    if not headline:
        headline = f"The {product.name.lower()}" if product else "Winter, layer by layer"
    subline = str(data.get("image_subline", "")).strip() or brand.tagline

    product_ids = tuple(str(pid) for pid in (data.get("product_ids") or []) if isinstance(pid, str))
    if product and product.id not in product_ids:
        product_ids = (product.id,)

    return Draft(
        hook=str(data.get("hook", "")).strip() or headline,
        caption=caption,
        hashtags=tuple(tags),
        image_headline=headline,
        image_subline=subline,
        product_ids=product_ids,
        source="gemini",
    )


def _call_gemini(
    payload: dict[str, Any],
    api_key: str,
    model: str,
    session: requests.Session,
    base_url: str,
    timeout: int,
    attempts: int = 4,
) -> str:
    url = f"{base_url.rstrip('/')}/models/{model}:generateContent"
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    delays = (2, 5, 10, 20)

    last_error = "unknown error"
    for attempt in range(attempts):
        try:
            response = session.post(url, json=payload, headers=headers, timeout=timeout)
        except requests.Timeout as exc:
            last_error = f"timeout: {exc}"
        except requests.RequestException as exc:
            last_error = f"request failed: {exc}"
        else:
            if response.status_code < 400:
                try:
                    body = response.json()
                    parts = body["candidates"][0]["content"]["parts"]
                    return "".join(part.get("text", "") for part in parts)
                except (KeyError, IndexError, TypeError, ValueError) as exc:
                    raise WriterError(f"unexpected Gemini response shape: {exc}") from exc

            snippet = response.text[:300]
            if response.status_code in (400, 401, 403, 404):
                raise WriterError(f"Gemini rejected the request ({response.status_code}): {snippet}")
            last_error = f"HTTP {response.status_code}: {snippet}"

        if attempt < attempts - 1:
            time.sleep(delays[min(attempt, len(delays) - 1)])

    raise WriterUnavailable(f"Gemini unavailable after {attempts} attempts: {last_error}")


def generate(
    topic: Topic,
    product: Product | None,
    brand: Brand,
    catalog: Catalog,
    day: date,
    *,
    offline: bool = False,
    api_key: str = "",
    model: str = DEFAULT_MODEL,
    session: requests.Session | None = None,
    base_url: str = GEMINI_BASE,
    timeout: int = 30,
    log: logging.Logger | None = None,
) -> Draft:
    log = log or LOG
    if offline:
        log.info("writer: offline mode, using templates")
        return build_offline(topic, product, brand, day)
    if not api_key:
        log.warning("writer: GEMINI_API_KEY is not set, falling back to templates")
        return build_offline(topic, product, brand, day)

    session = session or requests.Session()
    payload = {
        "systemInstruction": {"parts": [{"text": _system_prompt(brand)}]},
        "contents": [{"role": "user", "parts": [{"text": _user_prompt(topic, product, brand)}]}],
        "generationConfig": {
            "temperature": 0.85,
            "maxOutputTokens": 512,
            "responseMimeType": "application/json",
            "responseSchema": _SCHEMA,
        },
    }
    try:
        raw = _call_gemini(payload, api_key, model, session, base_url, timeout)
    except WriterUnavailable as exc:
        log.warning("writer: Gemini unavailable, using templates: %s", exc)
        fallback = build_offline(topic, product, brand, day)
        return replace(fallback, source="offline-fallback")
    data = _extract_json(raw)
    draft = _post_process(data, topic, product, brand)
    log.info("writer: gemini draft ready (%d chars, %d tags)", len(draft.caption), len(draft.hashtags))
    return draft
