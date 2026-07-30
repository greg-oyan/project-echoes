#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
    cat <<'EOF'
Usage: install_echoes_service.sh \
  [--repo-root /srv/project-echoes/repo] \
  [--resume-staging data/processed/lexical/.schema-v1.writing-<32hex>]

Install (but do not start) the fail-closed systemd service for the first,
resumed Milestone 7 cloud run.
EOF
}

REPO_ROOT="/srv/project-echoes/repo"
RESUME_STAGING="data/processed/lexical/.schema-v1.writing-238902db1f6e479596bea47e70ccf30b"
SERVICE_NAME="echoes-m7.service"
SERVICE_USER="echoes"
SERVICE_GROUP="echoes"
STATE_ROOT="/var/lib/project-echoes/m7"
TEMP_ROOT="/var/lib/project-echoes/tmp"
LOG_ROOT="/var/log/project-echoes/m7"
PACKAGE_ROOT="/srv/project-echoes/packages"
ENV_DIRECTORY="/etc/project-echoes"
ENV_FILE="$ENV_DIRECTORY/m7.env"
WORKER_PATH="/usr/local/libexec/echoes-m7-worker"
UNIT_PATH="/etc/systemd/system/$SERVICE_NAME"
DUCKDB_MEMORY_BYTES=51539607552
MAXIMUM_MEMORY_BYTES=60129542144
THREAD_COUNT=1

