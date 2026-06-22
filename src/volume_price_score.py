from __future__ import annotations

import pandas as pd

from src.indicators import moving_average


def calculate_volume_price_scores(daily: pd.DataFrame, report_date: str) -> pd.DataFrame:
    history = daily[daily["trade_date"] <= report_date].sort_values(["code", "trade_date"]).copy()
    history["ma5"] = history.groupby("code")["close"].transform(lambda value: moving_average(value, 5))
    history["ma10"] = history.groupby("code")["close"].transform(lambda value: moving_average(value, 10))
    history["ma20"] = history.groupby("code")["close"].transform(lambda value: moving_average(value, 20))
    history["amount_ma20"] = history.groupby("code")["amount"].transform(lambda value: moving_average(value, 20))
    history["high_20"] = history.groupby("code")["high"].transform(lambda value: value.rolling(20, min_periods=1).max())
    history["high_60"] = history.groupby("code")["high"].transform(lambda value: value.rolling(60, min_periods=1).max())
    latest = history.groupby("code", as_index=False).tail(1).copy()
    latest["amount_ratio"] = latest["amount"] / latest["amount_ma20"].replace(0, pd.NA)
    latest["break_20d_high"] = latest["close"] >= latest["high_20"] * 0.995
    latest["break_60d_high"] = latest["close"] >= latest["high_60"] * 0.995
    latest["above_ma5"] = latest["close"] >= latest["ma5"]
    latest["above_ma10"] = latest["close"] >= latest["ma10"]
    latest["above_ma20"] = latest["close"] >= latest["ma20"]
    latest["upper_shadow_ratio"] = (latest["high"] - latest[["open", "close"]].max(axis=1)) / (
        latest["high"] - latest["low"]
    ).replace(0, pd.NA)
    latest["volume_price_score_raw"] = (
        latest["amount_ratio"].fillna(1).clip(upper=3) * 12
        + latest["pct_chg"].fillna(0).clip(lower=-5, upper=8) * 2
        + latest["break_20d_high"].astype(int) * 15
        + latest["break_60d_high"].astype(int) * 15
        + latest["above_ma5"].astype(int) * 8
        + latest["above_ma10"].astype(int) * 6
        + latest["above_ma20"].astype(int) * 6
        - latest["upper_shadow_ratio"].fillna(0).gt(0.5).astype(int) * 10
    ).clip(lower=0, upper=100)
    latest["volume_price_reason"] = latest.apply(
        lambda row: "放量突破，站上关键均线" if row["break_20d_high"] and row["amount_ratio"] >= 1.5 else "量价结构普通",
        axis=1,
    )
    return latest[
        [
            "code",
            "amount_ratio",
            "break_20d_high",
            "break_60d_high",
            "above_ma5",
            "above_ma10",
            "above_ma20",
            "upper_shadow_ratio",
            "volume_price_score_raw",
            "volume_price_reason",
        ]
    ]
