from __future__ import annotations

import argparse
import hashlib
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


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def requirements_hash() -> str:
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def ensure_environment() -> Path:
    if sys.version_info < (3, 11):
        raise RuntimeError("需要 Python 3.11 或更高版本，推荐 Python 3.12")
    python = venv_python()
    if not python.exists():
        print("[1/2] 正在创建本地 Python 环境 .venv")
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
    marker = VENV / ".requirements.sha256"
    current_hash = requirements_hash()
    if not marker.exists() or marker.read_text(encoding="ascii").strip() != current_hash:
        print("[2/2] 正在安装或更新依赖")
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

    result = subprocess.run(command, cwd=ROOT, env=child_env)
    if result.returncode == 0 and args.publish and args.command in {"daily", "init"}:
        result = subprocess.run(
            [str(python), str(ROOT / "scripts" / "publish_pages.py")],
            cwd=ROOT,
            env=child_env,
        )
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
