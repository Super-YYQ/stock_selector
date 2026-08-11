from __future__ import annotations

import pandas as pd
import pytest

from src.config import PerformanceConfig
from src.performance import evaluate_selection_returns


def _selections() -> pd.DataFrame:
    return pd.DataFrame([{"report_date": "2026-06-22", "code": "000001", "close": 10}])


def _bar(
    trade_date: str,
    *,
    open_price: float,
    close: float,
    high: float | None = None,
    low: float | None = None,
    pct_chg: float = 1,
    suspended: int = 0,
) -> dict[str, object]:
    return {
        "code": "000001",
        "trade_date": trade_date,
        "open": open_price,
        "high": close if high is None else high,
        "low": open_price if low is None else low,
        "close": close,
        "pct_chg": pct_chg,
        "is_suspended": suspended,
    }


def test_returns_use_next_open_costs_and_benchmark_excess() -> None:
    daily = pd.DataFrame(
        [_bar("2026-06-23", open_price=10, close=11, high=11, low=9.9)]
    )
    benchmark = pd.DataFrame(
        [{"trade_date": "2026-06-23", "open": 100, "close": 101}]
    )
    config = PerformanceConfig(entry_cost_bps=8, exit_cost_bps=13)

    result = evaluate_selection_returns(_selections(), daily, benchmark, config).iloc[0]

    expected = (11 * (1 - 13 / 10_000) / (10 * (1 + 8 / 10_000)) - 1) * 100
    assert result["return_status"] == "evaluated"
    assert result["entry_date"] == "2026-06-23"
    assert result["return_1d"] == pytest.approx(expected, abs=1e-4)
    assert result["excess_return_1d"] == pytest.approx(expected - 1, abs=1e-4)


def test_one_price_limit_up_entry_is_not_counted_as_tradable() -> None:
    daily = pd.DataFrame(
        [
            _bar(
                "2026-06-23",
                open_price=11,
                close=11,
                high=11,
                low=11,
                pct_chg=10,
            )
        ]
    )

    result = evaluate_selection_returns(_selections(), daily, pd.DataFrame()).iloc[0]

    assert result["return_status"] == "untradable"
    assert pd.isna(result["return_1d"])


def test_horizon_crossing_price_jump_anomaly_is_excluded() -> None:
    daily = pd.DataFrame(
        [
            _bar("2026-06-23", open_price=10, close=10.5, high=10.6, low=9.9),
            _bar("2026-06-24", open_price=6, close=6, high=6.2, low=5.8, pct_chg=-42.86),
            _bar("2026-06-25", open_price=6, close=6.2, high=6.3, low=5.9),
        ]
    )
    config = PerformanceConfig(entry_cost_bps=0, exit_cost_bps=0)

    result = evaluate_selection_returns(_selections(), daily, pd.DataFrame(), config).iloc[0]

    assert result["return_1d"] == 5
    assert pd.isna(result["return_3d"])
    assert result["return_status"] == "evaluated"


def test_suspended_entry_is_not_tradable() -> None:
    daily = pd.DataFrame(
        [_bar("2026-06-23", open_price=10, close=10, suspended=1)]
    )

    result = evaluate_selection_returns(_selections(), daily, pd.DataFrame()).iloc[0]

    assert result["return_status"] == "untradable"


def test_missing_bar_on_next_market_day_is_not_shifted_to_later_entry() -> None:
    daily = pd.DataFrame(
        [_bar("2026-06-24", open_price=10, close=10.5, high=10.6, low=9.9)]
    )
    benchmark = pd.DataFrame(
        [
            {"trade_date": "2026-06-23", "open": 100, "close": 101},
            {"trade_date": "2026-06-24", "open": 101, "close": 102},
        ]
    )

    result = evaluate_selection_returns(_selections(), daily, benchmark).iloc[0]

    assert result["entry_date"] == "2026-06-23"
    assert result["return_status"] == "untradable"
    assert pd.isna(result["entry_open"])


def test_market_calendar_falls_back_to_all_stocks_not_selected_stock() -> None:
    daily = pd.DataFrame(
        [
            _bar("2026-06-24", open_price=10, close=10.5, high=10.6, low=9.9),
            {**_bar("2026-06-23", open_price=20, close=20.5, high=20.6, low=19.9), "code": "000002"},
        ]
    )

    result = evaluate_selection_returns(_selections(), daily, pd.DataFrame()).iloc[0]

    assert result["entry_date"] == "2026-06-23"
    assert result["return_status"] == "untradable"
