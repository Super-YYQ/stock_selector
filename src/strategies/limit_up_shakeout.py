from __future__ import annotations

import pandas as pd

from src.strategies.base import Strategy, hits_from_mask, latest_with_indicators


class LimitUpShakeoutStrategy(Strategy):
    key = "limit_up_shakeout"
    name = "涨停洗盘回踩"
    score = 30

    def evaluate(self, daily: pd.DataFrame, report_date: str, factors: pd.DataFrame) -> pd.DataFrame:
        history = daily[daily["trade_date"] <= report_date].sort_values(["code", "trade_date"]).copy()
        latest = latest_with_indicators(history, report_date)
        recent = history.groupby("code").tail(20)
        limit_counts = recent[recent["pct_chg"].ge(9.5)].groupby("code")["pct_chg"].count().reset_index(name="limit_up_20d")
        latest = latest.merge(limit_counts, on="code", how="left")
        latest["limit_up_20d"] = latest["limit_up_20d"].fillna(0)
        mask = latest["limit_up_20d"].gt(0) & latest["close"].ge(latest["ma20"] * 0.98) & latest["amount_ratio"].fillna(1).le(1.2)
        return hits_from_mask(latest, mask, self.name, self.score, "近20日有涨停，回踩后未破20日线")
