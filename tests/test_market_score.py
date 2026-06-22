import pandas as pd

from src.market_score import calculate_market_score


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
