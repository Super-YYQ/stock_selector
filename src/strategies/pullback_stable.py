from __future__ import annotations

import pandas as pd

from src.strategies.base import Strategy, hits_from_mask, latest_with_indicators


class PullbackStableStrategy(Strategy):
    key = "pullback_stable"
    name = "缩量回踩企稳"
    score = 30

    def evaluate(self, daily: pd.DataFrame, report_date: str, factors: pd.DataFrame) -> pd.DataFrame:
        latest = latest_with_indicators(daily, report_date)
        mask = (
            latest["close"].ge(latest["ma20"])
            & latest["low"].le(latest["ma10"] * 1.03)
            & latest["amount_ratio"].fillna(1).le(0.9)
            & latest["close"].ge(latest["low"] * 1.02)
        )
        return hits_from_mask(latest, mask, self.name, self.score, "缩量回踩关键均线后收稳")
