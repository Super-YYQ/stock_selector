from __future__ import annotations

from pathlib import Path

import pandas as pd


TOP50_COLUMNS = {
    "rank": "排名",
    "code": "股票代码",
    "name": "股票名称",
    "total_score": "总分",
    "industry": "所属板块",
    "pct_chg": "今日涨跌幅",
    "return_5d": "近5日涨跌幅",
    "return_20d": "近20日涨跌幅",
    "amount_ratio": "成交额放大倍数",
    "rps20": "RPS20",
    "rps60": "RPS60",
    "sector_score": "板块分",
    "stock_character_score": "股性分",
    "volume_price_score": "量价分",
    "strategy_score": "策略分",
    "risk_penalty": "风险扣分",
    "matched_strategies": "命中策略",
    "strategy_reason": "策略理由",
    "selection_reason": "入选理由",
    "risk_warning": "风险提示",
}

TOP10_COLUMNS = {
    "rank": "排名",
    "code": "股票代码",
    "name": "股票名称",
    "total_score": "总分",
    "matched_strategies": "命中策略",
    "strategy_reason": "策略理由",
    "selection_reason": "重点关注理由",
    "next_day_condition": "次日观察条件",
    "risk_warning": "风险提示",
}


def _rename_existing(df: pd.DataFrame, columns: dict[str, str]) -> pd.DataFrame:
    existing = [column for column in columns if column in df.columns]
    return df[existing].rename(columns=columns)


def write_excel_report(
    output_dir: str | Path,
    report_date: str,
    market: dict[str, object],
    strong_sectors: pd.DataFrame,
    top50: pd.DataFrame,
    top10: pd.DataFrame,
    ranked: pd.DataFrame,
    filtered: pd.DataFrame,
) -> Path:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    path = output / f"{report_date}_盘后选股报告.xlsx"
    market_df = pd.DataFrame([market])
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        market_df.to_excel(writer, sheet_name="市场环境", index=False)
        strong_sectors.to_excel(writer, sheet_name="强势板块", index=False)
        _rename_existing(top50, TOP50_COLUMNS).to_excel(writer, sheet_name="Top50观察名单", index=False)
        _rename_existing(top10, TOP10_COLUMNS).to_excel(writer, sheet_name="Top10重点关注", index=False)
        filtered.to_excel(writer, sheet_name="风险过滤名单", index=False)
        ranked.to_excel(writer, sheet_name="原始评分明细", index=False)
    return path
