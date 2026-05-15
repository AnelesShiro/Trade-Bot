$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$LogsDir = Join-Path $ProjectRoot "logs"
$PidFile = Join-Path $LogsDir "dashboard-local.pid"
$OutLog = Join-Path $LogsDir "dashboard-local.out.log"
$ErrLog = Join-Path $LogsDir "dashboard-local.err.log"
$Port = 8501
$Url = "http://127.0.0.1:$Port"

New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null

if (-not (Test-Path $Python)) {
    Write-Host "Missing virtualenv Python: $Python" -ForegroundColor Red
    Write-Host "Run: python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
    Read-Host "Press Enter to close"
    exit 1
}

$ExistingPort = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
    Where-Object { $_.State -eq "Listen" } |
    Select-Object -First 1

if ($ExistingPort) {
    $ExistingPort.OwningProcess | Set-Content -Path $PidFile -Encoding ASCII
    Start-Process $Url
    Write-Host "Local dashboard is already running at $Url"
    exit 0
}

$env:PYTHONIOENCODING = "utf-8"

$Process = Start-Process `
    -FilePath $Python `
    -ArgumentList "-m", "src.cli", "dashboard", "--port", "$Port" `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $OutLog `
    -RedirectStandardError $ErrLog `
    -PassThru

$Process.Id | Set-Content -Path $PidFile -Encoding ASCII
Start-Sleep -Seconds 3
Start-Process $Url

Write-Host "Started local dashboard at $Url"
Write-Host "PID: $($Process.Id)"
Write-Host "Logs: $OutLog / $ErrLog"
