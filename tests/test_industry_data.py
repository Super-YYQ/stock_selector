import pandas as pd

from src.industry_data import apply_point_in_time_industry, normalize_sw_industry_history


def test_normalize_and_resolve_sw_industry_point_in_time() -> None:
    raw = pd.DataFrame(
        [
            {"股票代码": "000001.SZ", "行业代码": "480000", "行业名称": "银行", "计入日期": "2020/01/01"},
            {"股票代码": "000001.SZ", "行业代码": "710000", "行业名称": "综合金融", "计入日期": "2025/01/01"},
            {"股票代码": "600000.SH", "行业代码": "480000", "行业名称": "银行", "计入日期": "2020/01/01"},
        ]
    )
    history = normalize_sw_industry_history(raw)
    basic = pd.DataFrame([{"code": "000001", "industry": ""}, {"code": "600000", "industry": ""}])

    old = apply_point_in_time_industry(basic, history, "2024-12-31")
    new = apply_point_in_time_industry(basic, history, "2026-01-01")

    assert old.loc[old["code"] == "000001", "industry"].iloc[0] == "银行"
    assert new.loc[new["code"] == "000001", "industry"].iloc[0] == "综合金融"
    assert set(new["industry_source"]) == {"sw2021"}


def test_point_in_time_industry_preserves_basic_when_history_is_unavailable() -> None:
    basic = pd.DataFrame([{"code": "000001", "industry": "银行"}])

    result = apply_point_in_time_industry(basic, pd.DataFrame(), "2026-01-01")

    assert result.loc[0, "industry"] == "银行"
    assert result.loc[0, "industry_source"] == "stock_basic"
