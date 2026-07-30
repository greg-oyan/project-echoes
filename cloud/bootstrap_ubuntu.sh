#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
    cat <<'EOF'
Usage: bootstrap_ubuntu.sh \
  --expected-branch BRANCH \
  --expected-commit FULL_SHA \
  [--repo-root /srv/project-echoes/repo] \
  [--manifest /srv/project-echoes/repo/cloud/transfer-manifest.json]

Run as root on a manually provisioned Ubuntu 24.04 x86_64 server. This script
does not create, purchase, connect to, or destroy cloud resources.
EOF
}

REPO_ROOT="/srv/project-echoes/repo"
MANIFEST_PATH=""
EXPECTED_BRANCH=""
EXPECTED_COMMIT=""
UV_VERSION="0.11.28"
MINIMUM_FREE_BYTES=$((250 * 1024 * 1024 * 1024))
SERVICE_USER="echoes"
SERVICE_GROUP="echoes"
STATE_ROOT="/var/lib/project-echoes/m7"

while (($#)); do
    case "$1" in
        --repo-root)
            (($# >= 2)) || { usage >&2; exit 2; }
            REPO_ROOT="$2"
            shift 2
            ;;
        --manifest)
            (($# >= 2)) || { usage >&2; exit 2; }
            MANIFEST_PATH="$2"
            shift 2
            ;;
        --expected-branch)
            (($# >= 2)) || { usage >&2; exit 2; }
            EXPECTED_BRANCH="$2"
            shift 2
            ;;
        --expected-commit)
            (($# >= 2)) || { usage >&2; exit 2; }
            EXPECTED_COMMIT="${2,,}"
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
    printf 'bootstrap_ubuntu.sh must run as root (use sudo).\n' >&2
    exit 1
fi
[[ "$REPO_ROOT" =~ ^/[A-Za-z0-9._/-]+$ && "$REPO_ROOT" != *".."* ]] || {
    printf 'Unsafe repository root: %s\n' "$REPO_ROOT" >&2
    exit 1
}
[[ "$EXPECTED_BRANCH" =~ ^[A-Za-z0-9._/-]+$ && "$EXPECTED_BRANCH" != *".."* ]] || {
    printf 'A safe --expected-branch is required.\n' >&2
    exit 1
}
[[ "$EXPECTED_COMMIT" =~ ^[0-9a-f]{40}$ ]] || {
    printf 'A full 40-character --expected-commit is required.\n' >&2
    exit 1
}
if [[ -z "$MANIFEST_PATH" ]]; then
    MANIFEST_PATH="$REPO_ROOT/cloud/transfer-manifest.json"
fi
[[ "$MANIFEST_PATH" =~ ^/[A-Za-z0-9._/-]+$ && "$MANIFEST_PATH" != *".."* ]] || {
    printf 'Unsafe transfer-manifest path: %s\n' "$MANIFEST_PATH" >&2
    exit 1
}

if [[ ! -r /etc/os-release ]]; then
    printf 'Cannot identify the operating system.\n' >&2
    exit 1
fi
# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "24.04" ]]; then
    printf 'Ubuntu 24.04 is required; observed ID=%s VERSION_ID=%s.\n' \
        "${ID:-unknown}" "${VERSION_ID:-unknown}" >&2
    exit 1
fi
if [[ "$(uname -m)" != "x86_64" ]]; then
    printf 'The governed CCX43 target is x86_64; observed %s.\n' "$(uname -m)" >&2
    exit 1
fi
if [[ ! -d "$REPO_ROOT/.git" || ! -f "$REPO_ROOT/docs/master-plan.md" ]]; then
    printf 'Repository is absent or incomplete at %s.\n' "$REPO_ROOT" >&2
    exit 1
fi
if systemctl is-active --quiet echoes-m7.service 2>/dev/null; then
    printf 'Refusing bootstrap while echoes-m7.service is active.\n' >&2
    exit 1
fi

CURRENT_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)"
CURRENT_BRANCH="$(git -C "$REPO_ROOT" branch --show-current)"
if [[ "${CURRENT_COMMIT,,}" != "$EXPECTED_COMMIT" ]]; then
    printf 'Commit mismatch: expected=%s observed=%s.\n' "$EXPECTED_COMMIT" "$CURRENT_COMMIT" >&2
    exit 1
fi
if [[ "$CURRENT_BRANCH" != "$EXPECTED_BRANCH" ]]; then
    printf 'Branch mismatch: expected=%s observed=%s.\n' "$EXPECTED_BRANCH" "$CURRENT_BRANCH" >&2
    exit 1
fi
if ! git -C "$REPO_ROOT" diff --quiet --ignore-submodules -- ||
    ! git -C "$REPO_ROOT" diff --cached --quiet --ignore-submodules --; then
    printf 'Tracked repository content is dirty; refusing bootstrap.\n' >&2
    exit 1
fi

REMOTE_SHA="$(
    git -C "$REPO_ROOT" ls-remote --exit-code origin "refs/heads/$EXPECTED_BRANCH" |
        awk 'NR == 1 {print tolower($1)}'
)"
if [[ "$REMOTE_SHA" != "$EXPECTED_COMMIT" ]]; then
    printf 'The expected commit is not the current remote branch tip: expected=%s remote=%s.\n' \
        "$EXPECTED_COMMIT" "${REMOTE_SHA:-missing}" >&2
    exit 1
fi

AVAILABLE_BYTES="$(df -PB1 "$REPO_ROOT" | awk 'NR == 2 {print $4}')"
if [[ ! "$AVAILABLE_BYTES" =~ ^[0-9]+$ ]] || ((AVAILABLE_BYTES < MINIMUM_FREE_BYTES)); then
    printf 'At least %s free bytes are required before bootstrap; observed %s.\n' \
        "$MINIMUM_FREE_BYTES" "${AVAILABLE_BYTES:-unknown}" >&2
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    jq \
    procps \
    python3-minimal \
    util-linux \
    zstd
apt-get clean

DATABASE_PATH="$REPO_ROOT/data/processed/project_echoes.duckdb"
PASSAGE_ROOT="$REPO_ROOT/data/processed/passages/schema-v1"
REBIND_RECEIPT="$STATE_ROOT/passage-view-rebind.json"
REBIND_INDEX="$STATE_ROOT/database-rebind.json"
MANIFEST_DATABASE_JSON="$(
    python3 - "$MANIFEST_PATH" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    payload = json.load(stream)
entries = payload.get("files", payload.get("entries", []))
matches = []
for entry in entries:
    path = entry.get("path", entry.get("relative_path"))
    if path == "data/processed/project_echoes.duckdb":
        matches.append(
            {
                "path": path,
                "size_bytes": entry.get("size_bytes", entry.get("byte_size")),
                "sha256": entry.get("sha256"),
            }
        )
if len(matches) != 1:
    raise SystemExit("transfer manifest must name the project database exactly once")
print(json.dumps(matches[0], sort_keys=True))
PY
)"
ORIGINAL_DATABASE_SHA256="$(jq -r '.sha256' <<<"$MANIFEST_DATABASE_JSON")"
ORIGINAL_DATABASE_SIZE="$(jq -r '.size_bytes' <<<"$MANIFEST_DATABASE_JSON")"
if [[ ! "$ORIGINAL_DATABASE_SHA256" =~ ^[0-9a-f]{64}$ ||
    ! "$ORIGINAL_DATABASE_SIZE" =~ ^[0-9]+$ ]]; then
    printf 'Transfer manifest project-database identity is malformed.\n' >&2
    exit 1
fi
ACTIVE_REBIND_RECEIPT=""
VERIFY_REBIND_ARGUMENTS=()
if [[ -e "$REBIND_INDEX" || -L "$REBIND_INDEX" ]]; then
    CURRENT_DATABASE_SHA256="$(
        sha256sum "$DATABASE_PATH" | awk '{print $1}'
    )"
    if [[ ! -f "$REBIND_INDEX" || -L "$REBIND_INDEX" ]] ||
        ! jq -e '
            .schema_version == 1 and
            .passed == true and
            (.commit | type == "string") and
            (.transfer_manifest_sha256 | type == "string") and
            (.governed_receipt_path | type == "string") and
            (.governed_receipt_sha256 | type == "string") and
            (.governed_intent_path | type == "string") and
            (.governed_intent_sha256 | type == "string") and
            (.original_sha256 | type == "string") and
            (.rebound_sha256 | type == "string")
        ' "$REBIND_INDEX" >/dev/null; then
        printf 'Existing database-rebind index is missing, unsafe, or malformed.\n' >&2
        exit 1
    fi
    CURRENT_MANIFEST_SHA256="$(sha256sum "$MANIFEST_PATH" | awk '{print $1}')"
    RECEIPT_MANIFEST_SHA256="$(jq -r '.transfer_manifest_sha256 // ""' "$REBIND_INDEX")"
    RECEIPT_COMMIT="$(jq -r '.commit // ""' "$REBIND_INDEX")"
    RECEIPT_REBOUND_SHA256="$(jq -r '.rebound_sha256 // ""' "$REBIND_INDEX")"
    RECEIPT_ORIGINAL_SHA256="$(jq -r '.original_sha256 // ""' "$REBIND_INDEX")"
    INDEXED_GOVERNED_RECEIPT="$(jq -r '.governed_receipt_path // ""' "$REBIND_INDEX")"
    INDEXED_GOVERNED_SHA256="$(jq -r '.governed_receipt_sha256 // ""' "$REBIND_INDEX")"
    INDEXED_GOVERNED_INTENT="$(jq -r '.governed_intent_path // ""' "$REBIND_INDEX")"
    INDEXED_GOVERNED_INTENT_SHA256="$(
        jq -r '.governed_intent_sha256 // ""' "$REBIND_INDEX"
    )"
    [[ "$INDEXED_GOVERNED_RECEIPT" =~ ^/var/lib/project-echoes/m7/passage-view-rebind(-[0-9TZ.-]+)?\.json$ &&
        "$INDEXED_GOVERNED_RECEIPT" != *".."* ]] || {
        printf 'Indexed passage-view-rebind receipt path is unsafe.\n' >&2
        exit 1
    }
    if [[ "$INDEXED_GOVERNED_INTENT" != "$INDEXED_GOVERNED_RECEIPT.intent.json" ||
        ! -f "$INDEXED_GOVERNED_RECEIPT" || -L "$INDEXED_GOVERNED_RECEIPT" ||
        "$(sha256sum "$INDEXED_GOVERNED_RECEIPT" | awk '{print $1}')" != "$INDEXED_GOVERNED_SHA256" ||
        ! -f "$INDEXED_GOVERNED_INTENT" || -L "$INDEXED_GOVERNED_INTENT" ||
        "$(sha256sum "$INDEXED_GOVERNED_INTENT" | awk '{print $1}')" != "$INDEXED_GOVERNED_INTENT_SHA256" ||
        "$(jq -r '.before_database_sha256 // ""' "$INDEXED_GOVERNED_RECEIPT")" != "$RECEIPT_ORIGINAL_SHA256" ||
        "$(jq -r '.after_database_sha256 // ""' "$INDEXED_GOVERNED_RECEIPT")" != "$RECEIPT_REBOUND_SHA256" ||
        "$(jq -r '.before_database_sha256 // ""' "$INDEXED_GOVERNED_INTENT")" != "$RECEIPT_ORIGINAL_SHA256" ]]; then
        printf 'Indexed passage-view-rebind receipt failed its integrity chain.\n' >&2
        exit 1
    fi
    if [[ "$CURRENT_MANIFEST_SHA256" == "$RECEIPT_MANIFEST_SHA256" &&
        "$EXPECTED_COMMIT" == "$RECEIPT_COMMIT" &&
        "$CURRENT_DATABASE_SHA256" == "$RECEIPT_REBOUND_SHA256" ]]; then
        ACTIVE_REBIND_RECEIPT="$INDEXED_GOVERNED_RECEIPT"
        VERIFY_REBIND_ARGUMENTS=(--rebind-receipt "$ACTIVE_REBIND_RECEIPT")
    fi
elif [[ -f "$REBIND_RECEIPT" && ! -L "$REBIND_RECEIPT" ]]; then
    CURRENT_DATABASE_SHA256="$(sha256sum "$DATABASE_PATH" | awk '{print $1}')"
    if [[ "$CURRENT_DATABASE_SHA256" == "$(jq -r '.after_database_sha256 // ""' "$REBIND_RECEIPT" 2>/dev/null)" ]]; then
        # Recover safely if a previous bootstrap committed the governed receipt
        # but was interrupted before writing its small manifest/commit index.
        ACTIVE_REBIND_RECEIPT="$REBIND_RECEIPT"
        VERIFY_REBIND_ARGUMENTS=(--rebind-receipt "$ACTIVE_REBIND_RECEIPT")
    fi
fi

if [[ -z "$ACTIVE_REBIND_RECEIPT" ]]; then
    CURRENT_DATABASE_SHA256="${CURRENT_DATABASE_SHA256:-$(
        sha256sum "$DATABASE_PATH" | awk '{print $1}'
    )}"
    if [[ "$CURRENT_DATABASE_SHA256" != "$ORIGINAL_DATABASE_SHA256" ]]; then
        RECOVERY_INTENTS=()
        shopt -s nullglob
        for candidate_intent in "$STATE_ROOT"/passage-view-rebind*.json.intent.json; do
            candidate_receipt="${candidate_intent%.intent.json}"
            if [[ -f "$candidate_intent" && ! -L "$candidate_intent" &&
                ! -e "$candidate_receipt" && ! -L "$candidate_receipt" &&
                "$candidate_receipt" =~ ^/var/lib/project-echoes/m7/passage-view-rebind(-[0-9TZ.-]+)?\.json$ &&
                "$(jq -r '.database_path // ""' "$candidate_intent" 2>/dev/null)" == "$DATABASE_PATH" &&
                "$(jq -r '.passage_root // ""' "$candidate_intent" 2>/dev/null)" == "$PASSAGE_ROOT" &&
                "$(jq -r '.before_database_sha256 // ""' "$candidate_intent" 2>/dev/null)" == "$ORIGINAL_DATABASE_SHA256" ]]; then
                RECOVERY_INTENTS+=("$candidate_intent")
            fi
        done
        shopt -u nullglob
        if ((${#RECOVERY_INTENTS[@]} != 1)); then
            printf 'Database is neither original nor indexed rebound state; found %s eligible recovery intents.\n' \
                "${#RECOVERY_INTENTS[@]}" >&2
            exit 1
        fi
        ACTIVE_REBIND_RECEIPT="${RECOVERY_INTENTS[0]%.intent.json}"
        if ! id "$SERVICE_USER" >/dev/null 2>&1 ||
            [[ ! -x /usr/local/bin/uv ||
                ! -d /var/lib/project-echoes/venv ]]; then
            printf 'A committed rebind needs recovery, but its pinned prior environment is unavailable.\n' >&2
            exit 1
        fi
        runuser -u "$SERVICE_USER" -- env \
            HOME=/var/lib/project-echoes \
            UV_CACHE_DIR=/var/cache/project-echoes/uv \
            UV_PYTHON_INSTALL_DIR=/var/lib/project-echoes/python \
            UV_PROJECT_ENVIRONMENT=/var/lib/project-echoes/venv \
            /usr/local/bin/uv run \
                --directory "$REPO_ROOT" \
                --frozen \
                --offline \
                --no-sync \
                echoes rebind-passage-views \
                    --database "$DATABASE_PATH" \
                    --passage-root "$PASSAGE_ROOT" \
                    --expected-database-sha256 "$ORIGINAL_DATABASE_SHA256" \
                    --receipt "$ACTIVE_REBIND_RECEIPT" \
                    --json >/dev/null
        VERIFY_REBIND_ARGUMENTS=(--rebind-receipt "$ACTIVE_REBIND_RECEIPT")
    fi
fi

bash "$REPO_ROOT/cloud/verify_transfer.sh" \
    --root "$REPO_ROOT" \
    --manifest "$MANIFEST_PATH" \
    "${VERIFY_REBIND_ARGUMENTS[@]}"

if ! getent group "$SERVICE_GROUP" >/dev/null; then
    groupadd --system "$SERVICE_GROUP"
fi
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    useradd \
        --system \
        --gid "$SERVICE_GROUP" \
        --home-dir /var/lib/project-echoes \
        --shell /usr/sbin/nologin \
        "$SERVICE_USER"
fi

install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 0750 \
    /var/lib/project-echoes \
    "$STATE_ROOT" \
    /var/lib/project-echoes/python \
    /var/lib/project-echoes/venv \
    /var/lib/project-echoes/tmp \
    /var/lib/project-echoes/tmp/duckdb \
    /var/cache/project-echoes \
    /var/cache/project-echoes/uv \
    /var/log/project-echoes \
    /var/log/project-echoes/m7 \
    /srv/project-echoes/packages
install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 0750 \
    "$REPO_ROOT/data" \
    "$REPO_ROOT/data/processed" \
    "$REPO_ROOT/data/interim" \
    "$REPO_ROOT/outputs"
chown -R "$SERVICE_USER:$SERVICE_GROUP" \
    "$REPO_ROOT/data" \
    "$REPO_ROOT/outputs"

curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" |
    env UV_UNMANAGED_INSTALL=/usr/local/bin sh
if [[ "$(/usr/local/bin/uv --version)" != "uv $UV_VERSION"* ]]; then
    printf 'Pinned uv installation failed; expected %s, observed %s.\n' \
        "$UV_VERSION" "$(/usr/local/bin/uv --version)" >&2
    exit 1
fi

runuser -u "$SERVICE_USER" -- env \
    HOME=/var/lib/project-echoes \
    UV_CACHE_DIR=/var/cache/project-echoes/uv \
    UV_PYTHON_INSTALL_DIR=/var/lib/project-echoes/python \
    UV_PROJECT_ENVIRONMENT=/var/lib/project-echoes/venv \
    /usr/local/bin/uv sync \
        --directory "$REPO_ROOT" \
        --frozen \
        --python 3.12

PORTABILITY_JSON="$(
    runuser -u "$SERVICE_USER" -- env \
        HOME=/var/lib/project-echoes \
        UV_CACHE_DIR=/var/cache/project-echoes/uv \
        UV_PYTHON_INSTALL_DIR=/var/lib/project-echoes/python \
        UV_PROJECT_ENVIRONMENT=/var/lib/project-echoes/venv \
        /usr/local/bin/uv run \
            --directory "$REPO_ROOT" \
            --frozen \
            --offline \
            --no-sync \
            python - "$REPO_ROOT/data/processed/project_echoes.duckdb" \
                /var/lib/project-echoes/tmp/duckdb <<'PY'
import json
import sys
from pathlib import Path

import duckdb

database = Path(sys.argv[1]).resolve()
spill = Path(sys.argv[2]).resolve()
if duckdb.__version__ != "1.5.4":
    raise SystemExit(f"pinned DuckDB mismatch: {duckdb.__version__}")
if not database.is_file() or database.is_symlink():
    raise SystemExit(f"transferred DuckDB database is missing or unsafe: {database}")
spill.mkdir(parents=True, exist_ok=True)
with duckdb.connect() as connection:
    connection.execute("SET memory_limit='48GiB'")
    connection.execute("SET threads=1")
    observed_limit, observed_threads = connection.execute(
        "SELECT current_setting('memory_limit'), current_setting('threads')"
    ).fetchone()
with duckdb.connect(str(database), read_only=True) as connection:
    database_version = connection.execute("SELECT version()").fetchone()[0]
    table_count = connection.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema='main'"
    ).fetchone()[0]
    sample = connection.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='main' ORDER BY table_name LIMIT 5"
    ).fetchall()
print(
    json.dumps(
        {
            "duckdb_python_version": duckdb.__version__,
            "database_engine_version": database_version,
            "database_table_count": table_count,
            "sample_tables": [row[0] for row in sample],
            "supports_48_gib_memory_limit": str(observed_limit) == "48.0 GiB",
            "observed_memory_limit": str(observed_limit),
            "observed_threads": int(observed_threads),
        },
        sort_keys=True,
    )
)
PY
)"
if [[ "$(jq -r '.supports_48_gib_memory_limit' <<<"$PORTABILITY_JSON")" != "true" ]]; then
    printf 'DuckDB did not retain the required 48 GiB setting: %s\n' "$PORTABILITY_JSON" >&2
    exit 1
