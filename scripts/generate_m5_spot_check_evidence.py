"""Generate deterministic, source-text-free Milestone 5 spot-check evidence.

The tracked JSON specification selects passages by governed analytical identity
fields.  This script verifies authoritative membership, ordering,
reconstruction/lemma sequence integrity, provenance, flags, exclusions, and
window neighbors against the local full-corpus DuckDB artifact.  It hashes but
never writes biblical text, lemmas, or token identifiers to the report bundle.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import duckdb


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _rows(cursor: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    columns = [str(item[0]) for item in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _select_passages(
    connection: duckdb.DuckDBPyConnection,
    check: dict[str, Any],
    *,
    profile: str | None = None,
    reading: str | None = None,
) -> list[dict[str, Any]]:
    parameters: list[object] = [
        check["corpus"],
        profile or check["analysis_profile"],
        reading or check["analysis_reading"],
        check["granularity"],
    ]
    selection = check["selection"]
    if selection == "exact_sequence":
        predicate = "reference_sequence_json = ?"
        parameters.append(_canonical(check["references"]))
    elif selection == "verse_set":
        placeholders = ",".join("?" for _ in check["references"])
        predicate = (
            f"start_reference IN ({placeholders}) "
            "AND end_reference = start_reference "
            "AND json_array_length(reference_sequence_json) = 1"
        )
        parameters.extend(check["references"])
    elif selection == "absence_multiverse_sentence":
        predicate = "json_array_length(reference_sequence_json) > 1"
    else:
        raise ValueError(f"unknown selection for {check['check_id']}: {selection}")
    return _rows(
        connection.execute(
            f"""
            SELECT * FROM passages
            WHERE corpus = ? AND analysis_profile = ? AND analysis_reading = ?
              AND granularity = ? AND {predicate}
            ORDER BY book_order, start_stream_position_in_corpus, passage_id
            """,
            parameters,
        )
    )


def _membership(
    connection: duckdb.DuckDBPyConnection, passage_ids: list[str]
) -> list[dict[str, Any]]:
    if not passage_ids:
        return []
    placeholders = ",".join("?" for _ in passage_ids)
    return _rows(
        connection.execute(
            f"""
            SELECT * FROM m5_spot_membership WHERE passage_id IN ({placeholders})
            ORDER BY passage_id, position_in_passage
            """,
            passage_ids,
        )
    )


def _source_facets(
    connection: duckdb.DuckDBPyConnection, token_ids: list[str]
) -> tuple[dict[str, int], int, int, int]:
    if not token_ids:
        return {}, 0, 0, 0
    placeholders = ",".join("?" for _ in token_ids)
    row = connection.execute(
        f"""
        SELECT json_group_object(language, language_count),
               sum(elided_count), sum(leading_count), sum(trailing_count)
        FROM (
          SELECT language, count(*) AS language_count,
                 count(*) FILTER (WHERE is_elided) AS elided_count,
                 count(*) FILTER (WHERE leading_punctuation <> '') AS leading_count,
                 count(*) FILTER (WHERE trailing_punctuation <> '') AS trailing_count
          FROM m5_spot_source_tokens WHERE token_id IN ({placeholders}) GROUP BY language
        )
        """,
        token_ids,
    ).fetchone()
    languages = json.loads(row[0]) if row and row[0] else {}
    return (
        {str(key): int(value) for key, value in languages.items()},
        int(row[1] or 0),
        int(row[2] or 0),
        int(row[3] or 0),
    )


def _exclusion_count(connection: duckdb.DuckDBPyConnection, check: dict[str, Any]) -> int:
    locus_ids = check.get("locus_ids", [])
    if locus_ids:
        placeholders = ",".join("?" for _ in locus_ids)
        parameters: list[object] = [
            check["corpus"],
            check["analysis_profile"],
            check["analysis_reading"],
            *locus_ids,
        ]
        granularity = check.get("exclusion_granularity")
        suffix = ""
        if granularity:
            suffix = " AND granularity = ?"
            parameters.append(granularity)
        return int(
            connection.execute(
                f"""
                SELECT count(*) FROM segmentation_exclusions
                WHERE corpus = ? AND analysis_profile = ? AND analysis_reading = ?
                  AND locus_id IN ({placeholders}){suffix}
                """,
                parameters,
            ).fetchone()[0]
        )
    references = check.get("references", [])
    if not references:
        return 0
    placeholders = ",".join("?" for _ in references)
    return int(
        connection.execute(
            f"""
            SELECT count(*) FROM segmentation_exclusions
            WHERE corpus = ? AND analysis_profile = ? AND analysis_reading = ?
              AND granularity = ? AND source_reference IN ({placeholders})
            """,
            [
                check["corpus"],
                check["analysis_profile"],
                check["analysis_reading"],
                check["granularity"],
                *references,
            ],
        ).fetchone()[0]
    )


def _chapter_crossing(row: dict[str, Any]) -> bool:
    pattern = re.compile(r"^[A-Z0-9]{3} ([0-9]+):[0-9]+$")
    start = pattern.match(str(row["start_reference"]))
    end = pattern.match(str(row["end_reference"]))
    return bool(start and end and start.group(1) != end.group(1))


def _check_neighbors(
    connection: duckdb.DuckDBPyConnection,
    passages: list[dict[str, Any]],
    membership_by_passage: dict[str, list[dict[str, Any]]],
) -> bool:
    neighbor_ids = sorted(
        {
            str(value)
            for passage in passages
            for value in (passage["previous_passage_id"], passage["next_passage_id"])
            if value
        }
    )
    neighbors = _membership(connection, neighbor_ids)
    neighbor_tokens: dict[str, set[str]] = {}
    for row in neighbors:
        neighbor_tokens.setdefault(str(row["passage_id"]), set()).add(str(row["token_id"]))
    for passage in passages:
        passage_id = str(passage["passage_id"])
        tokens = {str(row["token_id"]) for row in membership_by_passage[passage_id]}
        for direction in ("previous", "next"):
            neighbor_id = passage[f"{direction}_passage_id"]
            stored = passage[f"overlap_with_{direction}_token_count"]
            actual = (
                len(tokens & neighbor_tokens.get(str(neighbor_id), set())) if neighbor_id else 0
            )
            if int(stored or 0) != actual:
                return False
    return True


def _content_payload(passages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "references": json.loads(str(row["reference_sequence_json"])),
            "tokens": json.loads(str(row["token_ids_json"])),
            "surface": row["surface_text"],
            "normalized": row["normalized_text"],
            "unpointed": row["unpointed_text"],
            "folded": row["folded_text"],
            "lemmas": json.loads(str(row["lemma_sequence_json"])),
        }
        for row in passages
    ]


def _run_check(connection: duckdb.DuckDBPyConnection, check: dict[str, Any]) -> dict[str, object]:
    passages = _select_passages(connection, check)
    passage_ids = [str(row["passage_id"]) for row in passages]
    membership = _membership(connection, passage_ids)
    membership_by_passage: dict[str, list[dict[str, Any]]] = {key: [] for key in passage_ids}
    for row in membership:
        membership_by_passage[str(row["passage_id"])].append(row)

    failures: list[str] = []
    expected = check["expected"]
    counters = {
        "passage_count": len(passages),
        "membership_count": len(membership),
        "disputed_count": sum(bool(row["disputed_passage_flag"]) for row in passages),
        "reference_gap_count": sum(bool(row["reference_gap"]) for row in passages),
        "ketiv_uncertainty_count": sum(
            bool(row["ketiv_structural_uncertainty"]) for row in passages
        ),
        "chapter_crossing_count": sum(_chapter_crossing(row) for row in passages),
        "exclusion_count": _exclusion_count(connection, check),
    }
    for key in (
        "passage_count",
        "disputed_count",
        "reference_gap_count",
        "ketiv_uncertainty_count",
        "chapter_crossing_count",
        "exclusion_count",
    ):
        if counters[key] != expected[key]:
            failures.append(f"{key}: expected {expected[key]}, observed {counters[key]}")

    source_ids: set[str] = set()
    provenance_payload: list[dict[str, object]] = []
    token_order_ok = True
    reconstruction_ok = True
    lemma_sequence_ok = True
    for passage in passages:
        passage_id = str(passage["passage_id"])
        rows = membership_by_passage[passage_id]
        positions = [int(row["position_in_passage"]) for row in rows]
        token_ids = [str(row["token_id"]) for row in rows]
        token_order_ok &= positions == list(range(1, len(rows) + 1))
        token_order_ok &= token_ids == json.loads(str(passage["token_ids_json"]))
        token_order_ok &= len(rows) == int(passage["token_count"])
        lemmas = json.loads(str(passage["lemma_sequence_json"]))
        lemma_sequence_ok &= isinstance(lemmas, list) and len(lemmas) == len(rows)
        reconstruction_fields = (
            ("surface_text", "normalized_text", "unpointed_text")
            if check["corpus"] == "hebrew"
            else ("surface_text", "normalized_text", "folded_text")
        )
        reconstruction_ok &= all(isinstance(passage[field], str) for field in reconstruction_fields)
        source_ids.update(json.loads(str(passage["source_ids_json"])))
        provenance_payload.extend(
            {
                "source_id": row["source_id"],
                "source_version": row["source_version"],
                "source_edition_reference": row["source_edition_reference"],
            }
            for row in rows
        )
    if not token_order_ok:
        failures.append("authoritative membership or token order mismatch")
    if not reconstruction_ok:
        failures.append("language-aware reconstruction field missing")
    if not lemma_sequence_ok:
        failures.append("lemma sequence does not match membership length")
    if sorted(source_ids) != sorted(expected["source_ids"]):
        failures.append(
            f"source_ids: expected {expected['source_ids']}, observed {sorted(source_ids)}"
        )
    if not all(item["source_id"] and item["source_version"] for item in provenance_payload):
        failures.append("membership provenance is incomplete")

    all_token_ids = [str(row["token_id"]) for row in membership]
    languages, elided, leading, trailing = _source_facets(connection, all_token_ids)
    if "language_counts" in expected and languages != expected["language_counts"]:
        failures.append(
            f"language_counts: expected {expected['language_counts']}, observed {languages}"
        )
    for key, actual in (
        ("minimum_elided_tokens", elided),
        ("minimum_leading_punctuation_tokens", leading),
        ("minimum_trailing_punctuation_tokens", trailing),
    ):
        if actual < int(expected.get(key, 0)):
            failures.append(f"{key}: expected at least {expected[key]}, observed {actual}")

    neighbors_ok = _check_neighbors(connection, passages, membership_by_passage)
    if not neighbors_ok:
        failures.append("stored neighbor overlap does not match membership overlap")

    comparison_status = "not_applicable"
    compare = check.get("compare")
    if compare:
        compared = _select_passages(
            connection,
            check,
            profile=compare.get("analysis_profile"),
            reading=compare.get("analysis_reading"),
        )
        if len(compared) != int(compare["passage_count"]):
            failures.append(
                "comparison passage_count: expected "
                f"{compare['passage_count']}, observed {len(compared)}"
            )
        if "content_equivalent" in compare and passages and compared:
            equivalent = _content_payload(passages) == _content_payload(compared)
            if equivalent != bool(compare["content_equivalent"]):
                failures.append(
                    f"comparison content equivalence expected {compare['content_equivalent']}"
                )
        comparison_status = (
            f"{compare.get('analysis_profile', check['analysis_profile'])}/"
            f"{compare.get('analysis_reading', check['analysis_reading'])}:"
            f"{len(compared)}"
        )

    membership_payload = [
        {
            "passage_id": row["passage_id"],
            "position": row["position_in_passage"],
            "token_id": row["token_id"],
        }
        for row in membership
    ]
    content = _content_payload(passages)
    evidence_core = {
        "passage_ids": passage_ids,
        "references": check.get("references", []),
        "membership_sha256": _digest(membership_payload),
        "reconstruction_sha256": _digest(
            [
                {
                    "surface": item["surface"],
                    "normalized": item["normalized"],
                    "unpointed": item["unpointed"],
                    "folded": item["folded"],
                }
                for item in content
            ]
        ),
        "lemma_sequence_sha256": _digest([item["lemmas"] for item in content]),
        "provenance_sha256": _digest(provenance_payload),
    }
    return {
        "check_id": check["check_id"],
        "category": check["category"],
        "corpus": check["corpus"],
        "analysis_profile": check["analysis_profile"],
        "analysis_reading": check["analysis_reading"],
        "granularity": check["granularity"],
        "references_json": _canonical(check.get("references", [])),
        "passage_ids_json": _canonical(passage_ids),
        **counters,
        "source_ids_json": _canonical(sorted(source_ids)),
        "language_counts_json": _canonical(languages),
        "elided_token_count": elided,
        "leading_punctuation_token_count": leading,
        "trailing_punctuation_token_count": trailing,
        "membership_sha256": evidence_core["membership_sha256"],
        "reconstruction_sha256": evidence_core["reconstruction_sha256"],
        "lemma_sequence_sha256": evidence_core["lemma_sequence_sha256"],
        "provenance_sha256": evidence_core["provenance_sha256"],
        "verification_sha256": _digest(evidence_core),
        "neighbor_check": "passed" if neighbors_ok else "failed",
        "comparison_check": comparison_status,
        "status": "PASS" if not failures else "FAIL: " + "; ".join(failures),
    }


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_markdown(path: Path, spec: dict[str, Any], rows: list[dict[str, object]]) -> None:
    def cell(value: object) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")

    columns = (
        "check_id",
        "category",
        "passage_count",
        "membership_count",
        "disputed_count",
        "reference_gap_count",
        "ketiv_uncertainty_count",
        "exclusion_count",
        "verification_sha256",
        "neighbor_check",
        "comparison_check",
        "status",
    )
    lines = [
        "# Milestone 5 passage spot-check evidence",
        "",
        "Generated deterministically by `scripts/generate_m5_spot_check_evidence.py`",
        "from `outputs/reports/m5-spot-check-config.json` and the local full-corpus",
        "DuckDB artifact. Biblical text, lemma values, and token identifiers are hashed",
        "and are not reproduced here. Passage identifiers and canonical references are",
        "retained as auditable non-textual evidence.",
        "",
        f"- Specification schema: {spec['schema_version']}",
        f"- Checks passed: {sum(row['status'] == 'PASS' for row in rows)}/{len(rows)}",
        f"- Required facets: {', '.join(spec['required_facets'])}",
        "",
        "| " + " | ".join(columns) + " |",
        "|" + "|".join("---" for _ in columns) + "|",
    ]
    lines.extend("| " + " | ".join(cell(row[column]) for column in columns) + " |" for row in rows)
    lines.extend(
        [
            "",
            "The companion CSV records the selected passage IDs, exact references, source",
            "IDs, language counts, punctuation/elision counts, and separate membership,",
            "reconstruction, lemma-sequence, and provenance hashes for every check.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("outputs/reports/m5-spot-check-config.json"),
    )
    parser.add_argument("--database", type=Path)
    args = parser.parse_args()
    spec = json.loads(args.config.read_text(encoding="utf-8"))
    if spec.get("schema_version") != 1 or not spec.get("checks"):
        raise ValueError("spot-check specification must use schema_version 1 and define checks")
    database = args.database or Path(spec["database"])
    with duckdb.connect(str(database), read_only=True) as connection:
        selected = [
            passage for check in spec["checks"] for passage in _select_passages(connection, check)
        ]
        passage_ids = sorted(
            {
                str(value)
                for passage in selected
                for value in (
                    passage["passage_id"],
                    passage["previous_passage_id"],
                    passage["next_passage_id"],
                )
                if value
            }
        )
        placeholders = ",".join("?" for _ in passage_ids)
        connection.execute(
            f"""
            CREATE TEMP TABLE m5_spot_membership AS
            SELECT * FROM passage_membership WHERE passage_id IN ({placeholders})
            """,
            passage_ids,
        )
        connection.execute(
            """
            CREATE TEMP TABLE m5_spot_source_tokens AS
            WITH source_tokens AS (
              SELECT token_id, lower(language) AS language, false AS is_elided,
                     '' AS leading_punctuation, '' AS trailing_punctuation
              FROM hebrew_tokens
              UNION ALL
              SELECT token_id, lower(language), false, '', ''
              FROM hebrew_kq_ketiv_tokens
              UNION ALL
              SELECT token_id, lower(language), is_elided,
                     coalesce(leading_punctuation, ''), coalesce(trailing_punctuation, '')
              FROM greek_tokens
            )
            SELECT source_tokens.* FROM source_tokens
            SEMI JOIN (SELECT DISTINCT token_id FROM m5_spot_membership) selected_tokens
              USING (token_id)
            """
        )
        results = [_run_check(connection, check) for check in spec["checks"]]
    _write_csv(Path(spec["evidence_csv"]), results)
    _write_markdown(Path(spec["evidence_markdown"]), spec, results)
    failures = [row for row in results if row["status"] != "PASS"]
    print(f"Milestone 5 spot checks: {len(results) - len(failures)}/{len(results)} passed")
    for row in failures:
        print(f"- {row['check_id']}: {row['status']}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
