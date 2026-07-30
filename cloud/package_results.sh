#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
    cat <<'EOF'
Usage:
  package_results.sh --submit
  package_results.sh --execute

Create a small review archive plus a protected full-result manifest. --submit
runs the potentially long hashing work as a detached transient systemd unit.
No full-result archive is created, so the remote canonical result is not
duplicated.
EOF
}

MODE=""
while (($#)); do
    case "$1" in
        --submit|--execute)
            [[ -z "$MODE" ]] || { usage >&2; exit 2; }
            MODE="$1"
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
[[ -n "$MODE" ]] || { usage >&2; exit 2; }

ENV_FILE="/etc/project-echoes/m7.env"
if [[ ! -r "$ENV_FILE" ]]; then
    printf 'Service environment is missing.\n' >&2
    exit 1
fi
# shellcheck disable=SC1090
source "$ENV_FILE"

EXPECTED_PROMOTION_JOURNAL="$(
    dirname -- "$ECHOES_OUTPUT_DIRECTORY"
)/.schema-v1.promotion-intent.json"
if [[ "${ECHOES_PROMOTION_JOURNAL:-}" != "$EXPECTED_PROMOTION_JOURNAL" ]]; then
    printf 'Installed lexical promotion journal path is missing or not governed.\n' >&2
    exit 1
fi

require_sealed_promotion() {
    if [[ -e "$ECHOES_PROMOTION_JOURNAL" || -L "$ECHOES_PROMOTION_JOURNAL" ]]; then
        printf 'Packaging cannot discard or hide the active promotion journal: %s\n' \
            "$ECHOES_PROMOTION_JOURNAL" >&2
        printf 'Run detached strict validation/provenance recovery first: sudo bash %s/cloud/cloud_validate.sh --submit\n' \
            "$ECHOES_REPO_ROOT" >&2
        exit 1
    fi
}

require_successful_service_result() {
    local active result
    active="$(systemctl show echoes-m7.service --property=ActiveState --value)"
    result="$(systemctl show echoes-m7.service --property=Result --value)"
    if [[ "$active" != "inactive" || "$result" != "success" ]]; then
        printf 'Packaging requires inactive echoes-m7.service with Result=success; observed active=%s result=%s.\n' \
            "$active" "$result" >&2
        exit 1
    fi
}

