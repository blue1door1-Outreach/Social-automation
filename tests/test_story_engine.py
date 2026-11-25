from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from src import story_engine
from src.config import load_brand, load_catalog
from src.content import load_content
from src.main import _due_at_from_local
from src.validator import _bangla_words, errors, validate_draft
from src.writer import build_from_idea

ROOT = Path(__file__).resolve().parent.parent


def _topics():
    return story_engine.load_topics(ROOT / "config" / "story_topics.json")


def test_topics_cover_every_weekday_with_choices() -> None:
    topics = _topics()
    assert len(topics) >= 21
    per_weekday: dict[str, int] = {}
    for topic in topics:
        per_weekday[topic.weekday] = per_weekday.get(topic.weekday, 0) + 1
    for weekday in (
        "saturday",
        "sunday",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
    ):
        assert per_weekday.get(weekday, 0) >= 3, weekday


def test_topic_rotation_does_not_repeat_for_three_weeks() -> None:
    topics = _topics()
    history: list[dict[str, str]] = []
    day = date(2026, 11, 27)
    seen: list[str] = []
    for _ in range(21):
        topic = story_engine.choose_topic(
            topics, day, history=history, weather_tags=("fog", "cold"), season="winter"
        )
        seen.append(topic.id)
        history.append(
            {"date": day.isoformat(), "id": topic.id, "category": topic.category}
        )
        day += timedelta(days=1)
    assert len(set(seen)) == len(seen)


def test_every_curated_fallback_validates_as_a_story() -> None:
    content = load_content(ROOT / "config" / "content.json")
    brand = load_brand(ROOT / "config" / "brand.json")
    catalog = load_catalog(ROOT / "config" / "products.json")
    ideas = story_engine._fallback_ideas(
        content.ideas, ROOT / "config" / "story_fallbacks.json"
    )
    assert len(ideas) >= 7
    for idea in ideas:
        draft = build_from_idea(idea, brand, content, date(2026, 11, 27))
        assert draft.format == "story", idea.id
        assert 180 <= len(_bangla_words(draft.caption)) <= 300, idea.id
        assert errors(validate_draft(draft, brand, catalog)) == [], idea.id


def test_offline_daily_story_uses_a_curated_fallback() -> None:
    content = load_content(ROOT / "config" / "content.json")
    brand = load_brand(ROOT / "config" / "brand.json")
    result = story_engine.build_daily_story(
        topics_path=ROOT / "config" / "story_topics.json",
        fallback_path=ROOT / "config" / "story_fallbacks.json",
        history_path=ROOT / "state" / "story_history.json",
        day=date(2026, 11, 30),
        brand=brand,
        content_stories=content.ideas,
        offline=True,
        api_key="",
    )
    assert result.source == "curated-story"
    assert result.idea.format == "story"
    assert result.idea.question_bn


def test_due_at_from_local_is_nine_am_dhaka(brand) -> None:
    when = _due_at_from_local(date(2030, 1, 15), "09:00", brand)
    assert when.endswith("T03:00:00Z")
    parsed = datetime.fromisoformat(when.replace("Z", "+00:00"))
    assert parsed.astimezone(timezone.utc).hour == 3
