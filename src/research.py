"""Trend research from public RSS feeds.

Google News RSS is the primary source because it needs no key and no quota.
Everything is best-effort: a dead feed becomes an error string, never an
exception that kills the run. The caller decides whether a fallback topic is
acceptable.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import requests

from .config import ResearchConfig

GOOGLE_NEWS_URL = "https://news.google.com/rss/search"
USER_AGENT = "KhujeNaoAutomation/1.0 (daily social post research)"
ATOM = "{http://www.w3.org/2005/Atom}"


class ResearchError(RuntimeError):
    pass


@dataclass(frozen=True)
class Signal:
    title: str
    link: str
    source: str
    published: datetime | None
    summary: str = ""


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_rss(content: bytes, source: str) -> list[Signal]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ResearchError(f"invalid XML: {exc}") from exc

    signals: list[Signal] = []
    items = root.findall(".//item")
    if items:
        for item in items:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            if not title or not link:
                continue
            summary = (item.findtext("description") or "").strip()
            signals.append(
                Signal(
                    title=title,
                    link=link,
                    source=(item.findtext("source") or source).strip(),
                    published=_parse_date(item.findtext("pubDate")),
                    summary=summary,
                )
            )
        return signals

    for entry in root.findall(f".//{ATOM}entry"):
        title = (entry.findtext(f"{ATOM}title") or "").strip()
        link_el = entry.find(f"{ATOM}link")
        link = (link_el.get("href") if link_el is not None else "") or ""
        if not title or not link:
            continue
        signals.append(
            Signal(
                title=title,
                link=link,
                source=source,
                published=_parse_date(entry.findtext(f"{ATOM}published")),
                summary=(entry.findtext(f"{ATOM}summary") or "").strip(),
            )
        )
    return signals


def fetch_google_news(session: requests.Session, query: str, timeout: int = 20) -> list[Signal]:
    params = {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    response = session.get(GOOGLE_NEWS_URL, params=params, timeout=timeout)
    response.raise_for_status()
    return _parse_rss(response.content, f"Google News: {query}")


def fetch_feed(session: requests.Session, url: str, timeout: int = 20) -> list[Signal]:
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return _parse_rss(response.content, url)


def _age_days(signal: Signal, now: datetime) -> float | None:
    if signal.published is None:
        return None
    return (now - signal.published).total_seconds() / 86400


def collect(
    session: requests.Session,
    config: ResearchConfig,
    now: datetime | None = None,
    log: Any = None,
) -> tuple[list[Signal], list[str]]:
    now = now or datetime.now(timezone.utc)
    signals: list[Signal] = []
    errors: list[str] = []

    for query in config.queries:
        try:
            signals.extend(fetch_google_news(session, query))
        except (requests.RequestException, ResearchError) as exc:
            errors.append(f"google news '{query}': {exc}")
            if log:
                log.warning("research source failed: google news '%s': %s", query, exc)

    for url in config.feeds:
        try:
            signals.extend(fetch_feed(session, url))
        except (requests.RequestException, ResearchError) as exc:
            errors.append(f"feed {url}: {exc}")
            if log:
                log.warning("research source failed: %s: %s", url, exc)

    fresh: list[Signal] = []
    seen: set[str] = set()
    for signal in signals:
        age = _age_days(signal, now)
        if age is not None and age > config.max_age_days:
            continue
        key = signal.title.lower().strip()
        if key in seen:
            continue
        seen.add(key)
        fresh.append(signal)

    fresh.sort(key=lambda s: s.published or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return fresh[: config.max_signals], errors
