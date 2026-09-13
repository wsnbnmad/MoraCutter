[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PackageFolder,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9A-Fa-f]{40}$')][string]$CertificateThumbprint
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $MyInvocation.MyCommand.Path)).Path
$folder = (Resolve-Path -LiteralPath $PackageFolder).Path
$application = Join-Path $folder "MoraCutter.exe"
if (-not (Test-Path -LiteralPath $application)) { throw "MoraCutter.exe was not found in $folder" }
& (Join-Path $projectRoot "sign_windows.ps1") -Executable $application -CertificateThumbprint $CertificateThumbprint -AllowSelfSigned
$hashPath = Join-Path $folder "SHA256SUMS.txt"
if (Test-Path -LiteralPath $hashPath) { Remove-Item -LiteralPath $hashPath }
$hashLines = Get-ChildItem -LiteralPath $folder -File -Recurse | Sort-Object FullName | ForEach-Object {
    $relative = $_.FullName.Substring($folder.Length + 1).Replace('\', '/')
    "$((Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash)  $relative"
}
Set-Content -LiteralPath $hashPath -Value $hashLines -Encoding ascii
$zip = "$folder.zip"
if (Test-Path -LiteralPath $zip) { throw "ZIP output already exists: $zip" }
Compress-Archive -LiteralPath $folder -DestinationPath $zip -CompressionLevel Optimal
if ((Get-Item -LiteralPath $zip).Length -gt 500MB) { throw "Package exceeds 500 MB." }
$zipHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $zip).Hash
Set-Content -LiteralPath "$folder.sha256.txt" -Value "$zipHash  $([IO.Path]::GetFileName($zip))" -Encoding ascii
Write-Output "Signed package: $zip"
Write-Output "SHA-256: $zipHash"
