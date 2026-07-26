from __future__ import annotations

from datetime import date

import pandas as pd

from src.config import StockPoolConfig
from src.indicators import is_price_jump_anomaly
from src.sector_score import market_board


def _list_days(list_date: str, report_date: str) -> int | None:
    value = str(list_date or "").strip()
    if not value or value.lower() in {"nan", "nat", "none"}:
        return None
    try:
        return (date.fromisoformat(report_date) - date.fromisoformat(value)).days
    except ValueError:
        return None


def _latest_rows(daily: pd.DataFrame, report_date: str) -> pd.DataFrame:
    latest = daily[daily["trade_date"] <= report_date].sort_values(["code", "trade_date"])
    return latest.groupby("code", as_index=False).tail(1)


def _avg_amount(daily: pd.DataFrame, report_date: str, window: int = 20) -> pd.DataFrame:
    history = daily[daily["trade_date"] <= report_date].sort_values(["code", "trade_date"])
    values = history.groupby("code").tail(window).groupby("code")["amount"].mean().reset_index()
    return values.rename(columns={"amount": "avg_amount_20d"})


def _first_trade_dates(daily: pd.DataFrame, report_date: str) -> pd.DataFrame:
    history = daily[daily["trade_date"] <= report_date].sort_values(["code", "trade_date"])
    values = history.groupby("code", as_index=False)["trade_date"].first()
    return values.rename(columns={"trade_date": "first_trade_date"})


def build_stock_pool(
    basic: pd.DataFrame,
    daily: pd.DataFrame,
    report_date: str,
    config: StockPoolConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    latest = _latest_rows(daily, report_date)
    avg_amount = _avg_amount(daily, report_date)
    first_trade_dates = _first_trade_dates(daily, report_date)
    pool = basic.merge(latest, on="code", how="left").merge(avg_amount, on="code", how="left")
    pool = pool.merge(first_trade_dates, on="code", how="left")
    pool["market_board"] = pool["code"].astype(str).map(market_board)
    pool["filter_reason"] = ""

    def add_reason(mask: pd.Series, reason: str) -> None:
        pool.loc[mask, "filter_reason"] = pool.loc[mask, "filter_reason"].apply(
            lambda existing: reason if not existing else f"{existing}; {reason}"
        )

    excluded_boards = set(config.exclude_boards)
    if excluded_boards:
        add_reason(
            pool["market_board"].isin(excluded_boards),
            "已排除市场板块：" + "、".join(config.exclude_boards),
        )

    if config.exclude_st:
        add_reason(
            pool["is_st"].fillna(0).astype(int).eq(1) | pool["name"].astype(str).str.contains("ST"),
            "ST 或退市风险",
        )
    if config.exclude_suspended:
        add_reason(pool["is_suspended"].fillna(0).astype(int).eq(1) | pool["close"].isna(), "停牌或无当日行情")
    add_reason(
        pool["trade_date"].fillna("").astype(str).ne(report_date),
        "缺少报告日行情",
    )
    def effective_list_days(row: pd.Series) -> int | None:
        list_days = _list_days(row.get("list_date", ""), report_date)
        return list_days if list_days is not None else _list_days(row.get("first_trade_date", ""), report_date)

    list_days = pool.apply(effective_list_days, axis=1)
    add_reason(
        list_days.fillna(0) < config.min_list_days,
        f"上市不足 {config.min_list_days} 个自然日",
    )
    add_reason(pool["close"].fillna(0) < config.min_price, f"价格低于 {config.min_price} 元")
    add_reason(
        pool["avg_amount_20d"].fillna(0) < config.min_avg_amount_20d,
        f"最近20日平均成交额低于 {int(config.min_avg_amount_20d)}",
    )

    recent = daily[daily["trade_date"] <= report_date].sort_values(["code", "trade_date"]).groupby("code").tail(5)
    recent_stats = (
        recent.groupby("code")
        .agg(pct_sum=("pct_chg", "sum"), amount_last=("amount", "last"), amount_mean=("amount", "mean"))
        .reset_index()
    )
    pool = pool.merge(recent_stats, on="code", how="left")
    add_reason(
        pool["pct_sum"].fillna(0).gt(35) & pool["amount_last"].fillna(0).lt(pool["amount_mean"].fillna(0) * 0.7),
        "连续大涨后高位缩量",
    )

    is_st = (
        pd.to_numeric(basic["is_st"], errors="coerce").fillna(0)
        if "is_st" in basic.columns
        else pd.Series(0, index=basic.index)
    )
    st_codes = set(basic.loc[is_st.eq(1), "code"].astype(str))
    recent_quality = (
        daily[daily["trade_date"] <= report_date]
        .sort_values(["code", "trade_date"])
        .groupby("code")
        .tail(60)[["code", "pct_chg"]]
        .copy()
    )
    def price_jump_anomaly(row: pd.Series) -> bool:
        value = pd.to_numeric(row["pct_chg"], errors="coerce")
        pct_chg = 0.0 if pd.isna(value) else float(value)
        code = str(row["code"])
        return is_price_jump_anomaly(code, pct_chg, code in st_codes)

    recent_quality["price_jump_anomaly"] = recent_quality.apply(price_jump_anomaly, axis=1)
    anomaly_by_code = (
        recent_quality.groupby("code", as_index=False)["price_jump_anomaly"]
        .max()
    )
    pool = pool.merge(anomaly_by_code, on="code", how="left")
    add_reason(
        pool["price_jump_anomaly"].fillna(False),
        "最近60日存在疑似除权或异常价格跳变",
    )

    filtered = pool[pool["filter_reason"] != ""].copy()
    eligible = pool[pool["filter_reason"] == ""].copy()
    return eligible.reset_index(drop=True), filtered.reset_index(drop=True)
