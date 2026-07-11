from __future__ import annotations

import pandas as pd

from src.strategies.base import Strategy, hits_from_mask, strategy_features


class LimitUpShakeoutStrategy(Strategy):
    key = "limit_up_shakeout"
    name = "涨停洗盘回踩"
    family = "event"
    description = "近20日出现涨停，随后缩量回踩但未破趋势"
    score = 30

    def evaluate(self, daily, report_date, factors, features=None) -> pd.DataFrame:
        latest = strategy_features(daily, report_date, factors, features)
        mask = (
            latest["limit_up_20d"].gt(0)
            & latest["close"].ge(latest["ma20"] * 0.98)
            & latest["amount_ratio"].fillna(1).le(1.2)
        )
        return hits_from_mask(
            latest, mask, self.name, self.score, "近20日有涨停，回踩后未破20日线", key=self.key, family=self.family
        )
