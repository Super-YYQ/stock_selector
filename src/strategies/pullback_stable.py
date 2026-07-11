from __future__ import annotations

import pandas as pd

from src.strategies.base import Strategy, hits_from_mask, strategy_features


class PullbackStableStrategy(Strategy):
    key = "pullback_stable"
    name = "缩量回踩企稳"
    family = "pullback"
    description = "趋势未破坏，缩量回踩关键均线后收稳"
    score = 30

    def evaluate(self, daily, report_date, factors, features=None) -> pd.DataFrame:
        latest = strategy_features(daily, report_date, factors, features)
        mask = (
            latest["close"].ge(latest["ma20"])
            & latest["low"].le(latest["ma10"] * 1.03)
            & latest["amount_ratio"].fillna(1).le(0.9)
            & latest["close"].ge(latest["low"] * 1.02)
        )
        return hits_from_mask(
            latest, mask, self.name, self.score, "缩量回踩关键均线后收稳", key=self.key, family=self.family
        )
