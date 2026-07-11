from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from typing import Any, Iterable

import pandas as pd

from src.config import FeatureConfig
from src.database import Database
from src.sector_score import market_board


LOGGER = logging.getLogger(__name__)
CORE_THEME_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
SW_INDEX_TREND_URL = "https://www.swsresearch.com/institute-sw/api/index_publish/trend/"
SW_PRIMARY_INDEXES = {
    "农林牧渔": "801010", "基础化工": "801030", "钢铁": "801040", "有色金属": "801050",
    "电子": "801080", "家用电器": "801110", "食品饮料": "801120", "纺织服饰": "801130",
    "轻工制造": "801140", "医药生物": "801150", "公用事业": "801160", "交通运输": "801170",
    "房地产": "801180", "商贸零售": "801200", "社会服务": "801210", "综合": "801230",
    "建筑材料": "801710", "建筑装饰": "801720", "电力设备": "801730", "国防军工": "801740",
    "计算机": "801750", "传媒": "801760", "通信": "801770", "银行": "801780",
    "非银金融": "801790", "汽车": "801880", "机械设备": "801890", "煤炭": "801950",
    "石油石化": "801960", "环保": "801970", "美容护理": "801980",
}
MARKET_BOARD_NAMES = {"沪市主板", "深市主板", "创业板", "科创板", "北交所", "其他"}
GENERIC_CONCEPTS = {
    "融资融券",
    "深股通",
    "沪股通",
    "标准普尔",
    "富时罗素",
    "MSCI中国",
    "证金持股",
    "机构重仓",
    "昨日涨停",
    "昨日涨停_含一字",
    "深圳特区",
}
DYNAMIC_WORDS = ("昨日", "近期", "新高", "涨停", "高振幅", "趋势股", "连板")


def _as_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _json_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    text = _as_text(value)
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return [item for item in re.split(r"[、,，]", text) if item]
    return [str(item) for item in parsed if str(item).strip()] if isinstance(parsed, list) else []


