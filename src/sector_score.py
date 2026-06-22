from __future__ import annotations

import pandas as pd


def calculate_sector_scores(
    sector_daily: pd.DataFrame,
    stock_basic: pd.DataFrame,
    stock_daily: pd.DataFrame,
    report_date: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if sector_daily.empty:
        empty_stock = stock_basic[["code", "industry"]].copy()
        empty_stock["sector_score_raw"] = 0.0
        empty_stock["sector_reason"] = "行业数据缺失"
        return empty_stock, pd.DataFrame(columns=["sector_name", "sector_score_raw"])

    history = sector_daily[sector_daily["trade_date"] <= report_date].sort_values(["sector_name", "trade_date"]).copy()
    history["pct_chg_5d"] = history.groupby("sector_name")["pct_chg"].transform(
        lambda value: value.rolling(5, min_periods=1).sum()
    )
    history["pct_chg_20d"] = history.groupby("sector_name")["pct_chg"].transform(
        lambda value: value.rolling(20, min_periods=1).sum()
    )
    history["amount_ma5"] = history.groupby("sector_name")["amount"].transform(
        lambda value: value.rolling(5, min_periods=1).mean()
    )
    latest = history[history["trade_date"] == report_date].copy()
    latest["amount_ratio"] = latest["amount"] / latest["amount_ma5"].replace(0, pd.NA)

    latest_stocks = stock_daily[stock_daily["trade_date"] == report_date].merge(
        stock_basic[["code", "industry"]], on="code", how="left"
    )
    strong_counts = (
        latest_stocks[latest_stocks["pct_chg"] >= 5].groupby("industry")["code"].count().reset_index(name="strong_stock_count")
    )
    limit_counts = (
        latest_stocks[latest_stocks["pct_chg"] >= 9.5].groupby("industry")["code"].count().reset_index(name="limit_up_count")
    )
    latest = latest.merge(strong_counts, left_on="sector_name", right_on="industry", how="left").drop(
        columns=["industry"], errors="ignore"
    )
    latest = latest.merge(limit_counts, left_on="sector_name", right_on="industry", how="left").drop(
        columns=["industry"], errors="ignore"
    )
    latest[["strong_stock_count", "limit_up_count"]] = latest[["strong_stock_count", "limit_up_count"]].fillna(0)

    latest["sector_score_raw"] = (
        latest["pct_chg"].clip(lower=-5, upper=8) * 6
        + latest["pct_chg_5d"].clip(lower=-10, upper=20) * 1.2
        + latest["pct_chg_20d"].clip(lower=-20, upper=40) * 0.4
        + latest["amount_ratio"].fillna(1).clip(lower=0, upper=3) * 10
        + latest["limit_up_count"].clip(upper=10) * 2
        + latest["strong_stock_count"].clip(upper=20)
    ).clip(lower=0, upper=100)
    latest["sector_reason"] = latest.apply(
        lambda row: (
            f"板块涨幅 {row['pct_chg']:.2f}%，"
            f"成交额放大 {row['amount_ratio']:.2f} 倍，"
            f"强势股 {int(row['strong_stock_count'])} 家"
        ),
        axis=1,
    )

    stock_scores = stock_basic[["code", "industry"]].merge(
        latest[["sector_name", "sector_score_raw", "sector_reason"]],
        left_on="industry",
        right_on="sector_name",
        how="left",
    )
    stock_scores["sector_score_raw"] = stock_scores["sector_score_raw"].fillna(0)
    stock_scores["sector_reason"] = stock_scores["sector_reason"].fillna("行业信息缺失")
    strong = latest.sort_values("sector_score_raw", ascending=False).reset_index(drop=True)
    return stock_scores.drop(columns=["sector_name"], errors="ignore"), strong
