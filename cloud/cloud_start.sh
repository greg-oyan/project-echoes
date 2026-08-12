#!/usr/bin/env bash
set -Eeuo pipefail

SERVICE_NAME="echoes-m7.service"
ENV_FILE="/etc/project-echoes/m7.env"
MINIMUM_FREE_BYTES=$((120 * 1024 * 1024 * 1024))

if [[ $EUID -ne 0 ]]; then
    printf 'cloud_start.sh must run as root (use sudo).\n' >&2
    exit 1
fi
if [[ ! -r "$ENV_FILE" ]]; then
    printf 'Service environment is missing; run install_echoes_service.sh first.\n' >&2
    exit 1
fi
# shellcheck disable=SC1090
source "$ENV_FILE"

for name in ECHOES_REPO_ROOT ECHOES_EXPECTED_BRANCH ECHOES_EXPECTED_COMMIT \
    ECHOES_M7_CLOUD_EXECUTION ECHOES_MAXIMUM_MEMORY_BYTES \
    ECHOES_DUCKDB_MEMORY_LIMIT_BYTES ECHOES_MINIMUM_FREE_DISK_BYTES \
    ECHOES_THREAD_COUNT \
    ECHOES_DUCKDB_TEMP_DIRECTORY TMPDIR \
    ECHOES_TRANSFER_MANIFEST ECHOES_TRANSFER_MANIFEST_SHA256 ECHOES_DATABASE \
    ECHOES_PASSAGE_ROOT ECHOES_DATABASE_REBIND_RECEIPT \
    ECHOES_DATABASE_REBIND_RECEIPT_SHA256 ECHOES_DATABASE_REBIND_INTENT \
    ECHOES_DATABASE_REBIND_INTENT_SHA256 ECHOES_TRANSFER_DATABASE_SHA256 \
    ECHOES_REBOUND_DATABASE_SHA256 ECHOES_OUTPUT_DIRECTORY \
    ECHOES_RESUME_STAGING ECHOES_PROMOTION_JOURNAL ECHOES_STATE_ROOT \
    ECHOES_LOG_ROOT; do
    [[ -n "${!name:-}" ]] || {
        printf 'Required service variable is empty: %s\n' "$name" >&2
        exit 1
    }
done
if [[ "$ECHOES_M7_CLOUD_EXECUTION" != "1" ||
    "$ECHOES_MAXIMUM_MEMORY_BYTES" != "30064771072" ||
    "$ECHOES_DUCKDB_MEMORY_LIMIT_BYTES" != "23622320128" ||
    "$ECHOES_MINIMUM_FREE_DISK_BYTES" != "26843545600" ||
    "$ECHOES_THREAD_COUNT" != "1" ||
    "$ECHOES_DUCKDB_TEMP_DIRECTORY" != "/var/lib/project-echoes/tmp/duckdb" ||
    "$TMPDIR" != "/var/lib/project-echoes/tmp" ]]; then
    printf 'Installed process resource contract differs from the governed values.\n' >&2
    exit 1
fi
if systemctl is-active --quiet "$SERVICE_NAME"; then
    printf '%s is already active; refusing a duplicate launch.\n' "$SERVICE_NAME" >&2
    exit 1
fi
if pgrep -af '[r]un-lexical-pipeline' >/dev/null; then
    printf 'A run-lexical-pipeline process already exists outside the service.\n' >&2
    pgrep -af '[r]un-lexical-pipeline' >&2 || true
    exit 1
fi
if [[ "$(git -C "$ECHOES_REPO_ROOT" rev-parse HEAD)" != "$ECHOES_EXPECTED_COMMIT" ||
    "$(git -C "$ECHOES_REPO_ROOT" branch --show-current)" != "$ECHOES_EXPECTED_BRANCH" ]]; then
    printf 'Repository branch or commit differs from the installed execution contract.\n' >&2
    exit 1
fi

BOOTSTRAP_RECEIPT="$ECHOES_STATE_ROOT/bootstrap-validation.json"
if [[ ! -f "$BOOTSTRAP_RECEIPT" ||
    "$(jq -r '.passed' "$BOOTSTRAP_RECEIPT")" != "true" ]]; then
    printf 'Successful bootstrap receipt is missing.\n' >&2
    exit 1
