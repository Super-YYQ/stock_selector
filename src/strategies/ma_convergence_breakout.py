from __future__ import annotations

import pandas as pd

from src.strategies.base import Strategy, hits_from_mask, strategy_features


class MaConvergenceBreakoutStrategy(Strategy):
    key = "ma_convergence_breakout"
    name = "均线粘合突破"
    family = "breakout"
    description = "中长期均线先粘合后多头排列，放量突破12日高点"
    score = 40

    def evaluate(self, daily, report_date, factors, features=None) -> pd.DataFrame:
        latest = strategy_features(daily, report_date, factors, features)
        mask = (
            latest["ma13"].gt(latest["ma34"])
            & latest["ma34"].gt(latest["ma55"])
            & latest["ma_deviation_10"].le(3)
            & latest["ma_deviation_19"].le(3)
            & latest["close"].gt(latest["prior_high_12"])
            & latest["close"].ge(latest["open"])
            & latest["amount_ratio"].fillna(0).ge(1.0)
        )
        return hits_from_mask(
            latest,
            mask,
            self.name,
            self.score,
            "均线粘合后多头排列，突破12日高点且温和放量",
            key=self.key,
            family=self.family,
        )
