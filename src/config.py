from __future__ import annotations

import os
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AgentSettings(BaseModel):
    id: str
    name: str
    model: str
    session_id: str


class CompetitionSettings(BaseModel):
    name: str
    duration_days: int = 7
    poll_interval_seconds: int = 3600
    event_cooldown_seconds: int = 1800
    symbol: str = "BTC/USDT:USDT"
    display_symbol: str = "BTCUSDT"
    timeframe: str = "1h"
    ohlcv_limit: int = 240


class AccountSettings(BaseModel):
    initial_equity: float = 10000.0
    quote_currency: str = "USDT"


class RiskSettings(BaseModel):
    max_leverage: float = 10.0
    max_margin_per_action_pct: float = 0.10
    max_total_account_risk_pct: float = 0.02
    max_open_positions: int = 3
    max_dca_per_position: int = 2
    daily_loss_limit_pct: float = 0.03
    min_rr_tp1: float = 1.5
    min_rr_tp2: float = 2.0


class MarketSettings(BaseModel):
    exchange: str = "binanceusdm"
    sandbox: bool = False
    fetch_funding: bool = True
    fetch_open_interest: bool = True


class SharedLearningSettings(BaseModel):
    enabled: bool = True
    shared_ratio: float = 0.30
    private_ratio: float = 0.70
    min_sample_size: int = 10
    min_win_rate: float = 0.60
    min_profit_factor: float = 1.5
    compatibility_threshold: float = 0.50
    agreement_threshold: float = 0.85
    reduced_shared_ratio: float = 0.10


class ApiSettings(BaseModel):
    timeout_seconds: int = 600
    max_retries: int = 3
    backoff_initial_seconds: float = 1.0
    backoff_multiplier: float = 2.0


class ExecutionSettings(BaseModel):
    taker_fee_rate: float = 0.0005
    slippage_bps: float = 2.0


class SafetySettings(BaseModel):
    warmup_cycles: int = 0
    kill_switch_file: str = "KILL_SWITCH"
    require_preflight_for_live: bool = True
    minimum_free_disk_mb: int = 500
    downtime_threshold_seconds: int = 60


class HotReloadSettings(BaseModel):
    enabled: bool = True
    auto_detect_changes: bool = True
    check_interval_seconds: int = 5
    rollback_backups_to_keep: int = 10


class CloudDashboardSettings(BaseModel):
    enabled: bool = True
    snapshot_path: str = "cloud/dashboard_snapshot.json"
    git_auto_push: bool = True
    git_branch: str = "main"
    push_after_each_cycle: bool = True
    min_push_interval_seconds: int = 300
    render_enabled: bool = True
    stale_warning_minutes: int = 15
    stale_critical_minutes: int = 60


class FeatureFlagSettings(BaseModel):
    enabled: bool = False
    agents: list[str] = Field(default_factory=list)


class PathSettings(BaseModel):
    database: str = "database/arena.db"
    rulebook: str = "config/rulebook.md"
    outputs_dir: str = "outputs"
    signals: str = "outputs/SIGNALS.md"
    ledger: str = "outputs/LEDGER.csv"
    evaluation: str = "outputs/EVALUATION.md"
    logs_dir: str = "logs"


class Settings(BaseModel):
    competition: CompetitionSettings
    accounts: AccountSettings
    risk: RiskSettings
    market: MarketSettings
    shared_learning: SharedLearningSettings = Field(default_factory=SharedLearningSettings)
    api: ApiSettings = Field(default_factory=ApiSettings)
    execution: ExecutionSettings = Field(default_factory=ExecutionSettings)
    safety: SafetySettings = Field(default_factory=SafetySettings)
    hot_reload: HotReloadSettings = Field(default_factory=HotReloadSettings)
    cloud_dashboard: CloudDashboardSettings = Field(default_factory=CloudDashboardSettings)
    feature_flags: dict[str, FeatureFlagSettings] = Field(default_factory=dict)
    agents: list[AgentSettings] = Field(default_factory=list)
    paths: PathSettings

    @property
    def database_url(self) -> str:
        override = os.getenv("ARENA_DATABASE_URL")
        default_database = PROJECT_ROOT / PathSettings().database
        if override and self.resolve_path(self.paths.database) == default_database:
            return override
        return f"sqlite:///{self.resolve_path(self.paths.database)}"

    def resolve_path(self, value: str | Path) -> Path:
        path = Path(value)
        return path if path.is_absolute() else PROJECT_ROOT / path

    def feature_enabled(self, flag: str, agent_id: str | None = None) -> bool:
        setting = self.feature_flags.get(flag)
        if not setting or not setting.enabled:
            return False
        return agent_id is None or not setting.agents or agent_id in setting.agents


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_settings(config_path: str | Path | None = None) -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    path = Path(config_path) if config_path else PROJECT_ROOT / "config" / "settings.yaml"
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return Settings.model_validate(_load_yaml(path))


def settings_path(config_path: str | Path | None = None) -> Path:
    path = Path(config_path) if config_path else PROJECT_ROOT / "config" / "settings.yaml"
    return path if path.is_absolute() else PROJECT_ROOT / path


def canonical_settings_payload(path: str | Path | None = None) -> dict[str, Any]:
    return load_settings(path).model_dump(mode="json")


def settings_hash(path: str | Path | None = None) -> str:
    payload = json.dumps(canonical_settings_payload(path), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_rulebook(settings: Settings | None = None) -> str:
    current = settings or load_settings()
    return current.resolve_path(current.paths.rulebook).read_text(encoding="utf-8")
