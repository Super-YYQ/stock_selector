from __future__ import annotations

import json

import pandas as pd

from src.strategies.base import build_strategy_features
from src.strategies.first_pullback import FirstPullbackStrategy
from src.strategies.limit_up_shakeout import LimitUpShakeoutStrategy
from src.strategies.low_volatility_rps import LowVolatilityRpsStrategy
from src.strategies.ma_volume import MaVolumeStrategy
from src.strategies.pullback_stable import PullbackStableStrategy
from src.strategies.rps_breakout import RpsBreakoutStrategy
from src.strategies.sector_leader import SectorLeaderStrategy
from src.strategies.trend_pullback_reversal import TrendPullbackReversalStrategy
from src.strategies.turtle_breakout import TurtleBreakoutStrategy
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
    SectorLeaderStrategy,
]
STRATEGY_REGISTRY = {strategy.key: strategy for strategy in STRATEGY_CLASSES}

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
    return result


def _aggregate_code_hits(group: pd.DataFrame) -> pd.Series:
    family_scores = group.groupby("strategy_family")["strategy_score_raw"].max()
    details = [
        {
            "key": row.strategy_key,
            "name": row.strategy,
            "family": row.strategy_family,
            "score": float(row.strategy_score_raw),
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


def run_enabled_strategies(
    daily: pd.DataFrame,
    report_date: str,
    factors: pd.DataFrame,
    enabled: list[str],
) -> pd.DataFrame:
    source_codes = factors["code"] if "code" in factors.columns else daily["code"]
    codes = pd.DataFrame({"code": sorted(set(source_codes.astype(str)))})
    if codes.empty or not enabled:
        return _empty_strategy_result(codes)

    features = build_strategy_features(daily, report_date, factors)
    hits = []
    for key in dict.fromkeys(enabled):
        strategy_cls = STRATEGY_REGISTRY.get(key)
        if strategy_cls is None:
            continue
        hit = strategy_cls().evaluate(daily, report_date, factors, features)
        if not hit.empty:
            hits.append(hit)

    if not hits:
        return _empty_strategy_result(codes)

    all_hits = pd.concat(hits, ignore_index=True)
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
    return result
