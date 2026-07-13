"""Regenerate the sanitized Milestone 5 report bundle from local artifacts."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from echoes.reports.passage_segmentation import (
    PassageReportContext,
    collect_passage_report_data,
    write_passage_segmentation_report,
)


def _spot_checks(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    checks: list[dict[str, object]] = []
    for row in rows:
        if int(row["passage_count"]) == 0:
            # The source-absence inventory remains in the companion spot-check
            # evidence; the report model intentionally represents extant
            # passages and therefore requires a positive membership count.
            continue
        passage_ids = json.loads(row["passage_ids_json"])
        checks.append(
            {
                "check_id": row["check_id"],
                "category": row["category"],
                "reference": row["references_json"],
                "passage_id": ",".join(passage_ids) if passage_ids else "none-present",
                "corpus": row["corpus"],
                "analysis_profile": row["analysis_profile"],
                "analysis_reading": row["analysis_reading"],
                "granularity": row["granularity"],
                "token_count": int(row["membership_count"]),
                "membership_count": int(row["membership_count"]),
                "verification_sha256": row["verification_sha256"],
                "source_ids": row["source_ids_json"] or "[]",
                "disputed_passage": int(row["disputed_count"]) > 0,
                "reference_gap": int(row["reference_gap_count"]) > 0,
                "ketiv_structural_uncertainty": (int(row["ketiv_uncertainty_count"]) > 0),
                "exclusion_count": int(row["exclusion_count"]),
                "neighbor_check": row["neighbor_check"],
                "status": row["status"],
            }
        )
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database", type=Path, default=Path("data/processed/project_echoes.duckdb")
    )
    parser.add_argument(
        "--context", type=Path, default=Path("outputs/reports/m5-report-context.json")
    )
    parser.add_argument(
        "--spot-checks",
        type=Path,
        default=Path("outputs/reports/m5-passage-spot-checks.csv"),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/reports"))
    args = parser.parse_args()

    context_payload = json.loads(args.context.read_text(encoding="utf-8"))
    context_payload["spot_checks"] = _spot_checks(args.spot_checks)
    context = PassageReportContext.model_validate(context_payload)
    data = collect_passage_report_data(args.database)
    artifacts = write_passage_segmentation_report(data, context, args.output_dir)
    print(f"Wrote {artifacts.report_path} and {len(artifacts.csv_paths)} CSV files.")


if __name__ == "__main__":
    main()
