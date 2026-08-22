from __future__ import annotations

import numpy as np
import pandas as pd

from src.indicators import is_limit_down, is_limit_up, moving_average


def _latest_index(index_daily: pd.DataFrame, index_code: str, report_date: str) -> pd.DataFrame:
    return index_daily[(index_daily["index_code"] == index_code) & (index_daily["trade_date"] <= report_date)].sort_values(
        "trade_date"
    )


RSRS_WINDOW = 18
RSRS_ZSCORE_WINDOW = 200
RSRS_MIN_BETAS = 30
RSRS_STRONG = 0.85
RSRS_VERY_STRONG = 1.2


def _rsrs_indicator(index_history: pd.DataFrame) -> float | None:
    """成交量加权 RSRS（阻力支撑相对强度），右偏标准化后返回。

    口径参考聚宽社区改进版：18 日 high~low 加权回归斜率 beta，
    对近 200 个 beta 标准化为 zscore，指标 = zscore × beta × R²。
    历史不足时返回 None（中性，不加不减）。
    """
    if index_history.empty or not {"high", "low"} <= set(index_history.columns):
        return None
    high = index_history["high"].to_numpy(dtype=float)
    low = index_history["low"].to_numpy(dtype=float)
    if "volume" in index_history.columns:
        volume = pd.to_numeric(index_history["volume"], errors="coerce").to_numpy(dtype=float)
    else:
        volume = None

    betas: list[float] = []
    r_squared: list[float] = []
    uniform = np.full(RSRS_WINDOW, 1.0 / RSRS_WINDOW)
    for end in range(RSRS_WINDOW, len(high) + 1):
        y = high[end - RSRS_WINDOW : end]
        x = low[end - RSRS_WINDOW : end]
        w = None
        if volume is not None:
            chunk = volume[end - RSRS_WINDOW : end]
            if not pd.isna(chunk).any() and chunk.sum() > 0:
                w = chunk / chunk.sum()
        if w is None:
            w = uniform
        mean_x = float((w * x).sum())
        mean_y = float((w * y).sum())
        cov = float((w * (x - mean_x) * (y - mean_y)).sum())
        var = float((w * (x - mean_x) ** 2).sum())
        if var <= 0:
            continue
        beta = cov / var
        fitted = mean_y + beta * (x - mean_x)
        ss_res = float((w * (y - fitted) ** 2).sum())
        ss_tot = float((w * (y - mean_y) ** 2).sum())
        if ss_tot <= 0:
            continue
        betas.append(float(beta))
        r_squared.append(max(0.0, 1.0 - ss_res / ss_tot))
    if len(betas) < RSRS_MIN_BETAS:
        return None

    beta_series = pd.Series(betas[-RSRS_ZSCORE_WINDOW:])
    std = float(beta_series.std())
    if std <= 0:
        return None
    zscore = (float(beta_series.iloc[-1]) - float(beta_series.mean())) / std
    return float(zscore * betas[-1] * r_squared[-1])


def _rsrs_adjustment(rsrs: float | None) -> float:
    if rsrs is None:
        return 0.0
    if rsrs > RSRS_VERY_STRONG:
        return 1.0
    if rsrs > RSRS_STRONG:
        return 0.8
    if rsrs < -RSRS_VERY_STRONG:
        return -1.0
    if rsrs < -RSRS_STRONG:
        return -0.8
    return 0.0


def _new_high_ratio(stock_daily: pd.DataFrame, report_date: str) -> float | None:
    """当日创 20 日新高的个股占比；样本不足时返回 None（中性）。"""
    if stock_daily.empty or not {"code", "trade_date", "high", "close"} <= set(stock_daily.columns):
        return None
    history = stock_daily[stock_daily["trade_date"] <= report_date].sort_values(["code", "trade_date"])
    if history.empty:
        return None
    grouped = history.groupby("code", sort=False)
    prior_high = grouped["high"].transform(lambda value: value.shift(1).rolling(19, min_periods=5).max())
    latest = history["trade_date"].eq(report_date) & prior_high.notna()
    if not latest.any():
        return None
    breakout_ratio = history.loc[latest, "close"].ge(prior_high[latest]).mean()
    return round(float(breakout_ratio) * 100, 2)


def _new_high_adjustment(ratio: float | None) -> float:
    if ratio is None:
        return 0.0
    if ratio >= 15:
        return 0.6
    if ratio >= 8:
        return 0.3
    if ratio <= 2:
        return -0.4
    if ratio <= 5:
        return -0.2
    return 0.0


def calculate_market_score(
    index_daily: pd.DataFrame,
    stock_daily: pd.DataFrame,
    report_date: str,
    stock_basic: pd.DataFrame | None = None,
) -> dict[str, object]:
    latest_stocks = stock_daily[stock_daily["trade_date"] == report_date].copy()
    st_codes: set[str] = set()
    if stock_basic is not None and not stock_basic.empty and {"code", "is_st"} <= set(stock_basic.columns):
        st_codes = set(
            stock_basic.loc[
                pd.to_numeric(stock_basic["is_st"], errors="coerce").fillna(0).eq(1),
                "code",
            ].astype(str)
        )
    up_ratio = round((latest_stocks["pct_chg"].gt(0).mean() * 100) if not latest_stocks.empty else 0, 2)
    limit_up_count = (
        int(
            latest_stocks.apply(
                lambda row: is_limit_up(str(row["code"]), float(row["pct_chg"]), str(row["code"]) in st_codes),
                axis=1,
            ).sum()
        )
        if "pct_chg" in latest_stocks
        else 0
    )
    limit_down_count = (
        int(
            latest_stocks.apply(
                lambda row: is_limit_down(str(row["code"]), float(row["pct_chg"]), str(row["code"]) in st_codes),
                axis=1,
            ).sum()
        )
        if "pct_chg" in latest_stocks
        else 0
    )

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

    rsrs = _rsrs_indicator(_latest_index(index_daily, "sh000001", report_date))
    score += _rsrs_adjustment(rsrs)
    new_high_ratio = _new_high_ratio(stock_daily, report_date)
    score += _new_high_adjustment(new_high_ratio)

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
        "rsrs_score": round(rsrs, 2) if rsrs is not None else None,
        "new_high_ratio": new_high_ratio,
    }
