from __future__ import annotations

from datetime import datetime

import pandas as pd


FACTOR_COLUMNS = (
    "sector_score_raw",
    "stock_character_score_raw",
    "volume_price_score_raw",
    "strategy_score_raw",
    "rps20",
    "rps60",
)


def build_factor_diagnostics(factors: pd.DataFrame, report_date: str) -> pd.DataFrame:
    """Build compact cross-sectional health metrics for factor drift monitoring."""
    rows: list[dict[str, object]] = []
    sample_count = len(factors)
    now = datetime.now().isoformat(timespec="seconds")
    for factor in FACTOR_COLUMNS:
        values = pd.to_numeric(factors.get(factor, pd.Series(dtype=float)), errors="coerce")
        valid = values.dropna()
        quantiles = valid.quantile([0.1, 0.5, 0.9]) if not valid.empty else pd.Series(dtype=float)
        rows.append(
            {
                "report_date": report_date,
                "factor": factor,
                "sample_count": sample_count,
                "valid_count": int(len(valid)),
                "coverage": round(float(len(valid) / sample_count), 6) if sample_count else 0.0,
                "mean": round(float(valid.mean()), 6) if not valid.empty else None,
                "std": round(float(valid.std(ddof=0)), 6) if not valid.empty else None,
                "p10": round(float(quantiles.get(0.1)), 6) if not valid.empty else None,
                "p50": round(float(quantiles.get(0.5)), 6) if not valid.empty else None,
                "p90": round(float(quantiles.get(0.9)), 6) if not valid.empty else None,
                "zero_rate": round(float(valid.eq(0).mean()), 6) if not valid.empty else None,
                "updated_at": now,
            }
        )
    return pd.DataFrame(rows)
