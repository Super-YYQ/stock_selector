from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd


LOGGER = logging.getLogger(__name__)
SQLITE_BUSY_TIMEOUT_MS = 5_000
STOCK_DAILY_ROWS_KEY = "health.stock_daily_rows"
STOCK_DAILY_MAX_ROWID_KEY = "health.stock_daily_max_rowid"
STOCK_DAILY_ROWS_UPDATED_AT_KEY = "health.stock_daily_rows_updated_at"
STOCK_DAILY_HEALTH_KEYS = (
    STOCK_DAILY_ROWS_KEY,
    STOCK_DAILY_MAX_ROWID_KEY,
    STOCK_DAILY_ROWS_UPDATED_AT_KEY,
)


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

CREATE TABLE IF NOT EXISTS stock_context (
    code TEXT PRIMARY KEY,
    sector TEXT,
    industry TEXT,
    concepts TEXT,
    event_tags TEXT,
    source TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sector_context (
    sector_name TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    return_5d REAL,
    return_20d REAL,
    return_120d REAL,
    active_days_20 INTEGER,
    summary TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (sector_name, as_of_date)
);

CREATE TABLE IF NOT EXISTS stock_event (
    trade_date TEXT NOT NULL,
    code TEXT NOT NULL,
    event_type TEXT NOT NULL,
    summary TEXT,
    industry TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (trade_date, code, event_type)
);

CREATE TABLE IF NOT EXISTS selection_history (
    report_date TEXT NOT NULL,
    code TEXT NOT NULL,
    rank INTEGER NOT NULL,
    total_score REAL,
    close REAL,
    matched_strategies TEXT,
    strategy_families TEXT,
    return_1d REAL,
    return_3d REAL,
    return_5d REAL,
    return_10d REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (report_date, code)
);

CREATE TABLE IF NOT EXISTS run_history (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    mode TEXT NOT NULL,
    report_date TEXT,
    status TEXT NOT NULL,
    message TEXT,
    report_path TEXT,
    html_path TEXT,
    published_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_stock_daily_trade_date ON stock_daily(trade_date);
CREATE INDEX IF NOT EXISTS idx_selection_history_date ON selection_history(report_date);
CREATE INDEX IF NOT EXISTS idx_run_history_started_at ON run_history(started_at);
CREATE INDEX IF NOT EXISTS idx_stock_sync_lookup
ON stock_sync_status(provider, price_basis, start_date, end_date);
"""


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=SQLITE_BUSY_TIMEOUT_MS / 1_000)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
        return conn

    def initialize(self) -> None:
        with self.connect() as conn:
            try:
                conn.execute("PRAGMA journal_mode = WAL")
            except sqlite3.DatabaseError as exc:
                # Some network filesystems and read-only deployments cannot use WAL.
                # Keep the existing journal mode instead of preventing startup.
                LOGGER.warning("SQLite WAL mode is unavailable, keeping the current journal mode: %s", exc)
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
            if table == "stock_daily":
                marks = ", ".join(["?"] * len(STOCK_DAILY_HEALTH_KEYS))
                conn.execute(
                    f"DELETE FROM run_metadata WHERE key IN ({marks})",
                    STOCK_DAILY_HEALTH_KEYS,
                )
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

    @staticmethod
    def _metadata_values(conn: sqlite3.Connection, keys: tuple[str, ...]) -> dict[str, str]:
        marks = ", ".join(["?"] * len(keys))
        rows = conn.execute(
            f"SELECT key, value FROM run_metadata WHERE key IN ({marks})",
            keys,
        ).fetchall()
        return {str(row["key"]): str(row["value"]) for row in rows}

    @staticmethod
    def _active_symbol_count(conn: sqlite3.Connection, trade_date: str | None = None) -> int:
        date_filter = ""
        params: tuple[object, ...] = ()
        if trade_date is not None:
            date_filter = " AND d.trade_date = ?"
            params = (trade_date,)
        return int(
            conn.execute(
                f"""
                SELECT COUNT(*)
                FROM stock_basic b
                WHERE COALESCE(b.is_listed, 1) = 1
                  AND EXISTS (
                      SELECT 1
                      FROM stock_daily d
                      WHERE d.code = b.code{date_filter}
                  )
                """,
                params,
            ).fetchone()[0]
        )

    @staticmethod
    def _max_stock_daily_rowid(conn: sqlite3.Connection) -> int:
        return int(conn.execute("SELECT COALESCE(MAX(rowid), 0) FROM stock_daily").fetchone()[0])

    def _health_snapshot(self, *, exact_daily_rows: bool) -> dict[str, object]:
        with self.connect() as conn:
            active_symbols = int(
                conn.execute("SELECT COUNT(*) FROM stock_basic WHERE COALESCE(is_listed, 1) = 1").fetchone()[0]
            )
            covered_symbols = self._active_symbol_count(conn)
            current_max_rowid = self._max_stock_daily_rowid(conn)
            daily_rows_updated_at: str | None = None
            if exact_daily_rows:
                daily_rows = int(conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0])
                daily_rows_exact = True
                daily_rows_source = "exact_count"
                daily_rows_updated_at = datetime.now().isoformat(timespec="seconds")
                conn.executemany(
                    """
                    INSERT INTO run_metadata (key, value)
                    VALUES (?, ?)
                    ON CONFLICT (key) DO UPDATE SET value = excluded.value
                    """,
                    [
                        (STOCK_DAILY_ROWS_KEY, str(daily_rows)),
                        (STOCK_DAILY_MAX_ROWID_KEY, str(current_max_rowid)),
                        (STOCK_DAILY_ROWS_UPDATED_AT_KEY, daily_rows_updated_at),
                    ],
                )
            else:
                metadata = self._metadata_values(conn, STOCK_DAILY_HEALTH_KEYS)
                try:
                    cached_rows = int(metadata[STOCK_DAILY_ROWS_KEY])
                    cached_max_rowid = int(metadata[STOCK_DAILY_MAX_ROWID_KEY])
                except (KeyError, TypeError, ValueError):
                    cached_rows = -1
                    cached_max_rowid = -1
                if cached_rows >= 0 and cached_max_rowid == current_max_rowid:
                    daily_rows = cached_rows
                    daily_rows_exact = True
                    daily_rows_source = "metadata"
                    daily_rows_updated_at = metadata.get(STOCK_DAILY_ROWS_UPDATED_AT_KEY)
                else:
                    # MAX(rowid) is O(1) and is a useful display fallback, but it can
                    # over-count after deletions. It is never used for initialization
                    # validation and is explicitly labelled as an estimate.
                    daily_rows = current_max_rowid
                    daily_rows_exact = current_max_rowid == 0
                    daily_rows_source = "empty_table" if daily_rows_exact else "max_rowid_estimate"
            index_symbols = int(conn.execute("SELECT COUNT(DISTINCT index_code) FROM index_daily").fetchone()[0])
            latest_trade_date = conn.execute("SELECT MAX(trade_date) FROM stock_daily").fetchone()[0]
            latest_symbol_count = 0
            if latest_trade_date:
                latest_symbol_count = self._active_symbol_count(conn, str(latest_trade_date))
        coverage = covered_symbols / active_symbols if active_symbols else 0.0
        latest_coverage = latest_symbol_count / active_symbols if active_symbols else 0.0
        return {
            "active_symbols": active_symbols,
            "covered_symbols": covered_symbols,
            "stock_coverage": coverage,
            "daily_rows": daily_rows,
            "daily_rows_exact": daily_rows_exact,
            "daily_rows_source": daily_rows_source,
            "daily_rows_updated_at": daily_rows_updated_at,
            "index_symbols": index_symbols,
            "latest_trade_date": latest_trade_date,
            "latest_symbol_count": latest_symbol_count,
            "latest_stock_coverage": latest_coverage,
        }

    def data_health(self) -> dict[str, object]:
        """Return validation-grade health data and refresh the row-count metadata."""
        return self._health_snapshot(exact_daily_rows=True)

    def quick_data_health(self) -> dict[str, object]:
        """Return panel health without scanning every row in ``stock_daily``."""
        return self._health_snapshot(exact_daily_rows=False)

    def save_selections(self, report_date: str, ranked: pd.DataFrame, top_n: int = 50) -> int:
        selected = ranked.head(top_n).copy()
        now = datetime.now().isoformat(timespec="seconds")
        defaults: dict[str, object] = {
            "rank": 0,
            "total_score": 0.0,
            "close": 0.0,
            "matched_strategies": "",
            "strategy_families": "",
        }
        for column, default in defaults.items():
            if column not in selected.columns:
                selected[column] = default
        selected["report_date"] = report_date
        selected["created_at"] = now
        selected["updated_at"] = now
        columns = [
            "report_date",
            "code",
            "rank",
            "total_score",
            "close",
            "matched_strategies",
            "strategy_families",
            "created_at",
            "updated_at",
        ]
        records = (
            selected[columns].where(pd.notna(selected[columns]), None).to_records(index=False).tolist()
            if not selected.empty
            else []
        )
        marks = ", ".join(["?"] * len(columns))
        with self.connect() as conn:
            conn.execute("DELETE FROM selection_history WHERE report_date = ?", (report_date,))
            if records:
                conn.executemany(
                    f"INSERT INTO selection_history ({', '.join(columns)}) VALUES ({marks})",
                    records,
                )
            conn.commit()
        return len(records)

    def refresh_selection_returns(self) -> int:
        with self.connect() as conn:
            selections = pd.read_sql_query(
                """
                SELECT report_date, code, close
                FROM selection_history
                WHERE close IS NOT NULL AND close > 0
                """,
                conn,
            )
            if selections.empty:
                return 0
            daily = pd.read_sql_query(
                """
                SELECT code, trade_date, close
                FROM stock_daily
                WHERE trade_date > ?
                ORDER BY code, trade_date
                """,
                conn,
                params=(str(selections["report_date"].min()),),
            )
        if daily.empty:
            return 0

        grouped = {code: frame.reset_index(drop=True) for code, frame in daily.groupby("code", sort=False)}
        horizons = {1: "return_1d", 3: "return_3d", 5: "return_5d", 10: "return_10d"}
        updates: list[tuple[object, ...]] = []
        now = datetime.now().isoformat(timespec="seconds")
        for row in selections.itertuples(index=False):
            future = grouped.get(str(row.code))
            if future is None:
                continue
            future = future[future["trade_date"] > str(row.report_date)].head(10)
            values: dict[str, float | None] = {column: None for column in horizons.values()}
            for horizon, column in horizons.items():
                if len(future) >= horizon:
                    values[column] = round((float(future.iloc[horizon - 1]["close"]) / float(row.close) - 1) * 100, 4)
            if any(value is not None for value in values.values()):
                updates.append(
                    (
                        values["return_1d"],
                        values["return_3d"],
                        values["return_5d"],
                        values["return_10d"],
                        now,
                        str(row.report_date),
                        str(row.code),
                    )
                )
        if not updates:
            return 0
        with self.connect() as conn:
            conn.executemany(
                """
                UPDATE selection_history
                SET return_1d = COALESCE(?, return_1d),
                    return_3d = COALESCE(?, return_3d),
                    return_5d = COALESCE(?, return_5d),
                    return_10d = COALESCE(?, return_10d),
                    updated_at = ?
                WHERE report_date = ? AND code = ?
                """,
                updates,
            )
            conn.commit()
        return len(updates)

    def strategy_performance(self) -> pd.DataFrame:
        history = self.read_table("selection_history")
        columns = [
            "strategy",
            "sample_count",
            "return_1d",
            "win_rate_1d",
            "return_3d",
            "win_rate_3d",
            "return_5d",
            "win_rate_5d",
            "return_10d",
            "win_rate_10d",
        ]
        if history.empty:
            return pd.DataFrame(columns=columns)
        records: list[dict[str, object]] = []
        for row in history.itertuples(index=False):
            names = [name for name in str(row.matched_strategies or "").split("、") if name]
            for name in names:
                record = {"strategy": name}
                for horizon in (1, 3, 5, 10):
                    record[f"return_{horizon}d"] = getattr(row, f"return_{horizon}d")
                records.append(record)
        if not records:
            return pd.DataFrame(columns=columns)
        expanded = pd.DataFrame(records)
        rows: list[dict[str, object]] = []
        for strategy, group in expanded.groupby("strategy", sort=False):
            item: dict[str, object] = {"strategy": strategy, "sample_count": len(group)}
            for horizon in (1, 3, 5, 10):
                column = f"return_{horizon}d"
                values = pd.to_numeric(group[column], errors="coerce").dropna()
                item[column] = round(float(values.mean()), 2) if not values.empty else None
                item[f"win_rate_{horizon}d"] = round(float(values.gt(0).mean() * 100), 2) if not values.empty else None
            rows.append(item)
        return pd.DataFrame(rows, columns=columns).sort_values(
            ["return_5d", "sample_count"],
            ascending=[False, False],
            na_position="last",
        ).reset_index(drop=True)

    def start_run(self, run_id: str, mode: str, report_date: str | None) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        frame = pd.DataFrame(
            [
                {
                    "run_id": run_id,
                    "started_at": now,
                    "finished_at": None,
                    "mode": mode,
                    "report_date": report_date,
                    "status": "running",
                    "message": "",
                    "report_path": "",
                    "html_path": "",
                    "published_at": None,
                }
            ]
        )
        self.upsert_dataframe("run_history", frame, ["run_id"])

    def finish_run(
        self,
        run_id: str,
        status: str,
        *,
        report_date: str | None = None,
        message: str = "",
        report_path: str = "",
        html_path: str = "",
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE run_history
                SET finished_at = ?, status = ?, report_date = COALESCE(?, report_date),
                    message = ?, report_path = ?, html_path = ?
                WHERE run_id = ?
                """,
                (
                    datetime.now().isoformat(timespec="seconds"),
                    status,
                    report_date,
                    message,
                    report_path,
                    html_path,
                    run_id,
                ),
            )
            conn.commit()

    def recent_runs(self, limit: int = 20) -> pd.DataFrame:
        with self.connect() as conn:
            return pd.read_sql_query(
                """
                SELECT * FROM run_history
                ORDER BY started_at DESC
                LIMIT ?
                """,
                conn,
                params=(max(1, int(limit)),),
            )
