#requires -Version 5.1

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string] $Server,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string] $HostKeyFingerprint,

    [string] $User = "root",

    [ValidateRange(1, 65535)]
    [int] $Port = 22,

    [string] $ProjectRoot = "",

    [string] $ManifestPath = "",

    [string] $RemoteRoot = "/srv/project-echoes/repo",

    [string] $RemoteStateRoot = "/var/lib/project-echoes/m7",

    [string] $PrivateKeyPath = "",

    [switch] $Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-FullPath {
    param(
        [Parameter(Mandatory = $true)][string] $Path,
        [Parameter(Mandatory = $true)][string] $BasePath
    )
    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $BasePath $Path))
}

function Get-ObjectProperty {
    param(
        [Parameter(Mandatory = $true)][object] $InputObject,
        [Parameter(Mandatory = $true)][string[]] $Names
    )
    foreach ($name in $Names) {
        $property = $InputObject.PSObject.Properties[$name]
        if ($null -ne $property) {
            return $property.Value
        }
    }
    return $null
}

function Find-WinSCPAssembly {
    $candidates = New-Object System.Collections.Generic.List[string]
    if (-not [string]::IsNullOrWhiteSpace($env:WINSCP_PATH)) {
        $candidates.Add((Join-Path $env:WINSCP_PATH "WinSCPnet.dll"))
    }
    if (-not [string]::IsNullOrWhiteSpace(${env:ProgramFiles(x86)})) {
        $candidates.Add((Join-Path ${env:ProgramFiles(x86)} "WinSCP\WinSCPnet.dll"))
    }
    if (-not [string]::IsNullOrWhiteSpace($env:ProgramFiles)) {
        $candidates.Add((Join-Path $env:ProgramFiles "WinSCP\WinSCPnet.dll"))
    }
    $command = Get-Command "WinSCP.exe" -CommandType Application -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        $candidates.Add((Join-Path (Split-Path -Parent $command.Source) "WinSCPnet.dll"))
    }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return [System.IO.Path]::GetFullPath($candidate)
        }
    }
    throw (
        "WinSCP is required for resumable, host-key-verified transfer. " +
        "Install WinSCP, then rerun this command; no fallback will weaken transfer safety."
    )
}

function Convert-BytesToHex {
    param([Parameter(Mandatory = $true)][byte[]] $Bytes)
    return ([System.BitConverter]::ToString($Bytes)).Replace("-", "").ToLowerInvariant()
}

