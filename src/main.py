"""Daily pipeline entry point.

    python -m src.main --mode preview        # generate + report, publish nothing
    python -m src.main --mode queue          # publish the reviewed artifacts

Exit codes:

    0  preview ready, or every target queued
    1  blocked, skipped, partial, failed or unknown -- nothing more was published
    2  crash or configuration error

In GitHub Actions a non-zero exit is intentional: a skipped post should be
visible, not silent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import requests

from . import graphics, idea as idea_mod, photo_fetch, report, research, validator, writer
from .buffer_client import BufferClient, BufferError, BufferUncertain, verify_channels
from .config import Brand, ConfigError, load_all
from .content import ContentIdea, load_content, type_label_bn
from .duplicate_guard import decide, make_post_id
from .env_file import load_env_file
from .redact import collect_secrets, set_secrets, setup_logging
from .state import Ledger, LedgerError
from .topic_filter import Topic

LOG = logging.getLogger("khuje.main")
ROOT = Path(__file__).resolve().parent.parent
CHANNEL_ENV = {"facebook": "BUFFER_CHANNEL_FB", "instagram": "BUFFER_CHANNEL_IG"}
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class MainError(RuntimeError):
    pass


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="khuje-nao")
    parser.add_argument("--mode", choices=("preview", "queue"), default="preview")
    parser.add_argument("--date", help="override the run date (YYYY-MM-DD)")
    parser.add_argument("--out", default="out", help="output directory (default: out)")
    parser.add_argument("--config", default="config", help="config directory (default: config)")
    parser.add_argument("--ledger", default="state/ledger.jsonl")
    parser.add_argument("--image-url", default=None, help="public URL of the reviewed image")
    parser.add_argument("--idea", default=None, help="force a content idea id (manual override)")
    parser.add_argument("--now", action="store_true", help="publish immediately with Buffer shareNow")
    parser.add_argument("--offline", action="store_true", help="use templates instead of Gemini")
    parser.add_argument("--timeout", type=int, default=20)
    return parser.parse_args(argv)


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _annotate(level: str, title: str, message: str) -> None:
    safe = message.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
    print(f"::{level} title={title}::{safe}", file=sys.stderr)


def _resolve_day(args: argparse.Namespace, brand: Brand) -> date:
    if args.date:
        try:
            return date.fromisoformat(args.date)
        except ValueError as exc:
            raise MainError(f"--date must be YYYY-MM-DD, got {args.date!r}") from exc
    return datetime.now(timezone.utc).astimezone(brand.tz).date()


def _fetch_public(url: str) -> tuple[str, bytes]:
    joiner = "&" if "?" in url else "?"
    response = requests.get(
        f"{url}{joiner}cb={uuid.uuid4().hex[:8]}",
        timeout=30,
        headers={"Cache-Control": "no-cache", "User-Agent": research.USER_AGENT},
    )
    response.raise_for_status()
    return response.headers.get("content-type", ""), response.content


def _resolve_image_url(
    args: argparse.Namespace, env: dict[str, str], post_id: str, post: dict[str, Any] | None
) -> str:
    if args.image_url:
        return args.image_url.strip()
    if post and post.get("image_url"):
        return str(post["image_url"]).strip()
    base = env.get("PUBLIC_IMAGE_BASE_URL", "").strip()
    if base:
        return f"{base.rstrip('/')}/{post_id}.png"
    return ""


def _load_artifacts(out_dir: Path) -> tuple[dict[str, Any], Topic, writer.Draft, graphics.ImageMeta]:
    post_path = out_dir / "post.json"
    if not post_path.exists():
        raise MainError(f"no reviewed post for this date ({post_path}). Run --mode preview first.")
    try:
        post = json.loads(post_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MainError(f"cannot read {post_path}: {exc}") from exc
    if not isinstance(post, dict) or not isinstance(post.get("draft"), dict):
        raise MainError(f"{post_path} is not a valid preview file; rerun --mode preview")

    image_info = post.get("image")
    if not isinstance(image_info, dict) or not image_info.get("sha256"):
        raise MainError(f"{post_path} has no image hash; rerun --mode preview")

    image_path = out_dir / str(image_info.get("file", "image.png"))
    if not image_path.exists():
        raise MainError(f"image missing at {image_path}; rerun --mode preview")
    payload = image_path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != image_info["sha256"]:
        raise MainError("image on disk does not match post.json; rerun --mode preview")

    meta = graphics.ImageMeta(
        path=image_path,
        width=int(image_info.get("width", 0)),
        height=int(image_info.get("height", 0)),
        bytes=len(payload),
        sha256=digest,
    )
    topic_data = post.get("topic") or {}
    topic = Topic(
        title=str(topic_data.get("title", "")),
        link=str(topic_data.get("link", "")),
        source=str(topic_data.get("source", "")),
        score=int(topic_data.get("score", 0)),
        product_id=topic_data.get("product_id"),
        is_fallback=bool(topic_data.get("is_fallback", False)),
    )
    draft_data = post["draft"]
    if not draft_data.get("caption"):
        raise MainError(f"{post_path} has no caption; rerun --mode preview")
    draft = writer.Draft(
        hook=str(draft_data.get("hook", "")),
        caption=str(draft_data["caption"]),
        hashtags=tuple(draft_data.get("hashtags", [])),
        image_headline=str(draft_data.get("image_headline", "")),
        image_subline=str(draft_data.get("image_subline", "")),
        product_ids=tuple(draft_data.get("product_ids", [])),
        source=str(draft_data.get("source", "unknown")),
        format=str(draft_data.get("format", "short")),
    )
    return post, topic, draft, meta


def _buffer_key(env: dict[str, str]) -> str:
    return (env.get("BUFFER_API_KEY") or env.get("BUFFER_ACCESS_TOKEN") or "").strip()


def _gate_problems(env: dict[str, str], brand: Brand, image_url: str) -> list[str]:
    problems: list[str] = []
    if not _truthy(env.get("ENABLE_QUEUEING")):
        problems.append("ENABLE_QUEUEING is not true; queueing is disabled")
    if not brand.verified:
        problems.append("brand.json is not verified")
    if not _buffer_key(env):
        problems.append("BUFFER_API_KEY is not set")

    organization_id = (env.get("BUFFER_ORGANIZATION_ID") or "").strip()
    if not organization_id:
        problems.append("BUFFER_ORGANIZATION_ID is not set")
    elif not ID_PATTERN.match(organization_id):
        problems.append(
            f"BUFFER_ORGANIZATION_ID looks malformed (got {organization_id!r}); "
            "it must be the id alone, with no extra text"
        )

    for target, variable in CHANNEL_ENV.items():
        channel_id = (env.get(variable) or "").strip()
        if not channel_id:
            problems.append(f"{variable} is not set ({target} channel id)")
        elif not ID_PATTERN.match(channel_id):
            problems.append(
                f"{variable} looks malformed (got {channel_id!r}); it must be the id alone"
            )
    if not image_url:
        problems.append("no public image URL (set --image-url or PUBLIC_IMAGE_BASE_URL)")
    due_at = (env.get("BUFFER_DUE_AT") or "").strip()
    if due_at:
        try:
            parsed = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
        except ValueError:
            problems.append(
                f"BUFFER_DUE_AT is not ISO-8601 (got {due_at!r}); "
                "use e.g. 2026-11-24T04:00:00Z"
            )
        else:
            if parsed.tzinfo is None:
                problems.append("BUFFER_DUE_AT must include a timezone, e.g. 2026-11-24T04:00:00Z")
    return problems


def _publish(
    client: BufferClient,
    targets: Sequence[str],
    env: dict[str, str],
    text: str,
    image_url: str,
    due_at: str | None = None,
    mode: str = "addToQueue",
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for target in targets:
        channel_id = env[CHANNEL_ENV[target]]
        try:
            payload = client.create_update(
                channel_id, text, image_url=image_url, due_at=due_at, mode=mode, service=target
            )
        except BufferUncertain as exc:
            results[target] = {"status": "unknown", "detail": str(exc)}
            LOG.error("%s: outcome unknown, do not retry blindly: %s", target, exc)
        except BufferError as exc:
            results[target] = {"status": "failed", "detail": str(exc)}
            LOG.error("%s: buffer rejected the update: %s", target, exc)
        else:
            post_id = str(payload.get("id", "")) if isinstance(payload, dict) else ""
            detail = f"post {post_id}".strip()
            if payload.get("due_at"):
                detail = f"{detail} due {payload['due_at']}"
            results[target] = {"status": "queued", "detail": detail}
            LOG.info("%s: queued (%s)", target, post_id or "no id returned")
        results[target]["at"] = _iso(datetime.now(timezone.utc))
    return results


def _overall(targets: dict[str, dict[str, Any]]) -> str:
    statuses = [targets[t]["status"] for t in CHANNEL_ENV if t in targets]
    if any(status == "unknown" for status in statuses):
        return "unknown"
    if statuses and all(status == "queued" for status in statuses):
        return "queued"
    if any(status == "queued" for status in statuses):
        return "partial"
    return "failed"


def _next_steps(status: str, mode: str, out_dir: Path) -> list[str]:
    if status == "PREVIEW READY":
        return [
            f"Open {out_dir / 'image.png'} and read the caption above.",
            "Nothing was queued. Fix any wording you dislike, then rerun.",
            "Queueing stays disabled until ENABLE_QUEUEING is set and the configs are verified.",
        ]
    if status == "BLOCKED":
        return [
            "Fix the errors above; nothing was published.",
            "A skipped post is better than an inaccurate one.",
        ]
    if status == "SKIPPED":
        return ["Nothing was published. Review the gate lines above."]
    if status == "QUEUED":
        return [
            "Confirm the update in the Buffer queue before trusting this report.",
            "Check the Facebook and Instagram posts after the scheduled time.",
        ]
    if mode == "queue":
        return [
            "Open Buffer and check whether the update exists before rerunning.",
            f"If it is missing, remove only that day's record from state/ledger.jsonl after checking.",
        ]
    return ["Inspect the errors above."]


def _recent(ledger: Ledger, day: date, days: int) -> tuple[list[str], list[str]]:
    """Idea ids and photo ids used in the last ``days`` days, newest first."""
    if days <= 0:
        return [], []
    floor = day.toordinal() - days
    ideas: list[str] = []
    photos: list[str] = []
    try:
        records = ledger.records()
    except LedgerError:
        return [], []
    for record in records:
        stamp = str(record.get("date", ""))
        try:
            ordinal = date.fromisoformat(stamp).toordinal()
        except ValueError:
            continue
        if ordinal < floor or ordinal > day.toordinal():
            continue
        if record.get("idea_id"):
            ideas.append(str(record["idea_id"]))
        photo = record.get("photo")
        if isinstance(photo, dict) and photo.get("id"):
            photos.append(str(photo["id"]))
    return ideas, photos


def _local_history(out_root: Path, day: date, days: int) -> tuple[list[str], list[str]]:
    """Idea/photo ids from earlier local previews, so review runs do not repeat.

    The ledger only knows about published posts. While reviewing a week offline
    or online, consecutive preview folders are the de-facto history.
    """
    if days <= 0 or not out_root.is_dir():
        return [], []
    floor = day.toordinal() - days
    ideas: list[str] = []
    photos: list[str] = []
    for folder in sorted(out_root.iterdir()):
        if not folder.is_dir():
            continue
        try:
            ordinal = date.fromisoformat(folder.name).toordinal()
        except ValueError:
            continue
        if ordinal < floor or ordinal >= day.toordinal():
            continue
        payload = folder / "post.json"
        if not payload.is_file():
            continue
        try:
            post = json.loads(payload.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        idea = post.get("idea") or {}
        if idea.get("id"):
            ideas.append(str(idea["id"]))
        photo = post.get("photo") or {}
        if photo.get("id"):
            photos.append(str(photo["id"]))
    return ideas, photos


def run(args: argparse.Namespace, env: dict[str, str]) -> int:
    brand, catalog, _ = load_all(ROOT / args.config)
    content_config = load_content(ROOT / args.config / "content.json")
    context_cfg = idea_mod.load_context(ROOT / args.config / "context.json")
    recency_days = int(context_cfg.get("recency_days", 14))
    day = _resolve_day(args, brand)
    out_dir = (ROOT / args.out / day.isoformat()).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    started = datetime.now(timezone.utc)
    local_time = started.astimezone(brand.tz)

    warnings: list[str] = []
    errors: list[str] = []
    gates: list[str] = []
    decision_text = ""
    post: dict[str, Any] | None = None
    topic: Topic | None = None
    idea: ContentIdea | None = None
    photo: photo_fetch.FetchedPhoto | None = None
    situation: idea_mod.Situation | None = None
    chosen: idea_mod.Chosen | None = None
    draft: writer.Draft | None = None
    image_meta: graphics.ImageMeta | None = None
    image_url = ""

    session = requests.Session()
    session.headers["User-Agent"] = research.USER_AGENT

    if args.mode == "queue":
        try:
            post, topic, draft, image_meta = _load_artifacts(out_dir)
        except MainError as exc:
            gates.append(str(exc))

    if draft is None and not gates and args.mode == "preview":
        situation = idea_mod.build_situation(
            context_cfg, day, session=session, offline=args.offline, log=LOG, timeout=args.timeout
        )
        warnings.extend(situation.errors)
        used_ideas, used_photos = _recent(Ledger(ROOT / args.ledger), day, recency_days)
        local_ideas, local_photos = _local_history(out_dir.parent, day, recency_days)
        used_ideas = list(
            dict.fromkeys(
                used_ideas
                + local_ideas
                + idea_mod.recent_ideas(content_config, situation, recency_days)
            )
        )
        used_photos = list(dict.fromkeys(used_photos + local_photos))
        if args.idea:
            match = next((item for item in content_config.ideas if item.id == args.idea), None)
            if match is None:
                raise MainError(f"unknown idea id: {args.idea}")
            chosen = idea_mod.Chosen(
                idea=match,
                concept=match.concept or "comfort",
                score=0,
                reason=f"manual override: {match.id}",
                story=match.is_story,
            )
            LOG.info("idea: manual override -> %s [%s]", match.id, chosen.concept)
        else:
            chosen = idea_mod.choose(content_config, situation, used=used_ideas, log=LOG)
        idea = chosen.idea
        if not args.offline:
            photo = photo_fetch.fetch(
                chosen.concept,
                (context_cfg.get("photos") or {}).get("queries") or {},
                out_dir,
                day,
                used=used_photos,
                cfg=context_cfg.get("photos") or {},
                session=session,
                log=LOG,
                timeout=args.timeout,
            )
            if photo is None:
                warnings.append("photo: no relevant, clean photo found; using the text-only layout")
        topic = Topic(
            title=idea.title,
            link="",
            source=f"idea:{idea.id}",
            score=chosen.score,
            product_id=None,
            is_fallback=True,
        )
        try:
            draft = writer.generate(
                idea,
                brand,
                content_config,
                day,
                offline=args.offline,
                api_key=env.get("GEMINI_API_KEY", ""),
                model=env.get("GEMINI_MODEL", writer.DEFAULT_MODEL),
                session=session,
                situation=situation,
            )
        except writer.WriterError as exc:
            errors.append(f"writer: {exc}")
        if draft is not None and draft.source == "offline-fallback":
            warnings.append("writer: Gemini unavailable, used offline templates")

    if draft is not None and not errors:
        issues = validator.validate_draft(draft, brand, catalog)
        errors.extend(issue.message for issue in validator.errors(issues))
        warnings.extend(issue.message for issue in validator.warnings(issues))

    if draft is not None and not errors and image_meta is None:
        try:
            image_meta = graphics.render(
                out_dir / "image.png",
                brand=brand,
                headline=draft.image_headline,
                subline=draft.image_subline,
                kicker=content_config.display_kicker,
                label=type_label_bn(idea.type) if idea else "",
                follow=(
                    content_config.display_follow_story
                    if draft.format == "story"
                    else content_config.display_follow
                ),
                photo=photo.path if photo else None,
                cta=(
                    "আপনার গল্পটা কমেন্টে লিখুন"
                    if draft.format == "story"
                    else (brand.cta_text_bn or brand.cta_text)
                ),
                place=brand.location_bn or brand.location.split(",")[0].strip(),
            )
        except graphics.GraphicsError as exc:
            errors.append(f"graphics: {exc}")

    if image_meta is not None and not errors:
        image_issues = validator.validate_image(image_meta.path, image_meta.sha256)
        errors.extend(issue.message for issue in validator.errors(image_issues))
        warnings.extend(issue.message for issue in validator.warnings(image_issues))

    post_id = post.get("post_id") if post else None
    if topic and draft and image_meta and not errors:
        if not post_id:
            post_id = make_post_id(day.isoformat(), topic.title, draft.caption, image_meta.sha256)
        image_url = _resolve_image_url(args, env, post_id, post)
        post = {
            "post_id": post_id,
            "date": day.isoformat(),
            "created_at": post.get("created_at") if post else _iso(started),
            "updated_at": _iso(datetime.now(timezone.utc)),
            "mode": args.mode,
            "brand": brand.name,
            "timezone": brand.timezone,
            "topic": {
                "title": topic.title,
                "link": topic.link,
                "source": topic.source,
                "score": topic.score,
                "product_id": topic.product_id,
                "is_fallback": topic.is_fallback,
            },
            "draft": {
                "hook": draft.hook,
                "caption": draft.caption,
                "hashtags": list(draft.hashtags),
                "image_headline": draft.image_headline,
                "image_subline": draft.image_subline,
                "product_ids": list(draft.product_ids),
                "source": draft.source,
                "format": draft.format,
            },
            "image": {
                "file": image_meta.path.name,
                "width": image_meta.width,
                "height": image_meta.height,
                "bytes": image_meta.bytes,
                "sha256": image_meta.sha256,
            },
            "photo": photo.as_dict() if photo else None,
            "situation": situation.as_dict() if situation else None,
            "idea": (
                {"id": idea.id, "concept": chosen.concept if chosen else "", "reason": chosen.reason if chosen else ""}
                if idea
                else None
            ),
            "image_url": image_url,
            "targets": {"facebook": {"status": "not_attempted"}, "instagram": {"status": "not_attempted"}},
        }

        (out_dir / "caption.txt").write_text(draft.full_text().strip() + "\n", encoding="utf-8")
        (out_dir / "post.json").write_text(
            json.dumps(post, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    targets: dict[str, dict[str, Any]] = {"facebook": {"status": "not_attempted"}, "instagram": {"status": "not_attempted"}}
    ledger = Ledger(ROOT / args.ledger)

    if args.mode == "queue" and post is not None and not errors and not gates:
        gates.extend(_gate_problems(env, brand, image_url))

        if not gates:
            url_issues = validator.check_public_image(image_url, image_meta.sha256, _fetch_public)
            errors.extend(issue.message for issue in validator.errors(url_issues))

        client: BufferClient | None = None
        if not gates and not errors:
            try:
                client = BufferClient(_buffer_key(env), timeout=args.timeout)
                channels = client.channels(env["BUFFER_ORGANIZATION_ID"])
            except BufferError as exc:
                errors.append(f"buffer: {exc}")
            else:
                expected = {target: env[CHANNEL_ENV[target]] for target in CHANNEL_ENV}
                gates.extend(verify_channels(channels, expected))

        if client is not None and not gates and not errors:
            try:
                records = ledger.records()
                if ledger.corrupt_lines():
                    errors.append("ledger contains corrupt lines; fix state/ledger.jsonl before queueing")
                else:
                    decision = decide(records, post_id, day.isoformat())
                    decision_text = decision.reason
                    LOG.info("duplicate check: %s (%s)", decision.action, decision.reason)
                    if decision.action == "skip":
                        gates.append(decision.reason)
                        existing = next(
                            (record for record in records if record.get("post_id") == post_id),
                            None,
                        ) or next(
                            (
                                record
                                for record in records
                                if record.get("date") == day.isoformat()
                            ),
                            None,
                        )
                        if existing and isinstance(existing.get("targets"), dict):
                            targets = existing["targets"]
                    else:
                        due_at = (env.get("BUFFER_DUE_AT") or "").strip() or None
                        results = _publish(
                            client,
                            decision.targets,
                            env,
                            draft.full_text(),
                            image_url,
                            due_at=due_at,
                            mode="shareNow" if args.now else "addToQueue",
                        )
                        previous = next(
                            (record for record in records if record.get("post_id") == post_id), None
                        )
                        merged = dict(previous.get("targets", {})) if previous else {
                            "facebook": {"status": "not_attempted"},
                            "instagram": {"status": "not_attempted"},
                        }
                        merged.update(results)
                        targets = merged
                        status = _overall(merged)
                        try:
                            ledger.upsert(
                                {
                                    "post_id": post_id,
                                    "date": day.isoformat(),
                                    "created_at": post.get("created_at", _iso(started)),
                                    "updated_at": _iso(datetime.now(timezone.utc)),
                                    "topic": topic.title,
                                    "idea_id": (post.get("idea") or {}).get("id", ""),
                                    "photo": post.get("photo"),
                                    "caption_sha": hashlib.sha256(draft.caption.encode("utf-8")).hexdigest()[:16],
                                    "image_sha": image_meta.sha256,
                                    "image_url": image_url,
                                    "status": status,
                                    "targets": merged,
                                }
                            )
                        except LedgerError as exc:
                            errors.append(f"ledger: {exc} (posts may already be queued)")
                        post["status"] = status
            except LedgerError as exc:
                errors.append(f"ledger: {exc}")

    if post is not None:
        post["targets"] = targets
        status = ""
        if errors:
            status = "BLOCKED"
        elif gates:
            status = "SKIPPED"
        elif args.mode == "preview":
            status = "PREVIEW READY"
        else:
            status = _overall(targets).upper()
        post["status"] = status
        (out_dir / "post.json").write_text(
            json.dumps(post, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    else:
        status = "BLOCKED" if errors else "SKIPPED"

    context = {
        "status": status,
        "started": started,
        "local_time": local_time,
        "date": day.isoformat(),
        "mode": args.mode,
        "timezone": brand.timezone,
        "post_id": post_id,
        "topic": post["topic"] if post else None,
        "draft": post["draft"] if post else None,
        "image": post["image"] if post else None,
        "photo": post.get("photo") if post else None,
        "situation": post.get("situation") if post else None,
        "idea": post.get("idea") if post else None,
        "image_url": image_url,
        "gates": gates,
        "warnings": warnings,
        "errors": errors,
        "targets": targets,
        "decision": decision_text,
        "next_steps": _next_steps(status, args.mode, out_dir),
    }
    text = report.build(context)
    (out_dir / "report.md").write_text(text, encoding="utf-8")
    summary_path = env.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as handle:
                handle.write(text + "\n")
        except OSError as exc:
            LOG.warning("could not append to GITHUB_STEP_SUMMARY: %s", exc)

    LOG.info("status: %s | post: %s | report: %s", status, post_id or "none", out_dir / "report.md")
    if errors:
        _annotate("error", "Post blocked", "; ".join(errors)[:900])
    elif gates:
        _annotate("warning", "Post skipped", "; ".join(gates)[:900])

    if status in ("BLOCKED", "SKIPPED", "PARTIAL", "FAILED", "UNKNOWN"):
        return 1
    return 0


def main(argv: Sequence[str] | None = None, env_file: Path | None = None) -> int:
    args = parse_args(argv)
    applied = load_env_file(env_file) if env_file is not None else []
    setup_logging(getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO))
    if applied:
        LOG.info(".env loaded: %s", ", ".join(applied))
    secrets = collect_secrets(os.environ)
    set_secrets(secrets)
    try:
        return run(args, dict(os.environ))
    except ConfigError as exc:
        LOG.error("configuration error: %s", exc)
        _annotate("error", "Configuration error", str(exc))
        return 2
    except MainError as exc:
        LOG.error("%s", exc)
        _annotate("error", "Run error", str(exc))
        return 2
    except Exception:
        LOG.exception("unexpected failure")
        return 2


if __name__ == "__main__":
    raise SystemExit(main(env_file=ROOT / ".env"))
