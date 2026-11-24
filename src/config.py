"""Typed loaders for the JSON files under config/.

Everything the writer is allowed to say comes from these files. If a field is
missing or malformed we fail loudly at startup instead of guessing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
REQUIRED_COLORS = ("primary", "secondary", "accent", "surface", "ink", "muted", "text")


class ConfigError(RuntimeError):
    """Raised when a config file is missing, unreadable or invalid."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"missing config file: {path}") from exc
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top level must be an object")
    return data


def _req(data: dict[str, Any], key: str, kind: type, where: str) -> Any:
    if key not in data:
        raise ConfigError(f"{where}: missing '{key}'")
    value = data[key]
    if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
        raise ConfigError(f"{where}: '{key}' must be {kind.__name__}")
    return value


def _str_list(data: dict[str, Any], key: str, where: str) -> tuple[str, ...]:
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{where}: '{key}' must be a list of strings")
    return tuple(v.strip() for v in value if v.strip())


@dataclass(frozen=True)
class CaptionRules:
    min_chars: int
    max_chars: int
    min_hashtags: int
    max_hashtags: int


@dataclass(frozen=True)
class Brand:
    name: str
    tagline: str
    description: str
    audience: str
    location: str
    language: str
    timezone: str
    publish_time_local: str
    verified: bool
    colors: dict[str, str]
    tone: str
    cta_text: str
    cta_url: str
    caption: CaptionRules
    price_policy: str
    stock_policy: str
    required_hashtags: tuple[str, ...]
    banned_phrases: tuple[str, ...]
    notes: tuple[str, ...]
    hashtag_pools: dict[str, tuple[str, ...]]

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def color(self, key: str, default: str) -> str:
        return self.colors.get(key, default)


@dataclass(frozen=True)
class Product:
    id: str
    name: str
    category: str
    description: str
    price: float | None
    stock: str
    enabled: bool
    keywords: tuple[str, ...]
    audience: tuple[str, ...] = ()


@dataclass(frozen=True)
class Catalog:
    niche: str
    season: str
    currency: str
    show_prices: bool
    verified: bool
    products: tuple[Product, ...]

    def enabled(self) -> tuple[Product, ...]:
        return tuple(p for p in self.products if p.enabled)

    def by_id(self, product_id: str) -> Product | None:
        for product in self.products:
            if product.id == product_id:
                return product
        return None


@dataclass(frozen=True)
class FallbackTopic:
    title: str
    product_id: str | None


@dataclass(frozen=True)
class ResearchConfig:
    queries: tuple[str, ...]
    feeds: tuple[str, ...]
    max_age_days: int
    max_signals: int
    min_relevance_score: int
    relevance_keywords: tuple[str, ...]
    blocked_keywords: tuple[str, ...]
    fallback_topics: tuple[FallbackTopic, ...]


def load_brand(path: Path) -> Brand:
    data = _read_json(path)
    where = path.name

    caption_raw = data.get("caption")
    if not isinstance(caption_raw, dict):
        raise ConfigError(f"{where}: 'caption' must be an object")
    rules = CaptionRules(
        min_chars=_req(caption_raw, "min_chars", int, f"{where}.caption"),
        max_chars=_req(caption_raw, "max_chars", int, f"{where}.caption"),
        min_hashtags=_req(caption_raw, "min_hashtags", int, f"{where}.caption"),
        max_hashtags=_req(caption_raw, "max_hashtags", int, f"{where}.caption"),
    )
    if not 0 < rules.min_chars <= rules.max_chars:
        raise ConfigError(f"{where}: caption min_chars must be > 0 and <= max_chars")
    if not 0 <= rules.min_hashtags <= rules.max_hashtags:
        raise ConfigError(f"{where}: caption hashtag bounds are invalid")

    colors_raw = data.get("colors")
    if not isinstance(colors_raw, dict):
        raise ConfigError(f"{where}: 'colors' must be an object")
    colors: dict[str, str] = {}
    for key in REQUIRED_COLORS:
        value = colors_raw.get(key)
        if not isinstance(value, str) or not HEX_COLOR.match(value):
            raise ConfigError(f"{where}: color '{key}' must be a #rrggbb string")
        colors[key] = value

    timezone = _req(data, "timezone", str, where)
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(f"{where}: unknown timezone '{timezone}'") from exc

    cta = data.get("cta") or {}
    if not isinstance(cta, dict):
        raise ConfigError(f"{where}: 'cta' must be an object")

    required_hashtags = _str_list(data, "required_hashtags", where)
    for tag in required_hashtags:
        if not tag.startswith("#"):
            raise ConfigError(f"{where}: required hashtag '{tag}' must start with #")

    hashtags_raw = data.get("hashtags") or {}
    if not isinstance(hashtags_raw, dict):
        raise ConfigError(f"{where}: 'hashtags' must be an object")
    hashtag_pools: dict[str, tuple[str, ...]] = {}
    for group, tags in hashtags_raw.items():
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise ConfigError(f"{where}: 'hashtags.{group}' must be a list of strings")
        cleaned: list[str] = []
        for tag in tags:
            tag = tag.strip()
            if not tag:
                continue
            if not tag.startswith("#") or " " in tag:
                raise ConfigError(f"{where}: hashtag {tag!r} must start with # and contain no spaces")
            cleaned.append(tag)
        hashtag_pools[str(group).lower()] = tuple(cleaned)
    if "winter" not in hashtag_pools:
        raise ConfigError(f"{where}: 'hashtags.winter' is required")

    return Brand(
        name=_req(data, "name", str, where),
        tagline=_req(data, "tagline", str, where),
        description=_req(data, "description", str, where),
        audience=_req(data, "audience", str, where),
        location=_req(data, "location", str, where),
        language=_req(data, "language", str, where),
        timezone=timezone,
        publish_time_local=_req(data, "publish_time_local", str, where),
        verified=bool(_req(data, "verified", bool, where)),
        colors=colors,
        tone=data.get("tone", "friendly"),
        cta_text=str(cta.get("text", "")).strip(),
        cta_url=str(cta.get("url", "")).strip(),
        caption=rules,
        price_policy=data.get("price_policy", "never"),
        stock_policy=data.get("stock_policy", "never"),
        required_hashtags=required_hashtags,
        banned_phrases=_str_list(data, "banned_phrases", where),
        notes=_str_list(data, "notes", where),
        hashtag_pools=hashtag_pools,
    )


