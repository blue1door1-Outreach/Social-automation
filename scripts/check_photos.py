"""Build a contact sheet of the bundled photos for a human no-people check.

    python scripts/check_photos.py

Writes ``out/photos_sheet.png``. Photos are stock images with no people in them,
so a face slipping in is the one mistake that must not ship; this sheet makes
that review take a few seconds.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402

from src.photos import load_photos  # noqa: E402


def main() -> int:
    library = load_photos()
    if not library.photos:
        print("no photos found under assets/photos")
        return 1

    photos = sorted(library.photos, key=lambda photo: photo.id)
    cols, cell_w, cell_h = 4, 360, 300
    rows = (len(photos) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), "white")
    draw = ImageDraw.Draw(sheet)
    for index, photo in enumerate(photos):
        x, y = (index % cols) * cell_w, (index // cols) * cell_h
        with Image.open(photo.path) as image:
            thumb = image.convert("RGB")
            thumb.thumbnail((cell_w - 8, cell_h - 24))
        sheet.paste(thumb, (x + 4, y + 4))
        draw.text((x + 4, y + cell_h - 18), f"{index}: {photo.id}", fill="black")

    out = ROOT / "out" / "photos_sheet.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print(f"{len(photos)} photos -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
