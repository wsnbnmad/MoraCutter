[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Executable,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9A-Fa-f]{40}$')]
    [string]$CertificateThumbprint,
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"
$resolvedExecutable = (Resolve-Path -LiteralPath $Executable).Path
if ([System.IO.Path]::GetExtension($resolvedExecutable) -ne ".exe") {
    throw "Only the application EXE may be signed by this script."
}

$certificate = Get-ChildItem "Cert:\CurrentUser\My\$CertificateThumbprint" -ErrorAction Stop
if (-not $certificate.HasPrivateKey) {
    throw "The selected certificate has no private key."
}
$codeSigningOid = "1.3.6.1.5.5.7.3.3"
if (-not ($certificate.EnhancedKeyUsageList.ObjectId.Value -contains $codeSigningOid)) {
    throw "The selected certificate is not valid for code signing."
}
if ($certificate.NotAfter -le (Get-Date)) {
    throw "The selected certificate has expired."
}

$signTool = Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin" `
    -Filter "signtool.exe" -Recurse -ErrorAction Stop |
    Where-Object { $_.FullName -match '\\x64\\signtool\.exe$' } |
    Sort-Object FullName -Descending |
    Select-Object -First 1
if (-not $signTool) {
    throw "64-bit SignTool was not found. Install the Windows SDK signing tools."
}

& $signTool.FullName sign `
    /sha1 $CertificateThumbprint `
    /s My `
    /fd SHA256 `
    /tr $TimestampUrl `
    /td SHA256 `
    /d "Mora Cutter" `
    /du "https://signal88.com/" `
    $resolvedExecutable
if ($LASTEXITCODE -ne 0) { throw "SignTool returned exit code $LASTEXITCODE." }

& $signTool.FullName verify /pa /all /v $resolvedExecutable
if ($LASTEXITCODE -ne 0) { throw "Signature verification failed." }

$signature = Get-AuthenticodeSignature -LiteralPath $resolvedExecutable
if ($signature.Status -ne "Valid") {
    throw "Authenticode status is $($signature.Status), not Valid."
}
Write-Output "Valid Authenticode signature: $($signature.SignerCertificate.Subject)"

