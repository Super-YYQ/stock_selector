from __future__ import annotations

import argparse
import logging
from contextlib import contextmanager, nullcontext
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from src.build_pool import build_stock_pool
from src.config import AppConfig, load_config
from src.database import Database
from src.fetch_data import AkshareDataFetcher, DataFetcher, fetch_stock_daily_parallel
from src.market_score import calculate_market_score
from src.report import write_excel_report
from src.risk_filter import calculate_risk_penalties
from src.scoring import build_ranked_results
from src.sector_score import calculate_sector_scores
from src.strategies.registry import run_enabled_strategies
from src.stock_character import calculate_stock_character_scores
from src.volume_price_score import calculate_volume_price_scores

INDEX_CODES = ("sh000001", "sz399001", "sz399006")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A 股盘后多因子选股助手")
    parser.add_argument("--init", action="store_true", help="初始化并回填历史数据")
    parser.add_argument("--date", help="指定报告日期，格式 YYYY-MM-DD")
    return parser.parse_args(argv)


def setup_logging(report_date: str) -> None:
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.FileHandler(log_dir / f"run_{report_date}.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def resolve_report_date(requested_date: str | None, latest_trade_date: str | None) -> str:
    if requested_date:
        return requested_date
    return latest_trade_date or date.today().strftime("%Y-%m-%d")


def _empty_if_missing(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    return df if not df.empty else pd.DataFrame(columns=columns)


def _safe_read(db: Database, table: str, columns: list[str]) -> pd.DataFrame:
    try:
        return _empty_if_missing(db.read_table(table), columns)
    except Exception:
        return pd.DataFrame(columns=columns)


def _latest_stock_rows(stock_daily: pd.DataFrame, report_date: str) -> pd.DataFrame:
    return stock_daily[stock_daily["trade_date"] <= report_date].sort_values(["code", "trade_date"]).groupby("code").tail(1)


def _add_risk_inputs(factors: pd.DataFrame) -> pd.DataFrame:
    enriched = factors.copy()
    for column in ["return_5d", "return_10d", "return_20d", "distance_ma20", "volatility_20d"]:
        if column not in enriched.columns:
            enriched[column] = 0
    if "turnover_rate" not in enriched.columns:
        enriched["turnover_rate"] = 0
    return enriched


def _managed_fetcher(fetcher: Any):
    if hasattr(fetcher, "__enter__") and hasattr(fetcher, "__exit__"):
        return fetcher
    return nullcontext(fetcher)


def _latest_dates(df: pd.DataFrame, key_column: str, date_column: str = "trade_date") -> dict[str, str]:
    if df.empty or key_column not in df.columns or date_column not in df.columns:
        return {}
    latest = df.dropna(subset=[key_column, date_column]).copy()
    if latest.empty:
        return {}
    latest[key_column] = latest[key_column].astype(str)
    latest[date_column] = latest[date_column].astype(str)
    return latest.groupby(key_column)[date_column].max().to_dict()


def _next_fetch_start(latest_date: str | None, fallback_start: str) -> str:
    if not latest_date:
        return fallback_start
    parsed = datetime.strptime(str(latest_date), "%Y-%m-%d").date()
    return (parsed + timedelta(days=1)).strftime("%Y-%m-%d")


def _should_fetch(start_date: str, end_date: str) -> bool:
    return start_date <= end_date


def _is_baostock_rate_limit_error(error: object) -> bool:
    message = str(error).lower()
    return "blacklist" in message or "rate limit" in message or "\u9ed1\u540d\u5355" in str(error)



def _data_provider(config: AppConfig) -> str:
    return (config.data.provider or "mixed").strip().lower()


def _create_configured_fetcher(config: AppConfig) -> Any:
    provider = _data_provider(config)
    if provider in {"akshare", "eastmoney"}:
        return AkshareDataFetcher(config.data.start_date)
    return DataFetcher(
        config.data.start_date,
        query_retries=config.data.baostock_query_retries,
        reconnect_interval=config.data.baostock_reconnect_interval,
    )


def _allows_akshare_fallback(config: AppConfig) -> bool:
    return _data_provider(config) in {"mixed", "auto", ""}


@contextmanager
def _open_configured_fetcher(fetcher: Any | None, config: AppConfig, external_fetcher: bool):
    provider = _data_provider(config)
    active_context = _managed_fetcher(fetcher or _create_configured_fetcher(config))
    parallel_stock_fetch_allowed = not external_fetcher and provider not in {"akshare", "eastmoney"}
    try:
        active_fetcher = active_context.__enter__()
    except Exception as exc:
        if external_fetcher or not _allows_akshare_fallback(config) or not _is_baostock_rate_limit_error(exc):
            raise
        logging.getLogger(__name__).warning("baostock login blocked; fallback to AKShare: %s", exc)
        active_context = _managed_fetcher(AkshareDataFetcher(config.data.start_date))
        active_fetcher = active_context.__enter__()
        parallel_stock_fetch_allowed = False
    try:
        yield active_fetcher, parallel_stock_fetch_allowed
    finally:
        active_context.__exit__(None, None, None)

def update_market_data(
    db: Database,
    config: AppConfig,
    report_date: str,
    init: bool = False,
    fetcher: Any | None = None,
) -> dict[str, int]:
    logger = logging.getLogger(__name__)
    external_fetcher = fetcher is not None
    counts = {"stock_basic": 0, "stock_daily": 0, "index_daily": 0, "sector_daily": 0, "failed_symbols": 0}

    with _open_configured_fetcher(fetcher, config, external_fetcher) as (active_fetcher, parallel_stock_fetch_allowed):
        if init:
            try:
                basic = active_fetcher.fetch_stock_basic()
            except Exception as exc:
                fallback_basic = _safe_read(db, "stock_basic", ["code", "name", "exchange", "industry", "list_date", "is_st", "is_listed"])
                if fallback_basic.empty:
                    raise
                logger.warning("股票基础信息更新失败，使用本地已有股票列表继续初始化: %s", exc)
                basic = fallback_basic
            else:
                if not basic.empty:
                    counts["stock_basic"] = db.upsert_dataframe("stock_basic", basic, ["code"])
                else:
                    fallback_basic = _safe_read(db, "stock_basic", ["code", "name", "exchange", "industry", "list_date", "is_st", "is_listed"])
                    if not fallback_basic.empty:
                        logger.warning("股票基础信息接口返回空数据，使用本地已有股票列表继续初始化")
                        basic = fallback_basic
            existing_stock_daily = _safe_read(db, "stock_daily", ["code", "trade_date"])
            existing_index_daily = _safe_read(db, "index_daily", ["index_code", "trade_date"])
        else:
            basic = db.read_table("stock_basic")
            existing_stock_daily = _safe_read(db, "stock_daily", ["code", "trade_date"])
            existing_index_daily = _safe_read(db, "index_daily", ["index_code", "trade_date"])

        if basic.empty:
            logger.warning("无股票基础信息，跳过行情更新")
            return counts

        latest_stock_dates = _latest_dates(existing_stock_daily, "code")
        latest_index_dates = _latest_dates(existing_index_daily, "index_code")
        codes = basic["code"].dropna().astype(str).tolist()
        total = len(codes)
        skipped_symbols = 0

        stock_tasks: list[tuple[str, str, str]] = []
        for code in codes:
            fetch_start = _next_fetch_start(latest_stock_dates.get(code), config.data.start_date)
            if not _should_fetch(fetch_start, report_date):
                skipped_symbols += 1
                continue
            stock_tasks.append((code, fetch_start, report_date))

        def retry_stock_tasks_sequentially(tasks: list[tuple[str, str, str]], reason: str) -> None:
            if not tasks:
                return
            if hasattr(active_fetcher, "close"):
                active_fetcher.close()
            logger.info("retrying %s stock daily tasks sequentially after %s", len(tasks), reason)
            for position, (code, fetch_start, fetch_end) in enumerate(tasks, start=1):
                if position == 1 or position % 100 == 0 or position == len(tasks):
                    logger.info("stock daily retry: %s/%s %s (%s -> %s)", position, len(tasks), code, fetch_start, fetch_end)
                try:
                    daily = active_fetcher.fetch_stock_daily(code, start_date=fetch_start, end_date=fetch_end)
                    if not daily.empty:
                        counts["stock_daily"] += db.upsert_dataframe("stock_daily", daily, ["code", "trade_date"])
                except Exception as exc:
                    counts["failed_symbols"] += 1
                    logger.warning("[%s] stock daily update failed after retry: %s", code, exc)

        use_parallel_stock_fetch = bool(stock_tasks) and parallel_stock_fetch_allowed and config.data.baostock_parallel_workers > 1
        if use_parallel_stock_fetch:
            logger.info(
                "parallel stock daily update: %s/%s symbols, workers=%s, chunk_size=%s",
                len(stock_tasks),
                total,
                config.data.baostock_parallel_workers,
                config.data.baostock_parallel_chunk_size,
            )
            task_by_code = {task[0]: task for task in stock_tasks}
            retry_tasks: dict[str, tuple[str, str, str]] = {}
            processed_symbols = 0
            try:
                for daily, failures, requested in fetch_stock_daily_parallel(
                    stock_tasks,
                    workers=config.data.baostock_parallel_workers,
                    chunk_size=config.data.baostock_parallel_chunk_size,
                    query_retries=config.data.baostock_query_retries,
                    reconnect_interval=config.data.baostock_reconnect_interval,
                ):
                    processed_symbols += requested
                    for code, error in failures:
                        task = task_by_code.get(code)
                        if _is_baostock_rate_limit_error(error):
                            counts["failed_symbols"] += 1
                            logger.warning("[%s] stock daily blocked by baostock rate limit; stop immediate retry: %s", code, error)
                        elif task is not None:
                            retry_tasks[code] = task
                            logger.warning("[%s] stock daily parallel fetch failed; will retry sequentially: %s", code, error)
                        else:
                            counts["failed_symbols"] += 1
                            logger.warning("[%s] stock daily update failed: %s", code, error)
                    if not daily.empty:
                        counts["stock_daily"] += db.upsert_dataframe("stock_daily", daily, ["code", "trade_date"])
                    logger.info("parallel stock daily progress: %s/%s symbols", processed_symbols, len(stock_tasks))
            except Exception as exc:
                logger.warning("parallel stock daily update failed, fallback to sequential mode: %s", exc)
                use_parallel_stock_fetch = False
            else:
                retry_stock_tasks_sequentially(list(retry_tasks.values()), "parallel failures")

        if not use_parallel_stock_fetch:
            retry_stock_tasks_sequentially(stock_tasks, "sequential mode")

        if skipped_symbols:
            logger.info("skipped %s symbols already updated to %s", skipped_symbols, report_date)
        for index_code in INDEX_CODES:
            fetch_start = _next_fetch_start(latest_index_dates.get(index_code), config.data.start_date)
            if not _should_fetch(fetch_start, report_date):
                logger.info("指数日线已是最新，跳过: %s", index_code)
                continue
            try:
                logger.info("正在更新指数日线: %s (%s -> %s)", index_code, fetch_start, report_date)
                index_daily = active_fetcher.fetch_index_daily(index_code, start_date=fetch_start, end_date=report_date)
                if not index_daily.empty:
                    counts["index_daily"] += db.upsert_dataframe("index_daily", index_daily, ["index_code", "trade_date"])
            except Exception as exc:
                logger.warning("[%s] 指数数据更新失败: %s", index_code, exc)

        try:
            logger.info("正在更新行业板块数据")
            sector_daily = active_fetcher.fetch_sector_daily(report_date)
            if not sector_daily.empty:
                counts["sector_daily"] = db.upsert_dataframe("sector_daily", sector_daily, ["sector_name", "trade_date"])
        except Exception as exc:
            logger.warning("板块数据更新失败: %s", exc)

    logger.info("数据更新完成: %s", counts)
    return counts


def run(argv: list[str] | None = None) -> Path | None:
    args = parse_args(argv)
    preliminary_date = args.date or date.today().strftime("%Y-%m-%d")
    setup_logging(preliminary_date)
    logger = logging.getLogger(__name__)

    try:
        config = load_config()
        db = Database(config.data.database)
        db.initialize()

        existing_basic = _safe_read(db, "stock_basic", ["code", "name", "industry", "list_date", "is_st", "is_listed"])
        if args.init:
            logger.info("初始化模式已启动，开始更新免费数据源")
            update_market_data(db, config, preliminary_date, init=True)
        elif not existing_basic.empty:
            logger.info("开始执行每日增量数据更新")
            update_market_data(db, config, preliminary_date, init=False)

        stock_basic = _safe_read(db, "stock_basic", ["code", "name", "industry", "list_date", "is_st", "is_listed"])
        stock_daily = _safe_read(
            db,
            "stock_daily",
            ["code", "trade_date", "open", "high", "low", "close", "amount", "pct_chg", "turnover_rate", "is_suspended"],
        )
        index_daily = _safe_read(db, "index_daily", ["index_code", "trade_date", "close", "amount", "pct_chg"])
        sector_daily = _safe_read(db, "sector_daily", ["sector_name", "trade_date", "pct_chg", "amount"])
        latest_trade_date = None if stock_daily.empty else str(stock_daily["trade_date"].max())
        report_date = resolve_report_date(args.date, latest_trade_date)

        if stock_basic.empty or stock_daily.empty:
            logger.warning("本地数据库暂无足够行情数据，请先完成数据初始化或导入历史行情。")
            return None

        eligible, filtered = build_stock_pool(stock_basic, stock_daily, report_date, config.stock_pool)
        market = calculate_market_score(index_daily, stock_daily, report_date)
        sector_scores, strong_sectors = calculate_sector_scores(sector_daily, stock_basic, stock_daily, report_date)
        character = calculate_stock_character_scores(stock_daily, report_date)
        volume_price = calculate_volume_price_scores(stock_daily, report_date)

        latest = _latest_stock_rows(stock_daily, report_date)
        factor_columns = ["code", "pct_chg", "turnover_rate"]
        factors = eligible.drop(columns=[column for column in factor_columns[1:] if column in eligible.columns]).merge(
            latest[factor_columns],
            on="code",
            how="left",
        )
        factors = factors.merge(sector_scores, on=["code", "industry"], how="left")
        factors = factors.merge(character, on="code", how="left")
        factors = factors.merge(volume_price, on="code", how="left")
        strategy_scores = run_enabled_strategies(stock_daily, report_date, factors, config.strategies.enabled)
        factors = factors.merge(strategy_scores, on="code", how="left")
        factors = _add_risk_inputs(factors)
        risk = calculate_risk_penalties(factors, config.risk, config.scoring)
        factors = factors.merge(risk, on="code", how="left")
        ranked, top50, top10 = build_ranked_results(
            factors,
            market,
            config.scoring,
            config.report,
            config.strategies.strategy_score_weight,
        )
        report_path = write_excel_report(config.report.output_dir, report_date, market, strong_sectors, top50, top10, ranked, filtered)

        print(f"今日市场环境：{market['market_label']}")
        print(f"市场风险等级：{market['risk_level']}")
        print(f"上涨家数占比：{market['up_ratio']}%")
        print(f"涨停家数：{market['limit_up_count']}")
        print(f"跌停家数：{market['limit_down_count']}")
        print(f"报告路径：{report_path}")
        return report_path
    except Exception:
        logger.exception("每日任务执行失败")
        raise


if __name__ == "__main__":
    run()
