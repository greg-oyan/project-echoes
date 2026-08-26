"""Regression coverage for the production launcher's GNU df probe."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "cloud" / "launch_final_discovery.sh"
ADAPTER = ROOT / "cloud" / "launch_final_discovery_scaleway.sh"


def test_launcher_uses_valid_gnu_df_option_combination() -> None:
    script = LAUNCHER.read_text(encoding="utf-8")
    assert "df -P -B1 --output=avail" not in script
    assert script.count('df -B1 --output=avail "$ECHOES_WORK_DIR"') == 1


def test_scaleway_adapter_executes_the_validated_base_launcher() -> None:
    adapter = ADAPTER.read_text(encoding="utf-8")
    assert (
        'SOURCE_LAUNCHER="$REPO_ROOT/cloud/launch_final_discovery.sh"' in adapter
    )
    assert 'exec bash "$adapter"' in adapter
