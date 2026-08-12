#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
    cat <<'EOF'
Usage: verify_transfer.sh [--root PATH] [--manifest PATH]
                          [--rebind-receipt PATH] [--json] [--quiet]

Verify every transferable file in cloud/transfer-manifest.json by confined
relative path, exact byte size, and SHA-256. The manifest is intentionally not
self-listed because a file cannot contain its own stable hash. A successful
governed passage-view-rebind receipt permits repeat verification after the one
transactional Linux view rebind has intentionally changed the database bytes.
EOF
}

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
MANIFEST_PATH="$SCRIPT_DIR/transfer-manifest.json"
OUTPUT_JSON=0
QUIET=0
REBIND_RECEIPT=""

while (($#)); do
    case "$1" in
        --root)
            (($# >= 2)) || { usage >&2; exit 2; }
            PROJECT_ROOT="$2"
            shift 2
            ;;
        --manifest)
            (($# >= 2)) || { usage >&2; exit 2; }
            MANIFEST_PATH="$2"
            shift 2
            ;;
        --rebind-receipt)
            (($# >= 2)) || { usage >&2; exit 2; }
            REBIND_RECEIPT="$2"
            shift 2
            ;;
        --json)
            OUTPUT_JSON=1
            shift
            ;;
        --quiet)
            QUIET=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            printf 'Unknown argument: %s\n' "$1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

command -v python3 >/dev/null 2>&1 || {
    printf 'python3 is required to verify the transfer manifest.\n' >&2
    exit 1
}

if [[ ! -d "$PROJECT_ROOT" ]]; then
    printf 'Project root does not exist: %s\n' "$PROJECT_ROOT" >&2
    exit 1
fi
if [[ ! -f "$MANIFEST_PATH" || -L "$MANIFEST_PATH" ]]; then
    printf 'Transfer manifest is missing or unsafe: %s\n' "$MANIFEST_PATH" >&2
    exit 1
fi

set +e
RESULT="$(
    python3 - "$PROJECT_ROOT" "$MANIFEST_PATH" "$REBIND_RECEIPT" <<'PY'
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

root = Path(sys.argv[1]).resolve()
manifest_path = Path(sys.argv[2]).resolve()
rebind_receipt_argument = Path(sys.argv[3]) if sys.argv[3] else None
rebind_receipt_path = (
    rebind_receipt_argument.resolve() if rebind_receipt_argument is not None else None
)
errors: list[dict[str, str]] = []


def error(code: str, message: str, path: str = "") -> None:
    errors.append({"code": code, "path": path, "message": message})


try:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
except (OSError, UnicodeError, json.JSONDecodeError) as exc:
    print(
        json.dumps(
            {
                "schema_version": 1,
                "passed": False,
                "verified_file_count": 0,
                "verified_bytes": 0,
                "errors": [
                    {
                        "code": "manifest_unreadable",
                        "path": str(manifest_path),
                        "message": str(exc),
                    }
                ],
            },
            sort_keys=True,
        )
    )
    raise SystemExit(1)

if not isinstance(payload, dict):
    error("manifest_shape", "manifest root must be a JSON object")
    payload = {}
if payload.get("schema_version") != 1:
    error("manifest_schema", "schema_version must be exactly 1")

raw_entries = payload.get("files", payload.get("entries"))
if not isinstance(raw_entries, list) or not raw_entries:
    error("manifest_files", "files must be a nonempty array")
    raw_entries = []

expected_total = payload.get("total_upload_bytes", payload.get("required_upload_bytes"))
if not isinstance(expected_total, int) or isinstance(expected_total, bool) or expected_total < 0:
    error(
        "manifest_total",
        "total_upload_bytes (or required_upload_bytes) must be a nonnegative integer",
    )
    expected_total = None

rebind: dict[str, object] | None = None
rebind_intent_path: Path | None = None
if rebind_receipt_path is not None:
    if rebind_receipt_argument is not None and rebind_receipt_argument.is_symlink():
        error(
            "rebind_receipt_symlink",
            "passage-view-rebind receipt may not be a symlink",
            str(rebind_receipt_argument),
        )
    try:
        candidate = json.loads(rebind_receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        error("rebind_receipt_unreadable", str(exc), str(rebind_receipt_path))
    else:
        if not isinstance(candidate, dict):
            error(
                "rebind_receipt_shape",
                "passage-view-rebind receipt must be a JSON object",
                str(rebind_receipt_path),
            )
        elif candidate.get("schema_version") != 1:
            error(
                "rebind_receipt_invalid",
                "passage-view-rebind schema_version must be exactly 1",
                str(rebind_receipt_path),
            )
        else:
            before = candidate.get("before_database_sha256")
            after = candidate.get("after_database_sha256")
            database_path = candidate.get("database_path")
            passage_root = candidate.get("passage_root")
            view_globs = candidate.get("view_globs")
            tiny_reads = candidate.get("tiny_read_has_rows")
            expected_database = (root / "data/processed/project_echoes.duckdb").resolve()
            expected_passages = (root / "data/processed/passages/schema-v1").resolve()
            if (
                not isinstance(before, str)
                or re.fullmatch(r"[0-9a-f]{64}", before) is None
                or not isinstance(after, str)
                or re.fullmatch(r"[0-9a-f]{64}", after) is None
                or database_path != str(expected_database)
                or passage_root != str(expected_passages)
                or not isinstance(candidate.get("duckdb_version"), str)
                or not isinstance(view_globs, dict)
                or len(view_globs) != 6
                or not isinstance(tiny_reads, dict)
                or len(tiny_reads) != 6
            ):
                error(
                    "rebind_receipt_identity",
                    "passage-view-rebind receipt has malformed or unexpected identity fields",
                    str(rebind_receipt_path),
                )
            else:
                rebind_intent_path = rebind_receipt_path.with_name(
                    f"{rebind_receipt_path.name}.intent.json"
                )
                try:
                    intent = json.loads(
                        rebind_intent_path.read_text(encoding="utf-8")
                    )
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    error(
                        "rebind_intent_unreadable",
                        str(exc),
                        str(rebind_intent_path),
                    )
                else:
                    if rebind_intent_path.is_symlink():
                        error(
                            "rebind_intent_symlink",
                            "passage-view-rebind intent may not be a symlink",
                            str(rebind_intent_path),
                        )
                    if (
                        not isinstance(intent, dict)
                        or intent.get("schema_version") != 1
                        or intent.get("database_path") != database_path
                        or intent.get("passage_root") != passage_root
                        or intent.get("before_database_sha256") != before
                        or intent.get("duckdb_version")
                        != candidate.get("duckdb_version")
                        or intent.get("view_globs") != view_globs
                    ):
                        error(
                            "rebind_intent_identity",
                            "passage-view-rebind intent differs from its receipt",
                            str(rebind_intent_path),
                        )
                    else:
                        rebind = candidate

allowed_classifications = {
    "required",
    "recoverable_checkpoint",
    "final_output",
    "regenerable",
    "obsolete_or_excluded",
    "excluded",
}
seen: set[str] = set()
verified_count = 0
verified_bytes = 0
rebind_applied_count = 0
rebind_original_size: int | None = None
rebind_observed_size: int | None = None

for index, raw in enumerate(raw_entries):
    if not isinstance(raw, dict):
        error("entry_shape", f"files[{index}] must be an object")
        continue
    relative = raw.get("path", raw.get("relative_path"))
    size = raw.get("size_bytes", raw.get("byte_size"))
    digest = raw.get("sha256")
    classification = raw.get("classification")
    transfer = raw.get("transfer", raw.get("required", True))

    if transfer is False:
        continue
    if transfer is not True:
        error("entry_transfer", f"files[{index}] transfer/required must be boolean")
        continue
    if not isinstance(relative, str) or not relative:
        error("entry_path", f"files[{index}] has no relative path")
        continue
    if "\\" in relative or "\0" in relative:
        error("unsafe_path", "paths must use POSIX separators and contain no NUL", relative)
        continue
    pure = PurePosixPath(relative)
    if pure.is_absolute() or relative.startswith("/") or any(part in {"", ".", ".."} for part in pure.parts):
        error("unsafe_path", "path is absolute, empty, or traverses outside the root", relative)
        continue
    normalized = pure.as_posix()
    if normalized != relative:
        error("noncanonical_path", f"path must be canonical POSIX form: {normalized}", relative)
        continue
    if normalized in seen:
        error("duplicate_path", "path appears more than once", normalized)
        continue
    seen.add(normalized)
    if classification not in allowed_classifications:
        error("classification", f"unsupported classification: {classification!r}", normalized)
    if classification in {"obsolete_or_excluded", "excluded", "regenerable"}:
        error(
            "excluded_transfer",
            f"{classification} entries must not be marked for transfer",
            normalized,
        )
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        error("entry_size", "size_bytes must be a nonnegative integer", normalized)
        continue
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        error("entry_hash", "sha256 must be exactly 64 lowercase hex characters", normalized)
        continue

    expected_size: int | None = size
    expected_digest = digest
    if rebind is not None and normalized == "data/processed/project_echoes.duckdb":
        rebind_applied_count += 1
        original_digest = rebind.get("before_database_sha256")
        rebound_digest = rebind.get("after_database_sha256")
        if str(original_digest).lower() != digest.lower():
            error(
                "rebind_original_mismatch",
                "rebind receipt original database identity differs from transfer manifest",
                normalized,
            )
            continue
        rebind_original_size = size
        # The governed receipt authenticates the post-rebind content hash. Its
        # schema intentionally does not duplicate a byte count, so the observed
        # authenticated size is used for the adjusted total below.
        expected_size = None
        expected_digest = rebound_digest

    candidate = root.joinpath(*pure.parts)
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        error("missing_file", str(exc), normalized)
        continue
    try:
        resolved.relative_to(root)
    except ValueError:
        error("escaped_root", "resolved path is outside the project root", normalized)
        continue

    current = root
    unsafe_component = False
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            error("symlink", "transfer payload may not contain symlinks", normalized)
            unsafe_component = True
            break
    if unsafe_component:
        continue
    if not resolved.is_file():
        error("not_file", "transfer entry is not a regular file", normalized)
        continue

    observed_size = resolved.stat().st_size
    if expected_size is not None and observed_size != expected_size:
        error(
            "size_mismatch",
            f"expected={expected_size}, observed={observed_size}",
            normalized,
        )
        continue
    hasher = hashlib.sha256()
    try:
        with resolved.open("rb") as stream:
            for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                hasher.update(block)
    except OSError as exc:
        error("hash_read_error", str(exc), normalized)
        continue
    observed_digest = hasher.hexdigest()
    if observed_digest.lower() != expected_digest.lower():
        error(
            "hash_mismatch",
            f"expected={expected_digest.lower()}, observed={observed_digest}",
            normalized,
        )
        continue
    if rebind is not None and normalized == "data/processed/project_echoes.duckdb":
        rebind_observed_size = observed_size
    verified_count += 1
    verified_bytes += observed_size

effective_expected_total = expected_total
if rebind is not None:
    if (
        rebind_applied_count != 1
        or rebind_original_size is None
        or rebind_observed_size is None
    ):
        error(
            "rebind_database_entry",
            "rebind receipt must authenticate exactly one transferred project database",
        )
        effective_expected_total = None
    elif expected_total is not None:
        effective_expected_total = (
            expected_total - rebind_original_size + rebind_observed_size
        )
if effective_expected_total is not None and verified_bytes != effective_expected_total:
    error(
        "total_mismatch",
        f"expected={effective_expected_total}, verified={verified_bytes}",
    )

repository = payload.get("repository")
if not isinstance(repository, dict):
    error("repository_policy", "repository must be an object")
elif repository.get("commit_policy") != "operator_supplied":
    error(
        "repository_commit_policy",
        "repository.commit_policy must be exactly operator_supplied",
    )
elif "commit" in repository:
    error(
        "repository_embedded_commit",
        "transfer manifest must not embed its self-referential final commit",
    )
elif (root / ".git").exists():
    expected_branch = repository.get("branch")
    if isinstance(expected_branch, str) and expected_branch:
        result = subprocess.run(
            ["git", "-C", str(root), "branch", "--show-current"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or result.stdout.strip() != expected_branch:
            error(
                "repository_branch",
                f"expected={expected_branch}, observed={result.stdout.strip()}",
            )
    else:
        error("repository_branch_policy", "repository.branch must be nonempty")
else:
    error("repository_checkout", "project root must be a Git checkout")

report = {
    "schema_version": 1,
    "project_root": str(root),
    "manifest_path": str(manifest_path),
    "passed": not errors,
    "declared_file_count": len(raw_entries),
    "verified_file_count": verified_count,
    "declared_upload_bytes": expected_total,
    "effective_expected_bytes": effective_expected_total,
    "verified_bytes": verified_bytes,
    "database_rebind_receipt": (
        None if rebind_receipt_path is None else str(rebind_receipt_path)
    ),
    "database_rebind_intent": (
        None if rebind_intent_path is None else str(rebind_intent_path)
    ),
    "errors": errors,
}
print(json.dumps(report, indent=2, sort_keys=True))
raise SystemExit(0 if not errors else 1)
PY
)"
STATUS=$?
set -e

if ((OUTPUT_JSON)); then
    printf '%s\n' "$RESULT"
elif ((STATUS == 0)); then
    if ((QUIET == 0)); then
        VERIFIED_FILES="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["verified_file_count"])' <<<"$RESULT")"
        VERIFIED_BYTES="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["verified_bytes"])' <<<"$RESULT")"
        printf 'Transfer verification passed: files=%s bytes=%s\n' "$VERIFIED_FILES" "$VERIFIED_BYTES"
    fi
else
    printf '%s\n' "$RESULT" >&2
fi

exit "$STATUS"
