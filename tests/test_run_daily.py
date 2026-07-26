from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from src.config import AppConfig, DataConfig
from src.fetch_data import TDX_PRICE_BASIS
from src.database import Database
from src.run_lock import RunAlreadyLockedError, SingleInstanceRunLock
from src.run_daily import (
    MarketSessionProbe,
    _is_automatic_online_run,
    _next_fetch_start,
    _requires_current_market_data,
    parse_args,
    probe_market_session,
    resolve_report_date,
    resolve_snapshot_type,
    summarize_run_error,
    update_market_data,
    validate_expected_market_data,
    validate_initialization,
    validate_latest_coverage,
)


def test_parse_args_supports_init_date_offline_and_snapshot() -> None:
    args = parse_args(["--init", "--date", "2026-06-22", "--offline", "--snapshot", "intraday"])

    assert args.init is True
    assert args.date == "2026-06-22"
    assert args.offline is True
    assert args.snapshot == "intraday"


def test_explicit_offline_history_run_does_not_require_current_market_data() -> None:
    args = parse_args(["--date", "2026-06-22", "--offline"])

    assert _is_automatic_online_run(args) is False
    assert _requires_current_market_data(args, "2026-06-22") is False


def test_resolve_report_date_uses_requested_date() -> None:
    assert resolve_report_date("2026-06-22", "2026-06-21") == "2026-06-22"


def test_snapshot_type_auto_detects_intraday_and_post_market() -> None:
    assert resolve_snapshot_type("auto", "2026-06-22", datetime(2026, 6, 22, 12, 30)) == "intraday"
    assert resolve_snapshot_type("auto", "2026-06-22", datetime(2026, 6, 22, 17, 30)) == "close"
    assert resolve_snapshot_type("auto", "2026-06-21", datetime(2026, 6, 22, 12, 30)) == "close"


def test_current_day_refresh_reuses_latest_date() -> None:
    assert _next_fetch_start("2026-06-22", "2023-01-01", refresh_date="2026-06-22") == "2026-06-22"
    assert _next_fetch_start("2026-06-22", "2023-01-01") == "2026-06-23"


def test_validate_latest_coverage_rejects_partial_snapshot() -> None:
    with pytest.raises(RuntimeError, match="latest trading-day"):
        validate_latest_coverage({"latest_stock_coverage": 0.75}, 0.98)


def test_summarize_run_error_translates_tdx_connection_failure() -> None:
    summary = summarize_run_error(
        RuntimeError("all configured TDX hosts failed: first: other errors | second: other errors")
    )

    assert summary == "TDX 行情服务器暂时无法连接（已尝试全部节点），本次未更新数据，请稍后重试。"


def test_market_session_probe_skips_weekends_without_opening_provider() -> None:
    probe = probe_market_session(
        AppConfig(),
        "2026-06-20",
        now=datetime(2026, 6, 20, 12, 30),
    )

    assert probe.state == "closed"
    assert "周末" in probe.message


def test_validate_initialization_rejects_incomplete_market_data(tmp_path: Path) -> None:
    db = Database(tmp_path / "stock.db")
    db.initialize()
    config = AppConfig(
        data=DataConfig(
            database=str(tmp_path / "stock.db"),
            init_min_stock_coverage=0.9,
            init_min_daily_rows=2,
            init_min_index_count=3,
        )
    )
    db.upsert_dataframe(
        "stock_basic",
        pd.DataFrame(
            [
                {"code": "000001", "name": "A", "is_listed": 1},
                {"code": "000002", "name": "B", "is_listed": 1},
            ]
        ),
        ["code"],
    )
    db.upsert_dataframe(
        "stock_daily",
        pd.DataFrame([{"code": "000001", "trade_date": "2026-06-22", "close": 10.0}]),
        ["code", "trade_date"],
    )

    with pytest.raises(RuntimeError, match="initialization data validation failed"):
        validate_initialization(db, config)


def _seed_market_date(
    db: Database,
    trade_date: str,
    *,
    active_codes: tuple[str, ...] = ("000001", "000002"),
    daily_codes: tuple[str, ...] | None = None,
    index_codes: tuple[str, ...] = ("sh000001", "sz399001", "sz399006"),
) -> None:
    db.upsert_dataframe(
        "stock_basic",
        pd.DataFrame(
            [
                {
                    "code": code,
                    "name": code,
                    "list_date": "2020-01-01",
                    "is_listed": 1,
                }
                for code in active_codes
            ]
        ),
        ["code"],
    )
    selected_daily_codes = active_codes if daily_codes is None else daily_codes
    if selected_daily_codes:
        db.upsert_dataframe(
            "stock_daily",
            pd.DataFrame(
                [
                    {"code": code, "trade_date": trade_date, "close": 10.0}
                    for code in selected_daily_codes
                ]
            ),
            ["code", "trade_date"],
        )
    if index_codes:
        db.upsert_dataframe(
            "index_daily",
            pd.DataFrame(
                [
                    {"index_code": code, "trade_date": trade_date, "close": 3000.0}
                    for code in index_codes
                ]
            ),
            ["index_code", "trade_date"],
        )


