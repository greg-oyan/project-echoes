#requires -Version 5.1

[CmdletBinding()]
param(
    [string] $ProjectRoot = "",
    [string] $Database = "data/processed/project_echoes.duckdb",
    [string] $OutputDirectory = "data/processed/lexical/schema-v1",
    [string] $StagingDirectory = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-AbsolutePath {
    param(
        [Parameter(Mandatory = $true)][string] $Path,
        [Parameter(Mandatory = $true)][string] $BasePath
    )

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $BasePath $Path))
}

function Test-SamePath {
    param(
        [Parameter(Mandatory = $true)][string] $Left,
        [Parameter(Mandatory = $true)][string] $Right
    )

    return [string]::Equals(
        [System.IO.Path]::GetFullPath($Left).TrimEnd('\'),
        [System.IO.Path]::GetFullPath($Right).TrimEnd('\'),
        [System.StringComparison]::OrdinalIgnoreCase
    )
}

function Add-ValidationError {
    param([Parameter(Mandatory = $true)][string] $Message)
    $script:validationErrors.Add($Message)
}

function Test-ContiguousParts {
    param(
        [Parameter(Mandatory = $true)][string] $Directory,
        [Parameter(Mandatory = $true)][string] $Label
    )

    $parts = @(
        Get-ChildItem -LiteralPath $Directory -Force -File -Filter "part-*.parquet" `
            -ErrorAction SilentlyContinue |
            Sort-Object Name
    )
    for ($index = 0; $index -lt $parts.Count; $index++) {
        $expectedName = "part-{0:D5}.parquet" -f $index
        if ($parts[$index].Name -cne $expectedName) {
            Add-ValidationError (
                "$Label partitions are not contiguous: expected $expectedName, " +
                "found $($parts[$index].Name)."
            )
            return $parts
        }
    }
    return $parts
}

function Get-ReportPrerequisites {
    param([Parameter(Mandatory = $true)][string] $Root)

    $requirements = [ordered] @{}
    foreach ($relativePath in @(
        "scripts/generate_m7_report.py",
        "src/echoes/reports/lexical_baseline.py",
        "config/lexical.yaml",
        "config/experiments/m7-lexical-baseline.yaml",
        "outputs/reports/m7-spot-check-config.json",
        "data/processed/lexical/m7-first-run-reference/table-hashes.json",
        "data/processed/lexical/execution-manifests"
    )) {
        $requirements[$relativePath] = Test-Path -LiteralPath (Join-Path $Root $relativePath)
    }
    return $requirements
}

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$ProjectRoot = Get-AbsolutePath -Path $ProjectRoot -BasePath (Get-Location).Path
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot "docs/master-plan.md") -PathType Leaf)) {
    throw "Project root is not Project Echoes: $ProjectRoot"
}

$databasePath = Get-AbsolutePath -Path $Database -BasePath $ProjectRoot
$outputPath = Get-AbsolutePath -Path $OutputDirectory -BasePath $ProjectRoot
$canonicalOutput = Get-AbsolutePath `
    -Path "data/processed/lexical/schema-v1" `
    -BasePath $ProjectRoot
if (-not (Test-SamePath -Left $outputPath -Right $canonicalOutput)) {
    throw "Validation is confined to canonical lexical schema-v1: $outputPath"
}
if (-not (Test-Path -LiteralPath $databasePath -PathType Leaf)) {
    throw "Anchored lexical database does not exist: $databasePath"
}

$uvCommand = Get-Command uv -CommandType Application -ErrorAction Stop
$reportPrerequisites = Get-ReportPrerequisites -Root $ProjectRoot
$requiredReportPrerequisitePaths = @(
    "scripts/generate_m7_report.py",
    "src/echoes/reports/lexical_baseline.py",
    "config/lexical.yaml",
    "config/experiments/m7-lexical-baseline.yaml",
    "outputs/reports/m7-spot-check-config.json",
    "data/processed/lexical/execution-manifests"
)
$missingReportPrerequisites = @(
    $requiredReportPrerequisitePaths |
        Where-Object { -not [bool] $reportPrerequisites[$_] }
)
if (Test-Path -LiteralPath $canonicalOutput -PathType Container) {
    if (-not [string]::IsNullOrWhiteSpace($StagingDirectory)) {
        throw "Canonical schema-v1 exists; refusing ambiguous staging validation."
    }
    $strictOutput = @(
        & $uvCommand.Source run echoes validate-lexical `
            --all `
            --strict `
            --output-dir $canonicalOutput `
            --database $databasePath `
            --json 2>&1
    )
    $strictExitCode = $LASTEXITCODE
    $strictText = $strictOutput -join [Environment]::NewLine
    $strictReport = $null
    try {
        $strictReport = $strictText | ConvertFrom-Json
    }
    catch {
        $strictReport = [ordered] @{ raw_output = $strictText }
    }
    $canonicalReport = [ordered] @{
        mode = "canonical"
        validated_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
        canonical_output = $canonicalOutput
        strict_command = (
            "uv run echoes validate-lexical --all --strict --output-dir `"$canonicalOutput`" " +
            "--database `"$databasePath`" --json"
        )
        strict_exit_code = [int] $strictExitCode
        strict_report = $strictReport
        table_hash_manifest_exists = Test-Path `
            -LiteralPath (Join-Path $canonicalOutput "table-hashes.json") `
            -PathType Leaf
        report_prerequisites = $reportPrerequisites
        required_report_prerequisites_valid = ($missingReportPrerequisites.Count -eq 0)
        missing_report_prerequisites = $missingReportPrerequisites
        first_run_reference_exists = [bool] $reportPrerequisites[
            "data/processed/lexical/m7-first-run-reference/table-hashes.json"
        ]
    }
    $canonicalReport | ConvertTo-Json -Depth 12
    if ($strictExitCode -ne 0 -or $missingReportPrerequisites.Count -ne 0) {
        if ($strictExitCode -eq 0) {
            exit 1
        }
        exit $strictExitCode
    }
    exit 0
}

$outputParent = Split-Path -Parent $canonicalOutput
$stagingCandidates = @(
    Get-ChildItem -LiteralPath $outputParent -Force -Directory -ErrorAction Stop |
        Where-Object { $_.Name -match '^\.schema-v1\.writing-[0-9a-fA-F]{32}$' }
)
if ([string]::IsNullOrWhiteSpace($StagingDirectory)) {
    if ($stagingCandidates.Count -ne 1) {
        throw (
            "Expected exactly one governed staging sibling while canonical output is absent; " +
            "found $($stagingCandidates.Count)."
        )
    }
    $stagingPath = $stagingCandidates[0].FullName
}
else {
    $stagingPath = Get-AbsolutePath -Path $StagingDirectory -BasePath $ProjectRoot
}
$stagingItem = Get-Item -LiteralPath $stagingPath -Force -ErrorAction Stop
if (
    -not $stagingItem.PSIsContainer -or
    ($stagingItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 -or
    -not (Test-SamePath -Left $stagingItem.Parent.FullName -Right $outputParent) -or
    $stagingItem.Name -notmatch '^\.schema-v1\.writing-[0-9a-fA-F]{32}$'
) {
    throw "Staging validation escaped the governed schema-v1 sibling boundary: $stagingPath"
}

$validationErrors = New-Object System.Collections.Generic.List[string]
foreach ($missingPrerequisite in $missingReportPrerequisites) {
    Add-ValidationError "Required Milestone 7 report prerequisite is missing: $missingPrerequisite"
}
$unsafeEntries = @(
    Get-ChildItem -LiteralPath $stagingPath -Recurse -Force -ErrorAction Stop |
        Where-Object {
            ($_.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
        } |
        Select-Object -First 5
)
foreach ($unsafeEntry in $unsafeEntries) {
    Add-ValidationError "Staging contains a reparse point: $($unsafeEntry.FullName)"
}
if (Test-Path -LiteralPath (Join-Path $stagingPath "table-hashes.json")) {
    Add-ValidationError "Interrupted staging unexpectedly contains table-hashes.json."
}
if (Test-Path -LiteralPath (Join-Path $stagingPath "lexical_metadata")) {
    Add-ValidationError "Interrupted staging unexpectedly contains final lexical_metadata."
}

$expectedArtifactPartCounts = [ordered] @{
    feature_vocabulary = 1
    passage_feature_statistics = 1
    lexical_index_metadata = 3
    directional_rankings = 1565
    sensitivity_results = 640
    evaluation_results = 1
    null_replicate_summaries = 1
    threshold_calibration = 1
}
$artifactPartCounts = [ordered] @{}
foreach ($artifactName in $expectedArtifactPartCounts.Keys) {
    $artifactPath = Join-Path $stagingPath $artifactName
    $parts = @(Test-ContiguousParts -Directory $artifactPath -Label $artifactName)
    $artifactPartCounts[$artifactName] = $parts.Count
    if ($parts.Count -ne $expectedArtifactPartCounts[$artifactName]) {
        Add-ValidationError (
            "$artifactName expected $($expectedArtifactPartCounts[$artifactName]) partitions, " +
            "found $($parts.Count)."
        )
    }
}

$alignedCandidateArtifacts = @(
    "candidate_pairs",
    "candidate_detector_scores",
    "candidate_evidence",
    "shared_evidence",
    "ablation_results"
)
$alignedCandidateCounts = [ordered] @{}
foreach ($artifactName in $alignedCandidateArtifacts) {
    $artifactPath = Join-Path $stagingPath $artifactName
    $parts = @(Test-ContiguousParts -Directory $artifactPath -Label $artifactName)
    $alignedCandidateCounts[$artifactName] = $parts.Count
}
$distinctCandidateCounts = @($alignedCandidateCounts.Values | Sort-Object -Unique)
if ($distinctCandidateCounts.Count -ne 1) {
    Add-ValidationError (
        "Aligned candidate artifact partition counts differ: " +
        (($alignedCandidateCounts.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ", ")
    )
}

$checkpointRoot = Join-Path $stagingPath ".resume-primary-candidates"
$primaryManifestPath = Join-Path $checkpointRoot "complete.json"
$primaryParts = @(Test-ContiguousParts -Directory $checkpointRoot -Label "primary checkpoint")
if ($primaryParts.Count -ne 968) {
    Add-ValidationError "Primary checkpoint expected 968 partitions, found $($primaryParts.Count)."
}
$primaryManifest = $null
if (-not (Test-Path -LiteralPath $primaryManifestPath -PathType Leaf)) {
    Add-ValidationError "Primary checkpoint completion manifest is missing."
}
else {
    try {
        $primaryManifest = Get-Content -Raw -LiteralPath $primaryManifestPath | ConvertFrom-Json
        if ([int] $primaryManifest.schema_version -ne 1) {
            Add-ValidationError "Primary checkpoint schema_version is not 1."
        }
        if (@($primaryManifest.parts).Count -ne 968) {
            Add-ValidationError (
                "Primary checkpoint manifest expected 968 part records, " +
                "found $(@($primaryManifest.parts).Count)."
            )
        }
        [int64] $declaredRowCount = 0
        for ($index = 0; $index -lt @($primaryManifest.parts).Count; $index++) {
            $partRecord = @($primaryManifest.parts)[$index]
            $expectedName = "part-{0:D5}.parquet" -f $index
            if ([string] $partRecord.path -cne $expectedName) {
                Add-ValidationError (
                    "Primary checkpoint manifest is not contiguous at ${index}: " +
                    "$($partRecord.path)."
                )
                break
            }
            $partPath = Join-Path $checkpointRoot $expectedName
            if (-not (Test-Path -LiteralPath $partPath -PathType Leaf)) {
                Add-ValidationError "Primary checkpoint part is missing: $expectedName"
                continue
            }
            $observedHash = (Get-FileHash -LiteralPath $partPath -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($observedHash -cne ([string] $partRecord.sha256).ToLowerInvariant()) {
                Add-ValidationError "Primary checkpoint SHA-256 differs: $expectedName"
            }
            $declaredRowCount += [int64] $partRecord.row_count
        }
        if ($declaredRowCount -ne [int64] $primaryManifest.row_count) {
            Add-ValidationError "Primary checkpoint manifest row_count does not equal its part sum."
        }
    }
    catch {
        Add-ValidationError "Primary checkpoint manifest is unreadable: $($_.Exception.Message)"
    }
}

$tier3Root = Join-Path $checkpointRoot "tier3-evaluation"
$tier3Manifests = @(
    Get-ChildItem -LiteralPath $tier3Root -Force -File -Filter "*.json" `
        -ErrorAction SilentlyContinue |
        Sort-Object Name
)
$tier3Parts = @(
    Get-ChildItem -LiteralPath $tier3Root -Force -File -Filter "*.parquet" `
        -ErrorAction SilentlyContinue |
        Sort-Object Name
)
if ($tier3Manifests.Count -ne 26 -or $tier3Parts.Count -ne 26) {
    Add-ValidationError (
        "Tier 3 checkpoint expected 26 manifests and 26 Parquet parts; " +
        "found manifests=$($tier3Manifests.Count), parts=$($tier3Parts.Count)."
    )
}
$referencedTier3Parts = @{}
$tier3Identity = $null
foreach ($manifestFile in $tier3Manifests) {
    try {
        $manifest = Get-Content -Raw -LiteralPath $manifestFile.FullName | ConvertFrom-Json
        $partName = [string] $manifest.path
        if (
            [System.IO.Path]::GetFileName($partName) -cne $partName -or
            $partName -notmatch '^[A-Za-z0-9_.-]+\.parquet$'
        ) {
            Add-ValidationError "Tier 3 manifest has an unsafe part path: $($manifestFile.Name)"
            continue
        }
        $partPath = Join-Path $tier3Root $partName
        if (-not (Test-Path -LiteralPath $partPath -PathType Leaf)) {
            Add-ValidationError "Tier 3 checkpoint part is missing: $partName"
            continue
        }
        $observedHash = (Get-FileHash -LiteralPath $partPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($observedHash -cne ([string] $manifest.sha256).ToLowerInvariant()) {
            Add-ValidationError "Tier 3 checkpoint SHA-256 differs: $partName"
        }
        $referencedTier3Parts[$partName] = $true
        $identity = (
            "$($manifest.schema_version)|$($manifest.experiment_run_id)|" +
            "$($manifest.configuration_hash)|$($manifest.preregistration_hash)"
        )
        if ($null -eq $tier3Identity) {
            $tier3Identity = $identity
        }
        elseif ($tier3Identity -cne $identity) {
            Add-ValidationError "Tier 3 checkpoint identities are inconsistent."
        }
        if (
            $null -ne $primaryManifest -and
            (
                [string] $manifest.experiment_run_id -cne [string] $primaryManifest.experiment_run_id -or
                [string] $manifest.configuration_hash -cne [string] $primaryManifest.configuration_hash
            )
        ) {
            Add-ValidationError "Tier 3 checkpoint identity differs from the primary checkpoint."
        }
    }
    catch {
        Add-ValidationError "Tier 3 manifest is unreadable: $($manifestFile.Name): $($_.Exception.Message)"
    }
}
foreach ($part in $tier3Parts) {
    if (-not $referencedTier3Parts.ContainsKey($part.Name)) {
        Add-ValidationError "Tier 3 checkpoint has an unreferenced part: $($part.Name)"
    }
}

$parquetProbe = @'
import json
import sys
from pathlib import Path

import pyarrow.parquet as pq

root = Path(sys.argv[1]).resolve(strict=True)
errors = []
count = 0
for path in sorted(root.rglob('*.parquet')):
    try:
        parquet = pq.ParquetFile(path)
        _ = parquet.schema_arrow
        count += 1
    except Exception as exc:
        errors.append({'path': path.relative_to(root).as_posix(), 'error': str(exc)})
print(json.dumps({'parquet_file_count': count, 'errors': errors}, sort_keys=True))
raise SystemExit(1 if errors else 0)
'@
$parquetOutput = @(
    & $uvCommand.Source run python -c $parquetProbe $stagingPath 2>&1
)
$parquetExitCode = $LASTEXITCODE
$parquetText = $parquetOutput -join [Environment]::NewLine
$parquetReadability = $null
try {
    $parquetReadability = $parquetText | ConvertFrom-Json
}
catch {
    $parquetReadability = [ordered] @{ raw_output = $parquetText }
}
if ($parquetExitCode -ne 0) {
    Add-ValidationError "One or more staged Parquet files are unreadable."
}

$stagingReport = [ordered] @{
    mode = "staging"
    validated_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
    staging_path = $stagingPath
    governed_canonical_output = $canonicalOutput
    canonical_output_exists = $false
    artifact_partition_counts = $artifactPartCounts
    aligned_candidate_partition_counts = $alignedCandidateCounts
    checkpoint_counts = [ordered] @{
        primary_parts = $primaryParts.Count
        primary_manifests = [int] (Test-Path -LiteralPath $primaryManifestPath -PathType Leaf)
        tier3_parts = $tier3Parts.Count
        tier3_manifests = $tier3Manifests.Count
    }
    checkpoint_hashes_verified = ($validationErrors.Count -eq 0)
    parquet_readability = $parquetReadability
    report_prerequisites = $reportPrerequisites
    required_report_prerequisites_valid = ($missingReportPrerequisites.Count -eq 0)
    missing_report_prerequisites = $missingReportPrerequisites
    first_run_reference_exists = [bool] $reportPrerequisites[
        "data/processed/lexical/m7-first-run-reference/table-hashes.json"
    ]
    repair_attempted = $false
    deletion_attempted = $false
    errors = @($validationErrors)
    passed = ($validationErrors.Count -eq 0 -and $parquetExitCode -eq 0)
}
$stagingReport | ConvertTo-Json -Depth 12
if (-not $stagingReport.passed) {
    exit 1
}
exit 0
