[CmdletBinding()]
param(
    [string]$Python = "python",
    [string]$OutputRoot = "",
    [string]$CertificateThumbprint = "",
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $projectRoot "release"
}
$distRoot = Join-Path $OutputRoot "dist"
$workRoot = Join-Path $OutputRoot "build"
$portableRoot = Join-Path $distRoot "MoraCutter"

& $Python -m pip install --disable-pip-version-check --upgrade `
    -r (Join-Path $projectRoot "requirements.txt") `
    -r (Join-Path $projectRoot "requirements-whisper.txt") `
    "pyinstaller>=6.0"
if ($LASTEXITCODE -ne 0) { throw "Python dependencies could not be installed." }

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --distpath $distRoot `
    --workpath $workRoot `
    (Join-Path $projectRoot "MoraCutter.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

$binRoot = Join-Path $portableRoot "bin"
New-Item -ItemType Directory -Force -Path $binRoot | Out-Null
foreach ($toolName in @("ffmpeg.exe", "ffprobe.exe", "ffplay.exe")) {
    $tool = Get-Command $toolName -ErrorAction Stop
    Copy-Item -LiteralPath $tool.Source -Destination (Join-Path $binRoot $toolName) -Force
}
Copy-Item -LiteralPath (Join-Path $projectRoot "README.md") -Destination $portableRoot -Force
New-Item -ItemType Directory -Force -Path (Join-Path $portableRoot "models") | Out-Null

$application = Join-Path $portableRoot "MoraCutter.exe"
if ($CertificateThumbprint) {
    & (Join-Path $projectRoot "sign_windows.ps1") `
        -Executable $application `
        -CertificateThumbprint $CertificateThumbprint `
        -TimestampUrl $TimestampUrl
    if ($LASTEXITCODE -ne 0) { throw "Code signing failed." }
} else {
    Write-Warning "The executable is unsigned. Supply -CertificateThumbprint after obtaining a trusted code-signing certificate."
}

$hash = Get-FileHash -Algorithm SHA256 -LiteralPath $application
$hashLine = "$($hash.Hash)  MoraCutter.exe"
Set-Content -LiteralPath (Join-Path $portableRoot "SHA256SUMS.txt") -Value $hashLine -Encoding ascii
Write-Output "Build completed: $portableRoot"
Write-Output $hashLine
