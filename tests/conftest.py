from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import (  # noqa: E402
    Brand,
    CaptionRules,
    Catalog,
    FallbackTopic,
    Product,
    ResearchConfig,
)

COLORS = {
    "primary": "#0B2239",
    "secondary": "#1F4E6B",
    "accent": "#CFE6F2",
    "surface": "#F8FBFD",
    "ink": "#0B2239",
    "muted": "#5A7382",
    "text": "#FFFFFF",
}


@pytest.fixture
def brand() -> Brand:
    return Brand(
        name="Khuje Nao",
        tagline="Winter essentials, found for you.",
        description="An online shop in Bangladesh.",
        audience="Adults in Bangladesh",
        location="Dhaka, Bangladesh",
        language="en",
        timezone="Asia/Dhaka",
        publish_time_local="10:00",
        verified=False,
        colors=COLORS,
        tone="warm, practical",
        cta_text="Order via inbox",
        cta_url="",
        caption=CaptionRules(80, 320, 5, 10),
        price_policy="never",
        stock_policy="never",
        required_hashtags=("#KhujeNao",),
        banned_phrases=("discount", "sale", "% off"),
        notes=(),
        hashtag_pools={
            "local": ("#Dhaka", "#Bangladesh", "#DhakaFashion"),
            "winter": (
                "#WinterWear",
                "#WinterFashion",
                "#WinterStyle",
                "#Layering",
                "#ColdWeather",
                "#StayWarm",
            ),
            "kids": ("#KidsFashion", "#KidsWinterWear", "#KidsStyle"),
            "men": ("#MensFashion", "#MensStyle", "#MensWinterWear"),
            "women": ("#WomensFashion", "#WomensStyle", "#WomensWinterWear"),
        },
    )


@pytest.fixture
def puffer() -> Product:
    return Product(
        id="puffer-jacket",
        name="Quilted puffer jacket",
        category="outerwear",
        description="Quilted outer layer.",
        price=None,
        stock="unknown",
        enabled=True,
        keywords=("puffer", "jacket"),
        audience=("kids", "men", "women"),
    )


@pytest.fixture
def scarf() -> Product:
    return Product(
        id="woven-scarf",
        name="Long woven scarf",
        category="accessories",
        description="Long woven scarf.",
        price=None,
        stock="unknown",
        enabled=True,
        keywords=("scarf", "muffler"),
        audience=("men", "women"),
    )


@pytest.fixture
def catalog(puffer: Product, scarf: Product) -> Catalog:
    return Catalog(
        niche="winter clothing and cold-weather basics",
        season="November to February",
        currency="BDT",
        show_prices=False,
        verified=False,
        products=(puffer, scarf),
    )


@pytest.fixture
def research_config() -> ResearchConfig:
    return ResearchConfig(
        queries=("winter clothing Bangladesh",),
        feeds=(),
        max_age_days=10,
        max_signals=20,
        min_relevance_score=2,
        relevance_keywords=("winter", "cold", "jacket", "scarf"),
        blocked_keywords=("election", "killed", "war"),
        fallback_topics=(
            FallbackTopic("Layering for cool Dhaka mornings", "puffer-jacket"),
            FallbackTopic("Keep the evening chill off", "woven-scarf"),
        ),
    )
