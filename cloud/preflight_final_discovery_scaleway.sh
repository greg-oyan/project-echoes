#!/usr/bin/env bash
set -Eeuo pipefail

readonly REPO_ROOT="/srv/project-echoes/repo"
readonly ADAPTER="$REPO_ROOT/cloud/launch_final_discovery_scaleway.sh"
readonly POWER_OFF_GUARD="$REPO_ROOT/cloud/scaleway_poweroff_guard.sh"

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
[[ -f "$POWER_OFF_GUARD" && ! -L "$POWER_OFF_GUARD" ]] || {
    printf 'Reviewed Scaleway poweroff guard is absent or unsafe.\n' >&2
    exit 1
}

# Whether preflight passes or refuses, request a true provider-side poweroff so
# an idle validation server cannot continue billing. Preserve the preflight
# result unless the cost guard itself fails.
preflight_status=0
bash "$ADAPTER" --preflight-only || preflight_status=$?

poweroff_status=0
bash "$POWER_OFF_GUARD" --poweroff || poweroff_status=$?
if (( poweroff_status != 0 )); then
    printf 'Scaleway preflight finished, but automatic provider poweroff failed.\n' >&2
    exit 1
fi
printf 'SCALEWAY_PREFLIGHT_POWERDOWN_REQUESTED\n'
exit "$preflight_status"
