from __future__ import annotations

import pandas as pd

from src.indicators import is_limit_up

def market_board(code: str) -> str:
    normalized = str(code).zfill(6)
    if normalized.startswith(("43", "83", "87", "88", "92")):
        return "北交所"
    if normalized.startswith(("688", "689")):
        return "科创板"
    if normalized.startswith(("300", "301")):
        return "创业板"
    if normalized.startswith("6"):
        return "沪市主板"
    if normalized.startswith("0"):
        return "深市主板"
    return "其他"


def fill_market_board_industry(stock_basic: pd.DataFrame) -> pd.DataFrame:
    prepared = stock_basic.copy()
    if "industry" not in prepared.columns:
        prepared["industry"] = ""
    missing = prepared["industry"].isna() | prepared["industry"].astype(str).str.strip().eq("")
    prepared.loc[missing, "industry"] = prepared.loc[missing, "code"].astype(str).map(market_board)
    return prepared


def build_market_board_daily(stock_basic: pd.DataFrame, stock_daily: pd.DataFrame) -> pd.DataFrame:
    if stock_basic.empty or stock_daily.empty:
        return pd.DataFrame(columns=["sector_name", "trade_date", "pct_chg", "amount"])
    basic = fill_market_board_industry(stock_basic)[["code", "industry"]].copy()
    history = stock_daily[["code", "trade_date", "pct_chg", "amount"]].merge(basic, on="code", how="left")
    history["pct_chg"] = pd.to_numeric(history["pct_chg"], errors="coerce")
    history["amount"] = pd.to_numeric(history["amount"], errors="coerce")
    history = history.dropna(subset=["trade_date", "industry", "pct_chg"])
    result = (
        history.groupby(["industry", "trade_date"], as_index=False)
        .agg(pct_chg=("pct_chg", "mean"), amount=("amount", "sum"))
        .rename(columns={"industry": "sector_name"})
    )
    return result[["sector_name", "trade_date", "pct_chg", "amount"]]


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
    st_codes: set[str] = set()
    if "is_st" in stock_basic.columns:
        st_codes = set(
            stock_basic.loc[
                pd.to_numeric(stock_basic["is_st"], errors="coerce").fillna(0).eq(1),
                "code",
            ].astype(str)
        )
    latest_stocks["is_limit_up"] = latest_stocks.apply(
        lambda row: is_limit_up(
            str(row["code"]),
            float(row["pct_chg"]),
            str(row["code"]) in st_codes,
        ),
        axis=1,
    )
    strong_counts = (
        latest_stocks[latest_stocks["pct_chg"] >= 5].groupby("industry")["code"].count().reset_index(name="strong_stock_count")
    )
    limit_counts = (
        latest_stocks[latest_stocks["is_limit_up"]].groupby("industry")["code"].count().reset_index(name="limit_up_count")
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