if [[ "$MODE" == "--submit" ]]; then
    if [[ $EUID -ne 0 ]]; then
        printf 'Package submission must run as root (use sudo).\n' >&2
        exit 1
    fi
    if systemctl is-active --quiet echoes-m7.service; then
        printf 'Refusing packaging while echoes-m7.service is active.\n' >&2
        exit 1
    fi
    require_successful_service_result
    require_sealed_promotion
    for pointer in \
        "$ECHOES_STATE_ROOT/latest-validation-unit.txt" \
        "$ECHOES_STATE_ROOT/latest-package-unit.txt"; do
        if [[ -f "$pointer" && ! -L "$pointer" ]]; then
            prior_unit="$(<"$pointer")"
            if [[ -n "$prior_unit" ]] &&
                systemctl is-active --quiet "$prior_unit"; then
                printf 'Refusing duplicate/concurrent cloud task: %s\n' "$prior_unit" >&2
                exit 1
            fi
        fi
    done
    if [[ ! -f "$ECHOES_STATE_ROOT/latest-validation.json" ||
        -L "$ECHOES_STATE_ROOT/latest-validation.json" ||
        "$(jq -r '.passed // false' "$ECHOES_STATE_ROOT/latest-validation.json")" != "true" ||
        "$(jq -r '.service_completion.systemd_result // ""' "$ECHOES_STATE_ROOT/latest-validation.json")" != "success" ||
        "$(jq -r '.service_completion.systemd_result_passed // false' "$ECHOES_STATE_ROOT/latest-validation.json")" != "true" ||
        "$(jq -r '.service_completion.final_active_state // ""' "$ECHOES_STATE_ROOT/latest-validation.json")" != "inactive" ||
        "$(jq -r '.service_completion.final_systemd_result // ""' "$ECHOES_STATE_ROOT/latest-validation.json")" != "success" ||
        "$(jq -r '.lexical_promotion.journal_exists // true' "$ECHOES_STATE_ROOT/latest-validation.json")" != "false" ||
        "$(jq -r '.lexical_promotion.finalization_passed // false' "$ECHOES_STATE_ROOT/latest-validation.json")" != "true" ||
        "$(jq -r '.lexical_promotion.current_commit.execution_status // ""' "$ECHOES_STATE_ROOT/latest-validation.json")" != "succeeded" ]]; then
        printf 'A successful latest-validation.json is required before packaging.\n' >&2
        exit 1
    fi
    timestamp="$(date -u +%Y%m%dT%H%M%S.%3NZ)"
    unit="echoes-m7-package-$timestamp"
    stdout_path="$ECHOES_LOG_ROOT/$unit.stdout.log"
    stderr_path="$ECHOES_LOG_ROOT/$unit.stderr.log"
    install -o echoes -g echoes -m 0600 /dev/null "$stdout_path"
    install -o echoes -g echoes -m 0600 /dev/null "$stderr_path"
    printf '%s\n' "$unit.service" >"$ECHOES_STATE_ROOT/latest-package-unit.txt"
    printf '%s\n' "$stdout_path" >"$ECHOES_STATE_ROOT/latest-package-stdout.txt"
    printf '%s\n' "$stderr_path" >"$ECHOES_STATE_ROOT/latest-package-stderr.txt"
    chown echoes:echoes \
        "$ECHOES_STATE_ROOT/latest-package-unit.txt" \
        "$ECHOES_STATE_ROOT/latest-package-stdout.txt" \
        "$ECHOES_STATE_ROOT/latest-package-stderr.txt"
    chmod 0640 \
        "$ECHOES_STATE_ROOT/latest-package-unit.txt" \
        "$ECHOES_STATE_ROOT/latest-package-stdout.txt" \
        "$ECHOES_STATE_ROOT/latest-package-stderr.txt"

    systemd-run \
        --unit="$unit" \
        --description="Project Echoes M7 protected result packaging" \
        --uid=echoes \
        --gid=echoes \
        --working-directory="$ECHOES_REPO_ROOT" \
        --property=Type=exec \
        --property=Restart=no \
        --property=RuntimeMaxSec=12h \
        --property=MemoryMax=8G \
        --property=UMask=0077 \
        --property="StandardOutput=append:$stdout_path" \
        --property="StandardError=append:$stderr_path" \
        --collect \
        --no-block \
        /bin/bash "$ECHOES_REPO_ROOT/cloud/package_results.sh" --execute

    # Exactly one startup inspection; there is no sleep or polling.
    systemctl show "$unit.service" \
        --property=ActiveState \
        --property=SubState \
        --property=Result \
        --property=MainPID \
        --no-pager
    printf 'Detached packaging submitted as %s.service.\n' "$unit"
    printf 'One-shot status: sudo bash %s/cloud/cloud_status.sh\n' "$ECHOES_REPO_ROOT"
    exit 0
fi

if systemctl is-active --quiet echoes-m7.service; then
    printf 'Refusing packaging while echoes-m7.service is active.\n' >&2
    exit 1
fi
require_successful_service_result
require_sealed_promotion
VALIDATION_RECEIPT="$ECHOES_STATE_ROOT/latest-validation.json"
if [[ ! -f "$VALIDATION_RECEIPT" ||
    "$(jq -r '.passed // false' "$VALIDATION_RECEIPT")" != "true" ||
    "$(jq -r '.service_completion.systemd_result // ""' "$VALIDATION_RECEIPT")" != "success" ||
    "$(jq -r '.service_completion.systemd_result_passed // false' "$VALIDATION_RECEIPT")" != "true" ||
    "$(jq -r '.service_completion.final_active_state // ""' "$VALIDATION_RECEIPT")" != "inactive" ||
    "$(jq -r '.service_completion.final_systemd_result // ""' "$VALIDATION_RECEIPT")" != "success" ||
    "$(jq -r '.lexical_promotion.journal_exists // true' "$VALIDATION_RECEIPT")" != "false" ||
    "$(jq -r '.lexical_promotion.finalization_passed // false' "$VALIDATION_RECEIPT")" != "true" ||
    "$(jq -r '.lexical_promotion.current_commit.execution_status // ""' "$VALIDATION_RECEIPT")" != "succeeded" ]]; then
    printf 'A successful latest-validation.json is required before packaging.\n' >&2
    exit 1
fi
if [[ ! -d "$ECHOES_OUTPUT_DIRECTORY" || -L "$ECHOES_OUTPUT_DIRECTORY" ]]; then
    printf 'Canonical lexical output is missing or unsafe.\n' >&2
    exit 1
