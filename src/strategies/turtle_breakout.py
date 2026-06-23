from __future__ import annotations

import pandas as pd

from src.strategies.base import Strategy, hits_from_mask, latest_with_indicators


class TurtleBreakoutStrategy(Strategy):
    key = "turtle_breakout"
    name = "海龟突破"
    score = 35

    def evaluate(self, daily: pd.DataFrame, report_date: str, factors: pd.DataFrame) -> pd.DataFrame:
        latest = latest_with_indicators(daily, report_date)
        mask = latest["close"].ge(latest["high_60"] * 0.98) & latest["amount_ratio"].fillna(0).ge(1.2)
        return hits_from_mask(latest, mask, self.name, self.score, "接近或突破60日高点且成交额放大")
