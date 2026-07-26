from __future__ import annotations

import argparse
import logging
from contextlib import contextmanager, nullcontext
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd

from src.build_pool import build_stock_pool
from src.config import AppConfig, load_config
from src.custom_formulas import FormulaConfigError, evaluate_custom_formulas
from src.database import Database
from src.fetch_data import (
    TDX_PRICE_BASIS,
    AkshareDataFetcher,
    DataFetcher,
    TdxDataFetcher,
    fetch_stock_daily_parallel,
    fetch_tdx_stock_daily_parallel,
)
from src.market_score import calculate_market_score
from src.report import write_excel_report
from src.risk_filter import calculate_risk_penalties
from src.scoring import build_ranked_results
from src.sector_score import build_market_board_daily, calculate_sector_scores, fill_market_board_industry
from src.strategies.registry import (
    build_strategy_screener_data,
    evaluate_enabled_strategies,
)
from src.stock_character import calculate_stock_character_scores
from src.stock_context import enrich_ranked_context
from src.volume_price_score import calculate_volume_price_scores
from src.web_report import build_report_payload, write_static_report

INDEX_CODES = ("sh000001", "sz399001", "sz399006")
POST_MARKET_CUTOFF_MINUTES = 15 * 60 + 10


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A 股盘后多因子选股助手")
    parser.add_argument("--init", action="store_true", help="初始化并回填历史数据")
    parser.add_argument("--date", help="指定报告日期，格式 YYYY-MM-DD")
    parser.add_argument("--offline", action="store_true", help="仅使用本地数据库重算策略和报告，不连接行情源")
    parser.add_argument(
        "--snapshot",
        choices=("auto", "intraday", "close"),
        default="auto",
        help="报告阶段：自动判断、盘中快照或盘后正式报告",
    )
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


def resolve_snapshot_type(
    requested: str,
    report_date: str,
    now: datetime | None = None,
) -> str:
    if requested in {"intraday", "close"}:
        return requested
    current = now or datetime.now()
    if report_date != current.date().isoformat():
        return "close"
    current_minutes = current.hour * 60 + current.minute
    return "intraday" if current_minutes < POST_MARKET_CUTOFF_MINUTES else "close"


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


def _next_fetch_start(
    latest_date: str | None,
    fallback_start: str,
    refresh_date: str | None = None,
) -> str:
    if not latest_date:
        return fallback_start
    if refresh_date is not None and str(latest_date) == refresh_date:
        return refresh_date
    parsed = datetime.strptime(str(latest_date), "%Y-%m-%d").date()
    return (parsed + timedelta(days=1)).strftime("%Y-%m-%d")


def _should_fetch(start_date: str, end_date: str) -> bool:
    return start_date <= end_date


def _is_baostock_rate_limit_error(error: object) -> bool:
    message = str(error).lower()
    return "blacklist" in message or "rate limit" in message or "\u9ed1\u540d\u5355" in str(error)



def _data_provider(config: AppConfig) -> str:
    return (config.data.provider or "tdx").strip().lower()


def _create_tdx_fetcher(config: AppConfig) -> TdxDataFetcher:
    return TdxDataFetcher(
        config.data.start_date,
        timeout_seconds=config.data.tdx_timeout_seconds,
        query_retries=config.data.tdx_query_retries,
    )


def _create_configured_fetcher(config: AppConfig) -> Any:
    provider = _data_provider(config)
    if provider == "tdx":
        return _create_tdx_fetcher(config)
    if provider in {"akshare", "eastmoney"}:
        return AkshareDataFetcher(config.data.start_date)
    return DataFetcher(
        config.data.start_date,
        query_retries=config.data.baostock_query_retries,
        reconnect_interval=config.data.baostock_reconnect_interval,
    )


def _allows_tdx_fallback(config: AppConfig) -> bool:
    return _data_provider(config) in {"mixed", "auto", ""}


