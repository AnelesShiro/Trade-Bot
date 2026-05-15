from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"


def main() -> int:
    python = str(PYTHON) if PYTHON.exists() else sys.executable
    return subprocess.call([python, "-m", "src.cli", "safe-restart"], cwd=PROJECT_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
