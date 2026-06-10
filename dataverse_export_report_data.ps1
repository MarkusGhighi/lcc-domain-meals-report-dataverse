$ErrorActionPreference = 'Stop'

$systemFiles = Resolve-Path (Join-Path $PSScriptRoot '..\Systemfiles')
$tools = Join-Path $systemFiles 'pac_nupkg_2.7.4\tools'
$envPath = Join-Path $PSScriptRoot '.env'

if (Test-Path -LiteralPath $envPath) {
    Get-Content -LiteralPath $envPath | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith('#') -or -not $line.Contains('=')) {
            return
        }
        $parts = $line.Split('=', 2)
        [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), 'Process')
    }
}

Add-Type -Path (Join-Path $tools 'Microsoft.Identity.Client.dll')

$interactiveClientId = '51f81489-12ee-4a9e-aaae-a2591f45987d'
$tenantId = $env:DATAVERSE_TENANT_ID
$serviceClientId = $env:DATAVERSE_CLIENT_ID
$clientSecret = $env:DATAVERSE_CLIENT_SECRET
$orgUrl = if ($env:DATAVERSE_ORG_URL) { $env:DATAVERSE_ORG_URL.TrimEnd('/') } else { 'https://org1afb89f7.crm4.dynamics.com' }
$authority = if ($tenantId) { "https://login.microsoftonline.com/$tenantId" } else { 'https://login.microsoftonline.com/organizations' }
$redirect = 'http://localhost'
$api = "$orgUrl/api/data/v9.2"
$authMode = if ($tenantId -and $serviceClientId -and $clientSecret) { 'service_principal' } else { 'interactive_user' }

function Get-DataverseHeaders {
    $scopes = [string[]]@("$orgUrl/.default")

    if ($script:authMode -eq 'service_principal') {
        $app = [Microsoft.Identity.Client.ConfidentialClientApplicationBuilder]::Create($script:serviceClientId).
            WithClientSecret($script:clientSecret).
            WithAuthority($script:authority).
            Build()
        $result = $app.AcquireTokenForClient($scopes).ExecuteAsync().GetAwaiter().GetResult()
    }
    else {
        $az = Get-Command az -ErrorAction SilentlyContinue
        if (-not $az) {
            $az = Get-Command 'C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd' -ErrorAction SilentlyContinue
        }
        if ($az) {
            try {
                $token = (& $az.Source account get-access-token --resource $script:orgUrl --query accessToken -o tsv 2>$null)
                if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($token)) {
                    $script:authMode = 'azure_cli'
                    return @{
                        Authorization = "Bearer $token"
                        Accept = 'application/json'
                        'OData-MaxVersion' = '4.0'
                        'OData-Version' = '4.0'
                        Prefer = 'odata.maxpagesize=5000'
                    }
                }
            }
            catch {
                # Fall through to MSAL interactive auth.
            }
        }

        $app = [Microsoft.Identity.Client.PublicClientApplicationBuilder]::Create($script:interactiveClientId).
            WithAuthority($script:authority).
            WithRedirectUri($script:redirect).
            Build()

        $accounts = $app.GetAccountsAsync().GetAwaiter().GetResult()
        $account = $accounts | Select-Object -First 1

        try {
            if ($null -eq $account) {
                throw 'No cached account'
            }
            $result = $app.AcquireTokenSilent($scopes, $account).ExecuteAsync().GetAwaiter().GetResult()
        }
        catch {
            $result = $app.AcquireTokenInteractive($scopes).ExecuteAsync().GetAwaiter().GetResult()
        }
    }

    return @{
        Authorization = "Bearer $($result.AccessToken)"
        Accept = 'application/json'
        'OData-MaxVersion' = '4.0'
        'OData-Version' = '4.0'
        Prefer = 'odata.maxpagesize=5000'
    }
}

