from pathlib import Path

import pandas as pd

from src.config import AppConfig, DataConfig
from src.database import Database
from src.run_daily import parse_args, resolve_report_date, update_market_data


def test_parse_args_supports_init_and_date() -> None:
    args = parse_args(["--init", "--date", "2026-06-22"])

    assert args.init is True
    assert args.date == "2026-06-22"


def test_resolve_report_date_uses_requested_date() -> None:
    assert resolve_report_date("2026-06-22", "2026-06-21") == "2026-06-22"


class FakeFetcher:
    def __init__(self) -> None:
        self.stock_daily_calls: list[dict[str, str | None]] = []
        self.index_daily_calls: list[dict[str, str | None]] = []

    def fetch_stock_basic(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "code": "000001",
                    "name": "平安银行",
                    "exchange": "sz",
                    "industry": "银行",
                    "list_date": "1991-04-03",
                    "is_st": 0,
                    "is_listed": 1,
                }
            ]
        )

    def fetch_stock_daily(self, code: str, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        self.stock_daily_calls.append({"code": code, "start_date": start_date, "end_date": end_date})
        return pd.DataFrame(
            [
                {
                    "code": code,
                    "trade_date": end_date,
                    "open": 10,
                    "high": 11,
                    "low": 9,
                    "close": 10.5,
                    "volume": 1000,
                    "amount": 150000000,
                    "turnover_rate": 1.2,
                    "pct_chg": 2.0,
                    "is_suspended": False,
                }
            ]
        )

    def fetch_index_daily(self, index_code: str, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        self.index_daily_calls.append({"index_code": index_code, "start_date": start_date, "end_date": end_date})
        return pd.DataFrame(
            [
                {
                    "index_code": index_code,
                    "trade_date": end_date,
                    "open": 3000,
                    "high": 3020,
                    "low": 2990,
                    "close": 3010,
                    "volume": 100,
                    "amount": 200,
                    "pct_chg": 0.5,
                }
            ]
        )

    def fetch_sector_daily(self, trade_date: str) -> pd.DataFrame:
        return pd.DataFrame([{"sector_name": "银行", "trade_date": trade_date, "pct_chg": 1.2, "amount": 1000}])


def test_update_market_data_writes_fetched_tables(tmp_path: Path) -> None:
    db = Database(tmp_path / "stock.db")
    db.initialize()
    config = AppConfig(data=DataConfig(database=str(tmp_path / "stock.db")))
    fetcher = FakeFetcher()

    update_market_data(db, config, "2026-06-22", init=True, fetcher=fetcher)

    assert db.read_table("stock_basic")["code"].tolist() == ["000001"]
    assert db.read_table("stock_daily")["code"].tolist() == ["000001"]
    assert set(db.read_table("index_daily")["index_code"]) == {"sh000001", "sz399001", "sz399006"}
    assert db.read_table("sector_daily")["sector_name"].tolist() == ["银行"]
    assert fetcher.stock_daily_calls[0]["start_date"] == config.data.start_date



def test_init_falls_back_to_akshare_when_baostock_login_is_blacklisted(tmp_path: Path, monkeypatch) -> None:
    import src.run_daily as run_daily_module

    db = Database(tmp_path / "stock.db")
    db.initialize()
    config = AppConfig(data=DataConfig(database=str(tmp_path / "stock.db"), baostock_parallel_workers=1))

    class BlacklistedBaostockFetcher:
        def __enter__(self):
            raise RuntimeError("baostock login failed: blacklist user")

        def __exit__(self, exc_type, exc, traceback) -> None:
            pass

    fallback = FakeFetcher()

    monkeypatch.setattr(run_daily_module, "DataFetcher", lambda *args, **kwargs: BlacklistedBaostockFetcher())
    monkeypatch.setattr(run_daily_module, "AkshareDataFetcher", lambda *args, **kwargs: fallback, raising=False)

    counts = run_daily_module.update_market_data(db, config, "2026-06-22", init=True)

    assert counts["stock_basic"] == 1
    assert db.read_table("stock_daily")["code"].tolist() == ["000001"]
    assert fallback.stock_daily_calls == [{"code": "000001", "start_date": config.data.start_date, "end_date": "2026-06-22"}]

def test_update_market_data_fetches_incrementally_after_existing_daily_rows(tmp_path: Path) -> None:
    db = Database(tmp_path / "stock.db")
    db.initialize()
    config = AppConfig(data=DataConfig(database=str(tmp_path / "stock.db"), start_date="2023-01-01"))
    db.upsert_dataframe(
        "stock_basic",
        pd.DataFrame(
            [
                {
                    "code": "000001",
                    "name": "平安银行",
                    "exchange": "sz",
                    "industry": "银行",
                    "list_date": "1991-04-03",
                    "is_st": 0,
                    "is_listed": 1,
                }
            ]
        ),
        ["code"],
    )
    db.upsert_dataframe(
        "stock_daily",
        pd.DataFrame(
            [
                {
                    "code": "000001",
                    "trade_date": "2026-06-20",
                    "open": 10,
                    "high": 11,
                    "low": 9,
                    "close": 10.5,
                    "volume": 1000,
                    "amount": 150000000,
                    "turnover_rate": 1.2,
                    "pct_chg": 2.0,
                    "is_suspended": False,
                }
            ]
        ),
        ["code", "trade_date"],
    )
    db.upsert_dataframe(
        "index_daily",
        pd.DataFrame(
            [
                {
                    "index_code": "sh000001",
                    "trade_date": "2026-06-20",
                    "open": 3000,
                    "high": 3020,
                    "low": 2990,
                    "close": 3010,
                    "volume": 100,
                    "amount": 200,
                    "pct_chg": 0.5,
                }
            ]
        ),
        ["index_code", "trade_date"],
    )
    fetcher = FakeFetcher()

    update_market_data(db, config, "2026-06-23", init=False, fetcher=fetcher)

    assert fetcher.stock_daily_calls == [{"code": "000001", "start_date": "2026-06-21", "end_date": "2026-06-23"}]
    assert {call["index_code"]: call["start_date"] for call in fetcher.index_daily_calls}["sh000001"] == "2026-06-21"
    assert {call["index_code"]: call["start_date"] for call in fetcher.index_daily_calls}["sz399001"] == "2023-01-01"


def test_init_uses_existing_stock_basic_when_remote_basic_fetch_fails(tmp_path: Path) -> None:
    db = Database(tmp_path / "stock.db")
    db.initialize()
    config = AppConfig(data=DataConfig(database=str(tmp_path / "stock.db"), start_date="2023-01-01"))
    db.upsert_dataframe(
        "stock_basic",
        pd.DataFrame(
            [
                {
                    "code": "000001",
                    "name": "Ping An Bank",
                    "exchange": "sz",
                    "industry": "Bank",
                    "list_date": "1991-04-03",
                    "is_st": 0,
                    "is_listed": 1,
                }
            ]
        ),
        ["code"],
    )

    class BasicFailingFetcher(FakeFetcher):
        def fetch_stock_basic(self) -> pd.DataFrame:
            raise RuntimeError("baostock stock basic query failed: user not logged in")

    fetcher = BasicFailingFetcher()

    counts = update_market_data(db, config, "2026-06-22", init=True, fetcher=fetcher)

    assert counts["stock_basic"] == 0
    assert db.read_table("stock_daily")["code"].tolist() == ["000001"]
    assert fetcher.stock_daily_calls == [{"code": "000001", "start_date": "2023-01-01", "end_date": "2026-06-22"}]


def test_init_resumes_existing_stock_daily_rows(tmp_path: Path) -> None:
    db = Database(tmp_path / "stock.db")
    db.initialize()
    config = AppConfig(data=DataConfig(database=str(tmp_path / "stock.db"), start_date="2023-01-01"))
    db.upsert_dataframe(
        "stock_daily",
        pd.DataFrame(
            [
                {
                    "code": "000001",
                    "trade_date": "2026-06-20",
                    "open": 10,
                    "high": 11,
                    "low": 9,
                    "close": 10.5,
                    "volume": 1000,
                    "amount": 150000000,
                    "turnover_rate": 1.2,
                    "pct_chg": 2.0,
                    "is_suspended": False,
                }
            ]
        ),
        ["code", "trade_date"],
    )
    fetcher = FakeFetcher()

    update_market_data(db, config, "2026-06-23", init=True, fetcher=fetcher)

    assert fetcher.stock_daily_calls == [{"code": "000001", "start_date": "2026-06-21", "end_date": "2026-06-23"}]


def test_init_uses_parallel_stock_daily_fetcher_when_configured(tmp_path: Path, monkeypatch) -> None:
    import src.run_daily as run_daily_module

    db = Database(tmp_path / "stock.db")
    db.initialize()
    config = AppConfig(
        data=DataConfig(
            database=str(tmp_path / "stock.db"),
            start_date="2023-01-01",
            baostock_parallel_workers=2,
            baostock_parallel_chunk_size=7,
        )
    )

    class BasicOnlyFetcher(FakeFetcher):
        def fetch_stock_basic(self) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "code": "000001",
                        "name": "Ping An Bank",
                        "exchange": "sz",
                        "industry": "Bank",
                        "list_date": "1991-04-03",
                        "is_st": 0,
                        "is_listed": 1,
                    },
                    {
                        "code": "600000",
                        "name": "PF Bank",
                        "exchange": "sh",
                        "industry": "Bank",
                        "list_date": "1999-11-10",
                        "is_st": 0,
                        "is_listed": 1,
                    },
                ]
            )

        def fetch_stock_daily(self, code: str, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
            raise AssertionError("parallel init should not use sequential stock daily fetch")

    captured: dict[str, object] = {}

    def fake_parallel_fetch(tasks, workers, chunk_size, query_retries, reconnect_interval):
        captured["tasks"] = tasks
        captured["workers"] = workers
        captured["chunk_size"] = chunk_size
        captured["query_retries"] = query_retries
        captured["reconnect_interval"] = reconnect_interval
        yield (
            pd.DataFrame(
                [
                    {
                        "code": task[0],
                        "trade_date": task[2],
                        "open": 10,
                        "high": 11,
                        "low": 9,
                        "close": 10.5,
                        "volume": 1000,
                        "amount": 150000000,
                        "turnover_rate": 1.2,
                        "pct_chg": 2.0,
                        "is_suspended": False,
                    }
                    for task in tasks
                ]
            ),
            [],
            len(tasks),
        )

    monkeypatch.setattr(run_daily_module, "DataFetcher", lambda *args, **kwargs: BasicOnlyFetcher())
    monkeypatch.setattr(run_daily_module, "fetch_stock_daily_parallel", fake_parallel_fetch, raising=False)

    counts = run_daily_module.update_market_data(db, config, "2026-06-23", init=True)

    assert counts["stock_daily"] == 2
    assert captured["workers"] == 2
    assert captured["chunk_size"] == 7
    assert captured["tasks"] == [("000001", "2023-01-01", "2026-06-23"), ("600000", "2023-01-01", "2026-06-23")]
    assert set(db.read_table("stock_daily")["code"]) == {"000001", "600000"}


def test_parallel_stock_daily_failures_are_retried_sequentially(tmp_path: Path, monkeypatch) -> None:
    import src.run_daily as run_daily_module

    db = Database(tmp_path / "stock.db")
    db.initialize()
    config = AppConfig(
        data=DataConfig(
            database=str(tmp_path / "stock.db"),
            start_date="2023-01-01",
            baostock_parallel_workers=2,
            baostock_parallel_chunk_size=7,
        )
    )

    class RetryFetcher(FakeFetcher):
        def fetch_stock_basic(self) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "code": "000001",
                        "name": "Ping An Bank",
                        "exchange": "sz",
                        "industry": "Bank",
                        "list_date": "1991-04-03",
                        "is_st": 0,
                        "is_listed": 1,
                    },
                    {
                        "code": "600000",
                        "name": "PF Bank",
                        "exchange": "sh",
                        "industry": "Bank",
                        "list_date": "1999-11-10",
                        "is_st": 0,
                        "is_listed": 1,
                    },
                ]
            )

    def fake_parallel_fetch(tasks, workers, chunk_size, query_retries, reconnect_interval):
        yield (
            pd.DataFrame(
                [
                    {
                        "code": "000001",
                        "trade_date": "2026-06-23",
                        "open": 10,
                        "high": 11,
                        "low": 9,
                        "close": 10.5,
                        "volume": 1000,
                        "amount": 150000000,
                        "turnover_rate": 1.2,
                        "pct_chg": 2.0,
                        "is_suspended": False,
                    }
                ]
            ),
            [("600000", "baostock login failed: network receive error")],
            len(tasks),
        )

    created: dict[str, RetryFetcher] = {}

    def make_fetcher(*args, **kwargs):
        created["fetcher"] = RetryFetcher()
        return created["fetcher"]

    monkeypatch.setattr(run_daily_module, "DataFetcher", make_fetcher)
    monkeypatch.setattr(run_daily_module, "fetch_stock_daily_parallel", fake_parallel_fetch, raising=False)

    counts = run_daily_module.update_market_data(db, config, "2026-06-23", init=True)

    assert counts["failed_symbols"] == 0
    assert created["fetcher"].stock_daily_calls == [{"code": "600000", "start_date": "2023-01-01", "end_date": "2026-06-23"}]
    assert set(db.read_table("stock_daily")["code"]) == {"000001", "600000"}


