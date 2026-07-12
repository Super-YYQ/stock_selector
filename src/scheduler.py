from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


TASK_NAME = "A股盘后选股助手"
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


def scheduler_status(root: Path) -> dict[str, Any]:
    if not _is_windows():
        return {
            "supported": False,
            "enabled": False,
            "task_name": TASK_NAME,
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


def update_scheduler(root: Path, *, enabled: bool, time: str, publish: bool) -> dict[str, Any]:
    if not _is_windows():
        raise SchedulerError("当前面板仅支持管理 Windows 计划任务")
    if not TIME_PATTERN.fullmatch(time):
        raise SchedulerError("执行时间必须为 HH:MM 格式")
    if enabled:
        arguments = ["-Time", time]
        if publish:
            arguments.append("-Publish")
        _run_script(root, "install_scheduler.ps1", arguments)
    else:
        _run_script(root, "uninstall_scheduler.ps1")
    return scheduler_status(root)
