#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
    cat <<'EOF'
Usage:
  cloud_validate.sh --submit
  cloud_validate.sh --execute

--submit launches the potentially long validation as one detached transient
systemd unit, performs one startup inspection, and returns. --execute is the
internal worker mode used by that unit; do not run it while the pipeline is
active.
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

RECOVERY_COMMITTED_ACTIVE=false
RECOVERY_COMMITTED_ARCHIVED=false

authenticated_committed_recovery() {
    local latest="$ECHOES_STATE_ROOT/latest-promotion-recovery.json"
    local journal_hash archived_journal archived_hash immutable_receipt
    local witness_manifest witness_execution_id witness_status
    [[ -f "$ECHOES_PROMOTION_JOURNAL" &&
        ! -L "$ECHOES_PROMOTION_JOURNAL" &&
        "$(stat --format='%s' "$ECHOES_PROMOTION_JOURNAL")" -le 65536 &&
        -f "$latest" &&
        ! -L "$latest" &&
        "$(stat --format='%s' "$latest")" -le 65536 ]] || return 1
    journal_hash="$(sha256sum "$ECHOES_PROMOTION_JOURNAL" | awk '{print $1}')"
    [[ "$(jq -r '.schema_version // 0' "$latest")" == "1" &&
        "$(jq -r '.passed // false' "$latest")" == "true" &&
        "$(jq -r '.state // ""' "$latest")" == "canonical_committed" &&
        "$(jq -r '.canonical_output_present // false' "$latest")" == "true" &&
        "$(jq -r '.journal_path // ""' "$latest")" == "$ECHOES_PROMOTION_JOURNAL" &&
        "$(jq -r '.journal_before_sha256 // ""' "$latest")" == "$journal_hash" &&
        "$(jq -r '.journal_after_exists // false' "$latest")" == "true" &&
        "$(jq -r '.commit_witness.kind // ""' "$latest")" == "active_journal" &&
        "$(jq -r '.commit_witness.journal // ""' "$latest")" == "$ECHOES_PROMOTION_JOURNAL" &&
        "$(jq -r '.commit_witness.journal_sha256 // ""' "$latest")" == "$journal_hash" ]] ||
        return 1
    archived_journal="$(jq -r '.archived_journal // ""' "$latest")"
    archived_hash="$(jq -r '.archived_journal_sha256 // ""' "$latest")"
    immutable_receipt="$(jq -r '.receipt_path // ""' "$latest")"
    witness_manifest="$(jq -r '.commit_witness.execution_manifest // ""' "$latest")"
    witness_execution_id="$(jq -r '.commit_witness.execution_id // ""' "$latest")"
    witness_status="$(jq -r '.commit_witness.execution_status_at_recovery // ""' "$latest")"
    [[ "$(dirname -- "$archived_journal")" == "$ECHOES_STATE_ROOT" &&
        "$(basename -- "$archived_journal")" =~ ^\.schema-v1\.promotion-[A-Za-z0-9._-]+\.json$ &&
        -f "$archived_journal" &&
        ! -L "$archived_journal" &&
        "$(sha256sum "$archived_journal" | awk '{print $1}')" == "$archived_hash" &&
        "$archived_hash" == "$journal_hash" &&
        "$(dirname -- "$immutable_receipt")" == "$ECHOES_STATE_ROOT" &&
        "$(basename -- "$immutable_receipt")" =~ ^promotion-recovery-[0-9]{8}T[0-9]{6}\.[0-9]{3}Z\.json$ &&
        -f "$immutable_receipt" &&
        ! -L "$immutable_receipt" &&
        "$(sha256sum "$immutable_receipt" | awk '{print $1}')" == \
            "$(sha256sum "$latest" | awk '{print $1}')" &&
        -f "$witness_manifest" &&
        ! -L "$witness_manifest" &&
        "$(jq -r '.execution_id // ""' "$witness_manifest")" == "$witness_execution_id" &&
        "$(jq -r '.execution_status // ""' "$witness_manifest")" == "$witness_status" ]]
}

authenticated_archived_committed_recovery() {
    local latest="$ECHOES_STATE_ROOT/latest-promotion-recovery.json"
    local immutable_receipt witness_journal witness_hash witness_manifest
    local witness_execution_id
    [[ ! -e "$ECHOES_PROMOTION_JOURNAL" &&
        ! -L "$ECHOES_PROMOTION_JOURNAL" &&
        -f "$latest" &&
        ! -L "$latest" &&
        "$(stat --format='%s' "$latest")" -le 65536 &&
        "$(jq -r '.schema_version // 0' "$latest")" == "1" &&
        "$(jq -r '.passed // false' "$latest")" == "true" &&
        "$(jq -r '.state // ""' "$latest")" == "canonical_committed" &&
        "$(jq -r '.canonical_output_present // false' "$latest")" == "true" &&
        "$(jq -r '.journal_path // ""' "$latest")" == "$ECHOES_PROMOTION_JOURNAL" &&
        "$(jq -r '.journal_before_exists // true' "$latest")" == "false" &&
        "$(jq -r '.journal_after_exists // true' "$latest")" == "false" &&
        "$(jq -r '.commit_witness.kind // ""' "$latest")" == "archived_journal" ]] ||
        return 1
    immutable_receipt="$(jq -r '.receipt_path // ""' "$latest")"
    witness_journal="$(jq -r '.commit_witness.journal // ""' "$latest")"
    witness_hash="$(jq -r '.commit_witness.journal_sha256 // ""' "$latest")"
    witness_manifest="$(jq -r '.commit_witness.execution_manifest // ""' "$latest")"
    witness_execution_id="$(jq -r '.commit_witness.execution_id // ""' "$latest")"
    [[ "$(dirname -- "$immutable_receipt")" == "$ECHOES_STATE_ROOT" &&
        "$(basename -- "$immutable_receipt")" =~ ^promotion-recovery-[0-9]{8}T[0-9]{6}\.[0-9]{3}Z\.json$ &&
        -f "$immutable_receipt" &&
        ! -L "$immutable_receipt" &&
        "$(sha256sum "$immutable_receipt" | awk '{print $1}')" == \
            "$(sha256sum "$latest" | awk '{print $1}')" &&
        "$(dirname -- "$witness_journal")" == "$(dirname -- "$ECHOES_OUTPUT_DIRECTORY")" &&
        "$(basename -- "$witness_journal")" =~ ^\.schema-v1\.promotion-journal-(canonical-)?committed-[0-9a-f]{32}\.json$ &&
        -f "$witness_journal" &&
        ! -L "$witness_journal" &&
        "$(sha256sum "$witness_journal" | awk '{print $1}')" == "$witness_hash" &&
        -f "$witness_manifest" &&
        ! -L "$witness_manifest" &&
        "$(jq -r '.execution_id // ""' "$witness_manifest")" == "$witness_execution_id" &&
        "$(jq -r '.execution_status // ""' "$witness_manifest")" == "succeeded" ]]
}

require_resolved_or_committed_promotion() {
    RECOVERY_COMMITTED_ACTIVE=false
    RECOVERY_COMMITTED_ARCHIVED=false
    if [[ -e "$ECHOES_PROMOTION_JOURNAL" || -L "$ECHOES_PROMOTION_JOURNAL" ]]; then
        if authenticated_committed_recovery; then
            RECOVERY_COMMITTED_ACTIVE=true
            return
        fi
        printf 'An unresolved or unauthenticated lexical promotion journal is preserved at %s.\n' \
            "$ECHOES_PROMOTION_JOURNAL" >&2
        printf 'Run bounded recovery first: sudo bash %s/cloud/cloud_start.sh\n' \
            "$ECHOES_REPO_ROOT" >&2
        printf 'Never edit or delete the journal.\n' >&2
        exit 1
    fi
    if authenticated_archived_committed_recovery; then
        RECOVERY_COMMITTED_ARCHIVED=true
    fi
}

if [[ "$MODE" == "--submit" ]]; then
    if [[ $EUID -ne 0 ]]; then
        printf 'Validation submission must run as root (use sudo).\n' >&2
        exit 1
    fi
    if systemctl is-active --quiet echoes-m7.service; then
        printf 'Refusing validation while echoes-m7.service is active.\n' >&2
        exit 1
    fi
    require_resolved_or_committed_promotion
    submit_service_active="$(
        systemctl show echoes-m7.service --property=ActiveState --value
    )"
    submit_service_result="$(
        systemctl show echoes-m7.service --property=Result --value
    )"
    if [[ "$submit_service_active" != "inactive" ||
        "$submit_service_result" != "success" ]]; then
        printf 'Strict acceptance requires inactive service with Result=success; observed active=%s result=%s.\n' \
            "$submit_service_active" "$submit_service_result" >&2
        printf 'Recovered canonical evidence remains preserved but cannot override this gate.\n' >&2
        exit 1
    fi
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
    timestamp="$(date -u +%Y%m%dT%H%M%S.%3NZ)"
    unit="echoes-m7-validation-$timestamp"
    stdout_path="$ECHOES_LOG_ROOT/$unit.stdout.log"
    stderr_path="$ECHOES_LOG_ROOT/$unit.stderr.log"
    install -o echoes -g echoes -m 0600 /dev/null "$stdout_path"
    install -o echoes -g echoes -m 0600 /dev/null "$stderr_path"
    printf '%s\n' "$unit.service" >"$ECHOES_STATE_ROOT/latest-validation-unit.txt"
    printf '%s\n' "$stdout_path" >"$ECHOES_STATE_ROOT/latest-validation-stdout.txt"
    printf '%s\n' "$stderr_path" >"$ECHOES_STATE_ROOT/latest-validation-stderr.txt"
    chown echoes:echoes \
        "$ECHOES_STATE_ROOT/latest-validation-unit.txt" \
        "$ECHOES_STATE_ROOT/latest-validation-stdout.txt" \
        "$ECHOES_STATE_ROOT/latest-validation-stderr.txt"
    chmod 0640 \
        "$ECHOES_STATE_ROOT/latest-validation-unit.txt" \
        "$ECHOES_STATE_ROOT/latest-validation-stdout.txt" \
        "$ECHOES_STATE_ROOT/latest-validation-stderr.txt"

    systemd-run \
        --unit="$unit" \
        --description="Project Echoes M7 strict cloud validation" \
        --uid=echoes \
        --gid=echoes \
        --working-directory="$ECHOES_REPO_ROOT" \
        --property=Type=exec \
        --property=Restart=no \
        --property=RuntimeMaxSec=12h \
        --property=MemoryHigh=26G \
        --property=MemoryMax=28G \
        --property=MemorySwapMax=0 \
        --property=UMask=0077 \
        --property="StandardOutput=append:$stdout_path" \
        --property="StandardError=append:$stderr_path" \
        --collect \
        --no-block \
        /bin/bash "$ECHOES_REPO_ROOT/cloud/cloud_validate.sh" --execute

    # Exactly one startup inspection; there is no sleep or polling.
    systemctl show "$unit.service" \
        --property=ActiveState \
        --property=SubState \
        --property=Result \
        --property=MainPID \
        --no-pager
    printf 'Detached validation submitted as %s.service.\n' "$unit"
    printf 'One-shot status: sudo bash %s/cloud/cloud_status.sh\n' "$ECHOES_REPO_ROOT"
    exit 0
