from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src import research
from src.config import ResearchConfig

SAMPLE_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example</title>
    <item>
      <title>Winter jacket demand rises in Dhaka</title>
      <link>https://example.com/one</link>
      <pubDate>Mon, 23 Nov 2026 06:00:00 GMT</pubDate>
      <source>Example News</source>
    </item>
    <item>
      <title>Cold weather tips for the season</title>
      <link>https://example.com/two</link>
      <pubDate>Sun, 22 Nov 2026 06:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


def test_parse_rss_items() -> None:
    signals = research._parse_rss(SAMPLE_RSS, "unit")
    assert len(signals) == 2
    assert signals[0].title == "Winter jacket demand rises in Dhaka"
    assert signals[0].source == "Example News"
    assert signals[0].published is not None


def test_parse_rss_rejects_broken_xml() -> None:
    with pytest.raises(research.ResearchError):
        research._parse_rss(b"<rss><channel>", "unit")


def test_collect_filters_old_items(monkeypatch: pytest.MonkeyPatch, research_config: ResearchConfig) -> None:
    fresh = research.Signal(
        "Winter jacket demand rises",
        "https://example.com/fresh",
        "Example",
        datetime(2026, 11, 22, 6, 0, tzinfo=timezone.utc),
    )
    old = research.Signal(
        "Winter jacket demand from last month",
        "https://example.com/old",
        "Example",
        datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(research, "fetch_google_news", lambda session, query: [fresh, old])
    signals, errors = research.collect(
        session=object(),  # type: ignore[arg-type]
        config=research_config,
        now=datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc),
    )
    assert errors == []
    assert [item.title for item in signals] == ["Winter jacket demand rises"]


def test_collect_reports_failed_source(monkeypatch: pytest.MonkeyPatch, research_config: ResearchConfig) -> None:
    def boom(session, query):
        raise research.ResearchError("feed down")

    monkeypatch.setattr(research, "fetch_google_news", boom)
    signals, errors = research.collect(session=object(), config=research_config)  # type: ignore[arg-type]
    assert signals == []
    assert len(errors) == 1
    assert "feed down" in errors[0]


def test_collect_dedupes_titles(monkeypatch: pytest.MonkeyPatch, research_config: ResearchConfig) -> None:
    same = research.Signal(
        "Winter jacket demand rises",
        "https://example.com/a",
        "Example",
        datetime(2026, 11, 22, 6, 0, tzinfo=timezone.utc),
    )
    duplicate = research.Signal(
        "Winter jacket demand rises",
        "https://example.com/b",
        "Other",
        datetime(2026, 11, 22, 7, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(research, "fetch_google_news", lambda session, query: [same, duplicate])
    signals, _ = research.collect(session=object(), config=research_config)  # type: ignore[arg-type]
    assert len(signals) == 1
