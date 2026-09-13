[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Executable,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9A-Fa-f]{40}$')]
    [string]$CertificateThumbprint,
    [string]$TimestampUrl = "",
    [switch]$AllowSelfSigned
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
$usageOids = @($certificate.EnhancedKeyUsageList | ForEach-Object {
    if ($_.ObjectId -is [string]) { $_.ObjectId }
    elseif ($_.PSObject.Properties.Name -contains "ObjectId") { $_.ObjectId.Value }
    else { $_.Value }
})
if ($usageOids -notcontains $codeSigningOid) {
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

$arguments = @("sign", "/sha1", $CertificateThumbprint, "/s", "My", "/fd", "SHA256", "/d", "Mora Cutter", "/du", "https://sgnl88.com/")
if ($TimestampUrl) { $arguments += @("/tr", $TimestampUrl, "/td", "SHA256") }
$arguments += $resolvedExecutable
& $signTool.FullName @arguments
if ($LASTEXITCODE -ne 0) { throw "SignTool returned exit code $LASTEXITCODE." }

& $signTool.FullName verify /pa /all /v $resolvedExecutable
if ($LASTEXITCODE -ne 0 -and -not $AllowSelfSigned) { throw "Signature verification failed." }

$signature = Get-AuthenticodeSignature -LiteralPath $resolvedExecutable
if ($signature.Status -ne "Valid" -and -not $AllowSelfSigned) {
    throw "Authenticode status is $($signature.Status), not Valid."
}
if (-not $signature.SignerCertificate) { throw "No Authenticode signer certificate was written." }
Write-Output "Authenticode signer: $($signature.SignerCertificate.Subject); trust status: $($signature.Status)"
exit 0