def test_expected_market_data_rejects_incomplete_stock_coverage(tmp_path: Path) -> None:
    db = Database(tmp_path / "stock.db")
    db.initialize()
    _seed_market_date(
        db,
        "2026-06-22",
        active_codes=("000001", "000002", "000003", "000004"),
        daily_codes=("000001", "000002"),
    )

    with pytest.raises(RuntimeError, match="数据库当日股票覆盖率"):
        validate_expected_market_data(db, "2026-06-22", 0.90)


def test_expected_market_data_requires_all_three_indexes(tmp_path: Path) -> None:
    db = Database(tmp_path / "stock.db")
    db.initialize()
    _seed_market_date(
        db,
        "2026-06-22",
        index_codes=("sh000001", "sz399001"),
    )

    with pytest.raises(RuntimeError, match="sz399006"):
        validate_expected_market_data(db, "2026-06-22", 0.90)


def test_later_listed_stock_does_not_reduce_historical_date_coverage(tmp_path: Path) -> None:
    db = Database(tmp_path / "stock.db")
    db.initialize()
    db.upsert_dataframe(
        "stock_basic",
        pd.DataFrame(
            [
                {
                    "code": "000001",
                    "name": "当时已上市",
                    "list_date": "2020-01-01",
                    "is_listed": 1,
                },
                {
                    "code": "000002",
                    "name": "后来上市",
                    "list_date": "2026-07-01",
                    "is_listed": 1,
                },
            ]
        ),
        ["code"],
    )
    db.upsert_dataframe(
        "stock_daily",
        pd.DataFrame(
            [{"code": "000001", "trade_date": "2026-06-22", "close": 10.0}]
        ),
        ["code", "trade_date"],
    )
    db.upsert_dataframe(
        "index_daily",
        pd.DataFrame(
            [
                {"index_code": code, "trade_date": "2026-06-22", "close": 3000.0}
                for code in ("sh000001", "sz399001", "sz399006")
            ]
        ),
        ["index_code", "trade_date"],
    )

    result = validate_expected_market_data(db, "2026-06-22", 1.0)

    assert result["active_symbols"] == 1
    assert result["current_symbols"] == 1
    assert result["stock_coverage"] == 1.0


def test_current_online_validation_requires_fresh_rows_from_this_run(tmp_path: Path) -> None:
    db = Database(tmp_path / "stock.db")
    db.initialize()
    _seed_market_date(db, "2026-06-22")

    with pytest.raises(RuntimeError, match="本次抓取当日股票覆盖率"):
        validate_expected_market_data(
            db,
            "2026-06-22",
            0.90,
            {"fresh_stock_symbols": 1, "fresh_index_symbols": 3},
        )

    result = validate_expected_market_data(
        db,
        "2026-06-22",
        0.90,
        {"fresh_stock_symbols": 2, "fresh_index_symbols": 3},
    )
    assert result["stock_coverage"] == 1.0
    assert result["index_codes"] == ["sh000001", "sz399001", "sz399006"]


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


def test_market_session_probe_recognizes_weekday_exchange_closure() -> None:
    class ClosedFetcher(FakeFetcher):
        def fetch_index_daily(
            self,
            index_code: str,
            start_date: str | None = None,
            end_date: str | None = None,
        ) -> pd.DataFrame:
            self.index_daily_calls.append(
                {"index_code": index_code, "start_date": start_date, "end_date": end_date}
            )
            return pd.DataFrame()

    fetcher = ClosedFetcher()
    probe = probe_market_session(
        AppConfig(),
        "2026-06-22",
        now=datetime(2026, 6, 22, 12, 30),
        fetcher=fetcher,
    )

    assert probe.state == "closed"
    assert len(fetcher.index_daily_calls) == 3


def test_market_session_probe_confirms_trading_day_from_index_bar() -> None:
    fetcher = FakeFetcher()

    probe = probe_market_session(
        AppConfig(),
        "2026-06-22",
        now=datetime(2026, 6, 22, 12, 30),
        fetcher=fetcher,
    )

    assert probe.state == "trading"
    assert "3 个主要指数" in probe.message