def test_parallel_stock_daily_blacklist_failures_are_not_retried_immediately(tmp_path: Path, monkeypatch) -> None:
    import src.run_daily as run_daily_module

    db = Database(tmp_path / "stock.db")
    db.initialize()
    config = AppConfig(
        data=DataConfig(
            database=str(tmp_path / "stock.db"),
            start_date="2023-01-01",
            baostock_parallel_workers=2,
            baostock_parallel_chunk_size=7,
        )
    )

    class NoRetryFetcher(FakeFetcher):
        def fetch_stock_basic(self) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "code": "000001",
                        "name": "Ping An Bank",
                        "exchange": "sz",
                        "industry": "Bank",
                        "list_date": "1991-04-03",
                        "is_st": 0,
                        "is_listed": 1,
                    },
                    {
                        "code": "600000",
                        "name": "PF Bank",
                        "exchange": "sh",
                        "industry": "Bank",
                        "list_date": "1999-11-10",
                        "is_st": 0,
                        "is_listed": 1,
                    },
                ]
            )

        def fetch_stock_daily(self, code: str, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
            raise AssertionError("blacklist failures should not be retried immediately")

    def fake_parallel_fetch(tasks, workers, chunk_size, query_retries, reconnect_interval):
        yield (
            pd.DataFrame(
                [
                    {
                        "code": "000001",
                        "trade_date": "2026-06-23",
                        "open": 10,
                        "high": 11,
                        "low": 9,
                        "close": 10.5,
                        "volume": 1000,
                        "amount": 150000000,
                        "turnover_rate": 1.2,
                        "pct_chg": 2.0,
                        "is_suspended": False,
                    }
                ]
            ),
            [("600000", "blacklist user, contact administrator")],
            len(tasks),
        )

    monkeypatch.setattr(run_daily_module, "DataFetcher", lambda *args, **kwargs: NoRetryFetcher())
    monkeypatch.setattr(run_daily_module, "fetch_stock_daily_parallel", fake_parallel_fetch, raising=False)

    counts = run_daily_module.update_market_data(db, config, "2026-06-23", init=True)

    assert counts["failed_symbols"] == 1
    assert db.read_table("stock_daily")["code"].tolist() == ["000001"]
