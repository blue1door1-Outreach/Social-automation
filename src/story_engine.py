"""Daily long-form Bangla story engine.

One story a day, never a repeat of the last weeks. Two sources:

* **Gemini** writes a fresh 7-step story from one curated topic seed. The seed
  fixes the category, character, emotion and photo concept, so the model cannot
  drift back to the same idea every day.
* **Curated fallbacks** are complete stories kept in the repo. They are used
  when the model is unavailable, rate-limited or returns something that fails
  the rules. A day is never empty because of an API hiccup.

Topic selection is weighted by weekday category, season and weather, and never
repeats a topic used in the last 45 days. The chosen story is recorded in
``state/story_history.json`` so the next days stay varied.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Sequence

import requests

from .config import Brand
from .content import ContentIdea
from . import validator
from .writer import (
    DEFAULT_MODEL,
    GEMINI_BASE,
    WriterError,
    WriterUnavailable,
    _call_gemini,
    _clip,
    _extract_json,
)

LOG = logging.getLogger("khuje.story")

HISTORY_DAYS = 45
BLOCKED_TITLE_DAYS = 60
MIN_WORDS = 180
MAX_WORDS = 300
MIN_PARAGRAPHS = 10
MAX_PARAGRAPHS = 18
MAX_TITLE = 60
MAX_SUBLINE = 90

LATIN_RE = re.compile(r"[A-Za-z]")


@dataclass(frozen=True)
class StoryTopic:
    id: str
    category: str
    weekday: str
    title_seed: str
    premise: str
    character: str
    desire: str
    obstacle: str
    emotion: str
    reveal: str
    ending: str
    audience: tuple[str, ...] = ()
    seasons: tuple[str, ...] = ()
    weather: tuple[str, ...] = ()
    concept: str = ""
    hashtags: tuple[str, ...] = ()

    def prompt_block(self) -> str:
        return (
            f"Topic seed: {self.title_seed}\n"
            f"Category: {self.category}\n"
            f"Character: {self.character}\n"
            f"Desire: {self.desire}\n"
            f"Obstacle: {self.obstacle}\n"
            f"Emotion to leave the reader with: {self.emotion}\n"
            f"Suggested reveal (change the details, keep the feeling): {self.reveal}\n"
            f"Suggested ending: {self.ending}\n"
            f"Setting hints: {self.premise}"
        )


@dataclass(frozen=True)
class StoryResult:
    idea: ContentIdea
    source: str
    reason: str
    topic_id: str
    category: str
    title: str

    def history_entry(self, day: date) -> dict[str, Any]:
        return {
            "date": day.isoformat(),
            "id": self.topic_id,
            "category": self.category,
            "title": self.title,
            "source": self.source,
        }


def _str_tuple(item: dict[str, Any], key: str) -> tuple[str, ...]:
    value = item.get(key) or []
    if not isinstance(value, list):
        return ()
    return tuple(str(part).strip() for part in value if str(part).strip())


def load_topics(path: Path) -> tuple[StoryTopic, ...]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    raw = data.get("topics") if isinstance(data, dict) else None
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{path}: 'topics' must be a non-empty list")
    topics: list[StoryTopic] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"{path}: topics[{index}] must be an object")
        topic_id = str(item.get("id", "")).strip()
        if not topic_id or topic_id in seen:
            raise ValueError(f"{path}: topics[{index}] has a missing or duplicate id")
        seen.add(topic_id)
        topics.append(
            StoryTopic(
                id=topic_id,
                category=str(item.get("category", "everyday")).strip().lower(),
                weekday=str(item.get("weekday", "")).strip().lower(),
                title_seed=str(item.get("title_seed", "")).strip(),
                premise=str(item.get("premise", "")).strip(),
                character=str(item.get("character", "")).strip(),
                desire=str(item.get("desire", "")).strip(),
                obstacle=str(item.get("obstacle", "")).strip(),
                emotion=str(item.get("emotion", "")).strip(),
                reveal=str(item.get("reveal", "")).strip(),
                ending=str(item.get("ending", "")).strip(),
                audience=_str_tuple(item, "audience"),
                seasons=_str_tuple(item, "seasons"),
                weather=_str_tuple(item, "weather"),
                concept=str(item.get("concept", "comfort")).strip().lower(),
                hashtags=_str_tuple(item, "hashtags"),
            )
        )
    return tuple(topics)


def load_history(path: Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, dict):
        entries = data.get("entries")
    else:
        entries = data
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def save_history(path: Path, entries: Sequence[dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"entries": list(entries)[-400:]}
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def recent_ids(history: Sequence[dict[str, Any]], day: date, days: int) -> set[str]:
    cutoff = day - timedelta(days=days)
    used: set[str] = set()
    for entry in history:
        try:
            when = date.fromisoformat(str(entry.get("date", "")))
        except ValueError:
            continue
        if when >= cutoff:
            used.add(str(entry.get("id", "")))
    return used


def recent_categories(history: Sequence[dict[str, Any]], day: date, days: int = 3) -> list[str]:
    cutoff = day - timedelta(days=days)
    found: list[tuple[date, str]] = []
    for entry in history:
        try:
            when = date.fromisoformat(str(entry.get("date", "")))
        except ValueError:
            continue
        if when >= cutoff:
            found.append((when, str(entry.get("category", ""))))
    found.sort()
    return [category for _, category in found]


def recent_titles(history: Sequence[dict[str, Any]], day: date, days: int = BLOCKED_TITLE_DAYS) -> list[str]:
    cutoff = day - timedelta(days=days)
    titles: list[tuple[date, str]] = []
    for entry in history:
        try:
            when = date.fromisoformat(str(entry.get("date", "")))
        except ValueError:
            continue
        if when >= cutoff and entry.get("title"):
            titles.append((when, str(entry["title"])))
    titles.sort()
    return [title for _, title in titles][-10:]


def choose_topic(
    topics: Sequence[StoryTopic],
    day: date,
    *,
    history: Sequence[dict[str, Any]] = (),
    weather_tags: Sequence[str] = (),
    season: str = "",
) -> StoryTopic:
    used = recent_ids(history, day, HISTORY_DAYS)
    latest = recent_categories(history, day, 3)
    weekday = day.strftime("%A").lower()
    weather = set(weather_tags)

    best: tuple[float, int, StoryTopic] | None = None
    for position, topic in enumerate(topics):
        score = 0.0
        if topic.weekday and topic.weekday == weekday:
            score += 3
        if season and season in topic.seasons:
            score += 2
        overlap = weather & set(topic.weather)
        if overlap:
            score += min(len(overlap), 2)
        if topic.category and topic.category in latest:
            score -= 2
        if topic.id in used:
            score -= 100
        rotated = (position - day.toordinal()) % max(len(topics), 1)
        key = (score, -rotated)
        if best is None or key > (best[0], best[1]):
            best = (score, -rotated, topic)

    if best is None:
        raise ValueError("no story topics configured")
    return best[2]


def _bangla_only(text: str) -> bool:
    return not LATIN_RE.search(text)


def _word_count(text: str) -> int:
    return len(
        [
            word
            for word in text.split()
            if any("\u0980" <= char <= "\u09ff" for char in word)
        ]
    )


def _paragraphs(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", text.strip()) if part.strip()]


def _blocked(text: str, brand: Brand) -> str:
    lowered = text.lower()
    for phrase in (*brand.banned_phrases, *brand.story_banned_phrases):
        phrase = phrase.strip()
        if not phrase:
            continue
        if re.fullmatch(r"[a-z0-9 ]+", phrase):
            if re.search(rf"\b{re.escape(phrase)}\b", lowered):
                return f"banned phrase {phrase!r}"
        elif phrase in text:
            return f"banned phrase {phrase!r}"
    if validator.PRICE_RE.search(text):
        return "a price or pricing claim"
    if validator.STOCK_RE.search(text):
        return "a stock claim"
    return ""


def _validate_story(
    data: dict[str, Any],
    brand: Brand,
    recent: Sequence[str],
) -> tuple[dict[str, str] | None, str]:
    title = str(data.get("title", "")).strip().rstrip("।.!?")
    story = str(data.get("story", "")).strip()
    question = str(data.get("question", "")).strip()
    subline = str(data.get("image_subline", "")).strip()

    if not title or not story or not question:
        return None, "missing title, story or question"
    if LATIN_RE.search(title) or LATIN_RE.search(story) or LATIN_RE.search(question):
        return None, "contains English letters; write Bangla only"
    if len(title) > MAX_TITLE:
        return None, f"title is {len(title)} characters, over {MAX_TITLE}"
    normalized = re.sub(r"\s+", " ", title).strip().lower()
    if normalized in {re.sub(r"\s+", " ", item).strip().lower() for item in recent}:
        return None, "reuses a recent title"

    paragraphs = _paragraphs(story)
    if not MIN_PARAGRAPHS <= len(paragraphs) <= MAX_PARAGRAPHS:
        return None, (
            f"story has {len(paragraphs)} paragraphs, expected "
            f"{MIN_PARAGRAPHS}-{MAX_PARAGRAPHS} short ones"
        )
    words = _word_count(story)
    if not MIN_WORDS <= words <= MAX_WORDS:
        return None, f"story has {words} Bangla words, expected {MIN_WORDS}-{MAX_WORDS}"

    for label, text in (("story", story), ("question", question), ("image_subline", subline)):
        reason = _blocked(text, brand)
        if reason:
            return None, f"{label} contains {reason}"

    if not question.endswith("?"):
        return None, "the closing question must end with ?"
    if len(subline) > MAX_SUBLINE:
        subline = _clip(subline, MAX_SUBLINE)

    sentences = [part.strip().lower() for part in re.split(r"(?<=[।.!?])\s+", story) if part.strip()]
    if len(sentences) != len(set(sentences)):
        return None, "the story repeats a sentence"

    return (
        {
            "title": title,
            "story": story,
            "question": question,
            "image_subline": subline,
        },
        "",
    )


def _system_prompt(brand: Brand, recent: Sequence[str]) -> str:
    recent_line = (
        "Never reuse these recent titles or their openings: "
        + "; ".join(recent[:10])
        if recent
        else "There is no recent title to avoid yet."
    )
    return (
        "You are a senior Bangla creative story writer and Facebook storytelling "
        f"strategist. You write for {brand.name}, {brand.description} "
        f"Audience: {brand.audience}. Place: {brand.location}.\n"
        "Write an original, medium-length Bangla Facebook story, comfortable for "
        "a phone screen. Real human Bangla, natural dialogue, small live details.\n"
        "Follow the 7-step shape: a curiosity-driven title, a surprising first "
        "line, a relatable character in a familiar Bangladeshi setting, sensory "
        "atmosphere, a small problem, a slowly revealed reason, and a memorable "
        "ending that leaves warmth, peace, hope, nostalgia or quiet beauty.\n"
        "Hard rules:\n"
        "- Bangla only in every field. No English letters, no emojis.\n"
        "- Do not sell anything. No price, discount, stock, delivery or 'buy now'.\n"
        "- No politics, religion, music, film, celebrity, violence, death, "
        "accident, disaster or disease.\n"
        "- Family-friendly and halal-friendly. Never suggest a woman's photo.\n"
        "- Do not make every story sad. Avoid pity and preachy morals.\n"
        "- 180-300 Bangla words, 10-18 short paragraphs of 1-3 sentences.\n"
        "- One natural question at the end that invites a comment.\n"
        "- Output JSON only, matching the schema. No commentary, no code fences.\n"
        f"{recent_line}"
    )


def _user_prompt(topic: StoryTopic) -> str:
    return (
        f"{topic.prompt_block()}\n\n"
        "Return JSON with these keys:\n"
        '"title": the hook title, at most 60 Bangla characters, no full stop;\n'
        '"story": the full story as paragraphs separated by a blank line; the '
        "first paragraph is the opening hook; do not include the title again;\n"
        '"question": one closing question ending with ? that invites comments;\n'
        '"image_subline": a calm one-line takeaway under 90 Bangla characters.'
    )


_STORY_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "story": {"type": "string"},
        "question": {"type": "string"},
        "image_subline": {"type": "string"},
    },
    "required": ["title", "story", "question", "image_subline"],
}


def _idea_from_story(
    topic: StoryTopic,
    values: dict[str, str],
    *,
    source: str,
) -> ContentIdea:
    paragraphs = _paragraphs(values["story"])
    hook = paragraphs[0] if paragraphs else ""
    body = "\n\n".join(paragraphs[1:])
    return ContentIdea(
        id=f"story-{topic.id}",
        type="STORY",
        title=topic.title_seed,
        body=topic.premise,
        note=values["image_subline"],
        audience=topic.audience,
        tags=(topic.category,),
        title_bn=values["title"],
        body_bn=values["story"],
        note_bn=values["image_subline"],
        concept=topic.concept or "comfort",
        seasons=topic.seasons,
        weather=topic.weather,
        hook_bn=hook,
        story_bn=body,
        question_bn=values["question"],
        format="story",
        emotion_bn=topic.emotion,
        hashtags=topic.hashtags,
    )


def _model_chain(models: Sequence[str], model: str) -> list[str]:
    chain = [name.strip() for name in models if name and name.strip()]
    if model and model.strip() and model.strip() not in chain:
        chain.insert(0, model.strip())
    if not chain:
        chain = [DEFAULT_MODEL]
    return list(dict.fromkeys(chain))


def generate_with_model(
    topic: StoryTopic,
    brand: Brand,
    *,
    api_key: str,
    model: str = DEFAULT_MODEL,
    models: Sequence[str] = (),
    session: requests.Session | None = None,
    base_url: str = GEMINI_BASE,
    timeout: int = 45,
    recent: Sequence[str] = (),
    log: logging.Logger | None = None,
) -> ContentIdea | None:
    log = log or LOG
    if not api_key:
        return None
    session = session or requests.Session()

    for model_name in _model_chain(models, model):
        prompt = _user_prompt(topic)
        payload = {
            "systemInstruction": {"parts": [{"text": _system_prompt(brand, recent)}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.95,
                "maxOutputTokens": 6000,
                # Without this the model spends the budget "thinking" and the
                # JSON is cut off mid-story.
                "thinkingConfig": {"thinkingBudget": 0},
                "responseMimeType": "application/json",
                "responseSchema": _STORY_SCHEMA,
            },
        }
        for attempt in range(2):
            try:
                raw = _call_gemini(payload, api_key, model_name, session, base_url, timeout, attempts=2)
            except WriterUnavailable as exc:
                log.warning("story: %s unavailable: %s", model_name, exc)
                break
            except WriterError as exc:
                log.warning("story: %s rejected the request: %s", model_name, exc)
                break

            try:
                data = _extract_json(raw)
            except WriterError as exc:
                log.warning("story: invalid JSON: %s", exc)
                data = {}

            values, problem = _validate_story(data, brand, recent)
            if values is not None:
                log.info(
                    "story: %s wrote '%s' (%d words)",
                    model_name,
                    values["title"],
                    _word_count(values["story"]),
                )
                return _idea_from_story(topic, values, source="gemini-story")

            log.warning("story: %s attempt %d rejected: %s", model_name, attempt + 1, problem)
            if attempt == 0:
                payload["contents"][0]["parts"][0]["text"] = (
                    prompt + f"\n\nThe previous attempt was rejected: {problem}. Fix that and try again."
                )
    return None


def _fallback_ideas(
    content_stories: Sequence[ContentIdea],
    fallback_path: Path | None,
) -> tuple[ContentIdea, ...]:
    ideas: list[ContentIdea] = [idea for idea in content_stories if idea.is_long_story]
    if fallback_path and Path(fallback_path).exists():
        from .content import load_content

        # Reuse the same loader so the fallback file follows one shape.
        loaded = load_content(fallback_path)
        ideas.extend(idea for idea in loaded.ideas if idea.is_long_story)
    return tuple(ideas)


def choose_fallback(
    ideas: Sequence[ContentIdea],
    day: date,
    history: Sequence[dict[str, Any]],
) -> ContentIdea | None:
    if not ideas:
        return None
    used = recent_ids(history, day, 60)
    fresh = [idea for idea in ideas if idea.id not in used]
    pool = fresh or list(ideas)
    index = day.toordinal() % len(pool)
    return pool[index]


def build_daily_story(
    *,
    topics_path: Path,
    fallback_path: Path | None,
    history_path: Path,
    day: date,
    brand: Brand,
    content_stories: Sequence[ContentIdea] = (),
    season: str = "",
    weather_tags: Sequence[str] = (),
    offline: bool = False,
    api_key: str = "",
    model: str = DEFAULT_MODEL,
    models: Sequence[str] = (),
    session: requests.Session | None = None,
    timeout: int = 45,
    log: logging.Logger | None = None,
) -> StoryResult:
    log = log or LOG
    topics = load_topics(topics_path)
    history = load_history(history_path)
    recent = recent_titles(history, day)
    topic = choose_topic(
        topics,
        day,
        history=history,
        weather_tags=weather_tags,
        season=season,
    )
    log.info("story: topic -> %s [%s]", topic.id, topic.category)

    idea: ContentIdea | None = None
    source = "curated-story"
    if not offline and api_key:
        idea = generate_with_model(
            topic,
            brand,
            api_key=api_key,
            model=model,
            models=models,
            session=session,
            timeout=timeout,
            recent=recent,
            log=log,
        )
    if idea is None:
        fallback = choose_fallback(
            _fallback_ideas(content_stories, fallback_path), day, history
        )
        if fallback is None:
            raise ValueError("no curated fallback story is available")
        log.warning("story: using curated fallback %s", fallback.id)
        return StoryResult(
            idea=replace(fallback, format="story"),
            source="curated-story",
            reason=f"fallback after model unavailable; topic {topic.id}",
            topic_id=topic.id,
            category=topic.category,
            title=fallback.display_title,
        )

    return StoryResult(
        idea=idea,
        source="gemini-story",
        reason=f"model story from topic {topic.id} [{topic.category}]",
        topic_id=topic.id,
        category=topic.category,
        title=idea.display_title,
    )


def record(path: Path, result: StoryResult, day: date) -> None:
    history = load_history(path)
    history.append(result.history_entry(day))
    save_history(path, history)
