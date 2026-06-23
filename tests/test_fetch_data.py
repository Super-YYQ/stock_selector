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

def test_data_fetcher_reuses_baostock_login_across_context(monkeypatch) -> None:
    import sys

    from src.fetch_data import DataFetcher

    class LoginResult:
        error_code = "0"
        error_msg = ""

    class QueryResult:
        def __init__(self, fields: list[str], rows: list[list[str]]) -> None:
            self.error_code = "0"
            self.error_msg = ""
            self.fields = fields
            self._rows = rows
            self._index = -1

        def next(self) -> bool:
            self._index += 1
            return self._index < len(self._rows)

        def get_row_data(self) -> list[str]:
            return self._rows[self._index]

    class FakeBaostock:
        def __init__(self) -> None:
            self.login_count = 0
            self.logout_count = 0

        def login(self) -> LoginResult:
            self.login_count += 1
            return LoginResult()

        def logout(self) -> None:
            self.logout_count += 1

        def query_stock_basic(self, code_name: str, code: str) -> QueryResult:
            return QueryResult(
                ["code", "code_name", "ipoDate", "type", "status"],
                [["sh.600000", "浦发银行", "1999-11-10", "1", "1"]],
            )

        def query_history_k_data_plus(
            self,
            code: str,
            fields: str,
            start_date: str,
            end_date: str,
            frequency: str,
            adjustflag: str,
        ) -> QueryResult:
            if "code" in fields.split(","):
                return QueryResult(
                    ["date", "code", "open", "high", "low", "close", "volume", "amount", "turn", "pctChg"],
                    [["2026-06-22", code, "10", "11", "9", "10.5", "1000", "105000", "1.2", "2.0"]],
                )
            return QueryResult(
                ["date", "open", "high", "low", "close", "volume", "amount", "pctChg"],
                [["2026-06-22", "3000", "3020", "2990", "3010", "100", "200", "0.5"]],
            )

    fake = FakeBaostock()
    monkeypatch.setitem(sys.modules, "baostock", fake)

    fetcher = DataFetcher("2026-01-01")
    with fetcher:
        assert fetcher.fetch_stock_basic()["code"].tolist() == ["600000"]
        assert fetcher.fetch_stock_daily("600000", end_date="2026-06-22")["code"].tolist() == ["600000"]
        assert fetcher.fetch_index_daily("sh000001", end_date="2026-06-22")["index_code"].tolist() == ["sh000001"]

    assert fake.login_count == 1
    assert fake.logout_count == 1
