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
from src.content import ContentConfig, ContentIdea  # noqa: E402

COLORS = {
    "primary": "#594E38",
    "secondary": "#ADB7B3",
    "accent": "#E3CAA5",
    "surface": "#FFFBF9",
    "ink": "#594E38",
    "muted": "#7E7363",
    "text": "#FFFBF9",
}


@pytest.fixture
def brand() -> Brand:
    return Brand(
        name="Khuje Nao",
        tagline="Winter style notes for Dhaka.",
        description="An online shop sharing winter notes.",
        audience="Adults in Bangladesh",
        location="Dhaka, Bangladesh",
        language="bn",
        timezone="Asia/Dhaka",
        publish_time_local="10:00",
        verified=False,
        colors=COLORS,
        tone="warm, practical",
        cta_text="Save this for later",
        cta_url="",
        caption=CaptionRules(80, 620, 5, 10),
        price_policy="never",
        stock_policy="never",
        required_hashtags=("#KhujeNao",),
        banned_phrases=("discount", "sale", "% off", "buy now", "কিনুন", "ডিসকাউন্ট", "স্টক"),
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
        cta_text_bn="পরে পড়ার জন্য সেভ করুন",
        location_bn="ঢাকা",
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


@pytest.fixture
def idea() -> ContentIdea:
    return ContentIdea(
        id="layer-light",
        type="STYLE TIP",
        title="Layer light for Dhaka winter",
        body="Start with a tee, add a sweatshirt, finish with a light jacket.",
        note="Light layers beat one heavy coat here.",
        audience=("men", "women"),
        tags=("layering",),
        title_bn="ঢাকার শীতে হালকা স্তর",
        body_bn="একটি টি-শার্ট দিয়ে শুরু করুন, তার উপরে সুইটশার্ট, শেষে হালকা জ্যাকেট।",
        note_bn="একটি ভারী কোটের চেয়ে হালকা স্তর ভালো।",
        concept="knit",
        seasons=("winter", "hemanta"),
        weather=("cold", "chilly"),
        emotion_bn="স্বস্তি",
    )


@pytest.fixture
def story_idea(idea: ContentIdea) -> ContentIdea:
    from dataclasses import replace

    return replace(
        idea,
        id="foggy-commute",
        type="DHAKA NOTE",
        concept="weather",
        weather=("fog", "mist", "cold"),
        hook_bn="সকালে জানালা খুলে বোঝা যায়, আজ কুয়াশা শহরকে জড়িয়ে ধরেছে।",
        story_bn="রিকশায় বসে মনে হয় হাতটা যেন বরফ।",
    )


@pytest.fixture
def content(idea: ContentIdea) -> ContentConfig:
    return ContentConfig(
        kicker="WINTER STYLE NOTES",
        follow="Follow for more winter tips.",
        ideas=(idea,),
        kicker_bn="শীতের স্টাইল নোট",
        follow_bn="আরও শীতের টিপসের জন্য ফলো করুন।",
    )
