import pandas as pd
import pytest

from src.fetch_data import (
    normalize_akshare_index_daily,
    normalize_akshare_stock_basic,
    normalize_akshare_stock_daily,
    normalize_akshare_sector,
    normalize_baostock_daily,
    normalize_baostock_index_daily,
    normalize_baostock_stock_basic,
    normalize_tdx_stock_daily,
    tdx_market,
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


def test_normalize_tdx_stock_daily_converts_lots_and_calculates_returns() -> None:
    raw = pd.DataFrame(
        [
            {
                "open": 10.0,
                "close": 10.0,
                "high": 10.2,
                "low": 9.9,
                "vol": 1000,
                "amount": 1000000,
                "datetime": "2026-06-21 15:00",
            },
            {
                "open": 10.1,
                "close": 10.5,
                "high": 10.6,
                "low": 10.0,
                "vol": 1200,
                "amount": 1250000,
                "datetime": "2026-06-22 15:00",
            },
        ]
    )

    normalized = normalize_tdx_stock_daily(raw, "000001")

    assert normalized["trade_date"].tolist() == ["2026-06-21", "2026-06-22"]
    assert normalized["volume"].tolist() == [100000.0, 120000.0]
    assert normalized["amount"].tolist() == [1000000.0, 1250000.0]
    assert normalized.loc[0, "pct_chg"] == 0
    assert round(normalized.loc[1, "pct_chg"], 6) == 5
    assert pd.isna(normalized.loc[1, "turnover_rate"])


def test_tdx_market_covers_shenzhen_shanghai_and_beijing() -> None:
    assert tdx_market("000001") == 0
    assert tdx_market("600000") == 1
    assert tdx_market("920001") == 2



def test_tdxdata_fetcher_maps_async_bars_without_lot_conversion() -> None:
    from types import SimpleNamespace

    from src.fetch_data import TdxDataFetcher

    calls: list[tuple[str, dict[str, object]]] = []
    factory_kwargs: dict[str, object] = {}

    def bar(trade_date: str, close: float, volume: float) -> SimpleNamespace:
        return SimpleNamespace(
            trading_date=trade_date,
            open=close - 0.2,
            high=close + 0.2,
            low=close - 0.3,
            close=close,
            vol=volume,
            amount=volume * close,
        )

    class FakeTdxData:
        def __init__(self, **kwargs: object) -> None:
            factory_kwargs.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def get_bars(self, symbol: str, _period: object, **kwargs: object):
            calls.append((symbol, kwargs))
            if symbol == "sh000001":
                return [bar("2026-10-22", 3020, 120)]
            return [
                bar("2026-10-20", 10.0, 1000),
                bar("2026-10-21", 10.0, 1100),
                bar("2026-10-22", 10.5, 1200),
                bar("2026-10-23", 10.7, 1300),
            ]

    fetcher = TdxDataFetcher(
        "2026-10-01",
        hosts=(("first", "127.0.0.1", 7709), ("second", "127.0.0.2", 7709)),
        client_factory=FakeTdxData,
    )

    with fetcher:
        daily = fetcher.fetch_stock_daily("920001", "2026-10-22", "2026-10-23")
        index = fetcher.fetch_index_daily("sh000001", "2026-10-22", "2026-10-22")

    assert factory_kwargs["standard_servers"] == ["127.0.0.1", "127.0.0.2"]
    assert factory_kwargs["std_pool_cap"] == 1
    assert [symbol for symbol, _kwargs in calls] == ["sh000001", "bj920001", "sh000001"]
    assert daily["trade_date"].tolist() == ["2026-10-22", "2026-10-23"]
    assert daily["volume"].tolist() == [1200.0, 1300.0]
    assert round(float(daily.loc[0, "pct_chg"]), 6) == 5.0
    assert index["index_code"].tolist() == ["sh000001"]
    assert index["volume"].tolist() == [120.0]


def test_tdxdata_fetcher_rejects_mixed_ports() -> None:
    from src.fetch_data import TdxDataFetcher

    with pytest.raises(ValueError, match="same port"):
        TdxDataFetcher(
            "2026-10-01",
            hosts=(("first", "127.0.0.1", 7709), ("second", "127.0.0.2", 7727)),
        )


def test_parse_tdx_hosts_accepts_ip_port_and_rejects_malformed_entries() -> None:
    from src.tdx_fetcher import DEFAULT_TDX_HOSTS, parse_tdx_hosts

    assert parse_tdx_hosts([]) == ()
    assert parse_tdx_hosts([" 117.34.114.17:7709 ", "example.com:80"]) == (
        ("117.34.114.17:7709", "117.34.114.17", 7709),
        ("example.com:80", "example.com", 80),
    )
    assert all(len(host) == 3 and 0 < host[2] < 65536 for host in DEFAULT_TDX_HOSTS)
    for bad in ["117.34.114.17", "117.34.114.17:abc", ":7709", "117.34.114.17:0", ""]:
        with pytest.raises(ValueError, match="tdx host"):
            parse_tdx_hosts([bad])


def test_fetch_tdx_stock_daily_parallel_passes_hosts_to_workers(monkeypatch) -> None:
    from src import tdx_fetcher as tdx_module

    captured: list[tuple[tuple, int]] = []

    class RecordingFetcher:
        def __init__(self, start_date: str, **kwargs) -> None:
            captured.append((kwargs["hosts"], kwargs["host_offset"]))

        def __enter__(self) -> "RecordingFetcher":
            return self

        def __exit__(self, *args) -> None:
            pass

        def fetch_stock_daily(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
            return pd.DataFrame([{"code": code, "trade_date": end_date}])

    monkeypatch.setattr(tdx_module, "TdxDataFetcher", RecordingFetcher)
    hosts = (("custom", "127.0.0.9", 7709),)
    batches = list(
        tdx_module.fetch_tdx_stock_daily_parallel(
            [("000001", "2026-06-01", "2026-06-22"), ("000002", "2026-06-01", "2026-06-22")],
            workers=2,
            chunk_size=1,
            timeout_seconds=3,
            query_retries=1,
            hosts=hosts,
        )
    )

    assert captured == [(hosts, 0), (hosts, 0)]
    assert [len(daily) for daily, _failures, _requested in batches] == [1, 1]


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



def test_normalize_akshare_stock_daily_renames_and_converts_numbers() -> None:
    raw = pd.DataFrame(
        [
            {
                "\u65e5\u671f": "2026-06-22",
                "\u80a1\u7968\u4ee3\u7801": "000001",
                "\u5f00\u76d8": "10.0",
                "\u6536\u76d8": "10.8",
                "\u6700\u9ad8": "11.0",
                "\u6700\u4f4e": "9.9",
                "\u6210\u4ea4\u91cf": "1000",
                "\u6210\u4ea4\u989d": "108000",
                "\u6da8\u8dcc\u5e45": "2.86",
                "\u6362\u624b\u7387": "1.2",
            }
        ]
    )

    normalized = normalize_akshare_stock_daily(raw, "000001")

    assert normalized.to_dict("records") == [
        {
            "code": "000001",
            "trade_date": "2026-06-22",
            "open": 10.0,
            "high": 11.0,
            "low": 9.9,
            "close": 10.8,
            "volume": 1000,
            "amount": 108000,
            "turnover_rate": 1.2,
            "pct_chg": 2.86,
            "is_suspended": False,
        }
    ]


def test_normalize_akshare_stock_basic_outputs_core_columns() -> None:
    raw = pd.DataFrame(
        [
            {"code": "1", "name": "Ping An Bank"},
            {"code": "600000", "name": "PF Bank"},
        ]
    )

    normalized = normalize_akshare_stock_basic(raw)

    assert normalized.to_dict("records") == [
        {
            "code": "000001",
            "name": "Ping An Bank",
            "exchange": "sz",
            "industry": "",
            "list_date": "",
            "is_st": 0,
            "is_listed": 1,
        },
        {
            "code": "600000",
            "name": "PF Bank",
            "exchange": "sh",
            "industry": "",
            "list_date": "",
            "is_st": 0,
            "is_listed": 1,
        },
    ]


def test_normalize_akshare_index_daily_calculates_pct_chg_when_missing() -> None:
    raw = pd.DataFrame(
        [
            {"date": "2026-06-21", "open": "3000", "close": "3010", "high": "3020", "low": "2990", "volume": "100", "amount": "200"},
            {"date": "2026-06-22", "open": "3010", "close": "3040", "high": "3050", "low": "3000", "volume": "120", "amount": "240"},
        ]
    )

    normalized = normalize_akshare_index_daily(raw, "sh000001")

    assert normalized.loc[0, "index_code"] == "sh000001"
    assert normalized.loc[0, "trade_date"] == "2026-06-21"
    assert normalized.loc[0, "pct_chg"] == 0
    assert round(normalized.loc[1, "pct_chg"], 4) == round((3040 / 3010 - 1) * 100, 4)

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


def test_data_fetcher_relogs_and_retries_when_baostock_session_expires(monkeypatch) -> None:
    import sys

    from src.fetch_data import DataFetcher

    class LoginResult:
        error_code = "0"
        error_msg = ""

    class QueryResult:
        def __init__(self, error_code: str, error_msg: str, fields: list[str] | None = None, rows: list[list[str]] | None = None) -> None:
            self.error_code = error_code
            self.error_msg = error_msg
            self.fields = fields or []
            self._rows = rows or []
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
            self.query_count = 0

        def login(self) -> LoginResult:
            self.login_count += 1
            return LoginResult()

        def logout(self) -> None:
            self.logout_count += 1

        def query_history_k_data_plus(
            self,
            code: str,
            fields: str,
            start_date: str,
            end_date: str,
            frequency: str,
            adjustflag: str,
        ) -> QueryResult:
            self.query_count += 1
            if self.query_count < 3:
                return QueryResult("10002007", "\u7528\u6237\u672a\u767b\u5f55")
            return QueryResult(
                "0",
                "",
                ["date", "code", "open", "high", "low", "close", "volume", "amount", "turn", "pctChg"],
                [["2026-06-22", code, "10", "11", "9", "10.5", "1000", "105000", "1.2", "2.0"]],
            )

    fake = FakeBaostock()
    monkeypatch.setitem(sys.modules, "baostock", fake)

    fetcher = DataFetcher("2026-01-01")
    with fetcher:
        daily = fetcher.fetch_stock_daily("600000", end_date="2026-06-22")

    assert daily["code"].tolist() == ["600000"]
    assert fake.query_count == 3
    assert fake.login_count == 3
    assert fake.logout_count == 3


def test_data_fetcher_reconnects_after_configured_query_interval(monkeypatch) -> None:
    import sys

    from src.fetch_data import DataFetcher

    class LoginResult:
        error_code = "0"
        error_msg = ""

    class QueryResult:
        error_code = "0"
        error_msg = ""
        fields = ["code", "code_name", "ipoDate", "type", "status"]

        def __init__(self) -> None:
            self._rows = [["sh.600000", "PF Bank", "1999-11-10", "1", "1"]]
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
            self.query_count = 0

        def login(self) -> LoginResult:
            self.login_count += 1
            return LoginResult()

        def logout(self) -> None:
            self.logout_count += 1

        def query_stock_basic(self, code_name: str, code: str) -> QueryResult:
            self.query_count += 1
            return QueryResult()

    fake = FakeBaostock()
    monkeypatch.setitem(sys.modules, "baostock", fake)

    fetcher = DataFetcher("2026-01-01", reconnect_interval=2)
    with fetcher:
        fetcher.fetch_stock_basic()
        fetcher.fetch_stock_basic()
        fetcher.fetch_stock_basic()

    assert fake.query_count == 3
    assert fake.login_count == 2
    assert fake.logout_count == 2