fi
EXPECTED_MANIFEST_HASH="$(jq -r '.transfer_manifest_sha256' "$BOOTSTRAP_RECEIPT")"
CURRENT_MANIFEST_HASH="$(sha256sum "$ECHOES_TRANSFER_MANIFEST" | awk '{print $1}')"
if [[ "$CURRENT_MANIFEST_HASH" != "$EXPECTED_MANIFEST_HASH" ||
    "$CURRENT_MANIFEST_HASH" != "$ECHOES_TRANSFER_MANIFEST_SHA256" ]]; then
    printf 'Transfer manifest changed after bootstrap validation.\n' >&2
    exit 1
fi
if [[ "$(jq -r '.commit // ""' "$BOOTSTRAP_RECEIPT")" != "$ECHOES_EXPECTED_COMMIT" ||
    "$(jq -r '.database_rebind_receipt // ""' "$BOOTSTRAP_RECEIPT")" != "$ECHOES_DATABASE_REBIND_RECEIPT" ||
    "$(jq -r '.database_rebind_receipt_sha256 // ""' "$BOOTSTRAP_RECEIPT")" != "$ECHOES_DATABASE_REBIND_RECEIPT_SHA256" ||
    "$(jq -r '.database_rebind_intent // ""' "$BOOTSTRAP_RECEIPT")" != "$ECHOES_DATABASE_REBIND_INTENT" ||
    "$(jq -r '.database_rebind_intent_sha256 // ""' "$BOOTSTRAP_RECEIPT")" != "$ECHOES_DATABASE_REBIND_INTENT_SHA256" ||
    "$(jq -r '.database_rebind.before_database_sha256 // ""' "$BOOTSTRAP_RECEIPT")" != "$ECHOES_TRANSFER_DATABASE_SHA256" ||
    "$(jq -r '.database_rebind.after_database_sha256 // ""' "$BOOTSTRAP_RECEIPT")" != "$ECHOES_REBOUND_DATABASE_SHA256" ]]; then
    printf 'Installed rebind contract differs from the bootstrap receipt.\n' >&2
    exit 1
fi
if [[ ! -f "$ECHOES_DATABASE_REBIND_RECEIPT" ||
    -L "$ECHOES_DATABASE_REBIND_RECEIPT" ||
    "$(sha256sum "$ECHOES_DATABASE_REBIND_RECEIPT" | awk '{print $1}')" != "$ECHOES_DATABASE_REBIND_RECEIPT_SHA256" ]]; then
    printf 'Governed passage-view-rebind receipt is missing or changed.\n' >&2
    exit 1
fi
if [[ "$ECHOES_DATABASE_REBIND_INTENT" != "$ECHOES_DATABASE_REBIND_RECEIPT.intent.json" ||
    ! -f "$ECHOES_DATABASE_REBIND_INTENT" ||
    -L "$ECHOES_DATABASE_REBIND_INTENT" ||
    "$(sha256sum "$ECHOES_DATABASE_REBIND_INTENT" | awk '{print $1}')" != "$ECHOES_DATABASE_REBIND_INTENT_SHA256" ]]; then
    printf 'Governed passage-view-rebind intent is missing or changed.\n' >&2
    exit 1
fi

runuser -u echoes -- env \
    HOME=/var/lib/project-echoes \
    UV_CACHE_DIR=/var/cache/project-echoes/uv \
    UV_PYTHON_INSTALL_DIR=/var/lib/project-echoes/python \
    UV_PROJECT_ENVIRONMENT=/var/lib/project-echoes/venv \
    GIT_CONFIG_COUNT=1 \
    GIT_CONFIG_KEY_0=safe.directory \
    GIT_CONFIG_VALUE_0="$ECHOES_REPO_ROOT" \
    /usr/local/bin/uv run \
        --directory "$ECHOES_REPO_ROOT" \
        --frozen \
        --offline \
        --no-sync \
        echoes verify-passage-view-rebind \
            --database "$ECHOES_DATABASE" \
            --passage-root "$ECHOES_PASSAGE_ROOT" \
            --expected-before-database-sha256 "$ECHOES_TRANSFER_DATABASE_SHA256" \
            --receipt "$ECHOES_DATABASE_REBIND_RECEIPT" \
            --json >/dev/null

EXPECTED_PROMOTION_JOURNAL="$(
    dirname -- "$ECHOES_OUTPUT_DIRECTORY"
)/.schema-v1.promotion-intent.json"
if [[ "$ECHOES_PROMOTION_JOURNAL" != "$EXPECTED_PROMOTION_JOURNAL" ]]; then
    printf 'Installed lexical promotion journal path is not governed.\n' >&2
    exit 1
