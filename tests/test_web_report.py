import json
from pathlib import Path

import pandas as pd

from src.web_report import build_report_payload, write_static_report


def test_static_report_writes_latest_and_history(tmp_path: Path) -> None:
    template = tmp_path / "web"
    (template / "assets").mkdir(parents=True)
    (template / "index.html").write_text("<html>report</html>", encoding="utf-8")
    (template / "assets" / "app.css").write_text("body{}", encoding="utf-8")
    top = pd.DataFrame(
        [
            {
                "rank": 1,
                "code": "000001",
                "name": "测试股票",
                "matched_strategies": "均线放量突破",
                "total_score": 88.0,
            }
        ]
    )
    payload = build_report_payload(
        "2026-06-22",
        {"market_label": "偏强", "market_score": 7.5, "index_changes": {"sh000001": 1.2}},
        pd.DataFrame([{"sector_name": "机器人", "sector_score_raw": 90}]),
        top,
        top,
        pd.DataFrame([{"strategy": "均线放量突破", "sample_count": 3}]),
        {"stock_coverage": 0.98},
    )

    path = write_static_report(tmp_path / "site", payload, template_dir=template)
    latest = json.loads((tmp_path / "site" / "data" / "latest.json").read_text(encoding="utf-8"))

    assert path.exists()
    assert latest["report_date"] == "2026-06-22"
    assert latest["top50"][0]["name"] == "测试股票"
    assert latest["strategy_distribution"] == [{"strategy": "均线放量突破", "count": 1}]
    assert latest["custom_strategies"] == []
    assert latest["custom_strategy_results"] == []
    assert (tmp_path / "site" / "data" / "history" / "2026-06-22.json").exists()
    assert (tmp_path / "site" / "assets" / "app.css").exists()
