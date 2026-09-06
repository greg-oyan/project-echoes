"""Regression coverage for the Scaleway budget-refusal shell path."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "cloud" / "launch_final_discovery_scaleway.sh"
LAUNCHER = ROOT / "cloud" / "launch_final_discovery.sh"


def test_generated_budget_refusal_is_safe_with_nounset(tmp_path: Path) -> None:
    script = ADAPTER.read_text(encoding="utf-8")
    marker = 'python3 - "$adapter" "$POWER_OFF_UNIT" <<\'PY\'\n'
    terminator = '\nPY\nchmod 0700 "$adapter"'
    assert script.count(marker) == 1
    python_source, separator, _ = script.split(marker, 1)[1].partition(terminator)
    assert separator

    launcher_copy = tmp_path / "launch_final_discovery.sh"
    launcher_copy.write_text(LAUNCHER.read_text(encoding="utf-8"), encoding="utf-8")
    rewritten = subprocess.run(
        [
            sys.executable,
            "-c",
            python_source,
            str(launcher_copy),
            "echoes-final-discovery-poweroff.service",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert rewritten.returncode == 0, rewritten.stderr

    generated = launcher_copy.read_text(encoding="utf-8")
    matching = [
        line
        for line in generated.splitlines()
        if "current owner-verified pricing does not fit" in line and "die " in line
    ]
    assert matching == [
        ")\" || die 'current owner-verified pricing does not fit the "
        "owner-authorized $125 all-in cap'"
    ]

    refusal = matching[0].split("||", 1)[1].strip()
    executed = subprocess.run(
        [
            "bash",
            "-u",
            "-c",
            f'die() {{ printf "%s\\n" "$1"; }}; {refusal}',
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert executed.returncode == 0, executed.stderr
    assert executed.stdout.strip() == (
        "current owner-verified pricing does not fit the owner-authorized $125 all-in cap"
    )
