"""Static contracts for the non-babysitting Milestone 7 PowerShell tools."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


def _source(name: str) -> str:
    return (SCRIPTS / name).read_text(encoding="utf-8")


def _assert_tokens_in_order(source: str, tokens: tuple[str, ...]) -> None:
    cursor = 0
    for token in tokens:
        cursor = source.index(token, cursor) + len(token)


def test_agent_policy_makes_detached_non_babysitting_rules_durable() -> None:
    policy = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    required = (
        "Never monitor a local computation continuously.",
        "Never use polling or sleep loops for pipeline status.",
        "Commands expected to exceed ten minutes must be launched detached with logs, "
        "PID metadata, checkpoints, and a one-shot status command.",
        "After launching, perform only one startup verification after a brief bounded check.",
        "Return control to the user while the operating system runs the computation.",
        "Never delete preserved staging or checkpoints without explicit user authorization.",
    )
    assert all(rule in policy for rule in required)


def test_status_is_one_shot_and_reports_process_artifact_disk_and_log_state() -> None:
    source = _source("m7_status.ps1")
    assert source.startswith("#requires -Version 5.1")
    assert re.search(r"Start-Sleep|Wait-Process|WaitForExit|while\s*\(|\bdo\s*\{", source) is None
    assert "Get-CimInstance Win32_Process" in source
    for contract in (
        "ParentProcessId",
        "creation_time_utc",
        "elapsed_seconds",
        "cpu_seconds",
        "cpu_delta_seconds",
        "WorkingSet64",
        "schema_v1_exists",
        "output_partition_counts",
        "primary_checkpoint_part_count",
        "tier3_checkpoint_manifest_count",
        "available_free_space_bytes",
        "Get-Content -LiteralPath $Path -Tail",
        "stdout_tail",
        "stderr_tail",
        "status-latest.json",
    ):
        assert contract in source


def test_detached_launcher_uses_only_the_governed_resume_command() -> None:
    source = _source("m7_start_detached.ps1")
    assert source.startswith("#requires -Version 5.1")
    _assert_tokens_in_order(
        source,
        (
            '"run"',
            '"echoes"',
            '"run-lexical-pipeline"',
            '"--primary"',
            '"--database"',
            "$databasePath",
            '"--output-dir"',
            "$canonicalOutput",
            '"--force"',
            '"--resume-staging-dir"',
            "$stagingPath",
        ),
    )
    assert source.count("Start-Process") == 1
    for contract in (
        "-WindowStyle Hidden",
        "-RedirectStandardOutput $stdoutPath",
        "-RedirectStandardError $stderrPath",
        "-WorkingDirectory $ProjectRoot",
        "-PassThru",
        "Get-CimInstance Win32_Process",
        "Refusing duplicate launch",
        "Refusing noncanonical lexical output",
        "canonical schema-v1 already exists",
        "Refusing ambiguous resume",
        r"^\.schema-v1\.writing-[0-9a-fA-F]{32}$",
        "FileMode]::CreateNew",
        "launch-$timestamp.json",
        "latest.json",
        "launcher_pid",
        "command = $commandLine",
        "launch_submitted",
    ):
        assert contract in source
    assert "Get-Process -Id $process.Id" not in source
    assert re.search(r"Start-Sleep|Wait-Process|WaitForExit|while\s*\(|\bdo\s*\{", source) is None
    assert "-Wait" not in source


def test_validator_delegates_canonical_validation_and_reads_staging_only() -> None:
    source = _source("m7_validate.ps1")
    assert source.startswith("#requires -Version 5.1")
    _assert_tokens_in_order(
        source,
        (
            "validate-lexical",
            "--all",
            "--strict",
            "--output-dir",
            "$canonicalOutput",
            "--database",
            "$databasePath",
            "--json",
        ),
    )
    for contract in (
        "Test-ContiguousParts",
        "directional_rankings = 1565",
        "sensitivity_results = 640",
        "$primaryParts.Count -ne 968",
        "$tier3Manifests.Count -ne 26",
        "Get-FileHash -LiteralPath $partPath -Algorithm SHA256",
        "pyarrow.parquet as pq",
        "pq.ParquetFile(path)",
        "table-hashes.json",
        "scripts/generate_m7_report.py",
        "outputs/reports/m7-spot-check-config.json",
        "m7-first-run-reference/table-hashes.json",
        "required_report_prerequisites_valid",
        "Required Milestone 7 report prerequisite is missing",
        "first_run_reference_exists",
        "repair_attempted = $false",
        "deletion_attempted = $false",
    ):
        assert contract in source
    assert (
        re.search(
            r"\b(Remove-Item|Move-Item|Copy-Item|Rename-Item|Clear-Content|Set-Content)\b",
            source,
        )
        is None
    )
