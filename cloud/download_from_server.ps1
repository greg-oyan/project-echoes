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

    [string] $RemotePackage = "",

    [string] $RemoteStateRoot = "/var/lib/project-echoes/m7",

    [string] $DestinationDirectory = "",

    [string] $PrivateKeyPath = ""
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
        "Install WinSCP, then rerun this command."
    )
}

function Convert-BytesToHex {
    param([Parameter(Mandatory = $true)][byte[]] $Bytes)
    return ([System.BitConverter]::ToString($Bytes)).Replace("-", "").ToLowerInvariant()
}

function Get-RemoteSha256 {
    param(
        [Parameter(Mandatory = $true)][object] $Session,
        [Parameter(Mandatory = $true)][string] $RemotePath
    )
    try {
        return Convert-BytesToHex `
            -Bytes $Session.CalculateFileChecksum("sha-256", $RemotePath)
    }
    catch {
        # OpenSSH does not always advertise an SFTP checksum extension. The
        # remote-path grammar enforced below makes this fallback non-injectable.
        $checksum = $Session.ExecuteCommand("sha256sum -- '$RemotePath'")
        if ($checksum.ExitCode -ne 0) {
            throw "Could not calculate remote SHA-256: $($checksum.ErrorOutput)"
        }
        $observed = ($checksum.Output -split "\s+")[0].ToLowerInvariant()
        if ($observed -notmatch '^[0-9a-f]{64}$') {
            throw "Remote sha256sum returned a malformed digest."
        }
        return $observed
    }
}

if ($Server -notmatch '^[A-Za-z0-9.:-]+$') {
    throw "Server contains unsupported characters."
}
if ($User -notmatch '^[A-Za-z_][A-Za-z0-9_-]*$') {
    throw "User contains unsupported characters."
}
if ($User -ne "root") {
    throw "The governed download requires root to read protected result packages."
}
if ($RemoteStateRoot -notmatch '^/[A-Za-z0-9._/-]+$' -or $RemoteStateRoot.Contains("..")) {
    throw "RemoteStateRoot must be a safe absolute POSIX path."
}
if (
    -not [string]::IsNullOrWhiteSpace($RemotePackage) -and
    ($RemotePackage -notmatch '^/[A-Za-z0-9._/-]+$' -or $RemotePackage.Contains(".."))
) {
    throw "RemotePackage must be a safe absolute POSIX path."
}
if ([string]::IsNullOrWhiteSpace($DestinationDirectory)) {
    $DestinationDirectory = Join-Path `
        ([Environment]::GetFolderPath("UserProfile")) `
        "Downloads\project-echoes-m7"
}
$DestinationDirectory = Get-FullPath `
    -Path $DestinationDirectory `
    -BasePath (Get-Location).Path
if (-not (Test-Path -LiteralPath $DestinationDirectory -PathType Container)) {
    New-Item -ItemType Directory -Path $DestinationDirectory -Force | Out-Null
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
    if ([string]::IsNullOrWhiteSpace($RemotePackage)) {
        $pointerPath = "$RemoteStateRoot/latest-review-package.txt"
        $pointer = $session.ExecuteCommand("cat -- '$pointerPath'")
        if ($pointer.ExitCode -ne 0) {
            throw (
                "Remote review-package pointer is unavailable. Run package_results.sh first: " +
                $pointer.ErrorOutput
            )
        }
        $RemotePackage = $pointer.Output.Trim()
    }
    if ($RemotePackage -notmatch '^/[A-Za-z0-9._/-]+$' -or $RemotePackage.Contains("..")) {
        throw "Remote package pointer returned an unsafe path: $RemotePackage"
    }
    if (-not $RemotePackage.EndsWith(".tar.zst", [System.StringComparison]::Ordinal)) {
        throw "Refusing a remote object that is not an M7 .tar.zst review package."
    }

    $remoteInfo = $session.GetFileInfo($RemotePackage)
    $remoteHash = Get-RemoteSha256 -Session $session -RemotePath $RemotePackage
    $leaf = [System.IO.Path]::GetFileName($RemotePackage)
    $target = Join-Path $DestinationDirectory $leaf
    $partial = Join-Path $DestinationDirectory (".$leaf.filepart")
    $checksumPath = "$target.sha256"

    if (Test-Path -LiteralPath $target) {
        $localItem = Get-Item -LiteralPath $target
        $localHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash.ToLowerInvariant()
        if (
            [int64] $localItem.Length -eq [int64] $remoteInfo.Length -and
            [string]::Equals(
                $localHash,
                $remoteHash,
                [System.StringComparison]::OrdinalIgnoreCase
            )
        ) {
            [pscustomobject] @{
                downloaded = $false
                already_present = $true
                local_path = $target
                size_bytes = [int64] $localItem.Length
                sha256 = $localHash
            } | ConvertTo-Json
            exit 0
        }
        throw (
            "A different local archive already uses the target name. " +
            "It was not overwritten: $target"
        )
    }

    $transferOptions = New-Object WinSCP.TransferOptions
    $transferOptions.TransferMode = [WinSCP.TransferMode]::Binary
    $transferOptions.PreserveTimestamp = $true
    $transferOptions.ResumeSupport.State = [WinSCP.TransferResumeSupportState]::On
    $session.GetFiles(
        $RemotePackage,
        $partial,
        $false,
        $transferOptions
    ).Check()

    $partialItem = Get-Item -LiteralPath $partial
    $partialHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $partial).Hash.ToLowerInvariant()
    if (
        [int64] $partialItem.Length -ne [int64] $remoteInfo.Length -or
        -not [string]::Equals(
            $partialHash,
            $remoteHash,
            [System.StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw (
            "Downloaded package failed size/SHA-256 verification. " +
            "The resumable partial file was preserved: $partial"
        )
    }
    [System.IO.File]::Move($partial, $target)
    $checksumContent = "$remoteHash  $leaf`n"
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($checksumPath, $checksumContent, $encoding)

    [pscustomobject] @{
        downloaded = $true
        already_present = $false
        local_path = $target
        checksum_path = $checksumPath
        size_bytes = [int64] $remoteInfo.Length
        sha256 = $remoteHash
    } | ConvertTo-Json
}
finally {
    $session.Dispose()
}