fi

# Recovery is deliberately before the canonical/staging launch gates. The CLI
# performs only journal/catalog checks and tiny reads; it never reruns M7 work.
RECOVERY_TIMESTAMP="$(date -u +%Y%m%dT%H%M%S.%3NZ)"
RECOVERY_RECEIPT="$ECHOES_STATE_ROOT/promotion-recovery-$RECOVERY_TIMESTAMP.json"
RECOVERY_LATEST="$ECHOES_STATE_ROOT/latest-promotion-recovery.json"
RECOVERY_RAW="$ECHOES_STATE_ROOT/.promotion-recovery-cli-$RECOVERY_TIMESTAMP.writing-$$"
RECOVERY_STDERR="$ECHOES_LOG_ROOT/promotion-recovery-$RECOVERY_TIMESTAMP.stderr.log"
JOURNAL_ARCHIVE=""
JOURNAL_SHA256=""
JOURNAL_BEFORE_EXISTS=false

if [[ -e "$ECHOES_PROMOTION_JOURNAL" || -L "$ECHOES_PROMOTION_JOURNAL" ]]; then
    JOURNAL_BEFORE_EXISTS=true
    if [[ -L "$ECHOES_PROMOTION_JOURNAL" ||
        ! -f "$ECHOES_PROMOTION_JOURNAL" ]]; then
        printf 'Lexical promotion journal is not a safe regular file: %s\n' \
            "$ECHOES_PROMOTION_JOURNAL" >&2
        printf 'Preserve it in place and inspect with cloud_status.sh; never delete it.\n' >&2
        exit 1
    fi
    JOURNAL_SIZE="$(stat --format='%s' "$ECHOES_PROMOTION_JOURNAL")"
    if [[ ! "$JOURNAL_SIZE" =~ ^[0-9]+$ ]] || ((JOURNAL_SIZE > 65536)); then
        printf 'Lexical promotion journal exceeds the 64 KiB recovery bound.\n' >&2
        printf 'It remains preserved at %s.\n' "$ECHOES_PROMOTION_JOURNAL" >&2
        exit 1
    fi
    JOURNAL_ARCHIVE="$ECHOES_STATE_ROOT/.schema-v1.promotion-intent.$RECOVERY_TIMESTAMP.json"
    if [[ -e "$JOURNAL_ARCHIVE" || -L "$JOURNAL_ARCHIVE" ]]; then
        printf 'Refusing to overwrite promotion journal archive: %s\n' \
            "$JOURNAL_ARCHIVE" >&2
        exit 1
    fi
    cp -- "$ECHOES_PROMOTION_JOURNAL" "$JOURNAL_ARCHIVE"
    chown echoes:echoes "$JOURNAL_ARCHIVE"
    chmod 0600 "$JOURNAL_ARCHIVE"
    JOURNAL_SHA256="$(sha256sum "$ECHOES_PROMOTION_JOURNAL" | awk '{print $1}')"
    if [[ "$(sha256sum "$JOURNAL_ARCHIVE" | awk '{print $1}')" != "$JOURNAL_SHA256" ]]; then
        printf 'Promotion journal changed while it was being preserved; refusing recovery.\n' >&2
        exit 1
    fi
fi

install -o echoes -g echoes -m 0600 /dev/null "$RECOVERY_RAW"
install -o echoes -g echoes -m 0600 /dev/null "$RECOVERY_STDERR"
set +e
runuser -u echoes -- env \
    HOME=/var/lib/project-echoes \
    UV_CACHE_DIR=/var/cache/project-echoes/uv \
    UV_PYTHON_INSTALL_DIR=/var/lib/project-echoes/python \
    UV_PROJECT_ENVIRONMENT=/var/lib/project-echoes/venv \
    UV_OFFLINE=1 \
    GIT_CONFIG_COUNT=1 \
    GIT_CONFIG_KEY_0=safe.directory \
    GIT_CONFIG_VALUE_0="$ECHOES_REPO_ROOT" \
    OMP_NUM_THREADS="$ECHOES_THREAD_COUNT" \
    OPENBLAS_NUM_THREADS="$ECHOES_THREAD_COUNT" \
    MKL_NUM_THREADS="$ECHOES_THREAD_COUNT" \
    NUMEXPR_NUM_THREADS="$ECHOES_THREAD_COUNT" \
    POLARS_MAX_THREADS="$ECHOES_THREAD_COUNT" \
    /usr/local/bin/uv run \
        --directory "$ECHOES_REPO_ROOT" \
        --frozen \
        --offline \
        --no-sync \
        echoes recover-lexical-promotion \
            --database "$ECHOES_DATABASE" \
            --output-dir "$ECHOES_OUTPUT_DIRECTORY" \
            --json >"$RECOVERY_RAW" 2>"$RECOVERY_STDERR"
