from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.run_lock import RUN_LOCK_TOKEN_ENV, SingleInstanceRunLock


VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
RUN_LOCK_PATH = ROOT / "data" / "run_daily.lock"
LATEST_REPORT_PATH = "site/data/latest.json"


def _status(message: str) -> None:
    """Write orchestration status to stderr so a blocked stdout cannot stall a run."""

    sys.stderr.write(f"{message}\n")
    sys.stderr.flush()


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def requirements_hash() -> str:
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def ensure_environment() -> Path:
    if sys.version_info < (3, 11):
        raise RuntimeError("需要 Python 3.11 或更高版本，推荐 Python 3.12")
    python = venv_python()
    if not python.exists():
        _status("[1/2] 正在创建本地 Python 环境 .venv")
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
    marker = VENV / ".requirements.sha256"
    current_hash = requirements_hash()
    if not marker.exists() or marker.read_text(encoding="ascii").strip() != current_hash:
        _status("[2/2] 正在安装或更新依赖")
        subprocess.run([str(python), "-m", "pip", "install", "-r", str(REQUIREMENTS)], cwd=ROOT, check=True)
        marker.write_text(current_hash, encoding="ascii")
    return python


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--command", choices=["panel", "daily", "init", "publish"], default="panel")
    parser.add_argument("--date")
    parser.add_argument("--snapshot", choices=["auto", "intraday", "close"], default="auto")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    return parser.parse_args()


def _latest_report_is_provisional() -> bool:
    """仅当 site/data/latest.json 成功解析为 dict 且为盘中临时快照时返回 True。

    任何读取或解析失败都返回 False（fail-open，照常发布），这样测试里
    subprocess.run 被 mock 不会真正写出该文件时仍能进入发布，也将运维中
    的瞬时读取错误转化为不丢发布，避免悄悄吞掉应当发布的正式报告。"""
    path = ROOT / LATEST_REPORT_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    if bool(data.get("is_provisional")):
        return True
    snapshot_type = data.get("snapshot_type")
    return isinstance(snapshot_type, str) and snapshot_type == "intraday"


def _execute(args: argparse.Namespace, child_env: dict[str, str] | None = None) -> int:
    python = ensure_environment()
    if args.command == "panel":
        command = [str(python), "-m", "src.panel"]
        if args.no_browser:
            command.append("--no-browser")
    elif args.command == "publish":
        command = [str(python), str(ROOT / "scripts" / "publish_pages.py")]
    else:
        command = [str(python), str(ROOT / "run_daily.py")]
        if args.command == "init":
            command.append("--init")
        if args.date:
            command.extend(["--date", args.date])
        command.extend(["--snapshot", args.snapshot])

    _status(f"开始执行主任务：{' '.join(command)}")
    result = subprocess.run(command, cwd=ROOT, env=child_env)
    _status(f"主任务已退出，退出码：{result.returncode}")
    if result.returncode == 0 and args.publish and args.command in {"daily", "init"}:
        if _latest_report_is_provisional():
            _status("跳过发布：当前为盘中临时快照（intraday），不作为正式报告发布")
            return result.returncode
        _status("主任务成功，开始发布 GitHub Pages 静态报告")
        result = subprocess.run(
            [str(python), str(ROOT / "scripts" / "publish_pages.py")],
            cwd=ROOT,
            env=child_env,
        )
        _status(f"静态报告发布任务已退出，退出码：{result.returncode}")
    elif result.returncode == 0 and args.command in {"daily", "init"}:
        _status("主任务成功；本次未启用自动发布")
    return result.returncode


def main() -> int:
    args = parse_args()
    if args.command not in {"daily", "init", "publish"}:
        return _execute(args)

    with SingleInstanceRunLock(RUN_LOCK_PATH) as lock:
        child_env = os.environ.copy()
        child_env[RUN_LOCK_TOKEN_ENV] = lock.token
        return _execute(args, child_env)


if __name__ == "__main__":
    raise SystemExit(main())
