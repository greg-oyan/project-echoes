#requires -Version 5.1

[CmdletBinding()]
param(
    [string] $ProjectRoot = "",
    [string] $Database = "data/processed/project_echoes.duckdb",
    [string] $OutputDirectory = "data/processed/lexical/schema-v1",
    [string] $ResumeStagingDirectory = ""
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

function Format-NativeArgument {
    param([Parameter(Mandatory = $true)][string] $Value)

    if ($Value.Contains('"')) {
        throw "Native command arguments may not contain a quote character."
    }
    if ($Value -match '\s') {
        return '"' + $Value + '"'
    }
    return $Value
}

function Write-NewUtf8Text {
    param(
        [Parameter(Mandatory = $true)][string] $Path,
        [Parameter(Mandatory = $true)][string] $Content
    )

    $encoding = New-Object System.Text.UTF8Encoding($false)
    $stream = New-Object System.IO.FileStream(
        $Path,
        [System.IO.FileMode]::CreateNew,
        [System.IO.FileAccess]::Write,
        [System.IO.FileShare]::Read
    )
    try {
        $writer = New-Object System.IO.StreamWriter($stream, $encoding)
        try {
            $writer.Write($Content)
        }
        finally {
            $writer.Dispose()
        }
    }
    finally {
        $stream.Dispose()
    }
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

$databasePath = Get-AbsolutePath -Path $Database -BasePath $ProjectRoot
$outputPath = Get-AbsolutePath -Path $OutputDirectory -BasePath $ProjectRoot
$canonicalOutput = Get-AbsolutePath `
    -Path "data/processed/lexical/schema-v1" `
    -BasePath $ProjectRoot
if (-not (Test-SamePath -Left $outputPath -Right $canonicalOutput)) {
    throw "Refusing noncanonical lexical output: $outputPath"
}
if (Test-Path -LiteralPath $canonicalOutput) {
    throw "Refusing detached launch because canonical schema-v1 already exists: $canonicalOutput"
}
if (-not (Test-Path -LiteralPath $databasePath -PathType Leaf)) {
    throw "Anchored lexical database does not exist: $databasePath"
}

$liveMatches = @(
    Get-CimInstance Win32_Process -ErrorAction Stop |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine -match '(?i)(^|[\s"])run-lexical-pipeline([\s"]|$)'
        }
)
if ($liveMatches.Count -ne 0) {
    $livePids = ($liveMatches | ForEach-Object { [string] $_.ProcessId }) -join ", "
    throw "Refusing duplicate launch; run-lexical-pipeline is already alive (PID: $livePids)."
}

$outputParent = Split-Path -Parent $canonicalOutput
$stagingCandidates = @(
    Get-ChildItem -LiteralPath $outputParent -Force -Directory -ErrorAction Stop |
        Where-Object { $_.Name -match '^\.schema-v1\.writing-[0-9a-fA-F]{32}$' }
)
if ($stagingCandidates.Count -ne 1) {
    throw (
        "Refusing ambiguous resume: expected exactly one governed .schema-v1.writing-<32 hex> " +
        "sibling, found $($stagingCandidates.Count)."
    )
}
if ([string]::IsNullOrWhiteSpace($ResumeStagingDirectory)) {
    $stagingPath = $stagingCandidates[0].FullName
}
else {
    $stagingPath = Get-AbsolutePath -Path $ResumeStagingDirectory -BasePath $ProjectRoot
    if (-not (Test-SamePath -Left $stagingPath -Right $stagingCandidates[0].FullName)) {
        throw "Refusing resume staging that is not the sole governed candidate: $stagingPath"
    }
}
$stagingItem = Get-Item -LiteralPath $stagingPath -Force
if (
    -not $stagingItem.PSIsContainer -or
    ($stagingItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 -or
    -not (Test-SamePath -Left $stagingItem.Parent.FullName -Right $outputParent) -or
    $stagingItem.Name -notmatch '^\.schema-v1\.writing-[0-9a-fA-F]{32}$'
) {
    throw "Refusing unsafe or unconfined resume staging: $stagingPath"
}
$unsafeEntries = @(
    Get-ChildItem -LiteralPath $stagingPath -Recurse -Force -ErrorAction Stop |
        Where-Object {
            ($_.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
        } |
        Select-Object -First 1
)
if ($unsafeEntries.Count -ne 0) {
    throw "Refusing resume staging containing a reparse point: $($unsafeEntries[0].FullName)"
}
if (Test-Path -LiteralPath (Join-Path $stagingPath "table-hashes.json")) {
    throw "Refusing finalized staging; canonical validation is required instead."
}
if (Test-Path -LiteralPath (Join-Path $stagingPath "lexical_metadata")) {
    throw "Refusing staging that already contains final lexical metadata."
}
$checkpointManifest = Join-Path $stagingPath ".resume-primary-candidates/complete.json"
if (-not (Test-Path -LiteralPath $checkpointManifest -PathType Leaf)) {
    throw "Refusing resume without the governed primary checkpoint manifest: $checkpointManifest"
}

$uvCommand = Get-Command uv -CommandType Application -ErrorAction Stop
$rawArguments = @(
    "run",
    "echoes",
    "run-lexical-pipeline",
    "--primary",
    "--database",
    $databasePath,
    "--output-dir",
    $canonicalOutput,
    "--force",
    "--resume-staging-dir",
    $stagingPath
)
$startArguments = @($rawArguments | ForEach-Object { Format-NativeArgument -Value $_ })
$commandLine = (@("uv") + $startArguments) -join " "

$stateDirectory = Get-AbsolutePath -Path "data/interim/m7-runs" -BasePath $ProjectRoot
if (-not (Test-Path -LiteralPath $stateDirectory -PathType Container)) {
    New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
}
$timestamp = [DateTimeOffset]::UtcNow.ToString("yyyyMMddTHHmmssfffZ")
$stdoutPath = Join-Path $stateDirectory "m7-resume-$timestamp.stdout.log"
$stderrPath = Join-Path $stateDirectory "m7-resume-$timestamp.stderr.log"
$immutableStatePath = Join-Path $stateDirectory "launch-$timestamp.json"
$latestStatePath = Join-Path $stateDirectory "latest.json"
New-Item -ItemType File -Path $stdoutPath -ErrorAction Stop | Out-Null
New-Item -ItemType File -Path $stderrPath -ErrorAction Stop | Out-Null

$startedAt = [DateTimeOffset]::UtcNow
$process = Start-Process `
    -FilePath $uvCommand.Source `
    -ArgumentList $startArguments `
    -WorkingDirectory $ProjectRoot `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -WindowStyle Hidden `
    -PassThru

$state = [ordered] @{
    schema_version = 1
    launch_id = $timestamp
    started_at_utc = $startedAt.ToString("o")
    launcher_pid = [int] $process.Id
    launch_submitted = $true
    command = $commandLine
    executable = $uvCommand.Source
    arguments = $rawArguments
    project_root = $ProjectRoot
    database_path = $databasePath
    output_path = $canonicalOutput
    resume_staging_path = $stagingPath
    checkpoint_path = (Split-Path -Parent $checkpointManifest)
    stdout_path = $stdoutPath
    stderr_path = $stderrPath
    immutable_state_path = $immutableStatePath
    latest_state_path = $latestStatePath
}
$stateJson = $state | ConvertTo-Json -Depth 6
Write-NewUtf8Text -Path $immutableStatePath -Content $stateJson
Write-Utf8Text -Path $latestStatePath -Content $stateJson

$state | ConvertTo-Json -Depth 6
