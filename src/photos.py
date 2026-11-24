"""Curated, no-people photos for the daily graphic.

Every image in ``assets/photos`` is a prepared stock photo whose licence is
recorded in ``assets/photos/credits.json``. The pictures are chosen deliberately
to contain no people at all: no faces, and therefore never a photo of a woman.

The post picks one photo per day by matching the idea's tags, deterministically,
so the same day always uses the same picture.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "assets" / "photos"


class PhotoError(RuntimeError):
    pass


@dataclass(frozen=True)
class Photo:
    id: str
    file: str
    path: Path
    tags: tuple[str, ...]
    title: str
    creator: str
    license: str
    license_url: str
    source: str
    no_people: bool = True

    def credit(self) -> str:
        who = self.creator or "Unknown"
        licence = self.license.upper() if self.license else "unknown licence"
        return f"{self.title or self.id} - {who} ({licence})"


@dataclass(frozen=True)
class PhotoLibrary:
    photos: tuple[Photo, ...]

    def by_id(self, photo_id: str) -> Photo | None:
        for photo in self.photos:
            if photo.id == photo_id:
                return photo
        return None


def load_photos(directory: Path | None = None) -> PhotoLibrary:
    directory = Path(directory) if directory else DEFAULT_DIR
    manifest = directory / "credits.json"
    if not manifest.exists():
        return PhotoLibrary(photos=())

    try:
        raw = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PhotoError(f"cannot read {manifest}: {exc}") from exc

    entries = raw.get("photos") if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        raise PhotoError(f"{manifest}: expected a 'photos' list")

    photos: list[Photo] = []
    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            raise PhotoError(f"{manifest}.photos[{index}]: must be an object")
        photo_id = str(item.get("id", "")).strip()
        filename = str(item.get("file", "")).strip()
        if not photo_id or not filename:
            raise PhotoError(f"{manifest}.photos[{index}]: 'id' and 'file' are required")
        path = directory / filename
        if not path.exists():
            raise PhotoError(f"{manifest}: image missing for {photo_id!r} ({path})")
        tags = item.get("tags") or []
        photos.append(
            Photo(
                id=photo_id,
                file=filename,
                path=path,
                tags=tuple(str(tag).strip().lower() for tag in tags if str(tag).strip()),
                title=str(item.get("title", "")).strip(),
                creator=str(item.get("creator", "")).strip(),
                license=str(item.get("license", "")).strip(),
                license_url=str(item.get("license_url", "")).strip(),
                source=str(item.get("source", "")).strip(),
                no_people=bool(item.get("no_people", True)),
            )
        )
    return PhotoLibrary(photos=tuple(photos))


def pick_photo(
    library: PhotoLibrary,
    tags: tuple[str, ...] | list[str],
    audience: tuple[str, ...] | list[str] = (),
    day: date | None = None,
) -> Photo | None:
    """Deterministically choose the best-matching photo for the day.

    A photo scores the sum of its matched tags, but rarer tags weigh more than
    common ones ("kids" counts for more than "winter"), so a specific match
    beats a generic one. Exact ties rotate by date, keeping the feed varied.
    """
    if not library.photos:
        return None

    wanted = {str(tag).strip().lower() for tag in tags if str(tag).strip()}
    wanted |= {str(group).strip().lower() for group in audience if str(group).strip()}

    frequency: dict[str, int] = {}
    for photo in library.photos:
        for tag in photo.tags:
            frequency[tag] = frequency.get(tag, 0) + 1
    top = max(frequency.values(), default=1)

    def weight(tag: str) -> int:
        return top + 1 - frequency.get(tag, 1)

    scored = [
        (sum(weight(tag) for tag in wanted & set(photo.tags)), photo)
        for photo in library.photos
    ]
    best = max(score for score, _ in scored)
    candidates = [photo for score, photo in scored if score == best] if best else list(library.photos)
    candidates.sort(key=lambda photo: photo.id)
    key = day.toordinal() if day else 0
    return candidates[key % len(candidates)]