fi
if [[ ! -f "$ECHOES_DATABASE_REBIND_RECEIPT" ||
    -L "$ECHOES_DATABASE_REBIND_RECEIPT" ||
    "$(sha256sum "$ECHOES_DATABASE_REBIND_RECEIPT" | awk '{print $1}')" != "$ECHOES_DATABASE_REBIND_RECEIPT_SHA256" ||
    ! -f "$ECHOES_DATABASE_REBIND_INTENT" ||
    -L "$ECHOES_DATABASE_REBIND_INTENT" ||
    "$(sha256sum "$ECHOES_DATABASE_REBIND_INTENT" | awk '{print $1}')" != "$ECHOES_DATABASE_REBIND_INTENT_SHA256" ]]; then
    printf 'Governed database-rebind receipt or intent is missing or changed.\n' >&2
    exit 1
fi

timestamp="$(date -u +%Y%m%dT%H%M%S.%3NZ)"
temporary_root="$ECHOES_PACKAGE_ROOT/.review-package.writing-$timestamp"
review_root="$temporary_root/review"
review_archive="$ECHOES_PACKAGE_ROOT/m7-review-$timestamp.tar.zst"
full_manifest="$ECHOES_PACKAGE_ROOT/m7-full-results-$timestamp.manifest.json"
if [[ -e "$temporary_root" || -L "$temporary_root" ||
    -e "$review_archive" || -e "$full_manifest" ]]; then
    printf 'Refusing to overwrite an existing package path.\n' >&2
    exit 1
fi
mkdir -m 0700 -- "$temporary_root" "$review_root"

cleanup() {
    if [[ -n "${temporary_root:-}" &&
        "$temporary_root" == "$ECHOES_PACKAGE_ROOT"/.review-package.writing-* &&
        -d "$temporary_root" &&
        ! -L "$temporary_root" ]]; then
        rm -rf -- "$temporary_root"
    fi
}
trap cleanup EXIT

mkdir -m 0700 \
    "$review_root/control" \
    "$review_root/control/promotion-finalization" \
    "$review_root/control/promotion-journals" \
    "$review_root/control/promotion-recovery" \
    "$review_root/logs" \
    "$review_root/manifests" \
    "$review_root/metrics" \
    "$review_root/reports" \
    "$review_root/review-candidates" \
    "$review_root/validation"

cp -- "$ECHOES_REPO_ROOT/cloud/transfer-manifest.json" \
    "$review_root/manifests/transfer-manifest.json"
cp -- "$ECHOES_OUTPUT_DIRECTORY/table-hashes.json" \
    "$review_root/manifests/lexical-table-hashes.json"
cp -- "$VALIDATION_RECEIPT" "$review_root/validation/latest-validation.json"
if [[ -f "$ECHOES_STATE_ROOT/latest-launch.json" ]]; then
    cp -- "$ECHOES_STATE_ROOT/latest-launch.json" "$review_root/control/latest-launch.json"
fi
if [[ -f "$ECHOES_STATE_ROOT/bootstrap-validation.json" ]]; then
    cp -- "$ECHOES_STATE_ROOT/bootstrap-validation.json" \
        "$review_root/control/bootstrap-validation.json"
fi
if [[ -f "$ECHOES_STATE_ROOT/database-rebind.json" ]]; then
    cp -- "$ECHOES_STATE_ROOT/database-rebind.json" \
        "$review_root/control/database-rebind.json"
fi
cp -- "$ECHOES_DATABASE_REBIND_RECEIPT" \
    "$review_root/control/passage-view-rebind.json"
cp -- "$ECHOES_DATABASE_REBIND_INTENT" \
    "$review_root/control/passage-view-rebind.json.intent.json"

shopt -s nullglob
for path in \
    "$(dirname -- "$ECHOES_OUTPUT_DIRECTORY")"/.schema-v1.promotion-*.json \
    "$ECHOES_STATE_ROOT"/.schema-v1.promotion-*.json; do
    if [[ ! -f "$path" || -L "$path" ]]; then
        printf 'Promotion journal archive is unsafe and remains preserved: %s\n' \
            "$path" >&2
        exit 1
    fi
    journal_hash="$(sha256sum "$path" | awk '{print $1}')"
    if ! jq -e \
        --arg path "$path" \
        --arg sha256 "$journal_hash" \
        '.lexical_promotion.journals
            | any(.path == $path and .sha256 == $sha256)' \
        "$VALIDATION_RECEIPT" >/dev/null; then
        printf 'Promotion journal was not authenticated by the successful validation: %s\n' \
            "$path" >&2
        exit 1
    fi
    if [[ "$(dirname -- "$path")" == "$ECHOES_STATE_ROOT" ]]; then
        journal_prefix="cloud-state"
    else
        journal_prefix="lexical-parent"
    fi
    cp -- "$path" \
        "$review_root/control/promotion-journals/$journal_prefix-$(basename -- "$path")"
