"""Generate the tracked sanitized Build Week demonstration bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from echoes.reports.build_week_demo import (
    DEFAULT_ARTIFACT_ROOT,
    DEFAULT_DATABASE_PATH,
    DEFAULT_EXPORT_ROOT,
    DEFAULT_SOURCE_MANIFEST,
    export_build_week_demo,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export the sanitized Project Echoes Build Week lexical result."
    )
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_EXPORT_ROOT)
    parser.add_argument("--source-manifest", type=Path, default=DEFAULT_SOURCE_MANIFEST)
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    artifacts = export_build_week_demo(
        artifact_root=arguments.artifact_root,
        database_path=arguments.database,
        output_root=arguments.output_root,
        source_manifest_path=arguments.source_manifest,
        force=arguments.force,
    )
    print(
        json.dumps(
            {
                "lexical_run_id": artifacts.lexical_run_id,
                "known_recovery_count": artifacts.known_recovery_count,
                "unreviewed_candidate_count": artifacts.unreviewed_candidate_count,
                "uncertainty_example_count": artifacts.uncertainty_example_count,
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