fi

if [[ -z "$ACTIVE_REBIND_RECEIPT" ]]; then
    CURRENT_DATABASE_SHA256="$(sha256sum "$DATABASE_PATH" | awk '{print $1}')"
    CURRENT_DATABASE_SIZE="$(stat --format='%s' "$DATABASE_PATH")"
    if [[ "$CURRENT_DATABASE_SHA256" != "$ORIGINAL_DATABASE_SHA256" ||
        "$CURRENT_DATABASE_SIZE" != "$ORIGINAL_DATABASE_SIZE" ]]; then
        printf 'Original database identity differs from its verified transfer entry.\n' >&2
        exit 1
    fi
    if [[ -e "$REBIND_RECEIPT" || -L "$REBIND_RECEIPT" ]]; then
        ACTIVE_REBIND_RECEIPT="$(
            printf '/var/lib/project-echoes/m7/passage-view-rebind-%s.json' \
                "$(date -u +%Y%m%dT%H%M%S.%3NZ)"
        )"
    else
        ACTIVE_REBIND_RECEIPT="$REBIND_RECEIPT"
    fi
    if [[ -e "$ACTIVE_REBIND_RECEIPT" || -L "$ACTIVE_REBIND_RECEIPT" ]]; then
        printf 'Refusing to overwrite a preserved passage-view-rebind receipt: %s\n' \
            "$ACTIVE_REBIND_RECEIPT" >&2
        exit 1
    fi
    runuser -u "$SERVICE_USER" -- env \
        HOME=/var/lib/project-echoes \
        UV_CACHE_DIR=/var/cache/project-echoes/uv \
        UV_PYTHON_INSTALL_DIR=/var/lib/project-echoes/python \
        UV_PROJECT_ENVIRONMENT=/var/lib/project-echoes/venv \
        /usr/local/bin/uv run \
            --directory "$REPO_ROOT" \
            --frozen \
            --offline \
            --no-sync \
            echoes rebind-passage-views \
                --database "$DATABASE_PATH" \
                --passage-root "$PASSAGE_ROOT" \
                --expected-database-sha256 "$ORIGINAL_DATABASE_SHA256" \
                --receipt "$ACTIVE_REBIND_RECEIPT" \
                --json >/dev/null
