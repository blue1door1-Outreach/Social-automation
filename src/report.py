"""Markdown run report.

This file is the human interface: it is uploaded as an artifact, printed into
the Actions job summary, and committed nowhere. Secrets are redacted before the
text is written.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .redact import redact

STATUS_LABELS = {
    "queued": "queued",
    "failed": "failed",
    "unknown": "outcome unknown",
    "not_attempted": "not attempted (preview)",
    "skipped": "skipped",
}


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def build(context: dict[str, Any]) -> str:
    status = context.get("status", "UNKNOWN")
    started: datetime = context["started"]
    local: datetime = context["local_time"]
    lines: list[str] = [
        f"# Daily post report - {context['date']}",
        "",
        f"**Status:** {status}",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Mode | `{_cell(context['mode'])}` |",
        f"| Timezone | `{_cell(context['timezone'])}` |",
        f"| Started (UTC) | {started.strftime('%Y-%m-%d %H:%M:%S')} |",
        f"| Started (local) | {local.strftime('%Y-%m-%d %H:%M:%S %Z')} |",
        f"| Post id | `{_cell(context.get('post_id') or 'not created')}` |",
        "",
    ]

    situation = context.get("situation")
    chosen = context.get("idea")
    lines += ["## Situation", ""]
    if situation:
        lines.append(f"- When: {_cell(situation.get('weekday'))} at {situation.get('hour')}:00 ({_cell(situation.get('season'))})")
        weather = situation.get("weather")
        if weather:
            lines.append(f"- Weather: {_cell(weather.get('summary'))} [{_cell(', '.join(weather.get('tags', [])))}]")
        else:
            lines.append("- Weather: unavailable (season-only context)")
        if situation.get("trend_moods"):
            lines.append(f"- Trend mood: {_cell(', '.join(situation.get('trend_moods', [])))}")
        if situation.get("trend_titles"):
            lines.append("- Trending now (mood only, never stated as fact):")
            for title in situation.get("trend_titles", [])[:5]:
                lines.append(f"  - {_cell(title)}")
        if situation.get("errors"):
            lines.append(f"- Signals unavailable: {_cell('; '.join(situation['errors']))}")
    else:
        lines.append("_Queue mode reuses the reviewed preview; signals are not re-read._")
    if chosen:
        lines.append(f"- Chosen idea: `{_cell(chosen.get('id'))}` (concept `{_cell(chosen.get('concept'))}`)")
        lines.append(f"- Why: {_cell(chosen.get('reason'))}")
    lines.append("")

    topic = context.get("topic")
    lines += ["## Content idea", ""]
    if topic:
        source = str(topic.get("source", ""))
        origin = "curated content library" if source.startswith(("content:", "idea:")) else source
        lines.append(f"- **{_cell(topic.get('title'))}**")
        lines.append(f"- Source: {_cell(origin)}")
        if topic.get("link"):
            lines.append(f"- Link: {_cell(topic['link'])}")
        if topic.get("score"):
            lines.append(f"- Relevance score: {topic['score']}")
    else:
        lines.append("_No idea selected._")
    lines.append("")

    draft = context.get("draft")
    lines += ["## Content", ""]
    if draft:
        lines.append(f"- Generator: `{_cell(draft.get('source'))}`")
        lines.append(f"- Caption length: {len(draft.get('caption', ''))} characters")
        lines.append(f"- Hashtags: {_cell(' '.join(draft.get('hashtags', [])))}")
        lines.append(f"- Image headline: {_cell(draft.get('image_headline'))}")
        lines += ["", "> " + _cell(draft.get("caption", "")).replace("\n", "\n> "), ""]
    else:
        lines.append("_No caption generated._")
        lines.append("")

    image = context.get("image")
    lines += ["## Image", ""]
    if image:
        lines.append(
            f"- {image['width']}x{image['height']} PNG, {image['bytes'] / 1024:.0f} KB, "
            f"sha256 `{image['sha256'][:16]}`"
        )
        photo = context.get("photo")
        if photo:
            lines.append(
                f"- Photo: {_cell(photo.get('credit'))} "
                f"(concept `{_cell(photo.get('concept'))}`, palette distance {photo.get('palette_distance')})"
            )
            if photo.get("source"):
                lines.append(f"- Photo source: {_cell(photo['source'])}")
        else:
            lines.append("- Photo: none (text-only layout)")
        if context.get("image_url"):
            lines.append(f"- Public URL: {_cell(context['image_url'])}")
    else:
        lines.append("_No image rendered._")
    lines.append("")

    lines += ["## Publishing gate", ""]
    gates = context.get("gates") or []
    if gates:
        for gate in gates:
            lines.append(f"- BLOCKED: {_cell(gate)}")
    elif context.get("mode") == "preview":
        lines.append("- Not evaluated: preview run. Publishing gates apply in queue mode.")
    else:
        lines.append("- All configured gate checks passed.")
    lines.append("")

    targets = context.get("targets") or {}
    lines += ["## Platforms", "", "| Platform | Status | Detail |", "| --- | --- | --- |"]
    for name in ("facebook", "instagram"):
        entry = targets.get(name) or {"status": "not_attempted", "detail": ""}
        key = entry.get("status", "")
        if key == "not_attempted":
            status_text = (
                "not attempted (preview)"
                if context.get("mode") == "preview"
                else "not attempted (blocked)"
            )
        else:
            status_text = STATUS_LABELS.get(key, key)
        lines.append(f"| {name} | {_cell(status_text)} | {_cell(entry.get('detail', ''))} |")
    lines.append("")

    decision = context.get("decision")
    if decision:
        lines += ["## Duplicate check", "", f"- {_cell(decision)}", ""]

    errors = context.get("errors") or []
    if errors:
        lines += ["## Errors", ""]
        lines += [f"- {_cell(error)}" for error in errors]
        lines.append("")

    warnings = context.get("warnings") or []
    if warnings:
        lines += ["## Warnings", ""]
        lines += [f"- {_cell(warning)}" for warning in warnings]
        lines.append("")

    next_steps = context.get("next_steps") or []
    if next_steps:
        lines += ["## Next steps", ""]
        lines += [f"{index}. {_cell(step)}" for index, step in enumerate(next_steps, start=1)]
        lines.append("")

    return redact("\n".join(lines)).replace("\r\n", "\n")