function Test-RemoteFileMatches {
    param(
        [Parameter(Mandatory = $true)][object] $Session,
        [Parameter(Mandatory = $true)][string] $RemotePath,
        [Parameter(Mandatory = $true)][int64] $ExpectedSize,
        [Parameter(Mandatory = $true)][string] $ExpectedHash
    )
    try {
        $remoteInfo = $Session.GetFileInfo($RemotePath)
        if ([int64] $remoteInfo.Length -ne $ExpectedSize) {
            return $false
        }
        try {
            $remoteHash = Convert-BytesToHex `
                -Bytes $Session.CalculateFileChecksum("sha-256", $RemotePath)
            return [string]::Equals(
                $remoteHash,
                $ExpectedHash,
                [System.StringComparison]::OrdinalIgnoreCase
            )
        }
        catch {
            # OpenSSH servers do not all expose an SFTP SHA-256 extension. The
            # path grammar below makes this exact shell fallback non-injectable.
            $checksum = $Session.ExecuteCommand("sha256sum -- '$RemotePath'")
            if ($checksum.ExitCode -ne 0) {
                return $false
            }
            $observed = ($checksum.Output -split "\s+")[0]
            return [string]::Equals(
                $observed,
                $ExpectedHash,
                [System.StringComparison]::OrdinalIgnoreCase
            )
        }
    }
    catch {
        return $false
    }
}

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$ProjectRoot = Get-FullPath -Path $ProjectRoot -BasePath (Get-Location).Path
if ([string]::IsNullOrWhiteSpace($ManifestPath)) {
    $ManifestPath = Join-Path $ProjectRoot "cloud\transfer-manifest.json"
}
$ManifestPath = Get-FullPath -Path $ManifestPath -BasePath $ProjectRoot
if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
    throw "Transfer manifest does not exist: $ManifestPath"
}
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot "docs\master-plan.md") -PathType Leaf)) {
    throw "Project root is not Project Echoes: $ProjectRoot"
}
if ($RemoteRoot -notmatch '^/[A-Za-z0-9._/-]+$' -or $RemoteRoot.Contains("..")) {
    throw "RemoteRoot must be a safe absolute POSIX path: $RemoteRoot"
}
if ($RemoteStateRoot -notmatch '^/[A-Za-z0-9._/-]+$' -or $RemoteStateRoot.Contains("..")) {
    throw "RemoteStateRoot must be a safe absolute POSIX path: $RemoteStateRoot"
}
if ($Server -notmatch '^[A-Za-z0-9.:-]+$') {
    throw "Server contains unsupported characters."
}
if ($User -notmatch '^[A-Za-z_][A-Za-z0-9_-]*$') {
    throw "User contains unsupported characters."
}
if ($User -ne "root") {
    throw "The governed upload requires root to verify protected rebind state."
}

$manifest = Get-Content -Raw -LiteralPath $ManifestPath | ConvertFrom-Json
if ([int] $manifest.schema_version -ne 1) {
    throw "Transfer manifest schema_version must be exactly 1."
}
$repositoryProperty = $manifest.PSObject.Properties["repository"]
$repositoryPolicy = if ($null -eq $repositoryProperty) { $null } else {
    $repositoryProperty.Value
}
if (
    $null -eq $repositoryPolicy -or
    [string] $repositoryPolicy.commit_policy -ne "operator_supplied" -or
    [string]::IsNullOrWhiteSpace([string] $repositoryPolicy.branch) -or
    $null -ne $repositoryPolicy.PSObject.Properties["commit"]
) {
    throw "Transfer manifest repository policy must use branch plus operator_supplied commit."
}
$currentBranch = (& git -C $ProjectRoot branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or $currentBranch -ne [string] $repositoryPolicy.branch) {
    throw "Local branch differs from the transfer-manifest branch."
}
$rawFiles = Get-ObjectProperty -InputObject $manifest -Names @("files", "entries")
if ($null -eq $rawFiles -or @($rawFiles).Count -eq 0) {
    throw "Transfer manifest files must be nonempty."
}
$declaredTotal = Get-ObjectProperty `
    -InputObject $manifest `
    -Names @("total_upload_bytes", "required_upload_bytes")
if ($null -eq $declaredTotal) {
    throw "Transfer manifest lacks total_upload_bytes."
}

$projectPrefix = $ProjectRoot.TrimEnd('\') + '\'
$entries = New-Object System.Collections.Generic.List[object]
$seen = @{}
[int64] $observedTotal = 0
foreach ($rawEntry in @($rawFiles)) {
    $required = Get-ObjectProperty -InputObject $rawEntry -Names @("transfer", "required")
    if ($null -ne $required -and -not [bool] $required) {
        continue
    }
    $relative = [string] (Get-ObjectProperty -InputObject $rawEntry -Names @("path", "relative_path"))
    $sizeValue = Get-ObjectProperty -InputObject $rawEntry -Names @("size_bytes", "byte_size")
    $digest = [string] (Get-ObjectProperty -InputObject $rawEntry -Names @("sha256"))
    $classification = [string] (
        Get-ObjectProperty -InputObject $rawEntry -Names @("classification")
    )
    if (
        [string]::IsNullOrWhiteSpace($relative) -or
        $relative.Contains('\') -or
        $relative -notmatch '^[A-Za-z0-9._/-]+$' -or
        $relative.StartsWith('/') -or
        $relative -match '(^|/)\.\.?(/|$)'
    ) {
        throw "Unsafe or noncanonical manifest path: $relative"
    }
    if ($seen.ContainsKey($relative)) {
        throw "Duplicate manifest path: $relative"
    }
    $seen[$relative] = $true
    if ($classification -notin @("required", "recoverable_checkpoint", "final_output")) {
        throw "Unsupported transferable classification '$classification': $relative"
    }
    [int64] $expectedSize = $sizeValue
    if ($expectedSize -lt 0 -or $digest -cnotmatch '^[0-9a-f]{64}$') {
        throw "Invalid size or SHA-256 for $relative"
    }
    $localPath = Get-FullPath `
        -Path ($relative.Replace('/', [System.IO.Path]::DirectorySeparatorChar)) `
        -BasePath $ProjectRoot
    if (
        -not $localPath.StartsWith($projectPrefix, [System.StringComparison]::OrdinalIgnoreCase) -or
        -not (Test-Path -LiteralPath $localPath -PathType Leaf)
    ) {
        throw "Manifest file is absent or escaped the project root: $relative"
    }
    $item = Get-Item -Force -LiteralPath $localPath
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Manifest payload may not contain reparse points: $relative"
    }
    if ([int64] $item.Length -ne $expectedSize) {
        throw "Size mismatch for $relative"
    }
    $localHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $localPath).Hash.ToLowerInvariant()
    if (-not [string]::Equals(
        $localHash,
        $digest,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "SHA-256 mismatch for $relative"
    }
    $observedTotal += $expectedSize
    $entries.Add([pscustomobject] @{
        Relative = $relative
        LocalPath = $localPath
        Size = $expectedSize
        Hash = $digest.ToLowerInvariant()
    })
}
if ($observedTotal -ne [int64] $declaredTotal) {
    throw "Manifest total mismatch: declared=$declaredTotal observed=$observedTotal"
}

$assemblyPath = Find-WinSCPAssembly
Add-Type -Path $assemblyPath
$sessionOptions = New-Object WinSCP.SessionOptions
$sessionOptions.Protocol = [WinSCP.Protocol]::Sftp
$sessionOptions.HostName = $Server
$sessionOptions.UserName = $User
$sessionOptions.PortNumber = $Port
$sessionOptions.SshHostKeyFingerprint = $HostKeyFingerprint
if (-not [string]::IsNullOrWhiteSpace($PrivateKeyPath)) {
    $sessionOptions.SshPrivateKeyPath = Get-FullPath `
        -Path $PrivateKeyPath `
        -BasePath (Get-Location).Path
}

$session = New-Object WinSCP.Session
try {
    $session.Open($sessionOptions)
    $rebindState = $session.ExecuteCommand(
        "test -e '$RemoteStateRoot/database-rebind.json' || " +
        "find '$RemoteStateRoot' -maxdepth 1 -type f " +
        "-name 'passage-view-rebind*.json.intent.json' -print -quit 2>/dev/null | grep -q ."
    )
    if ($rebindState.ExitCode -eq 0) {
        throw (
            "The server already has a governed database-rebind state. " +
            "Refusing to restore the original database over that state."
        )
    }
    $rootResult = $session.ExecuteCommand("mkdir -p -- '$RemoteRoot/cloud'")
    if ($rootResult.ExitCode -ne 0) {
        throw "Could not create remote root: $($rootResult.ErrorOutput)"
    }

    $transferOptions = New-Object WinSCP.TransferOptions
    $transferOptions.TransferMode = [WinSCP.TransferMode]::Binary
    $transferOptions.PreserveTimestamp = $true
    $transferOptions.ResumeSupport.State = [WinSCP.TransferResumeSupportState]::On

    $remoteManifest = "$RemoteRoot/cloud/transfer-manifest.json"
    $session.PutFiles($ManifestPath, $remoteManifest, $false, $transferOptions).Check()

    $directories = @{}
    foreach ($entry in $entries) {
        $remotePath = "$RemoteRoot/$($entry.Relative)"
        $remoteDirectory = $remotePath.Substring(0, $remotePath.LastIndexOf('/'))
        $directories[$remoteDirectory] = $true
    }
    foreach ($remoteDirectory in @($directories.Keys | Sort-Object { $_.Length })) {
        $mkdirResult = $session.ExecuteCommand("mkdir -p -- '$remoteDirectory'")
        if ($mkdirResult.ExitCode -ne 0) {
            throw "Could not create remote directory $remoteDirectory"
        }
    }

    [int] $uploaded = 0
    [int] $reused = 0
    foreach ($entry in $entries) {
        $remotePath = "$RemoteRoot/$($entry.Relative)"
        $matches = $false
        if (-not $Force) {
            $matches = Test-RemoteFileMatches `
                -Session $session `
                -RemotePath $remotePath `
                -ExpectedSize $entry.Size `
                -ExpectedHash $entry.Hash
        }
        if ($matches) {
            $reused += 1
            continue
        }
        $session.PutFiles(
            $entry.LocalPath,
            $remotePath,
            $false,
            $transferOptions
        ).Check()
        $uploaded += 1
    }

    $verifyCommand = (
        "bash '$RemoteRoot/cloud/verify_transfer.sh' " +
        "--root '$RemoteRoot' --manifest '$remoteManifest' --json"
    )
    $verification = $session.ExecuteCommand($verifyCommand)
    if ($verification.ExitCode -ne 0) {
        throw (
            "Remote SHA-256 verification failed. No pipeline was launched.`n" +
            $verification.Output + "`n" + $verification.ErrorOutput
        )
    }
    $remoteReport = $verification.Output | ConvertFrom-Json
    if (-not [bool] $remoteReport.passed) {
        throw "Remote verification report did not pass."
    }
    [pscustomobject] @{
        server = $Server
        remote_root = $RemoteRoot
        manifest = $ManifestPath
        declared_upload_bytes = [int64] $declaredTotal
        verified_file_count = [int] $remoteReport.verified_file_count
        uploaded_file_count = $uploaded
        reused_verified_file_count = $reused
        remote_verification_passed = $true
    } | ConvertTo-Json -Depth 5
}
finally {
    $session.Dispose()
}
