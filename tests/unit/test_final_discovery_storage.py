"""Regression tests for final-discovery JSONL text encoding."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from echoes.final_discovery.storage import (
    FinalDiscoveryStorageError,
    iter_canonical_jsonl,
    iter_jsonl,
)


class _UnicodeRow(BaseModel):
    text: str


def test_iter_jsonl_accepts_utf8_without_weakening_canonical_bytes(tmp_path: Path) -> None:
    text = "λέγει מלך"
    path = tmp_path / "prepared-passages.jsonl"
    payload = json.dumps(
        {"text": text},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    path.write_bytes((payload + "\n").encode("utf-8"))

    assert [row.text for row in iter_jsonl(path, _UnicodeRow)] == [text]
    with pytest.raises(FinalDiscoveryStorageError, match="invalid _UnicodeRow"):
        tuple(iter_canonical_jsonl(path, _UnicodeRow))
