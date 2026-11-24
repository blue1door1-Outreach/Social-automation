from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from src import writer as writer_module
from src.config import Brand, Catalog, Product
from src.topic_filter import Topic
from src.writer import Draft, _extract_json, _post_process, build_offline, generate


def test_offline_is_deterministic(brand: Brand, puffer: Product) -> None:
    topic = Topic(title="Cold mornings", link="", source="test", score=4)
    first = build_offline(topic, puffer, brand, date(2026, 11, 23))
    second = build_offline(topic, puffer, brand, date(2026, 11, 23))
    assert first == second
    assert first.source == "offline"


def test_offline_uses_only_config_facts(brand: Brand, puffer: Product) -> None:
    topic = Topic(title="Cold mornings", link="", source="test", score=4)
    draft = build_offline(topic, puffer, brand, date(2026, 11, 23))
    assert puffer.name in draft.caption
    assert brand.name in draft.caption
    assert brand.cta_text in draft.caption
    assert not any(char.isdigit() for char in draft.caption)
    assert "discount" not in draft.caption.lower()
    assert brand.required_hashtags[0] in draft.hashtags


def test_offline_without_product(brand: Brand) -> None:
    topic = Topic(title="General winter", link="", source="test", score=2)
    draft = build_offline(topic, None, brand, date(2026, 11, 23))
    assert draft.product_ids == ()
    assert "Winter basics" in draft.caption


def test_hashtags_mix_audience_winter_and_local(brand: Brand, puffer: Product) -> None:
    topic = Topic(title="Cold mornings", link="", source="test", score=4)
    draft = build_offline(topic, puffer, brand, date(2026, 11, 23))
    tags = set(draft.hashtags)
    assert 5 <= len(tags) <= brand.caption.max_hashtags
    assert brand.required_hashtags[0] in tags
    assert tags & set(brand.hashtag_pools["winter"])
    assert tags & set(brand.hashtag_pools["local"])
    assert tags & set(brand.hashtag_pools["kids"] + brand.hashtag_pools["men"] + brand.hashtag_pools["women"])
    assert len(tags) == len(draft.hashtags)


def test_generate_without_key_falls_back(brand: Brand, catalog: Catalog, puffer: Product) -> None:
    topic = Topic(title="Cold mornings", link="", source="test", score=4)
    draft = generate(topic, puffer, brand, catalog, date(2026, 11, 23), api_key="")
    assert draft.source == "offline"


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
    brand: Brand, catalog: Catalog, puffer: Product, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(writer_module.time, "sleep", lambda seconds: None)
    topic = Topic(title="Cold mornings", link="", source="test", score=4)
    draft = generate(
        topic,
        puffer,
        brand,
        catalog,
        date(2026, 11, 23),
        api_key="key",
        session=_Session(503, "high demand"),  # type: ignore[arg-type]
    )
    assert draft.source == "offline-fallback"
    assert puffer.name in draft.caption


def test_retired_model_is_a_hard_error(
    brand: Brand, catalog: Catalog, puffer: Product, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(writer_module.time, "sleep", lambda seconds: None)
    topic = Topic(title="Cold mornings", link="", source="test", score=4)
    with pytest.raises(writer_module.WriterError):
        generate(
            topic,
            puffer,
            brand,
            catalog,
            date(2026, 11, 23),
            api_key="key",
            session=_Session(404, "model retired"),  # type: ignore[arg-type]
        )


def test_extract_json_handles_code_fences() -> None:
    payload = '```json\n{"caption": "hello"}\n```'
    assert _extract_json(payload) == {"caption": "hello"}


def test_post_process_adds_required_tag_and_caps(brand: Brand, puffer: Product) -> None:
    topic = Topic(title="Cold mornings", link="", source="test", score=4)
    data = {
        "hook": "Winter is here",
        "caption": "A cold morning deserves a proper jacket, and this one is ready for the commute.",
        "hashtags": [f"#Tag{index}" for index in range(12)],
        "image_headline": "The daily puffer",
        "image_subline": "Winter essentials",
        "product_ids": [],
    }
    draft = _post_process(data, topic, puffer, brand)
    assert isinstance(draft, Draft)
    assert len(draft.hashtags) <= brand.caption.max_hashtags
    assert draft.hashtags[0] == "#KhujeNao"
    assert draft.product_ids == (puffer.id,)


def test_post_process_trims_overlong_caption(brand: Brand, puffer: Product) -> None:
    topic = Topic(title="Cold mornings", link="", source="test", score=4)
    long_text = ("This is a sentence about winter layering. " * 20).strip()
    data = {
        "hook": "Winter",
        "caption": long_text,
        "hashtags": ["#KhujeNao", "#Dhaka", "#Winter"],
        "image_headline": "Layer up",
        "image_subline": "Winter",
        "product_ids": [puffer.id],
    }
    draft = _post_process(data, topic, puffer, brand)
    assert len(draft.caption) <= brand.caption.max_chars
    assert draft.caption.endswith(".")
