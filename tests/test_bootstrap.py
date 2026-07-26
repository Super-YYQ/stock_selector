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
