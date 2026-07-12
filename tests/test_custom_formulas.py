from pathlib import Path

import pandas as pd

from src.custom_formulas import (
    FormulaConfigError,
    evaluate_custom_formulas,
    load_custom_formulas,
    update_custom_formula_enabled,
)


def _write_config(path: Path) -> None:
    path.write_text(
        """
version: 1
strategies:
  - key: test_breakout
    name: 测试突破
    description: 测试安全公式
    enabled: true
    match: all
    max_results: 10
    sort_by: total_score
    conditions:
      - field: close
        operator: gte
        compare_field: ma20
        label: 收盘价站上20日线
      - field: rps20
        operator: gte
        value: 80
        label: RPS20不低于80
""".strip(),
        encoding="utf-8",
    )


def test_custom_formula_evaluates_safe_conditions(tmp_path: Path) -> None:
    config = tmp_path / "custom_strategies.yml"
    _write_config(config)
    dates = pd.date_range("2026-01-01", periods=25, freq="D").strftime("%Y-%m-%d")
    daily = pd.DataFrame(
        [
            {
                "code": code,
                "trade_date": trade_date,
                "open": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "amount": 200_000_000,
                "pct_chg": 1.0,
            }
            for code, close in (("000001", 10.0), ("000002", 8.0))
            for trade_date in dates
        ]
    )
    ranked = pd.DataFrame(
        [
            {"code": "000001", "name": "命中", "total_score": 88, "rps20": 90},
            {"code": "000002", "name": "未命中", "total_score": 70, "rps20": 60},
        ]
    )

    catalog, results = evaluate_custom_formulas(daily, dates[-1], ranked, config)

    assert catalog[0]["matched_count"] == 1
    assert catalog[0]["status"] == "active"
    assert results["code"].tolist() == ["000001"]
    assert results.iloc[0]["custom_reason"].startswith("命中公式：")


def test_custom_formula_enabled_update_rejects_unknown_keys(tmp_path: Path) -> None:
    config = tmp_path / "custom_strategies.yml"
    _write_config(config)

    updated = update_custom_formula_enabled(config, [])

    assert updated[0]["enabled"] is False
    assert load_custom_formulas(config)[0]["enabled"] is False
    try:
        update_custom_formula_enabled(config, ["unknown_formula"])
    except FormulaConfigError as exc:
        assert "未知自定义策略" in str(exc)
    else:
        raise AssertionError("unknown custom formula should be rejected")
