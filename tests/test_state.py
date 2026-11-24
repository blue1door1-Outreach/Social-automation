from __future__ import annotations

import json
from pathlib import Path

from src.state import Ledger


def test_ledger_roundtrip(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "state" / "ledger.jsonl")
    ledger.append({"post_id": "a", "date": "2026-11-23"})
    ledger.append({"post_id": "b", "date": "2026-11-24"})
    assert [record["post_id"] for record in ledger.records()] == ["a", "b"]
    assert not (tmp_path / "state" / "ledger.jsonl.tmp").exists()


def test_upsert_replaces_same_post_id(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.append({"post_id": "a", "status": "failed"})
    ledger.upsert({"post_id": "a", "status": "queued"})
    records = ledger.records()
    assert len(records) == 1
    assert records[0]["status"] == "queued"


def test_upsert_appends_new_post_id(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.upsert({"post_id": "a"})
    ledger.upsert({"post_id": "b"})
    assert len(ledger.records()) == 2


def test_corrupt_lines_are_counted_not_fatal(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    path.write_text('{"post_id": "a"}\nnot json\n', encoding="utf-8")
    ledger = Ledger(path)
    assert len(ledger.records()) == 1
    assert ledger.corrupt_lines() == 1
    ledger.append({"post_id": "b"})
    assert len(ledger.records()) == 2
    assert ledger.corrupt_lines() == 0
