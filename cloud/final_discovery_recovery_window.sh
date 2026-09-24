#!/usr/bin/env bash
set -Eeuo pipefail

# A one-shot ledger/timer operation, never a worker or polling supervisor.
[[ $EUID -eq 0 ]] || { printf 'Recovery window requires root.\n' >&2; exit 1; }
exec python3 - "$@" <<'PY'
from __future__ import annotations

import json
import math
import os
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

STATE = Path('/var/lib/project-echoes/final-discovery')
LEDGER = STATE / 'recovery-window.json'
UNIT_ROOT = Path('/etc/systemd/system')
TIMER_NAME = 'echoes-final-discovery-expiry.timer'
EXPIRY_NAME = 'echoes-final-discovery-expiry.service'
POWER_OFF_NAME = 'echoes-final-discovery-poweroff.service'
REPO = Path('/srv/project-echoes/repo')
WORK = '/srv/project-echoes/final-discovery/work-20260909T040447Z-e265b59c'
SUCCESSOR_WORK = '/srv/project-echoes/final-discovery/work-20260922-m7-null-recovery'
CALIBRATION_WORK = '/srv/project-echoes/final-discovery/work-20260923-calibration-memory'
REVIEW_WORK = '/srv/project-echoes/final-discovery/work-20260923-review-disk'
COMPRESSED_REVIEW_WORK = '/srv/project-echoes/final-discovery/work-20260923-review-compressed'
INSTANCE = '2ade35f2-3c65-474f-9ec3-71cd5c9a4ffe'
SECONDS = 96 * 3600


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def now():
    return datetime.now(timezone.utc)


def utc(value):
    parsed = datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    require(parsed.strftime('%Y-%m-%dT%H:%M:%SZ') == value, 'noncanonical UTC timestamp')
    return parsed


def safe_directory(path):
    require(path.is_dir() and path.resolve() == path and not path.is_symlink(),
            f'unsafe recovery directory: {path}')
    info = path.stat()
    require(info.st_uid == 0 and not stat.S_IMODE(info.st_mode) & 0o022,
            f'recovery directory is writable by a non-root owner: {path}')


def owned_file(path, mode):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and path.resolve() == path
            and info.st_uid == info.st_gid == 0 and stat.S_IMODE(info.st_mode) == mode,
            f'unsafe recovery file metadata: {path}')
    return path.read_bytes()


