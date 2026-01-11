<#
.SYNOPSIS
    Install and configure Microsoft Graph PowerShell SDK with God Mode integration

.DESCRIPTION
    This script installs the Microsoft Graph PowerShell SDK and configures it
    for use with the God Mode provisioning system.

.EXAMPLE
    ./Install-GraphSDK.ps1
    
.EXAMPLE
    ./Install-GraphSDK.ps1 -Scope CurrentUser
#>

[CmdletBinding()]
param(
    [ValidateSet("CurrentUser", "AllUsers")]
    [string]$Scope = "CurrentUser",
    
    [switch]$Force
)

$ErrorActionPreference = "Stop"

Write-Host "`n╔══════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║  Microsoft Graph PowerShell SDK Installer                        ║" -ForegroundColor Cyan
Write-Host "║  God Mode Integration                                            ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan

# Check PowerShell version
$psVersion = $PSVersionTable.PSVersion
Write-Host "`nPowerShell Version: $($psVersion.Major).$($psVersion.Minor)" -ForegroundColor Gray

if ($psVersion.Major -lt 5 -or ($psVersion.Major -eq 5 -and $psVersion.Minor -lt 1)) {
    Write-Error "PowerShell 5.1 or higher is required. Please upgrade PowerShell."
    exit 1
}

# Install NuGet provider if needed
Write-Host "`nChecking NuGet provider..." -ForegroundColor Yellow
$nuget = Get-PackageProvider -Name NuGet -ErrorAction SilentlyContinue
if (-not $nuget -or $nuget.Version -lt [Version]"2.8.5.201") {
    Write-Host "Installing NuGet provider..." -ForegroundColor Yellow
    Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force -Scope $Scope | Out-Null
    Write-Host "  ✓ NuGet provider installed" -ForegroundColor Green
} else {
    Write-Host "  ✓ NuGet provider already installed" -ForegroundColor Green
}

# Set PSGallery as trusted
Write-Host "`nConfiguring PSGallery..." -ForegroundColor Yellow
$repo = Get-PSRepository -Name PSGallery -ErrorAction SilentlyContinue
if ($repo.InstallationPolicy -ne "Trusted") {
    Set-PSRepository -Name PSGallery -InstallationPolicy Trusted
    Write-Host "  ✓ PSGallery set as trusted" -ForegroundColor Green
} else {
    Write-Host "  ✓ PSGallery already trusted" -ForegroundColor Green
}

# Install Microsoft Graph modules
$modules = @(
    "Microsoft.Graph.Authentication",
    "Microsoft.Graph.Users",
    "Microsoft.Graph.Groups",
    "Microsoft.Graph.Applications",
    "Microsoft.Graph.Identity.DirectoryManagement",
    "Microsoft.Graph.Teams"
)

Write-Host "`nInstalling Microsoft Graph modules..." -ForegroundColor Yellow

foreach ($module in $modules) {
    $installed = Get-Module -Name $module -ListAvailable -ErrorAction SilentlyContinue
    
    if ($installed -and -not $Force) {
        Write-Host "  ✓ $module (v$($installed.Version)) already installed" -ForegroundColor Green
    } else {
        Write-Host "  Installing $module..." -ForegroundColor Gray
        try {
            Install-Module -Name $module -Scope $Scope -Force -AllowClobber -ErrorAction Stop
            $ver = (Get-Module -Name $module -ListAvailable | Select-Object -First 1).Version
            Write-Host "  ✓ $module (v$ver) installed" -ForegroundColor Green
        } catch {
            Write-Host "  ✗ Failed to install $module: $_" -ForegroundColor Red
        }
    }
}

# Install Az module for Azure management
Write-Host "`nInstalling Azure PowerShell module..." -ForegroundColor Yellow
$azModule = Get-Module -Name Az -ListAvailable -ErrorAction SilentlyContinue

if ($azModule -and -not $Force) {
    Write-Host "  ✓ Az module (v$($azModule.Version)) already installed" -ForegroundColor Green
} else {
    Write-Host "  Installing Az module (this may take a few minutes)..." -ForegroundColor Gray
    try {
        Install-Module -Name Az -Scope $Scope -Force -AllowClobber -ErrorAction Stop
        $ver = (Get-Module -Name Az -ListAvailable | Select-Object -First 1).Version
        Write-Host "  ✓ Az module (v$ver) installed" -ForegroundColor Green
    } catch {
        Write-Host "  ⚠ Az module installation failed (optional): $_" -ForegroundColor Yellow
    }
}

