from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.config import ApiFailoverAgentSettings, FailoverRouteSettings
from src.schemas import Action, AgentSignal, Decision, Direction
from src.storage.models import PositionRecord, create_schema
from src.storage.repository import ArenaRepository
from src.trading.execution import PaperExecutionEngine
from src.trading.position_manager import PositionManager
from src.trading.risk_automation.cooldown import CooldownManager
from src.trading.risk_automation.engine import RiskAutomationEngine, _resolve_position_risk
from src.trading.risk_automation.position_rules import apply_break_even, apply_trailing_stop, time_exit_due
from src.trading.risk_automation.pending_order_view import pending_order_view, trigger_summary
from src.trading.risk_automation.triggers import evaluate_trigger
from src.trading.risk_automation.types import BreakEvenConfig, TimeExitConfig, TrailingStopConfig
from src.agents.api_failover import ActiveRoute, ApiFailoverManager


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


def test_step_trailing_stop_tightens_short() -> None:
    position = PositionRecord(
        id="p1",
        agent_id="crypto-deepseek",
        symbol="BTC",
        direction="SHORT",
        status="OPEN",
        leverage=10,
        margin=1000,
        notional=10000,
        average_entry=100000,
        stop_loss=101000,
        take_profit_1=95000,
        take_profit_2=90000,
    )
    config = TrailingStopConfig(enabled=True, mode="step", step_pct=0.01, distance_pct=0.01)
    new_sl, state = apply_trailing_stop(position, 98000, config, {})
    assert new_sl < position.stop_loss
    assert state["last_trail_anchor"] == 98000


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


def test_break_even_applies_by_default_on_open(test_settings) -> None:
    signal = AgentSignal(
        agent="crypto-qwen",
        decision=Decision.PAPER_TRADE,
        action=Action.OPEN,
        symbol="BTC",
        direction=Direction.LONG,
        leverage=5,
        margin_used_usdt=1000,
        notional_exposure_usdt=5000,
        entry=100000,
        stop_loss=99000,
        take_profit_1=103000,
        take_profit_2=105000,
        account_risk_usdt=50,
        thesis="default break-even test",
        invalidation="stop loss",
        counterargument="setup can fail",
        data_used=["test"],
    )

    automation = _resolve_position_risk(signal, test_settings.risk_automation)

    assert automation is not None
    assert automation.break_even is not None
    assert automation.break_even.enabled is True
    assert automation.break_even.trigger == "r_multiple"
    assert automation.break_even.r_multiple == 1.0


def test_break_even_default_cannot_be_disabled_by_signal(test_settings) -> None:
    signal = AgentSignal(
        agent="crypto-qwen",
        decision=Decision.PAPER_TRADE,
        action=Action.OPEN,
        symbol="BTC",
        direction=Direction.LONG,
        leverage=5,
        margin_used_usdt=1000,
        notional_exposure_usdt=5000,
        entry=100000,
        stop_loss=99000,
        take_profit_1=103000,
        take_profit_2=105000,
        account_risk_usdt=50,
        thesis="mandatory break-even test",
        invalidation="stop loss",
        counterargument="setup can fail",
        data_used=["test"],
        position_risk={
            "break_even": {"enabled": False, "trigger": "tp1"},
            "time_exit": {"enabled": True, "max_hold_hours": 12},
        },
    )

    automation = _resolve_position_risk(signal, test_settings.risk_automation)

    assert automation is not None
    assert automation.break_even is not None
    assert automation.break_even.enabled is True
    assert automation.break_even.trigger == "r_multiple"
    assert automation.break_even.r_multiple == 1.0
    assert automation.time_exit is not None
    assert automation.time_exit.max_hold_hours == 12


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


def test_pending_order_view_extracts_intent_and_trigger_summary() -> None:
    view = pending_order_view(
        order_id="po-test",
        agent_id="crypto-qwen",
        status="PENDING",
        trigger_json={
            "logic": "AND",
            "conditions": [
                {"field": "price", "op": "lte", "value": 78000},
                {"field": "rsi_14", "op": "lte", "value": 30},
            ],
        },
        execution_signal_json={
            "action": "OPEN",
            "direction": "LONG",
            "entry": 78000,
            "stop_loss": 77500,
            "take_profit_1": 79000,
            "leverage": 5,
            "thesis": "Buy pullback into support with RSI confirmation.",
        },
    )

    assert view["intent"] == "OPEN LONG"
    assert view["action"] == "OPEN"
    assert view["direction"] == "LONG"
    assert view["entry_price"] == 78000
    assert view["stop_loss"] == 77500
    assert view["take_profit_1"] == 79000
    assert view["leverage"] == 5
    assert view["trigger_summary"] == "Price <= 78000 AND RSI14 <= 30"
    assert view["thesis"] == "Buy pullback into support with RSI confirmation."


