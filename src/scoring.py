from __future__ import annotations

import pandas as pd

from src.config import ReportConfig, ScoringConfig


DEFAULT_STRATEGY_SCORE_WEIGHT = 15


def _weighted(raw: pd.Series, weight: float) -> pd.Series:
    return raw.fillna(0).clip(lower=0, upper=100) / 100 * weight


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
    result["sector_score"] = _weighted(result["sector_score_raw"], scoring.sector_score_weight)
    result["stock_character_score"] = _weighted(result["stock_character_score_raw"], scoring.stock_character_weight)
    result["volume_price_score"] = _weighted(result["volume_price_score_raw"], scoring.volume_price_weight)
    result["strategy_score"] = _weighted(result["strategy_score_raw"], strategy_score_weight)
    result["relative_strength_score"] = _weighted(
        result["rps20"].fillna(0) * 0.6 + result["rps60"].fillna(0) * 0.4,
        scoring.relative_strength_weight,
    )
    result["market_adjust_score"] = float(market.get("market_score", 5)) / 10 * scoring.market_adjust_weight
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
    return result, result.head(report.top_observe).copy(), result.head(report.top_focus).copy()
