"""Turn raw news signals into one safe, relevant topic.

Two filters matter: a topic must be about winter/clothing, and it must not
touch anything in the blocked list. When research produces nothing usable we
fall back to an approved evergreen topic instead of skipping the day.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Sequence

from .config import Catalog, FallbackTopic, Product, ResearchConfig
from .research import Signal

# Sentinel for signals with no publish date. It must be timezone-aware or
# sorting a mixed list (some dated, some not) raises TypeError.
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Topic:
    title: str
    link: str
    source: str
    score: int
    product_id: str | None = None
    is_fallback: bool = False


def _word_hit(text: str, keywords: Sequence[str]) -> str | None:
    lowered = text.lower()
    for keyword in keywords:
        if re.search(rf"\b{re.escape(keyword.lower())}\b", lowered):
            return keyword
    return None


def blocked_hit(text: str, keywords: Sequence[str]) -> str | None:
    return _word_hit(text, keywords)


def relevance_score(text: str, config: ResearchConfig) -> int:
    lowered = text.lower()
    hits = {
        keyword
        for keyword in config.relevance_keywords
        if re.search(rf"\b{re.escape(keyword.lower())}\b", lowered)
    }
    return min(len(hits) * 2, 20)


def clean_title(title: str) -> str:
    # Google News appends " - Publisher"; drop it when it is clearly a suffix.
    if " - " in title:
        head, tail = title.rsplit(" - ", 1)
        if 0 < len(tail) <= 40 and len(head) >= 20:
            return head.strip()
    return title.strip()


def _match_product(text: str, catalog: Catalog) -> Product | None:
    for product in catalog.enabled():
        for keyword in product.keywords:
            if re.search(rf"\b{re.escape(keyword.lower())}\b", text.lower()):
                return product
    return None


def fallback_topic(config: ResearchConfig, catalog: Catalog, day: date) -> Topic | None:
    if not config.fallback_topics:
        return None
    entry: FallbackTopic = config.fallback_topics[day.toordinal() % len(config.fallback_topics)]
    product = catalog.by_id(entry.product_id) if entry.product_id else None
    return Topic(
        title=entry.title,
        link="",
        source="approved fallback",
        score=0,
        product_id=product.id if product else None,
        is_fallback=True,
    )


def choose_topic(
    signals: Sequence[Signal],
    config: ResearchConfig,
    catalog: Catalog,
    day: date,
    log: Any = None,
) -> Topic | None:
    candidates: list[tuple[int, Signal, Product | None]] = []
    for signal in signals:
        text = f"{signal.title} {signal.summary}"
        if blocked_hit(text, config.blocked_keywords):
            continue
        score = relevance_score(text, config)
        if score < config.min_relevance_score:
            continue
        candidates.append((score, signal, _match_product(text, catalog)))

    if not candidates:
        if log:
            log.warning("no usable signal passed the filter; using an approved fallback topic")
        return fallback_topic(config, catalog, day)

    candidates.sort(
        key=lambda item: (
            item[0],
            item[1].published or _EPOCH,
        ),
        reverse=True,
    )
    score, signal, product = candidates[0]
    return Topic(
        title=clean_title(signal.title),
        link=signal.link,
        source=signal.source,
        score=score,
        product_id=product.id if product else None,
    )


def pick_product(topic: Topic, catalog: Catalog, day: date) -> Product | None:
    enabled = catalog.enabled()
    if not enabled:
        return None
    if topic.product_id:
        product = catalog.by_id(topic.product_id)
        if product and product.enabled:
            return product
    matched = _match_product(topic.title, catalog)
    if matched:
        return matched
    return enabled[day.toordinal() % len(enabled)]
