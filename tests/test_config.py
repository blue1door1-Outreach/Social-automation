from __future__ import annotations

from pathlib import Path

from src.config import load_all

ROOT = Path(__file__).resolve().parent.parent


def test_real_config_loads() -> None:
    brand, catalog, research = load_all(ROOT / "config")
    assert brand.name
    assert brand.verified is False
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


def test_content_rotation_covers_multiple_ideas() -> None:
    from datetime import date, timedelta

    from src.content import load_content, pick_idea

    content = load_content(ROOT / "config" / "content.json")
    start = date(2026, 11, 24)
    picked = {pick_idea(content, start + timedelta(days=offset)).id for offset in range(30)}
    assert len(picked) == 30
