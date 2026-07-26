from __future__ import annotations

import pandas as pd

from src.indicators import add_returns, add_rps, is_limit_up


def calculate_stock_character_scores(
    daily: pd.DataFrame,
    report_date: str,
    stock_basic: pd.DataFrame | None = None,
) -> pd.DataFrame:
    history = daily[daily["trade_date"] <= report_date].sort_values(["code", "trade_date"]).copy()
    history = add_returns(history, periods=(20, 60))
    history = add_rps(history, "return_20d", "rps20")
    history = add_rps(history, "return_60d", "rps60")
    recent60 = history.groupby("code").tail(60).copy()
    st_codes: set[str] = set()
    if stock_basic is not None and not stock_basic.empty and {"code", "is_st"} <= set(stock_basic.columns):
        st_codes = set(
            stock_basic.loc[
                pd.to_numeric(stock_basic["is_st"], errors="coerce").fillna(0).eq(1),
                "code",
            ].astype(str)
        )
    recent60["is_limit_up"] = recent60.apply(
        lambda row: is_limit_up(
            str(row["code"]),
            float(row["pct_chg"]),
            str(row["code"]) in st_codes,
        ),
        axis=1,
    )

    recent60["amplitude"] = (recent60["high"] - recent60["low"]) / recent60["close"] * 100
    active = (
        recent60.groupby("code")
        .agg(
            big_up_count=("pct_chg", lambda value: int((value > 5).sum())),
            limit_up_count=("is_limit_up", "sum"),
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
    ).clip(lower=0, upper=100)
    result["character_reason"] = result.apply(
        lambda row: (
            "股性活跃，历史异动频率较高"
            if row["big_up_count"] >= 4 or row["limit_up_count"] >= 2
            else "股性一般，历史活跃度不突出"
        ),
        axis=1,
    )
    return result
