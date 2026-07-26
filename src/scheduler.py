from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


TASK_NAME = "A股盘后选股助手"
DEFAULT_MIDDAY_TIME = "12:30"
TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class SchedulerError(RuntimeError):
    """Raised when the local scheduler cannot be read or changed."""


def _powershell() -> str:
    return "powershell.exe" if os.name == "nt" else "powershell"


def _is_windows() -> bool:
    return os.name == "nt"


def _run_script(root: Path, script_name: str, arguments: list[str] | None = None) -> str:
    script = root / "scripts" / script_name
    if not script.exists():
        raise SchedulerError(f"计划任务脚本不存在: {script.name}")
    command = [
        _powershell(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        *(arguments or []),
    ]
    try:
        result = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SchedulerError(f"计划任务命令执行失败: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "未知错误").strip()
        raise SchedulerError(detail)
    return result.stdout.strip()


def _is_permission_error(error: SchedulerError) -> bool:
    message = str(error).lower()
    return (
        "access is denied" in message
        or "permissiondenied" in message
        or "0x80041003" in message
        or "拒绝访问" in str(error)
    )


def _run_scheduler_change(
    root: Path,
    *,
    enabled: bool,
    time: str,
    publish: bool,
    midday_enabled: bool,
    midday_time: str,
) -> None:
    if enabled:
        script_name = "install_scheduler.ps1"
        arguments = ["-Time", time]
        elevated_arguments = ["-Operation", "install", "-Time", time]
        if midday_enabled:
            arguments.extend(["-Midday", "-MiddayTime", midday_time])
            elevated_arguments.extend(["-Midday", "-MiddayTime", midday_time])
        if publish:
            arguments.append("-Publish")
            elevated_arguments.append("-Publish")
    else:
        script_name = "uninstall_scheduler.ps1"
        arguments = []
        elevated_arguments = ["-Operation", "uninstall"]
    try:
        _run_script(root, script_name, arguments)
    except SchedulerError as exc:
        if not _is_permission_error(exc):
            raise
        _run_script(root, "scheduler_elevated.ps1", elevated_arguments)


def scheduler_status(root: Path) -> dict[str, Any]:
    if not _is_windows():
        return {
            "supported": False,
            "enabled": False,
            "task_name": TASK_NAME,
            "time": "17:30",
            "midday_enabled": False,
            "midday_time": DEFAULT_MIDDAY_TIME,
            "message": "当前面板仅支持管理 Windows 计划任务",
        }
    output = _run_script(root, "scheduler_status.ps1")
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise SchedulerError("计划任务状态返回格式异常") from exc
    if not isinstance(payload, dict):
        raise SchedulerError("计划任务状态返回格式异常")
    return payload


def _minutes(value: str) -> int:
    hours, minutes = value.split(":", 1)
    return int(hours) * 60 + int(minutes)


def update_scheduler(
    root: Path,
    *,
    enabled: bool,
    time: str,
    publish: bool,
    midday_enabled: bool = False,
    midday_time: str = DEFAULT_MIDDAY_TIME,
) -> dict[str, Any]:
    if not _is_windows():
        raise SchedulerError("当前面板仅支持管理 Windows 计划任务")
    if not TIME_PATTERN.fullmatch(time):
        raise SchedulerError("盘后执行时间必须为 HH:MM 格式")
    if not TIME_PATTERN.fullmatch(midday_time):
        raise SchedulerError("午间快照时间必须为 HH:MM 格式")
    if midday_enabled and _minutes(midday_time) >= _minutes(time):
        raise SchedulerError("午间快照时间必须早于盘后执行时间")
    _run_scheduler_change(
        root,
        enabled=enabled,
        time=time,
        publish=publish,
        midday_enabled=midday_enabled,
        midday_time=midday_time,
    )
    return scheduler_status(root)
