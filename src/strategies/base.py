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

    def evaluate(
        self,
        daily: pd.DataFrame,
        report_date: str,
        factors: pd.DataFrame,
        features: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        raise NotImplementedError


def build_strategy_features(
    daily: pd.DataFrame,
    report_date: str,
    factors: pd.DataFrame | None = None,
) -> pd.DataFrame:
    history = daily[daily["trade_date"] <= report_date].sort_values(["code", "trade_date"]).copy()
    if history.empty:
        return pd.DataFrame(columns=["code"])

    grouped = history.groupby("code", sort=False)
    for window in (5, 10, 20, 60):
        history[f"ma{window}"] = grouped["close"].transform(
            lambda value, size=window: value.rolling(size, min_periods=1).mean()
        )
    history["amount_ma20"] = grouped["amount"].transform(lambda value: value.rolling(20, min_periods=1).mean())
    history["high_20"] = grouped["high"].transform(lambda value: value.rolling(20, min_periods=1).max())
    history["high_60"] = grouped["high"].transform(lambda value: value.rolling(60, min_periods=1).max())
    history["low_10"] = grouped["low"].transform(lambda value: value.rolling(10, min_periods=1).min())
    history["low_20"] = grouped["low"].transform(lambda value: value.rolling(20, min_periods=1).min())
    history["prior_high_20"] = grouped["high"].transform(
        lambda value: value.shift(1).rolling(20, min_periods=10).max()
    )
    history["return_5d"] = grouped["close"].transform(lambda value: value.pct_change(5).mul(100))
    history["return_10d"] = grouped["close"].transform(lambda value: value.pct_change(10).mul(100))
    daily_return = grouped["close"].pct_change()
    history["volatility_20d"] = daily_return.groupby(history["code"]).transform(
        lambda value: value.rolling(20, min_periods=10).std()
    )
    history["range_20d"] = (history["high_20"] - history["low_20"]) / history["close"].replace(0, pd.NA)
    history["limit_up_20d"] = grouped["pct_chg"].transform(
        lambda value: value.ge(9.5).rolling(20, min_periods=1).sum()
    )
    history["breakout_signal"] = history["close"].ge(history["prior_high_20"] * 0.995)
    history["breakout_recent_10d"] = history.groupby("code", sort=False)["breakout_signal"].transform(
        lambda value: value.shift(1).rolling(10, min_periods=1).max()
    )
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
