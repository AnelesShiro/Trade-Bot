from __future__ import annotations


def calculate_position_size(
    equity: float,
    entry: float,
    stop_loss: float,
    leverage: float,
    max_risk_pct: float,
    max_margin_pct: float,
    direction: str,
) -> dict[str, float]:
    if entry <= 0 or leverage <= 0:
        raise ValueError("entry and leverage must be positive")
    price_risk_pct = abs(entry - stop_loss) / entry
    if price_risk_pct <= 0:
        raise ValueError("stop loss must differ from entry")
    max_loss = equity * max_risk_pct
    notional_by_risk = max_loss / price_risk_pct
    margin_by_risk = notional_by_risk / leverage
    max_margin = equity * max_margin_pct
    margin = min(margin_by_risk, max_margin)
    notional = margin * leverage
    risk_usdt = notional * price_risk_pct
    return {
        "direction": 1.0 if direction.upper() == "LONG" else -1.0,
        "margin_usdt": margin,
        "notional_usdt": notional,
        "risk_usdt": risk_usdt,
        "risk_pct": risk_usdt / equity,
    }
