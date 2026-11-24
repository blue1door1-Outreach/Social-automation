"""Render and validate every idea in config/content.json.

A quick end-to-end check that is not part of the daily pipeline:

    python scripts/check_ideas.py

It builds each idea's caption, runs the validator, renders the graphic with its
picked photo, and writes a contact sheet to ``out/ideas_sheet.png`` so a human can
eyeball the whole month at once. Exit code 1 means at least one idea failed.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402

from src.config import load_all  # noqa: E402
from src.content import load_content, type_label_bn  # noqa: E402
from src.graphics import render  # noqa: E402
from src.photos import load_photos, pick_photo  # noqa: E402
from src.validator import errors, validate_draft  # noqa: E402
from src.writer import build_from_idea  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config")
    parser.add_argument("--out", type=Path, default=ROOT / "out" / "ideas")
    parser.add_argument("--start", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()

    brand, catalog, _ = load_all(args.config)
    content = load_content(args.config / "content.json")
    library = load_photos()
    args.out.mkdir(parents=True, exist_ok=True)

    problems: list[tuple[str, str]] = []
    lengths: list[int] = []
    rendered: list[tuple[str, Path]] = []

    for offset, idea in enumerate(content.ideas):
        day = args.start + timedelta(days=offset)
        draft = build_from_idea(idea, brand, content, day)
        lengths.append(len(draft.caption))
        for issue in errors(validate_draft(draft, brand, catalog)):
            problems.append((idea.id, issue.message))

        photo = pick_photo(library, idea.tags, idea.audience, day)
        target = args.out / f"{offset:02d}-{idea.id}.png"
        try:
            render(
                target,
                brand=brand,
                headline=draft.image_headline,
                subline=draft.image_subline,
                kicker=content.display_kicker,
                label=type_label_bn(idea.type),
                follow=content.display_follow,
                photo=photo.path if photo else None,
                cta=brand.cta_text_bn or brand.cta_text,
                place=brand.location_bn or brand.location.split(",")[0].strip(),
            )
            rendered.append((idea.id, target))
        except Exception as exc:  # noqa: BLE001
            problems.append((idea.id, f"render: {exc}"))

    cols, cell_w, cell_h = 6, 300, 375
    rows = max((len(rendered) + cols - 1) // cols, 1)
    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (idea_id, path) in enumerate(rendered):
        x, y = (index % cols) * cell_w, (index // cols) * cell_h
        with Image.open(path) as image:
            thumb = image.convert("RGB").resize((cell_w - 8, cell_h - 22))
        sheet.paste(thumb, (x + 4, y + 4))
        draw.text((x + 4, y + cell_h - 16), idea_id[:40], fill="black")
    sheet.save(args.out / "sheet.png")

    print(
        json.dumps(
            {
                "ideas": len(content.ideas),
                "rendered": len(rendered),
                "captions_min": min(lengths) if lengths else 0,
                "captions_max": max(lengths) if lengths else 0,
                "problem_count": len(problems),
                "problems": problems[:20],
            },
            indent=2,
        )
    )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
