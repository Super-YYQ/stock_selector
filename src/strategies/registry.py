from __future__ import annotations

import json
from dataclasses import dataclass

import pandas as pd

from src.strategies.base import build_strategy_features
from src.strategies.box_breakout import BoxBreakoutStrategy
from src.strategies.double_bottom import DoubleBottomStrategy
from src.strategies.first_pullback import FirstPullbackStrategy
from src.strategies.ma_convergence_breakout import MaConvergenceBreakoutStrategy
from src.strategies.limit_up_shakeout import LimitUpShakeoutStrategy
from src.strategies.low_volatility_rps import LowVolatilityRpsStrategy
from src.strategies.ma_volume import MaVolumeStrategy
from src.strategies.pullback_stable import PullbackStableStrategy
from src.strategies.rps_breakout import RpsBreakoutStrategy
from src.strategies.sector_leader import SectorLeaderStrategy
from src.strategies.trend_pullback_reversal import TrendPullbackReversalStrategy
from src.strategies.turtle_breakout import TurtleBreakoutStrategy
from src.strategies.volume_breakout_pullback import VolumeBreakoutPullbackStrategy
from src.strategies.volatility_squeeze import VolatilitySqueezeStrategy


STRATEGY_CLASSES = [
    MaVolumeStrategy,
    TurtleBreakoutStrategy,
    RpsBreakoutStrategy,
    PullbackStableStrategy,
    LimitUpShakeoutStrategy,
    VolatilitySqueezeStrategy,
    TrendPullbackReversalStrategy,
    LowVolatilityRpsStrategy,
    FirstPullbackStrategy,
    VolumeBreakoutPullbackStrategy,
    SectorLeaderStrategy,
    MaConvergenceBreakoutStrategy,
    BoxBreakoutStrategy,
    DoubleBottomStrategy,
]
STRATEGY_REGISTRY = {strategy.key: strategy for strategy in STRATEGY_CLASSES}

# Columns computed on the strategy feature frame that the main pipeline also
# needs as risk-penalty inputs (calculate_risk_penalties reads them on `factors`).
# evaluate_enabled_strategies carries them onto the aggregate so the existing
# `factors.merge(aggregate)` wires them through; without this they stayed inside
# the internal feature frame and risk_filter saw zeros.
RISK_INPUT_COLUMNS = ["return_5d", "return_10d", "distance_ma20", "volatility_20d"]

STRATEGY_HIT_COLUMNS = [
    "code",
    "strategy_key",
    "strategy",
    "strategy_family",
    "strategy_score_raw",
    "strategy_score_effective",
    "strategy_hit_rate",
    "strategy_selectivity_multiplier",
    "strategy_reason",
]
STRATEGY_SCREENER_RESULT_COLUMNS = [
    "single_strategy_rank",
    "single_strategy_key",
    "single_strategy_name",
    "single_strategy_family",
    "single_strategy_score",
    "single_strategy_reason",
    "code",
    "name",
    "industry",
    "sector",
    "market_board",
    "concepts",
    "total_score",
    "close",
    "pct_chg",
    "amount_ratio",
    "rps20",
    "distance_ma20",
    "sector_score",
    "stock_character_score",
    "volume_price_score",
    "relative_strength_score",
    "strategy_score",
    "market_adjust_score",
    "risk_penalty",
    "stock_context_summary",
    "industry_activity",
    "limit_up_reason",
    "reason_tags",
    "matched_strategies",
    "selection_reason",
    "selection_reason_short",
    "next_day_condition",
    "risk_warning",
]

STRATEGY_PROFILES = {
    "balanced": list(STRATEGY_REGISTRY),
    "breakout": [
        "ma_volume",
        "turtle_breakout",
        "rps_breakout",
        "volatility_squeeze",
        "sector_leader",
    ],
    "pullback": [
        "pullback_stable",
        "limit_up_shakeout",
        "trend_pullback_reversal",
        "first_pullback",
        "volume_breakout_pullback",
    ],
    "steady": [
        "rps_breakout",
        "low_volatility_rps",
        "trend_pullback_reversal",
        "sector_leader",
    ],
}


def strategy_catalog() -> list[dict[str, object]]:
    return [
        {
            "key": strategy.key,
            "name": strategy.name,
            "family": strategy.family,
            "description": strategy.description,
            "score": strategy.score,
            "origin": "custom" if strategy.key == "volume_breakout_pullback" else "builtin",
        }
        for strategy in STRATEGY_CLASSES
    ]


def _empty_strategy_result(codes: pd.DataFrame) -> pd.DataFrame:
    result = codes.copy()
    result["strategy_score_raw"] = 0.0
    result["matched_strategies"] = ""
    result["strategy_reason"] = ""
    result["strategy_hit_count"] = 0
    result["strategy_family_count"] = 0
    result["strategy_families"] = ""
    result["strategy_details"] = "[]"
    for column in RISK_INPUT_COLUMNS:
        result[column] = pd.NA
    return result


