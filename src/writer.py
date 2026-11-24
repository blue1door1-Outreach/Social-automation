"""Caption and headline generation for engagement-first winter posts.

The account publishes Bangla styling, layering and care notes, not product ads.
Two paths:

* ``build_from_idea`` - deterministic templates from ``config/content.json``,
  used offline or when there is no API key. If an idea carries ``*_bn`` fields
  the caption and headline are Bangla; otherwise they fall back to English.
* ``generate`` - Gemini rewrites the same idea into a shorter Bangla caption,
  using a JSON response schema. A retired model or rejected key stops the run; a
  5xx or timeout falls back to the template so a busy API does not lose the day.

Neither path may invent facts or sell: no prices, stock, delivery, materials,
"buy now", or product pushes. Hashtags stay English letters and digits so every
platform accepts them.
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

from .config import Brand
from .content import ContentConfig, ContentIdea

LOG = logging.getLogger("khuje.writer")

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
# Checked 2026-11-24: 2.5 Flash is closed to new users; 3.8 Flash is current.
DEFAULT_MODEL = "gemini-3.8-flash"


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


def _is_bangla(text: str) -> bool:
    return any("\u0980" <= char <= "\u09ff" for char in text)


def _terminator(text: str) -> str:
    return "।" if _is_bangla(text) else "."


def _ensure_sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    if text[-1] in ".!?।":
        return text
    return f"{text}{_terminator(text)}"


def _audience_pool(brand: Brand, audience: Sequence[str]) -> list[str]:
    pool: list[str] = []
    for group in audience:
        pool.extend(brand.hashtag_pools.get(group.lower(), ()))
    return list(dict.fromkeys(pool))


def _hashtags(brand: Brand, audience: Sequence[str], rng: random.Random) -> tuple[str, ...]:
    limit = brand.caption.max_hashtags
    chosen: list[str] = []

    def add(tag: str) -> None:
        tag = tag.strip()
        if not re.fullmatch(r"#[A-Za-z0-9_]+", tag):
            return
        if tag.lower() in {item.lower() for item in chosen}:
            return
        if len(chosen) < limit:
            chosen.append(tag)

    for tag in brand.required_hashtags:
        add(tag)

    audience_pool = _audience_pool(brand, audience)
    winter = list(brand.hashtag_pools.get("winter", ()))
    local = list(brand.hashtag_pools.get("local", ()))

    plan: list[tuple[list[str], int]] = []
    if audience_pool:
        plan.append((audience_pool, 2))
    plan.append((winter, 4))
    plan.append((local, 2))

    for pool, quota in plan:
        rng.shuffle(pool)
        for tag in pool[:quota]:
            add(tag)

    filler = audience_pool + winter + local
    rng.shuffle(filler)
    for tag in filler:
        add(tag)

    return tuple(chosen[:limit])


def build_from_idea(
    idea: ContentIdea,
    brand: Brand,
    content: ContentConfig,
    day: date,
) -> Draft:
    rng = random.Random(f"{day.isoformat()}|{idea.id}")

    title = idea.display_title
    body = idea.display_body
    note = idea.display_note
    cta = brand.cta_text_bn or brand.cta_text
    follow = content.display_follow

    parts = [_ensure_sentence(title), _ensure_sentence(body)]
    if cta:
        parts.append(_ensure_sentence(cta))
    caption = " ".join(parts).strip()

    if follow:
        with_follow = f"{caption} {_ensure_sentence(follow)}".strip()
        if len(with_follow) <= brand.caption.max_chars:
            caption = with_follow

    if len(caption) < brand.caption.min_chars and brand.tagline:
        caption = f"{caption} {_ensure_sentence(brand.tagline)}".strip()

    if len(caption) > brand.caption.max_chars:
        caption = " ".join(
            [
                _ensure_sentence(title),
                _ensure_sentence(body),
                _ensure_sentence(cta) if cta else "",
            ]
        ).strip()
    if len(caption) > brand.caption.max_chars:
        caption = _clip(caption, brand.caption.max_chars)

    return Draft(
        hook=title,
        caption=caption,
        hashtags=_hashtags(brand, idea.audience, rng),
        image_headline=title,
        image_subline=note,
        product_ids=(),
        source="offline",
    )


def _system_prompt(brand: Brand) -> str:
    return (
        f"You write short social captions in Bangla (Bengali script) for {brand.name}, "
        f"{brand.description} Audience: {brand.audience}. "
        f"Tone: {brand.tone}. Location: {brand.location}.\n"
        "This account shares winter tips, not product ads.\n"
        "Hard rules:\n"
        "- Write every caption, headline and takeaway in Bangla, not English.\n"
        "- Use only the idea given by the user. Invent nothing.\n"
        "- Never sell. No price, discount, stock, delivery, warranty, material or 'buy now'.\n"
        "- Never mention a product name or push a product.\n"
        "- One to three short sentences. No emoji. At most one exclamation mark.\n"
        "- Keep hashtags in English letters and digits only.\n"
        "- Return JSON only, matching the schema. No code fences, no commentary."
    )


def _allowed_tags(brand: Brand, audience: Sequence[str]) -> list[str]:
    groups = ["winter", "local", *audience]
    pool: list[str] = []
    for group in groups:
        pool.extend(brand.hashtag_pools.get(group.lower(), ()))
    return list(dict.fromkeys(pool))


def _user_prompt(idea: ContentIdea, brand: Brand, content: ContentConfig) -> str:
    tag_pool = ", ".join(_allowed_tags(brand, idea.audience)[:30])
    cta = brand.cta_text_bn or brand.cta_text
    requirements = (
        f"caption: {brand.caption.min_chars}-{brand.caption.max_chars} characters of Bangla, 1-3 sentences.\n"
        f"hashtags: {brand.caption.min_hashtags}-{brand.caption.max_hashtags} English tags, each starting with #, "
        f"must include {', '.join(brand.required_hashtags) or 'none'}. "
        f"Prefer tags from this pool: {tag_pool or 'none'}.\n"
        "image_headline: the Bangla title, or 2-6 Bangla words.\n"
        "image_subline: under 70 Bangla characters, a short takeaway.\n"
        "hook: the Bangla title."
    )
    return (
        f"Idea type: {idea.type}\n"
        f"Bangla title: {idea.display_title}\n"
        f"Bangla body: {idea.display_body}\n"
        f"Bangla takeaway: {idea.display_note}\n"
        f"End the caption with this Bangla CTA: {cta or 'none'}\n"
        f"Do not use these phrases: {', '.join(brand.banned_phrases) or 'none'}\n\n"
        f"{requirements}\n\n"
        'Return {"hook","caption","hashtags","image_headline","image_subline"}.'
    )


_SCHEMA = {
    "type": "object",
    "properties": {
        "hook": {"type": "string"},
        "caption": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "image_headline": {"type": "string"},
        "image_subline": {"type": "string"},
    },
    "required": ["hook", "caption", "hashtags", "image_headline", "image_subline"],
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
    audience: Sequence[str],
    rng: random.Random,
) -> tuple[str, ...]:
    limit = brand.caption.max_hashtags
    ordered: list[str] = []

    def add(tag: str) -> None:
        tag = tag.strip()
        if not re.fullmatch(r"#[A-Za-z0-9_]+", tag):
            return
        if tag.lower() in {item.lower() for item in ordered}:
            return
        if len(ordered) < limit:
            ordered.append(tag)

    for tag in brand.required_hashtags:
        add(tag)
    for tag in list(model_tags)[:3]:
        add(tag)
    for tag in _hashtags(brand, audience, rng):
        add(tag)
    for tag in list(model_tags)[3:]:
        add(tag)
    return tuple(ordered[:limit])


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[: max(limit - 1, 0)]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return (cut.rstrip(",;:।") + _terminator(text))[:limit]


def _post_process(data: dict[str, Any], idea: ContentIdea, brand: Brand) -> Draft:
    caption = str(data.get("caption", "")).strip()
    if not caption:
        raise WriterError("model returned an empty caption")

    if len(caption) > brand.caption.max_chars:
        LOG.warning("trimmed model caption from %d to %d chars", len(caption), brand.caption.max_chars)
        caption = _clip(caption, brand.caption.max_chars)

    raw_tags: Sequence[Any] = data.get("hashtags") or []
    model_tags = [str(raw).strip() for raw in raw_tags]
    tags = _merge_hashtags(
        model_tags,
        brand,
        idea.audience,
        random.Random(f"{caption}|{idea.id}"),
    )

    headline = str(data.get("image_headline", "")).strip().rstrip("।.!?")
    if not 2 <= len(headline) <= 60:
        headline = idea.display_title
    subline = str(data.get("image_subline", "")).strip() or idea.display_note
    subline = _clip(subline, 90)

    return Draft(
        hook=str(data.get("hook", "")).strip() or idea.display_title,
        caption=caption,
        hashtags=tuple(tags),
        image_headline=headline,
        image_subline=subline,
        product_ids=(),
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
    idea: ContentIdea,
    brand: Brand,
    content: ContentConfig,
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
        return build_from_idea(idea, brand, content, day)
    if not api_key:
        log.warning("writer: GEMINI_API_KEY is not set, falling back to templates")
        return build_from_idea(idea, brand, content, day)

    session = session or requests.Session()
    payload = {
        "systemInstruction": {"parts": [{"text": _system_prompt(brand)}]},
        "contents": [{"role": "user", "parts": [{"text": _user_prompt(idea, brand, content)}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 512,
            "responseMimeType": "application/json",
            "responseSchema": _SCHEMA,
        },
    }
    try:
        raw = _call_gemini(payload, api_key, model, session, base_url, timeout)
    except WriterUnavailable as exc:
        log.warning("writer: Gemini unavailable, using templates: %s", exc)
        fallback = build_from_idea(idea, brand, content, day)
        return replace(fallback, source="offline-fallback")
    data = _extract_json(raw)
    draft = _post_process(data, idea, brand)
    log.info("writer: gemini draft ready (%d chars, %d tags)", len(draft.caption), len(draft.hashtags))
    return draft