[CmdletBinding()]
param([string]$OutputRoot = "")

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $MyInvocation.MyCommand.Path)).Path
if (-not $OutputRoot) { $OutputRoot = Join-Path $projectRoot "release" }
$outputFull = [System.IO.Path]::GetFullPath($OutputRoot)
if (-not $outputFull.StartsWith($projectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputRoot must be inside the project directory."
}
$version = (python -c "from mora_cutter import __version__; print(__version__)").Trim()
$name = "MoraCutter-v$version-Source"
$folder = Join-Path $outputFull $name
$zip = Join-Path $outputFull "$name.zip"
if ((Test-Path $folder) -or (Test-Path $zip)) { throw "Source package output already exists: $folder or $zip" }
New-Item -ItemType Directory -Force -Path $folder | Out-Null
$tracked = git -C $projectRoot ls-files
if ($LASTEXITCODE -ne 0) { throw "git ls-files failed." }
foreach ($relative in $tracked) {
    if ($relative -match '^(release|ref)/' -or $relative -eq 'recent_projects.json') { continue }
    $source = Join-Path $projectRoot $relative
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { continue }
    $target = Join-Path $folder $relative
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    Copy-Item -LiteralPath $source -Destination $target
}
Compress-Archive -LiteralPath $folder -DestinationPath $zip -CompressionLevel Optimal
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $zip).Hash
Set-Content -LiteralPath (Join-Path $outputFull "$name.sha256.txt") -Value "$hash  $name.zip" -Encoding ascii
Write-Output "Source package: $zip"
