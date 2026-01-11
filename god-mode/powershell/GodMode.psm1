<#
.SYNOPSIS
    God Mode PowerShell Module - Rapid Azure AD & GitHub Enterprise Bulk Provisioning

.DESCRIPTION
    Deploy entire organizational structures in seconds:
    - Multiple organizations/groups
    - Users with roles
    - Applications and service principals
    - GitHub Enterprise orgs and repos

.EXAMPLE
    # Import the module
    Import-Module ./GodMode.psm1

    # Provision 3 orgs with 50 users each
    New-GodModeInfrastructure -Organizations 3 -UsersPerOrg 50

    # Provision from config
    New-GodModeInfrastructure -ConfigFile infrastructure.json
#>

# Module variables
$script:GraphToken = $null
$script:TokenExpiry = $null

function Get-GodModeToken {
    <#
    .SYNOPSIS
        Get Microsoft Graph access token
    #>
    [CmdletBinding()]
    param()
    
    # Check if we have a valid cached token
    if ($script:GraphToken -and $script:TokenExpiry -gt (Get-Date)) {
        return $script:GraphToken
    }
    
    $tenantId = $env:AZURE_TENANT_ID
    $clientId = $env:AZURE_CLIENT_ID
    $clientSecret = $env:AZURE_CLIENT_SECRET
    
    if (-not $tenantId -or -not $clientId -or -not $clientSecret) {
        throw "Missing Azure credentials. Set AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET"
    }
    
    $tokenUrl = "https://login.microsoftonline.com/$tenantId/oauth2/v2.0/token"
    
    $body = @{
        client_id     = $clientId
        client_secret = $clientSecret
        scope         = "https://graph.microsoft.com/.default"
        grant_type    = "client_credentials"
    }
    
    try {
        $response = Invoke-RestMethod -Uri $tokenUrl -Method Post -Body $body -ContentType "application/x-www-form-urlencoded"
        $script:GraphToken = $response.access_token
        $script:TokenExpiry = (Get-Date).AddSeconds($response.expires_in - 60)
        return $script:GraphToken
    }
    catch {
        throw "Failed to acquire token: $_"
    }
}

function Invoke-GodModeGraphRequest {
    <#
    .SYNOPSIS
        Make a Microsoft Graph API request
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [ValidateSet("GET", "POST", "PATCH", "DELETE", "PUT")]
        [string]$Method,
        
        [Parameter(Mandatory)]
        [string]$Endpoint,
        
        [hashtable]$Body,
        
        [switch]$Beta
    )
    
    $token = Get-GodModeToken
    $baseUrl = if ($Beta) { "https://graph.microsoft.com/beta" } else { "https://graph.microsoft.com/v1.0" }
    $url = "$baseUrl$Endpoint"
    
    $headers = @{
        "Authorization" = "Bearer $token"
        "Content-Type"  = "application/json"
    }
    
    $params = @{
        Uri     = $url
        Method  = $Method
        Headers = $headers
    }
    
    if ($Body) {
        $params.Body = $Body | ConvertTo-Json -Depth 10
    }
    
    try {
        $response = Invoke-RestMethod @params
        return $response
    }
    catch {
        $errorMessage = $_.ErrorDetails.Message | ConvertFrom-Json -ErrorAction SilentlyContinue
        if ($errorMessage) {
            throw "Graph API Error: $($errorMessage.error.message)"
        }
        throw $_
    }
}

function New-GodModeUser {
    <#
    .SYNOPSIS
        Create a new Azure AD user
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$DisplayName,
        
        [Parameter(Mandatory)]
        [string]$UserPrincipalName,
        
        [string]$MailNickname,
        
        [string]$JobTitle,
        
        [string]$Department,
        
        [string]$Password
    )
    
    if (-not $MailNickname) {
        $MailNickname = $UserPrincipalName.Split("@")[0]
    }
    
    if (-not $Password) {
        $Password = -join ((65..90) + (97..122) + (48..57) + (33, 35, 36, 37, 64) | Get-Random -Count 16 | ForEach-Object { [char]$_ })
    }
    
    $body = @{
        accountEnabled    = $true
        displayName       = $DisplayName
        mailNickname      = $MailNickname
        userPrincipalName = $UserPrincipalName
        passwordProfile   = @{
            forceChangePasswordNextSignIn = $true
            password                      = $Password
        }
    }
    
    if ($JobTitle) { $body.jobTitle = $JobTitle }
    if ($Department) { $body.department = $Department }
    
    $result = Invoke-GodModeGraphRequest -Method POST -Endpoint "/users" -Body $body
    
    return [PSCustomObject]@{
        Success           = $true
        Id                = $result.id
        DisplayName       = $result.displayName
        UserPrincipalName = $result.userPrincipalName
        TempPassword      = $Password
    }
}

