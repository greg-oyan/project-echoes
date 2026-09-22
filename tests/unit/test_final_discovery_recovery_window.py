"""Execute the one-shot deadline logic with local files and a fake systemd interface."""

from __future__ import annotations

import ast
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "cloud/final_discovery_recovery_window.sh"
SERVICE = ROOT / "cloud/echoes-final-discovery-expiry.service"


@pytest.fixture
def window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    text = SCRIPT.read_text(encoding="utf-8")
    source = text.split("<<'PY'\n", 1)[1].rsplit("\nPY\n", 1)[0]
    namespace: dict[str, Any] = {"__name__": "deadline_test"}
    exec(compile(source, str(SCRIPT), "exec"), namespace)
    state = tmp_path / "state"
    units = tmp_path / "units"
    repo = tmp_path / "repo"
    state.mkdir()
    units.mkdir()
    (repo / "cloud").mkdir(parents=True)
    (repo / "cloud" / namespace["EXPIRY_NAME"]).write_bytes(SERVICE.read_bytes())
    clock = [datetime(2026, 9, 20, 12, 5, tzinfo=UTC)]
    armed = [False]
    calls: list[tuple[str, ...]] = []

    def run(*arguments: str) -> str:
        calls.append(arguments)
        if arguments[:2] == ("systemctl", "enable"):
            armed[0] = True
        if (
            arguments[:2] in {("systemctl", "is-enabled"), ("systemctl", "is-active")}
            and not armed[0]
        ):
            raise subprocess.CalledProcessError(1, arguments)
        if arguments[:2] == ("systemctl", "show"):
            property_name = arguments[3].removeprefix("--property=")
            return {
                "FragmentPath": str(units / arguments[2]),
                "DropInPaths": "",
                "NeedDaemonReload": "no",
                "LoadState": "loaded",
            }[property_name]
        return ""

    # Tests run on Windows as well as Linux. Keep all real ledger content,
    # exclusive-write, date, timer and command logic; substitute POSIX metadata
    # and directory fsync only, since Windows has no equivalent ownership model.
    def safe_directory(path: Path) -> None:
        assert path.is_dir() and path.resolve() == path and not path.is_symlink()

    def owned_file(path: Path, _mode: int) -> bytes:
        assert path.is_file() and path.resolve() == path and not path.is_symlink()
        return path.read_bytes()

    namespace.update(
        {
            "STATE": state,
            "LEDGER": state / "recovery-window.json",
            "UNIT_ROOT": units,
            "REPO": repo,
            "now": lambda: clock[0],
            "run": run,
            "safe_directory": safe_directory,
            "owned_file": owned_file,
            "sync_directory": lambda _path: None,
        }
    )
    if not hasattr(os, "O_NOFOLLOW"):
        monkeypatch.setattr(os, "O_NOFOLLOW", 0, raising=False)
    return SimpleNamespace(
        api=namespace,
        clock=clock,
        armed=armed,
        calls=calls,
        start="2026-09-20T12:00:00Z",
        work=namespace["WORK"],
    )


def poweroff_calls(window: SimpleNamespace) -> list[tuple[str, ...]]:
    return [
        call
        for call in window.calls
        if call == ("systemctl", "start", "--no-block", "echoes-final-discovery-poweroff.service")
    ]


def test_install_is_immutable_and_remaining_time_shrinks(window: SimpleNamespace) -> None:
    first = window.api["install"](window.start, window.work)
    assert first["deadline_at"] == "2026-09-24T12:00:00Z"
    assert first["remaining_seconds"] == 96 * 3600 - 300
    ledger = window.api["LEDGER"]
    original_bytes = ledger.read_bytes()
    original_time = ledger.stat().st_mtime_ns
    window.clock[0] += timedelta(hours=8)
    second = window.api["install"](window.start, window.work)
    assert second["remaining_seconds"] == first["remaining_seconds"] - 8 * 3600
    assert ledger.read_bytes() == original_bytes
    assert ledger.stat().st_mtime_ns == original_time
    with pytest.raises(RuntimeError, match="refusing to replace recovery evidence"):
        window.api["install"]("2026-09-20T13:00:00Z", window.work)
    assert ledger.read_bytes() == original_bytes
    assert not poweroff_calls(window)


@pytest.mark.parametrize("start", ["2026-09-20T12:05:01Z", "2026-09-20T12:00:00+00:00", "bad"])
def test_invalid_or_future_start_cannot_create_a_window(
    window: SimpleNamespace, start: str
) -> None:
    with pytest.raises((RuntimeError, ValueError)):
        window.api["install"](start, window.work)
    assert not window.api["LEDGER"].exists()
    assert not window.calls


