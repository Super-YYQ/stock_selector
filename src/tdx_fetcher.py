from __future__ import annotations

import asyncio
import logging
import os
import threading
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

_PROBE_ENV_LOCK = threading.Lock()
_PROBE_ENV_USERS = 0
_PROBE_ENV_ORIGINAL: str | None = None
_DECIMAL_ENV_ORIGINAL: str | None = None

TDX_PRICE_BASIS = "tdx_unadjusted_v1"

# pytdxdata uses the standard TDX protocol on port 7709. Keep a broad,
# real-bar-capable fallback list so one stale node cannot stop a daily run.
DEFAULT_TDX_HOSTS: tuple[tuple[str, str, int], ...] = tuple(
    (host, host, 7709)
    for host in (
        "139.9.52.158",
        "103.251.85.94",
        "58.67.221.146",
        "59.36.5.11",
        "103.221.142.82",
        "218.106.92.182",
        "60.12.136.251",
        "218.106.92.183",
        "60.12.136.250",
        "115.238.90.170",
        "220.178.55.86",
        "220.178.55.71",
        "180.153.18.170",
        "115.238.90.165",
        "60.191.117.167",
        "218.75.126.9",
        "115.238.56.198",
        "117.34.114.16",
        "159.75.55.232",
        "117.34.114.17",
        "117.34.114.14",
        "117.34.114.15",
        "117.34.114.13",
        "117.34.114.27",
        "117.34.114.18",
        "117.34.114.20",
        "117.34.114.30",
    )
)

StockDailyTask = tuple[str, str, str]
StockDailyBatchResult = tuple[pd.DataFrame, list[tuple[str, str]], int]


def parse_tdx_hosts(entries: Sequence[str]) -> tuple[tuple[str, str, int], ...]:
    hosts: list[tuple[str, str, int]] = []
    for entry in entries:
        text = str(entry).strip()
        host, separator, port_text = text.rpartition(":")
        if not separator or not host or not port_text.isdigit() or not 0 < int(port_text) < 65536:
            raise ValueError(f"invalid tdx host {entry!r}; expected ip:port")
        hosts.append((text, host, int(port_text)))
    return tuple(hosts)


def describe_tdx_error(error: BaseException) -> str:
    original = getattr(error, "original_exception", None)
    if original is None or str(original) == str(error):
        return str(error)
    return f"{error} ({type(original).__name__}: {original})"


def tdx_market(code: str) -> int:
    normalized = str(code).zfill(6)
    if normalized.startswith(("43", "83", "87", "88", "92")):
        return 2
    if normalized.startswith(("5", "6", "9")):
        return 1
    return 0


def _tdx_symbol(code: str) -> str:
    normalized = str(code).zfill(6)
    if tdx_market(normalized) == 2:
        return f"bj{normalized}"
    if tdx_market(normalized) == 1:
        return f"sh{normalized}"
    return f"sz{normalized}"


def _bar_trade_date(bar: Any) -> str:
    trading_date = getattr(bar, "trading_date", None)
    if trading_date:
        return str(trading_date)[:10]
    value = getattr(bar, "datetime", None)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if value:
        return str(value)[:10]
    year = int(getattr(bar, "year"))
    month = int(getattr(bar, "month"))
    day = int(getattr(bar, "day"))
    return date(year, month, day).isoformat()


