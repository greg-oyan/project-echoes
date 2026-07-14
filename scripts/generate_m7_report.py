"""Generate the authenticated sanitized Milestone 7 report bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from echoes.reports.lexical_baseline import (
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
    )
    print(
        json.dumps(
            {
                "acceptance_gate_passed": artifacts.acceptance_gate_passed,
                "determinism_status": artifacts.determinism.status,
                "paths": [path.as_posix() for path in artifacts.paths],
                "sha256": artifacts.sha256_by_name,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
