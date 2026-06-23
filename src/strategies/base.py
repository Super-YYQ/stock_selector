from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class StrategyHit:
    code: str
    strategy: str
    score: float
    reason: str


class Strategy:
    key: str = ""
    name: str = ""
    score: float = 0

    def evaluate(self, daily: pd.DataFrame, report_date: str, factors: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError


def latest_with_indicators(daily: pd.DataFrame, report_date: str) -> pd.DataFrame:
    history = daily[daily["trade_date"] <= report_date].sort_values(["code", "trade_date"]).copy()
    if history.empty:
        return pd.DataFrame(columns=["code"])
    grouped = history.groupby("code")
    history["ma5"] = grouped["close"].transform(lambda value: value.rolling(5, min_periods=1).mean())
    history["ma10"] = grouped["close"].transform(lambda value: value.rolling(10, min_periods=1).mean())
    history["ma20"] = grouped["close"].transform(lambda value: value.rolling(20, min_periods=1).mean())
    history["amount_ma20"] = grouped["amount"].transform(lambda value: value.rolling(20, min_periods=1).mean())
    history["high_20"] = grouped["high"].transform(lambda value: value.rolling(20, min_periods=1).max())
    history["high_60"] = grouped["high"].transform(lambda value: value.rolling(60, min_periods=1).max())
    history["low_10"] = grouped["low"].transform(lambda value: value.rolling(10, min_periods=1).min())
    latest = grouped.tail(1).copy()
    latest["amount_ratio"] = latest["amount"] / latest["amount_ma20"].replace(0, pd.NA)
    return latest.reset_index(drop=True)


def hits_from_mask(latest: pd.DataFrame, mask: pd.Series, strategy: str, score: float, reason: str) -> pd.DataFrame:
    selected = latest.loc[mask, ["code"]].copy()
    if selected.empty:
        return pd.DataFrame(columns=["code", "strategy", "strategy_score_raw", "strategy_reason"])
    selected["strategy"] = strategy
    selected["strategy_score_raw"] = score
    selected["strategy_reason"] = reason
    return selected.reset_index(drop=True)