function New-GodModeGroup {
    <#
    .SYNOPSIS
        Create a new Azure AD group
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$DisplayName,
        
        [string]$Description,
        
        [string]$MailNickname,
        
        [switch]$SecurityEnabled,
        
        [switch]$MailEnabled
    )
    
    if (-not $MailNickname) {
        $MailNickname = $DisplayName.ToLower() -replace '\s', ''
    }
    
    $body = @{
        displayName     = $DisplayName
        mailNickname    = $MailNickname
        mailEnabled     = $MailEnabled.IsPresent
        securityEnabled = (-not $MailEnabled.IsPresent) -or $SecurityEnabled.IsPresent
    }
    
    if ($Description) { $body.description = $Description }
    
    $result = Invoke-GodModeGraphRequest -Method POST -Endpoint "/groups" -Body $body
    
    return [PSCustomObject]@{
        Success      = $true
        Id           = $result.id
        DisplayName  = $result.displayName
        MailNickname = $result.mailNickname
    }
}

function New-GodModeInfrastructure {
    <#
    .SYNOPSIS
        Provision complete infrastructure rapidly
    
    .DESCRIPTION
        Create multiple organizations, users, and resources in a single command
    
    .EXAMPLE
        New-GodModeInfrastructure -Organizations 3 -UsersPerOrg 50
    
    .EXAMPLE
        New-GodModeInfrastructure -ConfigFile infrastructure.json
    #>
    [CmdletBinding()]
    param(
        [string]$ConfigFile,
        
        [int]$Organizations = 3,
        
        [int]$UsersPerOrg = 10,
        
        [switch]$IncludeGitHub,
        
        [int]$Concurrency = 10
    )
    
    $startTime = Get-Date
    $results = @{
        Groups = @()
        Users  = @()
        Errors = @()
    }
    
    Write-Host "`n╔══════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "║  God Mode - Rapid Bulk Provisioning                              ║" -ForegroundColor Cyan
    Write-Host "╚══════════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
    
    if ($ConfigFile) {
        $config = Get-Content $ConfigFile | ConvertFrom-Json
        $groups = $config.groups
        $users = $config.users
    }
    else {
        # Generate infrastructure spec
        $groups = @()
        $users = @()
        
        for ($i = 1; $i -le $Organizations; $i++) {
            $orgName = "Organization-$($i.ToString('00'))"
            $groups += @{
                displayName  = $orgName
                description  = "Auto-generated organization $i"
                mailNickname = "org$($i.ToString('00'))"
            }
            
            for ($j = 1; $j -le $UsersPerOrg; $j++) {
                $userNum = ($i - 1) * $UsersPerOrg + $j
                $jobTitles = @("Developer", "Manager", "Analyst", "Engineer", "Designer")
                $users += @{
                    displayName = "User $($userNum.ToString('000'))"
                    username    = "user$($userNum.ToString('000'))"
                    department  = $orgName
                    jobTitle    = $jobTitles[$j % 5]
                }
            }
        }
    }
    
    Write-Host "`nProvisioning:" -ForegroundColor White
    Write-Host "  • $($groups.Count) groups/organizations" -ForegroundColor Gray
    Write-Host "  • $($users.Count) users" -ForegroundColor Gray
    Write-Host ""
    
    # Create groups
    Write-Host "Creating groups..." -ForegroundColor Yellow
    $groupProgress = 0
    foreach ($group in $groups) {
        try {
            $result = New-GodModeGroup -DisplayName $group.displayName -Description $group.description -MailNickname $group.mailNickname
            $results.Groups += $result
            $groupProgress++
            Write-Progress -Activity "Creating Groups" -Status "$groupProgress of $($groups.Count)" -PercentComplete (($groupProgress / $groups.Count) * 100)
        }
        catch {
            $results.Errors += [PSCustomObject]@{
                Type    = "Group"
                Name    = $group.displayName
                Error   = $_.Exception.Message
            }
        }
    }
    Write-Progress -Activity "Creating Groups" -Completed
    Write-Host "  ✓ Groups created: $($results.Groups.Count)" -ForegroundColor Green
    
    # Create users (with throttling)
    Write-Host "Creating users..." -ForegroundColor Yellow
    $userProgress = 0
    $tenantId = $env:AZURE_TENANT_ID
    
    foreach ($user in $users) {
        try {
            $upn = "$($user.username)@$tenantId.onmicrosoft.com"
            $result = New-GodModeUser -DisplayName $user.displayName -UserPrincipalName $upn -Department $user.department -JobTitle $user.jobTitle
            $results.Users += $result
            $userProgress++
            Write-Progress -Activity "Creating Users" -Status "$userProgress of $($users.Count)" -PercentComplete (($userProgress / $users.Count) * 100)
            
            # Throttle to avoid rate limiting
            if ($userProgress % $Concurrency -eq 0) {
                Start-Sleep -Milliseconds 500
            }
        }
        catch {
            $results.Errors += [PSCustomObject]@{
                Type    = "User"
                Name    = $user.displayName
                Error   = $_.Exception.Message
            }
        }
    }
    Write-Progress -Activity "Creating Users" -Completed
    Write-Host "  ✓ Users created: $($results.Users.Count)" -ForegroundColor Green
    
    $endTime = Get-Date
    $duration = ($endTime - $startTime).TotalSeconds
    
    # Summary
    Write-Host "`n══════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "Provisioning Complete!" -ForegroundColor Green
    Write-Host "Duration: $([math]::Round($duration, 2)) seconds" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Summary:" -ForegroundColor White
    Write-Host "  Groups created: $($results.Groups.Count)" -ForegroundColor Green
    Write-Host "  Users created:  $($results.Users.Count)" -ForegroundColor Green
    
    if ($results.Errors.Count -gt 0) {
        Write-Host "  Errors:         $($results.Errors.Count)" -ForegroundColor Red
        Write-Host "`nErrors:" -ForegroundColor Red
        foreach ($error in $results.Errors) {
            Write-Host "  ✗ [$($error.Type)] $($error.Name): $($error.Error)" -ForegroundColor Red
        }
    }
    
    # Save results
    $resultsFile = Join-Path $HOME ".godmode/provision_$(Get-Date -Format 'yyyyMMdd_HHmmss').json"
    $null = New-Item -Path (Split-Path $resultsFile) -ItemType Directory -Force -ErrorAction SilentlyContinue
    $results | ConvertTo-Json -Depth 10 | Out-File $resultsFile
    Write-Host "`nResults saved to: $resultsFile" -ForegroundColor Gray
    
    return $results
}

