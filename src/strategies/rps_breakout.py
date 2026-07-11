from __future__ import annotations

import pandas as pd

from src.strategies.base import Strategy, hits_from_mask, strategy_features


class RpsBreakoutStrategy(Strategy):
    key = "rps_breakout"
    name = "RPS强势突破"
    family = "trend"
    description = "20日或60日相对强度领先，价格保持在阶段高位"
    score = 35

    def evaluate(self, daily, report_date, factors, features=None) -> pd.DataFrame:
        latest = strategy_features(daily, report_date, factors, features)
        mask = latest[["rps20", "rps60"]].max(axis=1).ge(85) & latest["close"].ge(latest["high_60"] * 0.9)
        return hits_from_mask(
            latest, mask, self.name, self.score, "RPS排名居前且价格靠近阶段高点", key=self.key, family=self.family
        )
