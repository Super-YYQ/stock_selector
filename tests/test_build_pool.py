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
