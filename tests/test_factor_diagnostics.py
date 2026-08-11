import pandas as pd

from src.factor_diagnostics import FACTOR_COLUMNS, build_factor_diagnostics


def test_factor_diagnostics_tracks_coverage_distribution_and_zeros() -> None:
    factors = pd.DataFrame(
        [
            {"sector_score_raw": 0, "rps20": 80},
            {"sector_score_raw": 50, "rps20": None},
        ]
    )

    result = build_factor_diagnostics(factors, "2026-06-22")

    assert set(result["factor"]) == set(FACTOR_COLUMNS)
    sector = result[result["factor"] == "sector_score_raw"].iloc[0]
    rps = result[result["factor"] == "rps20"].iloc[0]
    assert sector["coverage"] == 1
    assert sector["zero_rate"] == 0.5
    assert sector["p50"] == 25
    assert rps["coverage"] == 0.5
