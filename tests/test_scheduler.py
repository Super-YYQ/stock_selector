import json
from pathlib import Path

import pytest

import src.scheduler as scheduler


def test_scheduler_status_parses_windows_payload(tmp_path: Path, monkeypatch) -> None:
    payload = {
        "supported": True,
        "enabled": True,
        "task_name": scheduler.TASK_NAME,
        "time": "17:45",
        "publish": True,
        "state": "Ready",
    }
    monkeypatch.setattr(scheduler, "_is_windows", lambda: True)
    monkeypatch.setattr(scheduler, "_run_script", lambda root, name, arguments=None: json.dumps(payload))

    assert scheduler.scheduler_status(tmp_path) == payload


def test_update_scheduler_uses_allowlisted_script_arguments(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[str, list[str]]] = []

    def fake_run(root: Path, name: str, arguments: list[str] | None = None) -> str:
        calls.append((name, arguments or []))
        return json.dumps({"supported": True, "enabled": True, "time": "18:05"})

    monkeypatch.setattr(scheduler, "_is_windows", lambda: True)
    monkeypatch.setattr(scheduler, "_run_script", fake_run)

    result = scheduler.update_scheduler(tmp_path, enabled=True, time="18:05", publish=True)

    assert result["enabled"] is True
    assert calls[0] == ("install_scheduler.ps1", ["-Time", "18:05", "-Publish"])
    assert calls[1][0] == "scheduler_status.ps1"


def test_update_scheduler_rejects_invalid_time(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(scheduler, "_is_windows", lambda: True)

    with pytest.raises(scheduler.SchedulerError, match="HH:MM"):
        scheduler.update_scheduler(tmp_path, enabled=True, time="25:90", publish=False)
