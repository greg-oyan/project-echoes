"""Memory-isolated worker for full MACULA Greek parsing and Parquet construction."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from echoes.acquire import verify_acquisition
from echoes.corpus.greek import load_greek_configs, load_greek_source
from echoes.corpus.greek_storage import write_processed_greek_corpus
from echoes.ingest.macula_greek import parse_macula_greek_nodes
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
        source = load_greek_source(args.manifest_path)
        normalization, _ = load_greek_configs(args.config_dir)
        raw_root, receipt = verify_acquisition(source, data_root=args.data_root)
        adapter = parse_macula_greek_nodes(
            raw_root,
            source=source,
            normalization=normalization.greek,
        )
        processed = write_processed_greek_corpus(
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
