import pandas as pd

from src.config import ReportConfig, ScoringConfig
from src.scoring import build_ranked_results


def test_build_ranked_results_weights_scores_and_builds_text() -> None:
    factors = pd.DataFrame(
        [
            {
                "code": "000001",
                "name": "强势股",
                "industry": "机器人",
                "pct_chg": 4,
                "return_5d": 8,
                "return_20d": 20,
                "amount_ratio": 2,
                "rps20": 90,
                "rps60": 80,
                "sector_score_raw": 90,
                "stock_character_score_raw": 80,
                "volume_price_score_raw": 85,
                "strategy_score_raw": 100,
                "matched_strategies": "均线放量突破、RPS强势突破",
                "strategy_reason": "命中策略：均线放量突破、RPS强势突破",
                "risk_penalty": 5,
                "sector_reason": "板块走强",
                "character_reason": "股性活跃",
                "volume_price_reason": "放量突破",
                "risk_warning": "暂无明显量化风险",
            },
            {
                "code": "000002",
                "name": "普通股",
                "industry": "银行",
                "pct_chg": 0,
                "return_5d": 1,
                "return_20d": 2,
                "amount_ratio": 1,
                "rps20": 30,
                "rps60": 40,
                "sector_score_raw": 30,
                "stock_character_score_raw": 20,
                "volume_price_score_raw": 25,
                "strategy_score_raw": 0,
                "matched_strategies": "",
                "strategy_reason": "",
                "risk_penalty": 0,
                "sector_reason": "板块一般",
                "character_reason": "股性一般",
                "volume_price_reason": "量价普通",
                "risk_warning": "暂无明显量化风险",
            },
        ]
    )
    market = {"market_score": 7.5, "market_label": "偏强"}

    ranked, top50, top10 = build_ranked_results(
        factors,
        market,
        ScoringConfig(),
        ReportConfig(top_observe=1, top_focus=1),
    )

    assert ranked.iloc[0]["code"] == "000001"
    assert top50["code"].tolist() == ["000001"]
    assert top10["code"].tolist() == ["000001"]
    assert ranked.iloc[0]["strategy_score"] == 15
    assert "放量突破" in ranked.iloc[0]["selection_reason"]
    assert "命中策略" in ranked.iloc[0]["selection_reason"]
    assert "不追高" in ranked.iloc[0]["next_day_condition"]
