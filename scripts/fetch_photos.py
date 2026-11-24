"""Download the curated, no-people photo set and rewrite credits.json.

Every photo here was picked by eye from CC0 / public-domain results and has no
people in it. The script is committed so the set is reproducible: it downloads
each source once, trims the long edge to 1600px, and records the licence in
``assets/photos/credits.json``. Run it only when refreshing the set; the
downloaded JPEGs and the manifest are both committed.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import requests
from PIL import Image

DEST = Path(__file__).resolve().parent.parent / "assets" / "photos"
MAX_EDGE = 1600

SOURCES = [
    {
        "id": 'scarf-red-bow',
        "tags": ('scarf', 'style', 'accessories', 'colour'),
        "url": 'https://ids.si.edu/ids/deliveryService?id=NMAAHC-2011_172_1_001',
        "title": 'Red wool scarf worn by Joan Mulholland during a protest near the White House',
        "creator": 'Unidentified',
        "license": 'cc0',
        "license_url": 'https://creativecommons.org/publicdomain/zero/1.0/',
        "source": 'https://nmaahc.si.edu/object/nmaahc_2011.172.1',
    },
    {
        "id": 'scarf-plaid',
        "tags": ('scarf', 'texture', 'colour', 'style'),
        "url": 'https://pd.w.org/2024/04/16466138d627c9219.35963855-2048x1536.jpg',
        "title": 'Macro photography of a wool scarf in various colors',
        "creator": 'Yagnik Sangani',
        "license": 'cc0',
        "license_url": 'https://creativecommons.org/publicdomain/zero/1.0/',
        "source": 'https://wordpress.org/photos/photo/16466138d6/',
    },
    {
        "id": 'scarf-red-macro',
        "tags": ('scarf', 'texture', 'warm'),
        "url": 'https://live.staticflickr.com/4083/5224781734_4611e7cab3_b.jpg',
        "title": 'Project 365 #335: 011210 Winter Wear',
        "creator": 'comedy_nose',
        "license": 'pdm',
        "license_url": 'https://creativecommons.org/publicdomain/mark/1.0/',
        "source": 'https://www.flickr.com/photos/23408922@N07/5224781734',
    },
    {
        "id": 'foggy-window',
        "tags": ('dhaka', 'winter', 'mood', 'window'),
        "url": 'https://live.staticflickr.com/518/19178936993_f5a3083384_b.jpg',
        "title": 'Foggy Window',
        "creator": 'Huney Co',
        "license": 'cc0',
        "license_url": 'https://creativecommons.org/publicdomain/zero/1.0/',
        "source": 'https://www.flickr.com/photos/134838029@N08/19178936993',
    },
    {
        "id": 'city-abstract',
        "tags": ('dhaka', 'winter', 'city'),
        "url": 'https://cdn.stocksnap.io/img-thumbs/960w/O6ZKFPOHXN.jpg',
        "title": 'Buildings Architecture',
        "creator": 'Matthew Henry',
        "license": 'cc0',
        "license_url": 'https://creativecommons.org/publicdomain/zero/1.0/',
        "source": 'https://stocksnap.io/photo/buildings-architecture-O6ZKFPOHXN',
    },
    {
        "id": 'snowy-forest',
        "tags": ('winter', 'mood', 'outdoor'),
        "url": 'https://live.staticflickr.com/7024/6546071211_fc43f28476_b.jpg',
        "title": 'Foggy Morning, North Window',
        "creator": 'ArchesNPS',
        "license": 'pdm',
        "license_url": 'https://creativecommons.org/publicdomain/mark/1.0/',
        "source": 'https://www.flickr.com/photos/72578886@N08/6546071211',
    },
    {
        "id": 'coat-hanger',
        "tags": ('layering', 'wardrobe', 'style'),
        "url": 'https://collections.museumsvictoria.com.au/content/media/18/1349118-large.jpg',
        "title": 'Coat Hanger - Wood With Painted Face, circa 1948',
        "creator": 'Photographer: Museums Victoria',
        "license": 'pdm',
        "license_url": 'https://creativecommons.org/publicdomain/mark/1.0/',
        "source": 'https://collections.museumsvictoria.com.au/items/2502082',
    },
    {
        "id": 'knit-hat-cream',
        "tags": ('kids', 'hat', 'winter'),
        "url": 'https://live.staticflickr.com/8369/8489490503_db183a8e1d_b.jpg',
        "title": 'Cream knit hat with pom pom',
        "creator": 'D Coetzee',
        "license": 'cc0',
        "license_url": 'https://creativecommons.org/publicdomain/zero/1.0/',
        "source": 'https://www.flickr.com/photos/29507259@N02/8489490503',
    },
    {
        "id": 'yarn-colours',
        "tags": ('care', 'knit', 'texture'),
        "url": 'https://images.rawpixel.com/editor_1024/czNmcy1wcml2YXRlL3Jhd3BpeGVsX2ltYWdlcy93ZWJzaXRlX2NvbnRlbnQvd2s3NzgxMTE5NS1pbWFnZS1rcDZjajJ1eS5qcGc.jpg',
        "title": 'Image multiple rolls wool yarn',
        "creator": '',
        "license": 'cc0',
        "license_url": 'https://creativecommons.org/publicdomain/zero/1.0/',
        "source": 'https://www.rawpixel.com/image/3338324/free-photo-image-yarn-cc0-colorful',
    },
    {
        "id": 'yarn-bright',
        "tags": ('care', 'knit', 'texture', 'colour'),
        "url": 'https://live.staticflickr.com/3914/14996784845_0423b7c9c6_b.jpg',
        "title": 'Tell me a Yarn.',
        "creator": 'Bernard Spragg',
        "license": 'cc0',
        "license_url": 'https://creativecommons.org/publicdomain/zero/1.0/',
        "source": 'https://www.flickr.com/photos/88123769@N02/14996784845',
    },
    {
        "id": 'tea-mug-tray',
        "tags": ('winter', 'comfort', 'tea'),
        "url": 'https://images.rawpixel.com/editor_1024/cHJpdmF0ZS9zdGF0aWMvaW1hZ2Uvd2Vic2l0ZS8yMDIyLTA0L2xyL3B4ODE1MzE2LWltYWdlLWt3dnYxOGs2LmpwZw.jpg',
        "title": 'Free hot tea cup image',
        "creator": '',
        "license": 'cc0',
        "license_url": 'https://creativecommons.org/publicdomain/zero/1.0/',
        "source": 'https://www.rawpixel.com/image/5905684/photo-image-public-domain-free-tea',
    },
    {
        "id": 'tea-glass-window',
        "tags": ('winter', 'comfort', 'tea', 'dhaka'),
        "url": 'https://images.rawpixel.com/editor_1024/cHJpdmF0ZS9zdGF0aWMvaW1hZ2Uvd2Vic2l0ZS8yMDIyLTA0L2xyL2ZydGVhX211Z19nbGFzc193aW5kb3ctaW1hZ2Uta3liY20yZWMuanBn.jpg',
        "title": 'Hot tea cup',
        "creator": '',
        "license": 'cc0',
        "license_url": 'https://creativecommons.org/publicdomain/zero/1.0/',
        "source": 'https://www.rawpixel.com/image/6031397/hot-tea-cup-free-public-domain-cc0-image',
    },
    {
        "id": 'tea-set',
        "tags": ('winter', 'comfort', 'tea'),
        "url": 'https://images.rawpixel.com/editor_1024/czNmcy1wcml2YXRlL3Jhd3BpeGVsX2ltYWdlcy93ZWJzaXRlX2NvbnRlbnQvbHIvcHgxMzY0MjY1LWltYWdlLWt3dncxaHVqLmpwZw.jpg',
        "title": 'Free hot tea cup image',
        "creator": '',
        "license": 'cc0',
        "license_url": 'https://creativecommons.org/publicdomain/zero/1.0/',
        "source": 'https://www.rawpixel.com/image/5911947/image-public-domain-coffee-free',
    },
    {
        "id": 'tea-glass-table',
        "tags": ('winter', 'comfort', 'tea', 'mood'),
        "url": 'https://live.staticflickr.com/4168/34419804081_3ae747a143_b.jpg',
        "title": 'Tea on the countertop',
        "creator": 'freestocks.org',
        "license": 'cc0',
        "license_url": 'https://creativecommons.org/publicdomain/zero/1.0/',
        "source": 'https://www.flickr.com/photos/135396164@N05/34419804081',
    },
    {
        "id": 'wool-blanket',
        "tags": ('winter', 'comfort', 'knit', 'care'),
        "url": 'https://live.staticflickr.com/6084/6144495378_e7f6bb0b5c_b.jpg',
        "title": 'Berlin Duty Train Blanket',
        "creator": 'popo.uw23',
        "license": 'pdm',
        "license_url": 'https://creativecommons.org/publicdomain/mark/1.0/',
        "source": 'https://www.flickr.com/photos/10511576@N00/6144495378',
    },
    {
        "id": 'knit-orange',
        "tags": ('care', 'knit', 'texture'),
        "url": 'https://images.rawpixel.com/editor_1024/cHJpdmF0ZS9zdGF0aWMvaW1hZ2Uvd2Vic2l0ZS8yMDIyLTA0L2xyL3B4MTE1Njc1MC1pbWFnZS1rd3lyM29ieS5qcGc.jpg',
        "title": '',
        "creator": '',
        "license": 'cc0',
        "license_url": 'https://creativecommons.org/publicdomain/zero/1.0/',
        "source": 'https://www.rawpixel.com/image/5961547/free-public-domain-cc0-photo',
    },
    {
        "id": 'knit-multi',
        "tags": ('care', 'knit', 'texture', 'colour'),
        "url": 'https://images.rawpixel.com/editor_1024/czNmcy1wcml2YXRlL3Jhd3BpeGVsX2ltYWdlcy93ZWJzaXRlX2NvbnRlbnQvbHIvZnJrbml0dGVkX2tuaXR0aW5nX2tuaXR0ZWRfZmFicmljLWltYWdlLWt5Y2dodHNzLmpwZw.jpg',
        "title": '',
        "creator": '',
        "license": 'cc0',
        "license_url": 'https://creativecommons.org/publicdomain/zero/1.0/',
        "source": 'https://www.rawpixel.com/image/6057807/free-public-domain-cc0-photo',
    },
    {
        "id": 'woven-wool',
        "tags": ('care', 'knit', 'texture'),
        "url": 'https://openaccess-cdn.clevelandart.org/1930.628/1930.628_web.jpg',
        "title": 'Woven Wool Textile',
        "creator": '',
        "license": 'cc0',
        "license_url": 'https://creativecommons.org/publicdomain/zero/1.0/',
        "source": 'https://clevelandart.org/art/1930.628',
    },
    {
        "id": 'denim-jacket',
        "tags": ('denim', 'layering', 'style'),
        "url": 'https://images.rawpixel.com/editor_1024/cHJpdmF0ZS9sci9pbWFnZXMvd2Vic2l0ZS8yMDIyLTExL2xyL3NtaXRoc25ubWFhaGMyMDA3MzU2MTAwMS1pbWFnZS5qcGc.jpg',
        "title": 'Denim jacket designed Arthur McGee',
        "creator": '',
        "license": 'cc0',
        "license_url": 'https://creativecommons.org/publicdomain/zero/1.0/',
        "source": 'https://www.rawpixel.com/image/8849885/denim-jacket-designed-arthur-mcgee',
    },
    {
        "id": 'plaid-fabric',
        "tags": ('colour', 'fabric', 'pattern'),
        "url": 'https://live.staticflickr.com/65535/48680241762_2d9d0be4dc_b.jpg',
        "title": 'Blue Plaid Fabric',
        "creator": 'joncutrer',
        "license": 'cc0',
        "license_url": 'https://creativecommons.org/publicdomain/zero/1.0/',
        "source": 'https://www.flickr.com/photos/47121680@N00/48680241762',
    },
    {
        "id": 'stripe-fabric',
        "tags": ('colour', 'fabric', 'texture'),
        "url": 'https://images.rawpixel.com/editor_1024/czNmcy1wcml2YXRlL3Jhd3BpeGVsX2ltYWdlcy93ZWJzaXRlX2NvbnRlbnQvbHIvcHg5MjQ3NDktaW1hZ2Uta3d5bzFkcjQuanBn.jpg',
        "title": '',
        "creator": '',
        "license": 'cc0',
        "license_url": 'https://creativecommons.org/publicdomain/zero/1.0/',
        "source": 'https://www.rawpixel.com/image/5941472/free-public-domain-cc0-photo',
    },
]


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    photos = []
    for source in SOURCES:
        response = requests.get(
            source["url"], timeout=60, headers={"User-Agent": "khuje-nao/1.0"}
        )
        response.raise_for_status()
        image = Image.open(io.BytesIO(response.content))
        image.load()
        image = image.convert("RGB")
        image.thumbnail((MAX_EDGE, MAX_EDGE), Image.LANCZOS)
        entry = {key: source[key] for key in (
            "id", "title", "creator", "license", "license_url", "source"
        )}
        entry["file"] = f"{source['id']}.jpg"
        entry["tags"] = list(source["tags"])
        entry["no_people"] = True
        entry["width"] = image.width
        entry["height"] = image.height
        image.save(DEST / entry["file"], format="JPEG", quality=85, optimize=True)
        photos.append(entry)
        print(f"{source['id']}: {image.width}x{image.height}")

    (DEST / "credits.json").write_text(
        json.dumps({"photos": photos}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(photos)} photos")


if __name__ == "__main__":
    main()
