param(
    [switch]$OfflineFallback,
    [switch]$NoPublish
)

$ErrorActionPreference = 'Stop'

Set-Location -LiteralPath $PSScriptRoot

$pythonExe = "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe"
$statusDir = Join-Path $PSScriptRoot 'status'
$logsDir = Join-Path $PSScriptRoot 'logs'
$currentPath = Join-Path $statusDir 'current-run.json'
$lastPath = Join-Path $statusDir 'last-run.json'
$historyPath = Join-Path $statusDir 'history.jsonl'
$logPath = Join-Path $logsDir 'report-automation.log'
$publishDir = $PSScriptRoot
$pagesUrl = 'https://markusghighi.github.io/lcc-domain-meals-report-dataverse/'

New-Item -ItemType Directory -Force -Path $statusDir, $logsDir | Out-Null

function ConvertTo-IsoUtc($date) {
    return $date.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
}

function Write-Log($level, $message) {
    $line = '{0} [{1}] {2}' -f (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'), $level, $message
    for ($attempt = 1; $attempt -le 8; $attempt++) {
        try {
            Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
            return
        }
        catch {
            Start-Sleep -Milliseconds (150 * $attempt)
            if ($attempt -eq 8) {
                throw
            }
        }
    }
}

function Save-Json($path, $object) {
    $json = $object | ConvertTo-Json -Depth 20
    $tempPath = "$path.tmp"
    for ($attempt = 1; $attempt -le 8; $attempt++) {
        try {
            Set-Content -LiteralPath $tempPath -Value $json -Encoding UTF8
            Move-Item -LiteralPath $tempPath -Destination $path -Force
            return
        }
        catch {
            Start-Sleep -Milliseconds (150 * $attempt)
            if ($attempt -eq 8) {
                throw
            }
        }
    }
}

function New-Step($name) {
    return [ordered]@{
        name = $name
        status = 'pending'
        started_at = $null
        finished_at = $null
        duration_seconds = $null
        exit_code = $null
        message = $null
        details = $null
    }
}

function Update-RunStatus($run) {
    Save-Json $currentPath $run
}

function Invoke-NativeCapture($command, $arguments) {
    $oldPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $command @arguments 2>&1
        $exitCode = $LASTEXITCODE
        return [ordered]@{
            exit_code = $exitCode
            output = ($output | Out-String).Trim()
        }
    }
    finally {
        $ErrorActionPreference = $oldPreference
    }
}

function Start-Step($run, $name) {
    foreach ($step in $run.steps) {
        if ($step.name -eq $name) {
            $step.status = 'running'
            $step.started_at = ConvertTo-IsoUtc (Get-Date)
            $step.message = 'Running'
            break
        }
    }
    $run.current_step = $name
    Update-RunStatus $run
}

function Finish-Step($run, $name, $status, $message, $details, $exitCode) {
    foreach ($step in $run.steps) {
        if ($step.name -eq $name) {
            $step.status = $status
            $step.finished_at = ConvertTo-IsoUtc (Get-Date)
            $step.exit_code = $exitCode
            $step.message = $message
            $step.details = $details
            if ($step.started_at) {
                $started = [datetime]::Parse($step.started_at)
                $step.duration_seconds = [math]::Round(((Get-Date).ToUniversalTime() - $started.ToUniversalTime()).TotalSeconds, 2)
            }
            break
        }
    }
    Update-RunStatus $run
}

function Invoke-StepCommand($run, $name, $command, $arguments) {
    Start-Step $run $name
    Write-Log 'INFO' "Start: $name"

    $result = Invoke-NativeCapture $command $arguments
    $exitCode = $result.exit_code
    $details = $result.output

    if ($exitCode -ne 0) {
        Finish-Step $run $name 'error' "Failed with exit code $exitCode" $details $exitCode
        Write-Log 'ERROR' "$name failed: $details"
        throw "$name failed with exit code $exitCode"
    }

    Finish-Step $run $name 'success' 'Completed' $details 0
    Write-Log 'INFO' "Done: $name"
    return $details
}

$started = Get-Date
$runId = $started.ToString('yyyyMMdd-HHmmss')
$run = [ordered]@{
    run_id = $runId
    status = 'running'
    current_step = $null
    started_at = ConvertTo-IsoUtc $started
    finished_at = $null
    duration_seconds = $null
    participants = $null
    scan_logs = $null
    changed = $false
    committed = $false
    pushed = $false
    publish_skipped = $false
    commit = $null
    pages_url = $pagesUrl
    pages_status_code = $null
    error = $null
    steps = @(
        (New-Step 'Dataverse report generation'),
        (New-Step 'Update GitHub Pages index'),
        (New-Step 'Read generated counts'),
        (New-Step 'Git change detection'),
        (New-Step 'Git commit'),
        (New-Step 'Git push'),
        (New-Step 'GitHub Pages check')
    )
}

Update-RunStatus $run
Write-Log 'INFO' "Automation run started: $runId"

