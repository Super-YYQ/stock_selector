from __future__ import annotations

import pandas as pd

from src.strategies.base import Strategy, hits_from_mask, strategy_features


class TurtleBreakoutStrategy(Strategy):
    key = "turtle_breakout"
    name = "海龟突破"
    family = "breakout"
    description = "接近或突破60日高点，并得到成交额确认"
    score = 35

    def evaluate(self, daily, report_date, factors, features=None) -> pd.DataFrame:
        latest = strategy_features(daily, report_date, factors, features)
        mask = latest["close"].ge(latest["high_60"] * 0.98) & latest["amount_ratio"].fillna(0).ge(1.2)
        return hits_from_mask(
            latest, mask, self.name, self.score, "接近或突破60日高点且成交额放大", key=self.key, family=self.family
        )