RECOVERY_EXIT_CODE=$?
set -e

RECOVERY_CLI_JSON=null
RECOVERY_STATE=""
RECOVERY_PASSED=false
RECOVERY_RAW_SIZE="$(stat --format='%s' "$RECOVERY_RAW")"
if [[ "$RECOVERY_RAW_SIZE" =~ ^[0-9]+$ && "$RECOVERY_RAW_SIZE" -le 65536 ]] &&
    jq -e '
    type == "object"
    and (keys | sort) == ["canonical_output_present", "state"]
    and (.canonical_output_present | type) == "boolean"
    and (.state == "no_journal"
        or .state == "staging_restored"
        or .state == "canonical_committed")
' "$RECOVERY_RAW" >/dev/null 2>&1; then
    RECOVERY_CLI_JSON="$(jq -c . "$RECOVERY_RAW")"
    RECOVERY_STATE="$(jq -r '.state' "$RECOVERY_RAW")"
fi
JOURNAL_AFTER_EXISTS=false
if [[ -e "$ECHOES_PROMOTION_JOURNAL" || -L "$ECHOES_PROMOTION_JOURNAL" ]]; then
    JOURNAL_AFTER_EXISTS=true
fi
if ((RECOVERY_EXIT_CODE == 0)) &&
    [[ "$RECOVERY_CLI_JSON" != "null" ]] &&
    {
        [[ "$JOURNAL_BEFORE_EXISTS" == "false" &&
            "$JOURNAL_AFTER_EXISTS" == "false" &&
            "$RECOVERY_STATE" == "no_journal" ]] ||
        [[ "$JOURNAL_BEFORE_EXISTS" == "true" &&
            "$JOURNAL_AFTER_EXISTS" == "false" &&
            "$RECOVERY_STATE" == "staging_restored" ]] ||
        [[ "$JOURNAL_BEFORE_EXISTS" == "true" &&
            "$JOURNAL_AFTER_EXISTS" == "true" &&
            "$RECOVERY_STATE" == "canonical_committed" ]] ||
        [[ "$JOURNAL_BEFORE_EXISTS" == "false" &&
            "$JOURNAL_AFTER_EXISTS" == "false" &&
            "$RECOVERY_STATE" == "canonical_committed" ]]
    }; then
    RECOVERY_PASSED=true
fi
if [[ "$RECOVERY_STATE" == "canonical_committed" &&
    "$(jq -r '.canonical_output_present' "$RECOVERY_RAW" 2>/dev/null)" != "true" ]]; then
    RECOVERY_PASSED=false
fi

