"""Curated educational content for engagement-first posts.

The account is not a product catalogue here. Each day uses one idea from
``config/content.json``: a short style, care, kids or Dhaka-specific note that
a reader can save and use. Nothing in here is a price, stock or delivery claim.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

MAX_TITLE = 60
MAX_NOTE = 90


class ContentError(RuntimeError):
    pass


@dataclass(frozen=True)
class ContentIdea:
    id: str
    type: str
    title: str
    body: str
    note: str
    audience: tuple[str, ...]
    tags: tuple[str, ...]
    title_bn: str = ""
    body_bn: str = ""
    note_bn: str = ""
    concept: str = ""
    seasons: tuple[str, ...] = ()
    weather: tuple[str, ...] = ()
    hook_bn: str = ""
    story_bn: str = ""
    question_bn: str = ""
    format: str = ""
    emotion_bn: str = ""
    hashtags: tuple[str, ...] = ()

    @property
    def display_title(self) -> str:
        return self.title_bn or self.title

    @property
    def display_body(self) -> str:
        return self.body_bn or self.body

    @property
    def display_note(self) -> str:
        return self.note_bn or self.note

    @property
    def is_story(self) -> bool:
        return bool(self.hook_bn or self.story_bn)

    @property
    def is_long_story(self) -> bool:
        return self.format == "story" or len(self.story_bn.split()) >= 150


@dataclass(frozen=True)
class ContentConfig:
    kicker: str
    follow: str
    ideas: tuple[ContentIdea, ...]
    kicker_bn: str = ""
    follow_bn: str = ""
    follow_story_bn: str = ""

    def by_id(self, idea_id: str) -> ContentIdea | None:
        for idea in self.ideas:
            if idea.id == idea_id:
                return idea
        return None

    @property
    def display_kicker(self) -> str:
        return self.kicker_bn or self.kicker

    @property
    def display_follow(self) -> str:
        return self.follow_bn or self.follow

    @property
    def display_follow_story(self) -> str:
        return self.follow_story_bn or self.follow_bn or self.follow


TYPE_LABELS_BN = {
    "STYLE TIP": "স্টাইল টিপ",
    "LAYERING": "স্তরে স্তরে",
    "CARE": "পোশাকের যত্ন",
    "CHECKLIST": "চেকলিস্ট",
    "KIDS": "শিশুদের জন্য",
    "DHAKA NOTE": "ঢাকার নোট",
    "COLOUR": "রঙের খেলা",
    "COLOUR TIP": "রঙের খেলা",
    "STORY": "শীতের গল্প",
    "NOTE": "নোট",
}


def type_label_bn(idea_type: str) -> str:
    return TYPE_LABELS_BN.get(idea_type.strip().upper(), idea_type.strip().title())


def _read(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ContentError(f"missing content file: {path}") from exc
    except OSError as exc:
        raise ContentError(f"cannot read {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ContentError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ContentError(f"{path}: top level must be an object")
    return data


def load_content(path: Path) -> ContentConfig:
    data = _read(path)
    where = path.name

    kicker = str(data.get("kicker", "")).strip()
    follow = str(data.get("follow", "")).strip()
    if not kicker:
        raise ContentError(f"{where}: 'kicker' is required")
    kicker_bn = str(data.get("kicker_bn", "")).strip()
    follow_bn = str(data.get("follow_bn", "")).strip()
    follow_story_bn = str(data.get("follow_story_bn", "")).strip()

    raw_ideas = data.get("ideas")
    if not isinstance(raw_ideas, list) or not raw_ideas:
        raise ContentError(f"{where}: 'ideas' must be a non-empty list")

    ideas: list[ContentIdea] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_ideas):
        label = f"{where}.ideas[{index}]"
        if not isinstance(item, dict):
            raise ContentError(f"{label}: must be an object")

        idea_id = str(item.get("id", "")).strip()
        if not idea_id:
            raise ContentError(f"{label}: 'id' is required")
        if idea_id in seen:
            raise ContentError(f"{label}: duplicate id {idea_id!r}")
        seen.add(idea_id)

        title = str(item.get("title", "")).strip()
        body = str(item.get("body", "")).strip()
        note = str(item.get("note", "")).strip()
        if not title or not body:
            raise ContentError(f"{label}: 'title' and 'body' are required")
        if len(title) > MAX_TITLE:
            raise ContentError(f"{label}: title is longer than {MAX_TITLE} characters")
        if len(note) > MAX_NOTE:
            raise ContentError(f"{label}: note is longer than {MAX_NOTE} characters")

        title_bn = str(item.get("title_bn", "")).strip()
        body_bn = str(item.get("body_bn", "")).strip()
        note_bn = str(item.get("note_bn", "")).strip()
        bangla_fields = (title_bn, body_bn, note_bn)
        if any(bangla_fields) and not all(bangla_fields):
            raise ContentError(
                f"{label}: provide all of title_bn, body_bn, note_bn (or none of them)"
            )
        if title_bn and len(title_bn) > MAX_TITLE:
            raise ContentError(f"{label}: title_bn is longer than {MAX_TITLE} characters")
        if note_bn and len(note_bn) > MAX_NOTE:
            raise ContentError(f"{label}: note_bn is longer than {MAX_NOTE} characters")

        audience_raw = item.get("audience") or []
        tags_raw = item.get("tags") or []
        hashtags_raw = item.get("hashtags") or []
        if not isinstance(audience_raw, list) or not isinstance(tags_raw, list):
            raise ContentError(f"{label}: 'audience' and 'tags' must be lists")
        if not isinstance(hashtags_raw, list):
            raise ContentError(f"{label}: 'hashtags' must be a list")

        item_format = str(item.get("format", "")).strip().lower()
        if item_format == "story":
            if not item.get("hook_bn") or not item.get("story_bn"):
                raise ContentError(
                    f"{label}: a long story needs 'hook_bn' and 'story_bn'"
                )
            if not str(item.get("question_bn", "")).strip():
                raise ContentError(
                    f"{label}: a long story needs 'question_bn' to invite comments"
                )
            paragraphs = [
                part
                for part in re.split(r"\n\s*\n", str(item.get("story_bn", "")))
                if part.strip()
            ]
            if not 8 <= len(paragraphs) <= 20:
                raise ContentError(
                    f"{label}: a long story needs 8-20 short paragraphs, got {len(paragraphs)}"
                )

        ideas.append(
            ContentIdea(
                id=idea_id,
                type=str(item.get("type", "NOTE")).strip().upper(),
                title=title,
                body=body,
                note=note,
                audience=tuple(str(value).strip().lower() for value in audience_raw if str(value).strip()),
                tags=tuple(str(value).strip().lower() for value in tags_raw if str(value).strip()),
                title_bn=title_bn,
                body_bn=body_bn,
                note_bn=note_bn,
                concept=str(item.get("concept", "")).strip().lower(),
                seasons=tuple(
                    str(value).strip().lower()
                    for value in (item.get("seasons") or [])
                    if str(value).strip()
                ),
                weather=tuple(
                    str(value).strip().lower()
                    for value in (item.get("weather") or [])
                    if str(value).strip()
                ),
                hook_bn=str(item.get("hook_bn", "")).strip(),
                story_bn=str(item.get("story_bn", "")).strip(),
                question_bn=str(item.get("question_bn", "")).strip(),
                format=str(item.get("format", "")).strip().lower(),
                emotion_bn=str(item.get("emotion_bn", "")).strip(),
                hashtags=tuple(
                    str(value).strip()
                    for value in hashtags_raw
                    if str(value).strip()
                ),
            )
        )

    return ContentConfig(
        kicker=kicker,
        follow=follow,
        ideas=tuple(ideas),
        kicker_bn=kicker_bn,
        follow_bn=follow_bn,
        follow_story_bn=follow_story_bn,
    )


def pick_idea(config: ContentConfig, day: date) -> ContentIdea:
    """Deterministic rotation: the same day always gets the same idea."""
    return config.ideas[day.toordinal() % len(config.ideas)]