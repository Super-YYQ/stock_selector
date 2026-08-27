import pandas as pd

from src.config import RiskConfig, ScoringConfig
from src.risk_filter import calculate_risk_penalties
from src.strategies.registry import evaluate_enabled_strategies


def _trending_daily() -> pd.DataFrame:
    """61-day history; 000001 sits flat near 10 for 60 days then jumps to 15.

    That lifts the last close ~46% above the 20-day line (ma20 ~= 10.25), far
    past the 25% risk threshold, so a stock that has diverged from its 20-day
    line is detectable by the risk filter — but only if evaluate_enabled_strategies
    carries the feature-frame value onto its aggregate (the regression this guards).
    """
    rows = []
    for day in range(1, 62):
        is_last = day == 61
        close = 15 if is_last else 10
        rows.append(
            {
                "code": "000001",
                "trade_date": f"2026-05-{day:02d}",
                "open": close - 0.2,
                "high": close + 0.2,
                "low": close - 0.5,
                "close": close,
                "amount": 320 if is_last else 100,
                "pct_chg": 50 if is_last else 0,
            }
        )
    return pd.DataFrame(rows)


def test_risk_penalty_caps_and_explains_multiple_risks() -> None:
    factors = pd.DataFrame(
        [
            {
                "code": "000001",
                "return_5d": 35,
                "return_10d": 50,
                "distance_ma20": 30,
                "upper_shadow_ratio": 0.7,
                "amount_ratio": 3.5,
                "pct_chg": 0.2,
                "turnover_rate": 30,
                "volatility_20d": 0.1,
            }
        ]
    )

    result = calculate_risk_penalties(factors, RiskConfig(), ScoringConfig(risk_penalty_max=20))

    row = result.iloc[0]
    assert row["risk_penalty"] == 20
    assert "近5日涨幅" in row["risk_warning"]
    assert "距离20日线" in row["risk_warning"]


def test_risk_penalty_treats_nullable_numeric_values_as_zero() -> None:
    factors = pd.DataFrame(
        [
            {
                "code": "000001",
                "return_5d": 0.0,
                "return_10d": 0.0,
                "distance_ma20": 0.0,
                "upper_shadow_ratio": pd.NA,
                "amount_ratio": 1.0,
                "pct_chg": 0.0,
                "turnover_rate": pd.NA,
                "volatility_20d": 0.0,
            }
        ]
    )

    result = calculate_risk_penalties(factors, RiskConfig(), ScoringConfig())

    assert result.loc[0, "risk_penalty"] == 0


def test_strategy_aggregate_feeds_distance_ma20_into_risk_warning() -> None:
    # End-to-end regression for the factors/feature-frame seam: the risk filter
    # must see the real distance_ma20 carried from the strategy feature frame via
    # evaluate_enabled_strategies' aggregate (exactly what run_daily merges onto
    # factors). Before the fix, distance_ma20 arrived as 0 and "距离20日线" never
    # appeared in risk_warning for a genuinely extended stock.
    daily = _trending_daily()
    factors = pd.DataFrame(
        [
            {"code": "000001", "rps20": 92, "rps60": 88, "turnover_rate": 5, "pct_chg": 6},
        ]
    )

    evaluation = evaluate_enabled_strategies(
        daily,
        "2026-05-61",
        factors,
        ["ma_volume"],
    )
    factors_with_risk_inputs = factors.merge(evaluation.aggregate, on="code", how="left")

    carried = factors_with_risk_inputs.loc[0, "distance_ma20"]
    assert pd.notna(carried)
    assert carried > RiskConfig().max_distance_ma20  # genuinely extended

    result = calculate_risk_penalties(factors_with_risk_inputs, RiskConfig(), ScoringConfig())
    assert "距离20日线" in result.loc[0, "risk_warning"]
    assert result.loc[0, "risk_penalty"] >= 5
