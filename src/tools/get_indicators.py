from __future__ import annotations

import pandas as pd

from src.market.indicators import compute_indicators
from src.schemas import IndicatorSnapshot


def get_indicators(ohlcv: pd.DataFrame) -> IndicatorSnapshot:
    return compute_indicators(ohlcv)
