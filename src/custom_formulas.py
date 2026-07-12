from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.strategies.base import build_strategy_features


FORMULA_KEY = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
FORMULA_OPERATORS = {"gt", "gte", "lt", "lte", "eq", "between"}
RESULT_COLUMNS = [
    "formula_rank",
    "custom_strategy_key",
    "custom_strategy_name",
    "custom_reason",
    "rank",
    "code",
    "name",
    "industry",
    "sector",
    "market_board",
    "concepts",
    "total_score",
    "pct_chg",
    "return_5d",
    "return_10d",
    "return_20d",
    "amount_ratio",
    "rps20",
    "rps60",
    "distance_ma20",
    "risk_penalty",
    "reason_tags",
    "risk_tags",
    "matched_strategies",
    "selection_reason",
    "selection_reason_short",
    "stock_context_summary",
    "next_day_condition",
    "risk_warning",
    "sector_score",
    "stock_character_score",
    "volume_price_score",
    "relative_strength_score",
    "strategy_score",
    "market_adjust_score",
]


class FormulaConfigError(ValueError):
    pass


def _number(value: Any, label: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise FormulaConfigError(f"{label} 必须是数字") from exc


def _condition(raw: Any, strategy_key: str, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise FormulaConfigError(f"{strategy_key}.conditions[{index}] 必须是映射")
    field = str(raw.get("field", "")).strip()
    operator = str(raw.get("operator", "")).strip().lower()
    if not FORMULA_KEY.fullmatch(field):
        raise FormulaConfigError(f"{strategy_key} 的条件字段无效: {field or '<empty>'}")
    if operator not in FORMULA_OPERATORS:
        raise FormulaConfigError(f"{strategy_key} 使用了不支持的运算符: {operator or '<empty>'}")

    result: dict[str, Any] = {
        "field": field,
        "operator": operator,
        "label": str(raw.get("label", field)).strip() or field,
    }
    if operator == "between":
        minimum = _number(raw.get("min"), f"{strategy_key}.{field}.min")
        maximum = _number(raw.get("max"), f"{strategy_key}.{field}.max")
        if minimum > maximum:
            raise FormulaConfigError(f"{strategy_key}.{field} 的 min 不能大于 max")
        result.update({"min": minimum, "max": maximum})
        return result

    compare_field = str(raw.get("compare_field", "")).strip()
    if compare_field:
        if not FORMULA_KEY.fullmatch(compare_field):
            raise FormulaConfigError(f"{strategy_key} 的比较字段无效: {compare_field}")
        result.update(
            {
                "compare_field": compare_field,
                "multiplier": _number(raw.get("multiplier", 1), f"{strategy_key}.{field}.multiplier"),
                "offset": _number(raw.get("offset", 0), f"{strategy_key}.{field}.offset"),
            }
        )
    else:
        result["value"] = _number(raw.get("value"), f"{strategy_key}.{field}.value")
    return result


def load_custom_formulas(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        return []
    raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise FormulaConfigError("custom_strategies.yml 必须包含 YAML 映射")
    strategies = raw.get("strategies", [])
    if not isinstance(strategies, list):
        raise FormulaConfigError("custom_strategies.strategies 必须是列表")

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for position, item in enumerate(strategies):
        if not isinstance(item, dict):
            raise FormulaConfigError(f"strategies[{position}] 必须是映射")
        key = str(item.get("key", "")).strip()
        if not FORMULA_KEY.fullmatch(key):
            raise FormulaConfigError(f"自定义策略 key 无效: {key or '<empty>'}")
        if key in seen:
            raise FormulaConfigError(f"自定义策略 key 重复: {key}")
        seen.add(key)
        name = str(item.get("name", "")).strip()
        if not name:
            raise FormulaConfigError(f"{key}.name 不能为空")
        match = str(item.get("match", "all")).strip().lower()
        if match not in {"all", "any"}:
            raise FormulaConfigError(f"{key}.match 只能是 all 或 any")
        conditions_raw = item.get("conditions", [])
        if not isinstance(conditions_raw, list) or not conditions_raw:
            raise FormulaConfigError(f"{key}.conditions 至少需要一个条件")
        conditions = [_condition(value, key, index) for index, value in enumerate(conditions_raw)]
        max_results = int(_number(item.get("max_results", 50), f"{key}.max_results"))
        if not 1 <= max_results <= 200:
            raise FormulaConfigError(f"{key}.max_results 必须在 1 到 200 之间")
        sort_direction = str(item.get("sort_direction", "desc")).strip().lower()
        if sort_direction not in {"asc", "desc"}:
            raise FormulaConfigError(f"{key}.sort_direction 只能是 asc 或 desc")
        normalized.append(
            {
                "key": key,
                "name": name,
                "description": str(item.get("description", "")).strip(),
                "enabled": bool(item.get("enabled", True)),
                "match": match,
                "conditions": conditions,
                "formula_summary": "、".join(condition["label"] for condition in conditions),
                "max_results": max_results,
                "sort_by": str(item.get("sort_by", "total_score")).strip() or "total_score",
                "sort_direction": sort_direction,
            }
        )
    return normalized


def public_formula_catalog(
    formulas: list[dict[str, Any]],
    counts: dict[str, int] | None = None,
    errors: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    counts = counts or {}
    errors = errors or {}
    return [
        {
            "key": formula["key"],
            "name": formula["name"],
            "description": formula["description"],
            "enabled": formula["enabled"],
            "match": formula["match"],
            "condition_count": len(formula["conditions"]),
            "formula_summary": formula["formula_summary"],
            "matched_count": int(counts.get(formula["key"], 0)),
            "status": "error" if formula["key"] in errors else ("active" if formula["enabled"] else "disabled"),
            "error": errors.get(formula["key"], ""),
        }
        for formula in formulas
    ]


def _comparison(frame: pd.DataFrame, condition: dict[str, Any]) -> pd.Series:
    field = condition["field"]
    if field not in frame.columns:
        raise FormulaConfigError(f"当前数据缺少公式字段: {field}")
    left = pd.to_numeric(frame[field], errors="coerce")
    operator = condition["operator"]
    if operator == "between":
        return left.between(condition["min"], condition["max"], inclusive="both").fillna(False)

    compare_field = condition.get("compare_field")
    if compare_field:
        if compare_field not in frame.columns:
            raise FormulaConfigError(f"当前数据缺少公式比较字段: {compare_field}")
        right = (
            pd.to_numeric(frame[compare_field], errors="coerce") * condition["multiplier"]
            + condition["offset"]
        )
    else:
        right = condition["value"]
    comparisons = {
        "gt": left.gt(right),
        "gte": left.ge(right),
        "lt": left.lt(right),
        "lte": left.le(right),
        "eq": left.eq(right),
    }
    return comparisons[operator].fillna(False)


def _formula_frame(daily: pd.DataFrame, report_date: str, ranked: pd.DataFrame) -> pd.DataFrame:
    features = build_strategy_features(daily, report_date, ranked)
    if features.empty:
        return features
    details = ranked.drop_duplicates("code").copy()
    extra_columns = [column for column in details.columns if column == "code" or column not in features.columns]
    return features.merge(details[extra_columns], on="code", how="left")


def evaluate_custom_formulas(
    daily: pd.DataFrame,
    report_date: str,
    ranked: pd.DataFrame,
    config_path: str | Path,
) -> tuple[list[dict[str, Any]], pd.DataFrame]:
    formulas = load_custom_formulas(config_path)
    empty = pd.DataFrame(columns=RESULT_COLUMNS)
    if not formulas or daily.empty or ranked.empty:
        return public_formula_catalog(formulas), empty

    frame = _formula_frame(daily, report_date, ranked)
    counts: dict[str, int] = {}
    errors: dict[str, str] = {}
    selected_frames: list[pd.DataFrame] = []
    for formula in formulas:
        key = formula["key"]
        if not formula["enabled"]:
            continue
        try:
            masks = [_comparison(frame, condition) for condition in formula["conditions"]]
            mask = masks[0].copy()
            for condition_mask in masks[1:]:
                mask = mask & condition_mask if formula["match"] == "all" else mask | condition_mask
            selected = frame.loc[mask].copy()
            sort_by = formula["sort_by"]
            if sort_by not in selected.columns:
                raise FormulaConfigError(f"当前数据缺少排序字段: {sort_by}")
            selected = selected.sort_values(
                sort_by,
                ascending=formula["sort_direction"] == "asc",
                na_position="last",
            ).head(formula["max_results"])
            counts[key] = int(len(selected))
            if selected.empty:
                continue
            selected.insert(0, "formula_rank", range(1, len(selected) + 1))
            selected["custom_strategy_key"] = key
            selected["custom_strategy_name"] = formula["name"]
            selected["custom_reason"] = "命中公式：" + formula["formula_summary"]
            selected_frames.append(selected.reindex(columns=RESULT_COLUMNS))
        except (FormulaConfigError, KeyError, TypeError, ValueError) as exc:
            counts[key] = 0
            errors[key] = str(exc)

    results = pd.concat(selected_frames, ignore_index=True) if selected_frames else empty
    return public_formula_catalog(formulas, counts, errors), results


def update_custom_formula_enabled(path: str | Path, enabled: list[str]) -> list[dict[str, Any]]:
    source = Path(path)
    formulas = load_custom_formulas(source)
    known = {formula["key"] for formula in formulas}
    unknown = sorted(set(enabled) - known)
    if unknown:
        raise FormulaConfigError("未知自定义策略: " + "、".join(unknown))
    raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    enabled_set = set(enabled)
    for item in raw.get("strategies", []):
        item["enabled"] = str(item.get("key", "")) in enabled_set
    temporary = source.with_suffix(".yml.tmp")
    temporary.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    temporary.replace(source)
    return load_custom_formulas(source)
