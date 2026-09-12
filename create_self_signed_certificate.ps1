[CmdletBinding()]
param([string]$Subject = "CN=signal88.com", [int]$ValidYears = 10)

$ErrorActionPreference = "Stop"
$certificate = New-SelfSignedCertificate `
    -Type CodeSigningCert `
    -Subject $Subject `
    -CertStoreLocation "Cert:\CurrentUser\My" `
    -HashAlgorithm SHA256 `
    -KeyAlgorithm RSA `
    -KeyLength 3072 `
    -KeyExportPolicy NonExportable `
    -NotAfter (Get-Date).AddYears($ValidYears)
Write-Output "Thumbprint: $($certificate.Thumbprint)"
Write-Output "Expires: $($certificate.NotAfter.ToString('yyyy-MM-dd'))"
Write-Output "The private key is non-exportable and remains in the current user's certificate store."
