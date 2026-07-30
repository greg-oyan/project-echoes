#!/usr/bin/env python3
"""Build the exact, non-archiving Milestone 7 transfer allowlist."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final, Literal
from uuid import uuid4

Classification = Literal["required", "recoverable_checkpoint", "final_output"]

BRANCH: Final = "feature/m7-lexical-baseline"
STAGING_RELATIVE: Final = Path(
    "data/processed/lexical/.schema-v1.writing-238902db1f6e479596bea47e70ccf30b"
)
DATABASE_RELATIVE: Final = Path("data/processed/project_echoes.duckdb")
MANIFEST_RELATIVE: Final = Path("cloud/transfer-manifest.json")
CLOUD_REQUIRED_EXACT: Final = (
    Path("cloud/README.md"),
    Path("cloud/bootstrap_ubuntu.sh"),
    Path("cloud/build_transfer_manifest.py"),
    Path("cloud/cloud_start.sh"),
    Path("cloud/cloud_status.sh"),
    Path("cloud/cloud_stop.sh"),
    Path("cloud/cloud_validate.sh"),
    Path("cloud/download_from_server.ps1"),
    Path("cloud/install_echoes_service.sh"),
    Path("cloud/package_results.sh"),
    Path("cloud/upload_to_server.ps1"),
    Path("cloud/verify_transfer.sh"),
)

REQUIRED_EXACT: Final = (
    Path(".gitignore"),
    Path(".python-version"),
    Path("CHANGELOG.md"),
    Path("README.md"),
    Path("pyproject.toml"),
    Path("uv.lock"),
    Path("data/benchmarks/tier1_quotations.csv"),
    Path("data/manifests/sources.yaml"),
    Path("data/processed/benchmarks/schema-v1/table-hashes.json"),
    Path("data/processed/oshb-morphhb/master-3d15126/table-hashes.json"),
    Path("docs/cloud-execution.md"),
    Path("docs/data-licensing.md"),
    Path("docs/master-plan.md"),
    Path("docs/decisions/0017-single-node-cloud-execution-exception.md"),
    Path("outputs/reports/m7-lexical-feature-audit.md"),
    Path("outputs/reports/m7-spot-check-config.json"),
    Path("scripts/generate_m7_report.py"),
)

EXCLUDED: Final = (
    {
        "path_pattern": ".git/**",
        "classification": "excluded",
        "reason": "Git metadata is established by an exact remote clone, never uploaded.",
    },
    {
        "path_pattern": ".venv/**",
        "classification": "regenerable",
        "reason": "The pinned Linux environment is recreated from uv.lock.",
    },
    {
        "path_pattern": "**/{__pycache__,.mypy_cache,.pytest_cache,.ruff_cache}/**",
        "classification": "regenerable",
        "reason": "Interpreter and quality-tool caches are platform-specific.",
    },
    {
        "path_pattern": "data/raw/**",
        "classification": "excluded",
        "reason": "Raw acquisitions are restricted and unnecessary for M7 resume.",
    },
    {
        "path_pattern": "data/interim/**",
        "classification": "regenerable",
        "reason": "Interim work is not an authenticated M7 resume dependency.",
    },
    {
        "path_pattern": "data/processed/corpus/**",
        "classification": "excluded",
        "reason": "Required corpus relations are materialized in the transferred DuckDB.",
    },
    {
        "path_pattern": "data/processed/benchmarks/schema-v1/** except table-hashes.json",
        "classification": "excluded",
        "reason": "Benchmark relations are materialized in DuckDB; only the anchor is required.",
    },
    {
        "path_pattern": "data/processed/oshb-morphhb/master-3d15126/** except table-hashes.json",
        "classification": "excluded",
        "reason": "OSHB relations are materialized in DuckDB; only the anchor is required.",
    },
    {
        "path_pattern": "data/processed/lexical/.schema-v1.writing-* except the governed path",
        "classification": "obsolete_or_excluded",
        "reason": "Unselected failed staging attempts must be reviewed rather than uploaded.",
    },
    {
        "path_pattern": "data/processed/lexical/*spill*/**",
        "classification": "regenerable",
        "reason": "DuckDB spill is execution-owned temporary state, not a checkpoint.",
    },
    {
        "path_pattern": "outputs/** except the two governed M7 preparation reports",
        "classification": "excluded",
        "reason": "Unrelated milestone outputs are not M7 resume dependencies.",
    },
    {
        "path_pattern": "tests/** and development-only scripts",
        "classification": "excluded",
        "reason": "The exact Git clone supplies tests; they are not private transfer payload.",
    },
    {
        "path_pattern": "**/*.{log,tmp,swp,pagefile,sys,dmp}",
        "classification": "obsolete_or_excluded",
        "reason": "Logs, editor residue, dumps, and page/swap files are not resume inputs.",
    },
    {
        "path_pattern": "**/{.env,*credential*,*secret*,*private-key*}",
        "classification": "excluded",
        "reason": "Credentials, secrets, and private keys are prohibited from the payload.",
    },
)


class ManifestBuildError(RuntimeError):
    """Raised when the governed inventory cannot be built safely."""


@dataclass(frozen=True, slots=True)
class FileEntry:
    """One stable file hashed directly from the project tree."""

    path: str
    size_bytes: int
    sha256: str
    classification: Classification
    required: bool = True

    def as_json(self) -> dict[str, object]:
        return {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "classification": self.classification,
            "required": self.required,
        }


_DENIED_COMPONENTS: Final = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
}
_DENIED_SUFFIXES: Final = {".dmp", ".log", ".pagefile", ".swp", ".sys", ".tmp"}
_DENIED_NAME_FRAGMENTS: Final = ("credential", "private-key", "secret")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Project root (defaults to the parent of cloud/).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=MANIFEST_RELATIVE,
        help="Project-relative output path.",
    )
    return parser.parse_args()


def _assert_regular_file(path: Path, *, root: Path) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ManifestBuildError(f"required file is unreadable: {path}: {exc}") from exc
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    file_attributes = getattr(metadata, "st_file_attributes", 0)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or path.is_symlink()
        or bool(file_attributes & reparse_flag)
    ):
        raise ManifestBuildError(f"required path is not a regular non-reparse file: {path}")
    try:
        path.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as exc:
        raise ManifestBuildError(f"required file escapes the project root: {path}") from exc
    return metadata


def _sha256_stable(path: Path, *, root: Path) -> tuple[int, str]:
    before = _assert_regular_file(path, root=root)
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ManifestBuildError(f"could not hash required file {path}: {exc}") from exc
    after = _assert_regular_file(path, root=root)
    before_identity = (before.st_size, before.st_mtime_ns)
    after_identity = (after.st_size, after.st_mtime_ns)
    if before_identity != after_identity:
        raise ManifestBuildError(f"required file changed while being hashed: {path}")
    return after.st_size, digest.hexdigest()


def _relative_posix(path: Path, root: Path) -> str:
    try:
        value = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ManifestBuildError(f"path escapes project root: {path}") from exc
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ManifestBuildError(f"unsafe project-relative path: {value}")
    return value


def _assert_not_denied(relative: str) -> None:
    pure = PurePosixPath(relative)
    folded_parts = tuple(part.casefold() for part in pure.parts)
    name = folded_parts[-1]
    if any(part in _DENIED_COMPONENTS for part in folded_parts):
        raise ManifestBuildError(f"selected path enters a prohibited directory: {relative}")
    if name == ".env" or name.startswith(".env."):
        raise ManifestBuildError(f"selected path resembles an environment-secret file: {relative}")
    if PurePosixPath(name).suffix in _DENIED_SUFFIXES:
        raise ManifestBuildError(f"selected path has a prohibited residue suffix: {relative}")
    if any(fragment in name for fragment in _DENIED_NAME_FRAGMENTS):
        raise ManifestBuildError(f"selected path resembles secret material: {relative}")


def _tree_files(path: Path) -> list[Path]:
    if not path.is_dir() or path.is_symlink():
        raise ManifestBuildError(f"required directory is missing or unsafe: {path}")
    try:
        return sorted(candidate for candidate in path.rglob("*") if candidate.is_file())
    except OSError as exc:
        raise ManifestBuildError(f"could not enumerate required directory {path}: {exc}") from exc


def _governed_paths(root: Path) -> dict[Path, Classification]:
    selected: dict[Path, Classification] = {}

    def add(path: Path, classification: Classification) -> None:
        absolute = path if path.is_absolute() else root / path
        absolute = Path(os.path.abspath(absolute))
        previous = selected.get(absolute)
        if previous is not None and previous != classification:
            raise ManifestBuildError(
                f"file received conflicting classifications: {absolute}: "
                f"{previous} versus {classification}"
            )
        selected[absolute] = classification

    for relative in REQUIRED_EXACT:
        add(
            relative, "final_output" if relative.parts[:2] == ("outputs", "reports") else "required"
        )
    add(DATABASE_RELATIVE, "required")

    for path in _tree_files(root / "src"):
        if path.suffix == ".py":
            add(path, "required")
    for path in _tree_files(root / "config"):
        if path.suffix in {".yaml", ".yml"}:
            add(path, "required")
    for path in CLOUD_REQUIRED_EXACT:
        add(path, "required")

    for path in _tree_files(root / "data/processed/passages/schema-v1"):
        add(path, "required")
    for path in _tree_files(root / STAGING_RELATIVE):
        add(path, "recoverable_checkpoint")
    for path in _tree_files(root / "data/processed/lexical/execution-manifests"):
        add(path, "recoverable_checkpoint")

    return selected


def _validate_inventory_state(root: Path) -> None:
    database = root / DATABASE_RELATIVE
    if not database.is_file() or database.is_symlink():
        raise ManifestBuildError(f"required DuckDB database is missing or unsafe: {database}")
    wal = database.with_name(database.name + ".wal")
    if wal.exists() or wal.is_symlink():
        raise ManifestBuildError(f"refusing a potentially uncheckpointed DuckDB transfer: {wal}")
    canonical = root / "data/processed/lexical/schema-v1"
    if canonical.exists() or canonical.is_symlink():
        raise ManifestBuildError(
            "canonical lexical output exists; this manifest is only for the recovery run: "
            f"{canonical}"
        )
    lexical_parent = root / "data/processed/lexical"
    staging_candidates = sorted(
        path.resolve()
        for path in lexical_parent.glob(".schema-v1.writing-*")
        if path.is_dir() and not path.is_symlink()
    )
    expected = (root / STAGING_RELATIVE).resolve()
    if staging_candidates != [expected]:
        raise ManifestBuildError(
            "expected exactly the governed recovery staging directory; observed "
            f"{[path.as_posix() for path in staging_candidates]}"
        )


def _build(root: Path, output: Path) -> dict[str, object]:
    resolved_root = root.resolve(strict=True)
    try:
        output_relative = output if not output.is_absolute() else output.relative_to(resolved_root)
    except ValueError as exc:
        raise ManifestBuildError("manifest output must be inside the project root") from exc
    output_relative = Path(PurePosixPath(output_relative.as_posix()))
    if output_relative != MANIFEST_RELATIVE:
        raise ManifestBuildError(f"manifest output must be {MANIFEST_RELATIVE.as_posix()}")

    _validate_inventory_state(resolved_root)
    selected = _governed_paths(resolved_root)
    manifest_path = (resolved_root / output_relative).resolve(strict=False)
    if manifest_path in selected:
        raise ManifestBuildError("transfer manifest must not hash itself")

    initial_identities: dict[Path, tuple[int, int, int]] = {}
    for path in selected:
        metadata = _assert_regular_file(path, root=resolved_root)
        initial_identities[path] = (
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )

    entries: list[FileEntry] = []
    casefolded: dict[str, str] = {}
    for path, classification in sorted(
        selected.items(),
        key=lambda item: _relative_posix(item[0], resolved_root),
    ):
        relative = _relative_posix(path, resolved_root)
        _assert_not_denied(relative)
        prior = casefolded.get(relative.casefold())
        if prior is not None and prior != relative:
            raise ManifestBuildError(
                f"case-colliding paths are unsafe across filesystems: {prior} and {relative}"
            )
        casefolded[relative.casefold()] = relative
        size_bytes, digest = _sha256_stable(path, root=resolved_root)
        entries.append(
            FileEntry(
                path=relative,
                size_bytes=size_bytes,
                sha256=digest,
                classification=classification,
            )
        )

    selected_after = _governed_paths(resolved_root)
    if set(selected_after) != set(selected):
        added = sorted(
            _relative_posix(path, resolved_root)
            for path in set(selected_after).difference(selected)
        )
        removed = sorted(
            _relative_posix(path, resolved_root)
            for path in set(selected).difference(selected_after)
        )
        raise ManifestBuildError(
            f"governed inventory changed while hashing: added={added[:10]}, removed={removed[:10]}"
        )
    for path in selected:
        metadata = _assert_regular_file(path, root=resolved_root)
        observed_identity = (
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )
        if observed_identity != initial_identities[path]:
            raise ManifestBuildError(
                "governed file changed after its inventory snapshot: "
                f"{_relative_posix(path, resolved_root)}"
            )

    bytes_by_classification: Counter[str] = Counter()
    files_by_classification: Counter[str] = Counter()
    for entry in entries:
        bytes_by_classification[entry.classification] += entry.size_bytes
        files_by_classification[entry.classification] += 1
    total = sum(entry.size_bytes for entry in entries)
    return {
        "schema_version": 1,
        "repository": {
            "branch": BRANCH,
            "commit_policy": "operator_supplied",
        },
        "inventory_state": {
            "canonical_output_present": False,
            "governed_recovery_staging": STAGING_RELATIVE.as_posix(),
            "database_wal_present": False,
            "manifest_self_excluded": True,
        },
        "summary": {
            "file_count": len(entries),
            "bytes_by_classification": dict(sorted(bytes_by_classification.items())),
            "files_by_classification": dict(sorted(files_by_classification.items())),
        },
        "total_upload_bytes": total,
        "files": [entry.as_json() for entry in entries],
        "excluded": list(EXCLUDED),
    }


def _write_manifest(root: Path, output: Path, payload: dict[str, object]) -> Path:
    resolved_root = root.resolve(strict=True)
    destination = output if output.is_absolute() else resolved_root / output
    destination = destination.resolve(strict=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.writing-{uuid4().hex}")
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        temporary.write_bytes(encoded)
        temporary.replace(destination)
    except OSError as exc:
        raise ManifestBuildError(f"could not atomically write {destination}: {exc}") from exc
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination


def main() -> int:
    args = _parse_args()
    try:
        payload = _build(args.root, args.output)
        destination = _write_manifest(args.root, args.output, payload)
    except (ManifestBuildError, OSError) as exc:
        print(f"transfer manifest build failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "manifest": str(destination),
                "file_count": payload["summary"]["file_count"],
                "total_upload_bytes": payload["total_upload_bytes"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
