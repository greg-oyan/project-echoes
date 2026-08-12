#requires -Version 5.1

[CmdletBinding()]
param(
    [string] $ProjectRoot = "",
    [ValidateRange(1, 200)]
    [int] $LogTailLines = 20
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-AbsolutePath {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path,
        [Parameter(Mandatory = $true)]
        [string] $BasePath
    )

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $BasePath $Path))
}

function Get-DirectorySize {
    param([Parameter(Mandatory = $true)][string] $Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        return [int64] 0
    }
    [int64] $total = 0
    foreach ($file in Get-ChildItem -LiteralPath $Path -Recurse -Force -File -ErrorAction SilentlyContinue) {
        $total += [int64] $file.Length
    }
    return $total
}

function Get-PartitionCounts {
    param([Parameter(Mandatory = $true)][string] $Path)

    $counts = [ordered] @{}
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        return $counts
    }
    foreach ($directory in Get-ChildItem -LiteralPath $Path -Force -Directory) {
        if ($directory.Name.StartsWith(".")) {
            continue
        }
        $counts[$directory.Name] = @(
            Get-ChildItem -LiteralPath $directory.FullName -Force -File -Filter "part-*.parquet" `
                -ErrorAction SilentlyContinue
        ).Count
    }
    return $counts
}

function Get-LogTail {
    param(
        [string] $Path,
        [int] $Lines
    )

    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return @()
    }
    return @(Get-Content -LiteralPath $Path -Tail $Lines -ErrorAction SilentlyContinue)
}

function Write-Utf8Text {
    param(
        [Parameter(Mandatory = $true)][string] $Path,
        [Parameter(Mandatory = $true)][string] $Content
    )

    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $encoding)
}

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$ProjectRoot = Get-AbsolutePath -Path $ProjectRoot -BasePath (Get-Location).Path
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot "docs/master-plan.md") -PathType Leaf)) {
    throw "Project root is not Project Echoes: $ProjectRoot"
}

$canonicalOutput = Get-AbsolutePath `
    -Path "data/processed/lexical/schema-v1" `
    -BasePath $ProjectRoot
$lexicalParent = Split-Path -Parent $canonicalOutput
$stateDirectory = Get-AbsolutePath -Path "data/interim/m7-runs" -BasePath $ProjectRoot
$latestLaunchStatePath = Join-Path $stateDirectory "latest.json"
$previousStatusPath = Join-Path $stateDirectory "status-latest.json"

$previousByPid = @{}
if (Test-Path -LiteralPath $previousStatusPath -PathType Leaf) {
    try {
        $previousStatus = Get-Content -Raw -LiteralPath $previousStatusPath | ConvertFrom-Json
        foreach ($entry in @($previousStatus.processes)) {
            $previousByPid[[string] $entry.process_id] = $entry
        }
    }
    catch {
        Write-Warning "Previous status snapshot is unreadable; CPU deltas are unavailable: $($_.Exception.Message)"
    }
}

$matchingProcesses = @(
    Get-CimInstance Win32_Process -ErrorAction Stop |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine -match '(?i)(^|[\s"])run-lexical-pipeline([\s"]|$)'
        }
)
$processReports = @()
foreach ($cimProcess in $matchingProcesses) {
    $runtimeProcess = Get-Process -Id $cimProcess.ProcessId -ErrorAction SilentlyContinue
    if ($null -eq $runtimeProcess) {
        continue
    }
    try {
        $startTime = [DateTimeOffset] $runtimeProcess.StartTime
        $cpuSeconds = [double] $runtimeProcess.CPU
        $creationKey = $startTime.ToUniversalTime().ToString("o")
        $cpuDelta = $null
        $previous = $previousByPid[[string] $cimProcess.ProcessId]
        if (
            $null -ne $previous -and
            [string] $previous.creation_time_utc -eq $creationKey -and
            $null -ne $previous.cpu_seconds
        ) {
            $cpuDelta = [Math]::Max(0.0, $cpuSeconds - [double] $previous.cpu_seconds)
        }
        $processReports += [ordered] @{
            process_id = [int] $cimProcess.ProcessId
            parent_process_id = [int] $cimProcess.ParentProcessId
            creation_time_utc = $creationKey
            elapsed_seconds = [Math]::Max(
                0.0,
                ([DateTimeOffset]::Now - $startTime).TotalSeconds
            )
            cpu_seconds = $cpuSeconds
            cpu_delta_seconds = $cpuDelta
            working_set_bytes = [int64] $runtimeProcess.WorkingSet64
            private_memory_bytes = [int64] $runtimeProcess.PrivateMemorySize64
            command_line = [string] $cimProcess.CommandLine
        }
    }
    catch {
        Write-Warning "Process $($cimProcess.ProcessId) ended during the one-shot census."
    }
}

$stagingDirectories = @()
if (Test-Path -LiteralPath $lexicalParent -PathType Container) {
    $stagingDirectories = @(
        Get-ChildItem -LiteralPath $lexicalParent -Force -Directory |
            Where-Object { $_.Name -match '^\.schema-v1\.writing-[0-9a-fA-F]{32}$' }
    )
}
$stagingReports = @()
foreach ($staging in $stagingDirectories) {
    $checkpointRoot = Join-Path $staging.FullName ".resume-primary-candidates"
    $tier3Root = Join-Path $checkpointRoot "tier3-evaluation"
    $stagingReports += [ordered] @{
        path = $staging.FullName
        last_write_time_utc = $staging.LastWriteTimeUtc.ToString("o")
        disk_usage_bytes = Get-DirectorySize -Path $staging.FullName
        output_partition_counts = Get-PartitionCounts -Path $staging.FullName
        output_parquet_count = @(
            Get-ChildItem -LiteralPath $staging.FullName -Recurse -Force -File -Filter "*.parquet" |
                Where-Object { $_.FullName -notlike "$checkpointRoot*" }
        ).Count
        primary_checkpoint_part_count = @(
            Get-ChildItem -LiteralPath $checkpointRoot -Force -File -Filter "part-*.parquet" `
                -ErrorAction SilentlyContinue
        ).Count
        primary_checkpoint_manifest_exists = Test-Path `
            -LiteralPath (Join-Path $checkpointRoot "complete.json") `
            -PathType Leaf
        tier3_checkpoint_part_count = @(
            Get-ChildItem -LiteralPath $tier3Root -Force -File -Filter "*.parquet" `
                -ErrorAction SilentlyContinue
        ).Count
        tier3_checkpoint_manifest_count = @(
            Get-ChildItem -LiteralPath $tier3Root -Force -File -Filter "*.json" `
                -ErrorAction SilentlyContinue
        ).Count
    }
}

