import pandas as pd

from src.strategies.registry import (
    SINGLE_SCREENER_POOL_SIZE,
    STRATEGY_REGISTRY,
    build_strategy_screener_data,
    build_single_screener_pool,
    evaluate_enabled_strategies,
    run_enabled_strategies,
    strategy_catalog,
)
from src.strategies.volume_breakout_pullback import score_volume_breakout_pullback


def _strategy_daily() -> pd.DataFrame:
    rows = []
    for day in range(1, 62):
        close_a = 10 + day * 0.1
        rows.append(
            {
                "code": "000001",
                "trade_date": f"2026-05-{day:02d}",
                "open": close_a - 0.2,
                "high": close_a + 0.2,
                "low": close_a - 0.5,
                "close": close_a,
                "amount": 100,
                "pct_chg": 1,
            }
        )
        rows.append(
            {
                "code": "000002",
                "trade_date": f"2026-05-{day:02d}",
                "open": 10,
                "high": 10.2,
                "low": 9.8,
                "close": 10,
                "amount": 100,
                "pct_chg": 0,
            }
        )
    rows[-2]["close"] = 17
    rows[-2]["high"] = 17.2
    rows[-2]["amount"] = 320
    rows[-2]["pct_chg"] = 6
    return pd.DataFrame(rows)


def test_run_enabled_strategies_aggregates_by_family() -> None:
    daily = _strategy_daily()
    factors = pd.DataFrame(
        [
            {"code": "000001", "rps20": 92, "rps60": 88},
            {"code": "000002", "rps20": 20, "rps60": 30},
        ]
    )

    result = run_enabled_strategies(
        daily,
        "2026-05-61",
        factors,
        ["ma_volume", "turtle_breakout", "rps_breakout"],
    )

    strong = result[result["code"] == "000001"].iloc[0]
    weak = result[result["code"] == "000002"].iloc[0]
    assert "均线放量突破" in strong["matched_strategies"]
    assert "海龟突破" in strong["matched_strategies"]
    assert "RPS强势突破" in strong["matched_strategies"]
    assert strong["strategy_score_raw"] == 70
    assert strong["strategy_hit_count"] == 3
    assert strong["strategy_family_count"] == 2
    assert weak["strategy_score_raw"] == 0


def test_run_enabled_strategies_returns_zero_when_disabled() -> None:
    daily = _strategy_daily()
    factors = pd.DataFrame([{"code": "000001"}])

    result = run_enabled_strategies(daily, "2026-05-61", factors, [])

    assert result.loc[0, "strategy_score_raw"] == 0
    assert result.loc[0, "matched_strategies"] == ""


def test_strategy_selectivity_downweights_overbroad_hits() -> None:
    daily = _strategy_daily()
    factors = pd.DataFrame(
        [
            {"code": "000001", "rps20": 92, "rps60": 88},
            {"code": "000002", "rps20": 20, "rps60": 30},
        ]
    )

    evaluation = evaluate_enabled_strategies(
        daily,
        "2026-05-61",
        factors,
        ["ma_volume"],
        max_scoring_hit_rate=0.20,
        min_selectivity_multiplier=0.25,
    )

    hit = evaluation.hits.iloc[0]
    assert hit["strategy_hit_rate"] == 0.5
    assert hit["strategy_selectivity_multiplier"] == 0.4
    assert evaluation.aggregate.loc[evaluation.aggregate["code"] == "000001", "strategy_score_raw"].iloc[0] == 14


def test_sector_leader_rejects_market_board_industry_fallback() -> None:
    daily = _strategy_daily()
    factors = pd.DataFrame(
        [
            {
                "code": "000001",
                "rps20": 92,
                "rps60": 88,
                "sector_score_raw": 90,
                "industry": "深市主板",
                "industry_source": "market_board_fallback",
            }
        ]
    )

    evaluation = evaluate_enabled_strategies(
        daily,
        "2026-05-61",
        factors,
        ["sector_leader"],
    )

    assert evaluation.hits.empty
    assert evaluation.aggregate.loc[0, "strategy_score_raw"] == 0


def test_strategy_catalog_contains_all_strategy_families() -> None:
    catalog = strategy_catalog()

    assert len(catalog) == 11
    assert {item["key"] for item in catalog} >= {
        "volatility_squeeze",
        "trend_pullback_reversal",
        "low_volatility_rps",
        "first_pullback",
        "volume_breakout_pullback",
        "sector_leader",
    }
    assert {item["family"] for item in catalog} >= {"breakout", "trend", "pullback", "event", "sector"}


def test_strategy_screener_data_keeps_each_strategy_result_separate() -> None:
    daily = _strategy_daily()
    factors = pd.DataFrame(
        [
            {"code": "000001", "name": "强势股", "rps20": 92, "rps60": 88},
            {"code": "000002", "name": "弱势股", "rps20": 20, "rps60": 30},
        ]
    )
    evaluation = evaluate_enabled_strategies(
        daily,
        "2026-05-61",
        factors,
        ["ma_volume", "turtle_breakout", "rps_breakout"],
    )
    ranked = factors.assign(total_score=[88.0, 20.0], amount_ratio=[3.2, 1.0])

    catalog, results = build_strategy_screener_data(
        evaluation.hits,
        ranked,
        ["ma_volume", "turtle_breakout", "rps_breakout"],
        max_results=20,
    )

    by_key = {item["key"]: item for item in catalog}
    assert by_key["ma_volume"]["matched_count"] == 1
    assert by_key["ma_volume"]["enabled"] is True
    assert by_key["pullback_stable"]["enabled"] is False
    assert set(results["single_strategy_key"]) == {
        "ma_volume",
        "turtle_breakout",
        "rps_breakout",
    }
    assert results.groupby("single_strategy_key")["single_strategy_rank"].min().eq(1).all()
    assert results["single_strategy_reason"].ne("").all()