@contextmanager
def _open_configured_fetcher(fetcher: Any | None, config: AppConfig, external_fetcher: bool):
    provider = _data_provider(config)
    active_context = _managed_fetcher(fetcher or _create_configured_fetcher(config))
    parallel_backend: str | None = None
    if not external_fetcher:
        if provider == "tdx":
            parallel_backend = "tdx"
        elif provider not in {"akshare", "eastmoney"}:
            parallel_backend = "baostock"
    try:
        active_fetcher = active_context.__enter__()
    except Exception as exc:
        if external_fetcher or not _allows_tdx_fallback(config) or not _is_baostock_rate_limit_error(exc):
            raise
        logging.getLogger(__name__).warning("baostock login blocked; fallback to TDX without another baostock attempt: %s", exc)
        active_context = _managed_fetcher(_create_tdx_fetcher(config))
        active_fetcher = active_context.__enter__()
        parallel_backend = "tdx"
    try:
        yield active_fetcher, parallel_backend
    finally:
        active_context.__exit__(None, None, None)

def validate_initialization(db: Database, config: AppConfig) -> dict[str, object]:
    health = db.data_health()
    problems: list[str] = []
    coverage = float(health["stock_coverage"])
    daily_rows = int(health["daily_rows"])
    index_symbols = int(health["index_symbols"])
    if int(health["active_symbols"]) < 1:
        problems.append("stock_basic is empty")
    if coverage < config.data.init_min_stock_coverage:
        problems.append(
            f"stock coverage {coverage:.1%} is below {config.data.init_min_stock_coverage:.1%}"
        )
    if daily_rows < config.data.init_min_daily_rows:
        problems.append(f"daily rows {daily_rows} is below {config.data.init_min_daily_rows}")
    if index_symbols < config.data.init_min_index_count:
        problems.append(f"index count {index_symbols} is below {config.data.init_min_index_count}")
    logging.getLogger(__name__).info(
        "initialization health: active=%s covered=%s coverage=%.1f%% rows=%s indexes=%s latest=%s latest_symbols=%s",
        health["active_symbols"],
        health["covered_symbols"],
        coverage * 100,
        daily_rows,
        index_symbols,
        health["latest_trade_date"],
        health["latest_symbol_count"],
    )
    if problems:
        raise RuntimeError("initialization data validation failed: " + "; ".join(problems))
    return health


def validate_latest_coverage(health: dict[str, object], minimum: float) -> None:
    coverage = float(health.get("latest_stock_coverage", 0) or 0)
    if coverage < minimum:
        raise RuntimeError(
            f"latest trading-day stock coverage {coverage:.1%} is below {minimum:.1%}"
        )


def summarize_run_error(error: object) -> str:
    message = str(error)
    if "all configured TDX hosts failed" in message:
        return "TDX 行情服务器暂时无法连接（已尝试全部节点），本次未更新数据，请稍后重试。"
    return message[:2000]


