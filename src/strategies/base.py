from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class StrategyHit:
    code: str
    strategy: str
    score: float
    reason: str


class Strategy:
    key: str = ""
    name: str = ""
    family: str = "other"
    description: str = ""
    score: float = 0

    def __init__(self, params: dict[str, object] | None = None) -> None:
        self.params = params or {}

    def evaluate(
        self,
        daily: pd.DataFrame,
        report_date: str,
        factors: pd.DataFrame,
        features: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        raise NotImplementedError


def build_strategy_history(
    daily: pd.DataFrame,
    report_date: str,
) -> pd.DataFrame:
    history = daily[daily["trade_date"] <= report_date].sort_values(["code", "trade_date"]).copy()
    if history.empty:
        return history

    grouped = history.groupby("code", sort=False)
    for window in (5, 10, 20, 60):
        history[f"ma{window}"] = grouped["close"].transform(
            lambda value, size=window: value.rolling(size, min_periods=1).mean()
        )
    history["amount_ma5"] = grouped["amount"].transform(
        lambda value: value.rolling(5, min_periods=1).mean()
    )
    history["amount_ma20"] = grouped["amount"].transform(lambda value: value.rolling(20, min_periods=1).mean())
    history["prior_amount_ma5"] = grouped["amount"].transform(
        lambda value: value.shift(1).rolling(5, min_periods=3).mean()
    )
    history["high_20"] = grouped["high"].transform(lambda value: value.rolling(20, min_periods=1).max())
    history["high_60"] = grouped["high"].transform(lambda value: value.rolling(60, min_periods=1).max())
    history["low_10"] = grouped["low"].transform(lambda value: value.rolling(10, min_periods=1).min())
    history["low_20"] = grouped["low"].transform(lambda value: value.rolling(20, min_periods=1).min())
    history["prior_high_20"] = grouped["high"].transform(
        lambda value: value.shift(1).rolling(20, min_periods=10).max()
    )
    history["return_5d"] = grouped["close"].transform(lambda value: value.pct_change(5).mul(100))
    history["return_10d"] = grouped["close"].transform(lambda value: value.pct_change(10).mul(100))
    history["return_20d"] = grouped["close"].transform(lambda value: value.pct_change(20).mul(100))
    daily_return = grouped["close"].pct_change()
    history["close_return"] = daily_return.mul(100)
    history["volatility_20d"] = daily_return.groupby(history["code"]).transform(
        lambda value: value.rolling(20, min_periods=10).std()
    )
    history["range_20d"] = (history["high_20"] - history["low_20"]) / history["close"].replace(0, pd.NA)
    history["bar_index"] = grouped.cumcount()
    history["prev_open"] = grouped["open"].shift(1)
    history["prev_high"] = grouped["high"].shift(1)
    history["prev_low"] = grouped["low"].shift(1)
    history["prev_close"] = grouped["close"].shift(1)
    history["prev_amount"] = grouped["amount"].shift(1)

    bar_range = (history["high"] - history["low"]).clip(lower=0)
    safe_range = bar_range.replace(0, pd.NA)
    history["body_return"] = (
        history["close"] / history["open"].replace(0, pd.NA) - 1
    ).mul(100)
    history["close_position"] = (
        (history["close"] - history["low"]) / safe_range
    ).fillna(1.0).clip(0, 1)
    history["upper_shadow_ratio"] = (
        (history["high"] - history[["open", "close"]].max(axis=1)) / safe_range
    ).fillna(0).clip(0, 1)
    history["lower_shadow_ratio"] = (
        (history[["open", "close"]].min(axis=1) - history["low"]) / safe_range
    ).fillna(0).clip(0, 1)
    history["amount_ratio_5"] = (
        history["amount"] / history["prior_amount_ma5"].replace(0, pd.NA)
    )

    higher_high = grouped["high"].diff().gt(0).astype(float)
    higher_low = grouped["low"].diff().gt(0).astype(float)
    history["higher_high_count_3"] = higher_high.groupby(history["code"]).transform(
        lambda value: value.rolling(3, min_periods=1).sum()
    )
    history["higher_low_count_3"] = higher_low.groupby(history["code"]).transform(
        lambda value: value.rolling(3, min_periods=1).sum()
    )
    history["ma20_5d_ago"] = history.groupby("code", sort=False)["ma20"].shift(5)
    history["ma20_slope_5d"] = (
        history["ma20"] / history["ma20_5d_ago"].replace(0, pd.NA) - 1
    ).mul(100)
    history["distance_ma20"] = (
        history["close"] / history["ma20"].replace(0, pd.NA) - 1
    ).mul(100)

    reported_pct = pd.to_numeric(history["pct_chg"], errors="coerce")
    effective_pct = reported_pct.where(reported_pct.notna(), history["close_return"])
    strong_close = history["close_position"].ge(0.7) & history["close"].ge(history["open"])
    history["limit_up_like"] = (
        (effective_pct.ge(9.5) & history["close_position"].ge(0.9))
        | (
            history["body_return"].ge(4.5)
            & history["close_position"].ge(0.95)
            & history["amount_ratio_5"].fillna(0).ge(1.2)
        )
    )
    history["breakout_signal"] = history["close"].ge(history["prior_high_20"] * 0.995)
    history["ignition_signal"] = (
        history["limit_up_like"]
        | (
            history["breakout_signal"]
            & history["amount_ratio_5"].fillna(0).ge(1.2)
            & strong_close
        )
        | (
            history["body_return"].ge(4.0)
            & history["amount_ratio_5"].fillna(0).ge(1.4)
            & history["close_position"].ge(0.75)
        )
    )

    ignition_columns = {
        "bar": "bar_index",
        "low": "low",
        "high": "high",
        "close": "close",
        "amount": "amount",
        "platform": "prior_high_20",
        "is_limit": "limit_up_like",
    }
    for suffix, column in ignition_columns.items():
        marked = history[column].where(history["ignition_signal"])
        carried = marked.groupby(history["code"]).ffill()
        history[f"last_ignition_{suffix}"] = carried.groupby(history["code"]).shift(1)
    history["bars_since_ignition"] = history["bar_index"] - history["last_ignition_bar"]

    grouped = history.groupby("code", sort=False)
    history["prior_amount_mean_3"] = grouped["amount"].transform(
        lambda value: value.shift(1).rolling(3, min_periods=1).mean()
    )
    history["prior_amount_min_5"] = grouped["amount"].transform(
        lambda value: value.shift(1).rolling(5, min_periods=1).min()
    )
    history["prior_close_min_5"] = grouped["close"].transform(
        lambda value: value.shift(1).rolling(5, min_periods=1).min()
    )
    history["prior_low_min_5"] = grouped["low"].transform(
        lambda value: value.shift(1).rolling(5, min_periods=1).min()
    )
    history["prior_high_max_5"] = grouped["high"].transform(
        lambda value: value.shift(1).rolling(5, min_periods=1).max()
    )
    history["prev_upper_shadow_ratio"] = grouped["upper_shadow_ratio"].shift(1)
    history["prev_amount_ratio_5"] = grouped["amount_ratio_5"].shift(1)
    history["prev_limit_up_like"] = grouped["limit_up_like"].shift(1).fillna(False)

    history["limit_up_20d"] = history["limit_up_like"].groupby(history["code"]).transform(
        lambda value: value.rolling(20, min_periods=1).sum()
    )
    history["breakout_signal"] = history["close"].ge(history["prior_high_20"] * 0.995)
    history["breakout_recent_10d"] = history.groupby("code", sort=False)["breakout_signal"].transform(
        lambda value: value.shift(1).rolling(10, min_periods=1).max()
    )
    return history


def build_strategy_features(
    daily: pd.DataFrame,
    report_date: str,
    factors: pd.DataFrame | None = None,
) -> pd.DataFrame:
    history = build_strategy_history(daily, report_date)
    if history.empty:
        return pd.DataFrame(columns=["code"])

    latest = history.groupby("code", as_index=False, sort=False).tail(1).copy()
    latest["amount_ratio"] = latest["amount"] / latest["amount_ma20"].replace(0, pd.NA)
    latest["distance_ma20"] = (latest["close"] / latest["ma20"].replace(0, pd.NA) - 1).mul(100)

    if factors is not None and not factors.empty:
        factor_columns = [
            column
            for column in ["code", "rps20", "rps60", "sector_score_raw", "industry"]
            if column in factors.columns
        ]
        if len(factor_columns) > 1:
            extras = factors[factor_columns].drop_duplicates("code")
            duplicate_columns = [column for column in factor_columns[1:] if column in latest.columns]
            latest = latest.drop(columns=duplicate_columns, errors="ignore").merge(extras, on="code", how="left")

    for column in ["rps20", "rps60", "sector_score_raw"]:
        if column not in latest.columns:
            latest[column] = 0.0
        latest[column] = pd.to_numeric(latest[column], errors="coerce").fillna(0)
    return latest.reset_index(drop=True)


def strategy_features(
    daily: pd.DataFrame,
    report_date: str,
    factors: pd.DataFrame,
    features: pd.DataFrame | None,
) -> pd.DataFrame:
    return features if features is not None else build_strategy_features(daily, report_date, factors)


def hits_from_mask(
    latest: pd.DataFrame,
    mask: pd.Series,
    strategy: str,
    score: float,
    reason: str,
    *,
    key: str = "",
    family: str = "other",
) -> pd.DataFrame:
    selected = latest.loc[mask.fillna(False), ["code"]].copy()
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
    selected["strategy_key"] = key
    selected["strategy"] = strategy
    selected["strategy_family"] = family
    selected["strategy_score_raw"] = score
    selected["strategy_reason"] = reason
    return selected.reset_index(drop=True)