# Create profile additions
Write-Host "`nConfiguring PowerShell profile..." -ForegroundColor Yellow

$profileAdditions = @"

# ═══════════════════════════════════════════════════════════════════
# God Mode - Microsoft Graph PowerShell Integration
# ═══════════════════════════════════════════════════════════════════

# Import God Mode module
`$GodModePath = Join-Path `$PSScriptRoot "GodMode.psm1"
if (Test-Path `$GodModePath) {
    Import-Module `$GodModePath -Force
}

# Quick connect function
function Connect-GodMode {
    [CmdletBinding()]
    param(
        [switch]`$Interactive
    )
    
    if (`$Interactive) {
        Connect-MgGraph -Scopes "User.ReadWrite.All", "Group.ReadWrite.All", "Application.ReadWrite.All", "Directory.ReadWrite.All"
    } else {
        `$tenantId = `$env:AZURE_TENANT_ID
        `$clientId = `$env:AZURE_CLIENT_ID
        `$clientSecret = `$env:AZURE_CLIENT_SECRET
        
        if (`$tenantId -and `$clientId -and `$clientSecret) {
            `$secureSecret = ConvertTo-SecureString `$clientSecret -AsPlainText -Force
            `$credential = New-Object System.Management.Automation.PSCredential(`$clientId, `$secureSecret)
            Connect-MgGraph -TenantId `$tenantId -ClientSecretCredential `$credential
        } else {
            Write-Warning "Environment variables not set. Use -Interactive for browser login."
            Connect-MgGraph -Scopes "User.ReadWrite.All", "Group.ReadWrite.All"
        }
    }
    
    Get-MgContext
}

# Aliases
Set-Alias -Name gmconnect -Value Connect-GodMode
Set-Alias -Name gmprovision -Value New-GodModeInfrastructure
Set-Alias -Name gmstatus -Value Get-GodModeStatus

Write-Host "God Mode loaded. Type 'gmstatus' to check status." -ForegroundColor Cyan
"@

$profileDir = Split-Path $PROFILE -Parent
if (-not (Test-Path $profileDir)) {
    New-Item -Path $profileDir -ItemType Directory -Force | Out-Null
}

$godModeProfilePath = Join-Path $profileDir "GodMode_Profile.ps1"
$profileAdditions | Out-File -FilePath $godModeProfilePath -Encoding utf8 -Force

Write-Host "  ✓ Profile additions saved to: $godModeProfilePath" -ForegroundColor Green

# Summary
Write-Host "`n══════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "Installation Complete!" -ForegroundColor Green
Write-Host ""
Write-Host "To get started:" -ForegroundColor White
Write-Host "  1. Import the God Mode module:" -ForegroundColor Gray
Write-Host "     Import-Module ./GodMode.psm1" -ForegroundColor Yellow
Write-Host ""
Write-Host "  2. Or source the profile additions:" -ForegroundColor Gray
Write-Host "     . $godModeProfilePath" -ForegroundColor Yellow
Write-Host ""
Write-Host "  3. Connect to Microsoft Graph:" -ForegroundColor Gray
Write-Host "     Connect-GodMode" -ForegroundColor Yellow
Write-Host "     # or for interactive login:" -ForegroundColor Gray
Write-Host "     Connect-GodMode -Interactive" -ForegroundColor Yellow
Write-Host ""
Write-Host "  4. Provision infrastructure:" -ForegroundColor Gray
Write-Host "     New-GodModeInfrastructure -Organizations 3 -UsersPerOrg 50" -ForegroundColor Yellow
Write-Host ""
Write-Host "Environment variables needed:" -ForegroundColor White
Write-Host "  AZURE_TENANT_ID     - Your Azure AD tenant ID" -ForegroundColor Gray
Write-Host "  AZURE_CLIENT_ID     - Application (client) ID" -ForegroundColor Gray
Write-Host "  AZURE_CLIENT_SECRET - Client secret" -ForegroundColor Gray
Write-Host ""