def load_catalog(path: Path) -> Catalog:
    data = _read_json(path)
    where = path.name
    products_raw = data.get("products")
    if not isinstance(products_raw, list) or not products_raw:
        raise ConfigError(f"{where}: 'products' must be a non-empty list")

    products: list[Product] = []
    seen: set[str] = set()
    for index, item in enumerate(products_raw):
        label = f"{where}.products[{index}]"
        if not isinstance(item, dict):
            raise ConfigError(f"{label}: must be an object")
        product_id = _req(item, "id", str, label).strip()
        if not product_id:
            raise ConfigError(f"{label}: 'id' must not be empty")
        if product_id in seen:
            raise ConfigError(f"{label}: duplicate id '{product_id}'")
        seen.add(product_id)

        price = item.get("price")
        if price is not None and not isinstance(price, (int, float)):
            raise ConfigError(f"{label}: 'price' must be a number or null")

        products.append(
            Product(
                id=product_id,
                name=_req(item, "name", str, label).strip(),
                category=_req(item, "category", str, label).strip(),
                description=str(item.get("description", "")).strip(),
                price=float(price) if price is not None else None,
                stock=str(item.get("stock", "unknown")).strip(),
                enabled=bool(item.get("enabled", True)),
                keywords=_str_list(item, "keywords", label),
                audience=tuple(
                    group.lower() for group in _str_list(item, "audience", label)
                ),
            )
        )

    return Catalog(
        niche=_req(data, "niche", str, where),
        season=str(data.get("season", "")).strip(),
        currency=str(data.get("currency", "")).strip(),
        show_prices=bool(data.get("show_prices", False)),
        verified=bool(_req(data, "verified", bool, where)),
        products=tuple(products),
    )


def load_research(path: Path) -> ResearchConfig:
    data = _read_json(path)
    where = path.name

    fallback_raw = data.get("fallback_topics", [])
    if not isinstance(fallback_raw, list):
        raise ConfigError(f"{where}: 'fallback_topics' must be a list")
    fallback: list[FallbackTopic] = []
    for index, item in enumerate(fallback_raw):
        if not isinstance(item, dict) or not isinstance(item.get("title"), str):
            raise ConfigError(f"{where}.fallback_topics[{index}]: needs a 'title'")
        product_id = item.get("product_id")
        fallback.append(
            FallbackTopic(
                title=item["title"].strip(),
                product_id=str(product_id).strip() if product_id else None,
            )
        )

    return ResearchConfig(
        queries=_str_list(data, "queries", where),
        feeds=_str_list(data, "feeds", where),
        max_age_days=_req(data, "max_age_days", int, where),
        max_signals=_req(data, "max_signals", int, where),
        min_relevance_score=_req(data, "min_relevance_score", int, where),
        relevance_keywords=_str_list(data, "relevance_keywords", where),
        blocked_keywords=_str_list(data, "blocked_keywords", where),
        fallback_topics=tuple(fallback),
    )


def load_all(config_dir: Path) -> tuple[Brand, Catalog, ResearchConfig]:
    return (
        load_brand(config_dir / "brand.json"),
        load_catalog(config_dir / "products.json"),
        load_research(config_dir / "research.json"),
    )
