"""Duplicate detection for the daily post.

Rules, in order:

1. Same post id and every target already queued or in an unknown state -> skip.
2. Same post id, one target queued, the other failed -> resume only the failed
   target.
3. Same post id with an "unknown" target -> skip. A timeout is not a rejection;
   a human has to check Buffer before anything is retried.
4. Any queued/unknown target for the same day under another id -> skip. One
   post per day, even if the content changed between runs.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

TARGETS: tuple[str, ...] = ("facebook", "instagram")
BLOCKING_STATUSES = ("queued", "unknown")


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def make_post_id(day: str, topic: str, caption: str, image_sha: str) -> str:
    digest = hashlib.sha256(
        "|".join((day, normalize(topic), normalize(caption), image_sha)).encode("utf-8")
    ).hexdigest()
    return f"{day}-{digest[:12]}"


@dataclass(frozen=True)
class Decision:
    action: str  # "publish" | "resume" | "skip"
    targets: tuple[str, ...]
    reason: str


def target_status(record: dict[str, Any], target: str) -> str:
    entry = (record.get("targets") or {}).get(target) or {}
    return str(entry.get("status", "not_attempted"))


def decide(
    records: Sequence[dict[str, Any]],
    post_id: str,
    day: str,
    targets: Iterable[str] = TARGETS,
) -> Decision:
    wanted = tuple(targets)

    same_post = [r for r in records if r.get("post_id") == post_id]
    if same_post:
        record = same_post[-1]
        done = {t for t in wanted if target_status(record, t) in BLOCKING_STATUSES}
        unknown = {t for t in done if target_status(record, t) == "unknown"}
        if unknown:
            return Decision(
                "skip",
                (),
                f"previous attempt for {post_id} has unknown outcome on "
                f"{', '.join(sorted(unknown))}; check Buffer before retrying",
            )
        remaining = tuple(t for t in wanted if t not in done)
        if done and remaining:
            return Decision(
                "resume",
                remaining,
                f"resuming {', '.join(remaining)} for {post_id}; "
                f"{', '.join(sorted(done))} already queued",
            )
        if done:
            return Decision("skip", (), f"{post_id} already queued on {', '.join(sorted(done))}")

    for record in records:
        if record.get("date") != day:
            continue
        for target in wanted:
            status = target_status(record, target)
            if status in BLOCKING_STATUSES:
                return Decision(
                    "skip",
                    (),
                    f"{day} already has a {status} {target} post "
                    f"({record.get('post_id')}); refusing a second post",
                )

    return Decision("publish", wanted, "no prior post for this date")
