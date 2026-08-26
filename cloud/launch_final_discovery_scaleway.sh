#!/usr/bin/env bash
set -Eeuo pipefail

# Provider adapter for the frozen final-discovery-v1 launcher.
#
# The scientific campaign, detector/null/tier contracts, config hashes, B2
# contracts, memory/CPU/disk ceilings, systemd isolation, and launch-intent
# machinery remain owned by cloud/launch_final_discovery.sh. This wrapper
# changes only the reviewed Scaleway provider identity plus the separately
# authorized 68-hour operational stop required to preserve the USD 75 cap at
# the reviewed Scaleway rate. It does not change any scientific configuration.

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

require_source_occurrence() {
    local literal="$1"
    local expected_count="$2"
    local observed_count
    observed_count="$(grep -F -c -- "$literal" "$SOURCE_LAUNCHER" || true)"
    [[ "$observed_count" == "$expected_count" ]] || {
        printf 'Scaleway adapter source contract drifted: expected %s occurrence(s) of %s, observed %s.\n' \
            "$expected_count" "$literal" "$observed_count" >&2
        exit 1
    }
}

# Every substitution is pinned to one exact upstream occurrence. If the
# reviewed launcher changes, this adapter refuses to execute rather than
# silently producing a partially adapted launcher.
require_source_occurrence 'require_exact ECHOES_EXPECTED_SERVER_TYPE CCX43' 1
require_source_occurrence 'require_exact ECHOES_SERVER_NAME project-echoes-final-discovery-v1' 1
require_source_occurrence 'require_exact ECHOES_FINAL_DISCOVERY_RUNTIME_HOURS 96' 1
require_source_occurrence 'worker_hours = Decimal("96")' 1
require_source_occurrence '"maximum_worker_hours": 96,' 1
require_source_occurrence '--property=RuntimeMaxSec=96h' 1
require_source_occurrence 'CCX43 / Ubuntu 24.04 / 16 dedicated AMD vCPU / 64 GB / 360 GB SSD' 1

adapter="$(mktemp /run/project-echoes-final-discovery-scaleway.XXXXXX)"
cleanup() {
    rm -f -- "$adapter"
}
trap cleanup EXIT

sed \
    -e 's/require_exact ECHOES_EXPECTED_SERVER_TYPE CCX43/require_exact ECHOES_EXPECTED_SERVER_TYPE POP2-16C-64G/' \
    -e 's/require_exact ECHOES_SERVER_NAME project-echoes-final-discovery-v1/require_exact ECHOES_SERVER_NAME project-echoes-final-discovery/' \
    -e 's/require_exact ECHOES_FINAL_DISCOVERY_RUNTIME_HOURS 96/require_exact ECHOES_FINAL_DISCOVERY_RUNTIME_HOURS 68/' \
    -e 's/worker_hours = Decimal("96")/worker_hours = Decimal("68")/' \
    -e 's/"maximum_worker_hours": 96,/"maximum_worker_hours": 68,/' \
    -e 's/--property=RuntimeMaxSec=96h/--property=RuntimeMaxSec=68h/' \
    -e 's/CCX43 contract requires exactly 16 visible vCPUs/production contract requires exactly 16 visible vCPUs/' \
    -e 's/CCX43 contract requires AMD CPUs/production contract requires AMD CPUs/' \
    -e 's/CCX43 contract requires a host advertised with 64 GB RAM/production contract requires a host advertised with 64 GB RAM/' \
    -e 's#CCX43 / Ubuntu 24.04 / 16 dedicated AMD vCPU / 64 GB / 360 GB SSD#Scaleway POP2-16C-64G / Ubuntu 24.04 / 16 dedicated AMD vCPU / 64 GB / 400 GB Block Storage 5K#' \
    "$SOURCE_LAUNCHER" > "$adapter"
chmod 0700 "$adapter"

# Fail closed if any required binding is absent after adaptation.
for expected in \
    'require_exact ECHOES_EXPECTED_SERVER_TYPE POP2-16C-64G' \
    'require_exact ECHOES_SERVER_NAME project-echoes-final-discovery' \
    'require_exact ECHOES_FINAL_DISCOVERY_RUNTIME_HOURS 68' \
    'worker_hours = Decimal("68")' \
    '"maximum_worker_hours": 68,' \
    '--property=RuntimeMaxSec=68h' \
    'Scaleway POP2-16C-64G / Ubuntu 24.04 / 16 dedicated AMD vCPU / 64 GB / 400 GB Block Storage 5K'; do
    grep -F -q -- "$expected" "$adapter" || {
        printf 'Scaleway adapter could not bind required contract: %s\n' "$expected" >&2
        exit 1
    }
done

exec bash "$adapter" "$@" "$@" "$@" "$@" "$@"