done
for path in \
    "$ECHOES_STATE_ROOT"/promotion-recovery-*.json \
    "$ECHOES_STATE_ROOT"/latest-promotion-recovery.json; do
    if [[ ! -f "$path" || -L "$path" ]]; then
        printf 'Promotion recovery receipt is unsafe: %s\n' "$path" >&2
        exit 1
    fi
    cp -- "$path" \
        "$review_root/control/promotion-recovery/$(basename -- "$path")"
done
for path in \
    "$ECHOES_STATE_ROOT"/promotion-finalization-*.json \
    "$ECHOES_STATE_ROOT"/latest-promotion-finalization.json; do
    if [[ ! -f "$path" || -L "$path" ]]; then
        printf 'Promotion finalization receipt is unsafe: %s\n' "$path" >&2
        exit 1
    fi
    cp -- "$path" \
        "$review_root/control/promotion-finalization/$(basename -- "$path")"
done
shopt -u nullglob

MAX_REVIEW_LOG_BYTES=$((2 * 1024 * 1024))
while IFS= read -r -d '' path; do
    log_name="$(basename -- "$path")"
    log_size="$(stat --format='%s' "$path")"
    if ((log_size <= MAX_REVIEW_LOG_BYTES)); then
        cp -- "$path" "$review_root/logs/$log_name"
    else
        {
            head -c $((MAX_REVIEW_LOG_BYTES / 2)) -- "$path"
            printf '\n\n[... bounded review excerpt; full log remains protected remotely ...]\n\n'
            tail -c $((MAX_REVIEW_LOG_BYTES / 2)) -- "$path"
        } >"$review_root/logs/$log_name.excerpt"
    fi
done < <(find "$ECHOES_LOG_ROOT" -maxdepth 1 -type f -name '*.log' -print0)

while IFS= read -r -d '' path; do
    cp -- "$path" "$review_root/reports/$(basename -- "$path")"
done < <(
    find "$ECHOES_REPO_ROOT/outputs/reports" -maxdepth 1 -type f \
        \( -name 'm7-*' -o -name 'milestone-7-*' -o -name 'overnight-run-summary.md' \) \
        -print0
)

for artifact in \
    lexical_metadata \
    lexical_issues \
    evaluation_results \
    threshold_calibration \
    null_replicate_summaries \
    sensitivity_results; do
    source_directory="$ECHOES_OUTPUT_DIRECTORY/$artifact"
    if [[ -d "$source_directory" && ! -L "$source_directory" ]]; then
        cp -a -- "$source_directory" "$review_root/metrics/$artifact"
    fi
done

execution_root="$ECHOES_OUTPUT_DIRECTORY/../execution-manifests"
if [[ -d "$execution_root" && ! -L "$execution_root" ]]; then
    cp -a -- "$execution_root" "$review_root/manifests/execution-manifests"
fi

/usr/local/bin/uv run \
    --directory "$ECHOES_REPO_ROOT" \
    --frozen \
    --offline \
    --no-sync \
    python - "$ECHOES_OUTPUT_DIRECTORY" \
        "$review_root/review-candidates/top-100-review-candidates.csv" <<'PY'
from pathlib import Path
import sys

import polars as pl

root = Path(sys.argv[1])
destination = Path(sys.argv[2])
parts = sorted((root / "candidate_review_queue").glob("part-*.parquet"))
if not parts:
    raise SystemExit("candidate_review_queue has no Parquet parts")
frame = (
    pl.scan_parquet(parts)
    .sort(["queue_rank", "candidate_pair_id"])
    .head(100)
    .collect(engine="streaming")
)
frame.write_csv(destination)
PY

cat >"$review_root/README.txt" <<EOF
Project Echoes Milestone 7 small review package
Generated (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)
Commit: $ECHOES_EXPECTED_COMMIT
Canonical output: $ECHOES_OUTPUT_DIRECTORY

This package contains operational logs, authenticated manifests, aggregate
metrics, validation and promotion-recovery receipts, every preserved lexical
promotion journal, sanitized reports, and at most 100 rows from the unreviewed
candidate queue. It does not contain raw biblical source trees or a copy of the
full lexical result.
EOF

