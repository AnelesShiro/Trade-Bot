from __future__ import annotations

from datetime import UTC, datetime

from src.schemas import Action, AgentSignal, Direction, PositionStatus
from src.storage.models import PositionRecord, TradeRecord
from src.storage.repository import ArenaRepository, new_position_id, new_trade_id
from src.trading.pnl import calculate_pnl


class PositionManager:
    def __init__(
        self,
        repository: ArenaRepository,
        taker_fee_rate: float = 0.0,
        slippage_bps: float = 0.0,
        active_agent_ids: set[str] | None = None,
    ) -> None:
        self.repository = repository
        self.taker_fee_rate = taker_fee_rate
        self.slippage_bps = slippage_bps
        self.active_agent_ids = active_agent_ids
        self.config_version_id: int | None = None
        self.config_hash = ""
        self.code_version = ""

    def set_version_context(self, config_version_id: int | None, config_hash: str, code_version: str) -> None:
        self.config_version_id = config_version_id
        self.config_hash = config_hash
        self.code_version = code_version

    def apply_signal(self, signal: AgentSignal, current_price: float, execution_timestamp: datetime | None = None) -> str | None:
        execution_timestamp = _as_utc_naive(execution_timestamp or datetime.now(UTC))
        if signal.action in {Action.NONE, Action.HOLD}:
            return None
        if signal.action == Action.OPEN:
            return self._open(signal, execution_timestamp)
        if signal.action in {Action.ADD, Action.DCA}:
            return self._add(signal, execution_timestamp)
        if signal.action in {Action.REDUCE, Action.CUT, Action.CLOSE}:
            return self._close_or_reduce(signal, current_price, execution_timestamp)
        return None

    def update_stops_and_targets(self, current_price: float) -> list[TradeRecord]:
        exit_trades: list[TradeRecord] = []
        for position in self.repository.open_positions():
            if self.active_agent_ids is not None and position.agent_id not in self.active_agent_ids:
                continue
            hit_tp1 = (
                not self.repository.has_trade_note(position.id, "take_profit_1")
                and (
                    position.direction == Direction.LONG.value
                    and current_price >= position.take_profit_1
                    or position.direction == Direction.SHORT.value
                    and current_price <= position.take_profit_1
                )
            )
            hit_stop = (
                position.direction == Direction.LONG.value
                and current_price <= position.stop_loss
                or position.direction == Direction.SHORT.value
                and current_price >= position.stop_loss
            )
            hit_tp2 = (
                position.direction == Direction.LONG.value
                and current_price >= position.take_profit_2
                or position.direction == Direction.SHORT.value
                and current_price <= position.take_profit_2
            )
            if hit_tp1 and not hit_tp2 and not hit_stop:
                execution_timestamp = _as_utc_naive(datetime.now(UTC))
                closed_notional = position.notional * 0.5
                closed_margin = position.margin * 0.5
                exit_price = self._apply_slippage(current_price, position.direction, is_exit=True)
                fee = self._fee(closed_notional)
                pnl = calculate_pnl(position.direction, closed_notional, position.average_entry, exit_price) - fee
                position.realized_pnl += pnl
                position.notional -= closed_notional
                position.margin -= closed_margin
                position.status = PositionStatus.PARTIAL.value
                self.repository.add_or_update_position(position)
                trade = TradeRecord(
                    id=new_trade_id(position.agent_id),
                    agent_id=position.agent_id,
                    position_id=position.id,
                    created_at=execution_timestamp,
                    decision_timestamp=_as_utc_naive(position.opened_at),
                    execution_timestamp=execution_timestamp,
                    action="AUTO_REDUCE",
                    direction=position.direction,
                    leverage=position.leverage,
                    margin=closed_margin,
                    notional=closed_notional,
                    entry=position.average_entry,
                    exit_price=exit_price,
                    realized_pnl=pnl,
                    notes=_join_notes("take_profit_1", f"fee={fee:.4f}", f"slippage_bps={self.slippage_bps:g}"),
                    config_version_id=self.config_version_id,
                    config_hash=self.config_hash,
                    code_version=self.code_version,
                )
                self.repository.add_trade(trade)
                exit_trades.append(trade)
            if hit_stop or hit_tp2:
                execution_timestamp = _as_utc_naive(datetime.now(UTC))
                exit_price = self._apply_slippage(current_price, position.direction, is_exit=True)
                fee = self._fee(position.notional)
                pnl = calculate_pnl(position.direction, position.notional, position.average_entry, exit_price) - fee
                position.status = PositionStatus.CLOSED.value
                position.closed_at = execution_timestamp
                position.realized_pnl += pnl
                self.repository.add_or_update_position(position)
                trade = TradeRecord(
                    id=new_trade_id(position.agent_id),
                    agent_id=position.agent_id,
                    position_id=position.id,
                    created_at=execution_timestamp,
                    decision_timestamp=_as_utc_naive(position.opened_at),
                    execution_timestamp=execution_timestamp,
                    action="AUTO_CLOSE",
                    direction=position.direction,
                    leverage=position.leverage,
                    margin=position.margin,
                    notional=position.notional,
                    entry=position.average_entry,
                    exit_price=exit_price,
                    realized_pnl=pnl,
                    notes=_join_notes(_exit_reason(position, hit_stop), f"fee={fee:.4f}", f"slippage_bps={self.slippage_bps:g}"),
                    config_version_id=self.config_version_id,
                    config_hash=self.config_hash,
                    code_version=self.code_version,
                )
                self.repository.add_trade(trade)
                exit_trades.append(trade)
        return exit_trades

    def _open(self, signal: AgentSignal, execution_timestamp: datetime) -> str:
        position_id = signal.position_id or new_position_id(signal.agent)
        decision_timestamp = _as_utc_naive(signal.timestamp)
        margin = float(signal.margin_used_usdt or 0)
        leverage = float(signal.leverage or 1)
        notional = float(signal.notional_exposure_usdt or margin * leverage)
        entry = self._apply_slippage(float(signal.entry or 0), signal.direction.value, is_exit=False)
        fee = self._fee(notional)
        position = PositionRecord(
            id=position_id,
            agent_id=signal.agent,
            symbol="BTC",
            direction=signal.direction.value,
            status=PositionStatus.OPEN.value,
            leverage=leverage,
            margin=margin,
            notional=notional,
            average_entry=entry,
            stop_loss=float(signal.stop_loss or 0),
            take_profit_1=float(signal.take_profit_1 or 0),
            take_profit_2=float(signal.take_profit_2 or 0),
            dca_count=0,
            opened_at=execution_timestamp,
        )
        self.repository.add_or_update_position(position)
        self.repository.add_trade(
            TradeRecord(
                id=new_trade_id(signal.agent),
                agent_id=signal.agent,
                position_id=position_id,
                created_at=execution_timestamp,
                decision_timestamp=decision_timestamp,
                execution_timestamp=execution_timestamp,
                action=signal.action.value,
                direction=signal.direction.value,
                leverage=leverage,
                margin=margin,
                notional=notional,
                entry=entry,
                realized_pnl=-fee,
                notes=_join_notes(signal.notes_for_ledger, f"fee={fee:.4f}", f"slippage_bps={self.slippage_bps:g}"),
                config_version_id=self.config_version_id,
                config_hash=self.config_hash,
                code_version=self.code_version,
            )
        )
        return position_id

    def _add(self, signal: AgentSignal, execution_timestamp: datetime) -> str | None:
        if not signal.position_id:
            return None
        decision_timestamp = _as_utc_naive(signal.timestamp)
        position = self.repository.get_position(signal.position_id)
        if not position:
            return None
        margin = float(signal.margin_used_usdt or 0)
        leverage = float(signal.leverage or position.leverage)
        entry = self._apply_slippage(float(signal.entry or position.average_entry), position.direction, is_exit=False)
        added_notional = float(signal.notional_exposure_usdt or margin * leverage)
        fee = self._fee(added_notional)
        total_notional = position.notional + added_notional
        if total_notional <= 0:
            return position.id
        position.average_entry = ((position.average_entry * position.notional) + (entry * added_notional)) / total_notional
        position.margin += margin
        position.notional = total_notional
        position.leverage = position.notional / position.margin if position.margin else leverage
        signal_sl = float(signal.stop_loss or 0)
        if signal_sl > 0:
            if position.direction == Direction.LONG.value:
                position.stop_loss = max(signal_sl, position.stop_loss)
            else:
                position.stop_loss = min(signal_sl, position.stop_loss)
        position.take_profit_1 = float(signal.take_profit_1 or position.take_profit_1)
        position.take_profit_2 = float(signal.take_profit_2 or position.take_profit_2)
        if signal.action == Action.DCA:
            position.dca_count += 1
        self.repository.add_or_update_position(position)
        self.repository.add_trade(
            TradeRecord(
                id=new_trade_id(signal.agent),
                agent_id=signal.agent,
                position_id=position.id,
                created_at=execution_timestamp,
                decision_timestamp=decision_timestamp,
                execution_timestamp=execution_timestamp,
                action=signal.action.value,
                direction=position.direction,
                leverage=leverage,
                margin=margin,
                notional=added_notional,
                entry=entry,
                realized_pnl=-fee,
                notes=_join_notes(signal.notes_for_ledger, f"fee={fee:.4f}", f"slippage_bps={self.slippage_bps:g}"),
                config_version_id=self.config_version_id,
                config_hash=self.config_hash,
                code_version=self.code_version,
            )
        )
        return position.id

    def _close_or_reduce(self, signal: AgentSignal, current_price: float, execution_timestamp: datetime) -> str | None:
        if not signal.position_id:
            return None
        decision_timestamp = _as_utc_naive(signal.timestamp)
        position = self.repository.get_position(signal.position_id)
        if not position:
            return None
        exit_price = self._apply_slippage(float(signal.entry or current_price), position.direction, is_exit=True)
        close_fraction = 1.0 if signal.action in {Action.CUT, Action.CLOSE} else 0.5
        closed_notional = position.notional * close_fraction
        fee = self._fee(closed_notional)
        pnl = calculate_pnl(position.direction, closed_notional, position.average_entry, exit_price) - fee
        position.realized_pnl += pnl
        if close_fraction >= 1.0:
            position.status = PositionStatus.CLOSED.value
            position.closed_at = execution_timestamp
        else:
            position.notional -= closed_notional
            position.margin *= 1 - close_fraction
            position.status = PositionStatus.PARTIAL.value
        self.repository.add_or_update_position(position)
        self.repository.add_trade(
            TradeRecord(
                id=new_trade_id(signal.agent),
                agent_id=signal.agent,
                position_id=position.id,
                created_at=execution_timestamp,
                decision_timestamp=decision_timestamp,
                execution_timestamp=execution_timestamp,
                action=signal.action.value,
                direction=position.direction,
                leverage=position.leverage,
                margin=position.margin * close_fraction,
                notional=closed_notional,
                entry=position.average_entry,
                exit_price=exit_price,
                realized_pnl=pnl,
                notes=_join_notes(signal.notes_for_ledger, f"fee={fee:.4f}", f"slippage_bps={self.slippage_bps:g}"),
                config_version_id=self.config_version_id,
                config_hash=self.config_hash,
                code_version=self.code_version,
            )
        )
        return position.id

    def _fee(self, notional: float) -> float:
        return abs(notional) * self.taker_fee_rate

    def _apply_slippage(self, price: float, direction: str, is_exit: bool) -> float:
        if price <= 0 or self.slippage_bps <= 0:
            return price
        slip = self.slippage_bps / 10000
        if direction == Direction.LONG.value:
            return price * (1 - slip) if is_exit else price * (1 + slip)
        return price * (1 + slip) if is_exit else price * (1 - slip)


def _exit_reason(position: PositionRecord, hit_stop: bool) -> str:
    if not hit_stop:
        return "take_profit_2"
    return "break_even" if _is_protective_stop(position) else "stop_loss"


def _is_protective_stop(position: PositionRecord) -> bool:
    """A stop sitting at/beyond entry (moved by break-even or a profitable trail)
    is an at-worst-flat exit, not a real loss — label it distinctly."""
    if position.direction == Direction.LONG.value:
        return position.stop_loss >= position.average_entry
    return position.stop_loss <= position.average_entry


def _join_notes(*parts: str | None) -> str:
    return "; ".join([part for part in parts if part])


def _as_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
