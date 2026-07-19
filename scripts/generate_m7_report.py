"""Generate the authenticated sanitized Milestone 7 report bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from echoes.reports.lexical_baseline import (
    DEFAULT_EXECUTION_MANIFEST_ROOT,
    DEFAULT_FIRST_RUN_MANIFEST,
    DEFAULT_LEXICAL_ARTIFACT_ROOT,
    DEFAULT_REPORT_DIRECTORY,
    DEFAULT_SPOT_CHECK_CONFIG,
    PR7_MERGE_COMMIT,
    generate_lexical_baseline_reports,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate deterministic sanitized Project Echoes Milestone 7 reports."
    )
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_LEXICAL_ARTIFACT_ROOT)
    parser.add_argument("--output-directory", type=Path, default=DEFAULT_REPORT_DIRECTORY)
    parser.add_argument("--spot-check-config", type=Path, default=DEFAULT_SPOT_CHECK_CONFIG)
    parser.add_argument(
        "--comparison-manifest",
        type=Path,
        default=DEFAULT_FIRST_RUN_MANIFEST,
        help="Saved table-hashes.json from the first complete build.",
    )
    parser.add_argument("--pr7-merge-commit", default=PR7_MERGE_COMMIT)
    parser.add_argument(
        "--execution-manifest-root",
        type=Path,
        default=DEFAULT_EXECUTION_MANIFEST_ROOT,
        help="Ignored governed execution-manifest sidecar root.",
    )
    parser.add_argument(
        "--first-execution-id",
        help="Exact successful recovered-composite execution for build one.",
    )
    parser.add_argument(
        "--second-execution-id",
        help="Exact successful independent fresh execution for build two.",
    )
    parser.add_argument(
        "--allow-failed-acceptance",
        action="store_true",
        help=(
            "Emit a reportable failed-science bundle with exit code zero. "
            "Without this flag, a false acceptance receipt exits nonzero."
        ),
    )
    return parser


def main() -> int:
    """Run report generation and print a machine-readable receipt."""

    arguments = _parser().parse_args()
    artifacts = generate_lexical_baseline_reports(
        artifact_root=arguments.artifact_root,
        output_directory=arguments.output_directory,
        spot_check_config=arguments.spot_check_config,
        comparison_manifest=arguments.comparison_manifest,
        pr7_merge_commit=arguments.pr7_merge_commit,
        execution_manifest_root=arguments.execution_manifest_root,
        first_execution_id=arguments.first_execution_id,
        second_execution_id=arguments.second_execution_id,
    )
    print(
        json.dumps(
            {
                "acceptance_gate_passed": artifacts.acceptance_gate_passed,
                "determinism_status": artifacts.determinism.status,
                "execution_determinism_status": artifacts.execution_determinism.status,
                "first_execution_id": artifacts.execution_determinism.first_execution_id,
                "second_execution_id": artifacts.execution_determinism.second_execution_id,
                "paths": [path.as_posix() for path in artifacts.paths],
                "sha256": artifacts.sha256_by_name,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if artifacts.acceptance_gate_passed or arguments.allow_failed_acceptance else 1


if __name__ == "__main__":
    raise SystemExit(main())
