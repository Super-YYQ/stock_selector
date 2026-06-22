import pandas as pd

from src.sector_score import calculate_sector_scores


def test_calculate_sector_scores_ranks_hot_industries() -> None:
    sector_daily = pd.DataFrame(
        [
            {"sector_name": "机器人", "trade_date": "2026-06-22", "pct_chg": 4.2, "amount": 180},
            {"sector_name": "银行", "trade_date": "2026-06-22", "pct_chg": 0.5, "amount": 80},
            {"sector_name": "机器人", "trade_date": "2026-06-21", "pct_chg": 2.0, "amount": 100},
            {"sector_name": "银行", "trade_date": "2026-06-21", "pct_chg": -0.1, "amount": 90},
        ]
    )
    stock_basic = pd.DataFrame(
        [
            {"code": "000001", "industry": "机器人"},
            {"code": "000002", "industry": "银行"},
        ]
    )
    stock_daily = pd.DataFrame(
        [
            {"code": "000001", "trade_date": "2026-06-22", "pct_chg": 10},
            {"code": "000002", "trade_date": "2026-06-22", "pct_chg": 1},
        ]
    )

    stock_scores, strong = calculate_sector_scores(sector_daily, stock_basic, stock_daily, "2026-06-22")

    assert strong.iloc[0]["sector_name"] == "机器人"
    robot_score = stock_scores[stock_scores["code"] == "000001"].iloc[0]["sector_score_raw"]
    bank_score = stock_scores[stock_scores["code"] == "000002"].iloc[0]["sector_score_raw"]
    assert robot_score > bank_score