(
    cd -- "$review_root"
    find . -type f ! -name CONTENTS.sha256 -print0 |
        sort -z |
        xargs -0 sha256sum >CONTENTS.sha256
)
tar --create --zstd --file "$review_archive" \
    --directory "$temporary_root" \
    review
chmod 0600 "$review_archive"
sha256sum "$review_archive" >"$review_archive.sha256"
chmod 0600 "$review_archive.sha256"

/usr/local/bin/uv run \
    --directory "$ECHOES_REPO_ROOT" \
    --frozen \
    --offline \
    --no-sync \
    python - \
        "$ECHOES_REPO_ROOT" \
        "$ECHOES_OUTPUT_DIRECTORY" \
        "$ECHOES_DATABASE" \
        "$ECHOES_STATE_ROOT" \
        "$ECHOES_LOG_ROOT" \
        "$full_manifest" \
        "$ECHOES_EXPECTED_COMMIT" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

repository = Path(sys.argv[1]).resolve()
canonical = Path(sys.argv[2]).resolve()
database = Path(sys.argv[3]).resolve()
state = Path(sys.argv[4]).resolve()
logs = Path(sys.argv[5]).resolve()
destination = Path(sys.argv[6])
commit = sys.argv[7]
files: dict[Path, str] = {}


def add_file(path: Path, label: str) -> None:
    if path.is_file() and not path.is_symlink():
        files[path.resolve()] = label


for root, label in (
    (canonical, "canonical_lexical_output"),
    (canonical.parent / "execution-manifests", "execution_manifest"),
):
    if root.is_dir() and not root.is_symlink():
        for current_root, directories, names in os.walk(root, followlinks=False):
            current = Path(current_root)
            directories[:] = [
                name for name in directories if not (current / name).is_symlink()
            ]
            for name in names:
                add_file(current / name, label)
for path in canonical.parent.glob(".schema-v1.promotion-*.json"):
    add_file(path, "lexical_promotion_journal")
add_file(database, "project_database")
for path in state.glob("*.json"):
    add_file(path, "cloud_state_or_validation")
for path in logs.glob("*.log"):
    add_file(path, "cloud_log")
for pattern in ("m7-*", "milestone-7-*", "overnight-run-summary.md"):
    for path in (repository / "outputs/reports").glob(pattern):
        add_file(path, "sanitized_report")

entries = []
total = 0
for path, classification in sorted(files.items(), key=lambda item: str(item[0])):
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            hasher.update(block)
    size = path.stat().st_size
    total += size
    try:
        relative = path.relative_to(repository).as_posix()
        namespace = "repository"
    except ValueError:
        relative = str(path)
        namespace = "server_absolute"
    entries.append(
        {
            "namespace": namespace,
            "path": relative,
            "size_bytes": size,
            "sha256": hasher.hexdigest(),
            "classification": classification,
        }
    )

payload = {
    "schema_version": 1,
    "generated_at_utc": datetime.now(UTC).isoformat(),
    "repository_commit": commit,
    "protected_remote_only": True,
    "full_archive_created": False,
    "file_count": len(entries),
    "total_bytes": total,
    "files": entries,
}
temporary = destination.with_name(f".{destination.name}.writing-{os.getpid()}")
temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(destination)
PY
chmod 0600 "$full_manifest"
sha256sum "$full_manifest" >"$full_manifest.sha256"
chmod 0600 "$full_manifest.sha256"

printf '%s\n' "$review_archive" >"$ECHOES_STATE_ROOT/latest-review-package.txt.writing-$$"
mv -f -- \
    "$ECHOES_STATE_ROOT/latest-review-package.txt.writing-$$" \
    "$ECHOES_STATE_ROOT/latest-review-package.txt"
printf '%s\n' "$full_manifest" >"$ECHOES_STATE_ROOT/latest-full-manifest.txt.writing-$$"
mv -f -- \
    "$ECHOES_STATE_ROOT/latest-full-manifest.txt.writing-$$" \
    "$ECHOES_STATE_ROOT/latest-full-manifest.txt"

printf 'Small review package: %s\n' "$review_archive"
printf 'Small review SHA-256: %s\n' "$(awk '{print $1}' "$review_archive.sha256")"
printf 'Protected full-result manifest: %s\n' "$full_manifest"
printf 'No duplicate full-result archive was created.\n'
