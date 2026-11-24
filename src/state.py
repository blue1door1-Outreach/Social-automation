"""Append-only publish ledger.

One JSON object per line. Writes are atomic (temp file + os.replace) so a
crashed run cannot leave a half-written ledger behind. The file is meant to be
committed to the repository; that is what makes duplicate prevention survive
across workflow runs.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class LedgerError(RuntimeError):
    pass


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)

    def records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise LedgerError(f"cannot read ledger {self.path}: {exc}") from exc

        records: list[dict[str, Any]] = []
        for number, line in enumerate(raw.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                # Keep going; a corrupt line must not block today's gate, but
                # the caller surfaces the count via corrupt_lines().
                continue
            if isinstance(record, dict):
                records.append(record)
        return records

    def corrupt_lines(self) -> int:
        if not self.path.exists():
            return 0
        bad = 0
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                json.loads(line)
            except json.JSONDecodeError:
                bad += 1
        return bad

    def _write(self, records: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        payload = "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records
        )
        try:
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as exc:
            raise LedgerError(f"cannot write ledger {self.path}: {exc}") from exc

    def append(self, record: dict[str, Any]) -> None:
        records = self.records()
        records.append(record)
        self._write(records)

    def upsert(self, record: dict[str, Any]) -> None:
        records = self.records()
        post_id = record.get("post_id")
        for index, existing in enumerate(records):
            if existing.get("post_id") == post_id:
                records[index] = record
                break
        else:
            records.append(record)
        self._write(records)
