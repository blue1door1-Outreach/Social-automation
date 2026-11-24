from __future__ import annotations

from src.duplicate_guard import decide, make_post_id


def test_post_id_is_stable_and_content_sensitive() -> None:
    first = make_post_id("2026-11-23", "Cold mornings", "A caption", "a" * 64)
    second = make_post_id("2026-11-23", "Cold mornings", "A  caption ", "a" * 64)
    other_day = make_post_id("2026-11-24", "Cold mornings", "A caption", "a" * 64)
    other_image = make_post_id("2026-11-23", "Cold mornings", "A caption", "b" * 64)
    assert first == second
    assert first != other_day
    assert first != other_image
    assert first.startswith("2026-11-23-")


def test_publish_when_no_history() -> None:
    decision = decide([], "2026-11-23-abc", "2026-11-23")
    assert decision.action == "publish"
    assert set(decision.targets) == {"facebook", "instagram"}


def test_skip_when_both_targets_queued() -> None:
    record = {
        "post_id": "2026-11-23-abc",
        "date": "2026-11-23",
        "targets": {"facebook": {"status": "queued"}, "instagram": {"status": "queued"}},
    }
    decision = decide([record], "2026-11-23-abc", "2026-11-23")
    assert decision.action == "skip"


def test_resume_only_failed_target() -> None:
    record = {
        "post_id": "2026-11-23-abc",
        "date": "2026-11-23",
        "targets": {"facebook": {"status": "queued"}, "instagram": {"status": "failed"}},
    }
    decision = decide([record], "2026-11-23-abc", "2026-11-23")
    assert decision.action == "resume"
    assert decision.targets == ("instagram",)


def test_unknown_target_blocks_retry() -> None:
    record = {
        "post_id": "2026-11-23-abc",
        "date": "2026-11-23",
        "targets": {"facebook": {"status": "unknown"}, "instagram": {"status": "failed"}},
    }
    decision = decide([record], "2026-11-23-abc", "2026-11-23")
    assert decision.action == "skip"
    assert "unknown" in decision.reason


def test_second_post_same_day_is_refused() -> None:
    record = {
        "post_id": "2026-11-23-other",
        "date": "2026-11-23",
        "targets": {"facebook": {"status": "queued"}, "instagram": {"status": "failed"}},
    }
    decision = decide([record], "2026-11-23-new", "2026-11-23")
    assert decision.action == "skip"


def test_failed_day_can_be_retried() -> None:
    record = {
        "post_id": "2026-11-23-abc",
        "date": "2026-11-23",
        "targets": {"facebook": {"status": "failed"}, "instagram": {"status": "failed"}},
    }
    decision = decide([record], "2026-11-23-abc", "2026-11-23")
    assert decision.action == "publish"


def test_other_days_do_not_block() -> None:
    record = {
        "post_id": "2026-11-22-abc",
        "date": "2026-11-22",
        "targets": {"facebook": {"status": "queued"}, "instagram": {"status": "queued"}},
    }
    decision = decide([record], "2026-11-23-new", "2026-11-23")
    assert decision.action == "publish"