fi

if systemctl is-active --quiet echoes-m7.service; then
    printf 'Refusing validation while echoes-m7.service is active.\n' >&2
    exit 1
fi
require_resolved_or_committed_promotion
if [[ -e "$ECHOES_RESUME_STAGING" || -L "$ECHOES_RESUME_STAGING" ]]; then
    printf 'Recovered staging still exists; canonical promotion is not complete.\n' >&2
    exit 1
fi
if [[ ! -d "$ECHOES_OUTPUT_DIRECTORY" || -L "$ECHOES_OUTPUT_DIRECTORY" ]]; then
    printf 'Canonical lexical output is missing or unsafe: %s\n' \
        "$ECHOES_OUTPUT_DIRECTORY" >&2
    exit 1
fi

SERVICE_RESULT="$(systemctl show echoes-m7.service --property=Result --value)"
SERVICE_ACTIVE="$(systemctl show echoes-m7.service --property=ActiveState --value)"
RECOVERY_CONFIRMED_CANONICAL=false
LATEST_PROMOTION_RECOVERY="$ECHOES_STATE_ROOT/latest-promotion-recovery.json"
if [[ "$RECOVERY_COMMITTED_ACTIVE" == "true" ||
    "$RECOVERY_COMMITTED_ARCHIVED" == "true" ]]; then
    RECOVERY_CONFIRMED_CANONICAL=true
fi
SERVICE_RESULT_PASSED=false
if [[ "$SERVICE_RESULT" == "success" ]]; then
    SERVICE_RESULT_PASSED=true
fi
if [[ "$SERVICE_ACTIVE" != "inactive" ]]; then
    printf 'Pipeline service has not stopped: active=%s result=%s.\n' \
        "$SERVICE_ACTIVE" "$SERVICE_RESULT" >&2
    exit 1
fi
if [[ "$SERVICE_RESULT_PASSED" != "true" ]]; then
    printf 'Pipeline service did not finish successfully: active=%s result=%s.\n' \
        "$SERVICE_ACTIVE" "$SERVICE_RESULT" >&2
    printf 'Canonical recovery preserves evidence but never overrides Result=success.\n' >&2
    exit 1
fi

timestamp="$(date -u +%Y%m%dT%H%M%S.%3NZ)"
structural_path="$ECHOES_STATE_ROOT/validation-structural-$timestamp.json"
lexical_path="$ECHOES_STATE_ROOT/validation-lexical-$timestamp.json"
lexical_stderr="$ECHOES_STATE_ROOT/validation-lexical-$timestamp.stderr.log"
promotion_finalization_path="$ECHOES_STATE_ROOT/promotion-finalization-$timestamp.json"
promotion_finalization_latest="$ECHOES_STATE_ROOT/latest-promotion-finalization.json"
promotion_finalization_raw="$ECHOES_STATE_ROOT/.promotion-finalization-cli-$timestamp.writing-$$"
promotion_finalization_stderr="$ECHOES_LOG_ROOT/promotion-finalization-$timestamp.stderr.log"
receipt_path="$ECHOES_STATE_ROOT/validation-$timestamp.json"

normalize_json_result() {
    local path="$1"
    local label="$2"
    local exit_code="$3"
    if jq -e 'type == "object"' "$path" >/dev/null 2>&1; then
        return
    fi
    local preserved="${path}.invalid"
    mv -- "$path" "$preserved"
    jq -n \
        --arg label "$label" \
        --argjson exit_code "$exit_code" \
        --rawfile raw "$preserved" \
        '{
            schema_version: 1,
            passed: false,
            error: ($label + " did not emit a JSON object"),
            exit_code: $exit_code,
            raw_output: $raw
        }' >"$path"
}

set +e
/usr/local/bin/uv run \
    --directory "$ECHOES_REPO_ROOT" \
    --frozen \
    --offline \
    --no-sync \
    echoes validate-lexical \
        --all \
        --strict \
        --output-dir "$ECHOES_OUTPUT_DIRECTORY" \
        --database "$ECHOES_DATABASE" \
        --json >"$lexical_path" 2>"$lexical_stderr"
LEXICAL_STATUS=$?
set -e
normalize_json_result "$lexical_path" "strict lexical validation" "$LEXICAL_STATUS"