def normalize_core_theme_rows(code: str, rows: list[dict[str, object]]) -> dict[str, object]:
    normalized = sorted(rows, key=lambda item: int(item.get("BOARD_RANK") or 999))
    names = [_as_text(item.get("BOARD_NAME")) for item in normalized]
    names = [name for name in names if name]
    broad_sector = names[0] if names else ""
    industry = names[1] if len(names) > 1 else broad_sector

    precise = []
    dynamic = []
    for item in normalized:
        name = _as_text(item.get("BOARD_NAME"))
        if not name:
            continue
        if any(word in name for word in DYNAMIC_WORDS):
            dynamic.append(name)
        if _as_text(item.get("IS_PRECISE")) == "1":
            if name not in GENERIC_CONCEPTS and not name.endswith("板块"):
                precise.append(name)

    concepts = list(dict.fromkeys(precise))[:8]
    event_tags = list(dict.fromkeys(dynamic))[:6]
    return {
        "code": str(code).zfill(6),
        "sector": broad_sector,
        "industry": industry,
        "concepts": json.dumps(concepts, ensure_ascii=False),
        "event_tags": json.dumps(event_tags, ensure_ascii=False),
        "source": "eastmoney_core_theme",
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def _fetch_core_theme_one(code: str, timeout: float = 8.0) -> dict[str, object]:
    import requests

    normalized = str(code).zfill(6)
    params = {
        "reportName": "RPT_F10_CORETHEME_BOARDTYPE",
        "columns": "SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,BOARD_CODE,BOARD_NAME,IS_PRECISE,BOARD_RANK",
        "source": "WEB",
        "client": "WEB",
        "filter": f'(SECURITY_CODE="{normalized}")',
        "sortColumns": "BOARD_RANK",
        "sortTypes": "1",
    }
    response = requests.get(CORE_THEME_URL, params=params, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    rows = (payload.get("result") or {}).get("data") or []
    return normalize_core_theme_rows(normalized, rows)


def fetch_stock_contexts(codes: Iterable[str], workers: int = 4) -> pd.DataFrame:
    unique_codes = list(dict.fromkeys(str(code).zfill(6) for code in codes))
    if not unique_codes:
        return pd.DataFrame(columns=["code", "sector", "industry", "concepts", "event_tags", "source", "updated_at"])
    records: list[dict[str, object]] = []
    max_workers = max(1, min(int(workers), len(unique_codes)))
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="context-fetch") as executor:
        futures = {executor.submit(_fetch_core_theme_one, code): code for code in unique_codes}
        for future in as_completed(futures):
            code = futures[future]
            try:
                record = future.result()
            except Exception as exc:
                LOGGER.warning("[%s] 核心题材更新失败: %s", code, exc)
                continue
            if record.get("industry") or record.get("concepts") != "[]":
                records.append(record)
    return pd.DataFrame(records)


def fetch_limit_up_events(trade_date: str) -> pd.DataFrame:
    columns = ["trade_date", "code", "event_type", "summary", "industry", "updated_at"]
    try:
        import akshare as ak

        raw = ak.stock_zt_pool_em(date=str(trade_date).replace("-", ""))
    except Exception as exc:
        LOGGER.warning("涨停池更新失败: %s", exc)
        return pd.DataFrame(columns=columns)
    if raw.empty or "代码" not in raw.columns:
        return pd.DataFrame(columns=columns)

    now = datetime.now().isoformat(timespec="seconds")
    records = []
    for row in raw.to_dict("records"):
        code = str(row.get("代码", "")).zfill(6)
        statistics = _as_text(row.get("涨停统计"))
        streak = pd.to_numeric(row.get("连板数"), errors="coerce")
        parts = ["当日涨停"]
        if statistics:
            parts.append(f"涨停统计 {statistics}")
        if pd.notna(streak) and int(streak) > 1:
            parts.append(f"{int(streak)} 连板")
        records.append(
            {
                "trade_date": trade_date,
                "code": code,
                "event_type": "limit_up",
                "summary": "，".join(parts),
                "industry": _as_text(row.get("所属行业")),
                "updated_at": now,
            }
        )
    return pd.DataFrame(records, columns=columns)


def calculate_sector_activity(raw: pd.DataFrame, sector_name: str, as_of_date: str) -> dict[str, object] | None:
    if raw.empty:
        return None
    prepared = raw.copy()
    date_column = "日期" if "日期" in prepared.columns else "trade_date" if "trade_date" in prepared.columns else None
    if date_column:
        parsed_dates = pd.to_datetime(prepared[date_column], errors="coerce")
        prepared = prepared.loc[parsed_dates.le(pd.Timestamp(as_of_date))].copy()
        prepared["_date"] = parsed_dates[parsed_dates.le(pd.Timestamp(as_of_date))]
        prepared = prepared.sort_values("_date")

    pct_column = "涨跌幅" if "涨跌幅" in prepared.columns else "pct_chg" if "pct_chg" in prepared.columns else None
    if pct_column:
        values = pd.to_numeric(prepared[pct_column], errors="coerce").dropna()
    else:
        close_column = "收盘" if "收盘" in prepared.columns else "close" if "close" in prepared.columns else None
        if not close_column:
            return None
        closes = pd.to_numeric(prepared[close_column], errors="coerce").dropna()
        values = closes.pct_change(fill_method=None).mul(100).dropna()
    if values.empty:
        return None

    def compounded(period: int) -> float:
        window = values.tail(period)
        return round(float(((1 + window / 100).prod() - 1) * 100), 2)

    return_5d = compounded(5)
    return_20d = compounded(20)
    return_120d = compounded(120)
    active_days = int(values.tail(20).abs().ge(2).sum())
    if return_120d >= 30:
        trend = "近半年趋势强势"
    elif return_120d >= 15:
        trend = "近半年保持上行"
    elif return_120d <= -10:
        trend = "近半年仍偏弱"
    else:
        trend = "近半年以震荡为主"
    summary = (
        f"{sector_name}近20日累计 {return_20d:+.1f}%"
        f"，出现 {active_days} 个明显异动日；近半年 {return_120d:+.1f}%，{trend}。"
    )
    return {
        "sector_name": sector_name,
        "as_of_date": as_of_date,
        "return_5d": return_5d,
        "return_20d": return_20d,
        "return_120d": return_120d,
        "active_days_20": active_days,
        "summary": summary,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def _fetch_sector_activity_one(sector_name: str, report_date: str) -> dict[str, object] | None:
    import requests
    import urllib3

    index_code = SW_PRIMARY_INDEXES.get(sector_name)
    if not index_code:
        return None
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    params = {"swindexcode": index_code, "period": "DAY"}
    headers = {"User-Agent": "Mozilla/5.0"}
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            response = requests.get(
                SW_INDEX_TREND_URL,
                params=params,
                headers=headers,
                timeout=15,
                verify=False,
            )
            response.raise_for_status()
            raw = pd.DataFrame(response.json().get("data") or []).rename(
                columns={"bargaindate": "日期", "closeindex": "收盘"}
            )
            return calculate_sector_activity(raw, sector_name, report_date)
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(0.8)
    if last_error:
        raise last_error
    return None


def fetch_sector_contexts(sector_names: Iterable[str], report_date: str, workers: int = 4) -> pd.DataFrame:
    names = [
        name
        for name in dict.fromkeys(_as_text(value) for value in sector_names)
        if name and name in SW_PRIMARY_INDEXES
    ]
    columns = [
        "sector_name",
        "as_of_date",
        "return_5d",
        "return_20d",
        "return_120d",
        "active_days_20",
        "summary",
        "updated_at",
    ]
    if not names:
        return pd.DataFrame(columns=columns)
    records: list[dict[str, object]] = []
    max_workers = max(1, min(int(workers), len(names), 2))
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="sector-context") as executor:
        futures = {executor.submit(_fetch_sector_activity_one, name, report_date): name for name in names}
        for future in as_completed(futures):
            name = futures[future]
            try:
                record = future.result()
            except Exception as exc:
                LOGGER.warning("[%s] 行业阶段表现更新失败: %s", name, exc)
                continue
            if record:
                records.append(record)
    return pd.DataFrame(records, columns=columns)


def _is_stale(updated_at: object, cache_days: int) -> bool:
    text = _as_text(updated_at)
    if not text:
        return True
    try:
        updated = datetime.fromisoformat(text)
    except ValueError:
        return True
    return updated < datetime.now() - timedelta(days=max(1, cache_days))


def refresh_context_cache(
    db: Database,
    codes: Iterable[str],
    report_date: str,
    config: FeatureConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    wanted = list(dict.fromkeys(str(code).zfill(6) for code in codes))[: config.context_top_n]
    cached = db.read_table("stock_context")
    cached_by_code = cached.set_index("code") if not cached.empty else pd.DataFrame()
    refresh_codes = []
    for code in wanted:
        if cached.empty or code not in cached_by_code.index:
            refresh_codes.append(code)
        elif _is_stale(cached_by_code.loc[code, "updated_at"], config.context_cache_days):
            refresh_codes.append(code)

    if refresh_codes:
        LOGGER.info("正在更新 %s 只候选股的行业与核心题材", len(refresh_codes))
        fresh = fetch_stock_contexts(refresh_codes, config.context_workers)
        if not fresh.empty:
            db.upsert_dataframe("stock_context", fresh, ["code"])

    contexts = db.read_table("stock_context")
    contexts = contexts[contexts["code"].astype(str).isin(wanted)].copy() if not contexts.empty else contexts

    events = db.read_table("stock_event")
    events = events[events["trade_date"].astype(str).eq(report_date)].copy() if not events.empty else events
    if events.empty:
        fresh_events = fetch_limit_up_events(report_date)
        if not fresh_events.empty:
            db.upsert_dataframe("stock_event", fresh_events, ["trade_date", "code", "event_type"])
            events = fresh_events

    sectors = [_as_text(value) for value in contexts.get("sector", pd.Series(dtype=str)).tolist()]
    sector_context = db.read_table("sector_context")
    current_sector = (
        sector_context[sector_context["as_of_date"].astype(str).eq(report_date)].copy()
        if not sector_context.empty
        else sector_context
    )
    existing = set(current_sector.get("sector_name", pd.Series(dtype=str)).astype(str))
    missing_sectors = [name for name in dict.fromkeys(sectors) if name and name not in existing]
    if missing_sectors:
        fresh_sector = fetch_sector_contexts(missing_sectors[:20], report_date, config.context_workers)
        if not fresh_sector.empty:
            db.upsert_dataframe("sector_context", fresh_sector, ["sector_name", "as_of_date"])
            current_sector = pd.concat([current_sector, fresh_sector], ignore_index=True)
            current_sector = current_sector.drop_duplicates(["sector_name", "as_of_date"], keep="last")
    return contexts, events, current_sector


def _reason_tags(row: pd.Series) -> list[str]:
    tags: list[str] = []
    for name in _as_text(row.get("matched_strategies")).split("、")[:2]:
        if name:
            tags.append(name)
    industry = _as_text(row.get("industry"))
    if industry and industry not in MARKET_BOARD_NAMES:
        tags.append(industry)
    if float(row.get("rps20", 0) or 0) >= 80:
        tags.append(f"RPS20 {float(row.get('rps20', 0)):.0f}")
    if float(row.get("amount_ratio", 0) or 0) >= 1.5:
        tags.append(f"放量 {float(row.get('amount_ratio', 0)):.1f}x")
    if bool(row.get("break_20d_high", False)):
        tags.append("20日新高")
    return list(dict.fromkeys(tags))[:4]


def _risk_tags(value: object) -> list[str]:
    text = _as_text(value).replace("风险提示：", "")
    if not text or "暂无明显" in text:
        return []
    return [item.strip() for item in re.split(r"[，；;]", text) if item.strip()][:3]


def merge_stock_context(
    ranked: pd.DataFrame,
    contexts: pd.DataFrame,
    events: pd.DataFrame,
    sector_context: pd.DataFrame,
) -> pd.DataFrame:
    result = ranked.copy()
    if "market_board" not in result.columns:
        result["market_board"] = result["code"].astype(str).map(market_board)

    if not contexts.empty:
        prepared = contexts.rename(
            columns={"sector": "context_sector", "industry": "context_industry"}
        )
        result = result.merge(
            prepared[["code", "context_sector", "context_industry", "concepts", "event_tags", "source"]],
            on="code",
            how="left",
        )
    for column in ["context_sector", "context_industry", "concepts", "event_tags", "source"]:
        if column not in result.columns:
            result[column] = ""

    context_industry = result["context_industry"].fillna("").astype(str).str.strip()
    result["industry"] = result["industry"].fillna("").astype(str)
    result.loc[context_industry.ne(""), "industry"] = context_industry[context_industry.ne("")]
    result["sector"] = result["context_sector"].fillna("")
    result["concepts"] = result["concepts"].map(lambda value: "、".join(_json_list(value)))
    result["event_tags"] = result["event_tags"].map(lambda value: "、".join(_json_list(value)))

    event_columns = ["code", "summary", "industry"]
    if not events.empty and set(event_columns) <= set(events.columns):
        limit_events = events[events["event_type"].astype(str).eq("limit_up")][event_columns].copy()
        limit_events = limit_events.rename(columns={"summary": "limit_up_event", "industry": "event_industry"})
        result = result.merge(limit_events.drop_duplicates("code"), on="code", how="left")
    if "limit_up_event" not in result.columns:
        result["limit_up_event"] = ""
    if "event_industry" not in result.columns:
        result["event_industry"] = ""
    missing_industry = result["industry"].isin(MARKET_BOARD_NAMES) | result["industry"].eq("")
    result.loc[missing_industry & result["event_industry"].fillna("").ne(""), "industry"] = result.loc[
        missing_industry & result["event_industry"].fillna("").ne(""), "event_industry"
    ]

    if not sector_context.empty and {"sector_name", "summary"} <= set(sector_context.columns):
        summaries = sector_context[["sector_name", "summary"]].drop_duplicates("sector_name")
        result = result.merge(summaries, left_on="sector", right_on="sector_name", how="left")
        result = result.rename(columns={"summary": "industry_activity"})
    if "industry_activity" not in result.columns:
        result["industry_activity"] = ""

    def limit_up_clue(row: pd.Series) -> str:
        event = _as_text(row.get("limit_up_event"))
        concepts = _as_text(row.get("concepts")).split("、")
        concept_text = "、".join([item for item in concepts if item][:2])
        if event:
            return event + (f"；相关题材：{concept_text}" if concept_text else "")
        if float(row.get("pct_chg", 0) or 0) >= 9.5:
            count = int(float(row.get("limit_up_count", 0) or 0))
            parts = ["量价涨停线索"]
            if concept_text:
                parts.append(f"相关题材：{concept_text}")
            if count:
                parts.append(f"近60日 {count} 次涨停")
            return "；".join(parts)
        return ""

    result["limit_up_reason"] = result.apply(limit_up_clue, axis=1)
    result["reason_tags"] = result.apply(lambda row: "、".join(_reason_tags(row)), axis=1)
    result["risk_tags"] = result["risk_warning"].map(lambda value: "、".join(_risk_tags(value)))
    result["selection_reason_short"] = result["reason_tags"].str.replace("、", " · ", regex=False)

    def context_summary(row: pd.Series) -> str:
        parts = []
        industry = _as_text(row.get("industry"))
        sector = _as_text(row.get("sector"))
        if industry and industry not in MARKET_BOARD_NAMES:
            parts.append(f"所属行业：{industry}" + (f"（{sector}）" if sector and sector != industry else ""))
        concepts = _as_text(row.get("concepts"))
        if concepts:
            parts.append(f"核心概念：{concepts}")
        activity = _as_text(row.get("industry_activity"))
        if activity:
            parts.append(activity)
        limit_up = _as_text(row.get("limit_up_reason"))
        if limit_up:
            parts.append(limit_up)
        return "；".join(parts)

    result["stock_context_summary"] = result.apply(context_summary, axis=1)
    return result


def enrich_ranked_context(
    db: Database,
    ranked: pd.DataFrame,
    report_date: str,
    config: FeatureConfig,
) -> pd.DataFrame:
    if ranked.empty:
        return ranked
    if not config.enable_context_enrichment:
        return merge_stock_context(ranked, pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    codes = ranked.head(config.context_top_n)["code"].astype(str).tolist()
    contexts, events, sectors = refresh_context_cache(db, codes, report_date, config)
    return merge_stock_context(ranked, contexts, events, sectors)
