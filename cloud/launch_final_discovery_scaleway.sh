#!/usr/bin/env bash
set -Eeuo pipefail

# Provider adapter for the frozen final-discovery-v1 launcher.
#
# The scientific campaign, resource ceilings, config hashes, B2 contracts,
# systemd isolation, and launch-intent machinery remain owned by
# cloud/launch_final_discovery.sh. This wrapper changes only the reviewed
# provider identity strings needed for the owner-created Scaleway host.

readonly REPO_ROOT="/srv/project-echoes/repo"
readonly SOURCE_LAUNCHER="$REPO_ROOT/cloud/launch_final_discovery.sh"

[[ $EUID -eq 0 ]] || {
    printf 'Scaleway adapter must be run with sudo/root.\n' >&2
    exit 1
}
[[ -f "$SOURCE_LAUNCHER" && ! -L "$SOURCE_LAUNCHER" ]] || {
    printf 'Frozen launcher is missing or unsafe: %s\n' "$SOURCE_LAUNCHER" >&2
    exit 1
}

adapter="$(mktemp /run/project-echoes-final-discovery-scaleway.XXXXXX)"
cleanup() {
    rm -f -- "$adapter"
}
trap cleanup EXIT

sed \
    -e 's/require_exact ECHOES_EXPECTED_SERVER_TYPE CCX43/require_exact ECHOES_EXPECTED_SERVER_TYPE POP2-16C-64G/' \
    -e 's/require_exact ECHOES_SERVER_NAME project-echoes-final-discovery-v1/require_exact ECHOES_SERVER_NAME project-echoes-final-discovery/' \
    -e 's/CCX43 contract requires exactly 16 visible vCPUs/production contract requires exactly 16 visible vCPUs/' \
    -e 's/CCX43 contract requires AMD CPUs/production contract requires AMD CPUs/' \
    -e 's/CCX43 contract requires a host advertised with 64 GB RAM/production contract requires a host advertised with 64 GB RAM/' \
    -e 's#CCX43 / Ubuntu 24.04 / 16 dedicated AMD vCPU / 64 GB / 360 GB SSD#Scaleway POP2-16C-64G / Ubuntu 24.04 / 16 dedicated AMD vCPU / 64 GB / 400 GB Block Storage 5K#' \
    "$SOURCE_LAUNCHER" > "$adapter"
chmod 0700 "$adapter"

# Fail closed if an upstream edit makes any required substitution stop matching.
grep -q 'require_exact ECHOES_EXPECTED_SERVER_TYPE POP2-16C-64G' "$adapter" || {
    printf 'Scaleway adapter could not bind the expected server type.\n' >&2
    exit 1
}
grep -q 'require_exact ECHOES_SERVER_NAME project-echoes-final-discovery' "$adapter" || {
    printf 'Scaleway adapter could not bind the expected server name.\n' >&2
    exit 1
}
grep -q 'Scaleway POP2-16C-64G / Ubuntu 24.04 / 16 dedicated AMD vCPU / 64 GB / 400 GB Block Storage 5K' "$adapter" || {
    printf 'Scaleway adapter could not bind the reviewed resource description.\n' >&2
    exit 1
}

exec bash "$adapter"
