[CmdletBinding()]
param(
    [string]$Python = "python",
    [ValidateSet("x64", "ARM64")]
    [string]$Architecture = "x64",
    [string]$OutputRoot = "",
    [string]$CertificateThumbprint = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $MyInvocation.MyCommand.Path)).Path
if (-not $OutputRoot) { $OutputRoot = Join-Path $projectRoot "release" }
$outputFull = [System.IO.Path]::GetFullPath($OutputRoot)
if (-not $outputFull.StartsWith($projectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputRoot must be inside the project directory: $projectRoot"
}

$machine = (& $Python -c "import platform; print(platform.machine())").Trim().ToUpperInvariant()
if ($Architecture -eq "ARM64" -and $machine -notin @("ARM64", "AARCH64")) {
    throw "A native ARM64 Python on Windows ARM64 is required for the ARM64 package. Detected: $machine"
}
if ($Architecture -eq "x64" -and $machine -notin @("AMD64", "X86_64")) {
    throw "A native x64 Python is required for the x64 package. Detected: $machine"
}

$version = (& $Python -c "from mora_cutter import __version__; print(__version__)").Trim()
$packageName = "MoraCutter-v$version-Windows-$Architecture"
$stageRoot = Join-Path $outputFull "stage-$Architecture"
$distRoot = Join-Path $stageRoot "dist"
$workRoot = Join-Path $stageRoot "build"
$portableRoot = Join-Path $distRoot "MoraCutter"
$finalFolder = Join-Path $outputFull $packageName
$zipPath = Join-Path $outputFull "$packageName.zip"
foreach ($target in @($stageRoot, $finalFolder, $zipPath)) {
    if (Test-Path -LiteralPath $target) { throw "Output already exists; move or delete it before rebuilding: $target" }
}

& $Python -m pip install --disable-pip-version-check -r (Join-Path $projectRoot "requirements-build.txt")
if ($LASTEXITCODE -ne 0) { throw "Python dependencies could not be installed." }
& $Python -m unittest discover -s (Join-Path $projectRoot "tests") -v
if ($LASTEXITCODE -ne 0) { throw "Tests failed." }
& $Python -m PyInstaller --noconfirm --clean --distpath $distRoot --workpath $workRoot (Join-Path $projectRoot "MoraCutter.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

Move-Item -LiteralPath $portableRoot -Destination $finalFolder
Copy-Item -LiteralPath (Join-Path $projectRoot "お読みください.txt") -Destination $finalFolder
Copy-Item -LiteralPath (Join-Path $projectRoot "LICENSE.txt") -Destination $finalFolder
Copy-Item -LiteralPath (Join-Path $projectRoot "THIRD_PARTY_NOTICES.md") -Destination $finalFolder
Copy-Item -LiteralPath (Join-Path $projectRoot "resources") -Destination $finalFolder -Recurse
$thirdParty = Join-Path $finalFolder "THIRD_PARTY_LICENSES"
Copy-Item -LiteralPath (Join-Path $projectRoot "THIRD_PARTY_LICENSES") -Destination $finalFolder -Recurse
& $Python (Join-Path $projectRoot "build_support\collect_licenses.py") $thirdParty
if ($LASTEXITCODE -ne 0) { throw "Third-party license collection failed." }
$readmePath = Join-Path $finalFolder "お読みください.txt"
$readmeText = Get-Content -LiteralPath $readmePath -Raw
[System.IO.File]::WriteAllText($readmePath, $readmeText, [System.Text.UTF8Encoding]::new($true))

$application = Join-Path $finalFolder "MoraCutter.exe"
if ($CertificateThumbprint) {
    & (Join-Path $projectRoot "sign_windows.ps1") -Executable $application -CertificateThumbprint $CertificateThumbprint -AllowSelfSigned
    if ($LASTEXITCODE -ne 0) { throw "Code signing failed." }
} else {
    Write-Warning "The EXE is unsigned. Use create_self_signed_certificate.ps1, then pass -CertificateThumbprint."
}

$hashLines = Get-ChildItem -LiteralPath $finalFolder -File -Recurse | Sort-Object FullName | ForEach-Object {
    $relative = $_.FullName.Substring($finalFolder.Length + 1).Replace('\', '/')
    "$((Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash)  $relative"
}
Set-Content -LiteralPath (Join-Path $finalFolder "SHA256SUMS.txt") -Value $hashLines -Encoding ascii
Compress-Archive -LiteralPath $finalFolder -DestinationPath $zipPath -CompressionLevel Optimal
$zipSize = (Get-Item -LiteralPath $zipPath).Length
if ($zipSize -gt 500MB) { throw "Package exceeds 500 MB: $([math]::Round($zipSize / 1MB, 1)) MB" }
$zipHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $zipPath).Hash
Set-Content -LiteralPath (Join-Path $outputFull "$packageName.sha256.txt") -Value "$zipHash  $packageName.zip" -Encoding ascii
Write-Output "Package: $zipPath"
Write-Output "SHA-256: $zipHash"