try {
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        $pythonExe = 'python'
    }

    $reportArgs = @('gen_meals_report.py', '--no-serve')
    if ($OfflineFallback) {
        $reportArgs += '--offline-fallback'
    }
    Invoke-StepCommand $run 'Dataverse report generation' $pythonExe $reportArgs | Out-Null

    Start-Step $run 'Update GitHub Pages index'
    if (-not (Test-Path -LiteralPath $publishDir)) {
        throw "Publish repository not found: $publishDir"
    }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Meals_Report_py.html') -Destination (Join-Path $PSScriptRoot 'index.html') -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'index.html') -Destination (Join-Path $publishDir 'index.html') -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Meals_Report_py.html') -Destination (Join-Path $publishDir 'Meals_Report_py.html') -Force
    Finish-Step $run 'Update GitHub Pages index' 'success' 'Report files copied to publish repository' $publishDir 0

    Start-Step $run 'Read generated counts'
    $reportText = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Meals_Report_py.html') -Raw
    $masterMatch = [regex]::Match($reportText, 'let MASTER = (\[.*?\]);\s*let SCANS', [System.Text.RegularExpressions.RegexOptions]::Singleline)
    $scanMatch = [regex]::Match($reportText, 'let SCANS\s+= (\[.*?\]);\s*const COLORS', [System.Text.RegularExpressions.RegexOptions]::Singleline)
    if ($masterMatch.Success) {
        $run.participants = (($masterMatch.Groups[1].Value | ConvertFrom-Json) | Measure-Object).Count
    }
    if ($scanMatch.Success) {
        $run.scan_logs = (($scanMatch.Groups[1].Value | ConvertFrom-Json) | Measure-Object).Count
    }
    Finish-Step $run 'Read generated counts' 'success' "Participants: $($run.participants), scan logs: $($run.scan_logs)" $null 0

    Start-Step $run 'Git change detection'
    $status = (& git -C $publishDir status --porcelain index.html Meals_Report_py.html 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Git status failed: $status"
    }
    if ([string]::IsNullOrWhiteSpace($status)) {
        $run.changed = $false
        Finish-Step $run 'Git change detection' 'success' 'No report changes detected' $null 0
        foreach ($stepName in @('Git commit', 'Git push')) {
            Finish-Step $run $stepName 'skipped' 'No changes to publish' $null 0
        }
    }
    else {
        $run.changed = $true
        Finish-Step $run 'Git change detection' 'success' 'Report changes detected' $status 0

        if ($NoPublish) {
            $run.publish_skipped = $true
            foreach ($stepName in @('Git commit', 'Git push')) {
                Finish-Step $run $stepName 'skipped' 'NoPublish test mode' $null 0
            }
        }
        else {
            Start-Step $run 'Git commit'
            $addResult = Invoke-NativeCapture git @('-C', $publishDir, 'add', 'index.html', 'Meals_Report_py.html')
            if ($addResult.exit_code -ne 0) {
                Finish-Step $run 'Git commit' 'error' 'Git add failed' $addResult.output $addResult.exit_code
                throw 'Git add failed'
            }
            $commitMessage = "Update report $((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))"
            $commitResult = Invoke-NativeCapture git @('-C', $publishDir, 'commit', '-m', $commitMessage)
            if ($commitResult.exit_code -ne 0) {
                Finish-Step $run 'Git commit' 'error' 'Commit failed' $commitResult.output $commitResult.exit_code
                throw 'Git commit failed'
            }
            $run.committed = $true
            $revResult = Invoke-NativeCapture git @('-C', $publishDir, 'rev-parse', '--short', 'HEAD')
            $run.commit = $revResult.output
            Finish-Step $run 'Git commit' 'success' "Committed $($run.commit)" $commitResult.output 0

            Invoke-StepCommand $run 'Git push' git @('-C', $publishDir, 'push', 'origin', 'main') | Out-Null
            $run.pushed = $true
        }
    }

    Start-Step $run 'GitHub Pages check'
    try {
        $response = Invoke-WebRequest -Uri $pagesUrl -UseBasicParsing -TimeoutSec 30
        $run.pages_status_code = [int]$response.StatusCode
        Finish-Step $run 'GitHub Pages check' 'success' "HTTP $($response.StatusCode)" $null 0
    }
    catch {
        $run.pages_status_code = $null
        Finish-Step $run 'GitHub Pages check' 'warning' 'GitHub Pages check failed' $_.Exception.Message 1
    }

    $run.status = 'success'
}
catch {
    if ($run.current_step) {
        foreach ($step in $run.steps) {
            if ($step.name -eq $run.current_step -and $step.status -eq 'running') {
                Finish-Step $run $step.name 'error' $_.Exception.Message $null 1
                break
            }
        }
    }
    $run.status = 'error'
    $run.error = [ordered]@{
        message = $_.Exception.Message
        step = $run.current_step
        at = ConvertTo-IsoUtc (Get-Date)
    }
    Write-Log 'ERROR' "$($run.error.step): $($run.error.message)"
}
finally {
    $finished = Get-Date
    $run.finished_at = ConvertTo-IsoUtc $finished
    $run.duration_seconds = [math]::Round(($finished - $started).TotalSeconds, 2)
    $run.current_step = $null
    Save-Json $lastPath $run
    Save-Json $currentPath $run
    Add-Content -LiteralPath $historyPath -Value ($run | ConvertTo-Json -Depth 20 -Compress) -Encoding UTF8
    Write-Log 'INFO' "Automation run finished: $($run.status) in $($run.duration_seconds)s"
}

if ($run.status -eq 'error') {
    exit 1
}

exit 0