PROMOTION_FINALIZATION_REQUIRED="$RECOVERY_COMMITTED_ACTIVE"
PROMOTION_FINALIZATION_PASSED=true
if [[ "$PROMOTION_FINALIZATION_REQUIRED" == "true" ]]; then
    PROMOTION_FINALIZATION_PASSED=false
    JOURNAL_BEFORE_SHA256="$(
        sha256sum "$ECHOES_PROMOTION_JOURNAL" | awk '{print $1}'
    )"
    JOURNAL_EXECUTION_ID="$(jq -r '.execution_id // ""' "$ECHOES_PROMOTION_JOURNAL")"
    JOURNAL_PROMOTION_ID="$(jq -r '.promotion_id // ""' "$ECHOES_PROMOTION_JOURNAL")"
    LEXICAL_VALIDATION_SHA256="$(sha256sum "$lexical_path" | awk '{print $1}')"
    FINALIZATION_EXIT_CODE=125
    FINALIZATION_CLI_JSON=null
    FINALIZATION_ARCHIVE=""
    FINALIZATION_ARCHIVE_SHA256=""
    install -m 0600 /dev/null "$promotion_finalization_raw"
    install -m 0600 /dev/null "$promotion_finalization_stderr"

    if ((LEXICAL_STATUS == 0)) &&
        [[ "$(jq -r '.passed // false' "$lexical_path")" == "true" &&
            "$(jq -r '.strict // false' "$lexical_path")" == "true" ]]; then
        set +e
        /usr/local/bin/uv run \
            --directory "$ECHOES_REPO_ROOT" \
            --frozen \
            --offline \
            --no-sync \
            echoes finalize-lexical-promotion-recovery \
                --validation-report "$lexical_path" \
                --service-result "$SERVICE_RESULT" \
                --database "$ECHOES_DATABASE" \
                --output-dir "$ECHOES_OUTPUT_DIRECTORY" \
                --json >"$promotion_finalization_raw" \
                2>"$promotion_finalization_stderr"
        FINALIZATION_EXIT_CODE=$?
        set -e
    else
        printf 'Strict lexical validation did not pass; committed journal remains active.\n' \
            >"$promotion_finalization_stderr"
    fi

    FINALIZATION_RAW_SIZE="$(stat --format='%s' "$promotion_finalization_raw")"
    if ((FINALIZATION_EXIT_CODE == 0)) &&
        [[ "$FINALIZATION_RAW_SIZE" =~ ^[0-9]+$ &&
            "$FINALIZATION_RAW_SIZE" -le 65536 ]] &&
        jq -e \
            --arg execution_id "$JOURNAL_EXECUTION_ID" \
            --arg validation_report "$lexical_path" \
            --arg validation_sha256 "$LEXICAL_VALIDATION_SHA256" \
            --arg service_result "$SERVICE_RESULT" \
            '
                type == "object"
                and (keys | sort) == [
                    "active_journal_present",
                    "execution_id",
                    "execution_status",
                    "prior_execution_status",
                    "service_result",
                    "state",
                    "validation_report",
                    "validation_report_sha256"
                ]
                and .state == "canonical_committed"
                and .execution_id == $execution_id
                and (.prior_execution_status == "running"
                    or .prior_execution_status == "failed"
                    or .prior_execution_status == "succeeded")
                and .execution_status == "succeeded"
                and .validation_report == $validation_report
                and .validation_report_sha256 == $validation_sha256
                and .service_result == $service_result
                and .active_journal_present == false
            ' "$promotion_finalization_raw" >/dev/null &&
        [[ ! -e "$ECHOES_PROMOTION_JOURNAL" &&
            ! -L "$ECHOES_PROMOTION_JOURNAL" ]]; then
        FINALIZATION_CLI_JSON="$(jq -c . "$promotion_finalization_raw")"
        mapfile -d '' FINALIZATION_ARCHIVES < <(
            find "$(dirname -- "$ECHOES_OUTPUT_DIRECTORY")" \
                -mindepth 1 -maxdepth 1 -type f \
                -name '.schema-v1.promotion-journal-canonical-committed-*.json' \
                -print0
        )
        MATCHED_FINALIZATION_ARCHIVES=()
        for candidate in "${FINALIZATION_ARCHIVES[@]}"; do
            if [[ ! -L "$candidate" &&
                "$(jq -r '.promotion_id // ""' "$candidate" 2>/dev/null)" == \
                    "$JOURNAL_PROMOTION_ID" &&
                "$(sha256sum "$candidate" | awk '{print $1}')" == \
                    "$JOURNAL_BEFORE_SHA256" ]]; then
                MATCHED_FINALIZATION_ARCHIVES+=("$candidate")
            fi
        done
        if ((${#MATCHED_FINALIZATION_ARCHIVES[@]} == 1)); then
            FINALIZATION_ARCHIVE="${MATCHED_FINALIZATION_ARCHIVES[0]}"
            FINALIZATION_ARCHIVE_SHA256="$JOURNAL_BEFORE_SHA256"
            PROMOTION_FINALIZATION_PASSED=true
        fi
    fi

    JOURNAL_AFTER_FINALIZATION=false
    if [[ -e "$ECHOES_PROMOTION_JOURNAL" || -L "$ECHOES_PROMOTION_JOURNAL" ]]; then
        JOURNAL_AFTER_FINALIZATION=true
    fi
    finalization_tmp="${promotion_finalization_path}.writing-$$"
    jq -n \
        --arg receipt_path "$promotion_finalization_path" \
        --arg finalized_at_utc "$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)" \
        --arg journal_path "$ECHOES_PROMOTION_JOURNAL" \
        --arg journal_before_sha256 "$JOURNAL_BEFORE_SHA256" \
        --arg journal_archive "$FINALIZATION_ARCHIVE" \
        --arg journal_archive_sha256 "$FINALIZATION_ARCHIVE_SHA256" \
        --arg validation_report "$lexical_path" \
        --arg validation_report_sha256 "$LEXICAL_VALIDATION_SHA256" \
        --arg service_result "$SERVICE_RESULT" \
        --arg stderr_log "$promotion_finalization_stderr" \
        --argjson required true \
        --argjson passed "$PROMOTION_FINALIZATION_PASSED" \
        --argjson cli_exit_code "$FINALIZATION_EXIT_CODE" \
        --argjson cli_output_bytes "$FINALIZATION_RAW_SIZE" \
        --argjson journal_after_exists "$JOURNAL_AFTER_FINALIZATION" \
        --argjson cli "$FINALIZATION_CLI_JSON" \
        '{
            schema_version: 1,
            receipt_path: $receipt_path,
            finalized_at_utc: $finalized_at_utc,
            required: $required,
            passed: $passed,
            cli_exit_code: $cli_exit_code,
            cli_output_bytes: $cli_output_bytes,
            journal_path: $journal_path,
            journal_before_sha256: $journal_before_sha256,
            journal_archive: (
                if $journal_archive == "" then null else $journal_archive end
            ),
            journal_archive_sha256: (
                if $journal_archive_sha256 == ""
                then null else $journal_archive_sha256 end
            ),
            journal_after_exists: $journal_after_exists,
            validation_report: $validation_report,
            validation_report_sha256: $validation_report_sha256,
            service_result: $service_result,
            finalization_cli: $cli,
            stderr_log: $stderr_log
        }' >"$finalization_tmp"
    chmod 0600 "$finalization_tmp"
    mv -f -- "$finalization_tmp" "$promotion_finalization_path"
    cp -- "$promotion_finalization_path" \
        "${promotion_finalization_latest}.writing-$$"
    chmod 0600 "${promotion_finalization_latest}.writing-$$"
    mv -f -- \
        "${promotion_finalization_latest}.writing-$$" \
        "$promotion_finalization_latest"
    rm -f -- "$promotion_finalization_raw"
else
    jq -n \
        --arg receipt_path "$promotion_finalization_path" \
        --arg finalized_at_utc "$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)" \
        --arg journal_path "$ECHOES_PROMOTION_JOURNAL" \
        '{
            schema_version: 1,
            receipt_path: $receipt_path,
            finalized_at_utc: $finalized_at_utc,
            required: false,
            passed: true,
            cli_exit_code: null,
            cli_output_bytes: 0,
            journal_path: $journal_path,
            journal_before_sha256: null,
            journal_archive: null,
            journal_archive_sha256: null,
            journal_after_exists: false,
            validation_report: null,
            validation_report_sha256: null,
            service_result: null,
            finalization_cli: null,
            stderr_log: null
        }' >"$promotion_finalization_path"
    chmod 0600 "$promotion_finalization_path"
    cp -- "$promotion_finalization_path" \
        "${promotion_finalization_latest}.writing-$$"
    chmod 0600 "${promotion_finalization_latest}.writing-$$"
    mv -f -- \
        "${promotion_finalization_latest}.writing-$$" \
        "$promotion_finalization_latest"
fi

set +e
/usr/local/bin/uv run \
    --directory "$ECHOES_REPO_ROOT" \
    --frozen \
    --offline \
    --no-sync \
    python - \
        "$ECHOES_OUTPUT_DIRECTORY" \
        "$ECHOES_DATABASE" \
        "$ECHOES_REPO_ROOT" \
        "$ECHOES_EXPECTED_COMMIT" \
        "$ECHOES_DATABASE_REBIND_RECEIPT" \
        "$ECHOES_DATABASE_REBIND_RECEIPT_SHA256" \
        "$ECHOES_DATABASE_REBIND_INTENT" \
        "$ECHOES_DATABASE_REBIND_INTENT_SHA256" \
        "$ECHOES_TRANSFER_DATABASE_SHA256" \
        "$ECHOES_REBOUND_DATABASE_SHA256" \
        "$ECHOES_STATE_ROOT" \
        "$ECHOES_PROMOTION_JOURNAL" \
        "$LATEST_PROMOTION_RECOVERY" \
        "$promotion_finalization_latest" >"$structural_path" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq

root = Path(sys.argv[1]).resolve()
database = Path(sys.argv[2]).resolve()
repository = Path(sys.argv[3]).resolve()
expected_commit = sys.argv[4]
rebind_receipt_argument = Path(sys.argv[5])
rebind_receipt_path = rebind_receipt_argument.resolve()
expected_rebind_receipt_sha256 = sys.argv[6]
rebind_intent_argument = Path(sys.argv[7])
rebind_intent_path = rebind_intent_argument.resolve()
expected_rebind_intent_sha256 = sys.argv[8]
expected_transfer_database_sha256 = sys.argv[9]
expected_rebound_database_sha256 = sys.argv[10]
state_root = Path(sys.argv[11]).resolve()
promotion_journal_argument = Path(sys.argv[12])
promotion_journal_path = promotion_journal_argument.resolve(strict=False)
latest_promotion_recovery_argument = Path(sys.argv[13])
latest_promotion_recovery_path = latest_promotion_recovery_argument.resolve(strict=False)
latest_promotion_finalization_argument = Path(sys.argv[14])
latest_promotion_finalization_path = latest_promotion_finalization_argument.resolve(
    strict=False
)
errors: list[dict[str, Any]] = []
information: dict[str, Any] = {}
if rebind_receipt_argument.is_symlink():
    errors.append(
        {
            "code": "rebind_receipt_symlink",
            "path": str(rebind_receipt_argument),
            "message": "rebind receipt may not be a symlink",
        }
    )
if rebind_intent_argument.is_symlink():
    errors.append(
        {
            "code": "rebind_intent_symlink",
            "path": str(rebind_intent_argument),
            "message": "rebind intent may not be a symlink",
        }
    )

expected_artifacts = (
    "feature_vocabulary",
    "passage_feature_statistics",
    "lexical_index_metadata",
    "directional_rankings",
    "candidate_pairs",
    "candidate_detector_scores",
    "candidate_evidence",
    "shared_evidence",
    "null_replicate_summaries",
    "threshold_calibration",
    "evaluation_results",
    "ablation_results",
    "sensitivity_results",
    "candidate_review_queue",
    "lexical_issues",
    "lexical_metadata",
)
lexical_duckdb_relations = (
    "lexical_feature_vocabulary",
    "lexical_passage_feature_statistics",
    "lexical_index_metadata",
    "lexical_directional_rankings",
    "lexical_candidate_pairs",
    "lexical_candidate_detector_scores",
    "lexical_candidate_evidence",
    "lexical_shared_evidence",
    "lexical_null_replicates",
    "lexical_threshold_calibration",
    "lexical_evaluation_results",
    "lexical_ablation_results",
    "lexical_sensitivity_results",
    "lexical_candidate_review_queue",
    "lexical_issues",
    "lexical_metadata",
)
lexical_convenience_views = (
    "lexical_known_link_recovery",
    "lexical_unrepresented_candidates",
    "lexical_review_eligible_candidates",
    "lexical_formulaic_candidates",
    "lexical_rare_evidence_candidates",
    "lexical_english_derived_candidates",
    "lexical_ablation_failures",
    "lexical_candidate_ablation_results",
    "lexical_directional_english_ablation",
    "lexical_disputed_text_candidates",
    "lexical_reference_gap_candidates",
    "lexical_ketiv_sensitivity",
    "lexical_critical_core_sensitivity",
    "lexical_null_calibration",
    "lexical_detector_comparison",
    "lexical_performance_by_corpus_pair",
    "lexical_performance_by_mapping_status",
)


def fail(code: str, message: str, path: Path | None = None) -> None:
    errors.append(
        {
            "code": code,
            "path": "" if path is None else str(path),
            "message": message,
        }
    )


def sha256_path(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


expected_promotion_journal_path = root.parent / ".schema-v1.promotion-intent.json"
promotion_journal_exists = (
    promotion_journal_argument.exists() or promotion_journal_argument.is_symlink()
)
information["lexical_promotion"] = {
    "journal_path": str(promotion_journal_argument),
    "journal_exists": promotion_journal_exists,
    "journal_sha256": None,
    "latest_recovery_receipt": str(latest_promotion_recovery_argument),
}
if promotion_journal_path != expected_promotion_journal_path:
    fail(
        "promotion_journal_path",
        "installed lexical promotion journal path is not governed",
        promotion_journal_argument,
    )
if promotion_journal_argument.is_symlink():
    fail(
        "promotion_journal_symlink",
        "lexical promotion journal may not be a symlink",
        promotion_journal_argument,
    )
elif promotion_journal_exists:
    try:
        if promotion_journal_argument.stat().st_size > 65_536:
            fail(
                "promotion_journal_size",
                "lexical promotion journal exceeds the 64 KiB validation bound",
                promotion_journal_argument,
            )
        else:
            information["lexical_promotion"]["journal_sha256"] = sha256_path(
                promotion_journal_argument
            )
    except OSError as exc:
        fail("promotion_journal_read", str(exc), promotion_journal_argument)

try:
    if latest_promotion_recovery_argument.is_symlink():
        raise ValueError("latest promotion recovery receipt may not be a symlink")
    if latest_promotion_recovery_argument.stat().st_size > 65_536:
        raise ValueError("latest promotion recovery receipt exceeds 64 KiB")
    latest_promotion_recovery = json.loads(
        latest_promotion_recovery_path.read_text(encoding="utf-8")
    )
    latest_promotion_recovery_sha256 = sha256_path(latest_promotion_recovery_path)
except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
    fail(
        "promotion_recovery_receipt",
        str(exc),
        latest_promotion_recovery_argument,
    )
    latest_promotion_recovery = {}
    latest_promotion_recovery_sha256 = ""

try:
    if latest_promotion_finalization_argument.is_symlink():
        raise ValueError("latest promotion finalization receipt may not be a symlink")
    if latest_promotion_finalization_argument.stat().st_size > 65_536:
        raise ValueError("latest promotion finalization receipt exceeds 64 KiB")
    latest_promotion_finalization = json.loads(
        latest_promotion_finalization_path.read_text(encoding="utf-8")
    )
    latest_promotion_finalization_sha256 = sha256_path(
        latest_promotion_finalization_path
    )
except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
    fail(
        "promotion_finalization_receipt",
        str(exc),
        latest_promotion_finalization_argument,
    )
    latest_promotion_finalization = {}
    latest_promotion_finalization_sha256 = ""

immutable_finalization_value = latest_promotion_finalization.get("receipt_path")
immutable_finalization_path = (
    Path(immutable_finalization_value).resolve(strict=False)
    if isinstance(immutable_finalization_value, str)
    else Path()
)
if (
    latest_promotion_finalization.get("schema_version") != 1
    or latest_promotion_finalization.get("required") not in {True, False}
    or latest_promotion_finalization.get("passed") not in {True, False}
    or latest_promotion_finalization.get("journal_path")
    != str(expected_promotion_journal_path)
    or not isinstance(immutable_finalization_value, str)
    or immutable_finalization_path.parent != state_root
    or not re.fullmatch(
        r"promotion-finalization-[0-9]{8}T[0-9]{6}\.[0-9]{3}Z\.json",
        immutable_finalization_path.name,
    )
    or not immutable_finalization_path.is_file()
    or immutable_finalization_path.is_symlink()
):
    fail(
        "promotion_finalization_identity",
        "promotion finalization receipt has an invalid governed identity",
        latest_promotion_finalization_argument,
    )
else:
    try:
        if sha256_path(immutable_finalization_path) != latest_promotion_finalization_sha256:
            fail(
                "promotion_finalization_immutable_receipt",
                "latest and immutable promotion finalization receipts differ",
                immutable_finalization_path,
            )
    except OSError as exc:
        fail(
            "promotion_finalization_immutable_receipt",
            str(exc),
            immutable_finalization_path,
        )

finalization_required = latest_promotion_finalization.get("required") is True
finalization_passed = latest_promotion_finalization.get("passed") is True
if finalization_required and not finalization_passed:
    fail(
        "promotion_finalization_failed",
        "committed lexical promotion provenance was not sealed",
        latest_promotion_finalization_argument,
    )
if not finalization_required and (
    not finalization_passed
    or latest_promotion_finalization.get("journal_after_exists") is not False
    or latest_promotion_finalization.get("finalization_cli") is not None
):
    fail(
        "promotion_finalization_unexpected",
        "non-recovery validation has an inconsistent finalization receipt",
        latest_promotion_finalization_argument,
    )

finalized_journal_archive_value = latest_promotion_finalization.get("journal_archive")
if finalization_required and finalization_passed:
    finalized_journal_archive = Path(
        str(finalized_journal_archive_value)
    ).resolve(strict=False)
    finalization_validation_report = Path(
        str(latest_promotion_finalization.get("validation_report", ""))
    ).resolve(strict=False)
    finalization_cli = latest_promotion_finalization.get("finalization_cli")
    if (
        latest_promotion_finalization.get("journal_after_exists") is not False
        or finalized_journal_archive.parent != root.parent
        or not re.fullmatch(
            r"\.schema-v1\.promotion-journal-canonical-committed-[0-9a-f]{32}\.json",
            finalized_journal_archive.name,
        )
        or not finalized_journal_archive.is_file()
        or finalized_journal_archive.is_symlink()
        or not finalization_validation_report.is_file()
        or finalization_validation_report.is_symlink()
        or not isinstance(finalization_cli, dict)
        or finalization_cli.get("state") != "canonical_committed"
        or finalization_cli.get("execution_status") != "succeeded"
        or finalization_cli.get("active_journal_present") is not False
        or finalization_cli.get("validation_report")
        != str(finalization_validation_report)
        or finalization_cli.get("validation_report_sha256")
        != latest_promotion_finalization.get("validation_report_sha256")
        or finalization_cli.get("service_result")
        != latest_promotion_finalization.get("service_result")
    ):
        fail(
            "promotion_finalization_witness",
            "promotion finalization did not authenticate sealed provenance",
            latest_promotion_finalization_argument,
        )
    else:
        try:
            if (
                sha256_path(finalized_journal_archive)
                != latest_promotion_finalization.get("journal_archive_sha256")
                or sha256_path(finalization_validation_report)
                != latest_promotion_finalization.get("validation_report_sha256")
            ):
                fail(
                    "promotion_finalization_hash",
                    "promotion finalization input or archive hash changed",
                    latest_promotion_finalization_argument,
                )
        except OSError as exc:
            fail(
                "promotion_finalization_hash",
                str(exc),
                latest_promotion_finalization_argument,
            )

latest_recovery_state = latest_promotion_recovery.get("state")
latest_recovery_after_exists = latest_promotion_recovery.get("journal_after_exists")
if (
    latest_promotion_recovery.get("schema_version") != 1
    or latest_promotion_recovery.get("passed") is not True
    or latest_promotion_recovery.get("journal_path")
    != str(expected_promotion_journal_path)
    or latest_recovery_state
    not in {"no_journal", "staging_restored", "canonical_committed"}
):
    fail(
        "promotion_recovery_identity",
        "latest promotion recovery receipt has an invalid governed identity",
        latest_promotion_recovery_argument,
    )
if latest_recovery_state == "canonical_committed":
    active_committed_witness = (
        latest_recovery_after_exists is True
        and latest_promotion_recovery.get("journal_before_exists") is True
        and promotion_journal_exists
        and latest_promotion_recovery.get("canonical_output_present") is True
        and latest_promotion_recovery.get("journal_before_sha256")
        == information["lexical_promotion"]["journal_sha256"]
    )
    finalized_committed_witness = (
        latest_recovery_after_exists is True
        and latest_promotion_recovery.get("journal_before_exists") is True
        and not promotion_journal_exists
        and finalization_required
        and finalization_passed
        and latest_promotion_recovery.get("journal_before_sha256")
        == latest_promotion_finalization.get("journal_before_sha256")
    )
    archived_committed_witness = (
        latest_recovery_after_exists is False
        and latest_promotion_recovery.get("journal_before_exists") is False
        and not promotion_journal_exists
        and not finalization_required
        and finalization_passed
        and latest_promotion_recovery.get("canonical_output_present") is True
    )
    if not (
        active_committed_witness
        or finalized_committed_witness
        or archived_committed_witness
    ):
        fail(
            "promotion_recovery_committed_witness",
            "canonical-committed recovery does not authenticate active, finalized, or archived state",
            latest_promotion_recovery_argument,
        )
elif latest_recovery_after_exists is not False or promotion_journal_exists:
    fail(
        "promotion_recovery_unresolved",
        "non-committed recovery must leave no active promotion journal",
        promotion_journal_argument,
    )

immutable_recovery_path_value = latest_promotion_recovery.get("receipt_path")
immutable_recovery_path = (
    Path(immutable_recovery_path_value).resolve(strict=False)
    if isinstance(immutable_recovery_path_value, str)
    else Path()
)
if (
    not isinstance(immutable_recovery_path_value, str)
    or immutable_recovery_path.parent != state_root
    or not re.fullmatch(
        r"promotion-recovery-[0-9]{8}T[0-9]{6}\.[0-9]{3}Z\.json",
        immutable_recovery_path.name,
    )
    or not immutable_recovery_path.is_file()
    or immutable_recovery_path.is_symlink()
):
    fail(
        "promotion_recovery_immutable_receipt",
        "immutable promotion recovery receipt is missing or unsafe",
        immutable_recovery_path,
    )
else:
    try:
        if sha256_path(immutable_recovery_path) != latest_promotion_recovery_sha256:
            fail(
                "promotion_recovery_immutable_receipt",
                "latest and immutable promotion recovery receipts differ",
                immutable_recovery_path,
            )
    except OSError as exc:
        fail("promotion_recovery_immutable_receipt", str(exc), immutable_recovery_path)

archived_journal_value = latest_promotion_recovery.get("archived_journal")
archived_journal: Path | None = None
if archived_journal_value is not None:
    archived_journal = Path(str(archived_journal_value)).resolve(strict=False)
    if (
        archived_journal.parent != state_root
        or not re.fullmatch(
            r"\.schema-v1\.promotion-[A-Za-z0-9._-]+\.json",
            archived_journal.name,
        )
        or not archived_journal.is_file()
        or archived_journal.is_symlink()
    ):
        fail(
            "promotion_journal_archive",
            "preserved promotion journal copy is missing or unsafe",
            archived_journal,
        )
    else:
        try:
            archived_hash = sha256_path(archived_journal)
            if archived_hash != latest_promotion_recovery.get("archived_journal_sha256"):
                fail(
                    "promotion_journal_archive",
                    "preserved promotion journal copy changed after recovery",
                    archived_journal,
                )
        except OSError as exc:
            fail("promotion_journal_archive", str(exc), archived_journal)

commit_witness = latest_promotion_recovery.get("commit_witness")
commit_witness_information: dict[str, Any] | None = None
if latest_recovery_state == "canonical_committed":
    if not isinstance(commit_witness, dict):
        fail(
            "promotion_commit_witness",
            "canonical recovery receipt lacks its journal/manifest identity",
            latest_promotion_recovery_argument,
        )
    else:
        witness_kind = commit_witness.get("kind")
        witness_journal_value = commit_witness.get("journal")
        witness_journal_sha256 = commit_witness.get("journal_sha256")
        witness_manifest_value = commit_witness.get("execution_manifest")
        witness_execution_id = commit_witness.get("execution_id")
        witness_status_at_recovery = commit_witness.get(
            "execution_status_at_recovery"
        )
        witness_promotion_id = commit_witness.get("promotion_id")
        witness_manifest = Path(str(witness_manifest_value)).resolve(strict=False)
        witness_journal = Path(str(witness_journal_value)).resolve(strict=False)
        if witness_kind == "active_journal":
            witness_content_path = archived_journal
            witness_path_valid = witness_journal == expected_promotion_journal_path
        elif witness_kind == "archived_journal":
            witness_content_path = witness_journal
            witness_path_valid = (
                witness_journal.parent == root.parent
                and re.fullmatch(
                    r"\.schema-v1\.promotion-journal-(?:canonical-)?committed-[0-9a-f]{32}\.json",
                    witness_journal.name,
                )
                is not None
            )
        else:
            witness_content_path = None
            witness_path_valid = False
        if (
            not witness_path_valid
            or not isinstance(witness_journal_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", witness_journal_sha256)
            or not isinstance(witness_execution_id, str)
            or not re.fullmatch(r"[A-Za-z0-9._-]+", witness_execution_id)
            or witness_status_at_recovery not in {"running", "failed", "succeeded"}
            or not isinstance(witness_promotion_id, str)
            or not re.fullmatch(r"[0-9a-f]{32}", witness_promotion_id)
            or witness_content_path is None
            or not witness_content_path.is_file()
            or witness_content_path.is_symlink()
            or not witness_manifest.is_file()
            or witness_manifest.is_symlink()
            or witness_manifest.parent.parent
            != root.parent / "execution-manifests"
            or witness_manifest.name != f"{witness_execution_id}.json"
        ):
            fail(
                "promotion_commit_witness",
                "canonical recovery journal/manifest witness is unsafe",
                latest_promotion_recovery_argument,
            )
        else:
            try:
                witness_journal_payload = json.loads(
                    witness_content_path.read_text(encoding="utf-8")
                )
                witness_manifest_payload = json.loads(
                    witness_manifest.read_text(encoding="utf-8")
                )
                observed_witness_hash = sha256_path(witness_content_path)
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                fail("promotion_commit_witness", str(exc), witness_content_path)
                witness_journal_payload = {}
                witness_manifest_payload = {}
                observed_witness_hash = ""
            current_witness_status = witness_manifest_payload.get("execution_status")
            status_transition_valid = (
                current_witness_status == witness_status_at_recovery
                or (
                    finalization_required
                    and finalization_passed
                    and current_witness_status == "succeeded"
                    and witness_status_at_recovery in {"running", "succeeded"}
                )
            )
            if (
                observed_witness_hash != witness_journal_sha256
                or witness_journal_payload.get("execution_manifest_path")
                != str(witness_manifest)
                or witness_journal_payload.get("execution_id")
                != witness_execution_id
                or witness_journal_payload.get("promotion_id") != witness_promotion_id
                or witness_manifest_payload.get("execution_id")
                != witness_execution_id
                or not status_transition_valid
                or (
                    witness_kind == "archived_journal"
                    and witness_status_at_recovery != "succeeded"
                )
            ):
                fail(
                    "promotion_commit_witness",
                    "canonical recovery journal/manifest identity changed",
                    witness_content_path,
                )
            commit_witness_information = {
                "kind": witness_kind,
                "journal": str(witness_journal),
                "journal_content_source": str(witness_content_path),
                "journal_sha256": witness_journal_sha256,
                "execution_manifest": str(witness_manifest),
                "execution_id": witness_execution_id,
                "execution_status_at_recovery": witness_status_at_recovery,
                "execution_status_current": current_witness_status,
                "promotion_id": witness_promotion_id,
            }
elif commit_witness is not None:
    fail(
        "promotion_commit_witness",
        "non-committed recovery unexpectedly names a commit witness",
        latest_promotion_recovery_argument,
    )

information["lexical_promotion"].update(
    {
        "latest_recovery_receipt_sha256": latest_promotion_recovery_sha256,
        "latest_recovery_state": latest_recovery_state,
        "latest_recovery_journal_after_exists": latest_recovery_after_exists,
        "immutable_recovery_receipt": (
            str(immutable_recovery_path)
            if isinstance(immutable_recovery_path_value, str)
            else None
        ),
        "archived_journal": archived_journal_value,
        "archived_journal_sha256": latest_promotion_recovery.get(
            "archived_journal_sha256"
        ),
        "latest_finalization_receipt": str(
            latest_promotion_finalization_argument
        ),
        "latest_finalization_receipt_sha256": (
            latest_promotion_finalization_sha256
        ),
        "finalization_required": finalization_required,
        "finalization_passed": finalization_passed,
        "finalized_journal_archive": finalized_journal_archive_value,
        "finalized_journal_archive_sha256": (
            latest_promotion_finalization.get("journal_archive_sha256")
        ),
        "commit_witness": commit_witness_information,
    }
)

promotion_journal_records: list[dict[str, Any]] = []
promotion_journal_keys = {
    "schema_version",
    "output_dir",
    "staging_dir",
    "backup_dir",
    "database_path",
    "execution_manifest_path",
    "execution_id",
    "promotion_id",
    "table_hash_manifest_sha256",
}
for journal_parent, location in (
    (root.parent, "lexical_output_parent"),
    (state_root, "cloud_state_archive"),
):
    try:
        journal_candidates = sorted(
            (
                candidate
                for candidate in journal_parent.iterdir()
                if re.fullmatch(
                    r"\.schema-v1\.promotion-[A-Za-z0-9._-]+\.json",
                    candidate.name,
                )
            ),
            key=lambda candidate: candidate.name,
        )
    except OSError as exc:
        fail("promotion_journal_inventory", str(exc), journal_parent)
        journal_candidates = []
    for candidate in journal_candidates:
        record: dict[str, Any] = {
            "path": str(candidate),
            "location": location,
            "active": candidate == promotion_journal_argument,
        }
        if candidate.is_symlink() or not candidate.is_file():
            fail(
                "promotion_journal_inventory",
                "promotion journal inventory contains an unsafe path",
                candidate,
            )
            promotion_journal_records.append(record)
            continue
        try:
            journal_size = candidate.stat().st_size
            if journal_size > 65_536:
                raise ValueError("promotion journal exceeds 64 KiB")
            journal_payload = json.loads(candidate.read_text(encoding="utf-8"))
            journal_hash = sha256_path(candidate)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            fail("promotion_journal_inventory", str(exc), candidate)
            promotion_journal_records.append(record)
            continue
        if (
            not isinstance(journal_payload, dict)
            or set(journal_payload) != promotion_journal_keys
            or journal_payload.get("schema_version") != 1
            or journal_payload.get("output_dir") != str(root)
            or journal_payload.get("database_path") != str(database)
            or not isinstance(journal_payload.get("execution_manifest_path"), str)
            or not re.fullmatch(
                r"[A-Za-z0-9._-]+",
                str(journal_payload.get("execution_id", "")),
            )
            or Path(str(journal_payload.get("execution_manifest_path"))).parent.parent
            != root.parent / "execution-manifests"
            or not re.fullmatch(
                r"[A-Za-z0-9._-]+",
                Path(str(journal_payload.get("execution_manifest_path"))).parent.name,
            )
            or Path(str(journal_payload.get("execution_manifest_path"))).name
            != f"{journal_payload.get('execution_id')}.json"
            or not re.fullmatch(
                r"[0-9a-f]{32}",
                str(journal_payload.get("promotion_id", "")),
            )
            or not isinstance(journal_payload.get("staging_dir"), str)
            or Path(str(journal_payload.get("staging_dir"))).parent != root.parent
            or not Path(str(journal_payload.get("staging_dir"))).name.startswith(
                ".schema-v1.writing-"
            )
            or not isinstance(journal_payload.get("backup_dir"), str)
            or Path(str(journal_payload.get("backup_dir"))).parent != root.parent
            or not Path(str(journal_payload.get("backup_dir"))).name.startswith(
                ".schema-v1.backup-"
            )
            or not re.fullmatch(
                r"[0-9a-f]{64}",
                str(journal_payload.get("table_hash_manifest_sha256", "")),
            )
        ):
            fail(
                "promotion_journal_inventory",
                "promotion journal archive has an invalid governed schema",
                candidate,
            )
        record.update(
            {
                "size_bytes": journal_size,
                "sha256": journal_hash,
                "output_dir": journal_payload.get("output_dir"),
                "staging_dir": journal_payload.get("staging_dir"),
                "backup_dir": journal_payload.get("backup_dir"),
                "database_path": journal_payload.get("database_path"),
                "execution_manifest_path": journal_payload.get(
                    "execution_manifest_path"
                ),
                "execution_id": journal_payload.get("execution_id"),
                "promotion_id": journal_payload.get("promotion_id"),
                "table_hash_manifest_sha256": journal_payload.get(
                    "table_hash_manifest_sha256"
                ),
            }
        )
        promotion_journal_records.append(record)
information["lexical_promotion"]["journals"] = promotion_journal_records


passage_root = repository / "data/processed/passages/schema-v1"
passage_artifacts = (
    "passages",
    "passage_membership",
    "passage_adjacency",
    "segmentation_exclusions",
    "segmentation_issues",
    "segmentation_metadata",
)
try:
    rebind_receipt_raw = rebind_receipt_path.read_text(encoding="utf-8")
    rebind_receipt = json.loads(rebind_receipt_raw)
except (OSError, UnicodeError, json.JSONDecodeError) as exc:
    fail("rebind_receipt_unreadable", str(exc), rebind_receipt_path)
    rebind_receipt = {}
try:
    observed_rebind_receipt_sha256 = sha256_path(rebind_receipt_path)
except OSError as exc:
    fail("rebind_receipt_hash", str(exc), rebind_receipt_path)
    observed_rebind_receipt_sha256 = ""
if observed_rebind_receipt_sha256 != expected_rebind_receipt_sha256:
    fail(
        "rebind_receipt_hash",
        "governed passage-view-rebind receipt changed after launch",
        rebind_receipt_path,
    )
try:
    rebind_intent = json.loads(rebind_intent_path.read_text(encoding="utf-8"))
except (OSError, UnicodeError, json.JSONDecodeError) as exc:
    fail("rebind_intent_unreadable", str(exc), rebind_intent_path)
    rebind_intent = {}
try:
    observed_rebind_intent_sha256 = sha256_path(rebind_intent_path)
except OSError as exc:
    fail("rebind_intent_hash", str(exc), rebind_intent_path)
    observed_rebind_intent_sha256 = ""
if rebind_intent_path != Path(f"{rebind_receipt_path}.intent.json"):
    fail("rebind_intent_path", "rebind intent is not adjacent to its receipt")
if observed_rebind_intent_sha256 != expected_rebind_intent_sha256:
    fail("rebind_intent_hash", "governed rebind intent changed after launch")
if (
    rebind_intent.get("schema_version") != 1
    or rebind_intent.get("database_path") != str(database)
    or rebind_intent.get("passage_root") != str(passage_root.resolve())
    or rebind_intent.get("before_database_sha256")
    != expected_transfer_database_sha256
    or rebind_intent.get("duckdb_version") != duckdb.__version__
):
    fail("rebind_intent_identity", "governed rebind intent identity differs")
if rebind_receipt.get("schema_version") != 1:
    fail("rebind_receipt_schema", "rebind receipt schema_version must be 1")
if rebind_receipt.get("database_path") != str(database):
    fail("rebind_database_path", "rebind receipt database path differs")
if rebind_receipt.get("passage_root") != str(passage_root.resolve()):
    fail("rebind_passage_root", "rebind receipt passage root differs")
if (
    rebind_receipt.get("before_database_sha256")
    != expected_transfer_database_sha256
):
    fail("rebind_before_hash", "rebind receipt transfer hash differs")
if rebind_receipt.get("after_database_sha256") != expected_rebound_database_sha256:
    fail("rebind_after_hash", "rebind receipt prelaunch hash differs")
if rebind_receipt.get("duckdb_version") != duckdb.__version__:
    fail("rebind_duckdb_version", "rebind receipt DuckDB version differs")
view_globs = rebind_receipt.get("view_globs")
tiny_read_has_rows = rebind_receipt.get("tiny_read_has_rows")
if rebind_intent.get("view_globs") != view_globs:
    fail("rebind_intent_globs", "rebind intent globs differ from the receipt")
if not isinstance(view_globs, dict) or set(view_globs) != set(passage_artifacts):
    fail("rebind_view_globs", "rebind receipt must contain exactly six passage globs")
if (
    not isinstance(tiny_read_has_rows, dict)
    or set(tiny_read_has_rows) != set(passage_artifacts)
    or any(not isinstance(value, bool) for value in tiny_read_has_rows.values())
):
    fail("rebind_tiny_reads", "rebind receipt must contain six boolean tiny-read results")

launch_path = state_root / "latest-launch.json"
try:
    launch = json.loads(launch_path.read_text(encoding="utf-8"))
except (OSError, UnicodeError, json.JSONDecodeError) as exc:
    fail("launch_metadata", str(exc), launch_path)
    launch = {}
launch_expectations = {
    "commit": expected_commit,
    "database": str(database),
    "passage_root": str(passage_root.resolve()),
    "database_rebind_receipt": str(rebind_receipt_path),
    "database_rebind_receipt_sha256": expected_rebind_receipt_sha256,
    "database_rebind_intent": str(rebind_intent_path),
    "database_rebind_intent_sha256": expected_rebind_intent_sha256,
    "transfer_database_sha256": expected_transfer_database_sha256,
    "rebound_database_sha256": expected_rebound_database_sha256,
    "prelaunch_database_sha256": expected_rebound_database_sha256,
    "lexical_promotion_journal": str(expected_promotion_journal_path),
}
for field, expected in launch_expectations.items():
    if launch.get(field) != expected:
        fail(
            "launch_rebind_chain",
            f"launch field {field!r} differs from the authenticated rebind chain",
            launch_path,
        )
prelaunch_recovery_value = launch.get("promotion_recovery_receipt")
prelaunch_recovery_path = (
    Path(prelaunch_recovery_value).resolve(strict=False)
    if isinstance(prelaunch_recovery_value, str)
    else Path()
)
prelaunch_recovery_expected_hash = launch.get("promotion_recovery_receipt_sha256")
prelaunch_recovery_state = launch.get("promotion_recovery_state")
if (
    not isinstance(prelaunch_recovery_value, str)
    or prelaunch_recovery_path.parent != state_root
    or not re.fullmatch(
        r"promotion-recovery-[0-9]{8}T[0-9]{6}\.[0-9]{3}Z\.json",
        prelaunch_recovery_path.name,
    )
    or not isinstance(prelaunch_recovery_expected_hash, str)
    or not re.fullmatch(r"[0-9a-f]{64}", prelaunch_recovery_expected_hash)
    or prelaunch_recovery_state not in {"no_journal", "staging_restored"}
    or not prelaunch_recovery_path.is_file()
    or prelaunch_recovery_path.is_symlink()
):
    fail(
        "launch_promotion_recovery",
        "launch does not identify a safe worker-authorizing promotion recovery receipt",
        launch_path,
    )
else:
    try:
        prelaunch_recovery_payload = json.loads(
            prelaunch_recovery_path.read_text(encoding="utf-8")
        )
        prelaunch_recovery_hash = sha256_path(prelaunch_recovery_path)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail("launch_promotion_recovery", str(exc), prelaunch_recovery_path)
        prelaunch_recovery_payload = {}
        prelaunch_recovery_hash = ""
    if (
        prelaunch_recovery_hash != prelaunch_recovery_expected_hash
        or prelaunch_recovery_payload.get("passed") is not True
        or prelaunch_recovery_payload.get("state") != prelaunch_recovery_state
        or prelaunch_recovery_payload.get("journal_path")
        != str(expected_promotion_journal_path)
        or prelaunch_recovery_payload.get("journal_after_exists") is not False
    ):
        fail(
            "launch_promotion_recovery",
            "launch promotion recovery receipt changed or did not authorize a worker",
            prelaunch_recovery_path,
        )
transfer_hashes: dict[str, str] = {}
try:
    transfer_manifest_path = Path(str(launch["transfer_manifest"])).resolve()
    transfer_payload = json.loads(transfer_manifest_path.read_text(encoding="utf-8"))
    transfer_entries = transfer_payload.get("files", transfer_payload.get("entries", []))
    transfer_hashes = {
        str(entry.get("path", entry.get("relative_path"))): str(entry.get("sha256"))
        for entry in transfer_entries
        if isinstance(entry, dict)
        and entry.get("transfer", entry.get("required", True)) is True
    }
    staging_relative = (
        Path(str(launch["resume_staging_directory"]))
        .resolve()
        .relative_to(repository)
        .as_posix()
    )
except (KeyError, OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
    fail("transfer_lineage", str(exc), launch_path)
    transfer_manifest_path = repository / "cloud/transfer-manifest.json"
    staging_relative = ""


prerequisites = (
    database,
    rebind_receipt_path,
    rebind_intent_path,
    launch_path,
    latest_promotion_recovery_path,
    latest_promotion_finalization_path,
    prelaunch_recovery_path,
    transfer_manifest_path,
    repository / "uv.lock",
    repository / "config/lexical.yaml",
    repository / "config/experiments/m7-lexical-baseline.yaml",
    repository / "data/manifests/sources.yaml",
    repository / "data/processed/passages/schema-v1/table-hashes.json",
    repository / "data/processed/benchmarks/schema-v1/table-hashes.json",
    repository / "outputs/reports/m7-spot-check-config.json",
    repository / "scripts/generate_m7_report.py",
)
for prerequisite in prerequisites:
    if not prerequisite.is_file() or prerequisite.is_symlink():
        fail("missing_prerequisite", "required benchmark/report prerequisite is absent", prerequisite)

manifest_path = root / "table-hashes.json"
actual_table_hash_manifest_sha256 = ""
try:
    if manifest_path.is_symlink():
        raise ValueError("table-hashes.json may not be a symlink")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("table-hashes.json root must be an object")
    actual_table_hash_manifest_sha256 = sha256_path(manifest_path)
except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
    fail("hash_manifest", str(exc), manifest_path)
    manifest = {}

if manifest.get("schema_version") != 1:
    fail("hash_manifest_schema", "table-hashes schema_version must be 1", manifest_path)
file_hashes = manifest.get("file_sha256")
table_counts = manifest.get("table_counts")
artifacts = manifest.get("artifacts")
table_logical_hashes = manifest.get("table_logical_sha256")
table_physical_hashes = manifest.get("table_physical_sha256")
if not isinstance(file_hashes, dict):
    fail("hash_manifest_files", "file_sha256 must be an object", manifest_path)
    file_hashes = {}
if not isinstance(table_counts, dict):
    fail("hash_manifest_counts", "table_counts must be an object", manifest_path)
    table_counts = {}
if not isinstance(artifacts, dict):
    fail("hash_manifest_artifacts", "artifacts must be an object", manifest_path)
    artifacts = {}
if not isinstance(table_logical_hashes, dict):
    fail(
        "hash_manifest_logical",
        "table_logical_sha256 must be an object",
        manifest_path,
    )
    table_logical_hashes = {}
if not isinstance(table_physical_hashes, dict):
    fail(
        "hash_manifest_physical",
        "table_physical_sha256 must be an object",
        manifest_path,
    )
    table_physical_hashes = {}

actual_files: set[str] = set()
for current_root, directory_names, file_names in os.walk(root, followlinks=False):
    current = Path(current_root)
    for directory_name in list(directory_names):
        directory = current / directory_name
        if directory.is_symlink():
            fail("symlink", "canonical output contains a symlink", directory)
            directory_names.remove(directory_name)
    for file_name in file_names:
        file_path = current / file_name
        if file_path.is_symlink():
            fail("symlink", "canonical output contains a symlink", file_path)
            continue
        relative = file_path.relative_to(root).as_posix()
        if relative != "table-hashes.json":
            actual_files.add(relative)

declared_files = {str(path) for path in file_hashes}
for relative in sorted(declared_files - actual_files):
    fail("missing_declared_file", "hash manifest names a missing file", root / relative)
for relative in sorted(actual_files - declared_files):
    fail("undeclared_file", "canonical output contains an undeclared file", root / relative)

observed_table_rows: dict[str, int] = {}
part_counts: dict[str, int] = {}
for artifact in expected_artifacts:
    directory = root / artifact
    if not directory.is_dir() or directory.is_symlink():
        fail("artifact_directory", "expected artifact directory is missing or unsafe", directory)
        continue
    names = sorted(path.name for path in directory.iterdir() if path.is_file())
    part_names = [name for name in names if re.fullmatch(r"part-[0-9]{5}\.parquet", name)]
    unexpected = [name for name in names if name not in part_names]
    if unexpected:
        fail("unexpected_artifact_file", f"unexpected files: {unexpected[:10]}", directory)
    if not part_names:
        fail("missing_parts", "artifact has no Parquet part", directory)
        continue
    expected_names = [f"part-{index:05d}.parquet" for index in range(len(part_names))]
    if part_names != expected_names:
        fail(
            "noncontiguous_parts",
            f"expected={expected_names[:5]}... observed={part_names[:5]}...",
            directory,
        )
    part_counts[artifact] = len(part_names)
    row_count = 0
    schemas: set[str] = set()
    for name in part_names:
        path = directory / name
        try:
            parquet = pq.ParquetFile(path)
            row_count += parquet.metadata.num_rows
            schemas.add(str(parquet.schema_arrow))
        except (OSError, ValueError) as exc:
            fail("parquet_unreadable", str(exc), path)
    if len(schemas) > 1:
        fail("parquet_schema_drift", "parts in one artifact have different schemas", directory)
    observed_table_rows[artifact] = row_count
    declared_count = table_counts.get(artifact)
    if declared_count != row_count:
        fail(
            "row_count_mismatch",
            f"declared={declared_count!r}, observed={row_count}",
            directory,
        )
    declared_artifact = artifacts.get(artifact)
    if not isinstance(declared_artifact, dict):
        fail("artifact_manifest", "artifact leaf map is missing", directory)
    elif set(declared_artifact) != {
        f"{artifact}/{name}" for name in part_names
    }:
        fail("artifact_leaf_mismatch", "artifact leaf map differs from its parts", directory)

indexes = root / "indexes"
if not indexes.is_dir() or indexes.is_symlink():
    fail("indexes_missing", "governed sparse-index directory is missing", indexes)
elif not any(path.is_file() for path in indexes.rglob("*")):
    fail("indexes_empty", "governed sparse-index directory is empty", indexes)

verified_bytes = 0
for relative, expected_digest in sorted(file_hashes.items()):
    if not isinstance(relative, str) or not isinstance(expected_digest, str):
        fail("hash_entry", "file_sha256 entries must map strings to strings", manifest_path)
        continue
    path = root / relative
    if not path.is_file() or path.is_symlink():
        continue
    hasher = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                hasher.update(block)
    except OSError as exc:
        fail("hash_read", str(exc), path)
        continue
    observed_digest = hasher.hexdigest()
    if observed_digest != expected_digest:
        fail(
            "hash_mismatch",
            f"expected={expected_digest}, observed={observed_digest}",
            path,
        )
    verified_bytes += path.stat().st_size

successful_manifests: list[dict[str, Any]] = []
manifest_root = root.parent / "execution-manifests"
if manifest_root.is_dir() and not manifest_root.is_symlink():
    for path in sorted(manifest_root.glob("*/*.json")):
        try:
            candidate = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            fail("execution_manifest_unreadable", str(exc), path)
            continue
        if candidate.get("execution_status") == "succeeded":
            successful_manifests.append(candidate)
else:
    fail("execution_manifests_missing", "execution-manifest root is missing", manifest_root)
if len(successful_manifests) != 1:
    fail(
        "successful_execution_count",
        f"expected exactly one successful recovered execution, observed {len(successful_manifests)}",
        manifest_root,
    )
elif successful_manifests:
    execution = successful_manifests[0]
    if execution.get("git_commit") != expected_commit:
        fail("execution_commit", "successful execution commit differs", manifest_root)
    resume = execution.get("resume_lineage")
    if not isinstance(resume, dict) or resume.get("status") != "validated_and_reused":
        fail("resume_lineage", "successful first run did not authenticate reused staging", manifest_root)
    else:
        for field, code in (
            ("validated_artifact_part_hashes", "resume_artifact_hashes"),
            ("validated_checkpoint_manifest_hashes", "resume_checkpoint_manifests"),
            ("validated_checkpoint_part_hashes", "resume_checkpoint_parts"),
        ):
            validated = resume.get(field)
            if not isinstance(validated, dict) or not validated:
                fail(code, f"resume lineage has no {field}", manifest_root)
                continue
            for relative, digest in validated.items():
                transfer_relative = f"{staging_relative}/{relative}"
                if transfer_hashes.get(transfer_relative) != digest:
                    fail(
                        code,
                        f"reused lineage hash differs from transfer entry: {relative}",
                        transfer_manifest_path,
                    )

if duckdb.__version__ != "1.5.4":
    fail("duckdb_version", f"expected 1.5.4, observed {duckdb.__version__}", database)
elif database.is_file():
    try:
        with duckdb.connect(str(database), read_only=True) as connection:
            database_version = connection.execute("SELECT version()").fetchone()[0]
            lexical_relation_count = connection.execute(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema='main' AND table_name LIKE 'lexical_%'"
            ).fetchone()[0]
            passage_definitions = {
                str(name): str(sql)
                for name, sql in connection.execute(
                    "SELECT view_name, sql FROM duckdb_views() "
                    "WHERE database_name=current_database() AND schema_name='main' "
                    "AND view_name IN "
                    "('passages','passage_membership','passage_adjacency',"
                    "'segmentation_exclusions','segmentation_issues',"
                    "'segmentation_metadata') ORDER BY view_name"
                ).fetchall()
            }
            observed_tiny_reads = {
                name: bool(
                    connection.execute(
                        f'SELECT EXISTS(SELECT 1 FROM "{name}" LIMIT 1)'
                    ).fetchone()[0]
                )
                for name in passage_artifacts
                if name in passage_definitions
            }
            promotion_marker_rows = connection.execute(
                "SELECT promotion_id, table_hash_manifest_sha256, catalog_sha256 "
                "FROM lexical_promotion_commit"
            ).fetchall()
            expected_lexical_catalog_names = set(lexical_duckdb_relations) | set(
                lexical_convenience_views
            )
            lexical_catalog_definitions = {
                str(name): str(sql)
                for name, sql in connection.execute(
                    "SELECT view_name, sql FROM duckdb_views() "
                    "WHERE database_name=current_database() AND schema_name='main'"
                ).fetchall()
                if str(name) in expected_lexical_catalog_names
            }
            observed_lexical_catalog_sha256 = hashlib.sha256(
                json.dumps(
                    lexical_catalog_definitions,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        information["database_engine_version"] = database_version
        information["lexical_relation_count"] = lexical_relation_count
        if lexical_relation_count < len(expected_artifacts):
            fail(
                "database_lexical_relations",
                f"too few lexical relations: {lexical_relation_count}",
                database,
            )
        expected_passage_prefix = passage_root.resolve().as_posix()
        if set(passage_definitions) != set(passage_artifacts):
            fail(
                "database_passage_views",
                "database does not expose exactly the six governed passage views",
                database,
            )
        elif any(
            expected_passage_prefix not in sql
            for sql in passage_definitions.values()
        ):
            fail(
                "database_passage_paths",
                "one or more passage views no longer use the Linux passage root",
                database,
            )
        if observed_tiny_reads != tiny_read_has_rows:
            fail(
                "database_passage_tiny_reads",
                "post-run passage tiny reads differ from the governed rebind receipt",
                database,
            )
        if len(promotion_marker_rows) != 1:
            fail(
                "database_promotion_marker",
                f"expected exactly one lexical promotion marker, observed {len(promotion_marker_rows)}",
                database,
            )
        else:
            marker_promotion_id, marker_manifest_sha256, marker_catalog_sha256 = (
                str(value) for value in promotion_marker_rows[0]
            )
            if actual_table_hash_manifest_sha256 != marker_manifest_sha256:
                fail(
                    "database_promotion_hash_manifest",
                    "canonical table-hashes.json bytes differ from the DuckDB promotion marker",
                    manifest_path,
                )
            if set(lexical_catalog_definitions) != expected_lexical_catalog_names:
                fail(
                    "database_lexical_catalog",
                    "DuckDB lexical artifact/convenience view catalog is incomplete",
                    database,
                )
            if observed_lexical_catalog_sha256 != marker_catalog_sha256:
                fail(
                    "database_lexical_catalog_hash",
                    "DuckDB lexical catalog changed after the promotion transaction",
                    database,
                )
            current_journal_records = [
                record
                for record in promotion_journal_records
                if record.get("location") == "lexical_output_parent"
                and record.get("promotion_id") == marker_promotion_id
                and record.get("table_hash_manifest_sha256")
                == marker_manifest_sha256
                and re.fullmatch(
                    r"\.schema-v1\.promotion-journal-(?:canonical-)?committed-[0-9a-f]{32}\.json",
                    Path(str(record.get("path", ""))).name,
                )
            ]
            if len(current_journal_records) != 1:
                fail(
                    "database_promotion_journal",
                    "DuckDB marker does not identify exactly one preserved committed journal",
                    database,
                )
            else:
                current_journal = current_journal_records[0]
                current_manifest_path = Path(
                    str(current_journal.get("execution_manifest_path", ""))
                )
                try:
                    current_manifest = json.loads(
                        current_manifest_path.read_text(encoding="utf-8")
                    )
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    fail(
                        "database_promotion_manifest",
                        str(exc),
                        current_manifest_path,
                    )
                    current_manifest = {}
                if (
                    current_manifest_path.is_symlink()
                    or current_manifest.get("execution_id")
                    != current_journal.get("execution_id")
                    or current_manifest.get("execution_status") != "succeeded"
                ):
                    fail(
                        "database_promotion_manifest",
                        "current promotion journal does not identify succeeded execution provenance",
                        current_manifest_path,
                    )
                manifest_hash_witnesses = {
                    "canonical_table_hashes": actual_table_hash_manifest_sha256,
                    "duckdb_marker": marker_manifest_sha256,
                    "committed_journal": current_journal.get(
                        "table_hash_manifest_sha256"
                    ),
                    "execution_manifest": current_manifest.get(
                        "output_hash_manifest_sha256"
                    ),
                }
                if (
                    not actual_table_hash_manifest_sha256
                    or any(
                        value != actual_table_hash_manifest_sha256
                        for value in manifest_hash_witnesses.values()
                    )
                ):
                    fail(
                        "database_promotion_hash_witness",
                        "canonical table-hashes.json, DuckDB marker, committed journal, "
                        "and execution manifest do not share one exact SHA-256",
                        current_manifest_path,
                    )
                if current_manifest.get("output_table_hashes") != table_logical_hashes:
                    fail(
                        "database_promotion_logical_hashes",
                        "succeeded execution manifest disagrees with canonical "
                        "table_logical_sha256",
                        current_manifest_path,
                    )
                if (
                    current_manifest.get("output_table_physical_hashes")
                    != table_physical_hashes
                ):
                    fail(
                        "database_promotion_physical_hashes",
                        "succeeded execution manifest disagrees with canonical "
                        "table_physical_sha256",
                        current_manifest_path,
                    )
                information["lexical_promotion"]["current_commit"] = {
                    "journal": current_journal.get("path"),
                    "journal_sha256": current_journal.get("sha256"),
                    "promotion_id": marker_promotion_id,
                    "table_hash_manifest_sha256": marker_manifest_sha256,
                    "observed_table_hash_manifest_sha256": (
                        actual_table_hash_manifest_sha256
                    ),
                    "table_hash_manifest_witnesses": manifest_hash_witnesses,
                    "catalog_sha256": marker_catalog_sha256,
                    "observed_catalog_sha256": observed_lexical_catalog_sha256,
                    "execution_manifest": str(current_manifest_path),
                    "execution_id": current_journal.get("execution_id"),
                    "execution_status": current_manifest.get("execution_status"),
                }
    except duckdb.Error as exc:
        fail("database_read", str(exc), database)

try:
    current_database_sha256 = sha256_path(database)
except OSError as exc:
    fail("database_hash", str(exc), database)
    current_database_sha256 = ""
information["current_database_sha256"] = current_database_sha256
information["prelaunch_rebound_database_sha256"] = expected_rebound_database_sha256
information["database_changed_after_prelaunch"] = (
    bool(current_database_sha256)
    and current_database_sha256 != expected_rebound_database_sha256
)

information.update(
    {
        "verified_file_count": len(file_hashes),
        "verified_bytes": verified_bytes,
        "part_counts": part_counts,
        "table_rows": observed_table_rows,
        "successful_execution_manifest_count": len(successful_manifests),
    }
)
report = {
    "schema_version": 1,
    "passed": not errors,
    "canonical_output": str(root),
    "information": information,
    "errors": errors,
}
print(json.dumps(report, indent=2, sort_keys=True))
raise SystemExit(0 if not errors else 1)
PY
STRUCTURAL_STATUS=$?
set -e

normalize_json_result "$structural_path" "structural validation" "$STRUCTURAL_STATUS"

STRUCTURAL_PASSED=false
LEXICAL_PASSED=false
if ((STRUCTURAL_STATUS == 0)) &&
    [[ "$(jq -r '.passed // false' "$structural_path" 2>/dev/null)" == "true" ]]; then
    STRUCTURAL_PASSED=true
fi
if ((LEXICAL_STATUS == 0)) &&
    [[ "$(jq -r '.passed // false' "$lexical_path" 2>/dev/null)" == "true" ]]; then
    LEXICAL_PASSED=true
fi
FINAL_SERVICE_ACTIVE="$(
    systemctl show echoes-m7.service --property=ActiveState --value
)"
FINAL_SERVICE_RESULT="$(
    systemctl show echoes-m7.service --property=Result --value
)"
if [[ "$FINAL_SERVICE_ACTIVE" != "inactive" ||
    "$FINAL_SERVICE_RESULT" != "success" ||
    "$FINAL_SERVICE_RESULT" != "$SERVICE_RESULT" ]]; then
    SERVICE_RESULT_PASSED=false
fi
OVERALL_PASSED=false
if [[ "$STRUCTURAL_PASSED" == "true" &&
    "$LEXICAL_PASSED" == "true" &&
    "$PROMOTION_FINALIZATION_PASSED" == "true" &&
    "$SERVICE_RESULT_PASSED" == "true" ]]; then
    OVERALL_PASSED=true
fi

receipt_tmp="${receipt_path}.writing-$$"
jq -n \
    --arg validated_at_utc "$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)" \
    --arg canonical_output "$ECHOES_OUTPUT_DIRECTORY" \
    --arg database "$ECHOES_DATABASE" \
    --arg commit "$ECHOES_EXPECTED_COMMIT" \
    --arg database_rebind_receipt "$ECHOES_DATABASE_REBIND_RECEIPT" \
    --arg database_rebind_receipt_sha256 "$ECHOES_DATABASE_REBIND_RECEIPT_SHA256" \
    --arg database_rebind_intent "$ECHOES_DATABASE_REBIND_INTENT" \
    --arg database_rebind_intent_sha256 "$ECHOES_DATABASE_REBIND_INTENT_SHA256" \
    --arg transfer_database_sha256 "$ECHOES_TRANSFER_DATABASE_SHA256" \
    --arg prelaunch_rebound_database_sha256 "$ECHOES_REBOUND_DATABASE_SHA256" \
    --arg current_database_sha256 "$(
        jq -r '.information.current_database_sha256 // ""' "$structural_path"
    )" \
    --argjson passed "$OVERALL_PASSED" \
    --argjson recovery_confirmed_canonical "$RECOVERY_CONFIRMED_CANONICAL" \
    --arg service_result "$SERVICE_RESULT" \
    --arg final_service_active "$FINAL_SERVICE_ACTIVE" \
    --arg final_service_result "$FINAL_SERVICE_RESULT" \
    --argjson service_result_passed "$SERVICE_RESULT_PASSED" \
    --argjson promotion_finalization_required "$PROMOTION_FINALIZATION_REQUIRED" \
    --argjson promotion_finalization_passed "$PROMOTION_FINALIZATION_PASSED" \
    --argjson structural_status "$STRUCTURAL_STATUS" \
    --argjson lexical_status "$LEXICAL_STATUS" \
    --slurpfile structural "$structural_path" \
    --slurpfile lexical "$lexical_path" \
    --slurpfile promotion_finalization "$promotion_finalization_path" \
    --rawfile lexical_stderr "$lexical_stderr" \
    '{
        schema_version: 1,
        passed: $passed,
        validated_at_utc: $validated_at_utc,
        canonical_output: $canonical_output,
        database: $database,
        commit: $commit,
        database_rebind_receipt: $database_rebind_receipt,
        database_rebind_receipt_sha256: $database_rebind_receipt_sha256,
        database_rebind_intent: $database_rebind_intent,
        database_rebind_intent_sha256: $database_rebind_intent_sha256,
        transfer_database_sha256: $transfer_database_sha256,
        prelaunch_rebound_database_sha256: $prelaunch_rebound_database_sha256,
        current_database_sha256: $current_database_sha256,
        service_completion: {
            systemd_result: $service_result,
            systemd_result_passed: $service_result_passed,
            final_active_state: $final_service_active,
            final_systemd_result: $final_service_result,
            recovery_confirmed_canonical: $recovery_confirmed_canonical,
            promotion_finalization_required: $promotion_finalization_required,
            promotion_finalization_passed: $promotion_finalization_passed
        },
        lexical_promotion: (
            $structural[0].information.lexical_promotion // null
        ),
        promotion_finalization: ($promotion_finalization[0] // null),
        structural_exit_code: $structural_status,
        lexical_exit_code: $lexical_status,
        structural: ($structural[0] // null),
        lexical: ($lexical[0] // null),
        lexical_stderr: $lexical_stderr
    }' >"$receipt_tmp"
mv -f -- "$receipt_tmp" "$receipt_path"
cp -- "$receipt_path" "$ECHOES_STATE_ROOT/latest-validation.json.writing-$$"
mv -f -- \
    "$ECHOES_STATE_ROOT/latest-validation.json.writing-$$" \
    "$ECHOES_STATE_ROOT/latest-validation.json"

if [[ "$OVERALL_PASSED" != "true" ]]; then
    printf 'Milestone 7 cloud validation failed; receipt: %s\n' "$receipt_path" >&2
    exit 1
fi
printf 'Milestone 7 cloud validation passed: %s\n' "$receipt_path"
