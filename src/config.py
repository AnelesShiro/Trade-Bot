from __future__ import annotations

import os
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class LlmLockSettings(BaseModel):
    LLM_PROVIDER: str
    LLM_MODEL: str
    LLM_BASE_URL: str = ""
    LLM_API_KEY: str = ""
    LLM_ALLOW_FALLBACK: bool = False

    @model_validator(mode="after")
    def validate_model_lock(self) -> "LlmLockSettings":
        if not self.LLM_MODEL or not self.LLM_MODEL.strip():
            raise ValueError("LLM_MODEL is required for strict model locking")
        if self.LLM_MODEL.strip().lower() in {"auto", "default", "latest", "best"}:
            raise ValueError("LLM_MODEL must be an exact model id, not an alias")
        if self.LLM_ALLOW_FALLBACK:
            raise ValueError("LLM_ALLOW_FALLBACK must be false; automatic model switching is disabled")
        return self


class FailoverRouteSettings(BaseModel):
    provider: str
    model: str
    LLM_BASE_URL: str = ""
    LLM_API_KEY: str = ""


class ApiFailoverAgentSettings(BaseModel):
    enabled: bool = False
    fallback_chain: list[FailoverRouteSettings] = Field(default_factory=list)
    retest_interval_seconds: int = 3600


class AgentSettings(BaseModel):
    id: str
    name: str
    session_id: str = ""
    system_prompt_override: str = ""
    llm: LlmLockSettings
    api_failover: ApiFailoverAgentSettings = Field(default_factory=ApiFailoverAgentSettings)

    @property
    def model(self) -> str:
        return self.llm.LLM_MODEL

    @property
    def provider(self) -> str:
        return self.llm.LLM_PROVIDER


class CompetitionSettings(BaseModel):
    name: str
    duration_days: int = 0
    weekly_target_pct: float = 0.07
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


class ConditionalOrdersSettings(BaseModel):
    enabled: bool = True


class TrailingStopSettings(BaseModel):
    enabled: bool = True
    apply_by_default: bool = False
    mode: str = "percent"
    distance_pct: float = 0.01
    atr_multiple: float = 1.5
    step_pct: float = 0.005


class BreakEvenSettings(BaseModel):
    enabled: bool = True
    apply_by_default: bool = True
    trigger: str = "r_multiple"
    r_multiple: float = 1.0
    percent_gain: float = 0.01
    fee_buffer_pct: float = 0.0005


class TimeExitSettings(BaseModel):
    enabled: bool = True
    apply_by_default: bool = False
    max_hold_hours: float = 24.0
    only_if_profit_pct_below: float | None = None


class CooldownSettings(BaseModel):
    enabled: bool = True
    consecutive_losses: int = 3
    pause_hours_after_losses: float = 6.0
    daily_loss_pct: float = 0.05
    pause_hours_daily: float = 24.0
    weekly_drawdown_pct: float = 0.10
    pause_hours_weekly: float = 24.0
    rejection_rate_threshold: float = 0.80
    api_failure_threshold: int = 5


class ApiFailoverSettings(BaseModel):
    enabled: bool = True


class RiskAutomationSettings(BaseModel):
    enabled: bool = True
    conditional_orders: ConditionalOrdersSettings = Field(default_factory=ConditionalOrdersSettings)
    trailing_stop: TrailingStopSettings = Field(default_factory=TrailingStopSettings)
    break_even: BreakEvenSettings = Field(default_factory=BreakEvenSettings)
    time_exit: TimeExitSettings = Field(default_factory=TimeExitSettings)
    cooldown: CooldownSettings = Field(default_factory=CooldownSettings)
    api_failover: ApiFailoverSettings = Field(default_factory=ApiFailoverSettings)


class SafetySettings(BaseModel):
    warmup_cycles: int = 0
    kill_switch_file: str = "KILL_SWITCH"
    require_preflight_for_live: bool = True
    minimum_free_disk_mb: int = 500
    downtime_threshold_seconds: int = 60
    position_monitor_enabled: bool = True
    position_monitor_interval_seconds: int = 30


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


class FeaturesSettings(BaseModel):
    improved_shared_learning: bool = True
    event_driven_tp_sl: bool = True
    advanced_risk_model: bool = False
    cloud_sync: bool = True


class CanarySettings(BaseModel):
    enabled: bool = False
    target_agents: list[str] = Field(default_factory=list)


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
    risk_automation: RiskAutomationSettings = Field(default_factory=RiskAutomationSettings)
    safety: SafetySettings = Field(default_factory=SafetySettings)
    hot_reload: HotReloadSettings = Field(default_factory=HotReloadSettings)
    cloud_dashboard: CloudDashboardSettings = Field(default_factory=CloudDashboardSettings)
    features: FeaturesSettings = Field(default_factory=FeaturesSettings)
    canary: CanarySettings = Field(default_factory=CanarySettings)
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


def safe_features(settings: Settings) -> FeaturesSettings:
    features = getattr(settings, "features", None)
    return features if isinstance(features, FeaturesSettings) else FeaturesSettings()


def safe_canary(settings: Settings) -> CanarySettings:
    canary = getattr(settings, "canary", None)
    return canary if isinstance(canary, CanarySettings) else CanarySettings()
