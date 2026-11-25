"""Find, analyse and keep exactly one relevant photo - at run time.

No photo library is stored in the repository. For each post the fetcher:

1. asks Openverse (CC0 / public-domain only) for a handful of candidates whose
   query matches the idea's *concept*;
2. downloads them into the day's output folder (gitignored, discarded after
   publishing);
3. rejects anything unsafe or unusable: people/faces, tiny images, flat or
   corrupt files, extreme aspect ratios;
4. scores the survivors on concept fit, palette closeness and detail;
5. keeps the single best one, avoiding photos used in the last ``recency_days``.

If nothing passes, it returns ``None`` and the graphic falls back to the
text-only layout - a wrong picture is worse than no picture.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

import requests
from PIL import Image, ImageStat, UnidentifiedImageError

LOG = logging.getLogger("khuje.photo")

SEARCH_URL = "https://api.openverse.org/v1/images/"
LICENSE = "cc0,pdm"
USER_AGENT = "KhujeNaoAutomation/1.0 (daily social post photo pick)"


@dataclass(frozen=True)
class FetchedPhoto:
    photo_id: str
    path: Path
    concept: str
    credit: str
    source: str
    license: str
    score: float
    palette_distance: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.photo_id,
            "file": self.path.name,
            "concept": self.concept,
            "credit": self.credit,
            "source": self.source,
            "license": self.license,
            "score": round(self.score, 2),
            "palette_distance": round(self.palette_distance, 1),
        }


def _rgb(value: str) -> tuple[int, int, int]:
    text = value.lstrip("#")
    return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _palette_distance(image: Image.Image, chips: Sequence[str]) -> float:
    """Mean distance from the photo's average colour to the nearest brand chip."""
    stat = ImageStat.Stat(image.resize((32, 32)))
    mean = stat.mean[:3]
    best = None
    for chip in chips or ("#FFFBF9",):
        try:
            target = _rgb(str(chip))
        except (ValueError, IndexError):
            continue
        distance = sum((mean[i] - target[i]) ** 2 for i in range(3)) ** 0.5
        best = distance if best is None else min(best, distance)
    return float(best if best is not None else 255.0)


def _detail(image: Image.Image) -> float:
    """How much structure survives a downscale. Flat scans and blank files fail."""
    stat = ImageStat.Stat(image.convert("L").resize((128, 128)))
    return float(stat.stddev[0])


def inspect(
    payload: bytes,
    *,
    min_edge: int,
    chips: Sequence[str],
    min_short_edge: int = 560,
) -> tuple[Image.Image | None, float, float, str]:
    """Validate and score raw bytes. Returns (image, palette_distance, detail, reason).

    ``min_edge`` is the long edge, so a 1024x683 landscape still qualifies: the
    graphic crops it to a 1080x600 band with almost no upscaling.
    """
    try:
        image = Image.open(io.BytesIO(payload))
        image.load()
    except (UnidentifiedImageError, OSError, ValueError):
        return None, 0.0, 0.0, "undecodable"

    image = image.convert("RGB")
    width, height = image.size
    if max(width, height) < min_edge or min(width, height) < min_short_edge:
        return None, 0.0, 0.0, f"too small ({width}x{height})"
    if min(width, height) / max(width, height) < 0.34:
        return None, 0.0, 0.0, "extreme aspect ratio"

    detail = _detail(image)
    if detail < 8:
        return None, 0.0, 0.0, "flat or blank"

    distance = _palette_distance(image, chips)
    return image, distance, detail, ""


def _entry_text(entry: Mapping[str, Any]) -> str:
    bits: list[str] = [str(entry.get("title") or "")]
    for tag in entry.get("tags") or []:
        if isinstance(tag, dict):
            bits.append(str(tag.get("name") or ""))
        else:
            bits.append(str(tag))
    return " ".join(bits).lower()


def _has_word(text: str, word: str) -> bool:
    """Whole-word match so 'shirt' does not match 't-shirts' and 'man' not 'woman'."""
    return re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", text) is not None


def _looks_like_people(text: str, people_words: Sequence[str]) -> bool:
    return any(_has_word(text, word) for word in people_words)


def _looks_like_artefact(text: str, words: Sequence[str]) -> bool:
    return any(_has_word(text, word) for word in words)


def _matches_concept(text: str, concept: str, words: Mapping[str, Sequence[str]]) -> int:
    """How many concept words the entry's own metadata mentions."""
    expected = [str(word).lower() for word in words.get(concept) or ()]
    if not expected:
        return 1
    return sum(1 for word in expected if _has_word(text, word))


