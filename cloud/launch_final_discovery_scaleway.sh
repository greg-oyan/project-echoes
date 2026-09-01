#!/usr/bin/env bash
set -Eeuo pipefail

# Provider adapter for the frozen final-discovery-v1 launcher.
#
# The scientific campaign, detector/null/tier contracts, config hashes, B2
# contracts, memory/CPU/disk ceilings, systemd isolation, and launch-intent
# machinery remain owned by cloud/launch_final_discovery.sh. This wrapper
# changes only the reviewed Scaleway provider identity, the owner-authorized
# USD 125 all-in budget ceiling, and provider-side auto-poweroff around every
# production boundary. It deliberately retains the frozen 96-hour worker
# window to maximize the probability that the campaign completes. It does not
# change any scientific configuration.

readonly REPO_ROOT="/srv/project-echoes/repo"
readonly SOURCE_LAUNCHER="$REPO_ROOT/cloud/launch_final_discovery.sh"
readonly POWER_OFF_GUARD="$REPO_ROOT/cloud/scaleway_poweroff_guard.sh"
readonly POWER_OFF_ENV="/etc/project-echoes/scaleway-poweroff.env"
readonly POWER_OFF_UNIT="echoes-final-discovery-poweroff.service"

[[ $EUID -eq 0 ]] || {
    printf 'Scaleway adapter must be run with sudo/root.\n' >&2
    exit 1
}
for executable in grep mktemp sed python3 systemctl bash stat; do
    command -v "$executable" >/dev/null 2>&1 || {
        printf 'Scaleway adapter requires command: %s\n' "$executable" >&2
        exit 1
    }
