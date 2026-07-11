from __future__ import annotations

import pandas as pd

from src.strategies.base import Strategy, hits_from_mask, strategy_features


class TrendPullbackReversalStrategy(Strategy):
    key = "trend_pullback_reversal"
    name = "趋势回踩转强"
    family = "pullback"
    description = "中期多头趋势中回踩均线，当日重新转强"
    score = 35

    def evaluate(self, daily, report_date, factors, features=None) -> pd.DataFrame:
        latest = strategy_features(daily, report_date, factors, features)
        mask = (
            latest["ma20"].gt(latest["ma60"] * 1.01)
            & latest["close"].ge(latest["ma20"])
            & latest["low"].le(latest["ma10"] * 1.025)
            & latest["pct_chg"].between(1.0, 7.0)
            & latest["amount_ratio"].fillna(1).between(0.7, 1.6)
            & latest["return_5d"].fillna(0).between(-6, 8)
        )
        return hits_from_mask(
            latest, mask, self.name, self.score, "多头趋势回踩均线后重新转强", key=self.key, family=self.family
        )