COMMIT_WITNESS_KIND=""
COMMIT_WITNESS_JOURNAL=""
COMMIT_WITNESS_JOURNAL_SHA256=""
COMMIT_WITNESS_EXECUTION_MANIFEST=""
COMMIT_WITNESS_EXECUTION_ID=""
COMMIT_WITNESS_EXECUTION_STATUS=""
COMMIT_WITNESS_PROMOTION_ID=""
if [[ "$RECOVERY_PASSED" == "true" &&
    "$RECOVERY_STATE" == "canonical_committed" ]]; then
    if [[ "$JOURNAL_AFTER_EXISTS" == "true" ]]; then
        COMMIT_WITNESS_KIND="active_journal"
        COMMIT_WITNESS_JOURNAL="$ECHOES_PROMOTION_JOURNAL"
    else
        COMMIT_WITNESS_KIND="archived_journal"
        mapfile -d '' committed_candidates < <(
            find "$(dirname -- "$ECHOES_OUTPUT_DIRECTORY")" \
                -mindepth 1 -maxdepth 1 -type f \
                \( -name '.schema-v1.promotion-journal-committed-*.json' \
                    -o -name '.schema-v1.promotion-journal-canonical-committed-*.json' \) \
                -print0
        )
        matched_committed_candidates=()
        for candidate in "${committed_candidates[@]}"; do
            candidate_manifest="$(jq -r '.execution_manifest_path // ""' "$candidate" 2>/dev/null)"
            candidate_execution_id="$(jq -r '.execution_id // ""' "$candidate" 2>/dev/null)"
            if [[ ! -L "$candidate" &&
                "$(jq -r '.output_dir // ""' "$candidate" 2>/dev/null)" == "$ECHOES_OUTPUT_DIRECTORY" &&
                "$(jq -r '.database_path // ""' "$candidate" 2>/dev/null)" == "$ECHOES_DATABASE" &&
                -f "$candidate_manifest" &&
                ! -L "$candidate_manifest" &&
                "$(jq -r '.execution_id // ""' "$candidate_manifest" 2>/dev/null)" == \
                    "$candidate_execution_id" &&
                "$(jq -r '.execution_status // ""' "$candidate_manifest" 2>/dev/null)" == \
                    "succeeded" ]]; then
                matched_committed_candidates+=("$candidate")
            fi
        done
        if ((${#matched_committed_candidates[@]} == 1)); then
            COMMIT_WITNESS_JOURNAL="${matched_committed_candidates[0]}"
        else
            RECOVERY_PASSED=false
        fi
    fi
fi
if [[ -n "$COMMIT_WITNESS_JOURNAL" ]]; then
    COMMIT_WITNESS_JOURNAL_SHA256="$(
        sha256sum "$COMMIT_WITNESS_JOURNAL" | awk '{print $1}'
    )"
    COMMIT_WITNESS_EXECUTION_MANIFEST="$(
        jq -r '.execution_manifest_path // ""' "$COMMIT_WITNESS_JOURNAL"
    )"
    COMMIT_WITNESS_EXECUTION_ID="$(
        jq -r '.execution_id // ""' "$COMMIT_WITNESS_JOURNAL"
    )"
    COMMIT_WITNESS_PROMOTION_ID="$(
        jq -r '.promotion_id // ""' "$COMMIT_WITNESS_JOURNAL"
    )"
    if [[ -f "$COMMIT_WITNESS_EXECUTION_MANIFEST" &&
        ! -L "$COMMIT_WITNESS_EXECUTION_MANIFEST" ]]; then
        COMMIT_WITNESS_EXECUTION_STATUS="$(
            jq -r '.execution_status // ""' "$COMMIT_WITNESS_EXECUTION_MANIFEST"
        )"
    fi
    if [[ ! "$COMMIT_WITNESS_JOURNAL_SHA256" =~ ^[0-9a-f]{64}$ ||
        "$(jq -r '.output_dir // ""' "$COMMIT_WITNESS_JOURNAL")" != "$ECHOES_OUTPUT_DIRECTORY" ||
        "$(jq -r '.database_path // ""' "$COMMIT_WITNESS_JOURNAL")" != "$ECHOES_DATABASE" ||
        ! "$COMMIT_WITNESS_EXECUTION_ID" =~ ^[A-Za-z0-9._-]+$ ||
        ! "$COMMIT_WITNESS_PROMOTION_ID" =~ ^[0-9a-f]{32}$ ||
        ! -f "$COMMIT_WITNESS_EXECUTION_MANIFEST" ||
        -L "$COMMIT_WITNESS_EXECUTION_MANIFEST" ||
        "$(dirname -- "$(dirname -- "$COMMIT_WITNESS_EXECUTION_MANIFEST")")" != \
            "$(dirname -- "$ECHOES_OUTPUT_DIRECTORY")/execution-manifests" ||
        "$(basename -- "$COMMIT_WITNESS_EXECUTION_MANIFEST")" != \
            "$COMMIT_WITNESS_EXECUTION_ID.json" ||
        "$(jq -r '.execution_id // ""' "$COMMIT_WITNESS_EXECUTION_MANIFEST")" != \
            "$COMMIT_WITNESS_EXECUTION_ID" ||
        ( "$COMMIT_WITNESS_EXECUTION_STATUS" != "running" &&
            "$COMMIT_WITNESS_EXECUTION_STATUS" != "failed" &&
            "$COMMIT_WITNESS_EXECUTION_STATUS" != "succeeded" ) ||
        ( "$COMMIT_WITNESS_KIND" == "active_journal" &&
            "$COMMIT_WITNESS_JOURNAL_SHA256" != "$JOURNAL_SHA256" ) ||
        ( "$COMMIT_WITNESS_KIND" == "archived_journal" &&
            "$COMMIT_WITNESS_EXECUTION_STATUS" != "succeeded" ) ]]; then
        RECOVERY_PASSED=false
    fi
