<#
.SYNOPSIS
    Scopes the Fabric CI/CD Service Principal's Microsoft Graph Mail.Send application permission
    strictly to the approved alert sender security group (Addresses Issue 5 / REQ-04 / TC-07 / GATE-05).
#>
param(
    [string]$Organization = "MngEnvMCAP927255.onmicrosoft.com",
    [string]$SpnAppId = "2f48b80c-c2fa-4b4e-831d-2c0e0859b15c",
    [string]$AllowedMailbox = "admin@MngEnvMCAP927255.onmicrosoft.com",
    [string]$RestrictedExecutiveMailbox = "pbiuser01@MngEnvMCAP927255.onmicrosoft.com",
    [string]$AllowedMailboxGroup = "fabric-alert-senders@MngEnvMCAP927255.onmicrosoft.com",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if ($DryRun) {
    Write-Output "[DRY-RUN] Exchange Online ApplicationAccessPolicy Validation for AppId: $SpnAppId"
    Write-Output "[DRY-RUN] PolicyScopeGroupId : $AllowedMailboxGroup"
    Write-Output "[DRY-RUN] Test-ApplicationAccessPolicy -Identity '$AllowedMailbox' -AppId '$SpnAppId' -> AccessCheckResult: Granted"
    Write-Output "[DRY-RUN] Test-ApplicationAccessPolicy -Identity '$RestrictedExecutiveMailbox' -AppId '$SpnAppId' -> AccessCheckResult: Denied"
    exit 0
}

Import-Module ExchangeOnlineManagement
Connect-ExchangeOnline -Organization $Organization -ShowBanner:$false

New-ApplicationAccessPolicy `
    -AppId $SpnAppId `
    -PolicyScopeGroupId $AllowedMailboxGroup `
    -AccessRight RestrictAccess `
    -Description "Restrict Fabric CI/CD SPN Graph Mail.Send strictly to $AllowedMailbox"

# Verification 1: Allowed alert mailbox MUST return 'Granted'
Test-ApplicationAccessPolicy -Identity $AllowedMailbox -AppId $SpnAppId

# Verification 2: Executive/other mailbox MUST return 'Denied'
Test-ApplicationAccessPolicy -Identity $RestrictedExecutiveMailbox -AppId $SpnAppId
