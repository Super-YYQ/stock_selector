from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from src.strategies.base import Strategy, strategy_features


DEFAULT_PARAMS: dict[str, float] = {
    "min_score": 51.0,
    "ignition_min_age": 1.0,
    "ignition_max_age": 12.0,
    "volume_contraction_max": 0.90,
    "deep_volume_contraction": 0.60,
    "trigger_low_hold_ratio": 0.97,
    "platform_hold_ratio": 0.96,
    "trend_near_high_ratio": 0.80,
    "max_distance_ma20": 22.0,
}


def _params(values: Mapping[str, object] | None) -> dict[str, float]:
    result = dict(DEFAULT_PARAMS)
    for key, value in (values or {}).items():
        if key in result:
            result[key] = float(value)
    return result


def score_volume_breakout_pullback(
    frame: pd.DataFrame,
    params: Mapping[str, object] | None = None,
) -> pd.DataFrame:
    """Score the document-derived price/volume pattern on every supplied row."""

    result = frame.copy()
    settings = _params(params)

    trigger_amount = pd.to_numeric(result["last_ignition_amount"], errors="coerce")
    contraction_ratio = (
        pd.to_numeric(result["prior_amount_mean_3"], errors="coerce")
        / trigger_amount.replace(0, pd.NA)
    )
    deep_contraction_ratio = (
        pd.to_numeric(result["prior_amount_min_5"], errors="coerce")
        / trigger_amount.replace(0, pd.NA)
    )
    result["document_contraction_ratio"] = contraction_ratio

    trigger_low_support = (
        pd.to_numeric(result["last_ignition_low"], errors="coerce")
        * settings["trigger_low_hold_ratio"]
    )
    platform_support = (
        pd.to_numeric(result["last_ignition_platform"], errors="coerce")
        * settings["platform_hold_ratio"]
    )
    support_line = pd.concat([trigger_low_support, platform_support], axis=1).max(
        axis=1, skipna=True
    )
    result["document_support"] = support_line

    recent_ignition = result["bars_since_ignition"].between(
        settings["ignition_min_age"],
        settings["ignition_max_age"],
    )
    support_now = result["close"].ge(support_line)
    prior_support_hold = (
        result["prior_close_min_5"].ge(
            result["last_ignition_low"] * settings["trigger_low_hold_ratio"]
        )
        | result["prior_close_min_5"].ge(
            result["last_ignition_platform"] * settings["platform_hold_ratio"]
        )
    )
    volume_contracts = contraction_ratio.le(settings["volume_contraction_max"])
    deep_volume_contracts = deep_contraction_ratio.le(
        settings["deep_volume_contraction"]
    )

    above_trend = (
        result["close"].ge(result["ma20"] * 0.98)
        & result["ma20_slope_5d"].fillna(-99).ge(-0.5)
        & result["distance_ma20"].fillna(99).le(settings["max_distance_ma20"])
    )
    near_stage_high = result["close"].ge(
        result["high_60"] * settings["trend_near_high_ratio"]
    )
    higher_highs = result["higher_high_count_3"].fillna(0).ge(2)
    higher_lows = result["higher_low_count_3"].fillna(0).ge(2)
    rising_structure = higher_highs & higher_lows

    second_launch = (
        result["close"].gt(result["prev_high"])
        & result["close"].ge(result["open"])
        & result["close_position"].fillna(0).ge(0.65)
        & result["amount_ratio_5"].fillna(0).ge(0.70)
    ) | (
        result["close"].ge(result["last_ignition_high"] * 0.98)
        & result["close"].gt(result["prev_close"])
        & result["amount_ratio_5"].fillna(0).ge(0.85)
    )

    pullback_ready = (
        recent_ignition
        & support_now
        & prior_support_hold
        & volume_contracts
        & above_trend
    )
    confirmed_launch = (
        recent_ignition
        & support_now
        & prior_support_hold
        & contraction_ratio.le(1.05)
        & above_trend
        & second_launch
    )
    trend_rising = above_trend & near_stage_high & rising_structure

    upper_shadow_followthrough = (
        result["prev_upper_shadow_ratio"].fillna(0).ge(0.38)
        & result["prev_amount_ratio_5"].fillna(0).ge(1.15)
        & result["high"].gt(result["prev_high"])
        & result["low"].ge(result["prev_low"] * 0.99)
        & result["close"].ge(result["ma5"] * 0.98)
    )
    shadow_recovery = (
        result["prev_upper_shadow_ratio"].fillna(0).ge(0.35)
        & result["lower_shadow_ratio"].fillna(0).ge(0.30)
        & result["amount"].le(result["prev_amount"] * 1.05)
        & result["close"].ge(result["ma5"] * 0.98)
    )
    multi_limit_ladder = (
        result["limit_up_20d"].fillna(0).ge(2)
        & result["close"].ge(result["ma20"] * 0.96)
        & (rising_structure | support_now | second_launch)
    )

    score = pd.Series(0.0, index=result.index)
    score += above_trend.astype(float) * 8
    score += result["ma20_slope_5d"].fillna(-99).ge(0).astype(float) * 6
    score += near_stage_high.astype(float) * 6
    score += higher_highs.astype(float) * 7
    score += higher_lows.astype(float) * 9
    score += recent_ignition.astype(float) * 8
    score += support_now.astype(float) * 8
    score += prior_support_hold.astype(float) * 5
    score += volume_contracts.astype(float) * 11
    score += deep_volume_contracts.astype(float) * 4
    score += second_launch.astype(float) * 12
    score += multi_limit_ladder.astype(float) * 10
    score += upper_shadow_followthrough.astype(float) * 15
    score += shadow_recovery.astype(float) * 12
    score += pullback_ready.astype(float) * 8
    score += confirmed_launch.astype(float) * 10
    score += trend_rising.astype(float) * 12
    result["document_pattern_score"] = score.clip(upper=100).round(2)

    variant = pd.Series("", index=result.index, dtype="object")
    variant.loc[trend_rising] = "高低点抬高"
    variant.loc[multi_limit_ladder] = "涨停阶梯"
    variant.loc[upper_shadow_followthrough | shadow_recovery] = "上影试盘承接"
    variant.loc[pullback_ready] = "放量后缩量承接"
    variant.loc[confirmed_launch] = "缩量回踩后二次启动"
    result["document_pattern_variant"] = variant

    candidate = (
        pullback_ready
        | confirmed_launch
        | trend_rising
        | upper_shadow_followthrough
        | shadow_recovery
        | multi_limit_ladder
    )
    result["document_pattern_candidate"] = candidate
    result["document_entry_ready"] = pullback_ready & ~confirmed_launch
    result["document_pattern_hit"] = candidate & result[
        "document_pattern_score"
    ].ge(settings["min_score"])

    reason = result["document_pattern_variant"].fillna("").astype(str)

    def append_reason(condition: pd.Series, text: str) -> None:
        active = condition.fillna(False) & candidate
        existing = active & reason.ne("")
        reason.loc[existing] = reason.loc[existing] + "、" + text
        reason.loc[active & ~existing] = text

    append_reason(volume_contracts, "回调明显缩量")
    append_reason(higher_lows, "近期低点抬高")
    append_reason(result["limit_up_20d"].fillna(0).ge(2), "近20日多次强势涨停")
    result["document_pattern_reason"] = reason
    return result