fi

RECOVERY_TMP="${RECOVERY_RECEIPT}.writing-$$"
jq -n \
    --arg receipt_path "$RECOVERY_RECEIPT" \
    --arg recovered_at_utc "$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)" \
    --arg state "$RECOVERY_STATE" \
    --arg journal_path "$ECHOES_PROMOTION_JOURNAL" \
    --arg journal_sha256 "$JOURNAL_SHA256" \
    --arg archived_journal "$JOURNAL_ARCHIVE" \
    --arg commit_witness_kind "$COMMIT_WITNESS_KIND" \
    --arg commit_witness_journal "$COMMIT_WITNESS_JOURNAL" \
    --arg commit_witness_journal_sha256 "$COMMIT_WITNESS_JOURNAL_SHA256" \
    --arg commit_witness_execution_manifest "$COMMIT_WITNESS_EXECUTION_MANIFEST" \
    --arg commit_witness_execution_id "$COMMIT_WITNESS_EXECUTION_ID" \
    --arg commit_witness_execution_status "$COMMIT_WITNESS_EXECUTION_STATUS" \
    --arg commit_witness_promotion_id "$COMMIT_WITNESS_PROMOTION_ID" \
    --arg stderr_log "$RECOVERY_STDERR" \
    --argjson passed "$RECOVERY_PASSED" \
    --argjson cli_exit_code "$RECOVERY_EXIT_CODE" \
    --argjson cli_output_bytes "$RECOVERY_RAW_SIZE" \
    --argjson journal_before_exists "$JOURNAL_BEFORE_EXISTS" \
    --argjson journal_after_exists "$JOURNAL_AFTER_EXISTS" \
    --argjson cli "$RECOVERY_CLI_JSON" \
    '{
        schema_version: 1,
        receipt_path: $receipt_path,
        recovered_at_utc: $recovered_at_utc,
        passed: $passed,
        cli_exit_code: $cli_exit_code,
        cli_output_bytes: $cli_output_bytes,
        state: (if $state == "" then null else $state end),
        canonical_output_present: ($cli.canonical_output_present // null),
        journal_path: $journal_path,
        journal_before_exists: $journal_before_exists,
        journal_before_sha256: (
            if $journal_sha256 == "" then null else $journal_sha256 end
        ),
        archived_journal: (
            if $archived_journal == "" then null else $archived_journal end
        ),
        archived_journal_sha256: (
            if $journal_sha256 == "" then null else $journal_sha256 end
        ),
        commit_witness: (
            if $commit_witness_kind == "" then null else {
                kind: $commit_witness_kind,
                journal: $commit_witness_journal,
                journal_sha256: $commit_witness_journal_sha256,
                execution_manifest: $commit_witness_execution_manifest,
                execution_id: $commit_witness_execution_id,
                execution_status_at_recovery: $commit_witness_execution_status,
                promotion_id: $commit_witness_promotion_id
            } end
        ),
        journal_after_exists: $journal_after_exists,
        recovery_cli: $cli,
        stderr_log: $stderr_log
    }' >"$RECOVERY_TMP"
chown echoes:echoes "$RECOVERY_TMP"
chmod 0600 "$RECOVERY_TMP"
mv -f -- "$RECOVERY_TMP" "$RECOVERY_RECEIPT"
cp -- "$RECOVERY_RECEIPT" "${RECOVERY_LATEST}.writing-$$"
chown echoes:echoes "${RECOVERY_LATEST}.writing-$$"
chmod 0600 "${RECOVERY_LATEST}.writing-$$"
mv -f -- "${RECOVERY_LATEST}.writing-$$" "$RECOVERY_LATEST"
rm -f -- "$RECOVERY_RAW"

if [[ "$RECOVERY_PASSED" != "true" ]]; then
    printf 'Lexical promotion recovery failed closed; receipt: %s\n' \
        "$RECOVERY_RECEIPT" >&2
    printf 'The live journal and any immutable archive were preserved. Inspect cloud_status.sh.\n' >&2
    exit 1
