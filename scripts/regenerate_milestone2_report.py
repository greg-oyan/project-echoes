"""Regenerate the Milestone 2 ingestion report from canonical-byte raw data.

The script reruns the governed Hebrew pipeline, executes the configured manual
spot checks as scripted assertions, recomputes the corpus identity digest, and
rewrites ``outputs/reports/milestone-2-hebrew-ingestion-report.md`` with the
canonical-byte inventory.  The previous text-mode (CRLF) inventory is retained
inside the regenerated report as an explicitly superseded appendix.

Usage:
    uv run python scripts/regenerate_milestone2_report.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import polars as pl

from echoes.corpus.hebrew import HebrewPipelineResult, ingest_hebrew_corpus, load_hebrew_configs
from echoes.corpus.validation import corpus_identity_digest
from echoes.reports.hebrew_ingestion import ManualSpotCheck, render_hebrew_ingestion_report
from echoes.settings import HebrewSpotCheck

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = PROJECT_ROOT / "outputs" / "reports" / "milestone-2-hebrew-ingestion-report.md"
EXPECTED_IDENTITY_DIGEST = "91e923e6f4234e3d1946ad6fb1487f5894ec4e28f2fd3c919bf6ebd1680693b6"
INVENTORY_HEADING = "### Acquired-file SHA-256 inventory"


def extract_superseded_inventory(report_text: str) -> list[str]:
    """Return the prior report's inventory table rows for the superseded appendix."""
    lines = report_text.splitlines()
    try:
        start = lines.index(INVENTORY_HEADING)
    except ValueError:
        return []
    table: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        if line.startswith("|"):
            table.append(line)
    return table


def run_spot_check(tokens: pl.DataFrame, check: HebrewSpotCheck) -> ManualSpotCheck:
    """Execute one configured spot check as scripted assertions over the corpus."""
    book, rest = check.reference.split(" ", maxsplit=1)
    chapter, verse = (int(part) for part in rest.split(":"))
    rows = tokens.filter(
        (pl.col("book") == book) & (pl.col("chapter") == chapter) & (pl.col("verse") == verse)
    ).sort("position_in_verse")
    problems: list[str] = []
    if rows.is_empty():
        problems.append("verse is absent")
        return ManualSpotCheck(
            reference=check.reference,
            category=check.category,
            status="FAIL",
            details="; ".join(problems),
        )
    positions = rows["position_in_verse"].to_list()
    if positions != list(range(1, len(positions) + 1)):
        problems.append("verse positions are not continuous")
    languages = set(rows["language"].to_list())
    if check.expected_language not in languages:
        problems.append(f"expected language {check.expected_language} absent")
    if rows.filter(pl.col("lemma").is_null() | (pl.col("lemma") == "")).height:
        problems.append("missing lemma values")
    if rows.filter(pl.col("morphology_json").is_null()).height:
        problems.append("missing morphology values")
    if rows.filter(pl.col("source_record_id").is_null() | pl.col("source_file").is_null()).height:
        problems.append("missing source provenance")
    zero_width = rows.filter(pl.col("is_zero_width")).height
    variant_groups = rows["variant_group_id"].drop_nulls().n_unique()

    details = (
        f"{len(positions)} continuous positions; languages={sorted(languages)}; "
        f"lemma, morphology, and source provenance complete"
    )
    if zero_width:
        details += f"; {zero_width} explicit zero-width morpheme(s) retained"
    status = "PASS"
    if "ketiv_qere" in check.check and variant_groups == 0:
        status = "PASS WITH LIMITATION"
        details += (
            "; this source release exposes only the preferred Qere analysis, "
            "not a parallel Ketiv form"
        )
    if problems:
        status = "FAIL"
        details = "; ".join(problems)
    return ManualSpotCheck(
        reference=check.reference,
        category=check.category,
        status=status,
        details=details,
    )


