from __future__ import annotations

import pandas as pd

from src.strategies.limit_up_shakeout import LimitUpShakeoutStrategy
from src.strategies.ma_volume import MaVolumeStrategy
from src.strategies.pullback_stable import PullbackStableStrategy
from src.strategies.rps_breakout import RpsBreakoutStrategy
from src.strategies.turtle_breakout import TurtleBreakoutStrategy

STRATEGY_REGISTRY = {
    MaVolumeStrategy.key: MaVolumeStrategy,
    TurtleBreakoutStrategy.key: TurtleBreakoutStrategy,
    RpsBreakoutStrategy.key: RpsBreakoutStrategy,
    PullbackStableStrategy.key: PullbackStableStrategy,
    LimitUpShakeoutStrategy.key: LimitUpShakeoutStrategy,
}


def run_enabled_strategies(
    daily: pd.DataFrame,
    report_date: str,
    factors: pd.DataFrame,
    enabled: list[str],
) -> pd.DataFrame:
    codes = pd.DataFrame({"code": sorted(set(factors["code"].astype(str)) if "code" in factors.columns else set(daily["code"].astype(str)))})
    if codes.empty:
        return pd.DataFrame(columns=["code", "strategy_score_raw", "matched_strategies", "strategy_reason"])
    if not enabled:
        result = codes.copy()
        result["strategy_score_raw"] = 0.0
        result["matched_strategies"] = ""
        result["strategy_reason"] = ""
        return result

    hits = []
    for key in enabled:
        strategy_cls = STRATEGY_REGISTRY.get(key)
        if strategy_cls is None:
            continue
        hit = strategy_cls().evaluate(daily, report_date, factors)
        if not hit.empty:
            hits.append(hit)

    if not hits:
        result = codes.copy()
        result["strategy_score_raw"] = 0.0
        result["matched_strategies"] = ""
        result["strategy_reason"] = ""
        return result

    all_hits = pd.concat(hits, ignore_index=True)
    aggregated = all_hits.groupby("code").agg(
        strategy_score_raw=("strategy_score_raw", "sum"),
        matched_strategies=("strategy", lambda value: "、".join(dict.fromkeys(value.astype(str)))),
        strategy_reason=("strategy_reason", lambda value: "；".join(dict.fromkeys(value.astype(str)))),
    ).reset_index()
    aggregated["strategy_score_raw"] = aggregated["strategy_score_raw"].clip(upper=100)
    result = codes.merge(aggregated, on="code", how="left")
    result["strategy_score_raw"] = result["strategy_score_raw"].fillna(0.0)
    result["matched_strategies"] = result["matched_strategies"].fillna("")
    result["strategy_reason"] = result["strategy_reason"].fillna("")
    result.loc[result["matched_strategies"].ne(""), "strategy_reason"] = "命中策略：" + result.loc[
        result["matched_strategies"].ne(""), "matched_strategies"
    ] + "；" + result.loc[result["matched_strategies"].ne(""), "strategy_reason"]
    return result
