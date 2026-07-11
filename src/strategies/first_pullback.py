from __future__ import annotations

import pandas as pd

from src.strategies.base import Strategy, hits_from_mask, strategy_features


class FirstPullbackStrategy(Strategy):
    key = "first_pullback"
    name = "突破后首次回踩"
    family = "pullback"
    description = "近10日完成平台突破，随后首次缩量回踩均线"
    score = 35

    def evaluate(self, daily, report_date, factors, features=None) -> pd.DataFrame:
        latest = strategy_features(daily, report_date, factors, features)
        mask = (
            latest["breakout_recent_10d"].fillna(0).gt(0)
            & latest["close"].ge(latest["ma20"])
            & latest["low"].le(latest["ma10"] * 1.03)
            & latest["amount_ratio"].fillna(1).le(1.0)
            & latest["close"].ge(latest["open"])
        )
        return hits_from_mask(
            latest, mask, self.name, self.score, "近期突破后首次缩量回踩且收稳", key=self.key, family=self.family
        )