def _empty_tdx_daily(columns: Sequence[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=list(columns))


def normalize_tdxdata_daily(bars: Sequence[Any], code: str) -> pd.DataFrame:
    """Map pytdxdata SecurityBar records to the project's daily schema.

    pytdxdata reports A-share volume in shares. The legacy pytdx adapter
    reported lots and therefore multiplied volume by 100; that conversion
    must not be applied here.
    """
    columns = [
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
    rows: list[dict[str, Any]] = []
    normalized_code = str(code).zfill(6)
    for bar in bars:
        rows.append(
            {
                "code": normalized_code,
                "trade_date": _bar_trade_date(bar),
                "open": getattr(bar, "open"),
                "high": getattr(bar, "high"),
                "low": getattr(bar, "low"),
                "close": getattr(bar, "close"),
                "volume": getattr(bar, "vol"),
                "amount": getattr(bar, "amount"),
            }
        )
    if not rows:
        return _empty_tdx_daily(columns)

    df = pd.DataFrame(rows)
    for column in ["open", "high", "low", "close", "volume", "amount"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = (
        df.dropna(subset=["trade_date", "close"])
        .sort_values("trade_date")
        .drop_duplicates("trade_date", keep="last")
        .reset_index(drop=True)
    )
    df["turnover_rate"] = pd.NA
    df["pct_chg"] = (
        df["close"]
        .pct_change(fill_method=None)
        .mul(100)
        .replace([float("inf"), float("-inf")], pd.NA)
        .fillna(0)
    )
    df["is_suspended"] = df["volume"].fillna(0).le(0)
    return df[columns]


def normalize_tdxdata_index_daily(bars: Sequence[Any], index_code: str) -> pd.DataFrame:
    normalized = normalize_tdxdata_daily(bars, index_code[2:])
    normalized = normalized.rename(columns={"code": "index_code"})
    normalized["index_code"] = index_code
    return normalized[
        ["index_code", "trade_date", "open", "high", "low", "close", "volume", "amount", "pct_chg"]
    ].reset_index(drop=True)


# Compatibility normalizers for callers that still pass legacy pytdx-shaped rows.
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
    df = df.dropna(subset=["trade_date", "close"]).sort_values("trade_date").drop_duplicates(
        "trade_date", keep="last"
    )
    df["turnover_rate"] = pd.NA
    df["pct_chg"] = (
        df["close"]
        .pct_change(fill_method=None)
        .mul(100)
        .replace([float("inf"), float("-inf")], pd.NA)
        .fillna(0)
    )
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
    """Synchronous project adapter around the async pytdxdata client."""

    start_date: str
    timeout_seconds: float = 3.0
    query_retries: int = 3
    hosts: Sequence[tuple[str, str, int]] = DEFAULT_TDX_HOSTS
    host_offset: int = 0
    client_factory: Callable[..., Any] | None = None
    _client: Any = field(default=None, init=False, repr=False)
    _loop: asyncio.AbstractEventLoop | None = field(default=None, init=False, repr=False)
    _previous_event_loop: asyncio.AbstractEventLoop | None = field(default=None, init=False, repr=False)
    _probe_env_acquired: bool = field(default=False, init=False, repr=False)
    _decimal_env_acquired: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.hosts:
            raise ValueError("tdx hosts must not be empty")
        ports = {int(host[2]) for host in self.hosts}
        if len(ports) != 1:
            raise ValueError("all configured TDX hosts must use the same port")
        self.hosts = tuple(self.hosts)

    def __enter__(self) -> "TdxDataFetcher":
        global _PROBE_ENV_USERS, _PROBE_ENV_ORIGINAL, _DECIMAL_ENV_ORIGINAL

        self._loop = asyncio.new_event_loop()
        try:
            self._previous_event_loop = asyncio.get_running_loop()
        except RuntimeError:
            self._previous_event_loop = None
        asyncio.set_event_loop(self._loop)
        with _PROBE_ENV_LOCK:
            if _PROBE_ENV_USERS == 0:
                _PROBE_ENV_ORIGINAL = os.environ.get("PYPYTDX_DATA_DISABLE_PROBE")
                _DECIMAL_ENV_ORIGINAL = os.environ.get("PYPYTDX_DATA_DISABLE_DECIMAL_SYNC")
                os.environ["PYPYTDX_DATA_DISABLE_PROBE"] = "1"
                os.environ["PYPYTDX_DATA_DISABLE_DECIMAL_SYNC"] = "1"
            _PROBE_ENV_USERS += 1
            self._probe_env_acquired = True
            self._decimal_env_acquired = True
        try:
            self._client = self._new_client()
            opened = self._loop.run_until_complete(self._client.__aenter__())
            if opened is not None:
                self._client = opened
            probe_end = date.today().isoformat()
            probe_start = (date.today() - timedelta(days=30)).isoformat()
            probe = self._loop.run_until_complete(self._get_bars("sh000001", probe_start, probe_end))
            if not probe:
                raise RuntimeError("TDX probe returned no recent index bars")
        except Exception as exc:
            self.close()
            raise RuntimeError(f"pytdxdata TDX initialization failed: {describe_tdx_error(exc)}") from exc
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def _new_client(self) -> Any:
        rotated = self.hosts[self.host_offset % len(self.hosts) :] + self.hosts[: self.host_offset % len(self.hosts)]
        kwargs = {
            "standard_servers": [host[1] for host in rotated],
            "port": int(rotated[0][2]),
            "timeout": float(self.timeout_seconds),
            "pool_min": 1,
            "pool_max": max(1, min(len(rotated), 8)),
            "std_pool_cap": 1,
            "mac_pool_cap": 1,
            "ex_pool_cap": 1,
            "cache_dir": None,
        }
        if self.client_factory is not None:
            return self.client_factory(**kwargs)
        from pytdxdata import TdxData

        return TdxData(**kwargs)

    def _run(self, awaitable: Any) -> Any:
        if self._loop is None or self._loop.is_closed():
            raise RuntimeError("TDX fetcher is not open")
        return self._loop.run_until_complete(awaitable)

    async def _get_bars(self, symbol: str, start_date: str, end_date: str) -> list[Any]:
        from pytdxdata import KlinePeriod

        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        return await self._client.get_bars(
            symbol,
            KlinePeriod.DAY,
            start_date=start,
            end_date=end,
            concurrency=1,
            pipeline=1,
        )

    def _query_bars(self, symbol: str, start_date: str, end_date: str) -> list[Any]:
        errors: list[str] = []
        for attempt in range(1, max(1, int(self.query_retries)) + 1):
            try:
                return self._run(self._get_bars(symbol, start_date, end_date))
            except Exception as exc:
                errors.append(describe_tdx_error(exc))
                if attempt < self.query_retries:
                    logger.debug("TDX query failed; retrying (%s/%s): %s", attempt, self.query_retries, exc)
        raise RuntimeError(f"TDX get_bars failed for {symbol}: {' | '.join(errors)}")

    def close(self) -> None:
        loop = self._loop
        client = self._client
        self._client = None
        if loop is not None and not loop.is_closed() and client is not None:
            try:
                loop.run_until_complete(client.__aexit__(None, None, None))
            except Exception:
                logger.debug("TDX client close failed", exc_info=True)
        if loop is not None and not loop.is_closed():
            loop.close()
        global _PROBE_ENV_USERS, _PROBE_ENV_ORIGINAL, _DECIMAL_ENV_ORIGINAL

        self._loop = None
        if self._probe_env_acquired:
            with _PROBE_ENV_LOCK:
                _PROBE_ENV_USERS = max(0, _PROBE_ENV_USERS - 1)
                if _PROBE_ENV_USERS == 0:
                    if _PROBE_ENV_ORIGINAL is None:
                        os.environ.pop("PYPYTDX_DATA_DISABLE_PROBE", None)
                    else:
                        os.environ["PYPYTDX_DATA_DISABLE_PROBE"] = _PROBE_ENV_ORIGINAL
                    if _DECIMAL_ENV_ORIGINAL is None:
                        os.environ.pop("PYPYTDX_DATA_DISABLE_DECIMAL_SYNC", None)
                    else:
                        os.environ["PYPYTDX_DATA_DISABLE_DECIMAL_SYNC"] = _DECIMAL_ENV_ORIGINAL
                    _PROBE_ENV_ORIGINAL = None
                    _DECIMAL_ENV_ORIGINAL = None
            self._probe_env_acquired = False
            self._decimal_env_acquired = False
        asyncio.set_event_loop(self._previous_event_loop)
        self._previous_event_loop = None

    def fetch_stock_basic(self) -> pd.DataFrame:
        # TDX's universe endpoint does not enumerate Beijing Exchange symbols
        # consistently. Keep the existing optional AKShare basic-info adapter;
        # daily TDX updates use the persisted stock_basic table incrementally.
        import akshare as ak
        from src.fetch_data import normalize_akshare_stock_basic

        raw = ak.stock_info_a_code_name()
        return normalize_akshare_stock_basic(raw) if not raw.empty else pd.DataFrame()

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
        bars = self._query_bars(_tdx_symbol(normalized_code), overlap_start, end)
        normalized = normalize_tdxdata_daily(bars, normalized_code)
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
        bars = self._query_bars(index_code, overlap_start, end)
        normalized = normalize_tdxdata_index_daily(bars, index_code)
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
    hosts: Sequence[tuple[str, str, int]],
) -> StockDailyBatchResult:
    rows: list[dict[str, Any]] = []
    failures: list[tuple[str, str]] = []
    fetcher = TdxDataFetcher(
        tasks[0][1] if tasks else date.today().strftime("%Y-%m-%d"),
        timeout_seconds=timeout_seconds,
        query_retries=query_retries,
        hosts=hosts,
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
    hosts: Sequence[tuple[str, str, int]] = DEFAULT_TDX_HOSTS,
) -> Iterator[StockDailyBatchResult]:
    chunks = _chunked_tasks([(str(code), str(start), str(end)) for code, start, end in tasks], chunk_size)
    if not chunks:
        return

    max_workers = max(1, min(int(workers), len(chunks)))
    if max_workers == 1:
        for chunk in chunks:
            yield _fetch_tdx_batch_worker(chunk, timeout_seconds, query_retries, 0, hosts)
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
                0,
                hosts,
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
