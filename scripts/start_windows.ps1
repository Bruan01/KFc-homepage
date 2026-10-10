param([switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectDir
$pythonPath = Join-Path $projectDir '.venv\Scripts\python.exe'

function Invoke-Django {
    & $pythonPath manage.py @args
    if ($LASTEXITCODE -ne 0) {
        throw "Django command failed (exit $LASTEXITCODE). Startup stopped."
    }
}

function Find-ProjectProcess([string]$command) {
    Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq 'python.exe' -and $_.CommandLine -and
        $_.CommandLine.IndexOf($projectDir + '\', [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
        $_.CommandLine -match ('manage\.py\s+' + [regex]::Escape($command) + '(?:\s|$)')
    } | Select-Object -First 1
}

function Test-WebReady {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "$siteUrl/api/health" -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

try {
    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
        throw "Project virtual environment is missing. Run: python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
    }
    & $pythonPath -c 'import django, cryptography, PIL' 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Project dependencies are missing. Run: .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
    }
    Write-Host "Python: $pythonPath"

    # Let Django load .env and apply the same host/port defaults as start.sh.
    $settingsCode = "import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','kflow.settings'); from django.conf import settings; print(settings.SERVER_HOST); print(settings.SERVER_PORT); print(settings.DATABASES['default']['NAME'])"
    $settingsLines = @(& $pythonPath -c $settingsCode)
    if ($LASTEXITCODE -ne 0 -or $settingsLines.Count -lt 3) { throw 'Could not load Django settings.' }
    $serverHost = [string]$settingsLines[0]
    $serverPort = [int]$settingsLines[1]
    $databasePath = [string]$settingsLines[2]
    $serverAddress = '{0}:{1}' -f $serverHost, $serverPort
    $browserHost = if ($serverHost -in @('0.0.0.0', '::')) { '127.0.0.1' } else { $serverHost }
    if ($browserHost.Contains(':')) { $browserHost = "[$browserHost]" }
    $siteUrl = 'http://{0}:{1}' -f $browserHost, $serverPort

    if (Test-Path -LiteralPath $databasePath -PathType Leaf) {
        Invoke-Django backup_database
    }
    Invoke-Django migrate --fake-initial --noinput

    $logDir = Join-Path $projectDir 'data\logs'
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $web = Find-ProjectProcess 'runserver'
    if ($web) {
        if (-not (Test-WebReady)) {
            throw "A project Web process is already running (PID $($web.ProcessId)), but $siteUrl is not responding. Check its console or logs before restarting."
        }
        Write-Host "Web already running (PID $($web.ProcessId))."
    } else {
        # Refuse an occupied port instead of starting a server that immediately exits.
        $listener = Get-NetTCPConnection -State Listen -LocalPort $serverPort -ErrorAction SilentlyContinue
        if ($listener) { throw "Port $serverPort is already in use by another process." }
        $web = Start-Process -FilePath $pythonPath -ArgumentList @('manage.py', 'runserver', $serverAddress, '--noreload') -WorkingDirectory $projectDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDir 'runserver.out.log') -RedirectStandardError (Join-Path $logDir 'runserver.err.log')
        $ready = $false
        for ($attempt = 0; $attempt -lt 15; $attempt++) {
            Start-Sleep -Milliseconds 500
            $web.Refresh()
            if ($web.HasExited) { break }
            if (Test-WebReady) { $ready = $true; break }
        }
        if (-not $ready) { throw "Web did not start successfully. Check $logDir\runserver.err.log" }
        Write-Host "Web started (PID $($web.Id))."
    }

    $worker = Find-ProjectProcess 'process_imaging_jobs'
    if ($worker) {
        Write-Host "Imaging worker already running (PID $($worker.ProcessId))."
    } else {
        $worker = Start-Process -FilePath $pythonPath -ArgumentList @('manage.py', 'process_imaging_jobs', '--interval', '2') -WorkingDirectory $projectDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDir 'imaging-worker.out.log') -RedirectStandardError (Join-Path $logDir 'imaging-worker.err.log')
        Start-Sleep -Milliseconds 500
        $worker.Refresh()
        if ($worker.HasExited) { throw "Imaging worker failed. Check $logDir\imaging-worker.err.log" }
        Write-Host "Imaging worker started (PID $($worker.Id))."
    }

    Write-Host "Ready: $siteUrl"
    Write-Host "Logs: $logDir"
    if (-not $NoBrowser) { Start-Process $siteUrl }
    exit 0
} catch {
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
