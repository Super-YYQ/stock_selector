import pandas as pd

from src.config import RiskConfig, ScoringConfig
from src.risk_filter import calculate_risk_penalties


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
