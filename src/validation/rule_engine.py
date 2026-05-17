from __future__ import annotations

from src.config import RiskSettings
from src.schemas import Action, AgentSignal, Decision, Direction, ValidationResult
from src.trading.pnl import risk_at_stop


class RuleEngine:
    def __init__(self, risk: RiskSettings, initial_equity: float) -> None:
        self.risk = risk
        self.initial_equity = initial_equity

    def validate(
        self,
        signal: AgentSignal,
        current_equity: float,
        open_positions_count: int,
        current_total_risk: float,
        daily_pnl: float,
        dca_count_for_position: int = 0,
        recent_stop_loss_same_direction: bool = False,
    ) -> ValidationResult:
        reasons: list[str] = []
        if signal.decision in {Decision.NO_TRADE, Decision.WATCHLIST}:
            return ValidationResult(accepted=True)
        if signal.action == Action.PLACE_TRIGGER:
            if not signal.trigger_order:
                reasons.append("trigger_order is required for PLACE_TRIGGER")
            if not signal.data_used:
                reasons.append("data_used is required")
            return ValidationResult(accepted=not reasons, reasons=reasons)

        if signal.symbol != "BTC":
            reasons.append("symbol must be BTC")
        if signal.direction not in {Direction.LONG, Direction.SHORT} and signal.action not in {
            Action.HOLD,
            Action.CLOSE,
            Action.CUT,
        }:
            reasons.append("direction must be LONG or SHORT")
        if signal.leverage is None or signal.leverage <= 0 or signal.leverage > self.risk.max_leverage:
            reasons.append(f"leverage must be <= {self.risk.max_leverage}x")
        if signal.action in {Action.OPEN, Action.ADD, Action.DCA}:
            margin = signal.margin_used_usdt or 0.0
            if margin <= 0:
                reasons.append("margin_used_usdt must be positive")
            if margin > current_equity * self.risk.max_margin_per_action_pct:
                reasons.append("margin exceeds max 10% per OPEN/ADD/DCA")
            if open_positions_count >= self.risk.max_open_positions and signal.action == Action.OPEN:
                reasons.append("max simultaneous open positions reached")
        if signal.action == Action.DCA and dca_count_for_position >= self.risk.max_dca_per_position:
            reasons.append("max DCA actions reached for position")
        if signal.action == Action.OPEN and recent_stop_loss_same_direction:
            reasons.append("must wait one full decision cycle after stop loss before reopening same direction")
        if daily_pnl <= -(current_equity * self.risk.daily_loss_limit_pct) and signal.action in {
            Action.OPEN,
            Action.ADD,
            Action.DCA,
        }:
            reasons.append("daily loss limit reached; no new risk allowed")

        if signal.action in {Action.OPEN, Action.ADD, Action.DCA}:
            self._validate_trade_math(signal, current_equity, current_total_risk, reasons)

        if signal.action in {Action.ADD, Action.DCA, Action.REDUCE, Action.CUT, Action.CLOSE, Action.HOLD}:
            if not signal.position_id and not signal.position_context:
                reasons.append("position_id or position_context is required for position updates")

        if not signal.thesis:
            reasons.append("thesis is required")
        if not signal.invalidation:
            reasons.append("invalidation is required")
        if not signal.counterargument:
            reasons.append("counterargument is required")
        if not signal.data_used:
            reasons.append("data_used is required")

        return ValidationResult(accepted=not reasons, reasons=reasons)

    def _validate_trade_math(
        self,
        signal: AgentSignal,
        current_equity: float,
        current_total_risk: float,
        reasons: list[str],
    ) -> None:
        assert signal.entry is not None
        assert signal.stop_loss is not None
        assert signal.take_profit_1 is not None
        assert signal.take_profit_2 is not None
        assert signal.leverage is not None
        margin = signal.margin_used_usdt or 0.0
        notional = signal.notional_exposure_usdt or margin * signal.leverage
        risk = risk_at_stop(signal.direction, notional, signal.entry, signal.stop_loss)
        declared = signal.account_risk_usdt or 0.0
        if declared and abs(declared - risk) / max(risk, 1.0) > 0.25:
            reasons.append("declared account risk differs from calculated risk by more than 25%")
        total_risk = signal.total_account_risk_after_action_usdt or (current_total_risk + risk)
        if total_risk > current_equity * self.risk.max_total_account_risk_pct:
            reasons.append("total account risk exceeds 2% equity")

        reward1 = self._reward(signal.direction, notional, signal.entry, signal.take_profit_1)
        reward2 = self._reward(signal.direction, notional, signal.entry, signal.take_profit_2)
        if risk <= 0:
            reasons.append("risk at stop must be positive")
            return
        if reward1 / risk < self.risk.min_rr_tp1:
            reasons.append("risk/reward to TP1 below 1:1.5")
        if reward2 / risk < self.risk.min_rr_tp2:
            reasons.append("risk/reward to TP2 below 1:2.0")

    @staticmethod
    def _reward(direction: Direction, notional: float, entry: float, target: float) -> float:
        if direction == Direction.LONG:
            return max(notional * ((target - entry) / entry), 0.0)
        return max(notional * ((entry - target) / entry), 0.0)
