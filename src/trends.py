"""Niche trend signals that only *tint* the mood of a post.

Two free sources, both best-effort:

* Google News RSS (already used by ``research.py``) for a few hand-picked,
  winter/clothing-shaped queries.
* Google's daily trending-searches RSS for Bangladesh. It is unofficial, so it
  may move or block us; a failure is recorded and ignored.

A signal never becomes a factual claim in a caption. It only nudges which
curated idea wins and how the hook is written. Everything political, religious,
tragic, musical or otherwise haram is filtered out before it can reach the
writer.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import requests

from . import research
from .topic_filter import clean_title

LOG = logging.getLogger("khuje.trends")

# Moods the writer understands. Each allow-keyword maps to at most one of these.
MOOD_MAP = {
    "fog": "foggy", "foggy": "foggy", "mist": "foggy", "dew": "foggy",
    "cold": "chilly", "chill": "chilly", "winter": "chilly", "weather": "chilly",
    "sweater": "cosy", "cardigan": "cosy", "hoodie": "cosy", "blanket": "cosy",
    "comfort": "cosy", "tea": "cosy",
    "jacket": "layering", "layering": "layering", "thermal": "layering",
    "scarf": "layering", "muffler": "layering", "shawl": "layering",
    "beanie": "layering", "gloves": "layering", "mittens": "layering", "socks": "layering",
    "denim": "style", "outfit": "style", "fashion": "style", "style": "style",
    "shop": "shopping", "shopping": "shopping", "clothing": "shopping",
    "school": "school",
}


@dataclass(frozen=True)
class Trend:
    title: str
    source: str
    url: str
    keywords: tuple[str, ...] = field(default=())

    @property
    def moods(self) -> tuple[str, ...]:
        found = [MOOD_MAP[key] for key in self.keywords if key in MOOD_MAP]
        return tuple(dict.fromkeys(found))


def _hits(text: str, keywords: Sequence[str]) -> list[str]:
    lowered = text.lower()
    found: list[str] = []
    for keyword in keywords:
        if re.search(rf"\b{re.escape(keyword.lower())}\b", lowered):
            found.append(keyword.lower())
    return found


def blocked(text: str, deny: Sequence[str]) -> str | None:
    """Return the offending keyword, or None when the text is clean."""
    for keyword in deny:
        if re.search(rf"\b{re.escape(str(keyword).lower())}\b", text.lower()):
            return str(keyword)
    return None


def keep(title: str, cfg: Mapping[str, Any]) -> tuple[str, ...] | None:
    """Keep a headline only if it is clean and niche-relevant."""
    text = title.strip()
    if len(text) < 6:
        return None
    if blocked(text, cfg.get("deny_keywords") or ()):
        return None
    hits = _hits(text, cfg.get("allow_keywords") or ())
    if not hits:
        return None
    return tuple(hits)


def collect(
    cfg: Mapping[str, Any],
    session: requests.Session,
    *,
    log: logging.Logger | None = None,
    timeout: int = 15,
) -> tuple[list[Trend], list[str]]:
    log = log or LOG
    if not cfg.get("enabled", True):
        return [], []

    trends: list[Trend] = []
    errors: list[str] = []
    seen: set[str] = set()

    for query in cfg.get("queries") or ():
        try:
            signals = research.fetch_google_news(session, str(query), timeout=timeout)
        except (requests.RequestException, research.ResearchError) as exc:
            errors.append(f"news '{query}': {exc}")
            continue
        for signal in signals:
            title = clean_title(signal.title)
            keywords = keep(title, cfg)
            if keywords is None or title.lower() in seen:
                continue
            seen.add(title.lower())
            trends.append(Trend(title=title, source=signal.source, url=signal.link, keywords=keywords))

    for url in cfg.get("feeds") or ():
        try:
            signals = research.fetch_feed(session, str(url), timeout=timeout)
        except (requests.RequestException, research.ResearchError) as exc:
            errors.append(f"feed {url}: {exc}")
            continue
        for signal in signals:
            title = signal.title.strip()
            keywords = keep(title, cfg)
            if keywords is None or title.lower() in seen:
                continue
            seen.add(title.lower())
            trends.append(Trend(title=title, source=signal.source or "trends", url=signal.link, keywords=keywords))

    limit = int(cfg.get("max", 8))
    if errors:
        log.info("trends: %d usable, %d source error(s)", len(trends), len(errors))
    return trends[:limit], errors


def moods(trends: Sequence[Trend]) -> tuple[str, ...]:
    found: list[str] = []
    for trend in trends:
        found.extend(trend.moods)
    return tuple(dict.fromkeys(found))
