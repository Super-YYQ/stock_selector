import json
from pathlib import Path

import pytest

import src.scheduler as scheduler


def test_windows_scheduler_scripts_are_powershell5_ascii_safe() -> None:
    root = Path(__file__).resolve().parents[1]
    for name in (
        "install_scheduler.ps1",
        "uninstall_scheduler.ps1",
        "scheduler_status.ps1",
        "scheduler_elevated.ps1",
    ):
        (root / "scripts" / name).read_bytes().decode("ascii")


def test_scheduler_status_does_not_treat_permission_errors_as_missing() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts" / "scheduler_status.ps1").read_text(encoding="utf-8")

    assert "Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop" in script
    assert "CmdletizationQuery_NotFound_TaskName" in script
    assert "Unable to read scheduled task" in script
    assert "Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue" not in script


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


def test_update_scheduler_retries_permission_error_with_uac(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[str, list[str]]] = []

    def fake_run(root: Path, name: str, arguments: list[str] | None = None) -> str:
        calls.append((name, arguments or []))
        if name == "install_scheduler.ps1":
            raise scheduler.SchedulerError("Access is denied (0x80041003)")
        return json.dumps({"supported": True, "enabled": True, "time": "17:30"})

    monkeypatch.setattr(scheduler, "_is_windows", lambda: True)
    monkeypatch.setattr(scheduler, "_run_script", fake_run)

    result = scheduler.update_scheduler(tmp_path, enabled=True, time="17:30", publish=False)

    assert result["enabled"] is True
    assert calls[1] == (
        "scheduler_elevated.ps1",
        ["-Operation", "install", "-Time", "17:30"],
    )
