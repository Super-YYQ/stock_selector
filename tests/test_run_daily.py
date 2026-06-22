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

    def fetch_stock_daily(self, code: str, end_date: str | None = None) -> pd.DataFrame:
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

    def fetch_index_daily(self, index_code: str, end_date: str | None = None) -> pd.DataFrame:
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

    update_market_data(db, config, "2026-06-22", init=True, fetcher=FakeFetcher())

    assert db.read_table("stock_basic")["code"].tolist() == ["000001"]
    assert db.read_table("stock_daily")["code"].tolist() == ["000001"]
    assert set(db.read_table("index_daily")["index_code"]) == {"sh000001", "sz399001", "sz399006"}
    assert db.read_table("sector_daily")["sector_name"].tolist() == ["银行"]
