from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.main import main


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "GEMINI_API_KEY",
        "ENABLE_QUEUEING",
        "BUFFER_API_KEY",
        "BUFFER_ORGANIZATION_ID",
        "BUFFER_ACCESS_TOKEN",
        "BUFFER_CHANNEL_FB",
        "BUFFER_CHANNEL_IG",
        "PUBLIC_IMAGE_BASE_URL",
        "GITHUB_STEP_SUMMARY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_preview_end_to_end(tmp_path: Path) -> None:
    code = main(["--offline", "--date", "2026-11-23", "--out", str(tmp_path)])
    assert code == 0

    out = tmp_path / "2026-11-23"
    assert (out / "image.png").exists()
    assert (out / "caption.txt").exists()
    assert (out / "report.md").exists()

    post = json.loads((out / "post.json").read_text(encoding="utf-8"))
    assert post["status"] == "PREVIEW READY"
    assert post["targets"]["facebook"]["status"] == "not_attempted"
    assert post["date"] == "2026-11-23"
    assert post["draft"]["caption"]
    assert post["topic"]["title"]

    report = (out / "report.md").read_text(encoding="utf-8")
    assert "PREVIEW READY" in report
    assert "not attempted (preview)" in report


def test_preview_is_repeatable(tmp_path: Path) -> None:
    assert main(["--offline", "--date", "2026-11-23", "--out", str(tmp_path)]) == 0
    first = (tmp_path / "2026-11-23" / "post.json").read_text(encoding="utf-8")
    assert main(["--offline", "--date", "2026-11-23", "--out", str(tmp_path)]) == 0
    second = (tmp_path / "2026-11-23" / "post.json").read_text(encoding="utf-8")
    assert json.loads(first)["post_id"] == json.loads(second)["post_id"]


def test_queue_without_artifacts_is_skipped(tmp_path: Path) -> None:
    code = main(["--mode", "queue", "--date", "2026-11-23", "--out", str(tmp_path)])
    assert code == 1
    report = (tmp_path / "2026-11-23" / "report.md").read_text(encoding="utf-8")
    assert "SKIPPED" in report
    assert "Preview first" in report or "preview" in report


def test_queue_gate_blocks_without_environment(tmp_path: Path) -> None:
    assert main(["--offline", "--date", "2026-11-23", "--out", str(tmp_path)]) == 0
    code = main(["--mode", "queue", "--date", "2026-11-23", "--out", str(tmp_path)])
    assert code == 1
    report = (tmp_path / "2026-11-23" / "report.md").read_text(encoding="utf-8")
    assert "ENABLE_QUEUEING" in report


def test_bad_date_is_a_configuration_error(tmp_path: Path) -> None:
    assert main(["--offline", "--date", "23-11-2026", "--out", str(tmp_path)]) == 2


def test_queue_with_corrupt_post_is_skipped_not_a_crash(tmp_path: Path) -> None:
    out = tmp_path / "2026-11-23"
    out.mkdir(parents=True)
    (out / "post.json").write_text("{not valid json", encoding="utf-8")
    code = main(["--mode", "queue", "--date", "2026-11-23", "--out", str(tmp_path)])
    assert code == 1
    assert "SKIPPED" in (out / "report.md").read_text(encoding="utf-8")


def test_queue_with_incomplete_post_is_skipped(tmp_path: Path) -> None:
    out = tmp_path / "2026-11-23"
    out.mkdir(parents=True)
    (out / "post.json").write_text('{"post_id": "x"}', encoding="utf-8")
    code = main(["--mode", "queue", "--date", "2026-11-23", "--out", str(tmp_path)])
    assert code == 1
