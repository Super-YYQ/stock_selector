import pandas as pd

from src.stock_character import calculate_stock_character_scores


def test_stock_character_rewards_active_history_and_rps() -> None:
    rows = []
    for day in range(1, 62):
        rows.append(
            {
                "code": "A",
                "trade_date": f"2026-04-{day:02d}",
                "open": 10,
                "high": 12,
                "low": 9,
                "close": 10 + day * 0.2,
                "pct_chg": 6 if day % 10 == 0 else 1,
                "amount": 200 + day,
            }
        )
        rows.append(
            {
                "code": "B",
                "trade_date": f"2026-04-{day:02d}",
                "open": 10,
                "high": 10.5,
                "low": 9.8,
                "close": 10 + day * 0.02,
                "pct_chg": 0.2,
                "amount": 100,
            }
        )
    daily = pd.DataFrame(rows)

    result = calculate_stock_character_scores(daily, "2026-04-61")

    score_a = result[result["code"] == "A"].iloc[0]
    score_b = result[result["code"] == "B"].iloc[0]
    assert score_a["stock_character_score_raw"] > score_b["stock_character_score_raw"]
    assert score_a["rps60"] >= score_b["rps60"]
    assert "股性活跃" in score_a["character_reason"]
