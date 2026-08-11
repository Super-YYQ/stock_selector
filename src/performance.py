from __future__ import annotations

import math

import pandas as pd

from src.config import PerformanceConfig
from src.indicators import is_price_jump_anomaly, limit_up_threshold


HORIZONS = (1, 3, 5, 10)
RETURN_BASIS = "next_open_net_v1"


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _one_price_limit_up(row: pd.Series, code: str) -> bool:
    open_price = _number(row.get("open"))
    high = _number(row.get("high"))
    low = _number(row.get("low"))
    pct_chg = _number(row.get("pct_chg"))
    if None in {open_price, high, low, pct_chg}:
        return False
    one_price = math.isclose(open_price, high, rel_tol=0, abs_tol=1e-6) and math.isclose(
        high, low, rel_tol=0, abs_tol=1e-6
    )
    return one_price and pct_chg >= limit_up_threshold(code)


def _entry_is_tradable(row: pd.Series, code: str, config: PerformanceConfig) -> bool:
    entry_open = _number(row.get("open"))
    if entry_open is None or entry_open <= 0:
        return False
    suspended = _number(row.get("is_suspended")) or 0.0
    if suspended > 0:
        return False
    return not (config.exclude_untradable_entry and _one_price_limit_up(row, code))


def _path_has_anomaly(path: pd.DataFrame, code: str) -> bool:
    if "pct_chg" not in path.columns:
        return False
    for value in pd.to_numeric(path["pct_chg"], errors="coerce").dropna():
        if is_price_jump_anomaly(code, float(value)):
            return True
    return False


def _net_return_pct(entry_open: float, exit_close: float, config: PerformanceConfig) -> float:
    entry_cash = entry_open * (1 + config.entry_cost_bps / 10_000)
    exit_cash = exit_close * (1 - config.exit_cost_bps / 10_000)
    return (exit_cash / entry_cash - 1) * 100


def _benchmark_return_pct(
    benchmark_by_date: pd.DataFrame,
    entry_date: str,
    exit_date: str,
) -> float | None:
    if entry_date not in benchmark_by_date.index or exit_date not in benchmark_by_date.index:
        return None
    entry_open = _number(benchmark_by_date.at[entry_date, "open"])
    exit_close = _number(benchmark_by_date.at[exit_date, "close"])
    if entry_open is None or entry_open <= 0 or exit_close is None:
        return None
    return (exit_close / entry_open - 1) * 100


def evaluate_selection_returns(
    selections: pd.DataFrame,
    stock_daily: pd.DataFrame,
    index_daily: pd.DataFrame,
    config: PerformanceConfig | None = None,
) -> pd.DataFrame:
    """Evaluate saved close-of-day signals using a tradable next-open entry.

    Raw OHLC data is retained for execution checks. Suspended or one-price
    limit-up entries are rejected, and horizons crossing a suspicious price
    jump are left unevaluated instead of polluting strategy statistics.
    """

    settings = config or PerformanceConfig()
    output_columns = [
        "report_date",
        "code",
        "entry_date",
        "entry_open",
        "return_status",
        "return_basis",
        *[f"return_{horizon}d" for horizon in HORIZONS],
        *[f"excess_return_{horizon}d" for horizon in HORIZONS],
    ]
    if selections.empty:
        return pd.DataFrame(columns=output_columns)

    daily = stock_daily.copy()
    if not daily.empty:
        daily["code"] = daily["code"].astype(str).str.zfill(6)
        daily["trade_date"] = daily["trade_date"].astype(str)
        daily = daily.sort_values(["code", "trade_date"])
    grouped = {code: frame.reset_index(drop=True) for code, frame in daily.groupby("code", sort=False)}

    benchmark = index_daily.copy()
    if not benchmark.empty:
        benchmark["trade_date"] = benchmark["trade_date"].astype(str)
        benchmark = benchmark.sort_values("trade_date").drop_duplicates("trade_date", keep="last")
        benchmark = benchmark.set_index("trade_date")
    market_calendar = (
        benchmark.index.astype(str).tolist()
        if not benchmark.empty
        else sorted(daily["trade_date"].dropna().astype(str).unique().tolist())
    )

    rows: list[dict[str, object]] = []
    for selection in selections.itertuples(index=False):
        report_date = str(selection.report_date)
        code = str(selection.code).zfill(6)
        values: dict[str, object] = {
            "report_date": report_date,
            "code": code,
            "entry_date": None,
            "entry_open": None,
            "return_status": "pending",
            "return_basis": RETURN_BASIS,
        }
        values.update({f"return_{horizon}d": None for horizon in HORIZONS})
        values.update({f"excess_return_{horizon}d": None for horizon in HORIZONS})

        history = grouped.get(code)
        stock_future = history[history["trade_date"] > report_date] if history is not None else pd.DataFrame()
        calendar_dates = [date for date in market_calendar if date > report_date][: max(HORIZONS)]
        entry_date = calendar_dates[0] if calendar_dates else ""
        entry_rows = stock_future[stock_future["trade_date"] == entry_date] if entry_date else pd.DataFrame()

        if not entry_date:
            rows.append(values)
            continue

        values["entry_date"] = entry_date
        if entry_rows.empty:
            values["return_status"] = "untradable"
            rows.append(values)
            continue

        entry = entry_rows.iloc[0]
        entry_open = _number(entry.get("open"))
        values["entry_open"] = entry_open
        if not _entry_is_tradable(entry, code, settings):
            values["return_status"] = "untradable"
            rows.append(values)
            continue

        any_valid = False
        any_anomaly = False
        for horizon in HORIZONS:
            if len(calendar_dates) < horizon:
                continue
            horizon_dates = calendar_dates[:horizon]
            path = stock_future[stock_future["trade_date"].isin(horizon_dates)].sort_values("trade_date")
            if len(path) != horizon:
                continue
            if settings.exclude_price_jump_anomaly and _path_has_anomaly(path, code):
                any_anomaly = True
                continue
            exit_row = path.iloc[-1]
            exit_close = _number(exit_row.get("close"))
            if entry_open is None or exit_close is None:
                continue
            net_return = _net_return_pct(entry_open, exit_close, settings)
            values[f"return_{horizon}d"] = round(net_return, 4)
            benchmark_return = _benchmark_return_pct(
                benchmark,
                entry_date,
                str(exit_row["trade_date"]),
            )
            if benchmark_return is not None:
                values[f"excess_return_{horizon}d"] = round(net_return - benchmark_return, 4)
            any_valid = True

        if any_valid:
            values["return_status"] = "evaluated"
        elif any_anomaly:
            values["return_status"] = "anomalous"
        rows.append(values)

    return pd.DataFrame(rows, columns=output_columns)
