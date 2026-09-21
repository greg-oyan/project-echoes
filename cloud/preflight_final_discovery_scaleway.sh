#!/usr/bin/env bash
set -Eeuo pipefail

readonly REPO_ROOT="/srv/project-echoes/repo"
readonly ADAPTER="$REPO_ROOT/cloud/launch_final_discovery_scaleway.sh"

usage() {
    printf 'Usage: sudo bash %s/cloud/preflight_final_discovery_scaleway.sh\n' "$REPO_ROOT"
}

if (($#)); then
    case "$1" in
        -h|--help)
            (($# == 1)) || { usage >&2; exit 2; }
            usage
            exit 0
            ;;
        *)
            usage >&2
            exit 2
            ;;
    esac
fi

[[ $EUID -eq 0 ]] || {
    printf 'Scaleway production preflight must run as root.\n' >&2
    exit 1
}
[[ -f "$ADAPTER" && ! -L "$ADAPTER" ]] || {
    printf 'Reviewed Scaleway adapter is absent or unsafe.\n' >&2
    exit 1
}
# Preflight returns its actual result without launching a worker or powering
# off for a recoverable preparation failure. The immutable recovery expiry
# remains responsible for shutdown while preparation is in progress.
bash "$ADAPTER" --preflight-only