def update_market_data(
    db: Database,
    config: AppConfig,
    report_date: str,
    init: bool = False,
    fetcher: Any | None = None,
    refresh_latest: bool = False,
) -> dict[str, int]:
    logger = logging.getLogger(__name__)
    external_fetcher = fetcher is not None
    counts = {"stock_basic": 0, "stock_daily": 0, "index_daily": 0, "sector_daily": 0, "failed_symbols": 0}

    with _open_configured_fetcher(fetcher, config, external_fetcher) as (active_fetcher, parallel_backend):
        if init:
            try:
                basic = active_fetcher.fetch_stock_basic()
            except Exception as exc:
                fallback_basic = _safe_read(
                    db,
                    "stock_basic",
                    ["code", "name", "exchange", "industry", "list_date", "is_st", "is_listed"],
                )
                if fallback_basic.empty:
                    raise
                logger.warning("股票基础信息更新失败，使用本地已有股票列表继续初始化: %s", exc)
                basic = fallback_basic
            else:
                if not basic.empty:
                    if not external_fetcher and len(basic) >= 1000:
                        db.mark_all_stocks_unlisted()
                    counts["stock_basic"] = db.upsert_dataframe("stock_basic", basic, ["code"])
                else:
                    fallback_basic = _safe_read(
                        db,
                        "stock_basic",
                        ["code", "name", "exchange", "industry", "list_date", "is_st", "is_listed"],
                    )
                    if not fallback_basic.empty:
                        logger.warning("股票基础信息接口返回空数据，使用本地已有股票列表继续初始化")
                        basic = fallback_basic
        else:
            basic = db.read_table("stock_basic")

        if basic.empty:
            logger.warning("无股票基础信息，跳过行情更新")
            return counts

        latest_stock_dates = db.latest_dates("stock_daily", "code")
        latest_index_dates = db.latest_dates("index_daily", "index_code")
        active_basic = basic.copy()
        if "is_listed" in active_basic.columns:
            active_basic = active_basic[pd.to_numeric(active_basic["is_listed"], errors="coerce").fillna(1).eq(1)]
        codes = active_basic["code"].dropna().astype(str).str.zfill(6).drop_duplicates().tolist()
        total = len(codes)
        skipped_symbols = 0
        tdx_managed = parallel_backend == "tdx"
        synced_codes: set[str] = set()
        if tdx_managed:
            synced_codes = db.get_synced_codes("tdx", TDX_PRICE_BASIS, config.data.start_date)
            if init:
                logger.info(
                    "TDX price-basis resume state: %s/%s symbols already migrated; updates remain incremental",
                    len(synced_codes),
                    total,
                )

        stock_tasks: list[tuple[str, str, str]] = []
        for code in codes:
            if tdx_managed and init and code not in synced_codes:
                fetch_start = config.data.start_date
            else:
                fetch_start = _next_fetch_start(
                    latest_stock_dates.get(code),
                    config.data.start_date,
                    report_date if refresh_latest else None,
                )
            if not _should_fetch(fetch_start, report_date):
                skipped_symbols += 1
                continue
            stock_tasks.append((code, fetch_start, report_date))

        task_by_code = {task[0]: task for task in stock_tasks}

        def record_tdx_sync(daily: pd.DataFrame) -> None:
            if not tdx_managed or daily.empty or "code" not in daily.columns:
                return
            records: list[dict[str, object]] = []
            for code, group in daily.groupby("code"):
                normalized_code = str(code).zfill(6)
                task = task_by_code.get(normalized_code)
                if task is None:
                    continue
                if normalized_code not in synced_codes and task[1] != config.data.start_date:
                    continue
                records.append(
                    {
                        "code": normalized_code,
                        "provider": "tdx",
                        "price_basis": TDX_PRICE_BASIS,
                        "start_date": config.data.start_date,
                        "end_date": task[2],
                        "row_count": len(group),
                        "last_error": None,
                        "updated_at": datetime.now().isoformat(timespec="seconds"),
                    }
                )
            if records:
                db.upsert_dataframe(
                    "stock_sync_status",
                    pd.DataFrame(records),
                    ["code", "provider", "price_basis", "start_date"],
                )
                synced_codes.update(str(record["code"]) for record in records)

        def store_daily(daily: pd.DataFrame) -> None:
            if daily.empty:
                return
            counts["stock_daily"] += db.upsert_dataframe("stock_daily", daily, ["code", "trade_date"])
            record_tdx_sync(daily)

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
                    if daily.empty:
                        raise RuntimeError("data provider returned no daily rows")
                    store_daily(daily)
                except Exception as exc:
                    counts["failed_symbols"] += 1
                    logger.warning("[%s] stock daily update failed after retry: %s", code, exc)

        use_parallel_stock_fetch = bool(stock_tasks) and parallel_backend is not None
        if parallel_backend == "tdx":
            workers = config.data.tdx_parallel_workers
            chunk_size = config.data.tdx_parallel_chunk_size
        else:
            workers = config.data.baostock_parallel_workers
            chunk_size = config.data.baostock_parallel_chunk_size
        use_parallel_stock_fetch = use_parallel_stock_fetch and workers > 1

        if use_parallel_stock_fetch:
            logger.info(
                "%s parallel stock daily update: %s/%s symbols, workers=%s, chunk_size=%s",
                parallel_backend.upper(),
                len(stock_tasks),
                total,
                workers,
                chunk_size,
            )
            retry_tasks: dict[str, tuple[str, str, str]] = {}
            processed_symbols = 0
            try:
                if parallel_backend == "tdx":
                    batches = fetch_tdx_stock_daily_parallel(
                        stock_tasks,
                        workers=workers,
                        chunk_size=chunk_size,
                        timeout_seconds=config.data.tdx_timeout_seconds,
                        query_retries=config.data.tdx_query_retries,
                    )
                else:
                    batches = fetch_stock_daily_parallel(
                        stock_tasks,
                        workers=workers,
                        chunk_size=chunk_size,
                        query_retries=config.data.baostock_query_retries,
                        reconnect_interval=config.data.baostock_reconnect_interval,
                    )
                for daily, failures, requested in batches:
                    processed_symbols += requested
                    for code, error in failures:
                        task = task_by_code.get(code)
                        if parallel_backend == "baostock" and _is_baostock_rate_limit_error(error):
                            counts["failed_symbols"] += 1
                            logger.warning("[%s] stock daily blocked by baostock; no immediate retry: %s", code, error)
                        elif task is not None:
                            retry_tasks[code] = task
                            logger.warning("[%s] parallel stock daily fetch failed; queued for one retry: %s", code, error)
                        else:
                            counts["failed_symbols"] += 1
                            logger.warning("[%s] stock daily update failed: %s", code, error)
                    store_daily(daily)
                    logger.info("%s stock daily progress: %s/%s symbols", parallel_backend.upper(), processed_symbols, len(stock_tasks))
            except Exception as exc:
                if parallel_backend == "tdx":
                    raise RuntimeError(f"TDX parallel stock fetch aborted: {exc}") from exc
                logger.warning("parallel stock daily update failed, fallback to sequential mode: %s", exc)
                use_parallel_stock_fetch = False
            else:
                retry_limit = max(20, int(len(stock_tasks) * 0.10))
                if parallel_backend == "tdx" and len(retry_tasks) > retry_limit:
                    counts["failed_symbols"] += len(retry_tasks)
                    logger.error(
                        "TDX circuit breaker opened: %s failures exceed retry limit %s; stop instead of looping for hours",
                        len(retry_tasks),
                        retry_limit,
                    )
                else:
                    retry_stock_tasks_sequentially(list(retry_tasks.values()), "parallel failures")

        if not use_parallel_stock_fetch:
            retry_stock_tasks_sequentially(stock_tasks, "sequential mode")

        if skipped_symbols:
            logger.info("skipped %s symbols already updated to %s", skipped_symbols, report_date)

        for index_code in INDEX_CODES:
            fetch_start = _next_fetch_start(
                latest_index_dates.get(index_code),
                config.data.start_date,
                report_date if refresh_latest else None,
            )
            if not _should_fetch(fetch_start, report_date):
                logger.info("指数日线已是最新，跳过: %s", index_code)
                continue
            try:
                logger.info("正在更新指数日线: %s (%s -> %s)", index_code, fetch_start, report_date)
                index_daily = active_fetcher.fetch_index_daily(index_code, start_date=fetch_start, end_date=report_date)
                if index_daily.empty:
                    raise RuntimeError("data provider returned no index rows")
                counts["index_daily"] += db.upsert_dataframe("index_daily", index_daily, ["index_code", "trade_date"])
            except Exception as exc:
                logger.warning("[%s] 指数数据更新失败: %s", index_code, exc)

        if config.features.enable_sector_score:
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
    snapshot_type = "close" if args.init else resolve_snapshot_type(args.snapshot, preliminary_date)
    setup_logging(preliminary_date)
    logger = logging.getLogger(__name__)
    run_id = uuid4().hex
    db: Database | None = None
    run_started = False
    report_path: Path | None = None
    html_path: Path | None = None
    final_report_date = preliminary_date

    try:
        config = load_config()
        db = Database(config.data.database)
        db.initialize()
        run_mode = "init" if args.init else ("intraday" if snapshot_type == "intraday" else "daily")
        db.start_run(run_id, run_mode, preliminary_date)
        run_started = True

        existing_basic = _safe_read(
            db,
            "stock_basic",
            ["code", "name", "industry", "list_date", "is_st", "is_listed"],
        )
        if args.init:
            logger.info("初始化模式已启动，开始更新免费数据源")
            update_market_data(db, config, preliminary_date, init=True)
            validate_initialization(db, config)
        elif args.offline:
            logger.info("离线重算模式已启动，跳过行情更新并使用现有本地数据")
        elif not existing_basic.empty:
            logger.info("开始执行%s数据更新", "盘中快照" if snapshot_type == "intraday" else "每日增量")
            update_market_data(
                db,
                config,
                preliminary_date,
                init=False,
                refresh_latest=preliminary_date == date.today().isoformat(),
            )

        stock_basic = _safe_read(
            db,
            "stock_basic",
            ["code", "name", "industry", "list_date", "is_st", "is_listed"],
        )
        health = db.data_health()
        latest_trade_date = health.get("latest_trade_date")
        report_date = resolve_report_date(args.date, str(latest_trade_date) if latest_trade_date else None)
        final_report_date = report_date
        if snapshot_type == "intraday" and report_date != preliminary_date:
            message = f"当前日期 {preliminary_date} 尚无盘中日线，已跳过快照，最新交易日为 {report_date}"
            logger.info(message)
            db.finish_run(run_id, "skipped", report_date=report_date, message=message)
            return None
        if not args.offline and report_date == preliminary_date:
            validate_latest_coverage(health, config.data.min_latest_stock_coverage)
        analysis_start = (
            datetime.strptime(report_date, "%Y-%m-%d").date()
            - timedelta(days=config.data.analysis_lookback_days)
        ).strftime("%Y-%m-%d")
        stock_daily = db.read_table_between("stock_daily", "trade_date", analysis_start, report_date)
        index_daily = db.read_table_between("index_daily", "trade_date", analysis_start, report_date)
        sector_daily = db.read_table_between("sector_daily", "trade_date", analysis_start, report_date)
        stock_basic = fill_market_board_industry(stock_basic)
        if config.features.enable_sector_score and sector_daily.empty:
            logger.info("外部行业数据不可用，使用本地市场板块聚合评分")
            sector_daily = build_market_board_daily(stock_basic, stock_daily)

        if stock_basic.empty or stock_daily.empty:
            message = "本地数据库暂无足够行情数据，请先完成数据初始化或导入历史行情。"
            logger.warning(message)
            db.finish_run(run_id, "failed", report_date=report_date, message=message)
            return None

        eligible, filtered = build_stock_pool(stock_basic, stock_daily, report_date, config.stock_pool)
        market = calculate_market_score(index_daily, stock_daily, report_date, stock_basic)
        sector_scores, strong_sectors = calculate_sector_scores(
            sector_daily,
            stock_basic,
            stock_daily,
            report_date,
        )
        character = calculate_stock_character_scores(stock_daily, report_date, stock_basic)
        volume_price = calculate_volume_price_scores(stock_daily, report_date)

        latest = _latest_stock_rows(stock_daily, report_date)
        factor_columns = ["code", "pct_chg", "turnover_rate"]
        factors = eligible.drop(
            columns=[column for column in factor_columns[1:] if column in eligible.columns]
        ).merge(latest[factor_columns], on="code", how="left")
        factors = factors.merge(sector_scores, on=["code", "industry"], how="left")
        factors = factors.merge(character, on="code", how="left")
        factors = factors.merge(volume_price, on="code", how="left")
        strategy_evaluation = evaluate_enabled_strategies(
            stock_daily,
            report_date,
            factors,
            config.strategies.enabled,
            config.strategies.parameters,
        )
        factors = factors.merge(strategy_evaluation.aggregate, on="code", how="left")
        factors = _add_risk_inputs(factors)
        risk = calculate_risk_penalties(factors, config.risk, config.scoring)
        factors = factors.merge(risk, on="code", how="left")
        ranked, _top50, _top10 = build_ranked_results(
            factors,
            market,
            config.scoring,
            config.report,
            config.strategies.strategy_score_weight,
        )
        try:
            ranked = enrich_ranked_context(db, ranked, report_date, config.features)
        except Exception as exc:
            logger.warning("个股行业与题材说明更新失败，继续使用基础评分结果: %s", exc)
        strategy_screeners, strategy_screener_results = build_strategy_screener_data(
            strategy_evaluation.hits,
            ranked,
            config.strategies.enabled,
            config.strategies.top_per_strategy,
        )
        custom_strategies: list[dict[str, Any]] = []
        custom_strategy_results = pd.DataFrame()
        try:
            custom_strategies, custom_strategy_results = evaluate_custom_formulas(
                stock_daily,
                report_date,
                ranked,
                Path("config") / "custom_strategies.yml",
            )
            logger.info(
                "自定义公式筛选完成：%s 个公式，%s 条命中记录",
                len(custom_strategies),
                len(custom_strategy_results),
            )
        except (FormulaConfigError, OSError, ValueError) as exc:
            logger.warning("自定义公式配置异常，已跳过且不影响主任务: %s", exc)
        top50 = ranked.head(config.report.top_observe).copy()
        top10 = ranked.head(config.report.top_focus).copy()

        if snapshot_type == "close":
            db.save_selections(report_date, ranked, config.report.top_observe)
            updated_returns = db.refresh_selection_returns()
            logger.info("已更新 %s 条历史入选收益", updated_returns)
        else:
            logger.info("盘中快照不写入正式入选与未来收益历史")
        performance = db.strategy_performance()
        health = db.data_health()

        report_path = write_excel_report(
            config.report.output_dir,
            report_date,
            market,
            strong_sectors,
            top50,
            top10,
            ranked,
            filtered,
            strategy_performance=performance,
            health=health,
            custom_strategy_results=custom_strategy_results,
            snapshot_type=snapshot_type,
        )
        payload = build_report_payload(
            report_date,
            market,
            strong_sectors,
            top50,
            top10,
            performance,
            health,
            strategy_screeners=strategy_screeners,
            strategy_screener_results=strategy_screener_results,
            custom_strategies=custom_strategies,
            custom_strategy_results=custom_strategy_results,
            snapshot_type=snapshot_type,
        )
        html_path = write_static_report(
            config.report.site_dir,
            payload,
            history_days=config.report.history_days,
        )
        db.finish_run(
            run_id,
            "success",
            report_date=report_date,
            message=(
                f"生成盘中快照：Top{len(top50)} 观察名单和 Top{len(top10)} 重点关注"
                if snapshot_type == "intraday"
                else f"生成 Top{len(top50)} 观察名单和 Top{len(top10)} 重点关注"
            ),
            report_path=str(report_path),
            html_path=str(html_path),
        )

        print(f"报告阶段：{'盘中快照' if snapshot_type == 'intraday' else '盘后正式报告'}")
        print(f"今日市场环境：{market['market_label']}")
        print(f"市场风险等级：{market['risk_level']}")
        print(f"上涨家数占比：{market['up_ratio']}%")
        print(f"涨停家数：{market['limit_up_count']}")
        print(f"跌停家数：{market['limit_down_count']}")
        print(f"Excel 报告：{report_path}")
        print(f"网页报告：{html_path}")
        return report_path
    except Exception as exc:
        if db is not None and run_started:
            try:
                db.finish_run(
                    run_id,
                    "failed",
                    report_date=final_report_date,
                    message=summarize_run_error(exc),
                    report_path=str(report_path or ""),
                    html_path=str(html_path or ""),
                )
            except Exception:
                logger.exception("任务状态写入失败")
        logger.exception("每日任务执行失败")
        raise


if __name__ == "__main__":
    run()
