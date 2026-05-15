from src.schemas import Direction
from src.trading.pnl import calculate_pnl, notional, risk_at_stop


def test_long_pnl() -> None:
    assert notional(100, 10) == 1000
    assert calculate_pnl(Direction.LONG, 1000, 100000, 101000) == 10


def test_short_pnl() -> None:
    assert calculate_pnl(Direction.SHORT, 1000, 100000, 99000) == 10


def test_risk_at_stop_is_absolute() -> None:
    assert risk_at_stop(Direction.LONG, 1000, 100000, 99000) == 10
