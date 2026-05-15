from __future__ import annotations

import pandas as pd


def backtest_pattern(ohlcv: pd.DataFrame, lookahead: int = 6) -> dict[str, float]:
    """Simple non-ML diagnostic: recent forward-return distribution."""
    close = ohlcv["close"]
    returns = close.pct_change(lookahead).shift(-lookahead).dropna()
    if returns.empty:
        return {"sample_size": 0, "mean_forward_return": 0.0, "win_rate": 0.0}
    return {
        "sample_size": float(len(returns)),
        "mean_forward_return": float(returns.mean()),
        "win_rate": float((returns > 0).mean()),
    }
