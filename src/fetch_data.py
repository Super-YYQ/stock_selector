from __future__ import annotations

import logging
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


def normalize_akshare_sector(raw: pd.DataFrame, trade_date: str) -> pd.DataFrame:
    column_map = {
        "板块名称": "sector_name",
        "名称": "sector_name",
        "涨跌幅": "pct_chg",
        "涨跌幅%": "pct_chg",
        "成交额": "amount",
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