while (($#)); do
    case "$1" in
        --repo-root)
            (($# >= 2)) || { usage >&2; exit 2; }
            REPO_ROOT="$2"
            shift 2
            ;;
        --resume-staging)
            (($# >= 2)) || { usage >&2; exit 2; }
            RESUME_STAGING="$2"
            shift 2
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

if [[ $EUID -ne 0 ]]; then
    printf 'install_echoes_service.sh must run as root (use sudo).\n' >&2
    exit 1
fi
for value in "$REPO_ROOT" "$STATE_ROOT" "$TEMP_ROOT" "$LOG_ROOT" "$PACKAGE_ROOT"; do
    [[ "$value" =~ ^/[A-Za-z0-9._/-]+$ && "$value" != *".."* ]] || {
        printf 'Unsafe absolute path: %s\n' "$value" >&2
        exit 1
    }
done
[[ "$RESUME_STAGING" =~ ^[A-Za-z0-9._/-]+$ && "$RESUME_STAGING" != /* &&
    "$RESUME_STAGING" != *".."* ]] || {
    printf 'Resume staging must be a confined repository-relative path: %s\n' \
        "$RESUME_STAGING" >&2
    exit 1
}
[[ "$(basename -- "$RESUME_STAGING")" =~ ^\.schema-v1\.writing-[0-9a-fA-F]{32}$ ]] || {
    printf 'Resume staging name is not governed: %s\n' "$RESUME_STAGING" >&2
    exit 1
}
if [[ ! -f "$STATE_ROOT/bootstrap-validation.json" ]]; then
    printf 'Successful bootstrap receipt is missing: %s\n' \
        "$STATE_ROOT/bootstrap-validation.json" >&2
    exit 1
fi
if [[ "$(jq -r '.passed' "$STATE_ROOT/bootstrap-validation.json")" != "true" ]]; then
    printf 'Bootstrap receipt is not successful.\n' >&2
    exit 1
fi
if [[ ! -d "$REPO_ROOT/.git" ]]; then
    printf 'Repository is missing: %s\n' "$REPO_ROOT" >&2
    exit 1
fi

EXPECTED_COMMIT="$(jq -r '.commit' "$STATE_ROOT/bootstrap-validation.json")"
EXPECTED_BRANCH="$(jq -r '.branch' "$STATE_ROOT/bootstrap-validation.json")"
MANIFEST_PATH="$(jq -r '.transfer_manifest' "$STATE_ROOT/bootstrap-validation.json")"
MANIFEST_SHA256="$(
    jq -r '.transfer_manifest_sha256' "$STATE_ROOT/bootstrap-validation.json"
)"
REBIND_RECEIPT="$(
    jq -r '.database_rebind_receipt' "$STATE_ROOT/bootstrap-validation.json"
)"
REBIND_RECEIPT_SHA256="$(
    jq -r '.database_rebind_receipt_sha256' "$STATE_ROOT/bootstrap-validation.json"
)"
REBIND_INTENT="$(
    jq -r '.database_rebind_intent' "$STATE_ROOT/bootstrap-validation.json"
)"
REBIND_INTENT_SHA256="$(
    jq -r '.database_rebind_intent_sha256' "$STATE_ROOT/bootstrap-validation.json"
)"
TRANSFER_DATABASE_SHA256="$(
    jq -r '.database_rebind.before_database_sha256' \
        "$STATE_ROOT/bootstrap-validation.json"
)"
REBOUND_DATABASE_SHA256="$(
    jq -r '.database_rebind.after_database_sha256' \
        "$STATE_ROOT/bootstrap-validation.json"
)"
DATABASE_PATH="$REPO_ROOT/data/processed/project_echoes.duckdb"
PASSAGE_ROOT="$REPO_ROOT/data/processed/passages/schema-v1"
if [[ "$(git -C "$REPO_ROOT" rev-parse HEAD)" != "$EXPECTED_COMMIT" ||
    "$(git -C "$REPO_ROOT" branch --show-current)" != "$EXPECTED_BRANCH" ]]; then
    printf 'Repository no longer matches the successful bootstrap receipt.\n' >&2
    exit 1
fi
if [[ ! "$REBIND_RECEIPT" =~ ^/var/lib/project-echoes/m7/passage-view-rebind(-[0-9TZ.-]+)?\.json$ ||
    "$REBIND_RECEIPT" == *".."* ||
    ! "$REBIND_RECEIPT_SHA256" =~ ^[0-9a-f]{64}$ ||
    "$REBIND_INTENT" != "$REBIND_RECEIPT.intent.json" ||
    ! "$REBIND_INTENT_SHA256" =~ ^[0-9a-f]{64}$ ||
    ! "$TRANSFER_DATABASE_SHA256" =~ ^[0-9a-f]{64}$ ||
    ! "$REBOUND_DATABASE_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
    printf 'Bootstrap passage-view-rebind identity is malformed.\n' >&2
    exit 1
fi
if [[ ! -f "$REBIND_RECEIPT" || -L "$REBIND_RECEIPT" ||
    "$(sha256sum "$REBIND_RECEIPT" | awk '{print $1}')" != "$REBIND_RECEIPT_SHA256" ||
    "$(jq -r '.before_database_sha256 // ""' "$REBIND_RECEIPT")" != "$TRANSFER_DATABASE_SHA256" ||
    "$(jq -r '.after_database_sha256 // ""' "$REBIND_RECEIPT")" != "$REBOUND_DATABASE_SHA256" ]]; then
    printf 'Governed passage-view-rebind receipt no longer matches bootstrap.\n' >&2
    exit 1
fi
if [[ ! -f "$REBIND_INTENT" || -L "$REBIND_INTENT" ||
    "$(sha256sum "$REBIND_INTENT" | awk '{print $1}')" != "$REBIND_INTENT_SHA256" ||
    "$(jq -r '.before_database_sha256 // ""' "$REBIND_INTENT")" != "$TRANSFER_DATABASE_SHA256" ||
    "$(jq -r '.database_path // ""' "$REBIND_INTENT")" != "$DATABASE_PATH" ||
    "$(jq -r '.passage_root // ""' "$REBIND_INTENT")" != "$PASSAGE_ROOT" ]]; then
    printf 'Governed passage-view-rebind intent no longer matches bootstrap.\n' >&2
    exit 1
fi
if [[ "$(sha256sum "$MANIFEST_PATH" | awk '{print $1}')" != "$MANIFEST_SHA256" ||
    "$(sha256sum "$DATABASE_PATH" | awk '{print $1}')" != "$REBOUND_DATABASE_SHA256" ]]; then
    printf 'Transfer manifest or prelaunch database changed after bootstrap.\n' >&2
    exit 1
fi
runuser -u "$SERVICE_USER" -- env \
    HOME=/var/lib/project-echoes \
    UV_CACHE_DIR=/var/cache/project-echoes/uv \
    UV_PYTHON_INSTALL_DIR=/var/lib/project-echoes/python \
    UV_PROJECT_ENVIRONMENT=/var/lib/project-echoes/venv \
    GIT_CONFIG_COUNT=1 \
    GIT_CONFIG_KEY_0=safe.directory \
    GIT_CONFIG_VALUE_0="$REPO_ROOT" \
    /usr/local/bin/uv run \
        --directory "$REPO_ROOT" \
        --frozen \
        --offline \
        --no-sync \
        echoes verify-passage-view-rebind \
            --database "$DATABASE_PATH" \
            --passage-root "$PASSAGE_ROOT" \
            --expected-before-database-sha256 "$TRANSFER_DATABASE_SHA256" \
            --receipt "$REBIND_RECEIPT" \
            --json >/dev/null

CANONICAL_OUTPUT="$REPO_ROOT/data/processed/lexical/schema-v1"
STAGING_PATH="$REPO_ROOT/$RESUME_STAGING"
LEXICAL_PARENT="$(dirname -- "$CANONICAL_OUTPUT")"
PROMOTION_JOURNAL="$LEXICAL_PARENT/.schema-v1.promotion-intent.json"
if [[ -e "$CANONICAL_OUTPUT" || -L "$CANONICAL_OUTPUT" ]]; then
    printf 'Canonical schema-v1 already exists; refusing resume service installation: %s\n' \
        "$CANONICAL_OUTPUT" >&2
    exit 1
fi
if [[ ! -d "$STAGING_PATH" || -L "$STAGING_PATH" ]]; then
    printf 'Resume staging is missing or unsafe: %s\n' "$STAGING_PATH" >&2
    exit 1
fi
mapfile -d '' STAGING_CANDIDATES < <(
    find "$LEXICAL_PARENT" -mindepth 1 -maxdepth 1 -type d \
        -regextype posix-extended \
        -regex '.*/\.schema-v1\.writing-[0-9a-fA-F]{32}' -print0
)
if ((${#STAGING_CANDIDATES[@]} != 1)) ||
    [[ "${STAGING_CANDIDATES[0]%/}" != "${STAGING_PATH%/}" ]]; then
    printf 'Expected exactly the selected governed staging directory; found %s.\n' \
        "${#STAGING_CANDIDATES[@]}" >&2
    exit 1
fi
if [[ -n "$(find "$STAGING_PATH" -type l -print -quit)" ]]; then
    printf 'Resume staging contains a symlink; refusing installation.\n' >&2
    exit 1
fi
if [[ ! -f "$STAGING_PATH/.resume-primary-candidates/complete.json" ]]; then
    printf 'Primary checkpoint completion manifest is missing from resume staging.\n' >&2
    exit 1
fi
if [[ -e "$STAGING_PATH/table-hashes.json" ||
    -e "$STAGING_PATH/lexical_metadata" ]]; then
    printf 'Resume staging already resembles finalized output; refusing installation.\n' >&2
    exit 1
fi
if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    printf '%s is active; refusing to replace it.\n' "$SERVICE_NAME" >&2
    exit 1
fi

install -d -o root -g "$SERVICE_GROUP" -m 0750 "$ENV_DIRECTORY"
install -d -o root -g root -m 0755 "$(dirname -- "$WORKER_PATH")"
install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 0750 \
    "$STATE_ROOT" \
    "$TEMP_ROOT" \
    "$TEMP_ROOT/duckdb" \
    "$LOG_ROOT" \
    "$PACKAGE_ROOT"

ENV_TMP="${ENV_FILE}.writing-$$"
cat >"$ENV_TMP" <<EOF
ECHOES_M7_CLOUD_EXECUTION=1
ECHOES_REPO_ROOT=$REPO_ROOT
ECHOES_EXPECTED_BRANCH=$EXPECTED_BRANCH
ECHOES_EXPECTED_COMMIT=$EXPECTED_COMMIT
ECHOES_TRANSFER_MANIFEST=$MANIFEST_PATH
ECHOES_TRANSFER_MANIFEST_SHA256=$MANIFEST_SHA256
ECHOES_DATABASE=$DATABASE_PATH
ECHOES_PASSAGE_ROOT=$PASSAGE_ROOT
ECHOES_DATABASE_REBIND_RECEIPT=$REBIND_RECEIPT
ECHOES_DATABASE_REBIND_RECEIPT_SHA256=$REBIND_RECEIPT_SHA256
ECHOES_DATABASE_REBIND_INTENT=$REBIND_INTENT
ECHOES_DATABASE_REBIND_INTENT_SHA256=$REBIND_INTENT_SHA256
ECHOES_TRANSFER_DATABASE_SHA256=$TRANSFER_DATABASE_SHA256
ECHOES_REBOUND_DATABASE_SHA256=$REBOUND_DATABASE_SHA256
ECHOES_OUTPUT_DIRECTORY=$CANONICAL_OUTPUT
ECHOES_RESUME_STAGING=$STAGING_PATH
ECHOES_PROMOTION_JOURNAL=$PROMOTION_JOURNAL
ECHOES_STATE_ROOT=$STATE_ROOT
ECHOES_LOG_ROOT=$LOG_ROOT
ECHOES_PACKAGE_ROOT=$PACKAGE_ROOT
ECHOES_MAXIMUM_MEMORY_BYTES=$MAXIMUM_MEMORY_BYTES
ECHOES_DUCKDB_MEMORY_LIMIT_BYTES=$DUCKDB_MEMORY_BYTES
ECHOES_THREAD_COUNT=$THREAD_COUNT
ECHOES_DUCKDB_TEMP_DIRECTORY=$TEMP_ROOT/duckdb
TMPDIR=$TEMP_ROOT
HOME=/var/lib/project-echoes
UV_CACHE_DIR=/var/cache/project-echoes/uv
UV_PYTHON_INSTALL_DIR=/var/lib/project-echoes/python
UV_PROJECT_ENVIRONMENT=/var/lib/project-echoes/venv
UV_OFFLINE=1
GIT_CONFIG_COUNT=1
GIT_CONFIG_KEY_0=safe.directory
GIT_CONFIG_VALUE_0=$REPO_ROOT
PYTHONDONTWRITEBYTECODE=1
OMP_NUM_THREADS=$THREAD_COUNT
OPENBLAS_NUM_THREADS=$THREAD_COUNT
MKL_NUM_THREADS=$THREAD_COUNT
NUMEXPR_NUM_THREADS=$THREAD_COUNT
VECLIB_MAXIMUM_THREADS=$THREAD_COUNT
BLIS_NUM_THREADS=$THREAD_COUNT
POLARS_MAX_THREADS=$THREAD_COUNT
EOF
chown root:"$SERVICE_GROUP" "$ENV_TMP"
chmod 0640 "$ENV_TMP"
mv -f -- "$ENV_TMP" "$ENV_FILE"

WORKER_TMP="${WORKER_PATH}.writing-$$"
cat >"$WORKER_TMP" <<'WORKER'
#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 0077

# shellcheck disable=SC1091
source /etc/project-echoes/m7.env

required_variables=(
    ECHOES_REPO_ROOT
    ECHOES_EXPECTED_BRANCH
    ECHOES_EXPECTED_COMMIT
    ECHOES_TRANSFER_MANIFEST
    ECHOES_TRANSFER_MANIFEST_SHA256
    ECHOES_DATABASE
    ECHOES_PASSAGE_ROOT
    ECHOES_DATABASE_REBIND_RECEIPT
    ECHOES_DATABASE_REBIND_RECEIPT_SHA256
    ECHOES_DATABASE_REBIND_INTENT
    ECHOES_DATABASE_REBIND_INTENT_SHA256
    ECHOES_TRANSFER_DATABASE_SHA256
    ECHOES_REBOUND_DATABASE_SHA256
    ECHOES_OUTPUT_DIRECTORY
    ECHOES_RESUME_STAGING
    ECHOES_PROMOTION_JOURNAL
    ECHOES_STATE_ROOT
    ECHOES_LOG_ROOT
    ECHOES_MAXIMUM_MEMORY_BYTES
    ECHOES_DUCKDB_MEMORY_LIMIT_BYTES
    ECHOES_THREAD_COUNT
    ECHOES_DUCKDB_TEMP_DIRECTORY
)
for name in "${required_variables[@]}"; do
    [[ -n "${!name:-}" ]] || {
        printf 'Required service variable is empty: %s\n' "$name" >&2
        exit 1
    }
done

exec 9>/run/project-echoes/echoes-m7.lock
if ! flock -n 9; then
    printf 'Another Milestone 7 worker holds /run/project-echoes/echoes-m7.lock.\n' >&2
    exit 1
fi

if [[ "$(git -C "$ECHOES_REPO_ROOT" rev-parse HEAD)" != "$ECHOES_EXPECTED_COMMIT" ||
    "$(git -C "$ECHOES_REPO_ROOT" branch --show-current)" != "$ECHOES_EXPECTED_BRANCH" ]]; then
    printf 'Repository branch or commit drifted after service installation.\n' >&2
    exit 1
fi
if [[ ! -f "$ECHOES_DATABASE_REBIND_RECEIPT" ||
    -L "$ECHOES_DATABASE_REBIND_RECEIPT" ||
    "$(sha256sum "$ECHOES_DATABASE_REBIND_RECEIPT" | awk '{print $1}')" != "$ECHOES_DATABASE_REBIND_RECEIPT_SHA256" ||
    "$(jq -r '.before_database_sha256 // ""' "$ECHOES_DATABASE_REBIND_RECEIPT")" != "$ECHOES_TRANSFER_DATABASE_SHA256" ||
    "$(jq -r '.after_database_sha256 // ""' "$ECHOES_DATABASE_REBIND_RECEIPT")" != "$ECHOES_REBOUND_DATABASE_SHA256" ]]; then
    printf 'Governed passage-view-rebind receipt drifted before worker entry.\n' >&2
    exit 1
fi
if [[ ! -f "$ECHOES_DATABASE_REBIND_INTENT" ||
    -L "$ECHOES_DATABASE_REBIND_INTENT" ||
    "$(sha256sum "$ECHOES_DATABASE_REBIND_INTENT" | awk '{print $1}')" != "$ECHOES_DATABASE_REBIND_INTENT_SHA256" ||
    "$(jq -r '.before_database_sha256 // ""' "$ECHOES_DATABASE_REBIND_INTENT")" != "$ECHOES_TRANSFER_DATABASE_SHA256" ]]; then
    printf 'Governed passage-view-rebind intent drifted before worker entry.\n' >&2
    exit 1
fi
if [[ "$(sha256sum "$ECHOES_TRANSFER_MANIFEST" | awk '{print $1}')" != "$ECHOES_TRANSFER_MANIFEST_SHA256" ]]; then
    printf 'Transfer manifest drifted before worker entry.\n' >&2
    exit 1
fi
prelaunch_database_sha256="$(
    sha256sum "$ECHOES_DATABASE" | awk '{print $1}'
)"
if [[ "$prelaunch_database_sha256" != "$ECHOES_REBOUND_DATABASE_SHA256" ]]; then
    printf 'Database no longer matches its verified prelaunch rebound hash.\n' >&2
    exit 1
fi
expected_promotion_journal="$(
    dirname -- "$ECHOES_OUTPUT_DIRECTORY"
)/.schema-v1.promotion-intent.json"
if [[ "$ECHOES_PROMOTION_JOURNAL" != "$expected_promotion_journal" ]]; then
    printf 'Installed lexical promotion journal path is not governed.\n' >&2
    exit 1
fi
if [[ -e "$ECHOES_PROMOTION_JOURNAL" || -L "$ECHOES_PROMOTION_JOURNAL" ]]; then
    printf 'Unresolved lexical promotion journal appeared after launch preflight.\n' >&2
    printf 'Run cloud_start.sh again after this service stops; never delete the journal.\n' >&2
    exit 1
fi
latest_promotion_recovery="$ECHOES_STATE_ROOT/latest-promotion-recovery.json"
if [[ ! -f "$latest_promotion_recovery" || -L "$latest_promotion_recovery" ]]; then
    printf 'A safe lexical promotion recovery preflight receipt is required.\n' >&2
    exit 1
fi
promotion_recovery_receipt="$(
    jq -r '.receipt_path // ""' "$latest_promotion_recovery"
)"
promotion_recovery_basename="$(basename -- "$promotion_recovery_receipt")"
if [[ "$(dirname -- "$promotion_recovery_receipt")" != "$ECHOES_STATE_ROOT" ||
    ! "$promotion_recovery_basename" =~ ^promotion-recovery-[0-9]{8}T[0-9]{6}\.[0-9]{3}Z\.json$ ||
    ! -f "$promotion_recovery_receipt" ||
    -L "$promotion_recovery_receipt" ||
    "$(sha256sum "$promotion_recovery_receipt" | awk '{print $1}')" != \
        "$(sha256sum "$latest_promotion_recovery" | awk '{print $1}')" ||
    "$(jq -r '.passed // false' "$promotion_recovery_receipt")" != "true" ||
    "$(jq -r '.journal_path // ""' "$promotion_recovery_receipt")" != "$ECHOES_PROMOTION_JOURNAL" ||
    "$(jq -r '.journal_after_exists // true' "$promotion_recovery_receipt")" != "false" ]]; then
    printf 'Lexical promotion recovery preflight receipt is unsafe or inconsistent.\n' >&2
    exit 1
fi
promotion_recovery_state="$(
    jq -r '.state // ""' "$promotion_recovery_receipt"
)"
if [[ "$promotion_recovery_state" != "no_journal" &&
    "$promotion_recovery_state" != "staging_restored" ]]; then
    printf 'Recovery state %s does not authorize a new worker.\n' \
        "${promotion_recovery_state:-missing}" >&2
    exit 1
fi
promotion_recovery_receipt_sha256="$(
    sha256sum "$promotion_recovery_receipt" | awk '{print $1}'
)"
if [[ -e "$ECHOES_OUTPUT_DIRECTORY" || -L "$ECHOES_OUTPUT_DIRECTORY" ]]; then
    printf 'Canonical schema-v1 already exists; refusing the recovered first run.\n' >&2
    exit 1
fi
if [[ ! -d "$ECHOES_RESUME_STAGING" || -L "$ECHOES_RESUME_STAGING" ||
    ! -f "$ECHOES_RESUME_STAGING/.resume-primary-candidates/complete.json" ]]; then
    printf 'Governed resume staging or primary checkpoint manifest is unavailable.\n' >&2
    exit 1
fi
if [[ -n "$(find "$ECHOES_RESUME_STAGING" -type l -print -quit)" ]]; then
    printf 'Governed resume staging contains a symlink.\n' >&2
    exit 1
fi
mapfile -d '' worker_staging_candidates < <(
    find "$(dirname -- "$ECHOES_OUTPUT_DIRECTORY")" \
        -mindepth 1 -maxdepth 1 -type d \
        -regextype posix-extended \
        -regex '.*/\.schema-v1\.writing-[0-9a-fA-F]{32}' -print0
)
if ((${#worker_staging_candidates[@]} != 1)) ||
    [[ "${worker_staging_candidates[0]%/}" != "${ECHOES_RESUME_STAGING%/}" ]]; then
    printf 'Governed resume staging became ambiguous before worker entry.\n' >&2
    exit 1
fi

mkdir -p -- "$ECHOES_STATE_ROOT" "$ECHOES_LOG_ROOT" \
    "$ECHOES_DUCKDB_TEMP_DIRECTORY" "$TMPDIR"
timestamp="$(date -u +%Y%m%dT%H%M%S.%3NZ)"
stdout_path="$ECHOES_LOG_ROOT/m7-resume-$timestamp.stdout.log"
stderr_path="$ECHOES_LOG_ROOT/m7-resume-$timestamp.stderr.log"
metadata_path="$ECHOES_STATE_ROOT/launch-$timestamp.json"
latest_path="$ECHOES_STATE_ROOT/latest-launch.json"
install -m 0600 /dev/null "$stdout_path"
install -m 0600 /dev/null "$stderr_path"

command=(
    /usr/local/bin/uv
    run
    --directory "$ECHOES_REPO_ROOT"
    --frozen
    --offline
    --no-sync
    echoes
    run-lexical-pipeline
    --primary
    --database "$ECHOES_DATABASE"
    --output-dir "$ECHOES_OUTPUT_DIRECTORY"
    --resume-staging-dir "$ECHOES_RESUME_STAGING"
    --json
)

metadata_tmp="${metadata_path}.writing-$$"
jq -n \
    --arg launch_id "$timestamp" \
    --arg started_at_utc "$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)" \
    --argjson pid "$$" \
    --arg commit "$ECHOES_EXPECTED_COMMIT" \
    --arg branch "$ECHOES_EXPECTED_BRANCH" \
    --arg repository "$ECHOES_REPO_ROOT" \
    --arg database "$ECHOES_DATABASE" \
    --arg passage_root "$ECHOES_PASSAGE_ROOT" \
    --arg database_rebind_receipt "$ECHOES_DATABASE_REBIND_RECEIPT" \
    --arg database_rebind_receipt_sha256 "$ECHOES_DATABASE_REBIND_RECEIPT_SHA256" \
    --arg database_rebind_intent "$ECHOES_DATABASE_REBIND_INTENT" \
    --arg database_rebind_intent_sha256 "$ECHOES_DATABASE_REBIND_INTENT_SHA256" \
    --arg transfer_database_sha256 "$ECHOES_TRANSFER_DATABASE_SHA256" \
    --arg rebound_database_sha256 "$ECHOES_REBOUND_DATABASE_SHA256" \
    --arg prelaunch_database_sha256 "$prelaunch_database_sha256" \
    --arg promotion_journal "$ECHOES_PROMOTION_JOURNAL" \
    --arg promotion_recovery_receipt "$promotion_recovery_receipt" \
    --arg promotion_recovery_receipt_sha256 "$promotion_recovery_receipt_sha256" \
    --arg promotion_recovery_state "$promotion_recovery_state" \
    --arg transfer_manifest "$ECHOES_TRANSFER_MANIFEST" \
    --arg transfer_manifest_sha256 "$ECHOES_TRANSFER_MANIFEST_SHA256" \
    --arg output "$ECHOES_OUTPUT_DIRECTORY" \
    --arg staging "$ECHOES_RESUME_STAGING" \
    --arg stdout "$stdout_path" \
    --arg stderr "$stderr_path" \
    --arg uv_version "$(/usr/local/bin/uv --version)" \
    --arg python_version "$(
        /usr/local/bin/uv run --directory "$ECHOES_REPO_ROOT" \
            --frozen --offline --no-sync python --version 2>&1
    )" \
    --argjson maximum_memory_bytes "$ECHOES_MAXIMUM_MEMORY_BYTES" \
    --argjson duckdb_memory_limit_bytes "$ECHOES_DUCKDB_MEMORY_LIMIT_BYTES" \
    --argjson thread_count "$ECHOES_THREAD_COUNT" \
    --arg duckdb_temp_directory "$ECHOES_DUCKDB_TEMP_DIRECTORY" \
    --argjson command "$(printf '%s\n' "${command[@]}" | jq -R . | jq -s .)" \
    '{
        schema_version: 1,
        launch_id: $launch_id,
        started_at_utc: $started_at_utc,
        pid: $pid,
        repository: $repository,
        branch: $branch,
        commit: $commit,
        database: $database,
        passage_root: $passage_root,
        database_rebind_receipt: $database_rebind_receipt,
        database_rebind_receipt_sha256: $database_rebind_receipt_sha256,
        database_rebind_intent: $database_rebind_intent,
        database_rebind_intent_sha256: $database_rebind_intent_sha256,
        transfer_database_sha256: $transfer_database_sha256,
        rebound_database_sha256: $rebound_database_sha256,
        prelaunch_database_sha256: $prelaunch_database_sha256,
        lexical_promotion_journal: $promotion_journal,
        promotion_recovery_receipt: $promotion_recovery_receipt,
        promotion_recovery_receipt_sha256: $promotion_recovery_receipt_sha256,
        promotion_recovery_state: $promotion_recovery_state,
        transfer_manifest: $transfer_manifest,
        transfer_manifest_sha256: $transfer_manifest_sha256,
        output_directory: $output,
        resume_staging_directory: $staging,
        stdout_log: $stdout,
        stderr_log: $stderr,
        command: $command,
        environment: {
            uv: $uv_version,
            python: $python_version,
            cloud_execution: true
        },
        limits: {
            process_memory_bytes: $maximum_memory_bytes,
            duckdb_memory_limit_bytes: $duckdb_memory_limit_bytes,
            computational_threads: $thread_count,
            duckdb_temp_directory: $duckdb_temp_directory,
            systemd_memory_high_bytes: 53687091200,
            systemd_memory_max_bytes: 60129542144,
            runtime_max_seconds: 172800,
            restart: "no"
        }
    }' >"$metadata_tmp"
mv -f -- "$metadata_tmp" "$metadata_path"
cp -- "$metadata_path" "${latest_path}.writing-$$"
mv -f -- "${latest_path}.writing-$$" "$latest_path"
ln -sfn -- "$(basename -- "$stdout_path")" "$ECHOES_LOG_ROOT/latest.stdout.log"
ln -sfn -- "$(basename -- "$stderr_path")" "$ECHOES_LOG_ROOT/latest.stderr.log"

cd -- "$ECHOES_REPO_ROOT"
exec "${command[@]}" >>"$stdout_path" 2>>"$stderr_path"
WORKER
chown root:"$SERVICE_GROUP" "$WORKER_TMP"
chmod 0750 "$WORKER_TMP"
mv -f -- "$WORKER_TMP" "$WORKER_PATH"

UNIT_TMP="${UNIT_PATH}.writing-$$"
cat >"$UNIT_TMP" <<EOF
[Unit]
Description=Project Echoes Milestone 7 lexical baseline (resumed first cloud run)
Documentation=file://$REPO_ROOT/cloud/README.md
After=local-fs.target
RequiresMountsFor=$REPO_ROOT $STATE_ROOT $TEMP_ROOT $LOG_ROOT /var/cache/project-echoes
ConditionPathExists=$ENV_FILE
ConditionPathExists=$STAGING_PATH/.resume-primary-candidates/complete.json

[Service]
Type=exec
User=$SERVICE_USER
Group=$SERVICE_GROUP
WorkingDirectory=$REPO_ROOT
EnvironmentFile=$ENV_FILE
ExecStart=$WORKER_PATH
Restart=no
RuntimeMaxSec=48h
TimeoutStopSec=10min
KillSignal=SIGINT
KillMode=control-group
SendSIGKILL=yes
OOMPolicy=stop
MemoryAccounting=yes
MemoryHigh=50G
MemoryMax=56G
MemorySwapMax=0
CPUAccounting=yes
TasksAccounting=yes
TasksMax=64
RuntimeDirectory=project-echoes
RuntimeDirectoryMode=0750
UMask=0077
NoNewPrivileges=yes
PrivateDevices=yes
PrivateTmp=yes
ProtectClock=yes
ProtectControlGroups=yes
ProtectHome=yes
ProtectHostname=yes
ProtectKernelLogs=yes
ProtectKernelModules=yes
ProtectKernelTunables=yes
ProtectSystem=strict
ReadWritePaths=$REPO_ROOT/data $REPO_ROOT/outputs $STATE_ROOT $TEMP_ROOT $LOG_ROOT $PACKAGE_ROOT /var/cache/project-echoes
RestrictRealtime=yes
LockPersonality=yes
StandardOutput=journal
StandardError=journal
SyslogIdentifier=echoes-m7

[Install]
WantedBy=multi-user.target
EOF
chown root:root "$UNIT_TMP"
chmod 0644 "$UNIT_TMP"
mv -f -- "$UNIT_TMP" "$UNIT_PATH"

systemctl daemon-reload
systemctl disable "$SERVICE_NAME" >/dev/null 2>&1 || true
systemctl reset-failed "$SERVICE_NAME" >/dev/null 2>&1 || true

printf 'Installed %s without starting it.\n' "$SERVICE_NAME"
printf 'Resume staging: %s\n' "$STAGING_PATH"
printf 'Launch only with: sudo bash %s/cloud/cloud_start.sh\n' "$REPO_ROOT"