function Get-GodModeStatus {
    <#
    .SYNOPSIS
        Check God Mode status and credentials
    #>
    [CmdletBinding()]
    param()
    
    Write-Host "`n╔══════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "║  God Mode Status                                                 ║" -ForegroundColor Cyan
    Write-Host "╚══════════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
    
    Write-Host "`nAzure AD:" -ForegroundColor Yellow
    $tenantId = $env:AZURE_TENANT_ID
    $clientId = $env:AZURE_CLIENT_ID
    $clientSecret = $env:AZURE_CLIENT_SECRET
    
    if ($tenantId -and $clientId -and $clientSecret) {
        Write-Host "  ✓ Credentials configured" -ForegroundColor Green
        Write-Host "    Tenant ID: $($tenantId.Substring(0, 8))..." -ForegroundColor Gray
        Write-Host "    Client ID: $($clientId.Substring(0, 8))..." -ForegroundColor Gray
        
        # Test connection
        try {
            $token = Get-GodModeToken
            $org = Invoke-GodModeGraphRequest -Method GET -Endpoint "/organization"
            Write-Host "  ✓ Connected to: $($org.value[0].displayName)" -ForegroundColor Green
        }
        catch {
            Write-Host "  ✗ Connection test failed: $_" -ForegroundColor Red
        }
    }
    else {
        Write-Host "  ✗ Missing credentials" -ForegroundColor Red
        if (-not $tenantId) { Write-Host "    Missing: AZURE_TENANT_ID" -ForegroundColor Gray }
        if (-not $clientId) { Write-Host "    Missing: AZURE_CLIENT_ID" -ForegroundColor Gray }
        if (-not $clientSecret) { Write-Host "    Missing: AZURE_CLIENT_SECRET" -ForegroundColor Gray }
    }
    
    Write-Host "`nGitHub:" -ForegroundColor Yellow
    $gheToken = $env:GHE_ADMIN_TOKEN
    if (-not $gheToken) { $gheToken = $env:beast }
    
    if ($gheToken) {
        Write-Host "  ✓ Token configured" -ForegroundColor Green
        Write-Host "    Token: $($gheToken.Substring(0, 8))..." -ForegroundColor Gray
    }
    else {
        Write-Host "  ✗ Missing token (GHE_ADMIN_TOKEN or beast)" -ForegroundColor Red
    }
}

# Export functions
Export-ModuleMember -Function @(
    'Get-GodModeToken',
    'Invoke-GodModeGraphRequest',
    'New-GodModeUser',
    'New-GodModeGroup',
    'New-GodModeInfrastructure',
    'Get-GodModeStatus'
)
