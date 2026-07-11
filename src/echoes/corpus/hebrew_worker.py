"""Memory-isolated worker for full MACULA parsing and Parquet construction."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from echoes.acquire import verify_acquisition
from echoes.corpus.hebrew import load_hebrew_configs, load_hebrew_source
from echoes.corpus.storage import write_processed_corpus
from echoes.ingest.macula_hebrew import parse_macula_hebrew_nodes
from echoes.manifest import sha256_file


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-path", type=Path, required=True)
    parser.add_argument("--config-dir", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> int:
    """Build deterministic Parquet outputs and emit only compact result metadata."""
    args = _parser().parse_args()
    try:
        source = load_hebrew_source(args.manifest_path)
        normalization, _ = load_hebrew_configs(args.config_dir)
        raw_root, receipt = verify_acquisition(source, data_root=args.data_root)
        adapter = parse_macula_hebrew_nodes(
            raw_root,
            source=source,
            normalization=normalization.hebrew,
            analysis_reading=normalization.ketiv_qere.analysis_reading,
        )
        processed = write_processed_corpus(
            adapter,
            source=source,
            normalization_config_hash=sha256_file(args.config_dir / "normalization.yaml"),
            raw_file_hashes={item.relative_path: item.sha256 for item in receipt.files},
            output_dir=args.output_dir,
            force=args.force,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "adapter_summary": adapter.summary.model_dump(mode="json"),
                "run_id": processed.run_id,
                "file_hashes": processed.file_hashes,
                "logical_hashes": processed.logical_hashes,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - subprocess entry point
    raise SystemExit(main())
