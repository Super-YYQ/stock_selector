from __future__ import annotations

import pandas as pd

from src.strategies.base import Strategy, hits_from_mask, strategy_features


class MaVolumeStrategy(Strategy):
    key = "ma_volume"
    name = "均线放量突破"
    family = "breakout"
    description = "站上短中期均线并以明显放量接近20日高点"
    score = 35

    def evaluate(self, daily, report_date, factors, features=None) -> pd.DataFrame:
        latest = strategy_features(daily, report_date, factors, features)
        mask = (
            latest["close"].ge(latest["ma5"])
            & latest["close"].ge(latest["ma10"])
            & latest["close"].ge(latest["ma20"])
            & latest["amount_ratio"].fillna(0).ge(1.5)
            & latest["close"].ge(latest["high_20"] * 0.98)
        )
        return hits_from_mask(
            latest, mask, self.name, self.score, "站上多条均线且成交额明显放大", key=self.key, family=self.family
        )
