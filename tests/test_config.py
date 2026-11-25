from __future__ import annotations

from datetime import date
from pathlib import Path

from src.config import load_all

ROOT = Path(__file__).resolve().parent.parent


def test_real_config_loads() -> None:
    brand, catalog, research = load_all(ROOT / "config")
    assert brand.name
    assert brand.verified is True
    assert catalog.verified is False
    assert brand.hashtag_pools["winter"]
    assert brand.required_hashtags


def test_sweater_and_sweatshirt_are_separate_products() -> None:
    _, catalog, _ = load_all(ROOT / "config")
    ids = {product.id for product in catalog.products}
    assert {"sweater", "sweatshirt"} <= ids
    assert catalog.by_id("sweater").category == "knitwear"
    assert catalog.by_id("sweatshirt").category == "sweatshirt"


def test_products_never_claim_price_or_stock() -> None:
    _, catalog, _ = load_all(ROOT / "config")
    for product in catalog.products:
        assert product.price is None, product.id
        assert product.stock == "unknown", product.id
        assert product.audience, product.id
        assert product.keywords, product.id


def test_every_fallback_product_exists_and_is_enabled() -> None:
    _, catalog, research = load_all(ROOT / "config")
    for topic in research.fallback_topics:
        if topic.product_id:
            product = catalog.by_id(topic.product_id)
            assert product is not None, topic.title
            assert product.enabled, topic.title


def test_content_library_loads_and_is_usable() -> None:
    from src.content import MAX_NOTE, MAX_TITLE, load_content

    content = load_content(ROOT / "config" / "content.json")
    assert len(content.ideas) >= 30
    assert content.kicker
    assert content.kicker_bn and content.follow_bn
    ids = [idea.id for idea in content.ideas]
    assert len(ids) == len(set(ids))
    allowed = {"kids", "men", "women"}
    for idea in content.ideas:
        assert 2 <= len(idea.title) <= MAX_TITLE, idea.id
        assert idea.note and len(idea.note) <= MAX_NOTE, idea.id
        assert idea.body, idea.id
        assert idea.type, idea.id
        assert set(idea.audience) <= allowed, idea.id
        assert idea.tags, idea.id
        assert 2 <= len(idea.title_bn) <= MAX_TITLE, idea.id
        assert idea.body_bn, idea.id
        assert idea.note_bn and len(idea.note_bn) <= MAX_NOTE, idea.id
        assert idea.display_title == idea.title_bn, idea.id


def test_brand_carries_bangla_copy() -> None:
    brand, _, _ = load_all(ROOT / "config")
    assert brand.language == "bn"
    assert brand.cta_text_bn
    assert brand.location_bn
    assert any("\u0980" <= char <= "\u09ff" for char in brand.cta_text_bn)
    for phrase in ("কিনুন", "ডিসকাউন্ট", "স্টক"):
        assert phrase in brand.banned_phrases


def test_photos_are_fetched_not_stored() -> None:
    """The repo must not carry a photo library any more."""
    assert not (ROOT / "assets" / "photos").exists()
    assert not (ROOT / "src" / "photos.py").exists()


def test_context_config_loads() -> None:
    from src.idea import load_context, season_for

    cfg = load_context(ROOT / "config" / "context.json")
    assert cfg["location"]["latitude"]
    assert cfg["photos"]["queries"]
    assert cfg["trends"]["deny_keywords"]
    assert set(cfg["photos"]["queries"]) >= {"scarf", "knit", "kids", "care", "colour"}
    season, _ = season_for(date(2026, 12, 15), cfg)
    assert season == "winter"
    season, _ = season_for(date(2026, 6, 15), cfg)
    assert season == "warm"


def test_every_idea_has_a_concept_with_queries() -> None:
    from src.content import load_content
    from src.idea import load_context

    cfg = load_context(ROOT / "config" / "context.json")
    concepts = set(cfg["photos"]["queries"])
    content = load_content(ROOT / "config" / "content.json")
    for idea in content.ideas:
        assert idea.concept, idea.id
        assert idea.concept in concepts, f"{idea.id}: unknown concept {idea.concept}"
        assert idea.seasons, idea.id
        assert not (idea.hook_bn and not idea.story_bn), idea.id


def test_story_posts_carry_bangla_hook_and_story() -> None:
    from src.content import load_content

    content = load_content(ROOT / "config" / "content.json")
    stories = [idea for idea in content.ideas if idea.is_story]
    assert len(stories) >= 8
    for idea in stories:
        assert idea.hook_bn and idea.story_bn, idea.id
        assert any("\u0980" <= char <= "\u09ff" for char in idea.hook_bn), idea.id


def test_content_rotation_covers_multiple_ideas() -> None:
    from datetime import date, timedelta

    from src.content import load_content, pick_idea

    content = load_content(ROOT / "config" / "content.json")
    start = date(2026, 11, 24)
    picked = {pick_idea(content, start + timedelta(days=offset)).id for offset in range(30)}
    assert len(picked) == 30
