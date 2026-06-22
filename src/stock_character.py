from __future__ import annotations

import pandas as pd

from src.indicators import add_returns, add_rps


def calculate_stock_character_scores(daily: pd.DataFrame, report_date: str) -> pd.DataFrame:
    history = daily[daily["trade_date"] <= report_date].sort_values(["code", "trade_date"]).copy()
    history = add_returns(history, periods=(20, 60))
    history = add_rps(history, "return_20d", "rps20")
    history = add_rps(history, "return_60d", "rps60")
    recent60 = history.groupby("code").tail(60).copy()

    recent60["amplitude"] = (recent60["high"] - recent60["low"]) / recent60["close"] * 100
    active = (
        recent60.groupby("code")
        .agg(
            big_up_count=("pct_chg", lambda value: int((value > 5).sum())),
            limit_up_count=("pct_chg", lambda value: int((value >= 9.5).sum())),
            avg_amplitude_20d=("amplitude", lambda value: float(value.tail(20).mean())),
            max_return_60d=(
                "close",
                lambda value: float((value.max() - value.iloc[0]) / value.iloc[0] * 100) if len(value) else 0,
            ),
            amount_mean=("amount", "mean"),
            amount_last=("amount", "last"),
        )
        .reset_index()
    )

    latest = history.groupby("code", as_index=False).tail(1)[["code", "rps20", "rps60", "return_20d", "return_60d"]]
    result = active.merge(latest, on="code", how="left")
    result[["rps20", "rps60", "return_20d", "return_60d"]] = result[
        ["rps20", "rps60", "return_20d", "return_60d"]
    ].fillna(0)
    result["stock_character_score_raw"] = (
        result["big_up_count"].clip(upper=12) * 4
        + result["limit_up_count"].clip(upper=5) * 5
        + result["avg_amplitude_20d"].clip(upper=12) * 2
        + result["max_return_60d"].clip(lower=0, upper=80) * 0.2
        + result["rps20"] * 0.15
        + result["rps60"] * 0.15
    ).clip(lower=0, upper=100)
    result["character_reason"] = result.apply(
        lambda row: "股性活跃，历史异动频率较高" if row["big_up_count"] >= 4 or row["rps20"] >= 80 else "股性一般，历史活跃度不突出",
        axis=1,
    )
    return result
