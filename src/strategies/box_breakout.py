from __future__ import annotations

import pandas as pd

from src.strategies.base import Strategy, hits_from_mask, strategy_features


class BoxBreakoutStrategy(Strategy):
    key = "box_breakout"
    name = "箱体突破"
    family = "pattern"
    description = "20日箱体振幅收敛，收盘逼近箱体上沿准备突破"
    score = 30

    def evaluate(self, daily, report_date, factors, features=None) -> pd.DataFrame:
        latest = strategy_features(daily, report_date, factors, features)
        mask = (
            latest["range_20d"].between(0.05, 0.25)
            & latest["close"].ge(latest["prior_high_20"] * 0.98)
            & latest["close"].ge(latest["ma20"])
            & latest["amount_ratio"].fillna(0).ge(0.9)
        )
        return hits_from_mask(
            latest, mask, self.name, self.score, "箱体收敛后收盘逼近上沿，临近突破", key=self.key, family=self.family
        )
