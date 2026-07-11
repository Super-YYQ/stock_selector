from __future__ import annotations

import pandas as pd

from src.strategies.base import Strategy, hits_from_mask, strategy_features


class LowVolatilityRpsStrategy(Strategy):
    key = "low_volatility_rps"
    name = "低波RPS趋势"
    family = "trend"
    description = "相对强度领先，同时保持低波动和合理均线距离"
    score = 35

    def evaluate(self, daily, report_date, factors, features=None) -> pd.DataFrame:
        latest = strategy_features(daily, report_date, factors, features)
        mask = (
            latest["rps20"].ge(82)
            & latest["rps60"].ge(70)
            & latest["volatility_20d"].fillna(1).le(0.035)
            & latest["close"].ge(latest["ma20"])
            & latest["distance_ma20"].between(0, 12)
        )
        return hits_from_mask(
            latest, mask, self.name, self.score, "RPS领先且波动和均线距离受控", key=self.key, family=self.family
        )
