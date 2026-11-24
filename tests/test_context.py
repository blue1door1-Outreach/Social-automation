from __future__ import annotations

from datetime import date

from src import trends
from src.content import load_content
from src.idea import Situation, build_situation, choose, load_context, season_for
from src.photo_fetch import inspect
from src.weather import Weather, classify, describe

ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent


def test_classify_reads_fog_and_cold() -> None:
    tags = classify(temp=14.0, feels=13.0, humidity=92.0, code=45)
    assert "fog" in tags
    assert "cold" in tags or "chilly" in tags
    assert "humid" in tags
    assert "rain" not in tags


def test_classify_reads_rain_and_warm() -> None:
    tags = classify(temp=30.0, feels=34.0, humidity=70.0, code=63)
    assert "rain" in tags
    assert "warm" in tags


def test_describe_is_short_and_plain() -> None:
    text = describe(("fog", "cold"), 14.0, 13.0, 45)
    assert "fog" in text and "13" in text


def test_trends_block_politics_and_music() -> None:
    cfg = {
        "allow_keywords": ["winter", "fog", "sweater"],
        "deny_keywords": ["election", "music", "song", "cyclone"],
    }
    assert trends.keep("Dhaka winter fog returns this week", cfg) is not None
    assert trends.keep("Election rally in Dhaka winter", cfg) is None
    assert trends.keep("New song about winter fog", cfg) is None
    assert trends.keep("Cyclone heads for winter coast", cfg) is None
    assert trends.keep("Local football derby tonight", cfg) is None


def test_trends_moods_are_mapped() -> None:
    trend = trends.Trend(title="Foggy sweater weather", source="x", url="", keywords=("fog", "sweater"))
    assert set(trend.moods) == {"foggy", "cosy"}


def _situation(day: date, tags: tuple[str, ...], moods: tuple[str, ...] = ()) -> Situation:
    weather = Weather(
        temperature=15.0,
        feels_like=13.0,
        humidity=90.0,
        wind=4.0,
        code=45,
        hour=10,
        tags=tags,
        summary="foggy cold, around 13C (feels like)",
    )
    return Situation(
        day=day,
        hour=10,
        weekday=day.strftime("%A"),
        season="winter",
        season_note_bn="শীত",
        weather=weather,
        trend_moods=moods,
    )


def test_choose_prefers_weather_match() -> None:
    content = load_content(ROOT / "config" / "content.json")
    day = date(2026, 12, 8)
    foggy = choose(content, _situation(day, ("fog", "mist", "cold")))
    assert "fog" in foggy.idea.weather or "fog" in foggy.idea.tags
    assert foggy.reason


def test_choose_avoids_recent_ideas() -> None:
    content = load_content(ROOT / "config" / "content.json")
    day = date(2026, 12, 8)
    situation = _situation(day, ("cold", "chilly"))
    first = choose(content, situation)
    second = choose(content, situation, used=[first.idea.id])
    assert second.idea.id != first.idea.id


def test_build_situation_offline_needs_no_network() -> None:
    import requests

    cfg = load_context(ROOT / "config" / "context.json")
    situation = build_situation(cfg, date(2026, 12, 8), session=requests.Session(), offline=True)
    assert situation.weather is None
    assert situation.season == "winter"
    assert "Dhaka" in situation.brief()


def test_season_windows() -> None:
    cfg = load_context(ROOT / "config" / "context.json")
    assert season_for(date(2026, 1, 4), cfg)[0] == "winter"
    assert season_for(date(2026, 10, 4), cfg)[0] == "hemanta"
    assert season_for(date(2026, 7, 4), cfg)[0] == "warm"


def _png(colour: tuple[int, int, int], size: int = 1200) -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (size, size), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def test_inspect_rejects_flat_images() -> None:
    image, _, _, reason = inspect(_png((255, 255, 255)), min_edge=900, chips=["#FFFBF9"])
    assert image is None
    assert reason in {"flat or blank", "undecodable"}


def test_inspect_rejects_small_images() -> None:
    image, _, _, reason = inspect(_png((200, 180, 150), size=300), min_edge=900, chips=["#FFFBF9"])
    assert image is None
    assert "too small" in reason


def test_inspect_accepts_a_detailed_warm_image() -> None:
    import io

    from PIL import Image, ImageDraw

    buffer = io.BytesIO()
    image = Image.new("RGB", (1200, 1200), (226, 202, 165))
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 120, 520, 700), fill=(89, 78, 56))
    draw.rectangle((640, 200, 1120, 1080), fill=(173, 183, 179))
    draw.rectangle((120, 780, 1120, 1120), fill=(120, 100, 70))
    image.save(buffer, format="JPEG", quality=90)
    result, distance, detail, reason = inspect(buffer.getvalue(), min_edge=900, chips=["#E3CAA5", "#594E38"])
    assert result is not None, reason
    assert distance >= 0
    assert detail > 10
