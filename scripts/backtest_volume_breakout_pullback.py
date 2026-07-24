from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import load_config
from src.strategies.base import build_strategy_history
from src.strategies.volume_breakout_pullback import score_volume_breakout_pullback


DOCUMENT_CASES = [
    ("002832", "比音勒芬", "2026-07-24", "高低点逐步抬高"),
    ("002860", "星帅尔", "2026-07-24", "放量突破后高位整理"),
    ("300667", "必创科技", "2026-05-12", "放量阳线后缩量且不破低点"),
    ("002975", "博杰股份", "2026-05-11", "平台突破回踩后反包"),
    ("002228", "合兴包装", "2025-12-25", "平台突破回踩后反包"),
    ("301171", "易点天下", "2025-11-21", "放量接近前高后缩量抬高"),
    ("600516", "方大炭素", "2025-11-19", "多次涨停且位置抬高"),
    ("002129", "TCL中环", "2025-11-17", "倍量突破后缩量再突破"),
    ("002788", "鹭燕医药", "2025-11-14", "长上影后高低点抬高"),
    ("300300", "海峡创新", "2025-11-13", "首板后守低点并抬高"),
    ("300827", "上能电气", "2025-11-13", "平台上影试盘后承接"),
    ("600556", "天下秀", "2025-11-10", "多次涨停后缩量回调"),
    ("002112", "三变科技", "2025-11-05", "非连板涨停突破回踩"),
    ("300980", "祥源新材", "2025-11-05", "平台回踩后放量破前高"),
    ("600556", "天下秀", "2025-11-05", "近期多次非连续涨停"),
    ("600319", "亚星化学", "2025-11-19", "近期多次非连续涨停"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="回测文档价量二次启动策略")
    parser.add_argument("--database", default="data/stock.db")
    parser.add_argument("--history-start", default="2025-01-01")
    parser.add_argument("--backtest-start", default="2025-07-01")
    parser.add_argument("--backtest-end", default=None)
    parser.add_argument("--sample-window", type=int, default=5)
    parser.add_argument("--cooldown-days", type=int, default=5)
    parser.add_argument("--output-dir", default="artifacts/document_pattern_backtest")
    return parser.parse_args()


def _load_daily(
    database: Path, start: str, end: str | None
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    where = "WHERE d.trade_date >= ?"
    params: list[object] = [start]
    if end:
        where += " AND d.trade_date <= ?"
        params.append(end)
    with sqlite3.connect(database) as connection:
        daily = pd.read_sql_query(
            f"""
            SELECT d.code, d.trade_date, d.open, d.high, d.low, d.close,
                   d.volume, d.amount, d.turnover_rate, d.pct_chg,
                   d.is_suspended
            FROM stock_daily d
            {where}
            ORDER BY d.code, d.trade_date
            """,
            connection,
            params=params,
        )
        basic = pd.read_sql_query(
            """
            SELECT code, name, exchange, industry, list_date, is_st, is_listed
            FROM stock_basic
            """,
            connection,
        )
        index_daily = pd.read_sql_query(
            f"""
            SELECT trade_date, close
            FROM index_daily
            WHERE index_code = 'sh000001'
              AND trade_date >= ?
              {"AND trade_date <= ?" if end else ""}
            ORDER BY trade_date
            """,
            connection,
            params=params,
        )
    return daily, basic, index_daily


def _is_growth_board(code: pd.Series) -> pd.Series:
    return code.astype(str).str.startswith(("300", "301", "688", "689"))


def _is_beijing(code: pd.Series) -> pd.Series:
    return code.astype(str).str.startswith(("4", "8", "92"))


def _add_forward_returns(scored: pd.DataFrame) -> pd.DataFrame:
    result = scored.sort_values(["code", "trade_date"]).copy()
    grouped = result.groupby("code", sort=False)
    result["entry_open"] = grouped["open"].shift(-1)
    result["entry_high"] = grouped["high"].shift(-1)
    result["entry_low"] = grouped["low"].shift(-1)

    raw_return = result["close"] / result["prev_close"].replace(0, pd.NA) - 1
    allowed_move = pd.Series(0.12, index=result.index)
    allowed_move.loc[_is_growth_board(result["code"])] = 0.22
    result["corporate_action_anomaly"] = raw_return.abs().gt(allowed_move)

    next_gain = result["entry_open"] / result["close"].replace(0, pd.NA) - 1
    next_one_price = (
        result["entry_high"].eq(result["entry_low"])
        & result["entry_open"].eq(result["entry_high"])
        & next_gain.ge(
            pd.Series(0.195, index=result.index).where(
                _is_growth_board(result["code"]), 0.095
            )
        )
    )
    result["entry_tradable"] = result["entry_open"].gt(0) & ~next_one_price

    anomaly = result["corporate_action_anomaly"].fillna(False)
    for horizon in (1, 3, 5, 10):
        future_close = grouped["close"].shift(-horizon)
        crosses_anomaly = pd.Series(False, index=result.index)
        for offset in range(1, horizon + 1):
            crosses_anomaly |= anomaly.groupby(result["code"]).shift(-offset).fillna(False)
        returns = (future_close / result["entry_open"] - 1).mul(100)
        result[f"return_{horizon}d"] = returns.where(
            result["entry_tradable"] & ~crosses_anomaly
        )
    return result


def _mark_signals(
    scored: pd.DataFrame,
    cooldown_days: int,
    signal_column: str = "document_pattern_hit",
) -> pd.DataFrame:
    result = scored.copy()
    base_hit = (
        result[signal_column].fillna(False)
        & result["document_pattern_hit"].fillna(False)
        & result["eligible_universe"]
    )
    recent_hit = base_hit.groupby(result["code"]).transform(
        lambda value: value.shift(1).rolling(cooldown_days, min_periods=1).max()
    )
    result["backtest_signal"] = base_hit & recent_hit.fillna(0).eq(0)
    return result


def _sample_coverage(
    scored: pd.DataFrame,
    sample_window: int,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for code, name, target_date, note in DOCUMENT_CASES:
        stock = scored[
            (scored["code"].astype(str) == code)
            & (scored["trade_date"] <= target_date)
        ].tail(sample_window)
        exact = stock[stock["trade_date"] == target_date]
        hits = stock[stock["document_pattern_hit"].fillna(False)]
        exact_hit = bool(
            not exact.empty and exact.iloc[-1]["document_pattern_hit"]
        )
        rows.append(
            {
                "code": code,
                "name": name,
                "target_date": target_date,
                "document_note": note,
                "exact_hit": exact_hit,
                "window_hit": not hits.empty,
                "pool_eligible": (
                    bool(exact.iloc[-1]["eligible_universe"])
                    if not exact.empty
                    else False
                ),
                "assistant_exact_hit": (
                    bool(
                        exact.iloc[-1]["document_pattern_hit"]
                        and exact.iloc[-1]["eligible_universe"]
                    )
                    if not exact.empty
                    else False
                ),
                "latest_hit_date": (
                    str(hits.iloc[-1]["trade_date"]) if not hits.empty else ""
                ),
                "target_score": (
                    float(exact.iloc[-1]["document_pattern_score"])
                    if not exact.empty
                    else None
                ),
                "target_variant": (
                    str(exact.iloc[-1]["document_pattern_variant"])
                    if not exact.empty
                    else ""
                ),
                "target_reason": (
                    str(exact.iloc[-1]["document_pattern_reason"])
                    if not exact.empty
                    else ""
                ),
            }
        )
    return pd.DataFrame(rows)


def _performance(signals: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for horizon in (1, 3, 5, 10):
        values = pd.to_numeric(
            signals[f"return_{horizon}d"], errors="coerce"
        ).dropna()
        rows.append(
            {
                "horizon": f"{horizon}日",
                "samples": int(len(values)),
                "average_return": round(float(values.mean()), 3)
                if not values.empty
                else None,
                "median_return": round(float(values.median()), 3)
                if not values.empty
                else None,
                "win_rate": round(float(values.gt(0).mean() * 100), 2)
                if not values.empty
                else None,
                "p25": round(float(values.quantile(0.25)), 3)
                if not values.empty
                else None,
                "p75": round(float(values.quantile(0.75)), 3)
                if not values.empty
                else None,
            }
        )
    return pd.DataFrame(rows)


def _markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "（无数据）"
    columns = list(frame.columns)
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for row in frame.itertuples(index=False, name=None):
        values = ["" if pd.isna(value) else str(value) for value in row]
        lines.append("| " + " | ".join(value.replace("|", "/") for value in values) + " |")
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    database = Path(args.database)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    config = load_config()
    params = config.strategies.parameters.get("volume_breakout_pullback", {})
    daily, basic, index_daily = _load_daily(
        database, args.history_start, args.backtest_end
    )
    report_end = args.backtest_end or str(daily["trade_date"].max())

    history = build_strategy_history(daily, report_end)
    history["rps20_backtest"] = (
        history.groupby("trade_date")["return_20d"].rank(pct=True).mul(100)
    )
    scored = score_volume_breakout_pullback(history, params)
    index_daily["market_ma20"] = index_daily["close"].rolling(
        20, min_periods=10
    ).mean()
    index_daily["market_uptrend"] = index_daily["close"].ge(
        index_daily["market_ma20"]
    )
    scored = scored.merge(
        index_daily[["trade_date", "market_uptrend"]],
        on="trade_date",
        how="left",
    )
    scored = scored.merge(
        basic[["code", "name", "is_st", "is_listed"]],
        on="code",
        how="left",
    )
    scored["eligible_universe"] = (
        scored["bar_index"].ge(119)
        & scored["close"].ge(config.stock_pool.min_price)
        & scored["amount_ma20"].ge(config.stock_pool.min_avg_amount_20d)
        & scored["is_st"].fillna(0).eq(0)
        & scored["is_listed"].fillna(1).eq(1)
        & ~scored["name"].fillna("").str.contains(r"ST|退", regex=True)
        & ~_is_beijing(scored["code"])
        & scored["is_suspended"].fillna(0).eq(0)
    )

    coverage = _sample_coverage(scored, args.sample_window)
    with_returns = _add_forward_returns(scored)
    observation_frame = _mark_signals(with_returns, args.cooldown_days)
    observation_signals = observation_frame[
        observation_frame["backtest_signal"]
        & observation_frame["trade_date"].ge(args.backtest_start)
        & observation_frame["trade_date"].le(report_end)
    ].copy()
    entry_frame = _mark_signals(
        with_returns, args.cooldown_days, signal_column="document_entry_ready"
    )
    entry_signals = entry_frame[
        entry_frame["backtest_signal"]
        & entry_frame["trade_date"].ge(args.backtest_start)
        & entry_frame["trade_date"].le(report_end)
    ].copy()
    performance = _performance(entry_signals)
    focus_entry_signals = entry_signals[
        entry_signals["market_uptrend"].fillna(False)
        & entry_signals["rps20_backtest"].ge(60)
        & entry_signals["distance_ma20"].le(15)
    ].copy()
    focus_performance = _performance(focus_entry_signals)
    stage_rows: list[dict[str, object]] = []
    for variant, group in observation_signals.groupby(
        "document_pattern_variant", sort=False
    ):
        stage_rows.append(
            {
                "document_pattern_variant": variant,
                "signals": len(group),
                "return_1d": group["return_1d"].mean(),
                "return_3d": group["return_3d"].mean(),
                "return_5d": group["return_5d"].mean(),
                "return_10d": group["return_10d"].mean(),
                "win_rate_5d": group["return_5d"].gt(0).mean() * 100,
            }
        )
    stage_performance = pd.DataFrame(stage_rows).round(3)

    signal_columns = [
        "trade_date",
        "code",
        "name",
        "document_pattern_score",
        "document_pattern_variant",
        "document_pattern_reason",
        "rps20_backtest",
        "market_uptrend",
        "distance_ma20",
        "document_contraction_ratio",
        "close",
        "entry_open",
        "return_1d",
        "return_3d",
        "return_5d",
        "return_10d",
    ]
    coverage.to_csv(output_dir / "document_case_coverage.csv", index=False, encoding="utf-8-sig")
    observation_signals[signal_columns].to_csv(
        output_dir / "observation_signals.csv", index=False, encoding="utf-8-sig"
    )
    entry_signals[signal_columns].to_csv(
        output_dir / "entry_signals.csv", index=False, encoding="utf-8-sig"
    )
    focus_entry_signals[signal_columns].to_csv(
        output_dir / "focus_entry_signals.csv",
        index=False,
        encoding="utf-8-sig",
    )
    performance.to_csv(output_dir / "backtest_summary.csv", index=False, encoding="utf-8-sig")
    focus_performance.to_csv(
        output_dir / "focus_backtest_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    stage_performance.to_csv(
        output_dir / "stage_performance.csv", index=False, encoding="utf-8-sig"
    )

    exact_count = int(coverage["exact_hit"].sum())
    window_count = int(coverage["window_hit"].sum())
    assistant_exact_count = int(coverage["assistant_exact_hit"].sum())
    coverage_view = coverage[
        [
            "code",
            "name",
            "target_date",
            "exact_hit",
            "window_hit",
            "pool_eligible",
            "assistant_exact_hit",
            "latest_hit_date",
            "target_score",
            "target_variant",
        ]
    ].rename(
        columns={
            "code": "代码",
            "name": "名称",
            "target_date": "截图日期",
            "exact_hit": "当日命中",
            "window_hit": f"近{args.sample_window}日命中",
            "pool_eligible": "通过股票池",
            "assistant_exact_hit": "助手当日可见",
            "latest_hit_date": "最近命中日",
            "target_score": "当日分数",
            "target_variant": "当日类型",
        }
    )
    performance_view = performance.rename(
        columns={
            "horizon": "持有期",
            "samples": "样本数",
            "average_return": "平均收益%",
            "median_return": "中位收益%",
            "win_rate": "胜率%",
            "p25": "25分位%",
            "p75": "75分位%",
        }
    )
    stage_view = stage_performance.rename(
        columns={
            "document_pattern_variant": "形态阶段",
            "signals": "信号数",
            "return_1d": "1日平均%",
            "return_3d": "3日平均%",
            "return_5d": "5日平均%",
            "return_10d": "10日平均%",
            "win_rate_5d": "5日胜率%",
        }
    )
    focus_performance_view = focus_performance.rename(
        columns={
            "horizon": "持有期",
            "samples": "样本数",
            "average_return": "平均收益%",
            "median_return": "中位收益%",
            "win_rate": "胜率%",
            "p25": "25分位%",
            "p75": "75分位%",
        }
    )
    report = f"""# 文档价量二次启动策略校准与回测

- 行情范围：{args.history_start} 至 {report_end}
- 回测信号范围：{args.backtest_start} 至 {report_end}
- 文档截图：{len(coverage)} 张，截图当日命中 {exact_count} 张，近 {args.sample_window} 个交易日命中 {window_count} 张
- 按当前股票池过滤后，截图当日可在助手中出现 {assistant_exact_count} 张
- 买入假设：信号日收盘后入选，下一交易日开盘买入
- 去重：同一股票 {args.cooldown_days} 个交易日内只保留首次信号
- 数据处理：下一交易日一字涨停视为无法买入；持有期跨越疑似除权异常跳变时不计算收益

## 文档样本覆盖

{_markdown_table(coverage_view)}

## 全市场近期买入回测

买入子集只使用“放量后缩量承接”阶段；其他阶段仍进入助手观察池，但不直接视为买入信号。

{_markdown_table(performance_view)}

### 叠加助手已有的强弱与大盘过滤

在买入子集上再要求：上证指数位于20日线上方、横截面RPS20不低于60、距离个股20日线不超过15%。

{_markdown_table(focus_performance_view)}

## 各观察阶段对照

{_markdown_table(stage_view)}

> 以上结果仅是历史规则检验，不代表未来收益。未复权通达信数据中的疑似除权跳变已从对应收益样本中排除。
"""
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
