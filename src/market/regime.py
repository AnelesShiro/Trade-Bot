from __future__ import annotations

import pandas as pd

from src.market.indicators import ema
from src.schemas import IndicatorSnapshot


def detect_regime(frame: pd.DataFrame, indicators: IndicatorSnapshot) -> str:
    if len(frame) < 60:
        return "unknown"
    close = frame["close"]
    ema20 = indicators.ema_20 or float(ema(close, 20).iloc[-1])
    ema50 = indicators.ema_50 or float(ema(close, 50).iloc[-1])
    atr = indicators.atr_14 or 0.0
    price = float(close.iloc[-1])
    atr_pct = atr / price if price else 0.0

    if atr_pct > 0.025:
        volatility = "high_vol"
    elif atr_pct < 0.008:
        volatility = "low_vol"
    else:
        volatility = "normal_vol"

    if price > ema20 > ema50:
        trend = "uptrend"
    elif price < ema20 < ema50:
        trend = "downtrend"
    else:
        trend = "range"
    return f"{trend}_{volatility}"