fi

runuser -u "$SERVICE_USER" -- env \
    HOME=/var/lib/project-echoes \
    UV_CACHE_DIR=/var/cache/project-echoes/uv \
    UV_PYTHON_INSTALL_DIR=/var/lib/project-echoes/python \
    UV_PROJECT_ENVIRONMENT=/var/lib/project-echoes/venv \
    /usr/local/bin/uv run \
        --directory "$REPO_ROOT" \
        --frozen \
        --offline \
        --no-sync \
        echoes verify-passage-view-rebind \
            --database "$DATABASE_PATH" \
            --passage-root "$PASSAGE_ROOT" \
            --expected-before-database-sha256 "$ORIGINAL_DATABASE_SHA256" \
            --receipt "$ACTIVE_REBIND_RECEIPT" \
            --json >/dev/null

ACTIVE_REBIND_INTENT="$ACTIVE_REBIND_RECEIPT.intent.json"
if [[ ! -f "$ACTIVE_REBIND_INTENT" || -L "$ACTIVE_REBIND_INTENT" ]]; then
    printf 'Governed passage-view-rebind intent is missing or unsafe: %s\n' \
        "$ACTIVE_REBIND_INTENT" >&2
    exit 1
fi
chown root:"$SERVICE_GROUP" "$ACTIVE_REBIND_RECEIPT" "$ACTIVE_REBIND_INTENT"
chmod 0640 "$ACTIVE_REBIND_RECEIPT" "$ACTIVE_REBIND_INTENT"
REBIND_JSON="$(cat "$ACTIVE_REBIND_RECEIPT")"
REBIND_RECEIPT_SHA256="$(
    sha256sum "$ACTIVE_REBIND_RECEIPT" | awk '{print $1}'
)"
REBIND_INTENT_JSON="$(cat "$ACTIVE_REBIND_INTENT")"
REBIND_INTENT_SHA256="$(
    sha256sum "$ACTIVE_REBIND_INTENT" | awk '{print $1}'
)"
REBOUND_DATABASE_SHA256="$(jq -r '.after_database_sha256' <<<"$REBIND_JSON")"
REBOUND_DATABASE_SIZE="$(stat --format='%s' "$DATABASE_PATH")"
if [[ "$(sha256sum "$DATABASE_PATH" | awk '{print $1}')" != "$REBOUND_DATABASE_SHA256" ]]; then
    printf 'Rebound database differs from its governed receipt.\n' >&2
    exit 1
