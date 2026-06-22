from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

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


def _strip_exchange(code: str) -> str:
    return code.split(".")[-1]


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


@dataclass
class DataFetcher:
    start_date: str

    def fetch_stock_daily(self, code: str, end_date: str | None = None) -> pd.DataFrame:
        import baostock as bs

        bs_code = f"sh.{code}" if code.startswith(("6", "9")) else f"sz.{code}"
        end = end_date or date.today().strftime("%Y-%m-%d")
        login = bs.login()
        if login.error_code != "0":
            raise RuntimeError(f"baostock login failed: {login.error_msg}")
        try:
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,code,open,high,low,close,volume,amount,turn,pctChg",
                start_date=self.start_date,
                end_date=end,
                frequency="d",
                adjustflag="1",
            )
            if rs.error_code != "0":
                raise RuntimeError(f"baostock query failed for {code}: {rs.error_msg}")
            rows = []
            while rs.next():
                rows.append(rs.get_row_data())
            raw = pd.DataFrame(rows, columns=rs.fields)
            return normalize_baostock_daily(raw) if not raw.empty else pd.DataFrame()
        finally:
            bs.logout()

    def fetch_sector_daily(self, trade_date: str) -> pd.DataFrame:
        try:
            import akshare as ak

            raw = ak.stock_board_industry_name_em()
            return normalize_akshare_sector(raw, trade_date)
        except Exception as exc:
            logger.warning("AKShare sector fetch failed: %s", exc)
            return pd.DataFrame(columns=["sector_name", "trade_date", "pct_chg", "amount"])
