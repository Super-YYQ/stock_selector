import pandas as pd

from src.fetch_data import (
    normalize_akshare_sector,
    normalize_baostock_daily,
    normalize_baostock_index_daily,
    normalize_baostock_stock_basic,
)


def test_normalize_baostock_daily_renames_and_converts_numbers() -> None:
    raw = pd.DataFrame(
        [
            {
                "code": "sh.600000",
                "date": "2026-06-22",
                "open": "10.0",
                "high": "11.0",
                "low": "9.9",
                "close": "10.8",
                "volume": "1000",
                "amount": "108000",
                "turn": "1.2",
                "pctChg": "2.86",
            }
        ]
    )

    normalized = normalize_baostock_daily(raw)

    assert normalized.to_dict("records") == [
        {
            "code": "600000",
            "trade_date": "2026-06-22",
            "open": 10.0,
            "high": 11.0,
            "low": 9.9,
            "close": 10.8,
            "volume": 1000.0,
            "amount": 108000.0,
            "turnover_rate": 1.2,
            "pct_chg": 2.86,
            "is_suspended": False,
        }
    ]


def test_normalize_akshare_sector_supports_chinese_columns() -> None:
    raw = pd.DataFrame(
        [
            {"板块名称": "机器人", "涨跌幅": 4.2, "成交额": 18000000000},
            {"板块名称": "AI算力", "涨跌幅": 3.5, "成交额": 15000000000},
        ]
    )

    normalized = normalize_akshare_sector(raw, "2026-06-22")

    assert list(normalized.columns) == ["sector_name", "trade_date", "pct_chg", "amount"]
    assert normalized.loc[0, "sector_name"] == "机器人"
    assert normalized.loc[0, "trade_date"] == "2026-06-22"


def test_normalize_baostock_stock_basic_outputs_core_columns() -> None:
    raw = pd.DataFrame(
        [
            {
                "code": "sh.600000",
                "code_name": "浦发银行",
                "ipoDate": "1999-11-10",
                "type": "1",
                "status": "1",
            }
        ]
    )

    normalized = normalize_baostock_stock_basic(raw)

    assert normalized.to_dict("records") == [
        {
            "code": "600000",
            "name": "浦发银行",
            "exchange": "sh",
            "industry": "",
            "list_date": "1999-11-10",
            "is_st": 0,
            "is_listed": 1,
        }
    ]


def test_normalize_baostock_index_daily_sets_index_code() -> None:
    raw = pd.DataFrame(
        [
            {
                "date": "2026-06-22",
                "open": "3000",
                "high": "3030",
                "low": "2990",
                "close": "3020",
                "volume": "100",
                "amount": "200",
                "pctChg": "1.2",
            }
        ]
    )

    normalized = normalize_baostock_index_daily(raw, "sh000001")

    assert normalized.loc[0, "index_code"] == "sh000001"
    assert normalized.loc[0, "trade_date"] == "2026-06-22"
    assert normalized.loc[0, "pct_chg"] == 1.2
