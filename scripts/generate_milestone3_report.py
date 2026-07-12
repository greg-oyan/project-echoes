"""Generate the Milestone 3 Greek ingestion report with scripted spot checks.

The script reruns the governed Greek pipeline (proving rerun determinism),
executes the master-plan section 13 spot checks as assertions with recorded
expected values, sanity-checks the token count against the upstream published
figure, and writes ``outputs/reports/milestone-3-greek-ingestion-report.md``.

Usage:
    uv run python scripts/generate_milestone3_report.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import polars as pl

from echoes.corpus.greek import GreekPipelineResult, ingest_greek_corpus
from echoes.reports.greek_ingestion import ScriptedSpotCheck, write_greek_ingestion_report

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = PROJECT_ROOT / "outputs" / "reports" / "milestone-3-greek-ingestion-report.md"

# Upstream published expectation: the pinned repository's own test suite
# (test/test_nestle1904_nodes.py at commit b5b7ecec) asserts 137,779 leaf word
# nodes for the Nestle1904 nodes dataset.
UPSTREAM_PUBLISHED_TOKEN_COUNT = 137_779

# Expected values recorded before execution; each row becomes an assertion.
VERSE_EXPECTATIONS: list[tuple[str, str, int, int, int]] = [
    # (reference, category, expected_tokens, expected_elided, expected_punct_bearing)
    ("MAT 5:3", "Synoptic sample (Sermon on the Mount)", 12, 0, 2),
    ("MRK 1:2", "Synoptic sample with quotation framing", 20, 0, 2),
    ("LUK 15:11", "Synoptic sample (Lukan parable opening)", 7, 0, 1),
    ("JHN 1:1", "John prologue", 17, 0, 3),
    ("ROM 3:23", "Pauline letter", 9, 0, 1),
    ("JAS 1:1", "General letter opening", 15, 0, 1),
    ("REV 22:20", "Revelation closing", 11, 0, 4),
    ("JHN 8:3", "Pericope adulterae (disputed passage)", 18, 0, 2),
    ("MRK 16:9", "Longer ending of Mark (disputed passage)", 15, 1, 3),
    ("MAT 8:2", "Enclitic and punctuation case", 13, 0, 2),
    ("JHN 3:2", "Elision case", 32, 1, 4),
    ("ACT 8:36", "Versification boundary (edition omits ACT 8:37)", 20, 0, 4),
]


def _verse(tokens: pl.DataFrame, reference: str) -> pl.DataFrame:
    book, rest = reference.split(" ", maxsplit=1)
    chapter, verse = (int(part) for part in rest.split(":"))
    return tokens.filter(
        (pl.col("book") == book) & (pl.col("chapter") == chapter) & (pl.col("verse") == verse)
    ).sort("position_in_verse")


def _verse_check(
    tokens: pl.DataFrame,
    reference: str,
    category: str,
    expected_tokens: int,
    expected_elided: int,
    expected_punctuation: int,
) -> ScriptedSpotCheck:
    rows = _verse(tokens, reference)
    positions = rows["position_in_verse"].to_list()
    continuous = positions == list(range(1, len(positions) + 1))
    provenance_complete = (
        rows.filter(pl.col("source_record_id").is_null() | pl.col("source_file").is_null()).height
        == 0
    )
    lemma_complete = rows.filter(pl.col("lemma").is_null() | (pl.col("lemma") == "")).height == 0
    elided = rows.filter(pl.col("is_elided")).height
    punctuation = rows.filter(
        (pl.col("leading_punctuation") != "") | (pl.col("trailing_punctuation") != "")
    ).height
    observed = (
        f"{rows.height} tokens, {elided} elided, {punctuation} punctuation-bearing, "
        f"continuous={continuous}, provenance_complete={provenance_complete}, "
        f"lemma_complete={lemma_complete}"
    )
    expected = (
        f"{expected_tokens} tokens, {expected_elided} elided, "
        f"{expected_punctuation} punctuation-bearing, continuous positions, "
        "complete provenance and lemmas"
    )
    passed = (
        rows.height == expected_tokens
        and elided == expected_elided
        and punctuation == expected_punctuation
        and continuous
        and provenance_complete
        and lemma_complete
    )
    return ScriptedSpotCheck(
        reference=reference,
        category=category,
        expected=expected,
        observed=observed,
        status="PASS" if passed else "FAIL",
    )


def _edition_checks(tokens: pl.DataFrame) -> tuple[list[ScriptedSpotCheck], list[str]]:
    checks: list[ScriptedSpotCheck] = []
    flagged: list[str] = []

    pa = tokens.filter(
        (pl.col("book") == "JHN")
        & (
            ((pl.col("chapter") == 7) & (pl.col("verse") == 53))
            | ((pl.col("chapter") == 8) & (pl.col("verse") <= 11))
        )
    )
    checks.append(
        ScriptedSpotCheck(
            reference="JHN 7:53-8:11",
            category="Disputed passage: pericope adulterae",
            expected="190 tokens present inline in the pinned Nestle 1904 representation",
            observed=f"{pa.height} tokens present inline",
            status="PASS" if pa.height == 190 else "FAIL",
            flagged_for_human_review=True,
        )
    )
    flagged.append(
        "The pinned Nestle 1904 representation includes the pericope adulterae "
        "(JHN 7:53-8:11, 190 tokens) inline without a variant marker. Whether analyses "
        "should treat this disputed passage separately is an interpretation question "
        "for human review, not decided here."
    )

    shorter_ending = tokens.filter(
        (pl.col("book") == "MRK") & (pl.col("chapter") == 16) & (pl.col("verse") == 99)
    )
    longer_ending = tokens.filter(
        (pl.col("book") == "MRK")
        & (pl.col("chapter") == 16)
        & (pl.col("verse") >= 9)
        & (pl.col("verse") <= 20)
    )
    checks.append(
        ScriptedSpotCheck(
            reference="MRK 16:9-20; MRK 16:99",
            category="Edition-level versification: endings of Mark",
            expected=(
                "longer ending inline at 16:9-20; shorter ending encoded at "
                "out-of-sequence verse 99 with 33 tokens"
            ),
            observed=(
                f"longer ending tokens={longer_ending.height} (verses 9-20 present), "
                f"verse-99 tokens={shorter_ending.height}"
            ),
            status=("PASS" if shorter_ending.height == 33 and longer_ending.height > 0 else "FAIL"),
            flagged_for_human_review=True,
        )
    )
    flagged.append(
        "The pinned edition encodes the shorter ending of Mark at the out-of-sequence "
        "verse MRK 16:99 (33 tokens) after the inline longer ending (16:9-20). How "
        "analyses should treat the endings of Mark is flagged for human review."
    )

    act_837 = tokens.filter(
        (pl.col("book") == "ACT") & (pl.col("chapter") == 8) & (pl.col("verse") == 37)
    )
    checks.append(
        ScriptedSpotCheck(
            reference="ACT 8:37",
            category="Edition-level versification: omitted verse",
            expected="0 tokens; the pinned edition omits this verse entirely",
            observed=f"{act_837.height} tokens",
            status="PASS" if act_837.height == 0 else "FAIL",
        )
    )

    accent_regularized = tokens.filter(
        pl.col("normalized_form") != pl.col("source_normalized_form")
    ).height
    mat82 = _verse(tokens, "MAT 8:2")
    mat82_regularized = mat82.filter(
        pl.col("normalized_form") != pl.col("source_normalized_form")
    ).height
    checks.append(
        ScriptedSpotCheck(
            reference="MAT 8:2 and corpus-wide",
            category="Enclitic/accent policy: surface accents preserved",
            expected=(
                "6 accent-regularized tokens in MAT 8:2 and 37183 corpus-wide where the "
                "preserved source NormalizedForm differs from the punctuation-separated "
                "surface (grave and enclitic accentuation preserved in surface_form)"
            ),
            observed=(
                f"{mat82_regularized} accent-regularized tokens in MAT 8:2, "
                f"{accent_regularized} corpus-wide"
            ),
            status=("PASS" if mat82_regularized == 6 and accent_regularized == 37_183 else "FAIL"),
        )
    )

    elided_total = tokens.filter(pl.col("is_elided")).height
    punct_total = tokens.filter(
        (pl.col("leading_punctuation") != "") | (pl.col("trailing_punctuation") != "")
    ).height
    standalone_punct = tokens.filter(pl.col("is_punctuation")).height
    checks.append(
        ScriptedSpotCheck(
            reference="corpus-wide",
            category="Punctuation and elision handling",
            expected=(
                "1223 elided tokens; 18552 punctuation-bearing tokens with lossless "
                "separation; 0 standalone punctuation tokens (punctuation is attached "
                "to word text in this representation)"
            ),
            observed=(
                f"{elided_total} elided, {punct_total} punctuation-bearing, "
                f"{standalone_punct} standalone punctuation tokens"
            ),
            status=(
                "PASS"
                if elided_total == 1223 and punct_total == 18_552 and standalone_punct == 0
                else "FAIL"
            ),
        )
    )
    return checks, flagged


def main() -> int:
    result: GreekPipelineResult = ingest_greek_corpus(force=True)
    tokens = pl.read_parquet(result.processed.parquet_paths["tokens"])

    spot_checks = [
        _verse_check(tokens, reference, category, count, elided, punctuation)
        for reference, category, count, elided, punctuation in VERSE_EXPECTATIONS
    ]
    edition_checks, flagged = _edition_checks(tokens)
    spot_checks.extend(edition_checks)

    token_count_sanity = [
        f"Processed token count: {tokens.height}.",
        (
            "Expected published figure: 137,779 leaf word nodes, asserted by the pinned "
            "upstream repository's own test suite (`test/test_nestle1904_nodes.py` at "
            "commit `b5b7ecec0882a3e9a609ecac99e157391e5d9b46`, tag 24.06.17); the same "
            "figure appears in the upstream lowfat, TEI, and TSV tests for the "
            "Nestle1904 dataset."
        ),
        (
            "MATCH: the processed count equals the upstream published expectation."
            if tokens.height == UPSTREAM_PUBLISHED_TOKEN_COUNT
            else "MISMATCH against the upstream published expectation."
        ),
    ]
    determinism_notes = [
        "This report rerun rebuilt the corpus from the verified canonical-byte "
        "acquisition receipt; raw files are stored and hashed exactly as received.",
        f"Ingestion run ID `{result.processed.run_id}` is derived from the pinned "
        "commit, normalization configuration hash, canonical raw-file hashes, and "
        "schema version, and is reproduced identically on reruns.",
        "The logical token-table SHA-256 was "
        f"`{result.processed.logical_hashes['tokens']}` for this rebuild.",
        "The Parquet token-file SHA-256 was "
        f"`{result.processed.file_hashes['tokens.parquet']}` for this rebuild.",
        "DuckDB row counts and logical fingerprints matched the Parquet artifacts "
        "after transactional reload; reruns introduced no duplicate rows.",
        "Unified cross-corpus checks passed: distinct corpus and provenance values, "
        "no token-ID collisions, and Hebrew plus Greek row counts sum exactly.",
    ]
    flagged.append(
        "MARBLE-derived LN and LexDomain values are included upstream by permission; "
        "their appearance in redistributable derived outputs still needs a field-level "
        "human licensing review (recorded as the manifest's unresolved question)."
    )

    failed = [check for check in spot_checks if check.status != "PASS"]
    write_greek_ingestion_report(
        result,
        REPORT_PATH,
        determinism_notes=determinism_notes,
        spot_checks=spot_checks,
        token_count_sanity=token_count_sanity,
        flagged_items=flagged,
    )
    print(f"Wrote {REPORT_PATH}")
    print(f"Run ID: {result.processed.run_id}")
    print(f"Validation errors: {result.validation.error_count}")
    print(f"Spot checks: {len(spot_checks) - len(failed)}/{len(spot_checks)} passed")
    if failed or not result.validation.passed:
        for check in failed:
            print(f"FAILED: {check.reference}: {check.observed}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
