from __future__ import annotations

import pandas as pd

from src.market.indicators import compute_indicators
from src.market.regime import detect_regime


def get_market_regime(ohlcv: pd.DataFrame) -> str:
    indicators = compute_indicators(ohlcv)
    return detect_regime(ohlcv, indicators)
