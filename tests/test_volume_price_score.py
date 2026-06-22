import pandas as pd

from src.volume_price_score import calculate_volume_price_scores


def test_volume_price_rewards_breakout_with_volume() -> None:
    rows = []
    for day in range(1, 62):
        rows.append(
            {
                "code": "A",
                "trade_date": f"2026-05-{day:02d}",
                "open": 10,
                "high": 10 + day * 0.1,
                "low": 9.8,
                "close": 10 + day * 0.1,
                "amount": 100,
                "pct_chg": 1,
            }
        )
        rows.append(
            {
                "code": "B",
                "trade_date": f"2026-05-{day:02d}",
                "open": 10,
                "high": 10.2,
                "low": 9.8,
                "close": 10,
                "amount": 100,
                "pct_chg": 0,
            }
        )
    rows[-2]["amount"] = 300
    rows[-2]["pct_chg"] = 4
    daily = pd.DataFrame(rows)

    result = calculate_volume_price_scores(daily, "2026-05-61")

    score_a = result[result["code"] == "A"].iloc[0]
    score_b = result[result["code"] == "B"].iloc[0]
    assert score_a["volume_price_score_raw"] > score_b["volume_price_score_raw"]
    assert "突破" in score_a["volume_price_reason"]
