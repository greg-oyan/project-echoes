#!/usr/bin/env bash
set -Eeuo pipefail

SERVICE_NAME="echoes-m7.service"
ENV_FILE="/etc/project-echoes/m7.env"

if [[ $EUID -ne 0 ]]; then
    printf 'cloud_stop.sh must run as root (use sudo).\n' >&2
    exit 1
fi
if [[ ! -r "$ENV_FILE" ]]; then
    printf 'Service environment is missing.\n' >&2
    exit 1
fi
# shellcheck disable=SC1090
source "$ENV_FILE"

if ! systemctl is-active --quiet "$SERVICE_NAME"; then
    printf '%s is not active; no signal was sent.\n' "$SERVICE_NAME"
    systemctl show "$SERVICE_NAME" \
        --property=ActiveState \
        --property=SubState \
        --property=Result \
        --property=MainPID \
        --no-pager
    exit 0
fi

# --no-block submits one SIGINT-based graceful stop and returns. It does not
# poll, wait for completion, remove files, or escalate from this script.
systemctl stop --no-block "$SERVICE_NAME"
systemctl show "$SERVICE_NAME" \
    --property=ActiveState \
    --property=SubState \
    --property=Result \
    --property=MainPID \
    --no-pager

printf 'Graceful stop submitted once. Staging and checkpoints were not removed.\n'
printf 'Preserved staging path: %s\n' "$ECHOES_RESUME_STAGING"
