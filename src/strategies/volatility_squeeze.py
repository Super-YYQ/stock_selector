from __future__ import annotations

import pandas as pd

from src.strategies.base import Strategy, hits_from_mask, strategy_features


class VolatilitySqueezeStrategy(Strategy):
    key = "volatility_squeeze"
    name = "平台缩量突破"
    family = "breakout"
    description = "阶段波动收敛后放量突破20日平台"
    score = 40

    def evaluate(self, daily, report_date, factors, features=None) -> pd.DataFrame:
        latest = strategy_features(daily, report_date, factors, features)
        mask = (
            latest["prior_high_20"].notna()
            & latest["close"].ge(latest["prior_high_20"] * 0.995)
            & latest["amount_ratio"].fillna(0).ge(1.4)
            & latest["volatility_20d"].fillna(1).le(0.035)
            & latest["pct_chg"].between(1.5, 9.5)
        )
        return hits_from_mask(
            latest, mask, self.name, self.score, "低波平台收敛后放量突破", key=self.key, family=self.family
        )
