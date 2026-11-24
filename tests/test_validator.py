from __future__ import annotations

from dataclasses import replace
from datetime import date

from src import validator
from src.config import Brand, Catalog, Product
from src.topic_filter import Topic
from src.validator import errors, utf16_units, validate_draft, warnings
from src.writer import build_offline


def codes(issues, severity: str | None = None) -> set[str]:
    return {issue.code for issue in issues if severity is None or issue.severity == severity}


def test_offline_draft_passes_validation(brand: Brand, catalog: Catalog, puffer: Product) -> None:
    topic = Topic(title="Cold mornings in Dhaka", link="", source="test", score=4)
    draft = build_offline(topic, puffer, brand, date(2026, 11, 23))
    issues = validate_draft(draft, brand, catalog)
    assert errors(issues) == [], [issue.message for issue in issues]
    assert len(draft.caption) <= brand.caption.max_chars


def test_short_caption_is_rejected(brand: Brand, catalog: Catalog, puffer: Product) -> None:
    topic = Topic(title="x", link="", source="test", score=1)
    draft = replace(build_offline(topic, puffer, brand, date(2026, 11, 23)), caption="Too short.")
    assert "caption_short" in codes(validate_draft(draft, brand, catalog), "error")


def test_long_caption_is_rejected(brand: Brand, catalog: Catalog, puffer: Product) -> None:
    topic = Topic(title="x", link="", source="test", score=1)
    long_caption = ("A" * 120 + " ") * 4
    draft = replace(build_offline(topic, puffer, brand, date(2026, 11, 23)), caption=long_caption)
    assert "caption_long" in codes(validate_draft(draft, brand, catalog), "error")


def test_price_mention_is_rejected(brand: Brand, catalog: Catalog, puffer: Product) -> None:
    topic = Topic(title="x", link="", source="test", score=1)
    caption = "Winter is here and the jacket is only 1200 taka this week, order today please."
    draft = replace(build_offline(topic, puffer, brand, date(2026, 11, 23)), caption=caption)
    assert "price_claim" in codes(validate_draft(draft, brand, catalog), "error")


def test_banned_phrase_is_rejected(brand: Brand, catalog: Catalog, puffer: Product) -> None:
    topic = Topic(title="x", link="", source="test", score=1)
    caption = "A big discount on the winter jacket this week, order through our inbox today."
    draft = replace(build_offline(topic, puffer, brand, date(2026, 11, 23)), caption=caption)
    assert "banned_phrase" in codes(validate_draft(draft, brand, catalog), "error")


def test_stock_claim_is_rejected(brand: Brand, catalog: Catalog, puffer: Product) -> None:
    topic = Topic(title="x", link="", source="test", score=1)
    draft = replace(build_offline(topic, puffer, brand, date(2026, 11, 23)), caption="The winter jacket is back in stock now, order via inbox this week.")
    assert "stock_claim" in codes(validate_draft(draft, brand, catalog), "error")


def test_missing_required_hashtag(brand: Brand, catalog: Catalog, puffer: Product) -> None:
    topic = Topic(title="x", link="", source="test", score=1)
    draft = replace(
        build_offline(topic, puffer, brand, date(2026, 11, 23)),
        hashtags=("#WinterWear", "#Dhaka", "#Style"),
    )
    assert "hashtag_required" in codes(validate_draft(draft, brand, catalog), "error")


def test_too_many_hashtags(brand: Brand, catalog: Catalog, puffer: Product) -> None:
    topic = Topic(title="x", link="", source="test", score=1)
    tags = tuple(f"#Tag{index}" for index in range(11))
    draft = replace(build_offline(topic, puffer, brand, date(2026, 11, 23)), hashtags=tags)
    assert "hashtag_count" in codes(validate_draft(draft, brand, catalog), "error")


def test_utf16_units_counts_newlines_and_astral_chars() -> None:
    assert utf16_units("abc") == 3
    assert utf16_units("a\nb") == 4
    assert utf16_units("🧥") == 2


def test_platform_limit_is_measured_in_utf16(
    brand: Brand, catalog: Catalog, puffer: Product, monkeypatch
) -> None:
    monkeypatch.setattr(validator, "INSTAGRAM_CAPTION_LIMIT", 50)
    topic = Topic(title="x", link="", source="test", score=1)
    draft = build_offline(topic, puffer, brand, date(2026, 11, 23))
    assert len(draft.full_text()) > 50
    assert "caption_platform_limit" in codes(validate_draft(draft, brand, catalog), "error")


def test_invalid_hashtag_format(brand: Brand, catalog: Catalog, puffer: Product) -> None:
    topic = Topic(title="x", link="", source="test", score=1)
    draft = replace(
        build_offline(topic, puffer, brand, date(2026, 11, 23)),
        hashtags=("#KhujeNao", "#bad tag", "#Dhaka"),
    )
    assert "hashtag_format" in codes(validate_draft(draft, brand, catalog), "error")


def test_repeated_sentence_is_rejected(brand: Brand, catalog: Catalog, puffer: Product) -> None:
    topic = Topic(title="x", link="", source="test", score=1)
    sentence = "Layer up for the cold morning commute today."
    draft = replace(
        build_offline(topic, puffer, brand, date(2026, 11, 23)),
        caption=f"{sentence} {sentence} {sentence}",
    )
    assert "repetition" in codes(validate_draft(draft, brand, catalog), "error")


def test_missing_cta_is_only_a_warning(brand: Brand, catalog: Catalog, puffer: Product) -> None:
    topic = Topic(title="x", link="", source="test", score=1)
    draft = build_offline(topic, puffer, brand, date(2026, 11, 23))
    draft = replace(draft, caption=draft.caption.replace("Order via inbox.", "See the page."))
    issues = validate_draft(draft, brand, catalog)
    assert "cta_missing" in codes(issues, "warning")
    assert "cta_missing" not in codes(issues, "error")
