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
    (tmp_path / "config" / "custom_strategies.yml").write_text(
        """
version: 1
strategies:
  - key: test_formula
    name: 测试公式
    enabled: true
    match: all
    conditions:
      - field: close
        operator: gte
        value: 10
        label: 收盘价不低于10元
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "site" / "data" / "latest.json").write_text(
        json.dumps({"report_date": "2026-06-22", "top50": []}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_panel_reads_report_status_and_updates_strategy_config(tmp_path: Path, monkeypatch) -> None:
    _project(tmp_path)
    monkeypatch.setattr(panel, "ROOT", tmp_path)
    monkeypatch.setattr(
        panel,
        "scheduler_status",
        lambda root: {"supported": True, "enabled": False, "time": "17:30"},
    )
    monkeypatch.setattr(
        panel,
        "update_scheduler",
        lambda root, **values: {"supported": True, **values},
    )

    latest = panel.latest_report()
    status = panel.status()
    strategies = panel.strategies()
    custom = panel.custom_strategies()
    schedule = panel.scheduler()
    saved_schedule = panel.save_scheduler(
        panel.SchedulerUpdate(enabled=True, time="18:00", publish=True)
    )
    updated = panel.update_strategies(
        panel.StrategyUpdate(enabled=["ma_volume", "sector_leader"], profile="custom")
    )
    updated_custom = panel.update_custom_strategies(panel.CustomStrategyUpdate(enabled=[]))
    pool = panel.update_pool_config(
        panel.PoolConfigUpdate(
            min_list_days=180,
            min_price=5,
            min_avg_amount_20d=200_000_000,
            exclude_st=True,
            exclude_suspended=True,
            exclude_boards=["北交所", "科创板"],
        )
    )

    assert latest["report_date"] == "2026-06-22"
    assert "health" in status
    assert strategies["enabled"] == ["ma_volume"]
    assert custom["catalog"][0]["key"] == "test_formula"
    assert schedule["enabled"] is False
    assert saved_schedule == {"supported": True, "enabled": True, "time": "18:00", "publish": True}
    assert updated_custom["catalog"][0]["enabled"] is False
    assert updated["enabled"] == ["ma_volume", "sector_leader"]
    assert pool["min_list_days"] == 180
    assert pool["exclude_boards"] == ["北交所", "科创板"]
    persisted = (tmp_path / "config" / "stock_pool.yml").read_text(encoding="utf-8")
    assert "北交所" in persisted
    assert "科创板" in persisted


def test_task_runner_captures_background_output() -> None:
    task = panel.TaskRunner()

    started = task.start(
        [sys.executable, "-c", "print('completed')"],
        mode="daily",
        report_date="2026-07-23",
    )
    assert started["running"] is True
    assert started["mode"] == "daily"
    assert started["report_date"] == "2026-07-23"
    assert "任务已提交" in started["output"]
    for _ in range(120):
        snapshot = task.snapshot()
        if not snapshot["running"]:
            break
        time.sleep(0.05)

    assert snapshot["last_status"] == "成功"
    assert "completed" in snapshot["output"]


def test_manual_run_uses_publish_setting(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_start(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return {"running": True}

    monkeypatch.setattr(panel, "ROOT", tmp_path)
    monkeypatch.setattr(panel, "scheduler_status", lambda root: {"publish": True})
    monkeypatch.setattr(panel.runner, "start", fake_start)

    result = panel.start_run(panel.RunRequest(mode="daily", date="2026-07-23"))

    command = captured["command"]
    assert result == {"running": True}
    assert command[:4] == [
        sys.executable,
        str(tmp_path / "scripts" / "bootstrap.py"),
        "--command",
        "daily",
    ]
    assert command[-3:] == ["--date", "2026-07-23", "--publish"]
