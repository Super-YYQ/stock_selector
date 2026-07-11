import json

import pandas as pd

from src.stock_context import (
    _fetch_sector_activity_one,
    calculate_sector_activity,
    merge_stock_context,
    normalize_core_theme_rows,
)


def test_normalize_core_theme_rows_splits_industry_concepts_and_events() -> None:
    rows = [
        {"BOARD_NAME": "农林牧渔", "BOARD_RANK": 1, "IS_PRECISE": "0"},
        {"BOARD_NAME": "养殖业", "BOARD_RANK": 2, "IS_PRECISE": None},
        {"BOARD_NAME": "近期新高", "BOARD_RANK": 3, "IS_PRECISE": None},
        {"BOARD_NAME": "机器人概念", "BOARD_RANK": 4, "IS_PRECISE": "1"},
        {"BOARD_NAME": "猪肉概念", "BOARD_RANK": 5, "IS_PRECISE": "1"},
        {"BOARD_NAME": "融资融券", "BOARD_RANK": 6, "IS_PRECISE": "0"},
    ]

    result = normalize_core_theme_rows("000048", rows)

    assert result["sector"] == "农林牧渔"
    assert result["industry"] == "养殖业"
    assert json.loads(result["concepts"]) == ["机器人概念", "猪肉概念"]
    assert json.loads(result["event_tags"]) == ["近期新高"]


def test_calculate_sector_activity_builds_explainable_summary() -> None:
    raw = pd.DataFrame({"涨跌幅": [0.5] * 100 + [2.5, -2.2, 3.0, 1.0, 2.1]})

    result = calculate_sector_activity(raw, "证券", "2026-07-10")

    assert result is not None
    assert result["active_days_20"] == 4
    assert "证券近20日累计" in result["summary"]
    assert "近半年" in result["summary"]


def test_merge_stock_context_adds_short_tags_and_detail_summary() -> None:
    ranked = pd.DataFrame(
        [
            {
                "rank": 1,
                "code": "000048",
                "name": "京基智农",
                "industry": "深市主板",
                "market_board": "深市主板",
                "pct_chg": 10.0,
                "rps20": 92,
                "amount_ratio": 1.8,
                "break_20d_high": True,
                "limit_up_count": 2,
                "matched_strategies": "均线放量突破、RPS强势突破、缩量回踩企稳",
                "risk_warning": "近5日涨幅偏大，距离20日线偏远",
            }
        ]
    )
    contexts = pd.DataFrame(
        [
            {
                "code": "000048",
                "sector": "农林牧渔",
                "industry": "养殖业",
                "concepts": json.dumps(["机器人概念", "猪肉概念"], ensure_ascii=False),
                "event_tags": json.dumps(["近期新高"], ensure_ascii=False),
                "source": "test",
            }
        ]
    )
    events = pd.DataFrame(
        [
            {
                "trade_date": "2026-07-10",
                "code": "000048",
                "event_type": "limit_up",
                "summary": "当日涨停，涨停统计 3/2",
                "industry": "养殖业",
            }
        ]
    )
    sectors = pd.DataFrame(
        [{"sector_name": "农林牧渔", "summary": "农林牧渔近20日累计 +8.0%，出现 3 个明显异动日。"}]
    )

    result = merge_stock_context(ranked, contexts, events, sectors).iloc[0]

    assert result["industry"] == "养殖业"
    assert result["concepts"] == "机器人概念、猪肉概念"
    assert "均线放量突破" in result["reason_tags"]
    assert "近5日涨幅偏大" in result["risk_tags"]
    assert "相关题材：机器人概念、猪肉概念" in result["limit_up_reason"]
    assert "核心概念" in result["stock_context_summary"]
    assert "农林牧渔近20日累计" in result["industry_activity"]


def test_calculate_sector_activity_derives_returns_from_close_and_respects_date() -> None:
    raw = pd.DataFrame(
        {
            "日期": pd.date_range("2026-01-01", periods=130, freq="D"),
            "收盘": [100 + index for index in range(130)],
        }
    )

    result = calculate_sector_activity(raw, "农林牧渔", "2026-04-30")

    assert result is not None
    assert result["as_of_date"] == "2026-04-30"
    assert result["return_20d"] > 0
    assert "农林牧渔近20日累计" in result["summary"]


def test_fetch_sector_activity_uses_sw_primary_index(monkeypatch) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            dates = pd.date_range("2026-01-01", periods=130, freq="D")
            return {
                "data": [
                    {"bargaindate": day.strftime("%Y-%m-%d"), "closeindex": 100 + index}
                    for index, day in enumerate(dates)
                ]
            }

    calls: list[dict[str, object]] = []

    def fake_get(url: str, **kwargs: object) -> Response:
        calls.append({"url": url, **kwargs})
        return Response()

    monkeypatch.setattr("requests.get", fake_get)

    result = _fetch_sector_activity_one("农林牧渔", "2026-04-30")

    assert result is not None
    assert calls[0]["params"] == {"swindexcode": "801010", "period": "DAY"}
    assert result["sector_name"] == "农林牧渔"
    assert result["return_20d"] > 0
