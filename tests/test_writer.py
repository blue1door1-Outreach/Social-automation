from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from src import writer as writer_module
from src.config import Brand
from src.content import ContentConfig, ContentIdea
from src.writer import Draft, _extract_json, _post_process, build_from_idea, generate


def test_build_from_idea_is_deterministic(
    idea: ContentIdea, brand: Brand, content: ContentConfig
) -> None:
    first = build_from_idea(idea, brand, content, date(2026, 11, 23))
    second = build_from_idea(idea, brand, content, date(2026, 11, 23))
    assert first == second
    assert first.source == "offline"


def test_build_from_idea_uses_only_the_idea(
    idea: ContentIdea, brand: Brand, content: ContentConfig
) -> None:
    draft = build_from_idea(idea, brand, content, date(2026, 11, 23))
    assert idea.display_title in draft.caption
    assert idea.display_body in draft.caption
    assert brand.cta_text_bn in draft.caption
    assert idea.display_note == draft.image_subline
    assert draft.image_headline == idea.display_title
    assert draft.product_ids == ()
    assert brand.required_hashtags[0] in draft.hashtags
    assert 5 <= len(draft.hashtags) <= brand.caption.max_hashtags
    assert not any(char.isdigit() for char in draft.caption)


def test_generate_without_key_falls_back(
    idea: ContentIdea, brand: Brand, content: ContentConfig
) -> None:
    draft = generate(idea, brand, content, date(2026, 11, 23), api_key="")
    assert draft.source == "offline"


def _real_story():
    from pathlib import Path

    from src.config import load_brand
    from src.content import load_content

    root = Path(__file__).resolve().parent.parent
    content = load_content(root / "config" / "content.json")
    brand = load_brand(root / "config" / "brand.json")
    idea = content.by_id("folded-sweater-in-wardrobe")
    assert idea is not None
    return brand, content, idea


def test_long_story_builds_title_paragraphs_and_question() -> None:
    from src.validator import _bangla_words

    brand, content, idea = _real_story()
    draft = build_from_idea(idea, brand, content, date(2026, 11, 26))

    assert idea.is_long_story
    assert draft.format == "story"
    assert draft.caption.splitlines()[0] == idea.display_title
    paragraphs = [part for part in draft.caption.split("\n\n") if part.strip()]
    assert 10 <= len(paragraphs) <= 22
    assert draft.caption.rstrip().endswith("?")
    assert 180 <= len(_bangla_words(draft.caption)) <= 300
    assert brand.cta_text_bn not in draft.caption


def test_long_story_skips_the_model() -> None:
    brand, content, idea = _real_story()
    draft = generate(idea, brand, content, date(2026, 11, 26), api_key="not-used")
    assert draft.source == "curated"
    assert draft.format == "story"


def test_extract_json_handles_code_fences() -> None:
    payload = '```json\n{"caption": "hello"}\n```'
    assert _extract_json(payload) == {"caption": "hello"}


def test_post_process_caps_tags_and_ignores_products(
    idea: ContentIdea, brand: Brand
) -> None:
    data = {
        "hook": "Winter is here",
        "caption": "A cold morning deserves a light layer, and this one is easy to remove later.",
        "hashtags": [f"#Tag{index}" for index in range(12)],
        "image_headline": "A daily winter tip",
        "image_subline": "Layer light, stay warm.",
        "product_ids": ["puffer-jacket"],
    }
    draft = _post_process(data, idea, brand)
    assert isinstance(draft, Draft)
    assert len(draft.hashtags) <= brand.caption.max_hashtags
    assert draft.hashtags[0] == "#KhujeNao"
    assert draft.product_ids == ()


def test_post_process_falls_back_to_idea_copy(
    idea: ContentIdea, brand: Brand
) -> None:
    data = {
        "hook": "",
        "caption": "Layer light for the morning and remove one layer when the sun comes out.",
        "hashtags": ["#KhujeNao", "#Dhaka", "#Winter"],
        "image_headline": "x" * 80,
        "image_subline": "y" * 120,
        "product_ids": [],
    }
    draft = _post_process(data, idea, brand)
    assert draft.image_headline == idea.display_title
    assert len(draft.image_subline) <= 90


def test_post_process_trims_overlong_caption(
    idea: ContentIdea, brand: Brand
) -> None:
    long_text = ("This is a sentence about winter layering. " * 20).strip()
    data = {
        "hook": idea.title,
        "caption": long_text,
        "hashtags": ["#KhujeNao", "#Dhaka", "#Winter"],
        "image_headline": idea.title,
        "image_subline": idea.note,
        "product_ids": [],
    }
    draft = _post_process(data, idea, brand)
    assert len(draft.caption) <= brand.caption.max_chars
    assert draft.caption.endswith(".")


class _Response:
    def __init__(self, status: int, text: str):
        self.status_code = status
        self.text = text

    def json(self):
        return {}


class _Session:
    def __init__(self, status: int, text: str):
        self.status = status
        self.text = text

    def post(self, *args, **kwargs):
        return _Response(self.status, self.text)


def test_transient_gemini_failure_falls_back_to_templates(
    idea: ContentIdea,
    brand: Brand,
    content: ContentConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(writer_module.time, "sleep", lambda seconds: None)
    draft = generate(
        idea,
        brand,
        content,
        date(2026, 11, 23),
        api_key="key",
        session=_Session(503, "high demand"),  # type: ignore[arg-type]
    )
    assert draft.source == "offline-fallback"
    assert idea.display_title in draft.caption


def test_retired_model_is_a_hard_error(
    idea: ContentIdea,
    brand: Brand,
    content: ContentConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(writer_module.time, "sleep", lambda seconds: None)
    with pytest.raises(writer_module.WriterError):
        generate(
            idea,
            brand,
            content,
            date(2026, 11, 23),
            api_key="key",
            session=_Session(404, "model retired"),  # type: ignore[arg-type]
        )