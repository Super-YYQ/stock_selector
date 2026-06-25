from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


BAOSTOCK_DAILY_COLUMNS = {
    "date": "trade_date",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "amount": "amount",
    "turn": "turnover_rate",
    "pctChg": "pct_chg",
}

BAOSTOCK_INDEX_COLUMNS = {
    "date": "trade_date",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "amount": "amount",
    "pctChg": "pct_chg",
}


def _strip_exchange(code: str) -> str:
    return code.split(".")[-1]


def _exchange(code: str) -> str:
    return code.split(".")[0] if "." in code else ("sh" if code.startswith(("6", "9")) else "sz")


def normalize_baostock_daily(raw: pd.DataFrame) -> pd.DataFrame:
    required = {"code", *BAOSTOCK_DAILY_COLUMNS.keys()}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"baostock daily missing columns: {sorted(missing)}")
    df = raw[["code", *BAOSTOCK_DAILY_COLUMNS.keys()]].rename(columns=BAOSTOCK_DAILY_COLUMNS)
    df["code"] = df["code"].astype(str).map(_strip_exchange)
    numeric_columns = ["open", "high", "low", "close", "volume", "amount", "turnover_rate", "pct_chg"]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df["is_suspended"] = df["volume"].fillna(0).le(0)
    return df.dropna(subset=["close"]).reset_index(drop=True)


def normalize_baostock_stock_basic(raw: pd.DataFrame) -> pd.DataFrame:
    required = {"code", "code_name", "ipoDate", "type", "status"}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"baostock stock basic missing columns: {sorted(missing)}")
    df = raw[list(required)].copy()
    df = df[df["type"].astype(str).eq("1")].copy()
    df["exchange"] = df["code"].astype(str).map(_exchange)
    df["code"] = df["code"].astype(str).map(_strip_exchange)
    df["name"] = df["code_name"].astype(str)
    df["industry"] = ""
    df["list_date"] = df["ipoDate"].astype(str)
    df["is_st"] = df["name"].str.contains("ST", case=False, na=False).astype(int)
    df["is_listed"] = df["status"].astype(str).eq("1").astype(int)
    return df[["code", "name", "exchange", "industry", "list_date", "is_st", "is_listed"]].reset_index(drop=True)


