from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from src import main as main_module
from src.buffer_client import BufferError

DAY = "2026-11-23"


class FakeBuffer:
    channel_rows = [
        {"id": "fb1", "service": "facebook"},
        {"id": "ig1", "service": "instagram"},
    ]
    fail_channel = ""
    calls: list[str] = []
    organizations: list[str] = []

    def __init__(self, token, endpoint="https://api.buffer.com", session=None, timeout=30):
        self.token = token

    def channels(self, organization_id=None):
        type(self).organizations.append(str(organization_id))
        return [dict(row) for row in self.channel_rows]

    def create_update(
        self, channel_id, text, image_url, mode="addToQueue", due_at=None, service=""
    ):
        type(self).calls.append(channel_id)
        if type(self).fail_channel == channel_id:
            raise BufferError("simulated rejection")
        return {"id": f"post-{channel_id}", "due_at": due_at}


@pytest.fixture
def verified_config(tmp_path: Path) -> Path:
    target = tmp_path / "config"
    shutil.copytree(main_module.ROOT / "config", target)
    for name in ("brand.json", "products.json"):
        path = target / name
        data = json.loads(path.read_text(encoding="utf-8"))
        data["verified"] = True
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return target


@pytest.fixture
def queue_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_QUEUEING", "true")
    monkeypatch.setenv("BUFFER_API_KEY", "test-token")
    monkeypatch.setenv("BUFFER_ORGANIZATION_ID", "org1")
    monkeypatch.setenv("BUFFER_CHANNEL_FB", "fb1")
    monkeypatch.setenv("BUFFER_CHANNEL_IG", "ig1")
    monkeypatch.setenv("BUFFER_CHANNELS", "facebook,instagram")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def preview(config: Path, out: Path) -> None:
    code = main_module.main(
        ["--offline", "--date", DAY, "--out", str(out), "--config", str(config)]
    )
    assert code == 0


def queue(config: Path, out: Path, ledger: Path, image_url: str | None = None) -> int:
    args = [
        "--mode",
        "queue",
        "--date",
        DAY,
        "--out",
        str(out),
        "--config",
        str(config),
        "--ledger",
        str(ledger),
    ]
    if image_url:
        args.extend(["--image-url", image_url])
    return main_module.main(args)


def ledger_records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _queue_env(due_at: str = "") -> dict[str, str]:
    return {
        "ENABLE_QUEUEING": "true",
        "BUFFER_API_KEY": "key",
        "BUFFER_ORGANIZATION_ID": "org",
        "BUFFER_CHANNEL_FB": "fb",
        "BUFFER_CHANNEL_IG": "ig",
        "BUFFER_CHANNELS": "facebook,instagram",
        "BUFFER_DUE_AT": due_at,
    }


def test_targets_default_to_facebook_only() -> None:
    assert main_module._targets({}) == ("facebook",)
    assert main_module._targets({"BUFFER_CHANNELS": "facebook"}) == ("facebook",)
    assert main_module._targets({"BUFFER_CHANNELS": "facebook,instagram"}) == (
        "facebook",
        "instagram",
    )


def _verified_brand():
    from src.config import Brand, CaptionRules, Catalog

    colors = {key: "#000000" for key in ("primary", "secondary", "accent", "surface", "ink", "muted", "text")}
    brand = Brand(
        name="x",
        tagline="y",
        description="z",
        audience="a",
        location="Dhaka",
        language="en",
        timezone="Asia/Dhaka",
        publish_time_local="10:00",
        verified=True,
        colors=colors,
        tone="plain",
        cta_text="",
        cta_url="",
        caption=CaptionRules(80, 320, 5, 10),
        price_policy="never",
        stock_policy="never",
        required_hashtags=("#X",),
        banned_phrases=(),
        notes=(),
        hashtag_pools={"winter": ("#Winter",)},
    )
    catalog = Catalog(
        niche="winter",
        season="",
        currency="BDT",
        show_prices=False,
        verified=True,
        products=(),
    )
    return brand


def test_due_at_must_be_iso() -> None:
    brand = _verified_brand()

    bad = main_module._gate_problems(
        _queue_env("tomorrow"), brand, "https://example.com/a.png"
    )
    assert any("BUFFER_DUE_AT" in problem for problem in bad), bad

    naive = main_module._gate_problems(
        _queue_env("2026-11-24T04:00:00"), brand, "https://example.com/a.png"
    )
    assert any("timezone" in problem for problem in naive), naive

    good = main_module._gate_problems(
        _queue_env("2026-11-24T04:00:00Z"), brand, "https://example.com/a.png"
    )
    assert good == [], good


