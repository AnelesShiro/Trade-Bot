from __future__ import annotations

import importlib.util
import os
import shutil
import socket
from dataclasses import dataclass
from pathlib import Path

from src.config import Settings, load_rulebook
from src.market.data_feed import MarketDataFeed
from src.storage.models import create_schema


@dataclass(frozen=True)
class CheckResult:
    component: str
    status: str
    critical: bool
    message: str

    @property
    def passed(self) -> bool:
        return self.status == "PASS"


def run_preflight(settings: Settings) -> list[CheckResult]:
    results = [
        _check_api_keys(),
        _check_database(settings),
        _check_market_data(settings),
        _check_rulebook(settings),
        _check_prompts(settings),
        _check_dashboard(),
        _check_directories(settings),
        _check_disk_space(settings),
        _check_dependencies(),
    ]
    return results


def has_critical_failures(results: list[CheckResult]) -> bool:
    return any(not result.passed and result.critical for result in results)


def _check_api_keys() -> CheckResult:
    missing = [name for name in ["DEEPSEEK_API_KEY", "XAI_API_KEY"] if not os.getenv(name)]
    if missing:
        return CheckResult("api_keys", "FAIL", True, f"Missing {', '.join(missing)}")
    return CheckResult("api_keys", "PASS", True, "Required API key environment variables are present")


def _check_database(settings: Settings) -> CheckResult:
    try:
        create_schema(settings.database_url)
        return CheckResult("database", "PASS", True, settings.database_url)
    except Exception as error:
        return CheckResult("database", "FAIL", True, str(error))


def _check_market_data(settings: Settings) -> CheckResult:
    try:
        feed = MarketDataFeed(settings.market)
        frame = feed.fetch_ohlcv(settings.competition.symbol, settings.competition.timeframe, min(5, settings.competition.ohlcv_limit))
        if frame.empty:
            return CheckResult("market_data_feed", "FAIL", True, "OHLCV frame is empty")
        return CheckResult("market_data_feed", "PASS", True, f"Fetched {len(frame)} candles")
    except Exception as error:
        return CheckResult("market_data_feed", "FAIL", True, str(error))


def _check_rulebook(settings: Settings) -> CheckResult:
    try:
        text = load_rulebook(settings)
        if not text.strip():
            return CheckResult("rulebook", "FAIL", True, "Rulebook is empty")
        return CheckResult("rulebook", "PASS", True, f"{len(text)} chars")
    except Exception as error:
        return CheckResult("rulebook", "FAIL", True, str(error))


def _check_prompts(settings: Settings) -> CheckResult:
    path = settings.resolve_path("prompts/system_prompt.md")
    try:
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            return CheckResult("prompts", "FAIL", True, "system_prompt.md is empty")
        return CheckResult("prompts", "PASS", True, f"{path}")
    except Exception as error:
        return CheckResult("prompts", "FAIL", True, str(error))


def _check_dashboard() -> CheckResult:
    try:
        import streamlit  # noqa: F401
        import plotly  # noqa: F401

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            port_free = sock.connect_ex(("127.0.0.1", 8501)) != 0
        message = "Streamlit and Plotly import OK; port 8501 free" if port_free else "Streamlit and Plotly import OK; port 8501 already in use"
        return CheckResult("dashboard", "PASS", False, message)
    except Exception as error:
        return CheckResult("dashboard", "FAIL", False, str(error))


def _check_directories(settings: Settings) -> CheckResult:
    required = [
        settings.resolve_path(settings.paths.outputs_dir),
        settings.resolve_path(settings.paths.logs_dir),
        settings.resolve_path("data/raw"),
        settings.resolve_path("data/processed"),
        settings.resolve_path("data/vectors"),
        settings.resolve_path("data/private/deepseek"),
        settings.resolve_path("data/private/grok"),
        settings.resolve_path("data/shared"),
        settings.resolve_path("data/profiles"),
        settings.resolve_path("database"),
    ]
    for path in required:
        path.mkdir(parents=True, exist_ok=True)
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        return CheckResult("required_directories", "FAIL", True, "; ".join(missing))
    return CheckResult("required_directories", "PASS", True, f"{len(required)} directories ready")


def _check_disk_space(settings: Settings) -> CheckResult:
    usage = shutil.disk_usage(settings.resolve_path("."))
    free_mb = usage.free / (1024 * 1024)
    if free_mb < settings.safety.minimum_free_disk_mb:
        return CheckResult("disk_space", "FAIL", True, f"{free_mb:.0f} MB free")
    return CheckResult("disk_space", "PASS", True, f"{free_mb:.0f} MB free")


def _check_dependencies() -> CheckResult:
    packages = ["ccxt", "pandas", "numpy", "sqlalchemy", "pydantic", "streamlit", "plotly", "typer", "loguru", "yaml"]
    missing = [package for package in packages if importlib.util.find_spec(package) is None]
    if missing:
        return CheckResult("dependencies", "FAIL", True, f"Missing {', '.join(missing)}")
    return CheckResult("dependencies", "PASS", True, f"{len(packages)} packages available")