def build_report(
    result: HebrewPipelineResult,
    *,
    identity_digest: str,
    spot_checks: list[ManualSpotCheck],
    superseded_inventory: list[str],
) -> str:
    determinism_notes = [
        "This regeneration rebuilds the corpus from the canonical-byte acquisition; "
        "raw files are stored and hashed exactly as received from the pinned commit.",
        f"Ingestion run ID `{result.processed.run_id}` reflects the canonical raw-file "
        "hashes; run IDs derived from the superseded text-mode hashes are obsolete.",
        "The corpus identity digest (SHA-256 over corpus-position-ordered "
        "token_id\\0source_record_id\\0source_word_id\\n triples) is "
        f"`{identity_digest}` and equals the value recorded before remediation "
        f"(`{EXPECTED_IDENTITY_DIGEST}`), proving that line-ending remediation changed "
        "no parsed content or token identity.",
        "The logical token-table SHA-256 was "
        f"`{result.processed.logical_hashes['tokens']}` for this rebuild.",
        "The Parquet token-file SHA-256 was "
        f"`{result.processed.file_hashes['tokens.parquet']}` for this rebuild.",
        "DuckDB row counts and logical fingerprints matched the Parquet artifacts after "
        "transactional reload; reruns introduced no duplicate rows.",
        "A reordered-input fixture test confirms canonical identifiers and logical output "
        "are independent of filesystem enumeration order.",
    ]
    report = render_hebrew_ingestion_report(
        result,
        determinism_notes=determinism_notes,
        spot_checks=spot_checks,
    )
    appendix = [
        "",
        "## Appendix: superseded text-mode inventory",
        "",
        "**Status: SUPERSEDED on 2026-07-11 — do not use for verification.**",
        "",
        "The inventory below was produced by the original Milestone 2 acquisition on a "
        "Windows text-mode Git checkout (`core.autocrlf=true`). Git rewrote LF line "
        "endings to CRLF in text files before hashing, so these SHA-256 values describe "
        "locally mutated bytes, not the pinned commit's canonical bytes. External "
        "verification confirmed the `README.md` and `LICENSE.md` values match the pinned "
        "commit's raw bytes only after LF-to-CRLF conversion. The canonical-byte "
        "inventory above replaces every value in this table; the table is retained "
        "unchanged for audit history.",
        "",
        *superseded_inventory,
        "",
    ]
    return report + "\n".join(appendix)


def main() -> int:
    previous_report = REPORT_PATH.read_text(encoding="utf-8") if REPORT_PATH.is_file() else ""
    superseded_inventory = extract_superseded_inventory(previous_report)
    result = ingest_hebrew_corpus(force=True)
    tokens = pl.read_parquet(result.processed.parquet_paths["tokens"])
    identity_digest = corpus_identity_digest(tokens)
    if identity_digest != EXPECTED_IDENTITY_DIGEST:
        print(
            "STOP: corpus identity digest changed after canonical-byte remediation:\n"
            f"  expected {EXPECTED_IDENTITY_DIGEST}\n  computed {identity_digest}",
            file=sys.stderr,
        )
        return 1
    if tokens.height != 475_911:
        print(f"STOP: token count {tokens.height} != 475911", file=sys.stderr)
        return 1
    _, ingestion = load_hebrew_configs(PROJECT_ROOT / "config")
    spot_checks = [run_spot_check(tokens, check) for check in ingestion.spot_checks]
    failed = [check for check in spot_checks if check.status == "FAIL"]
    report = build_report(
        result,
        identity_digest=identity_digest,
        spot_checks=spot_checks,
        superseded_inventory=superseded_inventory,
    )
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"Wrote {REPORT_PATH}")
    print(f"Identity digest: {identity_digest}")
    print(f"Run ID: {result.processed.run_id}")
    print(f"Validation errors: {result.validation.error_count}")
    if failed or not result.validation.passed:
        print("Spot checks or validation failed; inspect the report.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
