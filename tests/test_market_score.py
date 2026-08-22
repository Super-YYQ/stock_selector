import pandas as pd

from src.market_score import (
    _new_high_ratio,
    _rsrs_adjustment,
    _rsrs_indicator,
    calculate_market_score,
)


def test_calculate_market_score_labels_strong_market() -> None:
    index_daily = pd.DataFrame(
        [
            {
                "index_code": "sh000001",
                "trade_date": f"2026-06-{day:02d}",
                "close": 3000 + day,
                "amount": 1000 + day * 10,
                "pct_chg": 0.2,
            }
            for day in range(1, 23)
        ]
        + [
            {"index_code": "sz399001", "trade_date": "2026-06-22", "close": 10000, "amount": 1200, "pct_chg": 1.2},
            {"index_code": "sz399006", "trade_date": "2026-06-22", "close": 2200, "amount": 800, "pct_chg": 1.8},
        ]
    )
    stock_daily = pd.DataFrame(
        [
            {"code": f"{i:06d}", "trade_date": "2026-06-22", "pct_chg": 1.0, "amount": 1000}
            for i in range(70)
        ]
        + [
            {"code": f"{i + 70:06d}", "trade_date": "2026-06-22", "pct_chg": -1.0, "amount": 1000}
            for i in range(30)
        ]
    )

    result = calculate_market_score(index_daily, stock_daily, "2026-06-22")

    assert result["market_label"] == "偏强"
    assert result["risk_level"] in {"低", "中"}
    assert result["up_ratio"] == 70.0
    assert result["market_score"] >= 7


def test_rsrs_indicator_turns_positive_when_range_expands_in_uptrend() -> None:
    rows = []
    for index in range(100):
        low = 100 + index
        spread = 4 if index < 80 else 4 + 6 * (index - 80) / 19
        high = low + spread
        rows.append(
            {
                "index_code": "sh000001",
                "trade_date": f"2026-01-{(index % 28) + 1:02d}",
                "open": low,
                "high": high,
                "low": low,
                "close": low + spread / 2,
                "volume": 1000 + index,
                "pct_chg": 0.5,
            }
        )
    history = pd.DataFrame(rows)

    rsrs = _rsrs_indicator(history)

    assert rsrs is not None
    assert rsrs > 0.85
    assert _rsrs_adjustment(rsrs) >= 0.8


def test_rsrs_indicator_neutral_without_enough_history() -> None:
    history = pd.DataFrame(
        [
            {
                "index_code": "sh000001",
                "trade_date": f"2026-06-{day:02d}",
                "high": 3010 + day,
                "low": 3000 + day,
                "close": 3005 + day,
                "volume": 1000,
                "pct_chg": 0.2,
            }
            for day in range(1, 23)
        ]
    )

    assert _rsrs_indicator(history) is None
    assert _rsrs_adjustment(None) == 0.0


def test_new_high_ratio_measures_market_breadth() -> None:
    rows = []
    for code, breakout in (("000001", True), ("000002", False)):
        for day in range(25):
            high = 10.0 + day * 0.05
            close = high + 0.3 if (breakout and day == 24) else high - 0.05
            rows.append(
                {
                    "code": code,
                    "trade_date": f"2026-06-{day + 1:02d}",
                    "high": high,
                    "low": high - 0.4,
                    "close": close,
                    "pct_chg": 1.0,
                    "amount": 1000,
                }
            )
    stock_daily = pd.DataFrame(rows)

    ratio = _new_high_ratio(stock_daily, "2026-06-25")

    assert ratio == 50.0
    empty_index = pd.DataFrame(
        columns=["index_code", "trade_date", "open", "high", "low", "close", "volume", "pct_chg"]
    )
    result = calculate_market_score(empty_index, stock_daily, "2026-06-25")
    assert result["new_high_ratio"] == 50.0
    assert result["rsrs_score"] is None
