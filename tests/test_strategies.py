import pandas as pd

from src.strategies.registry import run_enabled_strategies


def _strategy_daily() -> pd.DataFrame:
    rows = []
    for day in range(1, 62):
        close_a = 10 + day * 0.1
        rows.append(
            {
                "code": "000001",
                "trade_date": f"2026-05-{day:02d}",
                "open": close_a - 0.2,
                "high": close_a + 0.2,
                "low": close_a - 0.5,
                "close": close_a,
                "amount": 100,
                "pct_chg": 1,
            }
        )
        rows.append(
            {
                "code": "000002",
                "trade_date": f"2026-05-{day:02d}",
                "open": 10,
                "high": 10.2,
                "low": 9.8,
                "close": 10,
                "amount": 100,
                "pct_chg": 0,
            }
        )
    rows[-2]["close"] = 17
    rows[-2]["high"] = 17.2
    rows[-2]["amount"] = 320
    rows[-2]["pct_chg"] = 6
    return pd.DataFrame(rows)


def test_run_enabled_strategies_aggregates_hits_and_caps_score() -> None:
    daily = _strategy_daily()
    factors = pd.DataFrame(
        [
            {"code": "000001", "rps20": 92, "rps60": 88},
            {"code": "000002", "rps20": 20, "rps60": 30},
        ]
    )

    result = run_enabled_strategies(
        daily,
        "2026-05-61",
        factors,
        ["ma_volume", "turtle_breakout", "rps_breakout"],
    )

    strong = result[result["code"] == "000001"].iloc[0]
    weak = result[result["code"] == "000002"].iloc[0]
    assert "均线放量突破" in strong["matched_strategies"]
    assert "海龟突破" in strong["matched_strategies"]
    assert "RPS强势突破" in strong["matched_strategies"]
    assert strong["strategy_score_raw"] == 100
    assert weak["strategy_score_raw"] == 0


def test_run_enabled_strategies_returns_zero_when_disabled() -> None:
    daily = _strategy_daily()
    factors = pd.DataFrame([{"code": "000001"}])

    result = run_enabled_strategies(daily, "2026-05-61", factors, [])

    assert result.loc[0, "strategy_score_raw"] == 0
    assert result.loc[0, "matched_strategies"] == ""
