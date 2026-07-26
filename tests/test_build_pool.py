import pandas as pd

from src.build_pool import build_stock_pool
from src.config import StockPoolConfig


def test_build_stock_pool_filters_expected_reasons() -> None:
    basic = pd.DataFrame(
        [
            {"code": "000001", "name": "平安银行", "industry": "银行", "list_date": "2000-01-01", "is_st": 0, "is_listed": 1},
            {"code": "000002", "name": "ST测试", "industry": "地产", "list_date": "2000-01-01", "is_st": 1, "is_listed": 1},
            {"code": "000003", "name": "新股", "industry": "电子", "list_date": "2026-06-01", "is_st": 0, "is_listed": 1},
            {"code": "000004", "name": "低价", "industry": "机械", "list_date": "2000-01-01", "is_st": 0, "is_listed": 1},
        ]
    )
    daily = pd.DataFrame(
        [
            {"code": "000001", "trade_date": "2026-06-22", "close": 10, "amount": 200000000, "is_suspended": 0, "pct_chg": 2},
            {"code": "000002", "trade_date": "2026-06-22", "close": 8, "amount": 200000000, "is_suspended": 0, "pct_chg": 1},
            {"code": "000003", "trade_date": "2026-06-22", "close": 20, "amount": 200000000, "is_suspended": 0, "pct_chg": 1},
            {"code": "000004", "trade_date": "2026-06-22", "close": 2.5, "amount": 200000000, "is_suspended": 0, "pct_chg": 1},
        ]
    )

    eligible, filtered = build_stock_pool(
        basic,
        daily,
        "2026-06-22",
        StockPoolConfig(min_avg_amount_20d=100000000),
    )

    assert eligible["code"].tolist() == ["000001"]
    assert set(filtered["code"]) == {"000002", "000003", "000004"}
    assert "ST" in filtered[filtered["code"] == "000002"].iloc[0]["filter_reason"]
    assert "上市不足" in filtered[filtered["code"] == "000003"].iloc[0]["filter_reason"]
    assert "价格低于" in filtered[filtered["code"] == "000004"].iloc[0]["filter_reason"]


def test_build_stock_pool_uses_earliest_daily_date_when_list_date_missing() -> None:
    basic = pd.DataFrame(
        [
            {"code": "000001", "name": "Old Co", "industry": "Bank", "list_date": "", "is_st": 0, "is_listed": 1},
            {"code": "000002", "name": "New Co", "industry": "Tech", "list_date": "", "is_st": 0, "is_listed": 1},
        ]
    )
    daily = pd.DataFrame(
        [
            {"code": "000001", "trade_date": "2023-01-01", "close": 10, "amount": 200000000, "is_suspended": 0, "pct_chg": 1},
            {"code": "000001", "trade_date": "2026-06-22", "close": 11, "amount": 200000000, "is_suspended": 0, "pct_chg": 1},
            {"code": "000002", "trade_date": "2026-06-01", "close": 10, "amount": 200000000, "is_suspended": 0, "pct_chg": 1},
            {"code": "000002", "trade_date": "2026-06-22", "close": 11, "amount": 200000000, "is_suspended": 0, "pct_chg": 1},
        ]
    )

    eligible, filtered = build_stock_pool(
        basic,
        daily,
        "2026-06-22",
        StockPoolConfig(min_avg_amount_20d=0),
    )

    assert eligible["code"].tolist() == ["000001"]
    assert filtered["code"].tolist() == ["000002"]


def test_build_stock_pool_excludes_configured_market_boards() -> None:
    basic = pd.DataFrame(
        [
            {"code": "920001", "name": "北交股票", "industry": "", "list_date": "2020-01-01", "is_st": 0, "is_listed": 1},
            {"code": "688001", "name": "科创股票", "industry": "", "list_date": "2020-01-01", "is_st": 0, "is_listed": 1},
            {"code": "000001", "name": "主板股票", "industry": "", "list_date": "2020-01-01", "is_st": 0, "is_listed": 1},
        ]
    )
    daily = pd.DataFrame(
        [
            {"code": code, "trade_date": "2026-06-22", "close": 10, "amount": 200000000, "is_suspended": 0, "pct_chg": 1}
            for code in basic["code"]
        ]
    )

    eligible, filtered = build_stock_pool(
        basic,
        daily,
        "2026-06-22",
        StockPoolConfig(min_avg_amount_20d=0, exclude_boards=["北交所", "科创板"]),
    )

    assert eligible["code"].tolist() == ["000001"]
    assert set(filtered["code"]) == {"920001", "688001"}
    assert filtered["filter_reason"].str.contains("已排除市场板块").all()


def test_build_stock_pool_excludes_stale_and_recent_price_jump_data() -> None:
    basic = pd.DataFrame(
        [
            {"code": "000001", "name": "Stale", "industry": "Bank", "list_date": "2020-01-01", "is_st": 0},
            {"code": "000002", "name": "Jump", "industry": "Tech", "list_date": "2020-01-01", "is_st": 0},
        ]
    )
    daily = pd.DataFrame(
        [
            {"code": "000001", "trade_date": "2026-06-21", "close": 10, "amount": 200000000, "is_suspended": 0, "pct_chg": 1},
            {"code": "000002", "trade_date": "2026-06-21", "close": 20, "amount": 200000000, "is_suspended": 0, "pct_chg": -35},
            {"code": "000002", "trade_date": "2026-06-22", "close": 20, "amount": 200000000, "is_suspended": 0, "pct_chg": 1},
        ]
    )

    eligible, filtered = build_stock_pool(
        basic,
        daily,
        "2026-06-22",
        StockPoolConfig(min_avg_amount_20d=0),
    )

    assert eligible.empty
    reasons = filtered.set_index("code")["filter_reason"]
    assert "缺少报告日行情" in reasons["000001"]
    assert "异常价格跳变" in reasons["000002"]