def test_market_session_probe_keeps_provider_errors_unknown() -> None:
    class FailingFetcher(FakeFetcher):
        def fetch_index_daily(
            self,
            index_code: str,
            start_date: str | None = None,
            end_date: str | None = None,
        ) -> pd.DataFrame:
            raise RuntimeError("network unavailable")

    probe = probe_market_session(
        AppConfig(),
        "2026-06-22",
        now=datetime(2026, 6, 22, 12, 30),
        fetcher=FailingFetcher(),
    )

    assert probe.state == "unknown"
    assert "network unavailable" in probe.message


def test_update_market_data_writes_fetched_tables(tmp_path: Path) -> None:
    db = Database(tmp_path / "stock.db")
    db.initialize()
    config = AppConfig(data=DataConfig(database=str(tmp_path / "stock.db")))
    fetcher = FakeFetcher()

    counts = update_market_data(db, config, "2026-06-22", init=True, fetcher=fetcher)

    assert db.read_table("stock_basic")["code"].tolist() == ["000001"]
    assert db.read_table("stock_daily")["code"].tolist() == ["000001"]
    assert set(db.read_table("index_daily")["index_code"]) == {"sh000001", "sz399001", "sz399006"}
    assert db.read_table("sector_daily")["sector_name"].tolist() == ["银行"]
    assert fetcher.stock_daily_calls[0]["start_date"] == config.data.start_date
    assert counts["fresh_stock_symbols"] == 1
    assert counts["fresh_index_symbols"] == 3



def test_init_falls_back_to_tdx_when_baostock_login_is_blacklisted(tmp_path: Path, monkeypatch) -> None:
    import src.run_daily as run_daily_module

    db = Database(tmp_path / "stock.db")
    db.initialize()
    config = AppConfig(
        data=DataConfig(
            database=str(tmp_path / "stock.db"),
            provider="mixed",
            tdx_parallel_workers=1,
            baostock_parallel_workers=1,
        )
    )

    class BlacklistedBaostockFetcher:
        def __enter__(self):
            raise RuntimeError("baostock login failed: blacklist user")

        def __exit__(self, exc_type, exc, traceback) -> None:
            pass

    fallback = FakeFetcher()

    monkeypatch.setattr(run_daily_module, "DataFetcher", lambda *args, **kwargs: BlacklistedBaostockFetcher())
    monkeypatch.setattr(run_daily_module, "TdxDataFetcher", lambda *args, **kwargs: fallback, raising=False)

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
            provider="baostock",
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
            provider="baostock",
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
            provider="baostock",
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


def test_tdx_init_parallel_fetch_marks_full_refresh_for_resume(tmp_path: Path, monkeypatch) -> None:
    import src.run_daily as run_daily_module

    db = Database(tmp_path / "stock.db")
    db.initialize()
    config = AppConfig(
        data=DataConfig(
            database=str(tmp_path / "stock.db"),
            provider="tdx",
            start_date="2023-01-01",
            tdx_parallel_workers=2,
            tdx_parallel_chunk_size=10,
        )
    )

    class TdxBasicFetcher(FakeFetcher):
        def fetch_stock_basic(self) -> pd.DataFrame:
            rows = []
            for code, name, exchange in [("000001", "A", "sz"), ("920001", "B", "bj")]:
                rows.append(
                    {
                        "code": code,
                        "name": name,
                        "exchange": exchange,
                        "industry": "",
                        "list_date": "",
                        "is_st": 0,
                        "is_listed": 1,
                    }
                )
            return pd.DataFrame(rows)

    captured: dict[str, object] = {}

    def fake_tdx_parallel(tasks, workers, chunk_size, timeout_seconds, query_retries):
        captured["tasks"] = tasks
        captured["workers"] = workers
        captured["chunk_size"] = chunk_size
        yield (
            pd.DataFrame(
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
                        "turnover_rate": None,
                        "pct_chg": 2.0,
                        "is_suspended": False,
                    }
                    for code, _start_date, end_date in tasks
                ]
            ),
            [],
            len(tasks),
        )

    monkeypatch.setattr(run_daily_module, "TdxDataFetcher", lambda *args, **kwargs: TdxBasicFetcher())
    monkeypatch.setattr(run_daily_module, "fetch_tdx_stock_daily_parallel", fake_tdx_parallel)

    counts = run_daily_module.update_market_data(db, config, "2026-06-23", init=True)

    assert counts["stock_daily"] == 2
    assert captured["workers"] == 2
    assert captured["chunk_size"] == 10
    assert captured["tasks"] == [
        ("000001", "2023-01-01", "2026-06-23"),
        ("920001", "2023-01-01", "2026-06-23"),
    ]
    assert db.get_synced_codes("tdx", TDX_PRICE_BASIS, "2023-01-01", "2026-06-23") == {
        "000001",
        "920001",
    }

    run_daily_module.update_market_data(db, config, "2026-06-24", init=True)

    assert captured["tasks"] == [
        ("000001", "2026-06-24", "2026-06-24"),
        ("920001", "2026-06-24", "2026-06-24"),
    ]
    assert db.get_synced_codes("tdx", TDX_PRICE_BASIS, "2023-01-01", "2026-06-24") == {
        "000001",
        "920001",
    }


