"""Render every idea with its concept photo and check the whole library.

    python scripts/check_ideas.py            # offline: season-only context, no photos
    python scripts/check_ideas.py --online   # real weather + trends + fetched photos

Builds each idea's caption, runs the validator, renders the graphic and writes a
contact sheet to ``out/ideas/sheet.png``. Exit code 1 means at least one idea
failed.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import requests  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from src import photo_fetch  # noqa: E402
from src.config import load_all  # noqa: E402
from src.content import load_content, type_label_bn  # noqa: E402
from src.graphics import render  # noqa: E402
from src.idea import build_situation, choose, load_context  # noqa: E402
from src.validator import errors, validate_draft  # noqa: E402
from src.writer import build_from_idea  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config")
    parser.add_argument("--out", type=Path, default=ROOT / "out" / "ideas")
    parser.add_argument("--start", type=date.fromisoformat, default=date.today())
    parser.add_argument("--online", action="store_true", help="fetch weather, trends and photos")
    args = parser.parse_args()

    brand, catalog, _ = load_all(args.config)
    content = load_content(args.config / "content.json")
    cfg = load_context(args.config / "context.json")
    args.out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()

    problems: list[tuple[str, str]] = []
    rendered: list[tuple[str, str, Path]] = []

    for offset, idea in enumerate(content.ideas):
        day = args.start + timedelta(days=offset)
        situation = build_situation(cfg, day, session=session, offline=not args.online)
        chosen = choose(content, situation)
        draft = build_from_idea(idea, brand, content, day, situation)
        for issue in errors(validate_draft(draft, brand, catalog)):
            problems.append((idea.id, issue.message))

        photo = None
        if args.online:
            photo = photo_fetch.fetch(
                chosen.concept,
                (cfg.get("photos") or {}).get("queries") or {},
                args.out,
                day,
                cfg=cfg.get("photos") or {},
                session=session,
            )

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
            rendered.append((idea.id, chosen.concept, target))
        except Exception as exc:  # noqa: BLE001
            problems.append((idea.id, f"render: {exc}"))

    cols, cell_w, cell_h = 6, 300, 375
    rows = max((len(rendered) + cols - 1) // cols, 1)
    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (idea_id, concept, path) in enumerate(rendered):
        x, y = (index % cols) * cell_w, (index // cols) * cell_h
        with Image.open(path) as image:
            thumb = image.convert("RGB").resize((cell_w - 8, cell_h - 22))
        sheet.paste(thumb, (x + 4, y + 4))
        draw.text((x + 4, y + cell_h - 16), f"{idea_id[:28]} [{concept}]", fill="black")
    sheet.save(args.out / "sheet.png")

    print(
        json.dumps(
            {
                "ideas": len(content.ideas),
                "rendered": len(rendered),
                "problem_count": len(problems),
                "problems": problems[:20],
            },
            indent=2,
        )
    )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
