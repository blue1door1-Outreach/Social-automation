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


def test_every_category_has_copy() -> None:
    from src.writer import DEFAULT_HOOKS, HOOKS, LINES

    _, catalog, _ = load_all(ROOT / "config")
    for product in catalog.enabled():
        assert product.category.lower() in HOOKS or DEFAULT_HOOKS
        assert product.category.lower() in LINES
