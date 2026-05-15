from __future__ import annotations

import numpy as np
import pandas as pd

from src.schemas import IndicatorSnapshot


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(length).mean()
    loss = -delta.clip(upper=0).rolling(length).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(frame: pd.DataFrame, length: int = 14) -> pd.Series:
    high_low = frame["high"] - frame["low"]
    high_close = (frame["high"] - frame["close"].shift()).abs()
    low_close = (frame["low"] - frame["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(length).mean()


def compute_indicators(frame: pd.DataFrame) -> IndicatorSnapshot:
    close = frame["close"]
    ema_12 = ema(close, 12)
    ema_26 = ema(close, 26)
    macd = ema_12 - ema_26
    macd_signal = ema(macd, 9)
    mid = close.rolling(20).mean()
    std = close.rolling(20).std()
    latest = frame.index[-1]
    snapshot = IndicatorSnapshot(
        rsi_14=_safe(rsi(close, 14).loc[latest]),
        ema_20=_safe(ema(close, 20).loc[latest]),
        ema_50=_safe(ema(close, 50).loc[latest]),
        atr_14=_safe(atr(frame, 14).loc[latest]),
        macd=_safe(macd.loc[latest]),
        macd_signal=_safe(macd_signal.loc[latest]),
        bb_low=_safe((mid - 2 * std).loc[latest]),
        bb_mid=_safe(mid.loc[latest]),
        bb_high=_safe((mid + 2 * std).loc[latest]),
    )
    return snapshot


def _safe(value: float) -> float | None:
    if pd.isna(value):
        return None
    return float(value)
