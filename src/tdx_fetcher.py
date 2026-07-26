from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

TDX_PRICE_BASIS = "tdx_unadjusted_v1"
TDX_BAR_CATEGORY_DAILY = 9
TDX_BAR_PAGE_SIZE = 800
DEFAULT_TDX_HOSTS: tuple[tuple[str, str, int], ...] = (
    ("beijing-unicom-80", "202.108.253.139", 80),
    ("beijing-unicom", "123.125.108.14", 7709),
    ("hangzhou-unicom", "60.12.136.250", 7709),
    ("shanghai-telecom", "180.153.18.170", 7709),
    ("hangzhou-telecom", "115.238.90.165", 7709),
    ("shanghai-telecom-80", "180.153.18.172", 80),
)

StockDailyTask = tuple[str, str, str]
StockDailyBatchResult = tuple[pd.DataFrame, list[tuple[str, str]], int]


def tdx_market(code: str) -> int:
    normalized = str(code).zfill(6)
    if normalized.startswith("92"):
        return 2
    if normalized.startswith(("5", "6", "9")):
        return 1
    return 0


def _date_column(raw: pd.DataFrame) -> pd.Series:
    if "datetime" in raw.columns:
        return raw["datetime"].astype(str).str.slice(0, 10)
    if {"year", "month", "day"} <= set(raw.columns):
        values = {
            "year": pd.to_numeric(raw["year"], errors="coerce"),
            "month": pd.to_numeric(raw["month"], errors="coerce"),
            "day": pd.to_numeric(raw["day"], errors="coerce"),
        }
        return pd.to_datetime(pd.DataFrame(values), errors="coerce").dt.strftime("%Y-%m-%d")
    raise ValueError("tdx daily missing datetime fields")