def test_run_records_exchange_closure_as_skipped(tmp_path: Path, monkeypatch) -> None:
    import src.run_daily as run_daily_module

    db_path = tmp_path / "stock.db"
    config = AppConfig(data=DataConfig(database=str(db_path)))
    lock_path = tmp_path / "run_daily.lock"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_daily_module, "RUN_LOCK_PATH", lock_path)
    monkeypatch.setattr(run_daily_module, "load_config", lambda: config)
    monkeypatch.setattr(
        run_daily_module,
        "probe_market_session",
        lambda *_args, **_kwargs: MarketSessionProbe("closed", "测试日期为休市日"),
    )

    assert run_daily_module.run([]) is None

    latest = Database(db_path).recent_runs(1).iloc[0]
    assert latest["status"] == "skipped"
    assert "休市日" in latest["message"]
    assert not lock_path.exists()
    assert not (tmp_path / "reports").exists()


def test_run_lock_is_acquired_before_config_or_database_work(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import src.run_daily as run_daily_module

    lock_path = tmp_path / "run_daily.lock"
    config_loaded = False

    def unexpected_config_load() -> AppConfig:
        nonlocal config_loaded
        config_loaded = True
        return AppConfig()

    monkeypatch.setattr(run_daily_module, "RUN_LOCK_PATH", lock_path)
    monkeypatch.setattr(run_daily_module, "load_config", unexpected_config_load)

    with SingleInstanceRunLock(lock_path):
        with pytest.raises(RunAlreadyLockedError, match="已有选股任务正在执行"):
            run_daily_module.run([])

    assert config_loaded is False


def test_explicit_future_offline_date_is_rejected_instead_of_reusing_old_data(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import src.run_daily as run_daily_module

    db_path = tmp_path / "stock.db"
    db = Database(db_path)
    db.initialize()
    prior_date = (date.today() - timedelta(days=1)).isoformat()
    future_date = (date.today() + timedelta(days=30)).isoformat()
    _seed_market_date(db, prior_date)
    config = AppConfig(
        data=DataConfig(
            database=str(db_path),
            min_latest_stock_coverage=0.90,
        )
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_daily_module, "RUN_LOCK_PATH", tmp_path / "run_daily.lock")
    monkeypatch.setattr(run_daily_module, "load_config", lambda: config)

    with pytest.raises(RuntimeError, match=f"{future_date} 当日行情校验失败"):
        run_daily_module.run(["--date", future_date, "--offline"])

    latest = db.recent_runs(1).iloc[0]
    assert latest["status"] == "failed"
    assert latest["report_date"] == future_date
    assert not (tmp_path / "reports").exists()


def test_online_run_fails_closed_when_refresh_does_not_fetch_current_session(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import src.run_daily as run_daily_module

    db_path = tmp_path / "stock.db"
    db = Database(db_path)
    db.initialize()
    prior_date = (date.today() - timedelta(days=1)).isoformat()
    _seed_market_date(db, prior_date)
    config = AppConfig(
        data=DataConfig(
            database=str(db_path),
            min_latest_stock_coverage=0.90,
        )
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_daily_module, "RUN_LOCK_PATH", tmp_path / "run_daily.lock")
    monkeypatch.setattr(run_daily_module, "load_config", lambda: config)
    monkeypatch.setattr(
        run_daily_module,
        "probe_market_session",
        lambda *_args, **_kwargs: MarketSessionProbe("trading", "测试交易日"),
    )
    monkeypatch.setattr(
        run_daily_module,
        "update_market_data",
        lambda *_args, **_kwargs: {
            "fresh_stock_symbols": 0,
            "fresh_index_symbols": 0,
        },
    )

    with pytest.raises(RuntimeError, match="已阻止使用旧数据生成报告"):
        run_daily_module.run([])

    latest = db.recent_runs(1).iloc[0]
    assert latest["status"] == "failed"
    assert latest["report_date"] == date.today().isoformat()
    assert not (tmp_path / "reports").exists()
