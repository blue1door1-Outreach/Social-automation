from __future__ import annotations

from dataclasses import replace
from datetime import date

from src import validator
from src.config import Brand, Catalog
from src.content import ContentConfig, ContentIdea
from src.validator import errors, utf16_units, validate_draft, warnings
from src.writer import build_from_idea


def codes(issues, severity: str | None = None) -> set[str]:
    return {issue.code for issue in issues if severity is None or issue.severity == severity}


def base_draft(brand: Brand, content: ContentConfig, idea: ContentIdea):
    return build_from_idea(idea, brand, content, date(2026, 11, 23))


def test_offline_draft_passes_validation(
    brand: Brand, catalog: Catalog, content: ContentConfig, idea: ContentIdea
) -> None:
    draft = base_draft(brand, content, idea)
    issues = validate_draft(draft, brand, catalog)
    assert errors(issues) == [], [issue.message for issue in issues]
    assert len(draft.caption) <= brand.caption.max_chars


def test_short_caption_is_rejected(
    brand: Brand, catalog: Catalog, content: ContentConfig, idea: ContentIdea
) -> None:
    draft = replace(base_draft(brand, content, idea), caption="Too short.")
    assert "caption_short" in codes(validate_draft(draft, brand, catalog), "error")


def test_long_caption_is_rejected(
    brand: Brand, catalog: Catalog, content: ContentConfig, idea: ContentIdea
) -> None:
    long_caption = ("A" * 120 + " ") * 4
    draft = replace(base_draft(brand, content, idea), caption=long_caption)
    assert "caption_long" in codes(validate_draft(draft, brand, catalog), "error")


def test_price_mention_is_rejected(
    brand: Brand, catalog: Catalog, content: ContentConfig, idea: ContentIdea
) -> None:
    caption = "Winter is here and the jacket is only 1200 taka this week, take a look today please."
    draft = replace(base_draft(brand, content, idea), caption=caption)
    assert "price_claim" in codes(validate_draft(draft, brand, catalog), "error")


def test_selling_phrase_is_rejected(
    brand: Brand, catalog: Catalog, content: ContentConfig, idea: ContentIdea
) -> None:
    caption = "A warm winter layer for the morning, buy now before the cold gets worse."
    draft = replace(base_draft(brand, content, idea), caption=caption)
    assert "banned_phrase" in codes(validate_draft(draft, brand, catalog), "error")


def test_stock_claim_is_rejected(
    brand: Brand, catalog: Catalog, content: ContentConfig, idea: ContentIdea
) -> None:
    caption = "The winter jacket is back in stock now, take a look this week."
    draft = replace(base_draft(brand, content, idea), caption=caption)
    assert "stock_claim" in codes(validate_draft(draft, brand, catalog), "error")


def test_missing_required_hashtag(
    brand: Brand, catalog: Catalog, content: ContentConfig, idea: ContentIdea
) -> None:
    draft = replace(
        base_draft(brand, content, idea),
        hashtags=("#WinterWear", "#Dhaka", "#Style"),
    )
    assert "hashtag_required" in codes(validate_draft(draft, brand, catalog), "error")


def test_too_many_hashtags(
    brand: Brand, catalog: Catalog, content: ContentConfig, idea: ContentIdea
) -> None:
    tags = tuple(f"#Tag{index}" for index in range(11))
    draft = replace(base_draft(brand, content, idea), hashtags=tags)
    assert "hashtag_count" in codes(validate_draft(draft, brand, catalog), "error")


def test_invalid_hashtag_format(
    brand: Brand, catalog: Catalog, content: ContentConfig, idea: ContentIdea
) -> None:
    draft = replace(
        base_draft(brand, content, idea),
        hashtags=("#KhujeNao", "#bad tag", "#Dhaka"),
    )
    assert "hashtag_format" in codes(validate_draft(draft, brand, catalog), "error")


def test_repeated_sentence_is_rejected(
    brand: Brand, catalog: Catalog, content: ContentConfig, idea: ContentIdea
) -> None:
    sentence = "Layer up for the cold morning commute today."
    draft = replace(
        base_draft(brand, content, idea),
        caption=f"{sentence} {sentence} {sentence}",
    )
    assert "repetition" in codes(validate_draft(draft, brand, catalog), "error")


def test_missing_cta_is_only_a_warning(
    brand: Brand, catalog: Catalog, content: ContentConfig, idea: ContentIdea
) -> None:
    base = base_draft(brand, content, idea)
    caption = base.caption
    for cta in (brand.cta_text_bn, brand.cta_text):
        caption = caption.replace(cta, "দেখে নিন।")
    issues = validate_draft(replace(base, caption=caption), brand, catalog)
    assert "cta_missing" in codes(issues, "warning")
    assert "cta_missing" not in codes(issues, "error")


def test_utf16_units_counts_newlines_and_astral_chars() -> None:
    assert utf16_units("abc") == 3
    assert utf16_units("a\nb") == 4
    assert utf16_units("🧥") == 2


def test_platform_limit_is_measured_in_utf16(
    brand: Brand,
    catalog: Catalog,
    content: ContentConfig,
    idea: ContentIdea,
    monkeypatch,
) -> None:
    monkeypatch.setattr(validator, "INSTAGRAM_CAPTION_LIMIT", 50)
    draft = base_draft(brand, content, idea)
    assert len(draft.full_text()) > 50
    assert "caption_platform_limit" in codes(validate_draft(draft, brand, catalog), "error")