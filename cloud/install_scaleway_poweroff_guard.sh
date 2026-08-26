#!/usr/bin/env bash
set -Eeuo pipefail

readonly REPO_ROOT="/srv/project-echoes/repo"
readonly SOURCE_UNIT="$REPO_ROOT/cloud/echoes-final-discovery-poweroff.service"
readonly TARGET_UNIT="/etc/systemd/system/echoes-final-discovery-poweroff.service"
readonly GUARD="$REPO_ROOT/cloud/scaleway_poweroff_guard.sh"
readonly ENV_FILE="/etc/project-echoes/scaleway-poweroff.env"

fail() {
    printf 'Scaleway poweroff guard installation refused: %s\n' "$1" >&2
    exit 1
}

if (($#)); then
    case "$1" in
        -h|--help)
            printf 'Usage: sudo bash %s/cloud/install_scaleway_poweroff_guard.sh\n' "$REPO_ROOT"
            exit 0
            ;;
        *)
            exit 2
            ;;
    esac
fi

[[ $EUID -eq 0 ]] || fail "run as root"
for executable in install systemctl bash stat; do
    command -v "$executable" >/dev/null 2>&1 || fail "required command is missing: $executable"
done
[[ -f "$SOURCE_UNIT" && ! -L "$SOURCE_UNIT" ]] || fail "reviewed unit template is absent"
[[ -f "$GUARD" && ! -L "$GUARD" ]] || fail "reviewed guard script is absent"
[[ -f "$ENV_FILE" && ! -L "$ENV_FILE" ]] || fail "populate the root-only guard environment first"
[[ "$(stat -c '%u' "$ENV_FILE")" == 0 ]] || fail "guard environment must be root-owned"
env_mode="$(stat -c '%a' "$ENV_FILE")"
(( (8#$env_mode & 077) == 0 )) || fail "guard environment must be mode 600 or stricter"

bash -n "$GUARD"
install -m 0644 -o root -g root "$SOURCE_UNIT" "$TARGET_UNIT"
systemctl daemon-reload
systemctl reset-failed echoes-final-discovery-poweroff.service >/dev/null 2>&1 || true

# This API GET proves that the least-privilege key, zone, ID, name, and
# commercial type all agree. It does not power off or otherwise mutate the VM.
bash "$GUARD" --verify-only

load_state="$(systemctl show echoes-final-discovery-poweroff.service -p LoadState --value)"
[[ "$load_state" == loaded ]] || fail "installed poweroff unit did not load"
active_state="$(systemctl show echoes-final-discovery-poweroff.service -p ActiveState --value)"
[[ "$active_state" == inactive || "$active_state" == failed ]] ||
    fail "poweroff unit unexpectedly became active during installation"

printf 'SCALEWAY_POWEROFF_GUARD_INSTALLED\n'
