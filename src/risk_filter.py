from __future__ import annotations

import pandas as pd

from src.config import RiskConfig, ScoringConfig


def _number(row: pd.Series, column: str) -> float:
    value = row.get(column, 0)
    if value is None or pd.isna(value):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def calculate_risk_penalties(factors: pd.DataFrame, risk: RiskConfig, scoring: ScoringConfig) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for _, row in factors.iterrows():
        penalty = 0.0
        warnings: list[str] = []
        return_5d = _number(row, "return_5d")
        return_10d = _number(row, "return_10d")
        distance_ma20 = _number(row, "distance_ma20")
        upper_shadow_ratio = _number(row, "upper_shadow_ratio")
        amount_ratio = _number(row, "amount_ratio")
        pct_chg = _number(row, "pct_chg")
        turnover_rate = _number(row, "turnover_rate")
        volatility_20d = _number(row, "volatility_20d")

        if return_5d > risk.max_pct_chg_5d:
            penalty += 5
            warnings.append(f"近5日涨幅 {return_5d:.1f}% 过大")
        if return_10d > risk.max_pct_chg_10d:
            penalty += 5
            warnings.append(f"近10日涨幅 {return_10d:.1f}% 过大")
        if distance_ma20 > risk.max_distance_ma20:
            penalty += 5
            warnings.append(f"距离20日线 {distance_ma20:.1f}% 偏远")
        if upper_shadow_ratio > risk.long_upper_shadow_ratio:
            penalty += 3
            warnings.append("今日长上影线明显")
        if amount_ratio > 3 and pct_chg < 1:
            penalty += 4
            warnings.append("爆量滞涨")
        if turnover_rate > risk.high_turnover_ratio:
            penalty += 3
            warnings.append("换手率过高")
        if volatility_20d > risk.high_volatility_20d:
            penalty += 3
            warnings.append("近20日波动率偏高")
        rows.append(
            {
                "code": row["code"],
                "risk_penalty": min(scoring.risk_penalty_max, penalty),
                "risk_warning": "，".join(warnings) if warnings else "暂无明显量化风险",
            }
        )
    return pd.DataFrame(rows)
