import pandas as pd

from src.sector_score import build_market_board_daily, calculate_sector_scores, fill_market_board_industry, market_board


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


def test_local_market_board_fallback_assigns_industry_and_aggregates_daily() -> None:
    basic = pd.DataFrame(
        [
            {"code": "000001", "industry": ""},
            {"code": "300001", "industry": None},
            {"code": "688001", "industry": ""},
            {"code": "920001", "industry": ""},
        ]
    )
    daily = pd.DataFrame(
        [
            {"code": "000001", "trade_date": "2026-06-22", "pct_chg": 1.0, "amount": 100.0},
            {"code": "300001", "trade_date": "2026-06-22", "pct_chg": 2.0, "amount": 200.0},
            {"code": "688001", "trade_date": "2026-06-22", "pct_chg": 3.0, "amount": 300.0},
            {"code": "920001", "trade_date": "2026-06-22", "pct_chg": 4.0, "amount": 400.0},
        ]
    )

    prepared = fill_market_board_industry(basic)
    sectors = build_market_board_daily(prepared, daily)

    assert prepared["industry"].tolist() == ["深市主板", "创业板", "科创板", "北交所"]
    assert set(sectors["sector_name"]) == {"深市主板", "创业板", "科创板", "北交所"}
    assert sectors.loc[sectors["sector_name"] == "北交所", "amount"].iloc[0] == 400


def test_market_board_recognizes_legacy_beijing_exchange_codes() -> None:
    assert market_board("430001") == "北交所"
    assert market_board("830001") == "北交所"
    assert market_board("870001") == "北交所"
    assert market_board("880001") == "北交所"
    assert market_board("920001") == "北交所"
