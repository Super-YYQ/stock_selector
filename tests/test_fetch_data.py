import pandas as pd

from src.fetch_data import normalize_akshare_sector, normalize_baostock_daily


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