fi
if [[ "$RECOVERY_STATE" == "canonical_committed" ]]; then
    printf 'Recovery confirmed committed canonical output; refusing a new worker.\n' >&2
    if [[ "$JOURNAL_AFTER_EXISTS" == "true" ]]; then
        printf 'The active journal remains preserved until successful provenance sealing.\n' >&2
    else
        printf 'A committed journal archive and succeeded execution provenance were authenticated.\n' >&2
    fi
    printf 'Run detached strict validation/provenance recovery: sudo bash %s/cloud/cloud_validate.sh --submit\n' \
        "$ECHOES_REPO_ROOT" >&2
    exit 1
fi

if [[ -e "$ECHOES_OUTPUT_DIRECTORY" || -L "$ECHOES_OUTPUT_DIRECTORY" ]]; then
    printf 'Canonical schema-v1 already exists; refusing the recovered first run.\n' >&2
    exit 1
fi
if [[ ! -d "$ECHOES_RESUME_STAGING" || -L "$ECHOES_RESUME_STAGING" ||
    ! -f "$ECHOES_RESUME_STAGING/.resume-primary-candidates/complete.json" ]]; then
    printf 'Governed resume staging or its primary checkpoint manifest is missing.\n' >&2
    exit 1
fi
if [[ -n "$(find "$ECHOES_RESUME_STAGING" -type l -print -quit)" ]]; then
    printf 'Resume staging contains a symlink.\n' >&2
    exit 1
fi

mapfile -d '' STAGING_CANDIDATES < <(
    find "$(dirname -- "$ECHOES_OUTPUT_DIRECTORY")" -mindepth 1 -maxdepth 1 -type d \
        -regextype posix-extended \
        -regex '.*/\.schema-v1\.writing-[0-9a-fA-F]{32}' -print0
)
if ((${#STAGING_CANDIDATES[@]} != 1)) ||
    [[ "${STAGING_CANDIDATES[0]%/}" != "${ECHOES_RESUME_STAGING%/}" ]]; then
    printf 'Refusing ambiguous resume; expected exactly the configured staging directory.\n' >&2
    exit 1
fi

AVAILABLE_BYTES="$(
    df -PB1 "$(dirname -- "$ECHOES_OUTPUT_DIRECTORY")" | awk 'NR == 2 {print $4}'
)"
if [[ ! "$AVAILABLE_BYTES" =~ ^[0-9]+$ ]] || ((AVAILABLE_BYTES < MINIMUM_FREE_BYTES)); then
    printf 'At least %s free bytes are required before launch; observed %s.\n' \
        "$MINIMUM_FREE_BYTES" "${AVAILABLE_BYTES:-unknown}" >&2
    exit 1
fi

UNIT_PATH="/etc/systemd/system/$SERVICE_NAME"
if [[ "$(systemctl show "$SERVICE_NAME" --property=FragmentPath --value)" != "$UNIT_PATH" ||
    -n "$(systemctl show "$SERVICE_NAME" --property=DropInPaths --value)" ]]; then
    printf 'Service fragment path or drop-in state differs from the installed contract.\n' >&2
    exit 1
fi
for directive in \
    "User=echoes" \
    "Group=echoes" \
    "ExecStart=/usr/local/libexec/echoes-m7-worker" \
    "Restart=no" \
    "RuntimeMaxSec=48h" \
    "MemoryHigh=26G" \
    "MemoryMax=28G" \
    "MemorySwapMax=0" \
    "KillSignal=SIGINT"; do
    if ! grep -Fqx -- "$directive" "$UNIT_PATH"; then
        printf 'Required systemd directive is missing or changed: %s\n' "$directive" >&2
        exit 1
    fi
done

systemctl reset-failed "$SERVICE_NAME" >/dev/null 2>&1 || true
systemctl start "$SERVICE_NAME"

# Exactly one startup inspection; this command never polls or sleeps.
systemctl show "$SERVICE_NAME" \
    --property=Id \
    --property=ActiveState \
    --property=SubState \
    --property=Result \
    --property=MainPID \
    --property=ExecMainStartTimestamp \
    --property=MemoryHigh \
    --property=MemoryMax \
    --property=RuntimeMaxUSec \
    --no-pager

printf 'Detached Milestone 7 launch submitted. Do not babysit it.\n'
printf 'One-shot status: sudo bash %s/cloud/cloud_status.sh\n' "$ECHOES_REPO_ROOT"
