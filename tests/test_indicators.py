import pandas as pd

from src.indicators import add_returns, add_rps, moving_average, pct_change_over


def test_pct_change_over_uses_period_ago_close() -> None:
    series = pd.Series([10, 11, 12, 15], dtype=float)

    result = pct_change_over(series, 3)

    assert round(result.iloc[-1], 2) == 50.0


def test_add_returns_adds_grouped_return_columns() -> None:
    df = pd.DataFrame(
        {
            "code": ["000001", "000001", "000001", "000002", "000002", "000002"],
            "trade_date": ["d1", "d2", "d3", "d1", "d2", "d3"],
            "close": [10, 11, 12, 20, 19, 18],
        }
    )

    result = add_returns(df, periods=(2,))

    assert round(result[result["code"] == "000001"].iloc[-1]["return_2d"], 2) == 20.0
    assert round(result[result["code"] == "000002"].iloc[-1]["return_2d"], 2) == -10.0


def test_add_rps_ranks_latest_date_cross_sectionally() -> None:
    df = pd.DataFrame(
        {
            "code": ["A", "B", "C"],
            "trade_date": ["2026-06-22"] * 3,
            "return_20d": [10, 30, 20],
        }
    )

    result = add_rps(df, "return_20d", "rps20")

    assert result.sort_values("code")["rps20"].tolist() == [33.33333333333333, 100.0, 66.66666666666666]


def test_moving_average_returns_rolling_mean() -> None:
    result = moving_average(pd.Series([1, 2, 3], dtype=float), 2)

    assert result.tolist() == [1.0, 1.5, 2.5]