def test_boot_check_does_not_power_off_before_expiry_and_repeats_after_expiry(
    window: SimpleNamespace,
) -> None:
    window.api["install"](window.start, window.work)
    window.api["enforce_expiry"]()
    assert not poweroff_calls(window)
    window.clock[0] = datetime(2026, 9, 24, 12, 0, tzinfo=UTC) - timedelta(microseconds=500000)
    window.api["enforce_expiry"]()
    with pytest.raises(RuntimeError, match="less than one second remains"):
        window.api["remaining"](window.work)
    assert not poweroff_calls(window)
    window.clock[0] += timedelta(microseconds=500000)
    window.api["enforce_expiry"]()
    assert len(poweroff_calls(window)) == 1
    # A later reboot repeats the native OnBootSec check even if the persisted
    # one-shot calendar event already fired on the previous boot.
    window.clock[0] += timedelta(hours=2)
    window.api["enforce_expiry"]()
    assert len(poweroff_calls(window)) == 2
    with pytest.raises(RuntimeError, match="deadline has expired"):
        window.api["remaining"](window.work)
    assert len(poweroff_calls(window)) == 3


def test_unarmed_or_changed_timer_refuses_worker_start(window: SimpleNamespace) -> None:
    window.api["install"](window.start, window.work)
    window.armed[0] = False
    with pytest.raises(subprocess.CalledProcessError):
        window.api["remaining"](window.work)
    window.armed[0] = True
    timer = window.api["UNIT_ROOT"] / window.api["TIMER_NAME"]
    timer.write_text("[Timer]\nOnActiveSec=96h\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="timer deadline differs"):
        window.api["remaining"](window.work)
    assert not poweroff_calls(window)


def test_wrong_campaign_and_malformed_ledger_fail_closed(window: SimpleNamespace) -> None:
    with pytest.raises(RuntimeError, match="work directory differs"):
        window.api["install"](window.start, window.work + "-different")
    window.api["install"](window.start, window.work)
    ledger = window.api["LEDGER"]
    ledger.chmod(0o600)
    ledger.write_bytes(b"{}\n")
    with pytest.raises(RuntimeError, match="invalid recovery ledger"):
        window.api["remaining"](window.work)


def test_timer_and_service_delegate_to_existing_poweroff_without_a_supervisor(
    window: SimpleNamespace,
) -> None:
    record = window.api["record_for"](window.start, window.work)
    timer = window.api["timer_bytes"](record).decode()
    assert "OnCalendar=2026-09-24 12:00:00 UTC\n" in timer
    assert "OnBootSec=15s\n" in timer
    assert "Persistent=true\nAccuracySec=1s\nRandomizedDelaySec=0\n" in timer
    assert "Unit=echoes-final-discovery-expiry.service\n" in timer
    service = SERVICE.read_text(encoding="utf-8")
    assert "Type=oneshot\n" in service
    assert "--enforce-expiry\n" in service
    assert "OnFailure=echoes-final-discovery-poweroff.service\n" in service
    assert "Restart=" not in service
    script = SCRIPT.read_text(encoding="utf-8")
    assert "os.O_EXCL | os.O_NOFOLLOW" in script
    assert "stat.S_IMODE(info.st_mode) == mode" in script
    assert "info.st_uid == info.st_gid == 0" in script
    parsed = ast.parse(script.split("<<'PY'\n", 1)[1].rsplit("\nPY\n", 1)[0])
    assert not any(isinstance(node, ast.While) for node in ast.walk(parsed))
    assert "sleep(" not in script


def test_repaired_successor_inherits_original_deadline_without_rewriting_ledger(
    window: SimpleNamespace,
) -> None:
    first = window.api["install"](window.start, window.work)
    ledger = window.api["LEDGER"]
    content = ledger.read_bytes()
    modified = ledger.stat().st_mtime_ns
    successor = window.api["SUCCESSOR_WORK"]
    window.clock[0] += timedelta(hours=24)
    assert window.api["remaining"](successor) == first["remaining_seconds"] - 24 * 3600
    assert ledger.read_bytes() == content
    assert ledger.stat().st_mtime_ns == modified
    with pytest.raises(RuntimeError, match="work directory differs"):
        window.api["install"](window.start, successor)
    with pytest.raises(RuntimeError, match="work directory differs"):
        window.api["remaining"](successor + "-retry")
    window.clock[0] = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
    with pytest.raises(RuntimeError, match="deadline has expired"):
        window.api["remaining"](successor)
    assert len(poweroff_calls(window)) == 1
    assert ledger.read_bytes() == content
