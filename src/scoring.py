from __future__ import annotations

import pandas as pd

from src.config import ReportConfig, ScoringConfig
from src.sector_score import market_board


DEFAULT_STRATEGY_SCORE_WEIGHT = 15


def _weighted(raw: pd.Series, weight: float) -> pd.Series:
    return raw.fillna(0).clip(lower=0, upper=100) / 100 * weight


def _calibrate(raw: pd.Series, blend: float) -> pd.Series:
    values = pd.to_numeric(raw, errors="coerce").fillna(0).clip(lower=0, upper=100)
    if blend <= 0:
        return values
    percentile = pd.Series(0.0, index=values.index)
    positive = values.gt(0)
    if positive.any():
        percentile.loc[positive] = values.loc[positive].rank(method="average", pct=True) * 100
    return values * (1 - blend) + percentile * blend


def select_report_candidates(
    ranked: pd.DataFrame,
    report: ReportConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    def select(limit: int, minimum: float) -> pd.DataFrame:
        selected: list[int] = []
        industry_counts: dict[str, int] = {}
        board_counts: dict[str, int] = {}
        for index, row in ranked.iterrows():
            if float(row.get("total_score", 0) or 0) < minimum:
                continue
            code = str(row.get("code", ""))
            board = market_board(code)
            source = str(row.get("industry_source", "") or "")
            industry = str(row.get("industry", "") or "").strip()
            if board_counts.get(board, 0) >= report.max_per_market_board:
                continue
            is_real_industry = bool(industry) and source != "market_board_fallback"
            if is_real_industry and industry_counts.get(industry, 0) >= report.max_per_industry:
                continue
            selected.append(index)
            board_counts[board] = board_counts.get(board, 0) + 1
            if is_real_industry:
                industry_counts[industry] = industry_counts.get(industry, 0) + 1
            if len(selected) >= limit:
                break
        return ranked.loc[selected].copy().reset_index(drop=True)

    return (
        select(report.top_observe, report.min_observe_score),
        select(report.top_focus, report.min_focus_score),
    )


def _reason(row: pd.Series) -> str:
    parts: list[str] = []
    for column in ["sector_reason", "character_reason", "volume_price_reason", "strategy_reason"]:
        value = str(row.get(column, "") or "")
        if value:
            parts.append(value)
    if row.get("rps20", 0) >= 80:
        parts.append("RPS20 居前")
    return "；".join(parts)


def _next_day_condition(row: pd.Series, market: dict[str, object]) -> str:
    if market.get("market_label") == "偏弱":
        return "大盘偏弱，降低关注优先级，等待板块和成交量确认"
    if row.get("amount_ratio", 0) >= 1.5 and row.get("rps20", 0) >= 80:
        return "不追高，观察是否回踩 5 日线不破；若板块继续走强再重点观察"
    return "观察是否放量突破前高，弱于板块时降低优先级"


def _ensure_columns(result: pd.DataFrame) -> pd.DataFrame:
    defaults: dict[str, object] = {
        "sector_score_raw": 0,
        "stock_character_score_raw": 0,
        "volume_price_score_raw": 0,
        "strategy_score_raw": 0,
        "rps20": 0,
        "rps60": 0,
        "risk_penalty": 0,
        "strategy_reason": "",
        "matched_strategies": "",
    }
    for column, default in defaults.items():
        if column not in result.columns:
            result[column] = default
    return result


def build_ranked_results(
    factors: pd.DataFrame,
    market: dict[str, object],
    scoring: ScoringConfig,
    report: ReportConfig,
    strategy_score_weight: float = DEFAULT_STRATEGY_SCORE_WEIGHT,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    result = _ensure_columns(factors.copy())
    calibrated_columns: dict[str, pd.Series] = {}
    for column in (
        "sector_score_raw",
        "stock_character_score_raw",
        "volume_price_score_raw",
        "strategy_score_raw",
        "rps20",
        "rps60",
    ):
        calibrated_columns[column] = _calibrate(result[column], scoring.factor_percentile_blend)
        result[f"{column}_calibrated"] = calibrated_columns[column].round(2)
    result["sector_score"] = _weighted(calibrated_columns["sector_score_raw"], scoring.sector_score_weight)
    result["stock_character_score"] = _weighted(calibrated_columns["stock_character_score_raw"], scoring.stock_character_weight)
    result["volume_price_score"] = _weighted(calibrated_columns["volume_price_score_raw"], scoring.volume_price_weight)
    result["strategy_score"] = _weighted(calibrated_columns["strategy_score_raw"], strategy_score_weight)
    result["relative_strength_score"] = _weighted(
        calibrated_columns["rps20"] * 0.6 + calibrated_columns["rps60"] * 0.4,
        scoring.relative_strength_weight,
    )
    relative_strength_raw = calibrated_columns["rps20"] * 0.6 + calibrated_columns["rps60"] * 0.4
    setup_strength = (
        calibrated_columns["volume_price_score_raw"] * 0.45
        + calibrated_columns["strategy_score_raw"] * 0.35
        + relative_strength_raw * 0.20
    ).clip(lower=0, upper=100) / 100
    market_regime = max(-1.0, min(1.0, (float(market.get("market_score", 5)) - 5) / 5))
    result["market_adjust_score"] = (
        setup_strength * market_regime * scoring.market_adjust_weight
    ).round(2)
    result["total_score"] = (
        result["sector_score"]
        + result["stock_character_score"]
        + result["volume_price_score"]
        + result["strategy_score"]
        + result["relative_strength_score"]
        + result["market_adjust_score"]
        - result["risk_penalty"].fillna(0)
    ).clip(lower=0, upper=100).round(2)
    result["selection_reason"] = result.apply(_reason, axis=1)
    result["next_day_condition"] = result.apply(lambda row: _next_day_condition(row, market), axis=1)
    result = result.sort_values("total_score", ascending=False).reset_index(drop=True)
    result.insert(0, "rank", range(1, len(result) + 1))
    top_observe, top_focus = select_report_candidates(result, report)
    return result, top_observe, top_focus
