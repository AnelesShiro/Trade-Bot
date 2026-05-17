from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.config import RiskAutomationSettings
from src.schemas import Action, AgentSignal, Decision, Direction
from src.storage.models import PositionRecord, create_schema
from src.storage.repository import ArenaRepository
from src.trading.execution import PaperExecutionEngine
from src.trading.position_manager import PositionManager
from src.trading.risk_automation.cooldown import CooldownManager
from src.trading.risk_automation.engine import RiskAutomationEngine
from src.trading.risk_automation.position_rules import apply_break_even, apply_trailing_stop, time_exit_due
from src.trading.risk_automation.triggers import evaluate_trigger
from src.trading.risk_automation.types import BreakEvenConfig, TimeExitConfig, TrailingStopConfig
from src.agents.api_failover import ApiFailoverManager


def test_trigger_evaluation_and_logic() -> None:
    assert evaluate_trigger({"logic": "AND", "conditions": [{"field": "price", "op": "gte", "value": 100}]}, price=101, rsi_14=30)
    assert not evaluate_trigger({"logic": "OR", "conditions": [{"field": "rsi_14", "op": "lte", "value": 20}]}, price=101, rsi_14=40)
    assert evaluate_trigger(
        {
            "logic": "OR",
            "conditions": [
                {"field": "price", "op": "lte", "value": 90},
                {"field": "rsi_14", "op": "lte", "value": 25},
            ],
        },
        price=100,
        rsi_14=20,
    )


def test_trailing_stop_only_tightens_long() -> None:
    position = PositionRecord(
        id="p1",
        agent_id="crypto-deepseek",
        symbol="BTC",
        direction="LONG",
        status="OPEN",
        leverage=10,
        margin=1000,
        notional=10000,
        average_entry=100000,
        stop_loss=99000,
        take_profit_1=105000,
        take_profit_2=110000,
    )
    config = TrailingStopConfig(enabled=True, mode="percent", distance_pct=0.01)
    new_sl, state = apply_trailing_stop(position, 105000, config, {})
    assert new_sl > position.stop_loss
    assert state["trailing_active"] is True


def test_break_even_once() -> None:
    position = PositionRecord(
        id="p1",
        agent_id="crypto-deepseek",
        symbol="BTC",
        direction="LONG",
        status="OPEN",
        leverage=10,
        margin=1000,
        notional=10000,
        average_entry=100000,
        stop_loss=99000,
        take_profit_1=101000,
        take_profit_2=110000,
    )
    config = BreakEvenConfig(enabled=True, trigger="tp1")
    new_sl, state, applied = apply_break_even(position, 101500, config, {})
    assert applied
    assert new_sl >= position.average_entry
    _, state2, applied2 = apply_break_even(position, 102000, config, state)
    assert not applied2


def test_time_exit_due() -> None:
    position = PositionRecord(
        id="p1",
        agent_id="crypto-deepseek",
        symbol="BTC",
        direction="LONG",
        status="OPEN",
        leverage=10,
        margin=1000,
        notional=10000,
        average_entry=100000,
        stop_loss=99000,
        take_profit_1=105000,
        take_profit_2=110000,
        opened_at=datetime.now(UTC) - timedelta(hours=30),
    )
    config = TimeExitConfig(enabled=True, max_hold_hours=24)
    assert time_exit_due(position, 100100, config, {})


def test_pending_order_execution(repository: ArenaRepository, test_settings) -> None:
    create_schema(test_settings.database_url)
    position_manager = PositionManager(repository, active_agent_ids={"crypto-deepseek"})
    execution = PaperExecutionEngine(position_manager)
    engine = RiskAutomationEngine(test_settings, repository, position_manager, execution)
    order_id = repository.create_pending_order(
        agent_id="crypto-deepseek",
        trigger_json={"logic": "AND", "conditions": [{"field": "price", "op": "gte", "value": 100}]},
        execution_signal_json={
            "agent": "crypto-deepseek",
            "decision": "PAPER_TRADE",
            "action": "OPEN",
            "symbol": "BTC",
            "direction": "LONG",
            "execution_type": "MARKET",
            "leverage": 5,
            "margin_used_usdt": 500,
            "notional_exposure_usdt": 2500,
            "entry": 100,
            "stop_loss": 95,
            "take_profit_1": 110,
            "take_profit_2": 120,
            "account_risk_usdt": 50,
            "thesis": "trigger test",
            "invalidation": "n/a",
            "counterargument": "n/a",
            "data_used": ["test"],
        },
        expires_at=None,
        source_signal_id=None,
    )
    from src.schemas import MarketState, IndicatorSnapshot

    market = MarketState(symbol="BTCUSDT", exchange="binanceusdm", current_price=101, timeframe="1h", indicators=IndicatorSnapshot(rsi_14=50))
    stats = engine.run_market_tick(market, rsi_14=50)
    assert stats["pending_triggered"] == 1
    row = repository.get_pending_order(order_id)
    assert row.status == "TRIGGERED"
    assert repository.open_positions()


def test_cooldown_blocks(repository: ArenaRepository, test_settings) -> None:
    manager = CooldownManager(repository, test_settings.risk_automation.cooldown)
    manager.start("crypto-deepseek", "test", 1)
    assert manager.blocks_new_entries("crypto-deepseek")


def test_failover_error_detection(test_settings, repository) -> None:
    manager = ApiFailoverManager(test_settings, repository)
    assert manager.is_failover_error("GatewayClientRequestError: billing error 401")
