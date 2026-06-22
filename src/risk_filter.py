from __future__ import annotations

import pandas as pd

from src.config import RiskConfig, ScoringConfig


def calculate_risk_penalties(factors: pd.DataFrame, risk: RiskConfig, scoring: ScoringConfig) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for _, row in factors.iterrows():
        penalty = 0.0
        warnings: list[str] = []
        if float(row.get("return_5d", 0) or 0) > risk.max_pct_chg_5d:
            penalty += 5
            warnings.append(f"近5日涨幅 {row.get('return_5d'):.1f}% 过大")
        if float(row.get("return_10d", 0) or 0) > risk.max_pct_chg_10d:
            penalty += 5
            warnings.append(f"近10日涨幅 {row.get('return_10d'):.1f}% 过大")
        if float(row.get("distance_ma20", 0) or 0) > risk.max_distance_ma20:
            penalty += 5
            warnings.append(f"距离20日线 {row.get('distance_ma20'):.1f}% 偏远")
        if float(row.get("upper_shadow_ratio", 0) or 0) > risk.long_upper_shadow_ratio:
            penalty += 3
            warnings.append("今日长上影线明显")
        if float(row.get("amount_ratio", 0) or 0) > 3 and float(row.get("pct_chg", 0) or 0) < 1:
            penalty += 4
            warnings.append("爆量滞涨")
        if float(row.get("turnover_rate", 0) or 0) > risk.high_turnover_ratio:
            penalty += 3
            warnings.append("换手率过高")
        if float(row.get("volatility_20d", 0) or 0) > risk.high_volatility_20d:
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
