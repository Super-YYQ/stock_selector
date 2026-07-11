from __future__ import annotations

import pandas as pd

from src.strategies.base import Strategy, hits_from_mask, strategy_features


class SectorLeaderStrategy(Strategy):
    key = "sector_leader"
    name = "板块共振领涨"
    family = "sector"
    description = "板块热度与个股相对强度同时领先"
    score = 30

    def evaluate(self, daily, report_date, factors, features=None) -> pd.DataFrame:
        latest = strategy_features(daily, report_date, factors, features)
        mask = (
            latest["sector_score_raw"].ge(55)
            & latest["rps20"].ge(82)
            & latest["close"].ge(latest["ma20"])
            & latest["pct_chg"].ge(0)
            & latest["amount_ratio"].fillna(0).ge(1.0)
        )
        return hits_from_mask(
            latest, mask, self.name, self.score, "板块热度、RPS与量价同步走强", key=self.key, family=self.family
        )
