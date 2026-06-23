from __future__ import annotations

import pandas as pd

from src.strategies.base import Strategy, hits_from_mask, latest_with_indicators


class MaVolumeStrategy(Strategy):
    key = "ma_volume"
    name = "均线放量突破"
    score = 35

    def evaluate(self, daily: pd.DataFrame, report_date: str, factors: pd.DataFrame) -> pd.DataFrame:
        latest = latest_with_indicators(daily, report_date)
        mask = (
            latest["close"].ge(latest["ma5"])
            & latest["close"].ge(latest["ma10"])
            & latest["close"].ge(latest["ma20"])
            & latest["amount_ratio"].fillna(0).ge(1.5)
            & latest["close"].ge(latest["high_20"] * 0.98)
        )
        return hits_from_mask(latest, mask, self.name, self.score, "站上多条均线且成交额明显放大")
