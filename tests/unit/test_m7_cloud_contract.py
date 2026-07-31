"""Static contracts for the governed Milestone 7 CCX33 cloud tooling."""

from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUD = ROOT / "cloud"


def _cloud_source(name: str) -> str:
    return (CLOUD / name).read_text(encoding="utf-8")


def test_bootstrap_and_launch_use_ccx33_disk_and_duckdb_limits() -> None:
    bootstrap = _cloud_source("bootstrap_ubuntu.sh")
    launch = _cloud_source("cloud_start.sh")

    assert "MINIMUM_FREE_BYTES=$((120 * 1024 * 1024 * 1024))" in bootstrap
    assert "The governed CCX33 target is x86_64" in bootstrap
    assert "SET memory_limit='22GiB'" in bootstrap
    assert '"supports_22_gib_memory_limit": str(observed_limit) == "22.0 GiB"' in bootstrap
    assert "MINIMUM_FREE_BYTES=$((120 * 1024 * 1024 * 1024))" in launch
    assert '"$ECHOES_MAXIMUM_MEMORY_BYTES" != "30064771072"' in launch
    assert '"$ECHOES_DUCKDB_MEMORY_LIMIT_BYTES" != "23622320128"' in launch
    assert '"$ECHOES_MINIMUM_FREE_DISK_BYTES" != "26843545600"' in launch
    assert '"$ECHOES_THREAD_COUNT" != "1"' in launch


def test_service_and_validation_units_use_ccx33_memory_limits() -> None:
    installer = _cloud_source("install_echoes_service.sh")
    launch = _cloud_source("cloud_start.sh")
    validation = _cloud_source("cloud_validate.sh")

    for contract in (
        "DUCKDB_MEMORY_BYTES=23622320128",
        "MAXIMUM_MEMORY_BYTES=30064771072",
        "MINIMUM_FREE_DISK_BYTES=26843545600",
        "THREAD_COUNT=1",
        "ECHOES_MINIMUM_FREE_DISK_BYTES=$MINIMUM_FREE_DISK_BYTES",
        "maximum_computational_threads: 6",
        "launch_minimum_free_disk_bytes: 128849018880",
        "systemd_memory_high_bytes: 27917287424",
        "systemd_memory_max_bytes: 30064771072",
        "MemoryHigh=26G",
        "MemoryMax=28G",
    ):
        assert contract in installer
    assert '"MemoryHigh=26G"' in launch
    assert '"MemoryMax=28G"' in launch
    assert "--property=MemoryHigh=26G" in validation
    assert "--property=MemoryMax=28G" in validation


def test_cloud_tools_do_not_introduce_polling_or_a_second_worker() -> None:
    combined = "\n".join(
        _cloud_source(name)
        for name in (
            "bootstrap_ubuntu.sh",
            "cloud_start.sh",
            "cloud_status.sh",
            "install_echoes_service.sh",
        )
    )

    assert "echoes-m7.service" in combined
    assert "Start-Sleep" not in combined
    assert "while true" not in combined
    assert "watch " not in combined
    assert ".timer" not in combined


def test_owner_supplied_ccx33_cost_contract_is_exact() -> None:
    combined_rate = Decimal("0.2660") + Decimal("0.0010")
    one_worker = combined_rate * 48
    one_lifecycle = combined_rate * 72
    two_lifecycles = combined_rate * 144
    credit = Decimal("25.00")

    assert combined_rate == Decimal("0.2670")
    assert one_worker == Decimal("12.8160")
    assert one_lifecycle == Decimal("19.2240")
    assert two_lifecycles == Decimal("38.4480")
    assert max(one_lifecycle - credit, Decimal(0)) == Decimal("0")
    assert two_lifecycles - credit == Decimal("13.4480")
