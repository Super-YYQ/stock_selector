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
