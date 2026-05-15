from __future__ import annotations

from src.schemas import Direction


def notional(margin: float, leverage: float) -> float:
    return margin * leverage


def calculate_pnl(direction: Direction | str, notional_value: float, entry: float, exit_price: float) -> float:
    side = direction.value if isinstance(direction, Direction) else direction
    if entry <= 0:
        raise ValueError("entry must be positive")
    if side == Direction.LONG.value:
        return notional_value * ((exit_price - entry) / entry)
    if side == Direction.SHORT.value:
        return notional_value * ((entry - exit_price) / entry)
    return 0.0


def risk_at_stop(direction: Direction | str, notional_value: float, entry: float, stop_loss: float) -> float:
    return abs(calculate_pnl(direction, notional_value, entry, stop_loss))


def reward_to_target(direction: Direction | str, notional_value: float, entry: float, target: float) -> float:
    return max(calculate_pnl(direction, notional_value, entry, target), 0.0)
