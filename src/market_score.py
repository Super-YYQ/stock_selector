from __future__ import annotations

import pandas as pd

from src.indicators import moving_average


def _latest_index(index_daily: pd.DataFrame, index_code: str, report_date: str) -> pd.DataFrame:
    return index_daily[(index_daily["index_code"] == index_code) & (index_daily["trade_date"] <= report_date)].sort_values(
        "trade_date"
    )


def calculate_market_score(index_daily: pd.DataFrame, stock_daily: pd.DataFrame, report_date: str) -> dict[str, object]:
    latest_stocks = stock_daily[stock_daily["trade_date"] == report_date].copy()
    up_ratio = round((latest_stocks["pct_chg"].gt(0).mean() * 100) if not latest_stocks.empty else 0, 2)
    limit_up_count = int(latest_stocks["pct_chg"].ge(9.5).sum()) if "pct_chg" in latest_stocks else 0
    limit_down_count = int(latest_stocks["pct_chg"].le(-9.5).sum()) if "pct_chg" in latest_stocks else 0

    score = 0.0
    index_changes: dict[str, float] = {}
    above_ma5 = 0
    above_ma20 = 0
    for index_code in ["sh000001", "sz399001", "sz399006"]:
        history = _latest_index(index_daily, index_code, report_date)
        if history.empty:
            continue
        latest = history.iloc[-1]
        pct_chg = float(latest.get("pct_chg", 0) or 0)
        index_changes[index_code] = pct_chg
        score += 1.0 if pct_chg > 0 else 0.0
        ma5 = moving_average(history["close"], 5).iloc[-1]
        ma20 = moving_average(history["close"], 20).iloc[-1]
        above_ma5 += int(float(latest["close"]) >= ma5)
        above_ma20 += int(float(latest["close"]) >= ma20)

    score += min(up_ratio / 20, 3)
    score += min(limit_up_count / 30, 1)
    score -= min(limit_down_count / 20, 1)
    score += above_ma5 * 0.35
    score += above_ma20 * 0.35

    sh_change = index_changes.get("sh000001", 0)
    cyb_change = index_changes.get("sz399006", 0)
    if cyb_change > sh_change:
        score += 0.5

    market_score = round(max(0, min(10, score)), 2)
    if market_score >= 7:
        market_label = "偏强"
    elif market_score >= 4:
        market_label = "震荡"
    else:
        market_label = "偏弱"

    if market_score >= 7 and limit_down_count < 20:
        risk_level = "低"
    elif market_score >= 4:
        risk_level = "中"
    else:
        risk_level = "高"

    return {
        "market_label": market_label,
        "risk_level": risk_level,
        "market_score": market_score,
        "up_ratio": up_ratio,
        "limit_up_count": limit_up_count,
        "limit_down_count": limit_down_count,
        "index_changes": index_changes,
        "above_ma5_count": above_ma5,
        "above_ma20_count": above_ma20,
    }