fi

CURRENT_MANIFEST_SHA256="$(sha256sum "$MANIFEST_PATH" | awk '{print $1}')"
INDEX_NEEDS_WRITE=1
if [[ -f "$REBIND_INDEX" && ! -L "$REBIND_INDEX" ]] &&
    [[ "$(jq -r '.commit // ""' "$REBIND_INDEX")" == "$EXPECTED_COMMIT" ]] &&
    [[ "$(jq -r '.transfer_manifest_sha256 // ""' "$REBIND_INDEX")" == "$CURRENT_MANIFEST_SHA256" ]] &&
    [[ "$(jq -r '.governed_receipt_path // ""' "$REBIND_INDEX")" == "$ACTIVE_REBIND_RECEIPT" ]] &&
    [[ "$(jq -r '.governed_receipt_sha256 // ""' "$REBIND_INDEX")" == "$REBIND_RECEIPT_SHA256" ]] &&
    [[ "$(jq -r '.governed_intent_path // ""' "$REBIND_INDEX")" == "$ACTIVE_REBIND_INTENT" ]] &&
    [[ "$(jq -r '.governed_intent_sha256 // ""' "$REBIND_INDEX")" == "$REBIND_INTENT_SHA256" ]]; then
    INDEX_NEEDS_WRITE=0