def test_strategy_catalog_marks_origin() -> None:
    catalog = strategy_catalog()
    by_key = {item["key"]: item for item in catalog}

    assert by_key["volume_breakout_pullback"]["origin"] == "custom"
    assert all(
        item["origin"] == "builtin"
        for key, item in by_key.items()
        if key != "volume_breakout_pullback"
    )


def _multi_code_daily(codes: list[str]) -> pd.DataFrame:
    rows = []
    for day in range(1, 62):
        for index, code in enumerate(codes):
            close = 10 + day * 0.1 + index * 0.001
            row = {
                "code": code,
                "trade_date": f"2026-05-{day:02d}",
                "open": close - 0.2,
                "high": close + 0.2,
                "low": close - 0.5,
                "close": close,
                "amount": 100,
                "pct_chg": 1,
            }
            if day == 61:
                row.update(close=17 + index * 0.001, high=17.2, amount=320, pct_chg=6)
            rows.append(row)
    return pd.DataFrame(rows)


def test_build_single_screener_pool_evaluates_all_strategies() -> None:
    daily = _strategy_daily()
    factors = pd.DataFrame(
        [
            {"code": "000001", "name": "强势股", "rps20": 92, "rps60": 88},
            {"code": "000002", "name": "弱势股", "rps20": 20, "rps60": 30},
        ]
    )
    ranked = factors.assign(total_score=[88.0, 20.0], amount_ratio=[3.2, 1.0])

    catalog, results = build_single_screener_pool(daily, "2026-05-61", factors, ranked)

    assert {item["key"] for item in catalog} == set(STRATEGY_REGISTRY)
    assert len(catalog) == 11
    assert all("origin" in item for item in catalog)
    by_key = {item["key"]: item for item in catalog}
    assert by_key["volume_breakout_pullback"]["origin"] == "custom"
    assert by_key["ma_volume"]["max_results"] == SINGLE_SCREENER_POOL_SIZE
    # 默认（不传 enabled）时全部策略视为启用，与观察名单解耦
    assert all(item["enabled"] for item in catalog)
    enabled_only = build_single_screener_pool(
        daily, "2026-05-61", factors, ranked, enabled=[]
    )[0]
    assert all(not item["enabled"] for item in enabled_only)
    assert not results.empty


def test_single_screener_pool_respects_pool_size() -> None:
    codes = [f"{index:06d}" for index in range(1, 251)]
    daily = _multi_code_daily(codes)
    factors = pd.DataFrame({"code": codes, "rps20": 92, "rps60": 88})
    ranked = factors.assign(total_score=88.0, amount_ratio=3.2)

    catalog, results = build_single_screener_pool(daily, "2026-05-61", factors, ranked)

    by_key = {item["key"]: item for item in catalog}
    assert by_key["ma_volume"]["matched_count"] == len(codes)
    assert by_key["ma_volume"]["result_count"] == SINGLE_SCREENER_POOL_SIZE
    per_strategy = results.groupby("single_strategy_key").size()
    assert (per_strategy <= SINGLE_SCREENER_POOL_SIZE).all()


def test_document_pattern_scores_breakout_pullback_ready() -> None:
    frame = pd.DataFrame(
        [
            {
                "last_ignition_amount": 200,
                "prior_amount_mean_3": 100,
                "prior_amount_min_5": 80,
                "last_ignition_low": 10,
                "last_ignition_platform": 10.1,
                "bars_since_ignition": 4,
                "close": 10.6,
                "prior_close_min_5": 10.2,
                "ma20": 10.2,
                "ma20_slope_5d": 1,
                "distance_ma20": 3.9,
                "high_60": 11,
                "higher_high_count_3": 1,
                "higher_low_count_3": 2,
                "prev_high": 10.8,
                "open": 10.4,
                "close_position": 0.7,
                "amount_ratio_5": 0.7,
                "last_ignition_high": 11,
                "prev_close": 10.5,
                "prev_upper_shadow_ratio": 0.1,
                "prev_amount_ratio_5": 1,
                "high": 10.8,
                "low": 10.3,
                "prev_low": 10.2,
                "ma5": 10.5,
                "lower_shadow_ratio": 0.1,
                "amount": 90,
                "prev_amount": 100,
                "limit_up_20d": 1,
            }
        ]
    )

    scored = score_volume_breakout_pullback(frame)

    assert bool(scored.loc[0, "document_pattern_hit"])
    assert bool(scored.loc[0, "document_entry_ready"])
    assert scored.loc[0, "document_pattern_variant"] == "放量后缩量承接"
    assert "回调明显缩量" in scored.loc[0, "document_pattern_reason"]