done
[[ -f "$SOURCE_LAUNCHER" && ! -L "$SOURCE_LAUNCHER" ]] || {
    printf 'Frozen launcher is missing or unsafe: %s\n' "$SOURCE_LAUNCHER" >&2
    exit 1
}
[[ -f "$POWER_OFF_GUARD" && ! -L "$POWER_OFF_GUARD" ]] || {
    printf 'Scaleway poweroff guard is missing or unsafe.\n' >&2
    exit 1
}
[[ -f "$POWER_OFF_ENV" && ! -L "$POWER_OFF_ENV" ]] || {
    printf 'Root-only Scaleway poweroff environment is missing.\n' >&2
    exit 1
}
[[ "$(stat -c '%u' "$POWER_OFF_ENV")" == 0 ]] || {
    printf 'Scaleway poweroff environment must be root-owned.\n' >&2
    exit 1
}
poweroff_mode="$(stat -c '%a' "$POWER_OFF_ENV")"
(( (8#$poweroff_mode & 077) == 0 )) || {
    printf 'Scaleway poweroff environment must not be group/world accessible.\n' >&2
    exit 1
}

poweroff_load="$(systemctl show "$POWER_OFF_UNIT" --property=LoadState --value 2>/dev/null || true)"
[[ "$poweroff_load" == loaded ]] || {
    printf 'Scaleway poweroff unit is not installed; run the reviewed installer first.\n' >&2
    exit 1
}
poweroff_active="$(systemctl show "$POWER_OFF_UNIT" --property=ActiveState --value)"
[[ "$poweroff_active" != active && "$poweroff_active" != activating ]] || {
    printf 'Scaleway poweroff unit is unexpectedly active.\n' >&2
    exit 1
}
systemctl reset-failed "$POWER_OFF_UNIT" >/dev/null 2>&1 || true
bash "$POWER_OFF_GUARD" --verify-only >/dev/null

# From this point forward, every refusal, shell error, interrupt, or SSH hangup
# requests a true provider poweroff. Successful service handoff disarms it;
# the service itself has OnSuccess and OnFailure poweroff dependencies.
adapter=""
poweroff_if_unsuccessful=true
cleanup() {
    local status=$?
    [[ -z "$adapter" ]] || rm -f -- "$adapter"
    if [[ "$poweroff_if_unsuccessful" == true && $status -ne 0 ]]; then
        bash "$POWER_OFF_GUARD" --poweroff >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

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
require_source_occurrence 'require_exact ECHOES_HARD_BUDGET_USD 75.00' 1
require_source_occurrence 'cap != Decimal("75.00")' 1
require_source_occurrence 'verified accrued cost plus worker window and B2 reserve exceeds $75' 1
require_source_occurrence 'current owner-verified pricing does not fit the frozen $75 all-in cap' 1
require_source_occurrence '    --property=Restart=no \' 1
require_source_occurrence 'CCX43 / Ubuntu 24.04 / 16 dedicated AMD vCPU / 64 GB / 360 GB SSD' 1

adapter="$(mktemp /run/project-echoes-final-discovery-scaleway.XXXXXX)"

sed \
    -e 's/require_exact ECHOES_EXPECTED_SERVER_TYPE CCX43/require_exact ECHOES_EXPECTED_SERVER_TYPE POP2-16C-64G/' \
    -e 's/require_exact ECHOES_SERVER_NAME project-echoes-final-discovery-v1/require_exact ECHOES_SERVER_NAME project-echoes-final-discovery/' \
    -e 's/require_exact ECHOES_HARD_BUDGET_USD 75.00/require_exact ECHOES_HARD_BUDGET_USD 125.00/' \
    -e 's/cap != Decimal("75.00")/cap != Decimal("125.00")/' \
    -e 's/verified accrued cost plus worker window and B2 reserve exceeds [$]75/verified accrued cost plus worker window and B2 reserve exceeds $125/' \
    -e 's/current owner-verified pricing does not fit the frozen [$]75 all-in cap/current owner-verified pricing does not fit the owner-authorized $125 all-in cap/' \
    -e 's/CCX43 contract requires exactly 16 visible vCPUs/production contract requires exactly 16 visible vCPUs/' \
    -e 's/CCX43 contract requires AMD CPUs/production contract requires AMD CPUs/' \
    -e 's/CCX43 contract requires a host advertised with 64 GB RAM/production contract requires a host advertised with 64 GB RAM/' \
    -e 's#CCX43 / Ubuntu 24.04 / 16 dedicated AMD vCPU / 64 GB / 360 GB SSD#Scaleway POP2-16C-64G / Ubuntu 24.04 / 16 dedicated AMD vCPU / 64 GB / 400 GB Block Storage 5K#' \
    "$SOURCE_LAUNCHER" > "$adapter"

python3 - "$adapter" "$POWER_OFF_UNIT" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
poweroff_unit = sys.argv[2]
text = path.read_text(encoding="utf-8")
old = "    --property=Restart=no \\\n"
new = (
    old
    + f"    --property=OnSuccess={poweroff_unit} \\\n"
    + f"    --property=OnFailure={poweroff_unit} \\\n"
)
if text.count(old) != 1:
    raise SystemExit("Scaleway adapter could not bind one poweroff dependency")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
PY
chmod 0700 "$adapter"

# Fail closed if any required binding is absent after adaptation.
for expected in \
    'require_exact ECHOES_EXPECTED_SERVER_TYPE POP2-16C-64G' \
    'require_exact ECHOES_SERVER_NAME project-echoes-final-discovery' \
    'require_exact ECHOES_FINAL_DISCOVERY_RUNTIME_HOURS 96' \
    'worker_hours = Decimal("96")' \
    '"maximum_worker_hours": 96,' \
    '--property=RuntimeMaxSec=96h' \
    'require_exact ECHOES_HARD_BUDGET_USD 125.00' \
    'cap != Decimal("125.00")' \
    'verified accrued cost plus worker window and B2 reserve exceeds $125' \
    'current owner-verified pricing does not fit the owner-authorized $125 all-in cap' \
    '--property=OnSuccess=echoes-final-discovery-poweroff.service' \
    '--property=OnFailure=echoes-final-discovery-poweroff.service' \
    'Scaleway POP2-16C-64G / Ubuntu 24.04 / 16 dedicated AMD vCPU / 64 GB / 400 GB Block Storage 5K'; do
    grep -F -q -- "$expected" "$adapter" || {
        printf 'Scaleway adapter could not bind required contract: %s\n' "$expected" >&2
        exit 1
    }
done

bash "$adapter" "$@"
poweroff_if_unsuccessful=false
