import json
import sys
import time
from pathlib import Path

import src.panel as panel


def _project(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "site" / "data").mkdir(parents=True)
    (tmp_path / "reports").mkdir()
    (tmp_path / "config" / "strategy.yml").write_text(
        """
data:
  provider: tdx
  database: data/test.db
report:
  output_dir: reports
  site_dir: site
panel:
  host: 127.0.0.1
  port: 8765
strategies:
  enabled:
    - ma_volume
  profile: custom
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "config" / "stock_pool.yml").write_text("", encoding="utf-8")
    (tmp_path / "site" / "data" / "latest.json").write_text(
        json.dumps({"report_date": "2026-06-22", "top50": []}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_panel_reads_report_status_and_updates_strategy_config(tmp_path: Path, monkeypatch) -> None:
    _project(tmp_path)
    monkeypatch.setattr(panel, "ROOT", tmp_path)

    latest = panel.latest_report()
    status = panel.status()
    strategies = panel.strategies()
    updated = panel.update_strategies(
        panel.StrategyUpdate(enabled=["ma_volume", "sector_leader"], profile="custom")
    )

    assert latest["report_date"] == "2026-06-22"
    assert "health" in status
    assert strategies["enabled"] == ["ma_volume"]
    assert updated["enabled"] == ["ma_volume", "sector_leader"]


def test_task_runner_captures_background_output() -> None:
    task = panel.TaskRunner()

    started = task.start([sys.executable, "-c", "print('completed')"])
    assert started["running"] is True
    for _ in range(120):
        snapshot = task.snapshot()
        if not snapshot["running"]:
            break
        time.sleep(0.05)

    assert snapshot["last_status"] == "成功"
    assert "completed" in snapshot["output"]
