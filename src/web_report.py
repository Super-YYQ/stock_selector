from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _records(frame: pd.DataFrame | None, limit: int | None = None) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    prepared = frame.head(limit).copy() if limit is not None else frame.copy()
    prepared = prepared.replace([np.inf, -np.inf], np.nan)
    return json.loads(prepared.to_json(orient="records", force_ascii=False, date_format="iso"))


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    if pd.isna(value):
        return None
    return value


def _strategy_distribution(top50: pd.DataFrame) -> list[dict[str, Any]]:
    if top50.empty or "matched_strategies" not in top50.columns:
        return []
    counts: dict[str, int] = {}
    for value in top50["matched_strategies"].fillna("").astype(str):
        for name in (item for item in value.split("、") if item):
            counts[name] = counts.get(name, 0) + 1
    return [
        {"strategy": name, "count": count}
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def build_report_payload(
    report_date: str,
    market: dict[str, object],
    strong_sectors: pd.DataFrame,
    top50: pd.DataFrame,
    top10: pd.DataFrame,
    strategy_performance: pd.DataFrame | None,
    health: dict[str, object],
    custom_strategies: list[dict[str, Any]] | None = None,
    custom_strategy_results: pd.DataFrame | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "report_date": report_date,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "market": _json_value(market),
        "health": _json_value(health),
        "summary": {
            "observe_count": int(len(top50)),
            "focus_count": int(len(top10)),
            "sector_count": int(len(strong_sectors)),
        },
        "strong_sectors": _records(strong_sectors, 20),
        "top50": _records(top50, 50),
        "top10": _records(top10, 10),
        "strategy_performance": _records(strategy_performance),
        "strategy_distribution": _strategy_distribution(top50),
        "custom_strategies": _json_value(custom_strategies or []),
        "custom_strategy_results": _records(custom_strategy_results),
        "disclaimer": "仅用于盘后复盘和观察名单筛选，不构成投资建议，不执行自动交易。",
    }


def write_static_report(
    site_dir: str | Path,
    payload: dict[str, Any],
    *,
    template_dir: str | Path = "web",
    history_days: int = 90,
) -> Path:
    site = Path(site_dir)
    template = Path(template_dir)
    data_dir = site / "data"
    history_dir = data_dir / "history"
    assets_dir = site / "assets"
    history_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    for name in ("index.html", "404.html"):
        source = template / name
        if source.exists():
            shutil.copy2(source, site / name)
    source_assets = template / "assets"
    if source_assets.exists():
        for source in source_assets.iterdir():
            if source.is_file():
                shutil.copy2(source, assets_dir / source.name)

    serialized = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
    (data_dir / "latest.json").write_text(serialized, encoding="utf-8")
    report_date = str(payload["report_date"])
    (history_dir / f"{report_date}.json").write_text(serialized, encoding="utf-8")

    history_files = sorted(history_dir.glob("*.json"), reverse=True)
    for stale in history_files[max(1, history_days):]:
        stale.unlink()

    history = [
        {"report_date": item.stem, "path": f"data/history/{item.name}"}
        for item in sorted(history_dir.glob("*.json"), reverse=True)
    ]
    (data_dir / "history.json").write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return site / "index.html"
