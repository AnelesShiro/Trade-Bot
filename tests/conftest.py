from __future__ import annotations

from collections.abc import Iterator

import pytest

from src.config import AgentSettings, CloudDashboardSettings, CompetitionSettings, MarketSettings, PathSettings, RiskSettings, Settings, AccountSettings
from src.storage.models import create_schema, build_session_factory
from src.storage.repository import ArenaRepository


@pytest.fixture()
def repository(tmp_path) -> Iterator[ArenaRepository]:
    db = tmp_path / "arena.db"
    url = f"sqlite:///{db}"
    create_schema(url)
    repo = ArenaRepository(build_session_factory(url))
    yield repo


@pytest.fixture()
def test_settings(tmp_path) -> Settings:
    return Settings(
        competition=CompetitionSettings(name="test", symbol="BTC/USDT:USDT", display_symbol="BTCUSDT"),
        accounts=AccountSettings(initial_equity=10000),
        risk=RiskSettings(),
        market=MarketSettings(fetch_funding=False, fetch_open_interest=False),
        agents=[
            AgentSettings(
                id="crypto-deepseek",
                name="Crypto DeepSeek",
                model="deepseek/deepseek-v4-flash",
                session_id="crypto-deepseek",
            ),
            AgentSettings(
                id="crypto-grok",
                name="Crypto Grok",
                model="xai/grok-4-1-fast",
                session_id="crypto-grok",
            ),
        ],
        paths=PathSettings(
            database=str(tmp_path / "arena.db"),
            rulebook=str(tmp_path / "rulebook.md"),
            outputs_dir=str(tmp_path / "outputs"),
            signals=str(tmp_path / "outputs" / "SIGNALS.md"),
            ledger=str(tmp_path / "outputs" / "LEDGER.csv"),
            evaluation=str(tmp_path / "outputs" / "EVALUATION.md"),
            logs_dir=str(tmp_path / "logs"),
        ),
        cloud_dashboard=CloudDashboardSettings(enabled=False, snapshot_path=str(tmp_path / "cloud" / "dashboard_snapshot.json")),
    )
