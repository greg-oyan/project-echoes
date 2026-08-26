#!/usr/bin/env bash
set -Eeuo pipefail

readonly UV_VERSION="0.11.28"
readonly SERVICE_USER="echoes"
readonly SERVICE_GROUP="echoes"
readonly REPO_URL="https://github.com/greg-oyan/project-echoes.git"
readonly REPO_ROOT="/srv/project-echoes/repo"
readonly MODEL_ROOT="/srv/project-echoes/models/intfloat-multilingual-e5-small-614241f622f5"
readonly STATE_ROOT="/var/lib/project-echoes/final-discovery/bootstrap"
readonly MINIMUM_FREE_BYTES=$((300 * 1024 * 1024 * 1024))

usage() {
    cat <<'EOF'
Usage: bootstrap_final_discovery_scaleway.sh \
  (--preflight-only | --execute) \
  --expected-commit FULL_SHA \
  --expected-host-fingerprint SHA256:VALUE

Run as root on the owner-created Scaleway POP2-16C-64G instance. The script is
idempotent, never provisions or deletes cloud resources, and refuses to change
scientific configuration. Preflight performs no package installation, clone,
project sync, or model download.
EOF
}

fail() {
    printf 'final-discovery bootstrap refused: %s\n' "$1" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "required command is unavailable: $1"
}