class VolumeBreakoutPullbackStrategy(Strategy):
    key = "volume_breakout_pullback"
    name = "放量突破缩量承接"
    family = "pullback"
    description = "覆盖高低点抬高、平台突破回踩、涨停阶梯和上影试盘后的二次启动"
    score = 45

    def evaluate(self, daily, report_date, factors, features=None) -> pd.DataFrame:
        latest = strategy_features(daily, report_date, factors, features)
        scored = score_volume_breakout_pullback(latest, self.params)
        selected = scored.loc[
            scored["document_pattern_hit"].fillna(False),
            [
                "code",
                "document_pattern_score",
                "document_pattern_variant",
                "document_pattern_reason",
            ],
        ].copy()
        if selected.empty:
            return pd.DataFrame(
                columns=[
                    "code",
                    "strategy_key",
                    "strategy",
                    "strategy_family",
                    "strategy_score_raw",
                    "strategy_reason",
                ]
            )

        selected["strategy_key"] = self.key
        selected["strategy"] = self.name
        selected["strategy_family"] = self.family
        stage_score = selected["document_pattern_variant"].map(
            {
                "放量后缩量承接": 55.0,
                "高低点抬高": 42.0,
                "上影试盘承接": 40.0,
                "缩量回踩后二次启动": 38.0,
                "涨停阶梯": 30.0,
            }
        )
        selected["strategy_score_raw"] = stage_score.fillna(
            selected["document_pattern_score"].mul(0.45)
        ).clip(lower=30, upper=55)
        selected["strategy_reason"] = (
            "文档价量形态：" + selected["document_pattern_reason"]
        )
        return selected[
            [
                "code",
                "strategy_key",
                "strategy",
                "strategy_family",
                "strategy_score_raw",
                "strategy_reason",
            ]
        ].reset_index(drop=True)
