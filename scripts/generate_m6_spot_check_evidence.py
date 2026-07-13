"""Generate deterministic, sanitized Milestone 6 spot-check evidence.

The script selects records by governed criteria and stable identity order.  It
never stores biblical text or bulk source rows.  If a real-snapshot category is
absent, the evidence records the audited zero count instead of inventing an
example.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast

import duckdb

from echoes.benchmarks.tier1 import validate_tier1_quotations

DEFAULT_DATABASE = Path("data/processed/project_echoes.duckdb")
DEFAULT_CONFIG = Path("outputs/reports/m6-spot-check-config.json")
DEFAULT_OUTPUT = Path("outputs/reports/m6-spot-check-evidence.md")
DEFAULT_TIER1 = Path("data/benchmarks/tier1_quotations.csv")

_FORBIDDEN_EVIDENCE_FIELD_MARKERS = (
    "- biblical text:",
    "- quotation text:",
    "- source text:",
    "- target text:",
    "- surface:",
    "- surface form:",
    "- lemma:",
    "| biblical text |",
    "| quotation text |",
    "| source text |",
    "| target text |",
    "| surface |",
    "| lemma |",
)

_RELATIONSHIP_SELECTORS: dict[str, str] = {
    "normal_ot_ot_link": """
        SELECT r.relationship_id FROM within_old_testament_relationships r
        WHERE (SELECT count(*) FROM benchmark_endpoint_mappings m
               JOIN benchmark_endpoints e USING(endpoint_id)
               WHERE e.relationship_id=r.relationship_id
                 AND m.target_analysis_profile='edition_complete'
                 AND m.mapping_status IN ('mapped_verified','mapped_provisional'))=2
          AND NOT EXISTS (
          SELECT 1 FROM benchmark_endpoints e
          LEFT JOIN benchmark_endpoint_mappings m USING(endpoint_id)
          WHERE e.relationship_id=r.relationship_id
            AND (e.is_range OR m.target_analysis_profile='edition_complete' AND
                 (m.disputed_passage_flag OR m.reference_gap OR
                  m.mapping_status NOT IN ('mapped_verified','mapped_provisional')))
        ) ORDER BY r.relationship_id
    """,
    "normal_nt_nt_link": """
        SELECT r.relationship_id FROM within_new_testament_relationships r
        WHERE (SELECT count(*) FROM benchmark_endpoint_mappings m
               JOIN benchmark_endpoints e USING(endpoint_id)
               WHERE e.relationship_id=r.relationship_id
                 AND m.target_analysis_profile='edition_complete'
                 AND m.mapping_status IN ('mapped_verified','mapped_provisional'))=2
          AND NOT EXISTS (
          SELECT 1 FROM benchmark_endpoints e
          LEFT JOIN benchmark_endpoint_mappings m USING(endpoint_id)
          WHERE e.relationship_id=r.relationship_id
            AND (e.is_range OR m.target_analysis_profile='edition_complete' AND
                 (m.disputed_passage_flag OR m.reference_gap OR
                  m.mapping_status NOT IN ('mapped_verified','mapped_provisional')))
        ) ORDER BY r.relationship_id
    """,
    "normal_cross_testament_link": """
        SELECT r.relationship_id FROM cross_testament_relationships r
        WHERE (SELECT count(*) FROM benchmark_endpoint_mappings m
               JOIN benchmark_endpoints e USING(endpoint_id)
               WHERE e.relationship_id=r.relationship_id
                 AND m.target_analysis_profile='edition_complete'
                 AND m.mapping_status IN ('mapped_verified','mapped_provisional'))=2
          AND NOT EXISTS (SELECT 1 FROM benchmark_endpoints e
                          WHERE e.relationship_id=r.relationship_id AND e.is_range)
          AND NOT EXISTS (
          SELECT 1 FROM benchmark_endpoint_mappings m
          JOIN benchmark_endpoints e USING(endpoint_id)
          WHERE e.relationship_id=r.relationship_id
            AND m.target_analysis_profile='edition_complete'
            AND (m.disputed_passage_flag OR m.reference_gap OR
                 m.mapping_status NOT IN ('mapped_verified','mapped_provisional'))
        ) ORDER BY r.relationship_id
    """,
    "range_endpoint": """
        SELECT DISTINCT relationship_id FROM benchmark_endpoints
        WHERE is_range ORDER BY relationship_id
    """,
    "highest_weight_relationship": """
        SELECT relationship_id FROM benchmark_relationships
        ORDER BY source_weight_max DESC NULLS LAST, relationship_id
    """,
    "lowest_weight_relationship": """
        SELECT relationship_id FROM benchmark_relationships
        ORDER BY source_weight_max ASC NULLS LAST, relationship_id
    """,
    "duplicate_source_relationship": """
        SELECT relationship_id FROM benchmark_relationships
        WHERE source_record_count > 1 ORDER BY relationship_id
    """,
    "reverse_pair": """
        SELECT relationship_id FROM openbible_reverse_pairs ORDER BY relationship_id
    """,
    "disputed_passage_link": """
        SELECT DISTINCT e.relationship_id FROM benchmark_endpoint_mappings m
        JOIN benchmark_endpoints e USING(endpoint_id)
        WHERE m.disputed_passage_flag ORDER BY e.relationship_id
    """,
    "edition_omitted_nt_reference": """
        SELECT DISTINCT e.relationship_id FROM benchmark_endpoint_mappings m
        JOIN benchmark_endpoints e USING(endpoint_id)
        WHERE m.mapping_status='unresolved_missing_target'
          AND m.target_corpus='greek' ORDER BY e.relationship_id
    """,
    "partially_mapped_range": """
        SELECT DISTINCT e.relationship_id FROM benchmark_endpoint_mappings m
        JOIN benchmark_endpoints e USING(endpoint_id)
        WHERE e.is_range AND m.mapping_status='mapped_partial'
        ORDER BY e.relationship_id
    """,
    "ot_provisional_versification_risk": """
        SELECT DISTINCT e.relationship_id FROM benchmark_endpoint_mappings m
        JOIN benchmark_endpoints e USING(endpoint_id)
        WHERE m.target_corpus='hebrew'
          AND m.mapping_status IN ('mapped_provisional','unresolved_versification')
        ORDER BY e.relationship_id
    """,
    "held_out_book_split": """
        SELECT relationship_id FROM benchmark_split_assignments
        WHERE split_strategy='held_out_book' AND partition IN ('test','development')
        ORDER BY CASE partition WHEN 'test' THEN 0 ELSE 1 END, relationship_id
    """,
    "held_out_book_pair_split": """
        SELECT relationship_id FROM benchmark_split_assignments
        WHERE split_strategy='held_out_book_pair' AND partition IN ('test','development')
        ORDER BY CASE partition WHEN 'test' THEN 0 ELSE 1 END, relationship_id
    """,
    "held_out_source_passage_split": """
        SELECT relationship_id FROM benchmark_split_assignments
        WHERE split_strategy='held_out_source_passage'
          AND partition IN ('test','development')
        ORDER BY CASE partition WHEN 'test' THEN 0 ELSE 1 END, relationship_id
    """,
    "held_out_genre_split": """
        SELECT relationship_id FROM benchmark_split_assignments
        WHERE split_strategy='held_out_genre' AND partition IN ('test','development')
        ORDER BY CASE partition WHEN 'test' THEN 0 ELSE 1 END, relationship_id
    """,
}

_NEGATIVE_SELECTORS: dict[str, str] = {
    "presumed_length_matched_negative": "length_matched_random_unlinked",
    "presumed_same_genre_negative": "same_broad_genre_unlinked",
    "presumed_nearby_context_negative": "nearby_context_unlinked",
}

_REQUIRED_CRITERIA = (
    {("relationship", selector) for selector in _RELATIONSHIP_SELECTORS}
    | {("presumed_negative", selector) for selector in _NEGATIVE_SELECTORS}
    | {
        ("self_link", "self_link_issue"),
        ("tier1", "canonical_tier1_placeholder"),
    }
)


@dataclass(frozen=True, slots=True)
class SpotCriterion:
    criterion_id: str
    title: str
    selector: str
    kind: str
    absence_policy: str


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _load_criteria(path: Path) -> list[SpotCriterion]:
    payload = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    if payload.get("schema_version") != 1:
        raise ValueError("spot-check config requires schema_version 1")
    raw_criteria = payload.get("criteria")
    if not isinstance(raw_criteria, list):
        raise ValueError("spot-check config criteria must be a list")
    criteria: list[SpotCriterion] = []
    for raw in raw_criteria:
        if not isinstance(raw, dict):
            raise ValueError("every spot-check criterion must be an object")
        criterion = SpotCriterion(
            criterion_id=str(raw.get("criterion_id", "")),
            title=str(raw.get("title", "")),
            selector=str(raw.get("selector", "")),
            kind=str(raw.get("kind", "")),
            absence_policy=str(raw.get("absence_policy", "")),
        )
        if not all(
            (
                criterion.criterion_id,
                criterion.title,
                criterion.selector,
                criterion.kind,
                criterion.absence_policy,
            )
        ):
            raise ValueError("spot-check criteria cannot contain empty fields")
        if criterion.kind == "relationship" and criterion.selector not in _RELATIONSHIP_SELECTORS:
            raise ValueError(f"unknown relationship selector {criterion.selector}")
        if criterion.kind == "presumed_negative" and criterion.selector not in _NEGATIVE_SELECTORS:
            raise ValueError(f"unknown negative selector {criterion.selector}")
        if criterion.kind == "self_link" and criterion.selector != "self_link_issue":
            raise ValueError(f"unknown self-link selector {criterion.selector}")
        if criterion.kind == "tier1" and criterion.selector != "canonical_tier1_placeholder":
            raise ValueError(f"unknown Tier 1 selector {criterion.selector}")
        if criterion.kind not in {"relationship", "presumed_negative", "self_link", "tier1"}:
            raise ValueError(f"unsupported spot-check kind {criterion.kind}")
        criteria.append(criterion)
    if len({item.criterion_id for item in criteria}) != len(criteria):
        raise ValueError("spot-check criterion IDs must be unique")
    observed = {(item.kind, item.selector) for item in criteria}
    missing = sorted(_REQUIRED_CRITERIA - observed)
    if missing:
        raise ValueError(f"spot-check config omits required criteria: {missing}")
    return criteria


def _markdown(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _assert_content_boundary(content: str) -> None:
    """Fail closed if a text-bearing corpus field enters tracked evidence."""

    lowered = content.lower()
    found = [marker for marker in _FORBIDDEN_EVIDENCE_FIELD_MARKERS if marker in lowered]
    if found:
        raise ValueError(f"spot-check evidence contains prohibited text-bearing fields: {found}")


def _manual_review_lines(
    *, reviewer: str | None, review_date: str | None, verdict: str
) -> list[str]:
    if verdict not in {"pending", "passed"}:
        raise ValueError("manual spot-check verdict must be pending or passed")
    if verdict == "pending":
        if reviewer is not None or review_date is not None:
            raise ValueError("pending manual review cannot name a reviewer or review date")
        return [
            "- Manual review verdict: `PENDING`",
            "- Manual review boundary: the generated selections have not yet been signed off.",
        ]
    if not reviewer or not reviewer.strip():
        raise ValueError("passed manual review requires a reviewer")
    if review_date is None:
        raise ValueError("passed manual review requires an ISO review date")
    try:
        date.fromisoformat(review_date)
    except ValueError as exc:
        raise ValueError("manual review date must use ISO YYYY-MM-DD format") from exc
    return [
        "- Manual review verdict: `PASS`",
        f"- Manual reviewer: `{_markdown(reviewer.strip())}`",
        f"- Manual review date: `{review_date}`",
        "- Manual field review: selected identity or audited absence, source-record "
        "provenance, original references, direction, weight, tier and eligibility, mapping "
        "method/status/targets, disputed and gap flags, leakage groups, split assignment, "
        "and negative collision controls were checked where applicable.",
    ]


def _select_identity(
    connection: duckdb.DuckDBPyConnection, criterion: SpotCriterion
) -> tuple[str | None, int]:
    if criterion.kind == "relationship":
        rows = cast(
            list[tuple[object, ...]],
            connection.execute(_RELATIONSHIP_SELECTORS[criterion.selector]).fetchall(),
        )
    elif criterion.kind == "presumed_negative":
        rows = cast(
            list[tuple[object, ...]],
            connection.execute(
                "SELECT contrastive_id FROM benchmark_presumed_negatives "
                "WHERE negative_strategy=? ORDER BY contrastive_id",
                [_NEGATIVE_SELECTORS[criterion.selector]],
            ).fetchall(),
        )
    elif criterion.kind == "self_link":
        rows = cast(
            list[tuple[object, ...]],
            connection.execute(
                "SELECT issue_id FROM benchmark_issues WHERE code='self_link_excluded' "
                "ORDER BY issue_id"
            ).fetchall(),
        )
    else:
        return None, 0
    return (str(rows[0][0]) if rows else None, len(rows))


def _relationship_evidence(
    connection: duckdb.DuckDBPyConnection, relationship_id: str
) -> list[str]:
    relationship = cast(
        tuple[object, ...] | None,
        connection.execute(
            """
        SELECT source_reference_a,source_reference_b,relationship_direction,
               source_weight_sum,source_weight_max,tier,weak_supervision_eligible,
               knownness_filter_eligible,primary_evaluation_eligible,tier1_eligible,
               source_record_count,data_quality_status,license_status
        FROM benchmark_relationships WHERE relationship_id=?
        """,
            [relationship_id],
        ).fetchone(),
    )
    if relationship is None:
        raise ValueError(f"selected relationship disappeared: {relationship_id}")
    lines = [
        f"- Relationship ID: `{relationship_id}`",
        f"- Original source references: `{_markdown(relationship[0])}` → "
        f"`{_markdown(relationship[1])}`",
        f"- Direction: `{_markdown(relationship[2])}`",
        f"- Source weight sum / maximum: `{relationship[3]}` / `{relationship[4]}`",
        f"- Tier: `{relationship[5]}`",
        "- Eligibility flags: "
        f"weak supervision=`{relationship[6]}`, knownness=`{relationship[7]}`, "
        f"primary evaluation=`{relationship[8]}`, Tier 1=`{relationship[9]}`",
        f"- Data quality / license: `{relationship[11]}` / `{relationship[12]}`",
    ]
    provenance = cast(
        list[tuple[object, ...]],
        connection.execute(
            """
        SELECT s.source_record_id,s.source_file,s.source_line_number,
               s.raw_record_sha256,l.link_role
        FROM benchmark_relationship_source_records l
        JOIN benchmark_source_records s USING(source_record_id)
        WHERE l.relationship_id=? ORDER BY s.source_record_id
        """,
            [relationship_id],
        ).fetchall(),
    )
    preview = "; ".join(
        f"{row[0]} ({row[1]}:{row[2]}, sha256={row[3]}, role={row[4]})" for row in provenance[:10]
    )
    lines.append(
        f"- Source-record provenance ({len(provenance)} record(s)): `{_markdown(preview)}`"
    )

    mappings = cast(
        list[tuple[object, ...]],
        connection.execute(
            """
        SELECT e.endpoint_side,e.endpoint_id,e.source_reference,e.is_range,
               m.mapping_method,m.mapping_status,m.mapping_confidence,
               m.target_analysis_profile,m.target_passage_ids_json,
               m.disputed_passage_flag,m.disputed_passage_ids_json,m.reference_gap,
               m.ambiguity_reason
        FROM benchmark_endpoints e
        LEFT JOIN benchmark_endpoint_mappings m USING(endpoint_id)
        WHERE e.relationship_id=?
        ORDER BY e.endpoint_side,m.target_analysis_profile
        """,
            [relationship_id],
        ).fetchall(),
    )
    lines.extend(
        [
            "- Endpoint mappings:",
            "",
            "  | Side | Source reference | Range | Profile | Method | Status | Confidence | "
            "Target passage IDs | Disputed | Reference gap | Ambiguity |",
            "  |---|---|---:|---|---|---|---|---|---:|---:|---|",
        ]
    )
    for row in mappings:
        lines.append(
            "  | "
            + " | ".join(
                _markdown(value)
                for value in (
                    row[0],
                    row[2],
                    row[3],
                    row[7],
                    row[4],
                    row[5],
                    row[6],
                    row[8],
                    f"{row[9]} {row[10]}",
                    row[11],
                    row[12],
                )
            )
            + " |"
        )

    leakage = cast(
        list[tuple[object, ...]],
        connection.execute(
            "SELECT group_type,leakage_group_id,group_key FROM benchmark_leakage_groups "
            "WHERE relationship_id=? ORDER BY group_type,leakage_group_id",
            [relationship_id],
        ).fetchall(),
    )
    leakage_preview = "; ".join(f"{row[0]}:{row[1]} ({row[2]})" for row in leakage[:25])
    lines.append(
        f"- Leakage groups ({len(leakage)} membership(s); first 25): `{_markdown(leakage_preview)}`"
    )
    splits = cast(
        list[tuple[object, ...]],
        connection.execute(
            "SELECT split_strategy,partition,eligibility_status,exclusion_reason,seed "
            "FROM benchmark_split_assignments WHERE relationship_id=? "
            "ORDER BY split_strategy",
            [relationship_id],
        ).fetchall(),
    )
    split_preview = "; ".join(
        f"{row[0]}={row[1]} (eligibility={row[2]}, reason={row[3]}, seed={row[4]})"
        for row in splits
    )
    lines.append(f"- Split assignments: `{_markdown(split_preview)}`")
    return lines


def _negative_evidence(connection: duckdb.DuckDBPyConnection, contrastive_id: str) -> list[str]:
    row = cast(
        tuple[object, ...] | None,
        connection.execute(
            """
        SELECT passage_a_id,passage_b_id,corpus_pair,negative_strategy,
               presumed_negative,positive_graph_checked,reverse_pair_checked,
               passage_overlap_checked,leakage_checked,length_difference,
               book_pair,genre_pair,split_strategy,partition,seed,
               generation_config_hash,notes
        FROM benchmark_presumed_negatives WHERE contrastive_id=?
        """,
            [contrastive_id],
        ).fetchone(),
    )
    if row is None:
        raise ValueError(f"selected presumed negative disappeared: {contrastive_id}")
    return [
        f"- Contrastive ID: `{contrastive_id}`",
        f"- Passage IDs: `{row[0]}` / `{row[1]}`",
        f"- Corpus / book / genre pairs: `{row[2]}` / `{row[10]}` / `{row[11]}`",
        f"- Strategy: `{row[3]}`; length difference: `{row[9]}`",
        f"- Split: `{row[12]}` / `{row[13]}`; seed: `{row[14]}`",
        f"- Generation config SHA-256: `{row[15]}`",
        "- Collision controls: "
        f"presumed=`{row[4]}`, positive graph=`{row[5]}`, reverse pair=`{row[6]}`, "
        f"overlap=`{row[7]}`, leakage=`{row[8]}`",
        f"- Interpretation: {_markdown(row[16])}",
    ]


def _self_link_evidence(connection: duckdb.DuckDBPyConnection, issue_id: str) -> list[str]:
    row = cast(
        tuple[object, ...] | None,
        connection.execute(
            """
        SELECT i.issue_id,i.severity,i.code,i.message,s.source_record_id,
               s.source_reference_a,s.source_reference_b,s.source_weight,
               s.source_file,s.source_line_number,s.raw_record_sha256
        FROM benchmark_issues i
        JOIN benchmark_source_records s USING(source_record_id)
        WHERE i.issue_id=?
        """,
            [issue_id],
        ).fetchone(),
    )
    if row is None:
        raise ValueError(f"selected self-link issue disappeared: {issue_id}")
    return [
        f"- Issue ID: `{row[0]}`; severity/code: `{row[1]}` / `{row[2]}`",
        f"- Audit disposition: {_markdown(row[3])}",
        f"- Source record ID: `{row[4]}`",
        f"- Original references: `{_markdown(row[5])}` / `{_markdown(row[6])}`",
        f"- Weight: `{row[7]}`",
        f"- Provenance: `{row[8]}:{row[9]}`; raw SHA-256 `{row[10]}`",
        "- Relationship ID: none; governed self-link policy excluded it explicitly.",
    ]


def _tier1_evidence(path: Path, expected_hash: str) -> list[str]:
    validation = validate_tier1_quotations(path, expected_sha256=expected_hash)
    return [
        f"- Canonical path: `{path.as_posix()}`",
        f"- Data-row count: `{validation.row_count}`",
        f"- Header SHA-256: `{validation.sha256}`",
        f"- Metadata hash agreement: `{validation.sha256 == expected_hash}`",
        "- Governance: schema placeholder only; no generated or curated evidence rows.",
    ]


def generate_spot_check_evidence(
    *,
    database: Path,
    config: Path,
    output: Path,
    tier1_path: Path,
    manual_reviewer: str | None = None,
    manual_review_date: str | None = None,
    manual_verdict: str = "pending",
) -> Path:
    criteria = _load_criteria(config)
    review_lines = _manual_review_lines(
        reviewer=manual_reviewer,
        review_date=manual_review_date,
        verdict=manual_verdict,
    )
    criterion_verdict = "PASS" if manual_verdict == "passed" else "PENDING"
    with duckdb.connect(str(database), read_only=True) as connection:
        metadata = cast(
            tuple[object, ...] | None,
            connection.execute(
                "SELECT benchmark_run_id,benchmark_version,tier1_header_sha256 "
                "FROM benchmark_metadata"
            ).fetchone(),
        )
        if metadata is None:
            raise ValueError("benchmark metadata is absent")
        lines = [
            "# Milestone 6 spot-check evidence",
            "",
            f"- Benchmark run ID: `{metadata[0]}`",
            f"- Benchmark version: `{metadata[1]}`",
            "- Selection: lowest stable identity matching each governed criterion, unless the "
            "criterion defines a weight ordering.",
            "- Content boundary: references, identities, mappings, counts, and provenance only; "
            "no biblical quotation text is reproduced.",
            *review_lines,
            "",
        ]
        for criterion in criteria:
            lines.extend([f"## {criterion.title}", ""])
            if criterion.kind == "tier1":
                lines.append("- Status: `validated_placeholder`")
                lines.extend(_tier1_evidence(tier1_path, str(metadata[2])))
                lines.append(f"- Manual criterion verdict: `{criterion_verdict}`")
                lines.append("")
                continue
            identity, available_count = _select_identity(connection, criterion)
            if identity is None:
                lines.extend(
                    [
                        "- Status: `audited_absence`",
                        f"- Matching artifact count: `{available_count}`",
                        f"- Absence policy: {_markdown(criterion.absence_policy)}",
                        "- No example was fabricated.",
                        f"- Manual criterion verdict: `{criterion_verdict}`",
                        "",
                    ]
                )
                continue
            lines.extend(
                [
                    "- Status: `selected`",
                    f"- Matching artifact count: `{available_count}`",
                    f"- Deterministically selected identity: `{identity}`",
                ]
            )
            if criterion.kind == "relationship":
                lines.extend(_relationship_evidence(connection, identity))
            elif criterion.kind == "presumed_negative":
                lines.extend(_negative_evidence(connection, identity))
            else:
                lines.extend(_self_link_evidence(connection, identity))
            lines.append(f"- Manual criterion verdict: `{criterion_verdict}`")
            lines.append("")

    content = "\n".join(lines).rstrip() + "\n"
    _assert_content_boundary(content)
    _atomic_text(output, content)
    return output


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--tier1-path", type=Path, default=DEFAULT_TIER1)
    parser.add_argument("--manual-reviewer")
    parser.add_argument("--manual-review-date")
    parser.add_argument("--manual-verdict", choices=("pending", "passed"), default="pending")
    return parser


def main() -> None:
    args = _parser().parse_args()
    output = generate_spot_check_evidence(
        database=args.database,
        config=args.config,
        output=args.output,
        tier1_path=args.tier1_path,
        manual_reviewer=args.manual_reviewer,
        manual_review_date=args.manual_review_date,
        manual_verdict=args.manual_verdict,
    )
    print(output)


if __name__ == "__main__":
    main()