MODE=""
EXPECTED_COMMIT=""
EXPECTED_HOST_FINGERPRINT=""
while (($#)); do
    case "$1" in
        --preflight-only)
            [[ -z "$MODE" ]] || fail "select exactly one bootstrap mode"
            MODE="preflight"
            shift
            ;;
        --execute)
            [[ -z "$MODE" ]] || fail "select exactly one bootstrap mode"
            MODE="execute"
            shift
            ;;
        --expected-commit)
            (($# >= 2)) || fail "--expected-commit requires a value"
            EXPECTED_COMMIT="${2,,}"
            shift 2
            ;;
        --expected-host-fingerprint)
            (($# >= 2)) || fail "--expected-host-fingerprint requires a value"
            EXPECTED_HOST_FINGERPRINT="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage >&2
            fail "unknown argument: $1"
            ;;
    esac
done

[[ $EUID -eq 0 ]] || fail "run as root"
[[ "$MODE" == preflight || "$MODE" == execute ]] || fail "select --preflight-only or --execute"
[[ "$EXPECTED_COMMIT" =~ ^[0-9a-f]{40}$ ]] || fail "expected commit must be one full lowercase SHA"
[[ "$EXPECTED_HOST_FINGERPRINT" =~ ^SHA256:[A-Za-z0-9+/]{43}$ ]] ||
    fail "expected SSH host fingerprint is malformed"

for executable in awk curl df dpkg-query find getent git grep groupadd head id install mktemp \
    nproc python3.12 runuser sha256sum ssh-keygen stat tail tar tr uname useradd; do
    require_command "$executable"
done

source /etc/os-release
[[ "${ID-}" == ubuntu && "${VERSION_ID-}" == 24.04 ]] || fail "Ubuntu 24.04 is required"
[[ "$(uname -m)" == x86_64 ]] || fail "x86_64 is required"
[[ "$(nproc --all)" == 16 ]] || fail "exactly 16 visible vCPUs are required"
grep -qE 'AuthenticAMD|AMD EPYC' /proc/cpuinfo || fail "AMD CPU was not detected"
memory_bytes=$(( $(awk '/^MemTotal:/ {print $2}' /proc/meminfo) * 1024 ))
(( memory_bytes >= 60 * 1024 * 1024 * 1024 )) || fail "less than 60 GiB RAM is visible"
available_bytes="$(df -B1 --output=avail / | tail -n 1 | tr -d ' ')"
[[ "$available_bytes" =~ ^[0-9]+$ ]] || fail "could not measure available disk"
(( available_bytes >= MINIMUM_FREE_BYTES )) || fail "less than 300 GiB disk is available"

observed_fingerprint="$(ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256 | awk '{print $2}')"
[[ "$observed_fingerprint" == "$EXPECTED_HOST_FINGERPRINT" ]] ||
    fail "SSH host fingerprint differs: $observed_fingerprint"

remote_main="$(git ls-remote --exit-code "$REPO_URL" refs/heads/main | awk 'NR == 1 {print tolower($1)}')"
[[ "$remote_main" == "$EXPECTED_COMMIT" ]] ||
    fail "origin/main differs: expected=$EXPECTED_COMMIT observed=${remote_main:-missing}"

required_packages=(
    build-essential
    ca-certificates
    curl
    git
    jq
    openssh-client
    python3.12
    python3.12-venv
    rclone
    rsync
    util-linux
    zstd
)
missing_packages=()
for package in "${required_packages[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q '^install ok installed$'; then
        missing_packages+=("$package")
    fi
done

if [[ -x /usr/local/bin/uv ]]; then
    observed_uv_version="$(/usr/local/bin/uv -V | awk 'NR == 1 {print $2}')"
else
    observed_uv_version="missing"
fi
python_version="$(python3.12 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
[[ "$python_version" == 3.12 ]] || fail "Python 3.12 is required"

# Confirm that the exact pinned model revision is reachable before the execute
# phase is detached. This downloads no model body.
model_probe_url="https://huggingface.co/intfloat/multilingual-e5-small/resolve/614241f622f53c4eeff9890bdc4f31cfecc418b3/config.json"
curl --proto '=https' --tlsv1.2 --fail --location --head --retry 3 --max-time 30 \
    "$model_probe_url" >/dev/null

printf 'HOST_VERIFIED fingerprint=%s\n' "$observed_fingerprint"
printf 'REMOTE_COMMIT_VERIFIED commit=%s\n' "$remote_main"
printf 'PYTHON_VERIFIED version=%s\n' "$python_version"
printf 'UV_OBSERVED version=%s\n' "$observed_uv_version"
printf 'PACKAGES_MISSING count=%s' "${#missing_packages[@]}"
if ((${#missing_packages[@]})); then
    printf ' names=%s' "${missing_packages[*]}"
fi
printf '\nDISK_AVAILABLE_BYTES=%s\n' "$available_bytes"
printf 'MODEL_ENDPOINT_VERIFIED\n'

if [[ "$MODE" == preflight ]]; then
    printf 'PREFLIGHT_COMPLETE\n'
    exit 0
fi

export DEBIAN_FRONTEND=noninteractive
if ((${#missing_packages[@]})); then
    apt-get update
    apt-get install -y --no-install-recommends "${missing_packages[@]}"
    apt-get clean
fi

if [[ "$observed_uv_version" != "$UV_VERSION" ]]; then
    temporary_uv="$(mktemp -d)"
    cleanup_temporary_uv() {
        rm -rf -- "$temporary_uv"
    }
    trap cleanup_temporary_uv EXIT
    curl --proto '=https' --tlsv1.2 --fail --location --retry 5 \
        "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-x86_64-unknown-linux-gnu.tar.gz" \
        --output "$temporary_uv/uv.tar.gz"
    tar -xzf "$temporary_uv/uv.tar.gz" -C "$temporary_uv"
    uv_binary="$(find "$temporary_uv" -type f -name uv -perm -u+x | head -n 1)"
    [[ -n "$uv_binary" ]] || fail "uv binary was not found in the release archive"
    install -m 0755 "$uv_binary" /usr/local/bin/uv
    cleanup_temporary_uv
    trap - EXIT
fi
observed_uv_version="$(/usr/local/bin/uv -V | awk 'NR == 1 {print $2}')"
[[ "$observed_uv_version" == "$UV_VERSION" ]] ||
    fail "uv version differs: expected=$UV_VERSION observed=$observed_uv_version"

getent group "$SERVICE_GROUP" >/dev/null || groupadd --system "$SERVICE_GROUP"
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --gid "$SERVICE_GROUP" --home-dir /var/lib/project-echoes \
        --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_GROUP" \
    /srv/project-echoes \
    /srv/project-echoes/inputs/final-discovery \
    /srv/project-echoes/final-discovery/work \
    /srv/project-echoes/models \
    /var/lib/project-echoes \
    /var/lib/project-echoes/uv-cache \
    /var/lib/project-echoes/hf-cache
install -d -m 0700 -o root -g root "$STATE_ROOT"

if [[ ! -d "$REPO_ROOT/.git" ]]; then
    [[ ! -e "$REPO_ROOT" ]] || fail "repository path exists without a Git repository"
    runuser -u "$SERVICE_USER" -- git clone --filter=blob:none --no-checkout "$REPO_URL" "$REPO_ROOT"
else
    observed_origin="$(runuser -u "$SERVICE_USER" -- git -C "$REPO_ROOT" remote get-url origin)"
    [[ "$observed_origin" == "$REPO_URL" ]] || fail "repository origin differs: $observed_origin"
fi
runuser -u "$SERVICE_USER" -- git -C "$REPO_ROOT" fetch --prune origin main
runuser -u "$SERVICE_USER" -- git -C "$REPO_ROOT" checkout --detach "$EXPECTED_COMMIT"
[[ "$(runuser -u "$SERVICE_USER" -- git -C "$REPO_ROOT" rev-parse HEAD)" == "$EXPECTED_COMMIT" ]] ||
    fail "checked-out commit differs"
[[ -z "$(runuser -u "$SERVICE_USER" -- git -C "$REPO_ROOT" status --porcelain=v1 --untracked-files=all)" ]] ||
    fail "repository is not clean"

runuser -u "$SERVICE_USER" -- env HOME=/var/lib/project-echoes \
    UV_CACHE_DIR=/var/lib/project-echoes/uv-cache \
    bash -c 'cd "$1" && exec /usr/local/bin/uv sync --locked --all-groups --python /usr/bin/python3.12' \
    bash "$REPO_ROOT"

install -d -m 0700 -o "$SERVICE_USER" -g "$SERVICE_GROUP" "$MODEL_ROOT"
runuser -u "$SERVICE_USER" -- env HOME=/var/lib/project-echoes \
    HF_HOME=/var/lib/project-echoes/hf-cache \
    UV_CACHE_DIR=/var/lib/project-echoes/uv-cache \
    bash -c 'cd "$1" && exec /usr/local/bin/uv run --frozen --no-sync python - "$2" "$3"' \
    bash "$REPO_ROOT" "$MODEL_ROOT" /var/lib/project-echoes/hf-cache <<'PY'
from __future__ import annotations

import hashlib
import os
import shutil
import sys
from pathlib import Path

from huggingface_hub import hf_hub_download

from echoes.final_discovery.config import load_final_discovery_config
from echoes.final_discovery.semantic import verify_model_artifacts

model_root = Path(sys.argv[1])
cache_root = Path(sys.argv[2])
config = load_final_discovery_config(Path("config/experiments/final-discovery-v1.yaml"))
model = config.embedding_model


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


for relative_name, expected_hash in sorted(model.allowed_files.items()):
    destination = model_root / relative_name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and sha256(destination) == expected_hash:
        continue
    if destination.exists():
        raise SystemExit(f"existing model path has wrong identity: {destination}")
    downloaded = Path(
        hf_hub_download(
            repo_id=model.model_id,
            revision=model.revision,
            filename=relative_name,
            cache_dir=cache_root,
        )
    )
    temporary = destination.with_name(f".{destination.name}.writing-{os.getpid()}")
    shutil.copyfile(downloaded, temporary)
    if sha256(temporary) != expected_hash:
        temporary.unlink(missing_ok=True)
        raise SystemExit(f"downloaded model file failed SHA-256: {relative_name}")
    os.replace(temporary, destination)

verify_model_artifacts(model_root, model)
print(f"MODEL_VERIFIED files={len(model.allowed_files)}")
PY

runuser -u "$SERVICE_USER" -- env HOME=/var/lib/project-echoes \
    UV_CACHE_DIR=/var/lib/project-echoes/uv-cache \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
    bash -c 'cd "$1" && /usr/local/bin/uv run --frozen --no-sync echoes validate-config && /usr/local/bin/uv run --frozen --no-sync echoes validate-final-discovery-model-runtime --json' \
    bash "$REPO_ROOT"
runuser -u "$SERVICE_USER" -- rclone version >/dev/null

receipt_staging="$STATE_ROOT/.bootstrap-receipt.json.$$.tmp"
python3.12 - "$receipt_staging" "$EXPECTED_COMMIT" "$observed_fingerprint" "$observed_uv_version" "$MODEL_ROOT" <<'PY'
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

output, commit, fingerprint, uv_version, model_root = sys.argv[1:]
payload = {
    "schema_version": 1,
    "completed_at_utc": datetime.now(UTC).isoformat(),
    "git_commit": commit,
    "ssh_host_fingerprint": fingerprint,
    "uv_version": uv_version,
    "python_version": "3.12",
    "model_root": model_root,
    "passed": True,
}
Path(output).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
install -m 0400 -o root -g root "$receipt_staging" "$STATE_ROOT/bootstrap-receipt.json"
rm -f -- "$receipt_staging"

printf 'BOOTSTRAP_COMPLETE\n'
printf 'COMMIT=%s\n' "$EXPECTED_COMMIT"
printf 'UV=%s\n' "$observed_uv_version"
printf 'MODEL_ROOT=%s\n' "$MODEL_ROOT"
df -h /