@dataclass(frozen=True)
class StrategyEvaluation:
    aggregate: pd.DataFrame
    hits: pd.DataFrame


def _aggregate_code_hits(group: pd.DataFrame) -> pd.Series:
    score_column = "strategy_score_effective" if "strategy_score_effective" in group.columns else "strategy_score_raw"
    family_scores = group.groupby("strategy_family")[score_column].max()
    details = [
        {
            "key": row.strategy_key,
            "name": row.strategy,
            "family": row.strategy_family,
            "score": float(row.strategy_score_raw),
            "effective_score": float(getattr(row, "strategy_score_effective", row.strategy_score_raw)),
            "hit_rate": float(getattr(row, "strategy_hit_rate", 0.0)),
            "reason": row.strategy_reason,
        }
        for row in group.itertuples(index=False)
    ]
    return pd.Series(
        {
            "strategy_score_raw": min(float(family_scores.sum()), 100.0),
            "matched_strategies": "、".join(dict.fromkeys(group["strategy"].astype(str))),
            "strategy_reason": "；".join(dict.fromkeys(group["strategy_reason"].astype(str))),
            "strategy_hit_count": int(len(group)),
            "strategy_family_count": int(group["strategy_family"].nunique()),
            "strategy_families": "、".join(dict.fromkeys(group["strategy_family"].astype(str))),
            "strategy_details": json.dumps(details, ensure_ascii=False),
        }
    )


