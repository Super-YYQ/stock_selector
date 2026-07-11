from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

import pandas as pd


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS stock_basic (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    exchange TEXT,
    industry TEXT,
    list_date TEXT,
    is_st INTEGER DEFAULT 0,
    is_listed INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS stock_daily (
    code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    amount REAL,
    turnover_rate REAL,
    pct_chg REAL,
    is_suspended INTEGER DEFAULT 0,
    PRIMARY KEY (code, trade_date)
);

CREATE TABLE IF NOT EXISTS index_daily (
    index_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    amount REAL,
    pct_chg REAL,
    PRIMARY KEY (index_code, trade_date)
);

CREATE TABLE IF NOT EXISTS sector_daily (
    sector_name TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    pct_chg REAL,
    pct_chg_5d REAL,
    pct_chg_20d REAL,
    amount REAL,
    amount_ratio REAL,
    limit_up_count INTEGER,
    strong_stock_count INTEGER,
    consecutive_strong_days INTEGER,
    PRIMARY KEY (sector_name, trade_date)
);

CREATE TABLE IF NOT EXISTS run_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stock_sync_status (
    code TEXT NOT NULL,
    provider TEXT NOT NULL,
    price_basis TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    row_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (code, provider, price_basis, start_date)
);

CREATE INDEX IF NOT EXISTS idx_stock_daily_trade_date ON stock_daily(trade_date);
CREATE INDEX IF NOT EXISTS idx_stock_sync_lookup
ON stock_sync_status(provider, price_basis, start_date, end_date);
"""


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)
            conn.commit()

    def list_tables(self) -> set[str]:
        with self.connect() as conn:
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        return {row["name"] for row in rows}

    def upsert_dataframe(self, table: str, df: pd.DataFrame, key_columns: Iterable[str]) -> int:
        if df.empty:
            return 0
        keys = list(key_columns)
        columns = list(df.columns)
        missing = [column for column in keys if column not in columns]
        if missing:
            raise ValueError(f"missing key columns for {table}: {missing}")
        value_marks = ", ".join(["?"] * len(columns))
        column_sql = ", ".join(columns)
        update_columns = [column for column in columns if column not in keys]
        update_sql = ", ".join([f"{column}=excluded.{column}" for column in update_columns])
        conflict_sql = ", ".join(keys)
        sql = (
            f"INSERT INTO {table} ({column_sql}) VALUES ({value_marks}) "
            f"ON CONFLICT ({conflict_sql}) DO UPDATE SET {update_sql}"
        )
        records = df.where(pd.notna(df), None).to_records(index=False).tolist()
        with self.connect() as conn:
            conn.executemany(sql, records)
            conn.commit()
        return len(records)

    def read_table(self, table: str) -> pd.DataFrame:
        with self.connect() as conn:
            return pd.read_sql_query(f"SELECT * FROM {table}", conn)

    def mark_all_stocks_unlisted(self) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE stock_basic SET is_listed = 0")
            conn.commit()

    def latest_dates(self, table: str, key_column: str, date_column: str = "trade_date") -> dict[str, str]:
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT {key_column}, MAX({date_column}) AS latest_date FROM {table} GROUP BY {key_column}"
            ).fetchall()
        return {
            str(row[key_column]): str(row["latest_date"])
            for row in rows
            if row[key_column] is not None and row["latest_date"] is not None
        }

    def read_table_between(self, table: str, date_column: str, start_date: str, end_date: str) -> pd.DataFrame:
        with self.connect() as conn:
            return pd.read_sql_query(
                f"SELECT * FROM {table} WHERE {date_column} >= ? AND {date_column} <= ?",
                conn,
                params=(start_date, end_date),
            )

    def get_synced_codes(
        self,
        provider: str,
        price_basis: str,
        start_date: str,
        end_date: str | None = None,
    ) -> set[str]:
        sql = """
            SELECT code
            FROM stock_sync_status
            WHERE provider = ? AND price_basis = ? AND start_date = ?
        """
        params: list[object] = [provider, price_basis, start_date]
        if end_date is not None:
            sql += " AND end_date >= ?"
            params.append(end_date)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return {str(row["code"]) for row in rows}

    def data_health(self) -> dict[str, object]:
        with self.connect() as conn:
            active_symbols = int(
                conn.execute("SELECT COUNT(*) FROM stock_basic WHERE COALESCE(is_listed, 1) = 1").fetchone()[0]
            )
            covered_symbols = int(
                conn.execute(
                    """
                    SELECT COUNT(DISTINCT d.code)
                    FROM stock_daily d
                    JOIN stock_basic b ON b.code = d.code
                    WHERE COALESCE(b.is_listed, 1) = 1
                    """
                ).fetchone()[0]
            )
            daily_rows = int(conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0])
            index_symbols = int(conn.execute("SELECT COUNT(DISTINCT index_code) FROM index_daily").fetchone()[0])
            latest_trade_date = conn.execute("SELECT MAX(trade_date) FROM stock_daily").fetchone()[0]
            latest_symbol_count = 0
            if latest_trade_date:
                latest_symbol_count = int(
                    conn.execute(
                        "SELECT COUNT(DISTINCT code) FROM stock_daily WHERE trade_date = ?",
                        (latest_trade_date,),
                    ).fetchone()[0]
                )
        coverage = covered_symbols / active_symbols if active_symbols else 0.0
        return {
            "active_symbols": active_symbols,
            "covered_symbols": covered_symbols,
            "stock_coverage": coverage,
            "daily_rows": daily_rows,
            "index_symbols": index_symbols,
            "latest_trade_date": latest_trade_date,
            "latest_symbol_count": latest_symbol_count,
        }
