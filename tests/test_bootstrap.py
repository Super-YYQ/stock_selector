from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from scripts import bootstrap
from src.run_lock import RUN_LOCK_TOKEN_ENV


def test_bootstrap_holds_one_lock_across_daily_and_publish(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    lock_path = tmp_path / "run_daily.lock"
    python = tmp_path / "python"
    calls: list[dict[str, object]] = []
    args = argparse.Namespace(
        command="daily",
        date=None,
        snapshot="close",
        publish=True,
        no_browser=False,
    )

    monkeypatch.setattr(bootstrap, "RUN_LOCK_PATH", lock_path)
    monkeypatch.setattr(bootstrap, "ROOT", tmp_path)
    monkeypatch.setattr(bootstrap, "parse_args", lambda: args)
    monkeypatch.setattr(bootstrap, "ensure_environment", lambda: python)

    def fake_run(command, *, cwd, env=None):
        owner = json.loads(lock_path.read_text(encoding="utf-8"))
        calls.append(
            {
                "command": command,
                "cwd": cwd,
                "token": env.get(RUN_LOCK_TOKEN_ENV) if env else None,
                "owner_token": owner["token"],
            }
        )
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)

    assert bootstrap.main() == 0
    assert len(calls) == 2
    assert all(call["cwd"] == tmp_path for call in calls)
    assert all(call["token"] == call["owner_token"] for call in calls)
    assert not lock_path.exists()
    status = capsys.readouterr().err
    assert "主任务已退出，退出码：0" in status
    assert "主任务成功，开始发布 GitHub Pages 静态报告" in status
    assert "静态报告发布任务已退出，退出码：0" in status


def test_bootstrap_skips_publish_when_latest_is_provisional(
    tmp_path: Path,
    monkeypatch,
) -> None:
    lock_path = tmp_path / "run_daily.lock"
    python = tmp_path / "python"
    calls: list[dict[str, object]] = []
    args = argparse.Namespace(
        command="daily",
        date=None,
        snapshot="intraday",
        publish=True,
        no_browser=False,
    )

    monkeypatch.setattr(bootstrap, "RUN_LOCK_PATH", lock_path)
    monkeypatch.setattr(bootstrap, "ROOT", tmp_path)
    monkeypatch.setattr(bootstrap, "parse_args", lambda: args)
    monkeypatch.setattr(bootstrap, "ensure_environment", lambda: python)

    def fake_run(command, *, cwd, env=None):
        owner = json.loads(lock_path.read_text(encoding="utf-8"))
        calls.append({"command": command})
        # Simulate run_daily writing a provisional latest.json on the first call.
        latest = tmp_path / "site/data/latest.json"
        latest.parent.mkdir(parents=True, exist_ok=True)
        latest.write_text(
            json.dumps(
                {
                    "report_date": "2026-08-03",
                    "snapshot_type": "intraday",
                    "is_provisional": True,
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)

    assert bootstrap.main() == 0
    # The provisional snapshot suppresses the second publish_pages.py call.
    assert len(calls) == 1
