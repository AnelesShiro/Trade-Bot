$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$OpenClaw = "C:\Users\Admin\AppData\Roaming\npm\openclaw.cmd"
$LogsDir = Join-Path $ProjectRoot "logs"
$PidFile = Join-Path $LogsDir "bot-live.pid"
$BootstrapLog = Join-Path $LogsDir "bot-live-task.bootstrap.log"
$OutLog = Join-Path $LogsDir "bot-live-task.out.log"
$ErrLog = Join-Path $LogsDir "bot-live-task.err.log"

New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null

$Existing = Get-CimInstance Win32_Process |
    Where-Object {
        $_.Name -like "python*" -and
        $_.CommandLine -like "*src.cli*run-live*" -and
        $_.CommandLine -like "*crypto-paper-trading-arena*"
    }

if ($Existing) {
    $Existing[0].ProcessId | Set-Content -Path $PidFile -Encoding ASCII
    "Bot already running with PID $($Existing[0].ProcessId) at $(Get-Date -Format o)" | Add-Content -Path $BootstrapLog -Encoding UTF8
    exit 0
}

$env:OPENCLAW_BIN = $OpenClaw
$env:PYTHONIOENCODING = "utf-8"

"Starting bot at $(Get-Date -Format o)" | Add-Content -Path $BootstrapLog -Encoding UTF8

$Process = Start-Process `
    -FilePath $Python `
    -ArgumentList "-m", "src.cli", "run-live", "--resume" `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $OutLog `
    -RedirectStandardError $ErrLog `
    -PassThru

$Process.Id | Set-Content -Path $PidFile -Encoding ASCII
"Started bot PID $($Process.Id)" | Add-Content -Path $BootstrapLog -Encoding UTF8
