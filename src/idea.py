"""Turn today's situation into the one idea worth posting.

The situation is built from three signals, in order of weight:

1. **Weather** at posting time in Dhaka (Open-Meteo) - what the reader is
   physically feeling at 10:00.
2. **Season** from ``config/context.json`` - winter, hemanta or warm months.
3. **Trends** (optional) - niche, non-political, non-music signals that only
   *tint* the mood. They never decide the post on their own.

Everything degrades safely: no weather and no trends still yields a post from
the curated library, chosen as weather-agnostically as the season allows.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

import requests

from . import trends as trends_mod
from .config import Brand, ConfigError
from .content import ContentConfig, ContentIdea
from .weather import Weather, fetch as fetch_weather

LOG = logging.getLogger("khuje.idea")

MIN_SCORE = 1


@dataclass(frozen=True)
class Situation:
    day: date
    hour: int
    weekday: str
    season: str
    season_note_bn: str
    weather: Weather | None = None
    trend_titles: tuple[str, ...] = field(default=())
    trend_moods: tuple[str, ...] = field(default=())
    errors: tuple[str, ...] = field(default=())

    @property
    def weather_tags(self) -> tuple[str, ...]:
        return self.weather.tags if self.weather else ()

    def brief(self) -> str:
        """A short, plain-English brief the writer turns into Bangla."""
        parts = [f"{self.season} season in Dhaka", f"{self.weekday} at {self.hour:02d}:00"]
        if self.weather:
            parts.append(self.weather.summary)
        if self.trend_moods:
            parts.append("readers' mood right now: " + ", ".join(self.trend_moods))
        return "; ".join(parts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "day": self.day.isoformat(),
            "hour": self.hour,
            "weekday": self.weekday,
            "season": self.season,
            "weather": self.weather.as_dict() if self.weather else None,
            "trend_titles": list(self.trend_titles),
            "trend_moods": list(self.trend_moods),
            "brief": self.brief(),
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class Chosen:
    idea: ContentIdea
    concept: str
    score: int
    reason: str
    story: bool


def load_context(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}: invalid JSON ({exc})") from exc
    if not isinstance(data, dict) or "location" not in data:
        raise ConfigError(f"{path}: expected an object with a 'location'")
    return data


def season_for(day: date, cfg: Mapping[str, Any]) -> tuple[str, str]:
    for name, spec in (cfg.get("seasons") or {}).items():
        months = (spec or {}).get("months") or []
        if day.month in months:
            return str(name), str((spec or {}).get("note_bn", name))
    return "warm", "গরম"


def build_situation(
    cfg: Mapping[str, Any],
    day: date,
    *,
    session: requests.Session,
    offline: bool = False,
    log: logging.Logger | None = None,
    timeout: int = 15,
) -> Situation:
    log = log or LOG
    location = cfg.get("location") or {}
    hour = int(cfg.get("publish_hour_local", 10))
    season, season_note = season_for(day, cfg)
    errors: list[str] = []

    weather: Weather | None = None
    found: list[trends_mod.Trend] = []

    if not offline:
        weather = fetch_weather(
            float(location.get("latitude", 23.8103)),
            float(location.get("longitude", 90.4125)),
            day,
            hour,
            session,
            timeout=timeout,
        )
        if weather is None:
            errors.append("weather unavailable")
            log.warning("weather unavailable; continuing with season only")

        found, trend_errors = trends_mod.collect(cfg.get("trends") or {}, session, log=log, timeout=timeout)
        if trend_errors:
            errors.extend(f"trends: {err}" for err in trend_errors[:3])

    return Situation(
        day=day,
        hour=hour,
        weekday=day.strftime("%A"),
        season=season,
        season_note_bn=season_note,
        weather=weather,
        trend_titles=tuple(trend.title for trend in found),
        trend_moods=trends_mod.moods(found),
        errors=tuple(errors),
    )


def _score(idea: ContentIdea, situation: Situation, *, used: bool) -> tuple[int, list[str]]:
    score = 0
    why: list[str] = []

    if situation.season in idea.seasons:
        score += 3
        why.append(f"season:{situation.season}")

    overlap = set(idea.weather) & set(situation.weather_tags)
    if overlap:
        score += min(len(overlap) * 2, 6)
        why.append("weather:" + ",".join(sorted(overlap)))

    if situation.trend_moods and set(idea.tags) & set(situation.trend_moods):
        score += min(len(set(idea.tags) & set(situation.trend_moods)), 2)
        why.append("trend")

    if used:
        score -= 100
        why.append("recent")

    return score, why


def choose(
    content: ContentConfig,
    situation: Situation,
    *,
    used: Sequence[str] = (),
    log: logging.Logger | None = None,
) -> Chosen:
    log = log or LOG
    used_set = set(used)
    best: tuple[int, int, ContentIdea, list[str]] | None = None

    for position, idea in enumerate(content.ideas):
        score, why = _score(idea, situation, used=idea.id in used_set)
        # Tie-break: earlier in the library wins, rotated by the day so the
        # library is walked in a different order over time.
        rotated = (position - situation.day.toordinal()) % max(len(content.ideas), 1)
        key = (score, -rotated)
        if best is None or key > (best[0], best[1]):
            best = (score, -rotated, idea, why)

    if best is None:
        raise ConfigError("content library is empty")
    score, _, idea, why = best

    if score < MIN_SCORE:
        why = why or ["no signal; using the daily rotation"]

    concept = idea.concept or "comfort"
    reason = f"{situation.brief()} -> {idea.id} [{concept}] score {score} ({', '.join(why) or 'rotation'})"
    log.info("idea: %s", reason)
    return Chosen(idea=idea, concept=concept, score=score, reason=reason, story=bool(idea.hook_bn))