def canonical(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def record_for(start, work):
    require(work == WORK, 'recovery work directory differs from the authorized campaign')
    started = utc(start)
    require(started <= now(), 'recovery start is in the future')
    return {'schema_version': 1, 'instance_id': INSTANCE, 'zone': 'nl-ams-1',
            'work_directory': WORK, 'started_at': start,
            'deadline_at': (started + timedelta(seconds=SECONDS)).strftime('%Y-%m-%dT%H:%M:%SZ')}


def read_record(work=WORK):
    require(work in (WORK, SUCCESSOR_WORK, CALIBRATION_WORK, REVIEW_WORK, COMPRESSED_REVIEW_WORK),
            'recovery work directory differs from the authorized campaign')
    safe_directory(STATE)
    content = owned_file(LEDGER, 0o444)
    value = json.loads(content)
    require(isinstance(value, dict) and 'started_at' in value, 'invalid recovery ledger')
    # A repaired-code successor inherits the original ledger; it cannot create
    # or reset a window. Installation remains restricted to the original WORK.
    expected = record_for(value['started_at'], WORK)
    require(value == expected and content == canonical(expected), 'recovery ledger binding differs')
    return value


def write_once(path, content, mode):
    if path.exists() or path.is_symlink():
        require(owned_file(path, mode) == content, f'refusing to replace recovery evidence: {path}')
        return
    # Exclusive creation intentionally leaves a partial record on I/O failure;
    # a later invocation must reject it, never reset the recovery window.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(descriptor, 'wb') as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, mode)
    sync_directory(path.parent)
    require(owned_file(path, mode) == content, f'published recovery file differs: {path}')


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def timer_bytes(record):
    deadline = utc(record['deadline_at']).strftime('%Y-%m-%d %H:%M:%S UTC')
    return (
        '[Unit]\nDescription=Enforce the original Project Echoes recovery deadline\n\n'
        '[Timer]\nUnit=' + EXPIRY_NAME + '\nOnCalendar=' + deadline + '\n'
        'OnBootSec=15s\nPersistent=true\nAccuracySec=1s\nRandomizedDelaySec=0\n\n'
        '[Install]\nWantedBy=timers.target\n'
    ).encode()


def run(*arguments):
    result = subprocess.run(arguments, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def request_poweroff():
    run('systemctl', 'start', '--no-block', POWER_OFF_NAME)


def verify_armed(record):
    safe_directory(UNIT_ROOT)
    require(owned_file(UNIT_ROOT / TIMER_NAME, 0o644) == timer_bytes(record),
            'recovery timer deadline differs')
    source = REPO / 'cloud' / EXPIRY_NAME
    require(source.is_file() and not source.is_symlink(), 'expiry service source is unsafe')
    require(owned_file(UNIT_ROOT / EXPIRY_NAME, 0o644) == source.read_bytes(),
            'installed recovery expiry service differs')
    for unit in (TIMER_NAME, EXPIRY_NAME):
        require(run('systemctl', 'show', unit, '--property=FragmentPath', '--value')
                == str(UNIT_ROOT / unit), 'recovery unit loaded from an unexpected path')
        require(not run('systemctl', 'show', unit, '--property=DropInPaths', '--value'),
                'recovery unit has unreviewed overrides')
        require(run('systemctl', 'show', unit, '--property=NeedDaemonReload', '--value') == 'no',
                'recovery unit has unapplied changes')
    run('systemctl', 'is-enabled', '--quiet', TIMER_NAME)
    run('systemctl', 'is-active', '--quiet', TIMER_NAME)
    require(run('systemctl', 'show', POWER_OFF_NAME, '--property=LoadState', '--value') == 'loaded',
            'existing poweroff service is not loaded')


def remaining(work):
    record = read_record(work)
    seconds_left = (utc(record['deadline_at']) - now()).total_seconds()
    if seconds_left <= 0:
        request_poweroff()
        raise RuntimeError('the original 96-hour recovery deadline has expired')
    seconds = math.floor(seconds_left)
    require(seconds > 0, 'less than one second remains before the recovery deadline')
    require(seconds <= SECONDS, 'remaining recovery window exceeds 96 hours')
    verify_armed(record)
    # Re-read the clock after systemd verification; callers use this immediately
    # as RuntimeMaxSec, while the independent calendar timer retains the deadline.
    seconds_left = (utc(record['deadline_at']) - now()).total_seconds()
    if seconds_left <= 0:
        request_poweroff()
        raise RuntimeError('the original 96-hour recovery deadline has expired')
    seconds = math.floor(seconds_left)
    require(seconds > 0, 'less than one second remains before the recovery deadline')
    return seconds


def install(start, work):
    record = record_for(start, work)
    safe_directory(STATE)
    safe_directory(UNIT_ROOT)
    run('/usr/bin/bash', str(REPO / 'cloud/scaleway_poweroff_guard.sh'), '--verify-only')
    write_once(LEDGER, canonical(record), 0o444)
    source = REPO / 'cloud' / EXPIRY_NAME
    require(source.is_file() and not source.is_symlink(), 'expiry service source is unsafe')
    write_once(UNIT_ROOT / EXPIRY_NAME, source.read_bytes(), 0o644)
    write_once(UNIT_ROOT / TIMER_NAME, timer_bytes(record), 0o644)
    run('systemctl', 'daemon-reload')
    run('systemctl', 'enable', '--now', TIMER_NAME)
    return {**record, 'remaining_seconds': remaining(work)}


def enforce_expiry():
    record = read_record()
    if now() >= utc(record['deadline_at']):
        request_poweroff()


def main(arguments):
    if len(arguments) == 3 and arguments[0] == '--install':
        print(json.dumps(install(arguments[1], arguments[2]), sort_keys=True))
    elif len(arguments) == 2 and arguments[0] == '--remaining':
        print(remaining(arguments[1]))
    elif arguments == ['--enforce-expiry']:
        enforce_expiry()
    else:
        raise RuntimeError('usage: --install START_UTC WORK_DIR | --remaining WORK_DIR | --enforce-expiry')


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except Exception as error:
        print(f'Recovery window refused: {error}', file=sys.stderr)
        sys.exit(1)
PY