function Get-DataverseRows {
    param(
        [hashtable]$Headers,
        [string]$EntitySetName,
        [string[]]$SelectColumns,
        [string]$OrderBy
    )

    $select = $selectColumns -join ','
    $uri = "${api}/${EntitySetName}?`$select=$select"
    if ($orderBy) {
        $uri = "$uri&`$orderby=$([System.Uri]::EscapeDataString($orderBy))"
    }

    $rows = New-Object System.Collections.Generic.List[object]
    while ($uri) {
        $response = Invoke-RestMethod -Uri $uri -Headers $headers -Method Get
        foreach ($row in $response.value) {
            $rows.Add($row)
        }
        $uri = $response.'@odata.nextLink'
    }

    return $rows
}

function Test-DataverseColumn {
    param(
        [hashtable]$Headers,
        [string]$EntitySetName,
        [string]$ColumnName
    )

    $uri = "${api}/${EntitySetName}?`$top=1&`$select=$ColumnName"
    try {
        Invoke-RestMethod -Uri $uri -Headers $headers -Method Get | Out-Null
        return $true
    }
    catch {
        return $false
    }
}

function Resolve-DataverseColumns {
    param(
        [hashtable]$Headers,
        [string]$EntitySetName,
        [string[]]$PreferredColumns
    )

    $validColumns = New-Object System.Collections.Generic.List[string]
    $skippedColumns = New-Object System.Collections.Generic.List[string]

    foreach ($columnName in $preferredColumns) {
        if (Test-DataverseColumn -Headers $Headers -EntitySetName $EntitySetName -ColumnName $columnName) {
            $validColumns.Add($columnName)
        }
        else {
            $skippedColumns.Add($columnName)
        }
    }

    if ($validColumns.Count -eq 0) {
        throw "No readable Dataverse columns found for $entitySetName"
    }

    return [ordered]@{
        selected = $validColumns.ToArray()
        skipped = $skippedColumns.ToArray()
    }
}

$headers = Get-DataverseHeaders

$participantColumns = @(
    'new_no',
    'new_firstnameandsurname',
    'new_idnumber',
    'new_dateofbirth',
    'new_ageformula',
    'new_agegroupformula',
    'new_gender',
    'new_race',
    'new_disabled',
    'new_specifydisability',
    'new_dateofadmission',
    'new_powerappsid',
    'new_legacypowerappsid'
)

$scanLogColumns = @(
    'new_firstnameandsurname',
    'new_idnumber',
    'new_scantimestamp',
    'new_ageformula',
    'new_gender',
    'new_race',
    'new_disabled',
    'new_newqrcode',
    'new_powerappsid',
    'new_legacypowerappsid'
)

$participantColumnsResolved = Resolve-DataverseColumns -Headers $headers -EntitySetName 'new_mealparticipants' -PreferredColumns $participantColumns
$scanLogColumnsResolved = Resolve-DataverseColumns -Headers $headers -EntitySetName 'new_mealscanlogs' -PreferredColumns $scanLogColumns

[ordered]@{
    source = 'Dataverse'
    org_url = $orgUrl
    auth_mode = $authMode
    generated_at = (Get-Date).ToString('s')
    tables = [ordered]@{
        meal_participants = 'new_mealparticipants'
        meal_scan_logs = 'new_mealscanlogs'
    }
    selected_columns = [ordered]@{
        meal_participants = $participantColumnsResolved.selected
        meal_scan_logs = $scanLogColumnsResolved.selected
    }
    skipped_columns = [ordered]@{
        meal_participants = $participantColumnsResolved.skipped
        meal_scan_logs = $scanLogColumnsResolved.skipped
    }
    meal_participants = Get-DataverseRows -Headers $headers -EntitySetName 'new_mealparticipants' -SelectColumns $participantColumnsResolved.selected -OrderBy $null
    meal_scan_logs = Get-DataverseRows -Headers $headers -EntitySetName 'new_mealscanlogs' -SelectColumns $scanLogColumnsResolved.selected -OrderBy $null
} | ConvertTo-Json -Depth 20
