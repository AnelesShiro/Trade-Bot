from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
LOGS = PROJECT_ROOT / "logs"


def live_runner_count() -> int:
    if os.name == "nt":
        command = [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.CommandLine -like '*src.cli run-live*' -and $_.Name -like 'python*' } | "
            "Measure-Object | Select-Object -ExpandProperty Count",
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        try:
            return int(result.stdout.strip() or "0")
        except ValueError:
            return 0
    result = subprocess.run(["pgrep", "-f", "src.cli run-live"], capture_output=True, text=True, check=False)
    return len([line for line in result.stdout.splitlines() if line.strip()])


def start_runner() -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    python = str(PYTHON) if PYTHON.exists() else sys.executable
    stdout = (LOGS / "watchdog-live.out.log").open("ab")
    stderr = (LOGS / "watchdog-live.err.log").open("ab")
    kwargs = {
        "cwd": PROJECT_ROOT,
        "stdout": stdout,
        "stderr": stderr,
        "stdin": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    subprocess.Popen([python, "-m", "src.cli", "run-live", "--resume"], **kwargs)


def main() -> int:
    interval = int(os.getenv("ARENA_WATCHDOG_INTERVAL_SECONDS", "30"))
    while True:
        if live_runner_count() == 0:
            start_runner()
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