$stdoutPath = ""
$stderrPath = ""
if (Test-Path -LiteralPath $latestLaunchStatePath -PathType Leaf) {
    try {
        $launchState = Get-Content -Raw -LiteralPath $latestLaunchStatePath | ConvertFrom-Json
        $stdoutPath = [string] $launchState.stdout_path
        $stderrPath = [string] $launchState.stderr_path
    }
    catch {
        Write-Warning "Latest launch state is unreadable: $($_.Exception.Message)"
    }
}
if ([string]::IsNullOrWhiteSpace($stdoutPath)) {
    $latestStdout = Get-ChildItem -LiteralPath (Join-Path $ProjectRoot "data/interim") `
        -Force -File -Filter "m7*.stdout.log" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -ne $latestStdout) {
        $stdoutPath = $latestStdout.FullName
    }
}
if ([string]::IsNullOrWhiteSpace($stderrPath)) {
    $latestStderr = Get-ChildItem -LiteralPath (Join-Path $ProjectRoot "data/interim") `
        -Force -File -Filter "m7*.stderr.log" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -ne $latestStderr) {
        $stderrPath = $latestStderr.FullName
    }
}

$drive = New-Object System.IO.DriveInfo([System.IO.Path]::GetPathRoot($canonicalOutput))
$report = [ordered] @{
    inspected_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
    project_root = $ProjectRoot
    process_match = "run-lexical-pipeline"
    matching_process_count = $processReports.Count
    processes = $processReports
    canonical_output = [ordered] @{
        path = $canonicalOutput
        schema_v1_exists = Test-Path -LiteralPath $canonicalOutput -PathType Container
        disk_usage_bytes = Get-DirectorySize -Path $canonicalOutput
        output_partition_counts = Get-PartitionCounts -Path $canonicalOutput
        parquet_count = @(
            Get-ChildItem -LiteralPath $canonicalOutput -Recurse -Force -File -Filter "*.parquet" `
                -ErrorAction SilentlyContinue
        ).Count
        table_hash_manifest_exists = Test-Path `
            -LiteralPath (Join-Path $canonicalOutput "table-hashes.json") `
            -PathType Leaf
    }
    staging_directory_count = $stagingReports.Count
    staging = $stagingReports
    disk = [ordered] @{
        drive_name = $drive.Name
        available_free_space_bytes = [int64] $drive.AvailableFreeSpace
        total_size_bytes = [int64] $drive.TotalSize
    }
    logs = [ordered] @{
        stdout_path = $stdoutPath
        stdout_tail = Get-LogTail -Path $stdoutPath -Lines $LogTailLines
        stderr_path = $stderrPath
        stderr_tail = Get-LogTail -Path $stderrPath -Lines $LogTailLines
    }
}

if (-not (Test-Path -LiteralPath $stateDirectory -PathType Container)) {
    New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
}
$statusSnapshot = [ordered] @{
    inspected_at_utc = $report.inspected_at_utc
    processes = $processReports
}
Write-Utf8Text `
    -Path $previousStatusPath `
    -Content ($statusSnapshot | ConvertTo-Json -Depth 6)

$report | ConvertTo-Json -Depth 10