def test_malformed_ids_are_gate_problems() -> None:
    brand = _verified_brand()

    env = _queue_env()
    env["BUFFER_ORGANIZATION_ID"] = "6b0416841dfa25309243c31d name=My organization"
    problems = main_module._gate_problems(env, brand, "https://example.com/a.png")
    assert any("BUFFER_ORGANIZATION_ID looks malformed" in problem for problem in problems), problems

    env = _queue_env()
    env["BUFFER_CHANNEL_FB"] = "6b041845 id=extra"
    problems = main_module._gate_problems(env, brand, "https://example.com/a.png")
    assert any("BUFFER_CHANNEL_FB looks malformed" in problem for problem in problems), problems


def test_queue_publishes_and_refuses_a_second_run(
    tmp_path: Path,
    verified_config: Path,
    queue_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeBuffer.calls.clear()
    FakeBuffer.organizations.clear()
    FakeBuffer.fail_channel = ""
    monkeypatch.setattr(main_module, "BufferClient", FakeBuffer)

    out = tmp_path / "out"
    ledger = tmp_path / "ledger.jsonl"
    preview(verified_config, out)

    image = out / DAY / "image.png"
    monkeypatch.setattr(
        main_module, "_fetch_public", lambda url: ("image/png", image.read_bytes())
    )

    assert (
        queue(verified_config, out, ledger, image_url="https://example.com/post.png")
        == 0
    )
    assert FakeBuffer.calls == ["fb1", "ig1"]
    assert FakeBuffer.organizations == ["org1"]

    record = ledger_records(ledger)[-1]
    assert record["status"] == "queued"
    assert record["targets"]["facebook"]["status"] == "queued"
    assert record["targets"]["instagram"]["status"] == "queued"

    post = json.loads((out / DAY / "post.json").read_text(encoding="utf-8"))
    assert post["status"] == "QUEUED"
    assert "QUEUED" in (out / DAY / "report.md").read_text(encoding="utf-8")

    # A second run on the same day must not create another post, even though the
    # image URL is saved in post.json and the gate would otherwise pass.
    assert queue(verified_config, out, ledger) == 1
    assert FakeBuffer.calls == ["fb1", "ig1"]
    report = (out / DAY / "report.md").read_text(encoding="utf-8")
    assert "SKIPPED" in report
    assert "already" in report


def test_partial_failure_resumes_only_the_failed_target(
    tmp_path: Path,
    verified_config: Path,
    queue_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeBuffer.calls.clear()
    FakeBuffer.fail_channel = "ig1"
    monkeypatch.setattr(main_module, "BufferClient", FakeBuffer)

    out = tmp_path / "out"
    ledger = tmp_path / "ledger.jsonl"
    preview(verified_config, out)

    image = out / DAY / "image.png"
    monkeypatch.setattr(
        main_module, "_fetch_public", lambda url: ("image/png", image.read_bytes())
    )

    assert (
        queue(verified_config, out, ledger, image_url="https://example.com/post.png")
        == 1
    )
    record = ledger_records(ledger)[-1]
    assert record["status"] == "partial"
    assert record["targets"]["facebook"]["status"] == "queued"
    assert record["targets"]["instagram"]["status"] == "failed"

    FakeBuffer.fail_channel = ""
    assert queue(verified_config, out, ledger) == 0
    assert FakeBuffer.calls == ["fb1", "ig1", "ig1"]

    record = ledger_records(ledger)[-1]
    assert record["status"] == "queued"
    assert record["targets"]["facebook"]["status"] == "queued"
    assert record["targets"]["instagram"]["status"] == "queued"


def test_unknown_outcome_blocks_retry(
    tmp_path: Path,
    verified_config: Path,
    queue_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.buffer_client import BufferUncertain

    class UncertainBuffer(FakeBuffer):
        def create_update(
            self, channel_id, text, image_url, mode="addToQueue", due_at=None, service=""
        ):
            type(self).calls.append(channel_id)
            raise BufferUncertain("timed out")

    FakeBuffer.calls.clear()
    monkeypatch.setattr(main_module, "BufferClient", UncertainBuffer)

    out = tmp_path / "out"
    ledger = tmp_path / "ledger.jsonl"
    preview(verified_config, out)
    image = out / DAY / "image.png"
    monkeypatch.setattr(
        main_module, "_fetch_public", lambda url: ("image/png", image.read_bytes())
    )

    assert (
        queue(verified_config, out, ledger, image_url="https://example.com/post.png")
        == 1
    )
    record = ledger_records(ledger)[-1]
    assert record["status"] == "unknown"

    calls_before = list(UncertainBuffer.calls)
    assert queue(verified_config, out, ledger) == 1
    assert UncertainBuffer.calls == calls_before
    assert "unknown outcome" in (out / DAY / "report.md").read_text(encoding="utf-8")
