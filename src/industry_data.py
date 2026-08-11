from __future__ import annotations

from datetime import datetime

import pandas as pd


INDUSTRY_HISTORY_COLUMNS = [
    "code",
    "industry_code",
    "industry_name",
    "valid_from",
    "source",
    "updated_at",
]


def _first_column(frame: pd.DataFrame, aliases: tuple[str, ...]) -> pd.Series:
    for name in aliases:
        if name in frame.columns:
            return frame[name]
    return pd.Series(index=frame.index, dtype="object")


def normalize_sw_industry_history(raw: pd.DataFrame) -> pd.DataFrame:
    """Normalize AKShare/SW 2021 classification history without assuming one release schema."""
    if raw.empty:
        return pd.DataFrame(columns=INDUSTRY_HISTORY_COLUMNS)

    result = pd.DataFrame(index=raw.index)
    result["code"] = _first_column(raw, ("symbol", "股票代码", "证券代码", "code"))
    result["industry_code"] = _first_column(raw, ("industry_code", "行业代码", "申万行业代码"))
    result["industry_name"] = _first_column(
        raw,
        (
            "industry_name",
            "行业名称",
            "申万行业名称",
            "三级行业名称",
            "二级行业名称",
            "一级行业名称",
        ),
    )
    result["valid_from"] = _first_column(raw, ("start_date", "计入日期", "纳入日期", "起始日期"))
    result["code"] = (
        result["code"].fillna("").astype(str).str.extract(r"(\d{6})", expand=False).fillna("")
    )
    result["industry_code"] = result["industry_code"].fillna("").astype(str).str.strip()
    result["industry_name"] = result["industry_name"].fillna("").astype(str).str.strip()
    result["valid_from"] = pd.to_datetime(result["valid_from"], errors="coerce").dt.strftime("%Y-%m-%d")
    result = result[(result["code"] != "") & (result["industry_name"] != "") & result["valid_from"].notna()].copy()
    result["source"] = "sw2021"
    result["updated_at"] = datetime.now().isoformat(timespec="seconds")
    return (
        result[INDUSTRY_HISTORY_COLUMNS]
        .drop_duplicates(["code", "valid_from", "industry_code"], keep="last")
        .sort_values(["code", "valid_from", "industry_code"])
        .reset_index(drop=True)
    )


def fetch_sw_industry_history() -> pd.DataFrame:
    """Fetch the public SW classification history through AKShare."""
    import akshare as ak

    return normalize_sw_industry_history(ak.stock_industry_clf_hist_sw())


def apply_point_in_time_industry(
    stock_basic: pd.DataFrame,
    history: pd.DataFrame,
    as_of_date: str,
) -> pd.DataFrame:
    """Resolve the latest classification known on or before ``as_of_date`` for every stock."""
    result = stock_basic.copy()
    if "industry" not in result.columns:
        result["industry"] = ""
    result["industry_source"] = result["industry"].fillna("").astype(str).str.strip().ne("").map(
        {True: "stock_basic", False: ""}
    )
    if history.empty:
        return result

    eligible = history[history["valid_from"].astype(str) <= as_of_date].copy()
    if eligible.empty:
        return result
    latest = (
        eligible.sort_values(["code", "valid_from", "industry_code"])
        .drop_duplicates("code", keep="last")[["code", "industry_name", "source"]]
    )
    result = result.merge(latest, on="code", how="left")
    resolved = result["industry_name"].fillna("").astype(str).str.strip().ne("")
    result.loc[resolved, "industry"] = result.loc[resolved, "industry_name"]
    result.loc[resolved, "industry_source"] = result.loc[resolved, "source"]
    return result.drop(columns=["industry_name", "source"], errors="ignore")
