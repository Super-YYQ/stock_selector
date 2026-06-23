from __future__ import annotations

import pandas as pd

from src.strategies.base import Strategy, hits_from_mask, latest_with_indicators


class RpsBreakoutStrategy(Strategy):
    key = "rps_breakout"
    name = "RPS强势突破"
    score = 35

    def evaluate(self, daily: pd.DataFrame, report_date: str, factors: pd.DataFrame) -> pd.DataFrame:
        latest = latest_with_indicators(daily, report_date)
        merged = latest.merge(factors[[column for column in ["code", "rps20", "rps60"] if column in factors.columns]], on="code", how="left")
        if "rps20" not in merged.columns:
            merged["rps20"] = 0
        if "rps60" not in merged.columns:
            merged["rps60"] = 0
        mask = (merged[["rps20", "rps60"]].max(axis=1).fillna(0).ge(85)) & merged["close"].ge(merged["high_60"] * 0.9)
        return hits_from_mask(merged, mask, self.name, self.score, "RPS排名居前且价格靠近阶段高点")