def _merge_risk_inputs(result: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    """Carry risk-penalty inputs from the strategy feature frame onto the aggregate.

    ``return_5d``/``return_10d``/``distance_ma20``/``volatility_20d`` are computed
    on the shared feature frame and never re-computed elsewhere, so without this
    merge they would be missing from ``factors`` and ``calculate_risk_penalties``
    would see zeros. Codes absent from the feature frame keep NA, which
    ``risk_filter._number`` already coerces to 0.0.
    """
    available = [column for column in RISK_INPUT_COLUMNS if column in features.columns]
    if not available or "code" not in features.columns:
        for column in RISK_INPUT_COLUMNS:
            if column not in result.columns:
                result[column] = pd.NA
        return result
    supplement = features[["code", *available]].drop_duplicates("code")
    existing = [column for column in available if column in result.columns]
    result = result.drop(columns=existing, errors="ignore").merge(
        supplement, on="code", how="left"
    )
    for column in RISK_INPUT_COLUMNS:
        if column not in result.columns:
            result[column] = pd.NA
    return result


def evaluate_enabled_strategies(
    daily: pd.DataFrame,
    report_date: str,
    factors: pd.DataFrame,
    enabled: list[str],
    parameters: dict[str, dict[str, object]] | None = None,
    max_scoring_hit_rate: float = 1.0,
    min_selectivity_multiplier: float = 1.0,
) -> StrategyEvaluation:
    source_codes = factors["code"] if "code" in factors.columns else daily["code"]
    codes = pd.DataFrame({"code": sorted(set(source_codes.astype(str)))})
    if codes.empty or not enabled:
        return StrategyEvaluation(
            aggregate=_empty_strategy_result(codes),
            hits=pd.DataFrame(columns=STRATEGY_HIT_COLUMNS),
        )

    features = build_strategy_features(daily, report_date, factors)
    hits: list[pd.DataFrame] = []
    for key in dict.fromkeys(enabled):
        strategy_cls = STRATEGY_REGISTRY.get(key)
        if strategy_cls is None:
            continue
        hit = strategy_cls((parameters or {}).get(key, {})).evaluate(
            daily, report_date, factors, features
        )
        if not hit.empty:
            hits.append(hit)

    if not hits:
        return StrategyEvaluation(
            aggregate=_empty_strategy_result(codes),
            hits=pd.DataFrame(columns=STRATEGY_HIT_COLUMNS),
        )

    all_hits = pd.concat(hits, ignore_index=True)
    universe_size = max(len(codes), 1)
    hit_rates = all_hits.groupby("strategy_key")["code"].nunique().div(universe_size)
    all_hits["strategy_hit_rate"] = all_hits["strategy_key"].map(hit_rates).astype(float)
    all_hits["strategy_selectivity_multiplier"] = (
        max_scoring_hit_rate / all_hits["strategy_hit_rate"].replace(0, pd.NA)
    ).clip(lower=min_selectivity_multiplier, upper=1.0).fillna(1.0)
    all_hits["strategy_score_effective"] = (
        all_hits["strategy_score_raw"] * all_hits["strategy_selectivity_multiplier"]
    )
    rows = []
    for code, group in all_hits.groupby("code", sort=False):
        row = _aggregate_code_hits(group).to_dict()
        row["code"] = code
        rows.append(row)
    aggregated = pd.DataFrame(rows)
    result = codes.merge(aggregated, on="code", how="left")
    defaults = {
        "strategy_score_raw": 0.0,
        "matched_strategies": "",
        "strategy_reason": "",
        "strategy_hit_count": 0,
        "strategy_family_count": 0,
        "strategy_families": "",
        "strategy_details": "[]",
    }
    for column, default in defaults.items():
        result[column] = result[column].fillna(default)
    result[["strategy_hit_count", "strategy_family_count"]] = result[
        ["strategy_hit_count", "strategy_family_count"]
    ].astype(int)
    matched = result["matched_strategies"].ne("")
    result.loc[matched, "strategy_reason"] = (
        "命中策略："
        + result.loc[matched, "matched_strategies"]
        + "；"
        + result.loc[matched, "strategy_reason"]
    )
    result = _merge_risk_inputs(result, features)
    return StrategyEvaluation(aggregate=result, hits=all_hits)


def run_enabled_strategies(
    daily: pd.DataFrame,
    report_date: str,
    factors: pd.DataFrame,
    enabled: list[str],
    parameters: dict[str, dict[str, object]] | None = None,
    max_scoring_hit_rate: float = 1.0,
    min_selectivity_multiplier: float = 1.0,
) -> pd.DataFrame:
    return evaluate_enabled_strategies(
        daily,
        report_date,
        factors,
        enabled,
        parameters,
        max_scoring_hit_rate,
        min_selectivity_multiplier,
    ).aggregate


def build_strategy_screener_data(
    hits: pd.DataFrame,
    ranked: pd.DataFrame,
    enabled: list[str],
    max_results: int,
) -> tuple[list[dict[str, object]], pd.DataFrame]:
    enabled_set = set(enabled)
    counts = (
        hits.groupby("strategy_key").size().astype(int).to_dict()
        if not hits.empty and "strategy_key" in hits.columns
        else {}
    )
    catalog = []
    for item in strategy_catalog():
        key = str(item["key"])
        enabled_item = key in enabled_set
        matched_count = int(counts.get(key, 0))
        catalog.append(
            {
                **item,
                "enabled": enabled_item,
                "matched_count": matched_count,
                "result_count": min(matched_count, max_results),
                "max_results": int(max_results),
                "status": "active" if enabled_item else "disabled",
                "formula_summary": item["description"],
            }
        )

    if hits.empty or ranked.empty:
        return catalog, pd.DataFrame(columns=STRATEGY_SCREENER_RESULT_COLUMNS)

    selected = hits.rename(
        columns={
            "strategy_key": "single_strategy_key",
            "strategy": "single_strategy_name",
            "strategy_family": "single_strategy_family",
            "strategy_score_raw": "single_strategy_score",
            "strategy_reason": "single_strategy_reason",
        }
    ).copy()
    details = ranked.drop_duplicates("code").copy()
    # Strategy features are built from the full daily frame, so a strategy can
    # hit a code that build_stock_pool filtered out (ST, halted, low liquidity,
    # ...). Such a code is absent from `ranked`, so a left merge would leave its
    # name/industry/total_score as NaN — the UI then shows a bare code with no
    # name at the tail of each strategy. Drop those hits before merging so the
    # screener only surfaces codes that are actually in the ranked pool.
    selected = selected[selected["code"].isin(details["code"])]
    selected = selected.merge(details, on="code", how="left")
    selected = selected.sort_values(
        ["single_strategy_key", "single_strategy_score", "total_score"],
        ascending=[True, False, False],
        na_position="last",
    )
    selected = selected.groupby("single_strategy_key", sort=False).head(max_results).copy()
    selected.insert(
        0,
        "single_strategy_rank",
        selected.groupby("single_strategy_key", sort=False).cumcount().add(1),
    )
    columns = [
        column
        for column in STRATEGY_SCREENER_RESULT_COLUMNS
        if column in selected.columns
    ]
    return catalog, selected[columns].reset_index(drop=True)


SINGLE_SCREENER_POOL_SIZE = 200


def build_single_screener_pool(
    daily: pd.DataFrame,
    report_date: str,
    factors: pd.DataFrame,
    ranked: pd.DataFrame,
    parameters: dict[str, dict[str, object]] | None = None,
    max_scoring_hit_rate: float = 1.0,
    min_selectivity_multiplier: float = 1.0,
    enabled: list[str] | None = None,
) -> tuple[list[dict[str, object]], pd.DataFrame]:
    """评估全部内置策略，每策略预计算 Top 200 命中池，供单策略筛选页即时截断。

    与观察名单（strategies.enabled）解耦：无论观察名单勾选了哪些策略，
    这里始终评估全部策略，前端按 single_screener 配置本地过滤。
    """
    all_keys = list(STRATEGY_REGISTRY)
    evaluation = evaluate_enabled_strategies(
        daily,
        report_date,
        factors,
        all_keys,
        parameters,
        max_scoring_hit_rate,
        min_selectivity_multiplier,
    )
    return build_strategy_screener_data(
        evaluation.hits,
        ranked,
        enabled if enabled is not None else all_keys,
        SINGLE_SCREENER_POOL_SIZE,
    )