fi
if ((INDEX_NEEDS_WRITE)); then
    if [[ -f "$REBIND_INDEX" && ! -L "$REBIND_INDEX" ]]; then
        PRESERVED_INDEX="$STATE_ROOT/database-rebind-preserved-$(
            sha256sum "$REBIND_INDEX" | awk '{print $1}'
        ).json"
        if [[ ! -e "$PRESERVED_INDEX" && ! -L "$PRESERVED_INDEX" ]]; then
            install -o root -g "$SERVICE_GROUP" -m 0640 \
                "$REBIND_INDEX" "$PRESERVED_INDEX"
        fi
    fi
    REBIND_INDEX_TMP="${REBIND_INDEX}.writing-$$"
    jq -n \
        --arg rebound_at_utc "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        --arg commit "$EXPECTED_COMMIT" \
        --arg transfer_manifest "$MANIFEST_PATH" \
        --arg transfer_manifest_sha256 "$CURRENT_MANIFEST_SHA256" \
        --arg database_relative_path "data/processed/project_echoes.duckdb" \
        --arg governed_receipt_path "$ACTIVE_REBIND_RECEIPT" \
        --arg governed_receipt_sha256 "$REBIND_RECEIPT_SHA256" \
        --arg governed_intent_path "$ACTIVE_REBIND_INTENT" \
        --arg governed_intent_sha256 "$REBIND_INTENT_SHA256" \
        --arg original_sha256 "$ORIGINAL_DATABASE_SHA256" \
        --arg rebound_sha256 "$REBOUND_DATABASE_SHA256" \
        --argjson original_size_bytes "$ORIGINAL_DATABASE_SIZE" \
        --argjson rebound_size_bytes "$REBOUND_DATABASE_SIZE" \
        --argjson governed_receipt "$REBIND_JSON" \
        --argjson governed_intent "$REBIND_INTENT_JSON" \
        '{
            schema_version: 1,
            passed: true,
            rebound_at_utc: $rebound_at_utc,
            commit: $commit,
            transfer_manifest: $transfer_manifest,
            transfer_manifest_sha256: $transfer_manifest_sha256,
            database_relative_path: $database_relative_path,
            original_size_bytes: $original_size_bytes,
            original_sha256: $original_sha256,
            rebound_size_bytes: $rebound_size_bytes,
            rebound_sha256: $rebound_sha256,
            governed_receipt_path: $governed_receipt_path,
            governed_receipt_sha256: $governed_receipt_sha256,
            governed_intent_path: $governed_intent_path,
            governed_intent_sha256: $governed_intent_sha256,
            governed_receipt: $governed_receipt,
            governed_intent: $governed_intent
        }' >"$REBIND_INDEX_TMP"
    chown root:"$SERVICE_GROUP" "$REBIND_INDEX_TMP"
    chmod 0640 "$REBIND_INDEX_TMP"
    mv -f -- "$REBIND_INDEX_TMP" "$REBIND_INDEX"