def normalize_tdx_stock_daily(raw: pd.DataFrame, code: str) -> pd.DataFrame:
    required = {"open", "close", "high", "low", "vol", "amount"}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"tdx stock daily missing columns: {sorted(missing)}")

    df = pd.DataFrame(
        {
            "code": str(code).zfill(6),
            "trade_date": _date_column(raw),
            "open": raw["open"],
            "high": raw["high"],
            "low": raw["low"],
            "close": raw["close"],
            "volume": raw["vol"],
            "amount": raw["amount"],
        }
    )
    for column in ["open", "high", "low", "close", "volume", "amount"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df["volume"] = df["volume"].mul(100)
    df = df.dropna(subset=["trade_date", "close"]).sort_values("trade_date").drop_duplicates("trade_date", keep="last")
    df["turnover_rate"] = pd.NA
    df["pct_chg"] = df["close"].pct_change(fill_method=None).mul(100).replace([float("inf"), float("-inf")], pd.NA).fillna(0)
    df["is_suspended"] = df["volume"].fillna(0).le(0)
    return df[
        [
            "code",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "turnover_rate",
            "pct_chg",
            "is_suspended",
        ]
    ].reset_index(drop=True)


def normalize_tdx_index_daily(raw: pd.DataFrame, index_code: str) -> pd.DataFrame:
    stock = normalize_tdx_stock_daily(raw, index_code[2:])
    stock = stock.rename(columns={"code": "index_code"})
    stock["index_code"] = index_code
    return stock[
        ["index_code", "trade_date", "open", "high", "low", "close", "volume", "amount", "pct_chg"]
    ].reset_index(drop=True)


@dataclass
class TdxDataFetcher:
    start_date: str
    timeout_seconds: float = 3.0
    query_retries: int = 3
    hosts: Sequence[tuple[str, str, int]] = DEFAULT_TDX_HOSTS
    host_offset: int = 0
    api_factory: Callable[[], Any] | None = None
    _api: Any = field(default=None, init=False, repr=False)
    _host_cursor: int = field(default=0, init=False, repr=False)
    _connected_host: tuple[str, str, int] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.hosts:
            raise ValueError("tdx hosts must not be empty")
        self._host_cursor = int(self.host_offset) % len(self.hosts)

    def __enter__(self) -> "TdxDataFetcher":
        self._connect()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def _new_api(self) -> Any:
        if self.api_factory is not None:
            return self.api_factory()
        from pytdx.hq import TdxHq_API

        return TdxHq_API(heartbeat=False, auto_retry=False, raise_exception=True)

    def _connect(self) -> None:
        if self._api is not None:
            return
        errors: list[str] = []
        # A connection attempt is cheap compared with a full daily update. Check
        # every configured endpoint before declaring the provider unavailable;
        # query_retries controls request-level retries after a connection exists.
        for _ in range(len(self.hosts)):
            host = self.hosts[self._host_cursor]
            self._host_cursor = (self._host_cursor + 1) % len(self.hosts)
            api = self._new_api()
            try:
                connected = api.connect(host[1], host[2], time_out=float(self.timeout_seconds))
                if connected is False:
                    raise RuntimeError("connect returned false")
            except Exception as exc:
                errors.append(f"{host[0]}: {exc}")
                try:
                    api.disconnect()
                except Exception:
                    pass
                continue
            self._api = api
            self._connected_host = host
            logger.debug("connected to TDX host %s (%s:%s)", host[0], host[1], host[2])
            return
        raise RuntimeError("all configured TDX hosts failed: " + " | ".join(errors))

    def close(self) -> None:
        if self._api is not None:
            try:
                self._api.disconnect()
            except Exception:
                pass
        self._api = None
        self._connected_host = None

    def _request(self, method_name: str, *args: object) -> Any:
        errors: list[str] = []
        for attempt in range(1, max(1, self.query_retries) + 1):
            try:
                self._connect()
                return getattr(self._api, method_name)(*args)
            except Exception as exc:
                host_name = self._connected_host[0] if self._connected_host else "unconnected"
                errors.append(f"{host_name}: {exc}")
                self.close()
                if attempt < self.query_retries:
                    logger.debug("TDX request failed; switching host (%s/%s): %s", attempt, self.query_retries, exc)
        raise RuntimeError(f"TDX {method_name} failed: " + " | ".join(errors))

    def fetch_stock_basic(self) -> pd.DataFrame:
        import akshare as ak
        from src.fetch_data import normalize_akshare_stock_basic

        raw = ak.stock_info_a_code_name()
        return normalize_akshare_stock_basic(raw) if not raw.empty else pd.DataFrame()

    def _fetch_daily_bars(
        self,
        market: int,
        code: str,
        start_date: str,
        end_date: str,
        method_name: str = "get_security_bars",
    ) -> pd.DataFrame:
        pages: list[pd.DataFrame] = []
        offset = 0
        max_pages = 20
        for _ in range(max_pages):
            rows = self._request(
                method_name,
                TDX_BAR_CATEGORY_DAILY,
                market,
                code,
                offset,
                TDX_BAR_PAGE_SIZE,
            )
            if not rows:
                break
            page = pd.DataFrame(rows)
            pages.append(page)
            page_dates = _date_column(page).dropna()
            if not page_dates.empty and str(page_dates.min()) <= start_date:
                break
            if len(page) < TDX_BAR_PAGE_SIZE:
                break
            offset += TDX_BAR_PAGE_SIZE
        if not pages:
            return pd.DataFrame()
        combined = pd.concat(pages, ignore_index=True)
        combined_dates = _date_column(combined)
        return combined[(combined_dates >= start_date) & (combined_dates <= end_date)].copy()

    def fetch_stock_daily(
        self,
        code: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        normalized_code = str(code).zfill(6)
        start = str(start_date or self.start_date)
        end = str(end_date or date.today().strftime("%Y-%m-%d"))
        overlap_start = (datetime.strptime(start, "%Y-%m-%d").date() - timedelta(days=10)).strftime("%Y-%m-%d")
        raw = self._fetch_daily_bars(tdx_market(normalized_code), normalized_code, overlap_start, end)
        if raw.empty:
            return pd.DataFrame()
        normalized = normalize_tdx_stock_daily(raw, normalized_code)
        return normalized[normalized["trade_date"] >= start].reset_index(drop=True)

    def fetch_index_daily(
        self,
        index_code: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        start = str(start_date or self.start_date)
        end = str(end_date or date.today().strftime("%Y-%m-%d"))
        overlap_start = (datetime.strptime(start, "%Y-%m-%d").date() - timedelta(days=10)).strftime("%Y-%m-%d")
        market = 1 if index_code.startswith("sh") else 0
        raw = self._fetch_daily_bars(
            market,
            index_code[2:],
            overlap_start,
            end,
            method_name="get_index_bars",
        )
        if raw.empty:
            return pd.DataFrame()
        normalized = normalize_tdx_index_daily(raw, index_code)
        return normalized[normalized["trade_date"] >= start].reset_index(drop=True)

    def fetch_sector_daily(self, trade_date: str) -> pd.DataFrame:
        logger.info("TDX provider does not fetch an external sector snapshot; continuing with local stock data")
        return pd.DataFrame(columns=["sector_name", "trade_date", "pct_chg", "amount"])


def _chunked_tasks(tasks: Sequence[StockDailyTask], chunk_size: int) -> list[list[StockDailyTask]]:
    size = max(1, int(chunk_size))
    return [list(tasks[index : index + size]) for index in range(0, len(tasks), size)]


def _fetch_tdx_batch_worker(
    tasks: list[StockDailyTask],
    timeout_seconds: float,
    query_retries: int,
    host_offset: int,
) -> StockDailyBatchResult:
    rows: list[dict[str, Any]] = []
    failures: list[tuple[str, str]] = []
    fetcher = TdxDataFetcher(
        tasks[0][1] if tasks else date.today().strftime("%Y-%m-%d"),
        timeout_seconds=timeout_seconds,
        query_retries=query_retries,
        host_offset=host_offset,
    )
    try:
        with fetcher:
            for code, start_date, end_date in tasks:
                try:
                    daily = fetcher.fetch_stock_daily(code, start_date=start_date, end_date=end_date)
                    if daily.empty:
                        failures.append((code, "TDX returned no daily rows"))
                    else:
                        rows.extend(daily.to_dict("records"))
                except Exception as exc:
                    failures.append((code, str(exc)))
    except Exception as exc:
        failures.extend((code, str(exc)) for code, _start, _end in tasks)
    return pd.DataFrame(rows), failures, len(tasks)


def fetch_tdx_stock_daily_parallel(
    tasks: Sequence[StockDailyTask],
    workers: int,
    chunk_size: int,
    timeout_seconds: float,
    query_retries: int,
) -> Iterator[StockDailyBatchResult]:
    chunks = _chunked_tasks([(str(code), str(start), str(end)) for code, start, end in tasks], chunk_size)
    if not chunks:
        return

    max_workers = max(1, min(int(workers), len(chunks)))
    if max_workers == 1:
        for index, chunk in enumerate(chunks):
            yield _fetch_tdx_batch_worker(chunk, timeout_seconds, query_retries, index)
        return

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="tdx-fetch") as executor:
        pending: dict[Any, int] = {}
        next_index = 0

        def submit_one() -> None:
            nonlocal next_index
            if next_index >= len(chunks):
                return
            index = next_index
            next_index += 1
            future = executor.submit(
                _fetch_tdx_batch_worker,
                chunks[index],
                timeout_seconds,
                query_retries,
                index,
            )
            pending[future] = index

        for _ in range(max_workers):
            submit_one()

        while pending:
            done, _ = wait(set(pending), return_when=FIRST_COMPLETED)
            for future in done:
                pending.pop(future, None)
                yield future.result()
                submit_one()