def normalize_baostock_index_daily(raw: pd.DataFrame, index_code: str) -> pd.DataFrame:
    required = set(BAOSTOCK_INDEX_COLUMNS.keys())
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"baostock index daily missing columns: {sorted(missing)}")
    df = raw[list(BAOSTOCK_INDEX_COLUMNS.keys())].rename(columns=BAOSTOCK_INDEX_COLUMNS)
    df.insert(0, "index_code", index_code)
    for column in ["open", "high", "low", "close", "volume", "amount", "pct_chg"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    return df.dropna(subset=["close"]).reset_index(drop=True)


AKSHARE_STOCK_DAILY_COLUMNS = {
    "\u65e5\u671f": "trade_date",
    "\u5f00\u76d8": "open",
    "\u6700\u9ad8": "high",
    "\u6700\u4f4e": "low",
    "\u6536\u76d8": "close",
    "\u6210\u4ea4\u91cf": "volume",
    "\u6210\u4ea4\u989d": "amount",
    "\u6362\u624b\u7387": "turnover_rate",
    "\u6da8\u8dcc\u5e45": "pct_chg",
}

AKSHARE_INDEX_COLUMNS = {
    "date": "trade_date",
    "\u65e5\u671f": "trade_date",
    "open": "open",
    "\u5f00\u76d8": "open",
    "high": "high",
    "\u6700\u9ad8": "high",
    "low": "low",
    "\u6700\u4f4e": "low",
    "close": "close",
    "\u6536\u76d8": "close",
    "volume": "volume",
    "\u6210\u4ea4\u91cf": "volume",
    "amount": "amount",
    "\u6210\u4ea4\u989d": "amount",
    "pct_chg": "pct_chg",
    "\u6da8\u8dcc\u5e45": "pct_chg",
}


def _format_trade_date(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce").dt.strftime("%Y-%m-%d")


def _compact_date(value: str) -> str:
    return str(value).replace("-", "")


def normalize_akshare_stock_basic(raw: pd.DataFrame) -> pd.DataFrame:
    column_map = {
        "\u8bc1\u5238\u4ee3\u7801": "code",
        "\u8bc1\u5238\u7b80\u79f0": "name",
        "A\u80a1\u4ee3\u7801": "code",
        "A\u80a1\u7b80\u79f0": "name",
    }
    renamed = raw.rename(columns={key: value for key, value in column_map.items() if key in raw.columns})
    required = {"code", "name"}
    missing = required - set(renamed.columns)
    if missing:
        raise ValueError(f"akshare stock basic missing columns: {sorted(missing)}")

    df = renamed[["code", "name"]].copy()
    df["code"] = df["code"].astype(str).str.extract(r"(\d+)", expand=False).fillna("").str.zfill(6)
    df = df[df["code"].str.len().eq(6)].copy()
    df["name"] = df["name"].astype(str)
    df["exchange"] = df["code"].map(_exchange)
    df["industry"] = ""
    df["list_date"] = ""
    df["is_st"] = df["name"].str.contains("ST", case=False, na=False).astype(int)
    df["is_listed"] = 1
    return df[["code", "name", "exchange", "industry", "list_date", "is_st", "is_listed"]].reset_index(drop=True)


def normalize_akshare_stock_daily(raw: pd.DataFrame, code: str) -> pd.DataFrame:
    renamed = raw.rename(columns={key: value for key, value in AKSHARE_STOCK_DAILY_COLUMNS.items() if key in raw.columns})
    if "code" not in renamed.columns:
        if "\u80a1\u7968\u4ee3\u7801" in raw.columns:
            renamed["code"] = raw["\u80a1\u7968\u4ee3\u7801"]
        else:
            renamed["code"] = code
    required = {"trade_date", "open", "high", "low", "close", "volume", "amount", "turnover_rate", "pct_chg", "code"}
    missing = required - set(renamed.columns)
    if missing:
        raise ValueError(f"akshare stock daily missing columns: {sorted(missing)}")

    df = renamed[["code", "trade_date", "open", "high", "low", "close", "volume", "amount", "turnover_rate", "pct_chg"]].copy()
    df["code"] = df["code"].astype(str).str.extract(r"(\d+)", expand=False).fillna(code).str.zfill(6)
    df["trade_date"] = _format_trade_date(df["trade_date"])
    for column in ["open", "high", "low", "close", "volume", "amount", "turnover_rate", "pct_chg"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df["is_suspended"] = df["volume"].fillna(0).le(0)
    return df.dropna(subset=["trade_date", "close"]).reset_index(drop=True)


def normalize_akshare_index_daily(raw: pd.DataFrame, index_code: str) -> pd.DataFrame:
    renamed = raw.rename(columns={key: value for key, value in AKSHARE_INDEX_COLUMNS.items() if key in raw.columns})
    required = {"trade_date", "open", "high", "low", "close", "volume", "amount"}
    missing = required - set(renamed.columns)
    if missing:
        raise ValueError(f"akshare index daily missing columns: {sorted(missing)}")

    columns = ["trade_date", "open", "high", "low", "close", "volume", "amount"]
    if "pct_chg" in renamed.columns:
        columns.append("pct_chg")
    df = renamed[columns].copy()
    df.insert(0, "index_code", index_code)
    df["trade_date"] = _format_trade_date(df["trade_date"])
    for column in ["open", "high", "low", "close", "volume", "amount"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    if "pct_chg" in df.columns:
        df["pct_chg"] = pd.to_numeric(df["pct_chg"], errors="coerce")
    else:
        df["pct_chg"] = df["close"].pct_change().mul(100)
    df["pct_chg"] = df["pct_chg"].fillna(0)
    return df[["index_code", "trade_date", "open", "high", "low", "close", "volume", "amount", "pct_chg"]].dropna(
        subset=["trade_date", "close"]
    ).reset_index(drop=True)


def normalize_akshare_sector(raw: pd.DataFrame, trade_date: str) -> pd.DataFrame:
    column_map = {
        "\u677f\u5757\u540d\u79f0": "sector_name",
        "\u540d\u79f0": "sector_name",
        "\u6da8\u8dcc\u5e45": "pct_chg",
        "\u6da8\u8dcc\u5e45%": "pct_chg",
        "\u6210\u4ea4\u989d": "amount",
    }
    renamed = raw.rename(columns={key: value for key, value in column_map.items() if key in raw.columns})
    required = {"sector_name", "pct_chg", "amount"}
    missing = required - set(renamed.columns)
    if missing:
        raise ValueError(f"akshare sector missing columns: {sorted(missing)}")
    df = renamed[["sector_name", "pct_chg", "amount"]].copy()
    df["trade_date"] = trade_date
    df["pct_chg"] = pd.to_numeric(df["pct_chg"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    return df[["sector_name", "trade_date", "pct_chg", "amount"]].dropna(subset=["sector_name"]).reset_index(drop=True)


def _is_baostock_not_logged_in(error_msg: str) -> bool:
    message = str(error_msg)
    lowered = message.lower()
    return "用户未登录" in message or "not login" in lowered or "not logged" in lowered


@dataclass
class DataFetcher:
    start_date: str
    query_retries: int = 3
    reconnect_interval: int = 200
    _bs: Any = field(default=None, init=False, repr=False)
    _baostock_logged_in: bool = field(default=False, init=False, repr=False)
    _queries_since_login: int = field(default=0, init=False, repr=False)

    def __enter__(self) -> DataFetcher:
        self._login_baostock()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def _login_baostock(self) -> Any:
        if self._baostock_logged_in and self._bs is not None:
            return self._bs

        import baostock as bs

        login = bs.login()
        if login.error_code != "0":
            raise RuntimeError(f"baostock login failed: {login.error_msg}")
        self._bs = bs
        self._baostock_logged_in = True
        self._queries_since_login = 0
        return bs

    def close(self) -> None:
        if self._baostock_logged_in and self._bs is not None:
            self._bs.logout()
        self._baostock_logged_in = False
        self._bs = None
        self._queries_since_login = 0

    def _reconnect_baostock_if_needed(self) -> None:
        if self.reconnect_interval < 1:
            return
        if self._baostock_logged_in and self._bs is not None and self._queries_since_login >= self.reconnect_interval:
            logger.info("baostock session reached %s queries; reconnecting", self.reconnect_interval)
            self.close()

    def _query_with_relogin_retry(self, query: Any, max_attempts: int | None = None) -> Any:
        attempts = max(1, max_attempts or self.query_retries)
        for attempt in range(1, attempts + 1):
            self._reconnect_baostock_if_needed()
            rs = query(self._login_baostock())
            self._queries_since_login += 1
            if rs.error_code == "0" or not _is_baostock_not_logged_in(rs.error_msg):
                return rs
            if attempt == attempts:
                return rs
            logger.warning("baostock session expired; relogin and retry (%s/%s)", attempt, attempts - 1)
            self.close()
        return rs

    def fetch_stock_basic(self) -> pd.DataFrame:
        rs = self._query_with_relogin_retry(lambda bs: bs.query_stock_basic(code_name="", code=""))
        if rs.error_code != "0":
            raise RuntimeError(f"baostock stock basic query failed: {rs.error_msg}")
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        raw = pd.DataFrame(rows, columns=rs.fields)
        return normalize_baostock_stock_basic(raw) if not raw.empty else pd.DataFrame()

    def fetch_stock_daily(
        self,
        code: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        bs_code = f"sh.{code}" if code.startswith(("6", "9")) else f"sz.{code}"
        start = start_date or self.start_date
        end = end_date or date.today().strftime("%Y-%m-%d")
        rs = self._query_with_relogin_retry(
            lambda bs: bs.query_history_k_data_plus(
                bs_code,
                "date,code,open,high,low,close,volume,amount,turn,pctChg",
                start_date=start,
                end_date=end,
                frequency="d",
                adjustflag="1",
            )
        )
        if rs.error_code != "0":
            raise RuntimeError(f"baostock query failed for {code}: {rs.error_msg}")
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        raw = pd.DataFrame(rows, columns=rs.fields)
        return normalize_baostock_daily(raw) if not raw.empty else pd.DataFrame()

    def fetch_index_daily(
        self,
        index_code: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        bs_code = f"{index_code[:2]}.{index_code[2:]}"
        start = start_date or self.start_date
        end = end_date or date.today().strftime("%Y-%m-%d")
        rs = self._query_with_relogin_retry(
            lambda bs: bs.query_history_k_data_plus(
                bs_code,
                "date,open,high,low,close,volume,amount,pctChg",
                start_date=start,
                end_date=end,
                frequency="d",
                adjustflag="3",
            )
        )
        if rs.error_code != "0":
            raise RuntimeError(f"baostock index query failed for {index_code}: {rs.error_msg}")
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        raw = pd.DataFrame(rows, columns=rs.fields)
        return normalize_baostock_index_daily(raw, index_code) if not raw.empty else pd.DataFrame()

    def fetch_sector_daily(self, trade_date: str) -> pd.DataFrame:
        try:
            import akshare as ak

            raw = ak.stock_board_industry_name_em()
            return normalize_akshare_sector(raw, trade_date)
        except Exception as exc:
            logger.warning("AKShare sector fetch failed: %s", exc)
            return pd.DataFrame(columns=["sector_name", "trade_date", "pct_chg", "amount"])


@dataclass
class AkshareDataFetcher:
    start_date: str

    def __enter__(self) -> "AkshareDataFetcher":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        return None

    def fetch_stock_basic(self) -> pd.DataFrame:
        import akshare as ak

        raw = ak.stock_info_a_code_name()
        return normalize_akshare_stock_basic(raw) if not raw.empty else pd.DataFrame()

    def fetch_stock_daily(
        self,
        code: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        import akshare as ak

        start = _compact_date(start_date or self.start_date)
        end = _compact_date(end_date or date.today().strftime("%Y-%m-%d"))
        raw = ak.stock_zh_a_hist(symbol=str(code).zfill(6), period="daily", start_date=start, end_date=end, adjust="hfq")
        return normalize_akshare_stock_daily(raw, str(code).zfill(6)) if not raw.empty else pd.DataFrame()

    def fetch_index_daily(
        self,
        index_code: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        import akshare as ak

        start = _compact_date(start_date or self.start_date)
        end = _compact_date(end_date or date.today().strftime("%Y-%m-%d"))
        raw = ak.stock_zh_index_daily_em(symbol=index_code, start_date=start, end_date=end)
        return normalize_akshare_index_daily(raw, index_code) if not raw.empty else pd.DataFrame()

    def fetch_sector_daily(self, trade_date: str) -> pd.DataFrame:
        try:
            import akshare as ak

            raw = ak.stock_board_industry_name_em()
            return normalize_akshare_sector(raw, trade_date)
        except Exception as exc:
            logger.warning("AKShare sector fetch failed: %s", exc)
            return pd.DataFrame(columns=["sector_name", "trade_date", "pct_chg", "amount"])

StockDailyTask = tuple[str, str, str]
StockDailyBatchResult = tuple[pd.DataFrame, list[tuple[str, str]], int]


def _chunked_tasks(tasks: Sequence[StockDailyTask], chunk_size: int) -> list[list[StockDailyTask]]:
    size = max(1, int(chunk_size))
    return [list(tasks[index : index + size]) for index in range(0, len(tasks), size)]


def _fetch_stock_daily_batch_worker(
    payload: tuple[list[StockDailyTask], int, int],
) -> tuple[list[dict[str, Any]], list[tuple[str, str]], int]:
    tasks, query_retries, reconnect_interval = payload
    rows: list[dict[str, Any]] = []
    failures: list[tuple[str, str]] = []
    if not tasks:
        return rows, failures, 0

    fetcher = DataFetcher(
        tasks[0][1],
        query_retries=query_retries,
        reconnect_interval=reconnect_interval,
    )
    try:
        with fetcher:
            for code, start_date, end_date in tasks:
                try:
                    daily = fetcher.fetch_stock_daily(code, start_date=start_date, end_date=end_date)
                except Exception as exc:
                    failures.append((code, str(exc)))
                    continue
                if not daily.empty:
                    rows.extend(daily.to_dict("records"))
    except Exception as exc:
        failures.extend((code, str(exc)) for code, _start, _end in tasks)

    return rows, failures, len(tasks)


def fetch_stock_daily_parallel(
    tasks: Sequence[StockDailyTask],
    workers: int,
    chunk_size: int,
    query_retries: int,
    reconnect_interval: int,
) -> Iterator[StockDailyBatchResult]:
    task_list = [(str(code), str(start), str(end)) for code, start, end in tasks]
    if not task_list:
        return

    chunks = _chunked_tasks(task_list, chunk_size)
    max_workers = max(1, min(int(workers), len(chunks)))

    if max_workers == 1:
        rows, failures, requested = _fetch_stock_daily_batch_worker((task_list, query_retries, reconnect_interval))
        yield pd.DataFrame(rows), failures, requested
        return

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_fetch_stock_daily_batch_worker, (chunk, query_retries, reconnect_interval)): chunk
            for chunk in chunks
        }
        for future in as_completed(futures):
            rows, failures, requested = future.result()
            yield pd.DataFrame(rows), failures, requested