fi
REBIND_INDEX_JSON="$(cat "$REBIND_INDEX")"

AVAILABLE_AFTER_BYTES="$(df -PB1 "$REPO_ROOT" | awk 'NR == 2 {print $4}')"
if [[ ! "$AVAILABLE_AFTER_BYTES" =~ ^[0-9]+$ ]] ||
    ((AVAILABLE_AFTER_BYTES < MINIMUM_FREE_BYTES)); then
    printf 'At least %s free bytes are required after environment setup; observed %s.\n' \
        "$MINIMUM_FREE_BYTES" "${AVAILABLE_AFTER_BYTES:-unknown}" >&2
    exit 1
fi

RECEIPT="/var/lib/project-echoes/m7/bootstrap-validation.json"
RECEIPT_TMP="${RECEIPT}.writing-$$"
jq -n \
    --arg validated_at_utc "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg repository_root "$REPO_ROOT" \
    --arg branch "$EXPECTED_BRANCH" \
    --arg commit "$EXPECTED_COMMIT" \
    --arg manifest "$MANIFEST_PATH" \
    --arg manifest_sha256 "$(sha256sum "$MANIFEST_PATH" | awk '{print $1}')" \
    --arg uv_version "$UV_VERSION" \
    --arg database_rebind_receipt "$ACTIVE_REBIND_RECEIPT" \
    --arg database_rebind_receipt_sha256 "$REBIND_RECEIPT_SHA256" \
    --arg database_rebind_intent "$ACTIVE_REBIND_INTENT" \
    --arg database_rebind_intent_sha256 "$REBIND_INTENT_SHA256" \
    --argjson free_bytes "$AVAILABLE_AFTER_BYTES" \
    --argjson portability "$PORTABILITY_JSON" \
    --argjson database_rebind "$REBIND_JSON" \
    --argjson database_rebind_intent_payload "$REBIND_INTENT_JSON" \
    --argjson database_rebind_index "$REBIND_INDEX_JSON" \
    '{
        schema_version: 1,
        passed: true,
        validated_at_utc: $validated_at_utc,
        repository_root: $repository_root,
        branch: $branch,
        commit: $commit,
        transfer_manifest: $manifest,
        transfer_manifest_sha256: $manifest_sha256,
        uv_version: $uv_version,
        free_bytes: $free_bytes,
        duckdb_portability: $portability,
        database_rebind_receipt: $database_rebind_receipt,
        database_rebind_receipt_sha256: $database_rebind_receipt_sha256,
        database_rebind_intent: $database_rebind_intent,
        database_rebind_intent_sha256: $database_rebind_intent_sha256,
        database_rebind: $database_rebind,
        database_rebind_intent_payload: $database_rebind_intent_payload,
        database_rebind_index: $database_rebind_index
    }' >"$RECEIPT_TMP"
chown root:"$SERVICE_GROUP" "$RECEIPT_TMP"
chmod 0640 "$RECEIPT_TMP"
if [[ -L "$RECEIPT" ]]; then
    printf 'Refusing to replace a symlinked bootstrap receipt: %s\n' "$RECEIPT" >&2
    exit 1
fi
if [[ -f "$RECEIPT" ]]; then
    PRESERVED_BOOTSTRAP="$STATE_ROOT/bootstrap-validation-preserved-$(
        sha256sum "$RECEIPT" | awk '{print $1}'
    ).json"
    if [[ ! -e "$PRESERVED_BOOTSTRAP" && ! -L "$PRESERVED_BOOTSTRAP" ]]; then
        install -o root -g "$SERVICE_GROUP" -m 0640 \
            "$RECEIPT" "$PRESERVED_BOOTSTRAP"
    fi
fi
mv -f -- "$RECEIPT_TMP" "$RECEIPT"

printf 'Bootstrap passed for %s at %s.\n' "$EXPECTED_BRANCH" "$EXPECTED_COMMIT"
printf 'Next: sudo bash %s/cloud/install_echoes_service.sh --repo-root %s\n' \
    "$REPO_ROOT" "$REPO_ROOT"
