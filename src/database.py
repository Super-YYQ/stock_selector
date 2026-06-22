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
