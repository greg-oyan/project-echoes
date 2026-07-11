"""Source-edition identity must remain isolated from later mapping layers."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import polars as pl
import pytest

import echoes.corpus.token_ids as token_ids
from echoes.corpus.token_ids import TokenIdentityError, generate_source_edition_token_id
from echoes.corpus.validation import corpus_identity_digest


def _identity() -> str:
    return generate_source_edition_token_id(
        book_identifier="GEN",
        chapter=1,
        verse=2,
        source_token_position=3,
        source_subtoken_position=1,
        source_record_id="source-record-1",
        disambiguate_with_source_record=True,
    )


def test_token_identity_module_imports_no_crosswalk_layer() -> None:
    tree = ast.parse(inspect.getsource(token_ids))
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}

    assert imported_modules == {"__future__", "hashlib", "re"}
    assert "crosswalk" not in inspect.signature(generate_source_edition_token_id).parameters


def test_crosswalk_file_add_change_and_removal_cannot_change_identity(
    tmp_path: Path,
) -> None:
    before = _identity()
    crosswalk = tmp_path / "versification-crosswalk.yaml"
    crosswalk.write_text("GEN 1:2: GEN 1:3\n", encoding="utf-8")
    after_add = _identity()
    crosswalk.write_text("GEN 1:2: EXO 2:1\n", encoding="utf-8")
    after_change = _identity()
    crosswalk.unlink()
    after_removal = _identity()

    assert {before, after_add, after_change, after_removal} == {before}


def test_source_identity_is_stable_and_requires_explicit_variant_disambiguation() -> None:
    assert _identity() == _identity()
    with pytest.raises(TokenIdentityError, match="source_record_id is required"):
        generate_source_edition_token_id(
            book_identifier="GEN",
            chapter=1,
            verse=2,
            source_token_position=3,
            disambiguate_with_source_record=True,
        )


def test_corpus_identity_digest_orders_by_corpus_position_and_detects_changes() -> None:
    frame = pl.DataFrame(
        {
            "position_in_corpus": [2, 1],
            "token_id": ["HB_GEN_001_001_0002", "HB_GEN_001_001_0001"],
            "source_record_id": ["o2", "o1"],
            "source_word_id": ["GEN 1:1!2", "GEN 1:1!1"],
        }
    )
    reordered = frame.sort("token_id")

    digest = corpus_identity_digest(frame)
    assert digest == corpus_identity_digest(reordered)

    changed = frame.with_columns(pl.col("source_record_id").str.replace("o2", "different"))
    assert corpus_identity_digest(changed) != digest
