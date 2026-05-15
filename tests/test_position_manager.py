from __future__ import annotations

from src.schemas import Action, AgentSignal, Decision, Direction, ExecutionType
from src.trading.position_manager import PositionManager


def make_signal(**updates) -> AgentSignal:
    data = {
        "agent": "crypto-deepseek",
        "decision": Decision.PAPER_TRADE,
        "action": Action.OPEN,
        "direction": Direction.LONG,
        "execution_type": ExecutionType.LIMIT,
        "leverage": 5,
        "margin_used_usdt": 500,
        "notional_exposure_usdt": 2500,
        "entry": 100000,
        "stop_loss": 99000,
        "take_profit_1": 101500,
        "take_profit_2": 102000,
        "account_risk_usdt": 25,
        "thesis": "defined setup",
        "invalidation": "stop hit",
        "counterargument": "range rejection",
        "data_used": ["ohlcv"],
    }
    data.update(updates)
    return AgentSignal(**data)


def test_open_add_tp1_and_tp2_flow(repository) -> None:
    manager = PositionManager(repository)
    position_id = manager.apply_signal(make_signal(position_id="p1"), 100000)

    add = make_signal(action=Action.ADD, position_id=position_id, margin_used_usdt=100, notional_exposure_usdt=500)
    manager.apply_signal(add, 100500)
    position = repository.get_position("p1")
    assert position is not None
    assert position.margin == 600
    assert position.notional == 3000

    tp1_trades = manager.update_stops_and_targets(101600)
    position = repository.get_position("p1")
    assert len(tp1_trades) == 1
    assert position is not None
    assert position.status == "PARTIAL"
    assert position.notional == 1500
    assert repository.has_trade_note("p1", "take_profit_1")

    tp2_trades = manager.update_stops_and_targets(102100)
    position = repository.get_position("p1")
    assert len(tp2_trades) == 1
    assert position is not None
    assert position.status == "CLOSED"
    assert position.realized_pnl > 0


def test_close_signal_realizes_pnl(repository) -> None:
    manager = PositionManager(repository)
    position_id = manager.apply_signal(make_signal(position_id="p2"), 100000)
    close = make_signal(action=Action.CLOSE, position_id=position_id, entry=101000)
    manager.apply_signal(close, 101000)
    trade = repository.latest_trade_for_position("p2")
    position = repository.get_position("p2")
    assert trade is not None
    assert trade.realized_pnl > 0
    assert position is not None
    assert position.status == "CLOSED"
