from __future__ import annotations

from collections.abc import Sequence

import pandas as pd


def pct_change_over(close: pd.Series, period: int) -> pd.Series:
    previous = close.shift(period)
    return (close - previous) / previous * 100


def moving_average(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=1).mean()


def add_returns(df: pd.DataFrame, periods: Sequence[int] = (5, 10, 20, 60)) -> pd.DataFrame:
    result = df.sort_values(["code", "trade_date"]).copy()
    for period in periods:
        result[f"return_{period}d"] = result.groupby("code")["close"].transform(
            lambda close: pct_change_over(close, period)
        )
    return result


def add_rps(df: pd.DataFrame, return_column: str, output_column: str) -> pd.DataFrame:
    result = df.copy()
    result[output_column] = result.groupby("trade_date")[return_column].rank(pct=True) * 100
    return result


def daily_price_limit(code: str, is_st: bool = False) -> float:
    normalized = str(code).zfill(6)
    if normalized.startswith(("43", "83", "87", "88", "92")):
        return 30.0
    if normalized.startswith(("300", "301", "688", "689")):
        return 20.0
    if is_st:
        return 5.0
    return 10.0


def limit_up_threshold(code: str, is_st: bool = False) -> float:
    limit = daily_price_limit(code, is_st)
    if limit >= 30:
        return 29.5
    if limit >= 20:
        return 19.5
    if limit <= 5:
        return 4.5
    return 9.5


def is_limit_up(code: str, pct_chg: float, is_st: bool = False) -> bool:
    return pct_chg >= limit_up_threshold(code, is_st)


def is_limit_down(code: str, pct_chg: float, is_st: bool = False) -> bool:
    return pct_chg <= -limit_up_threshold(code, is_st)


def is_price_jump_anomaly(code: str, pct_chg: float, is_st: bool = False) -> bool:
    return abs(float(pct_chg)) > daily_price_limit(code, is_st) + 1.0
