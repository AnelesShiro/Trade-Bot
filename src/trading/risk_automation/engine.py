from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from src.config import RiskAutomationSettings, Settings
from src.schemas import Action, AgentSignal, Decision, Direction, MarketState
from src.storage.repository import ArenaRepository
from src.trading.execution import PaperExecutionEngine
from src.trading.position_manager import PositionManager
from src.trading.risk_automation.cooldown import CooldownManager
from src.trading.risk_automation.position_rules import (
    apply_break_even,
    apply_trailing_stop,
    default_max_hold_until,
    parse_position_risk,
    time_exit_due,
)
from src.trading.risk_automation.triggers import evaluate_trigger, trigger_expired
from src.trading.risk_automation.types import PositionRiskAutomation, TriggerOrderPayload


class RiskAutomationEngine:
    def __init__(
        self,
        settings: Settings,
        repository: ArenaRepository,
        position_manager: PositionManager,
        execution: PaperExecutionEngine,
    ) -> None:
        self.settings = settings
        self.cfg: RiskAutomationSettings = settings.risk_automation
        self.repository = repository
        self.position_manager = position_manager
        self.execution = execution
        self.cooldowns = CooldownManager(repository, self.cfg.cooldown)

    @property
    def enabled(self) -> bool:
        return self.cfg.enabled

    def blocks_new_entries(self, agent_id: str) -> bool:
        try:
            return self.cooldowns.blocks_new_entries(agent_id)
        except Exception as error:
            logger.warning("cooldown check failed without blocking trading: {}", error)
            return False

    def run_market_tick(
        self,
        market_state: MarketState,
        *,
        rsi_14: float | None = None,
        atr_14: float | None = None,
    ) -> dict[str, int]:
        stats = {"pending_triggered": 0, "time_exits": 0, "trailing_updates": 0}
        if not self.enabled:
            return stats
        try:
            stats["pending_triggered"] = self._process_pending_orders(market_state, rsi_14=rsi_14)
        except Exception as error:
            logger.exception("pending order processing failed without stopping trading: {}", error)
        try:
            automation_stats = self._process_position_automation(market_state, rsi_14=rsi_14, atr_14=atr_14)
            stats.update(automation_stats)
        except Exception as error:
            logger.exception("position automation failed without stopping trading: {}", error)
        return stats

    def handle_place_trigger(self, signal: AgentSignal, signal_record_id: int | None) -> str | None:
        if not self.cfg.conditional_orders.enabled:
            return None
        payload = signal.trigger_order
        if not payload:
            raise ValueError("trigger_order is required for PLACE_TRIGGER")
        order = TriggerOrderPayload.model_validate(payload)
        execution_payload = dict(order.execution_signal)
        execution_payload["agent"] = signal.agent
        execution_signal = AgentSignal.model_validate(execution_payload)
        if execution_signal.action in {Action.NONE, Action.PLACE_TRIGGER}:
            raise ValueError("trigger_order.execution_signal must be an executable trade action")
        if execution_signal.decision not in {Decision.PAPER_TRADE, Decision.POSITION_UPDATE}:
            raise ValueError("trigger_order.execution_signal must be PAPER_TRADE or POSITION_UPDATE")
        order_id = self.repository.create_pending_order(
            agent_id=signal.agent,
            trigger_json=order.trigger.model_dump(),
            execution_signal_json=execution_signal.model_dump(mode="json"),
            expires_at=order.expires_at,
            source_signal_id=signal_record_id,
        )
        return order_id

    def attach_position_risk(self, position_id: str, signal: AgentSignal) -> None:
        if not self.enabled:
            return
        automation = _resolve_position_risk(signal, self.cfg)
        if not automation:
            return
        state: dict[str, Any] = {"atr_14": None}
        if automation.time_exit and automation.time_exit.enabled:
            position = self.repository.get_position(position_id)
            if position:
                state["max_hold_until"] = default_max_hold_until(position, automation.time_exit)
        self.repository.upsert_position_risk_state(position_id, automation.model_dump(), state)

    def evaluate_agent_cooldowns(self, agent_id: str, *, equity: float, daily_pnl: float) -> None:
        try:
            total, rejected = self.repository.signal_counts(agent_id, limit=20)
            rejection_rate = (rejected / total) if total else 0.0
            api_failures = self.repository.recent_api_failures(agent_id, limit=10)
            weekly_pnl = equity - self.settings.accounts.initial_equity
            self.cooldowns.evaluate_after_cycle(
                agent_id,
                equity=equity,
                daily_pnl=daily_pnl,
                weekly_pnl=weekly_pnl,
                rejection_rate=rejection_rate,
                api_failures=api_failures,
            )
        except Exception as error:
            logger.warning("cooldown evaluation failed for {}: {}", agent_id, error)

    def _process_pending_orders(self, market_state: MarketState, *, rsi_14: float | None) -> int:
        triggered = 0
        for row in self.repository.list_pending_orders(status="PENDING"):
            if trigger_expired(row.expires_at):
                self.repository.update_pending_order(row.id, status="EXPIRED")
                continue
            if not evaluate_trigger(json.loads(row.trigger_json), price=market_state.current_price, rsi_14=rsi_14):
                continue
            if self.cooldowns.blocks_new_entries(row.agent_id):
                continue
            execution_payload = json.loads(row.execution_signal_json)
            signal = AgentSignal.model_validate(execution_payload)
            signal.agent = row.agent_id
            if signal.decision not in {Decision.PAPER_TRADE, Decision.POSITION_UPDATE}:
                signal.decision = Decision.PAPER_TRADE
            if signal.action == Action.NONE:
                signal.action = Action.OPEN
            position_id = self.execution.execute(signal, market_state.current_price)
            self.repository.update_pending_order(
                row.id,
                status="TRIGGERED",
                triggered_at=datetime.now(UTC),
                position_id=position_id,
            )
            if position_id:
                self.attach_position_risk(position_id, signal)
            triggered += 1
        return triggered

    def _process_position_automation(
        self,
        market_state: MarketState,
        *,
        rsi_14: float | None,
        atr_14: float | None,
    ) -> dict[str, int]:
        stats = {"trailing_updates": 0, "time_exits": 0}
        current_price = market_state.current_price
        for position in self.repository.open_positions():
            risk_row = self.repository.get_position_risk_state(position.id)
            if not risk_row:
                continue
            automation = parse_position_risk(risk_row.config_json)
            if not automation:
                continue
            state = json.loads(risk_row.state_json or "{}")
            if atr_14 is not None:
                state["atr_14"] = atr_14
            updated_sl = position.stop_loss
            if automation.trailing_stop and self.cfg.trailing_stop.enabled:
                updated_sl, state = apply_trailing_stop(position, current_price, automation.trailing_stop, state)
                if updated_sl != position.stop_loss:
                    position.stop_loss = updated_sl
                    stats["trailing_updates"] += 1
            if automation.break_even and self.cfg.break_even.enabled:
                updated_sl, state, applied = apply_break_even(position, current_price, automation.break_even, state)
                if applied:
                    position.stop_loss = updated_sl
            if automation.time_exit and self.cfg.time_exit.enabled and time_exit_due(
                position, current_price, automation.time_exit, state
            ):
                close_signal = AgentSignal(
                    agent=position.agent_id,
                    decision=Decision.POSITION_UPDATE,
                    action=Action.CLOSE,
                    symbol="BTC",
                    direction=Direction(position.direction),
                    position_id=position.id,
                    entry=current_price,
                    leverage=position.leverage,
                    margin_used_usdt=position.margin,
                    stop_loss=position.stop_loss,
                    take_profit_1=position.take_profit_1,
                    take_profit_2=position.take_profit_2,
                    thesis="Time-based exit",
                    invalidation="N/A",
                    counterargument="N/A",
                    data_used=["risk_automation_time_exit"],
                )
                self.execution.execute(close_signal, current_price)
                stats["time_exits"] += 1
                continue
            if updated_sl != position.stop_loss or state != json.loads(risk_row.state_json or "{}"):
                self.repository.add_or_update_position(position)
            self.repository.upsert_position_risk_state(position.id, risk_row.config_json, state, merge_state=True)
        return stats


def _resolve_position_risk(signal: AgentSignal, cfg: RiskAutomationSettings) -> PositionRiskAutomation | None:
    defaults: dict[str, Any] = {}
    if cfg.trailing_stop.enabled and cfg.trailing_stop.apply_by_default:
        defaults["trailing_stop"] = {"enabled": True, **cfg.trailing_stop.model_dump(exclude={"apply_by_default"})}
    if cfg.break_even.enabled and cfg.break_even.apply_by_default:
        defaults["break_even"] = {"enabled": True, **cfg.break_even.model_dump(exclude={"apply_by_default"})}
    if cfg.time_exit.enabled and cfg.time_exit.apply_by_default:
        defaults["time_exit"] = {"enabled": True, **cfg.time_exit.model_dump(exclude={"apply_by_default"})}
    if signal.position_risk:
        explicit = PositionRiskAutomation.model_validate(signal.position_risk).model_dump(exclude_none=True)
        defaults.update(explicit)
        if cfg.break_even.enabled and cfg.break_even.apply_by_default:
            defaults["break_even"] = {"enabled": True, **cfg.break_even.model_dump(exclude={"apply_by_default"})}
    if not defaults:
        return None
    return PositionRiskAutomation.model_validate(defaults)
