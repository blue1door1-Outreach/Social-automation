from __future__ import annotations

from datetime import date, datetime, timezone

from src.config import Catalog, ResearchConfig
from src.research import Signal
from src.topic_filter import choose_topic, clean_title, pick_product


def signal(title: str, published: datetime | None = None) -> Signal:
    return Signal(
        title=title,
        link="https://example.com/item",
        source="Example",
        published=published or datetime(2026, 11, 22, 6, 0, tzinfo=timezone.utc),
    )


def test_relevant_signal_wins(research_config: ResearchConfig, catalog: Catalog) -> None:
    signals = [
        signal("Winter jacket demand rises as cold weather arrives in Dhaka"),
        signal("Local football league continues this weekend"),
    ]
    topic = choose_topic(signals, research_config, catalog, date(2026, 11, 23))
    assert topic is not None
    assert "jacket" in topic.title.lower()
    assert not topic.is_fallback


def test_blocked_topic_falls_back(research_config: ResearchConfig, catalog: Catalog) -> None:
    signals = [signal("Election results and cold weather debate continue")]
    topic = choose_topic(signals, research_config, catalog, date(2026, 11, 23))
    assert topic is not None
    assert topic.is_fallback


def test_empty_signals_use_approved_fallback(
    research_config: ResearchConfig, catalog: Catalog
) -> None:
    topic = choose_topic([], research_config, catalog, date(2026, 11, 23))
    assert topic is not None
    assert topic.is_fallback
    assert topic.source == "approved fallback"


def test_fallback_rotates_by_date(research_config: ResearchConfig, catalog: Catalog) -> None:
    first = choose_topic([], research_config, catalog, date(2026, 11, 23))
    second = choose_topic([], research_config, catalog, date(2026, 11, 24))
    assert first is not None and second is not None
    assert first.title != second.title


def test_clean_title_strips_publisher_suffix() -> None:
    assert clean_title("Winter layers return to Dhaka - The Daily Star") == (
        "Winter layers return to Dhaka"
    )
    assert clean_title("Short - X") == "Short - X"


def test_pick_product_prefers_topic_hint(catalog: Catalog) -> None:
    from src.topic_filter import Topic

    topic = Topic(
        title="Anything at all",
        link="",
        source="test",
        score=0,
        product_id="woven-scarf",
    )
    product = pick_product(topic, catalog, date(2026, 11, 24))
    assert product is not None
    assert product.id == "woven-scarf"


def test_pick_product_matches_keywords(
    research_config: ResearchConfig, catalog: Catalog
) -> None:
    from src.topic_filter import Topic

    topic = Topic(title="A puffer for the commute", link="", source="test", score=4)
    product = pick_product(topic, catalog, date(2026, 11, 23))
    assert product is not None
    assert product.id == "puffer-jacket"


def test_undated_signal_mixes_with_dated_signal(
    research_config: ResearchConfig, catalog: Catalog
) -> None:
    """A signal without a pubDate must not crash the sort against a dated one."""
    from src.research import Signal

    undated = Signal(
        title="Winter jacket demand rises in Dhaka",
        link="https://example.com/undated",
        source="Example",
        published=None,
    )
    dated = Signal(
        title="Winter jacket demand rises in Dhaka again",
        link="https://example.com/dated",
        source="Example",
        published=datetime(2026, 11, 22, 6, 0, tzinfo=timezone.utc),
    )
    topic = choose_topic([undated, dated], research_config, catalog, date(2026, 11, 23))
    assert topic is not None
    assert not topic.is_fallback
    assert "jacket" in topic.title.lower()
