from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from src.build_pool import build_stock_pool
from src.config import AppConfig, load_config
from src.database import Database
from src.fetch_data import DataFetcher
from src.market_score import calculate_market_score
from src.report import write_excel_report
from src.risk_filter import calculate_risk_penalties
from src.scoring import build_ranked_results
from src.sector_score import calculate_sector_scores
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


def update_market_data(
    db: Database,
    config: AppConfig,
    report_date: str,
    init: bool = False,
    fetcher: Any | None = None,
) -> dict[str, int]:
    logger = logging.getLogger(__name__)
    fetcher = fetcher or DataFetcher(config.data.start_date)
    counts = {"stock_basic": 0, "stock_daily": 0, "index_daily": 0, "sector_daily": 0, "failed_symbols": 0}

    if init:
        basic = fetcher.fetch_stock_basic()
        if not basic.empty:
            counts["stock_basic"] = db.upsert_dataframe("stock_basic", basic, ["code"])
    else:
        basic = db.read_table("stock_basic")

    if basic.empty:
        logger.warning("无股票基础信息，跳过行情更新")
        return counts

    for code in basic["code"].dropna().astype(str).tolist():
        try:
            daily = fetcher.fetch_stock_daily(code, end_date=report_date)
            if not daily.empty:
                counts["stock_daily"] += db.upsert_dataframe("stock_daily", daily, ["code", "trade_date"])
        except Exception as exc:
            counts["failed_symbols"] += 1
            logger.warning("[%s] 日线数据更新失败: %s", code, exc)

    for index_code in INDEX_CODES:
        try:
            index_daily = fetcher.fetch_index_daily(index_code, end_date=report_date)
            if not index_daily.empty:
                counts["index_daily"] += db.upsert_dataframe("index_daily", index_daily, ["index_code", "trade_date"])
        except Exception as exc:
            logger.warning("[%s] 指数数据更新失败: %s", index_code, exc)

    try:
        sector_daily = fetcher.fetch_sector_daily(report_date)
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
    factors = _add_risk_inputs(factors)
    risk = calculate_risk_penalties(factors, config.risk, config.scoring)
    factors = factors.merge(risk, on="code", how="left")
    ranked, top50, top10 = build_ranked_results(factors, market, config.scoring, config.report)
    report_path = write_excel_report(config.report.output_dir, report_date, market, strong_sectors, top50, top10, ranked, filtered)

    print(f"今日市场环境：{market['market_label']}")
    print(f"市场风险等级：{market['risk_level']}")
    print(f"上涨家数占比：{market['up_ratio']}%")
    print(f"涨停家数：{market['limit_up_count']}")
    print(f"跌停家数：{market['limit_down_count']}")
    print(f"报告路径：{report_path}")
    return report_path


if __name__ == "__main__":
    run()
