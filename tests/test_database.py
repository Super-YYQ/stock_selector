from pathlib import Path

import pandas as pd

from src.database import Database


def test_database_creates_core_tables(tmp_path: Path) -> None:
    db = Database(tmp_path / "stock.db")
    db.initialize()

    tables = db.list_tables()

    assert {
        "stock_basic",
        "stock_daily",
        "index_daily",
        "sector_daily",
        "run_metadata",
        "stock_sync_status",
        "selection_history",
        "run_history",
    } <= tables


def test_upsert_stock_daily_replaces_same_code_and_date(tmp_path: Path) -> None:
    db = Database(tmp_path / "stock.db")
    db.initialize()
    first = pd.DataFrame(
        [
            {
                "code": "600000",
                "trade_date": "2026-06-22",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10.5,
                "volume": 1000,
                "amount": 105000,
                "turnover_rate": 1.2,
                "pct_chg": 2.0,
                "is_suspended": False,
            }
        ]
    )
    second = first.assign(close=10.8, amount=108000)

    db.upsert_dataframe("stock_daily", first, ["code", "trade_date"])
    db.upsert_dataframe("stock_daily", second, ["code", "trade_date"])
    stored = db.read_table("stock_daily")

    assert len(stored) == 1
    assert stored.loc[0, "close"] == 10.8
    assert stored.loc[0, "amount"] == 108000


def test_mark_all_stocks_unlisted_allows_fresh_basic_list_to_reactivate(tmp_path: Path) -> None:
    db = Database(tmp_path / "stock.db")
    db.initialize()
    basic = pd.DataFrame(
        [
            {"code": "000001", "name": "A", "is_listed": 1},
            {"code": "000002", "name": "B", "is_listed": 1},
        ]
    )
    db.upsert_dataframe("stock_basic", basic, ["code"])

    db.mark_all_stocks_unlisted()
    db.upsert_dataframe("stock_basic", basic.iloc[[0]], ["code"])

    stored = db.read_table("stock_basic").set_index("code")
    assert stored.loc["000001", "is_listed"] == 1
    assert stored.loc["000002", "is_listed"] == 0


def test_selection_history_refreshes_forward_returns_and_performance(tmp_path: Path) -> None:
    db = Database(tmp_path / "stock.db")
    db.initialize()
    ranked = pd.DataFrame(
        [
            {
                "rank": 1,
                "code": "000001",
                "total_score": 88,
                "close": 10,
                "matched_strategies": "均线放量突破、RPS强势突破",
                "strategy_families": "breakout、trend",
            }
        ]
    )
    daily = pd.DataFrame(
        [
            {
                "code": "000001",
                "trade_date": f"2026-06-{day:02d}",
                "open": 10,
                "high": 10 + day / 10,
                "low": 9.8,
                "close": 10 + day / 10,
                "volume": 1000,
                "amount": 10000,
                "turnover_rate": 1,
                "pct_chg": 1,
                "is_suspended": 0,
            }
            for day in range(23, 33)
        ]
    )

    db.save_selections("2026-06-22", ranked)
    db.upsert_dataframe("stock_daily", daily, ["code", "trade_date"])
    updated = db.refresh_selection_returns()
    stored = db.read_table("selection_history")
    performance = db.strategy_performance()

    assert updated == 1
    assert stored.loc[0, "return_1d"] == 23
    assert stored.loc[0, "return_5d"] == 27
    assert len(performance) == 2
    assert set(performance["strategy"]) == {"均线放量突破", "RPS强势突破"}


def test_run_history_records_status(tmp_path: Path) -> None:
    db = Database(tmp_path / "stock.db")
    db.initialize()

    db.start_run("run-1", "daily", "2026-06-22")
    db.finish_run("run-1", "success", report_path="reports/report.xlsx")
    recent = db.recent_runs()

    assert recent.loc[0, "status"] == "success"
    assert recent.loc[0, "report_path"] == "reports/report.xlsx"