def test_trigger_summary_formats_single_condition() -> None:
    assert trigger_summary({"logic": "OR", "conditions": [{"field": "price", "op": "gte", "value": 80000}]}) == "Price >= 80000"


def test_place_trigger_rejects_invalid_execution_signal(repository: ArenaRepository, test_settings) -> None:
    position_manager = PositionManager(repository, active_agent_ids={"crypto-deepseek"})
    execution = PaperExecutionEngine(position_manager)
    engine = RiskAutomationEngine(test_settings, repository, position_manager, execution)
    signal = AgentSignal(
        agent="crypto-deepseek",
        decision=Decision.PAPER_TRADE,
        action=Action.PLACE_TRIGGER,
        symbol="BTC",
        direction=Direction.NONE,
        trigger_order={
            "trigger": {"logic": "AND", "conditions": [{"field": "price", "op": "gte", "value": 100}]},
            "execution_signal": {
                "agent": "crypto-deepseek",
                "decision": "PAPER_TRADE",
                "action": "OPEN",
                "symbol": "BTC",
                "direction": "LONG",
                "data_used": ["test"],
            },
        },
        thesis="place trigger",
        invalidation="n/a",
        counterargument="n/a",
        data_used=["test"],
    )
    with pytest.raises(ValueError):
        engine.handle_place_trigger(signal, signal_record_id=None)


def test_cooldown_blocks(repository: ArenaRepository, test_settings) -> None:
    manager = CooldownManager(repository, test_settings.risk_automation.cooldown)
    manager.start("crypto-deepseek", "test", 1)
    assert manager.blocks_new_entries("crypto-deepseek")
    assert repository.risk_notifications(limit=1)[0].event_type == "COOLDOWN_STARTED"


def test_weekly_drawdown_starts_cooldown(repository: ArenaRepository, test_settings) -> None:
    manager = CooldownManager(repository, test_settings.risk_automation.cooldown)
    manager.evaluate_after_cycle(
        "crypto-deepseek",
        equity=10000,
        daily_pnl=0,
        weekly_pnl=-1200,
        rejection_rate=0,
        api_failures=0,
    )
    state = repository.active_cooldown("crypto-deepseek")
    assert state is not None
    assert "weekly drawdown" in state.reason


def test_failover_error_detection(test_settings, repository) -> None:
    manager = ApiFailoverManager(test_settings, repository)
    assert manager.is_failover_error("GatewayClientRequestError: billing error 401")


def test_failover_route_settings_update_model_lock(test_settings, repository) -> None:
    manager = ApiFailoverManager(test_settings, repository)
    agent = test_settings.agents[1]
    route = ActiveRoute(
        provider="deepseek",
        model="deepseek-v4-flash",
        base_url="",
        api_key_env="DEEPSEEK_API_KEY",
        using_fallback=True,
        fallback_index=0,
    )
    fallback_agent = manager.settings_for_route(agent, route)
    assert fallback_agent.id == agent.id
    assert fallback_agent.provider == "deepseek"
    assert fallback_agent.model == "deepseek-v4-flash"
    assert fallback_agent.llm.LLM_ALLOW_FALLBACK is False


def test_failover_preserves_primary_when_fallback_fails(test_settings, repository, monkeypatch) -> None:
    manager = ApiFailoverManager(test_settings, repository)
    agent = test_settings.agents[0].model_copy(
        update={
            "api_failover": ApiFailoverAgentSettings(
                enabled=True,
                fallback_chain=[
                    FailoverRouteSettings(provider="qwen", model="qwen3-max-2026-01-23", LLM_API_KEY="QWEN_API_KEY"),
                    FailoverRouteSettings(provider="deepseek-backup", model="deepseek-chat", LLM_API_KEY="DEEPSEEK_API_KEY"),
                ],
            )
        }
    )
    monkeypatch.setattr(manager, "_apply_openclaw_route", lambda *args, **kwargs: None)

    first_route = manager.handle_failure(agent, "billing error 402")
    second_agent = manager.settings_for_route(agent, first_route)
    second_route = manager.handle_failure(second_agent, "timeout")

    state = repository.get_agent_failover_state(agent.id)
    events = repository.failover_events(limit=2)
    assert second_route is not None
    assert state.primary_provider == "deepseek"
    assert state.primary_model == "deepseek-v4-flash"
    assert state.active_provider == "deepseek-backup"
    assert events[0].from_provider == "qwen"
    assert events[0].to_provider == "deepseek-backup"
