import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import src.scheduler as scheduler


def _install_scheduler_inner_command_template() -> str:
    script = Path(__file__).resolve().parents[1] / "scripts" / "install_scheduler.ps1"
    match = re.search(
        r"^\$InnerCommand = '(.+)' -f ",
        script.read_text(encoding="ascii"),
        flags=re.M,
    )
    assert match is not None, "install_scheduler.ps1 must define $InnerCommand"
    return match.group(1)


def test_windows_scheduler_scripts_are_powershell5_ascii_safe() -> None:
    root = Path(__file__).resolve().parents[1]
    for name in (
        "install_scheduler.ps1",
        "uninstall_scheduler.ps1",
        "scheduler_status.ps1",
        "scheduler_elevated.ps1",
    ):
        (root / "scripts" / name).read_bytes().decode("ascii")


def test_install_scheduler_redirects_task_output_to_log_file() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts" / "install_scheduler.ps1").read_text(encoding="ascii")

    assert "cmd.exe" in script
    assert "bootstrap.log" in script
    assert ">>" in script
    assert "2>&1" in script
    assert 'New-ScheduledTaskAction -Execute "$env:SystemRoot\\System32\\cmd.exe"' in script


def test_install_scheduler_does_not_bind_python_to_mkdir_if() -> None:
    template = _install_scheduler_inner_command_template()

    # cmd.exe parses `if cond command1 & command2` as `if cond (command1 & command2)`.
    # When logs/ already exists the python process is skipped and the task still
    # returns 0. Parentheses make mkdir optional and python unconditional.
    assert template.startswith("(if not exist "), template
    assert ') & "{1}"' in template


@pytest.mark.skipif(os.name != "nt", reason="cmd.exe IF chaining is Windows-specific")
def test_scheduler_cmd_wrapper_runs_python_when_logs_already_exist() -> None:
    template = _install_scheduler_inner_command_template()
    work = Path(__file__).resolve().parents[1] / ".pytest_tmp" / "scheduler_cmd_wrapper"
    if work.exists():
        for child in work.rglob("*"):
            if child.is_file():
                child.unlink()
    logs = work / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log_file = logs / "bootstrap.log"
    marker = work / "ran.txt"
    if marker.exists():
        marker.unlink()
    probe = work / "probe.py"
    probe.write_text(
        "from pathlib import Path\n"
        f"Path(r'{marker.as_posix()}').write_text('ok', encoding='utf-8')\n",
        encoding="utf-8",
    )

    inner = template.format(str(logs), sys.executable, f'"{probe}"', str(log_file))
    completed = subprocess.run(f'cmd.exe /c "{inner}"', cwd=work, check=False)

    assert marker.exists(), (
        "scheduled cmd wrapper skipped python because logs already existed "
        f"(exit={completed.returncode}; inner={inner!r})"
    )


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


def test_update_scheduler_adds_optional_midday_trigger_arguments(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[str, list[str]]] = []

    def fake_run(root: Path, name: str, arguments: list[str] | None = None) -> str:
        calls.append((name, arguments or []))
        return json.dumps(
            {
                "supported": True,
                "enabled": True,
                "time": "17:30",
                "midday_enabled": True,
                "midday_time": "12:20",
            }
        )

    monkeypatch.setattr(scheduler, "_is_windows", lambda: True)
    monkeypatch.setattr(scheduler, "_run_script", fake_run)

    scheduler.update_scheduler(
        tmp_path,
        enabled=True,
        time="17:30",
        publish=False,
        midday_enabled=True,
        midday_time="12:20",
    )

    assert calls[0] == (
        "install_scheduler.ps1",
        ["-Time", "17:30", "-Midday", "-MiddayTime", "12:20"],
    )


def test_update_scheduler_rejects_invalid_time(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(scheduler, "_is_windows", lambda: True)

    with pytest.raises(scheduler.SchedulerError, match="HH:MM"):
        scheduler.update_scheduler(tmp_path, enabled=True, time="25:90", publish=False)


def test_update_scheduler_rejects_midday_after_close(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(scheduler, "_is_windows", lambda: True)

    with pytest.raises(scheduler.SchedulerError, match="早于"):
        scheduler.update_scheduler(
            tmp_path,
            enabled=True,
            time="12:00",
            publish=False,
            midday_enabled=True,
            midday_time="12:30",
        )


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