def _candidate_urls(entry: Mapping[str, Any]) -> list[str]:
    urls: list[str] = []
    for key in ("url", "thumbnail"):
        value = str(entry.get(key) or "").strip()
        if value and value not in urls:
            urls.append(value)
    return urls


def fetch(
    concept: str,
    queries: Mapping[str, Sequence[str]],
    dest_dir: Path,
    day: date,
    *,
    used: Sequence[str] = (),
    cfg: Mapping[str, Any] | None = None,
    session: requests.Session | None = None,
    log: logging.Logger | None = None,
    timeout: int = 20,
) -> FetchedPhoto | None:
    log = log or LOG
    cfg = cfg or {}
    session = session or requests.Session()
    session.headers.setdefault("User-Agent", USER_AGENT)

    concept_order = [concept]
    for extra in cfg.get("fallback_concepts") or ():
        extra = str(extra).strip().lower()
        if extra and extra != concept and extra not in concept_order and queries.get(extra):
            concept_order.append(extra)

    min_edge = int(cfg.get("min_edge", 1000))
    min_short_edge = int(cfg.get("min_short_edge", 560))
    max_downloads = int(cfg.get("max_downloads", 12))
    chips = list(cfg.get("chips") or [])
    people_words = [str(word).lower() for word in cfg.get("people_words") or []]
    artefact_words = [str(word).lower() for word in cfg.get("artefact_words") or []]
    concept_words = cfg.get("concept_words") or {}
    used_set = set(used)

    candidates: list[tuple[float, float, dict[str, Any], Image.Image]] = []
    downloaded = 0
    reviewed = 0
    max_reviewed = max(max_downloads * 3, 24)

    for active in concept_order:
        concept_queries = list(queries.get(active) or [])
        if not concept_queries:
            continue
        # Rotate which query runs first so the same concept yields variety over time.
        shift = day.toordinal() % len(concept_queries)
        ordered = concept_queries[shift:] + concept_queries[:shift]

        for query in ordered:
            try:
                response = session.get(
                    SEARCH_URL,
                    params={"q": query, "license": LICENSE, "page_size": 10, "mature": "false"},
                    timeout=timeout,
                )
                response.raise_for_status()
                results = response.json().get("results") or []
            except (requests.RequestException, ValueError) as exc:
                log.info("photo search failed for %r: %s", query, exc)
                continue

            for entry in results:
                if downloaded >= max_downloads or reviewed >= max_reviewed:
                    break
                text = _entry_text(entry)
                if not text.strip():
                    continue
                if _looks_like_people(text, people_words):
                    continue
                if _looks_like_artefact(text, artefact_words):
                    continue
                hits = _matches_concept(text, active, concept_words)
                if hits == 0:
                    log.info("photo skipped (off-concept): %s", entry.get("title"))
                    continue
                photo_id = str(entry.get("id") or "").strip()
                if photo_id and photo_id in used_set:
                    continue

                blob = None
                reviewed += 1
                for url in _candidate_urls(entry):
                    try:
                        asset = session.get(url, timeout=timeout)
                        asset.raise_for_status()
                        blob = asset.content
                        break
                    except requests.RequestException:
                        continue
                if not blob:
                    continue
                downloaded += 1

                image, distance, detail, reason = inspect(
                    blob, min_edge=min_edge, chips=chips, min_short_edge=min_short_edge
                )
                if image is None:
                    log.info("photo rejected (%s): %s", reason, entry.get("title"))
                    continue
                score = detail + max(0.0, 120.0 - distance) / 6.0 + 4.0 * hits
                candidates.append((score, distance, entry, image))
            if candidates:
                break
        if candidates:
            concept = active
            break

    if not candidates:
        log.warning("no usable photo for concept %r; falling back to text-only", concept)
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    top = candidates[: max(1, min(5, len(candidates)))]
    score, distance, entry, image = top[day.toordinal() % len(top)]

    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / "photo.jpg"
    image.save(path, format="JPEG", quality=88, optimize=True)

    title = str(entry.get("title") or "").strip()
    creator = str(entry.get("creator") or "").strip()
    licence = str(entry.get("license") or "").strip()
    credit = f"{title or 'Untitled'} - {creator or 'Unknown'} ({licence.upper()})"
    return FetchedPhoto(
        photo_id=str(entry.get("id") or title or path.name),
        path=path,
        concept=concept,
        credit=credit,
        source=str(entry.get("foreign_landing_url") or entry.get("url") or ""),
        license=licence,
        score=score,
        palette_distance=distance,
    )
