from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import threading
import webbrowser
from collections import deque
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pandas as pd
import uvicorn
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.config import load_config
from src.database import Database
from src.strategies.registry import STRATEGY_PROFILES, STRATEGY_REGISTRY, strategy_catalog


ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
LOGGER = logging.getLogger(__name__)


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    return json.loads(frame.to_json(orient="records", force_ascii=False))


class RunRequest(BaseModel):
    mode: str = Field(default="daily", pattern="^(daily|init)$")
    date: str | None = None


class StrategyUpdate(BaseModel):
    enabled: list[str]
    profile: str = "custom"


class TaskRunner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._output: deque[str] = deque(maxlen=400)
        self._started_at: str | None = None
        self._finished_at: str | None = None
        self._last_status = "空闲"
        self._command: list[str] = []

    def start(self, command: list[str]) -> dict[str, Any]:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                raise RuntimeError("已有任务正在执行")
            self._output.clear()
            self._started_at = datetime.now().isoformat(timespec="seconds")
            self._finished_at = None
            self._last_status = "运行中"
            self._command = command
            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            self._process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                creationflags=creationflags,
            )
            thread = threading.Thread(target=self._collect_output, daemon=True)
            thread.start()
        return self.snapshot()

    def _collect_output(self) -> None:
        process = self._process
        if process is None:
            return
        if process.stdout is not None:
            for line in process.stdout:
                self._output.append(line.rstrip())
        return_code = process.wait()
        with self._lock:
            self._finished_at = datetime.now().isoformat(timespec="seconds")
            self._last_status = "成功" if return_code == 0 else "失败"

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            running = self._process is not None and self._process.poll() is None
            return_code = None if running or self._process is None else self._process.returncode
            return {
                "running": running,
                "started_at": self._started_at,
                "finished_at": self._finished_at,
                "last_status": "运行中" if running else self._last_status,
                "return_code": return_code,
                "command": self._command,
                "output": "\n".join(self._output),
            }


runner = TaskRunner()
app = FastAPI(title="A股盘后选股助手", version="1.0.0")
if (WEB_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")


def _config():
    return load_config(ROOT / "config")


def _database() -> Database:
    config = _config()
    db = Database(ROOT / config.data.database)
    db.initialize()
    return db


def _latest_payload_path() -> Path:
    config = _config()
    return ROOT / config.report.site_dir / "data" / "latest.json"


@app.get("/api/latest")
def latest_report() -> Any:
    path = _latest_payload_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail="尚未生成盘后报告")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"报告数据读取失败: {exc}") from exc


@app.get("/api/status")
def status() -> dict[str, Any]:
    config = _config()
    db = _database()
    health = db.data_health()
    runs = _records(db.recent_runs(20))
    report_dir = ROOT / config.report.output_dir
    reports = []
    for path in sorted(report_dir.glob("*.xlsx"), key=lambda item: item.stat().st_mtime, reverse=True)[:30]:
        reports.append(
            {
                "name": path.name,
                "size": path.stat().st_size,
                "modified_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
                "download_url": "/api/reports/" + quote(path.name),
            }
        )
    return {
        "health": health,
        "runner": runner.snapshot(),
        "runs": runs,
        "reports": reports,
        "server_time": datetime.now().isoformat(timespec="seconds"),
    }


@app.get("/api/strategies")
def strategies() -> dict[str, Any]:
    config = _config()
    return {
        "catalog": strategy_catalog(),
        "enabled": config.strategies.enabled,
        "profile": config.strategies.profile,
        "profiles": STRATEGY_PROFILES,
    }


@app.put("/api/strategies")
def update_strategies(update: StrategyUpdate) -> dict[str, Any]:
    unknown = sorted(set(update.enabled) - set(STRATEGY_REGISTRY))
    if unknown:
        raise HTTPException(status_code=422, detail="未知策略: " + ", ".join(unknown))
    if not update.enabled:
        raise HTTPException(status_code=422, detail="至少启用一个策略")
    if update.profile not in set(STRATEGY_PROFILES) | {"custom"}:
        raise HTTPException(status_code=422, detail="未知策略组合")

    path = ROOT / "config" / "strategy.yml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw.setdefault("strategies", {})
    raw["strategies"]["enabled"] = list(dict.fromkeys(update.enabled))
    raw["strategies"]["profile"] = update.profile
    temporary = path.with_suffix(".yml.tmp")
    temporary.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    temporary.replace(path)
    return strategies()


@app.post("/api/run")
def start_run(request: RunRequest) -> dict[str, Any]:
    if request.date:
        try:
            datetime.strptime(request.date, "%Y-%m-%d")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="日期格式必须为 YYYY-MM-DD") from exc
    command = [sys.executable, str(ROOT / "run_daily.py")]
    if request.mode == "init":
        command.append("--init")
    if request.date:
        command.extend(["--date", request.date])
    try:
        return runner.start(command)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/run")
def run_status() -> dict[str, Any]:
    return runner.snapshot()


@app.get("/api/performance")
def performance() -> list[dict[str, Any]]:
    return _records(_database().strategy_performance())


@app.get("/api/reports/{filename}")
def download_report(filename: str) -> FileResponse:
    config = _config()
    report_dir = (ROOT / config.report.output_dir).resolve()
    path = (report_dir / filename).resolve()
    if path.parent != report_dir or path.suffix.lower() != ".xlsx" or not path.exists():
        raise HTTPException(status_code=404, detail="报告不存在")
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/")
def index() -> FileResponse:
    path = WEB_DIR / "index.html"
    if not path.exists():
        raise HTTPException(status_code=500, detail="面板静态文件缺失")
    return FileResponse(path)


@app.get("/{path:path}")
def single_page_app(path: str) -> FileResponse:
    requested = (WEB_DIR / path).resolve()
    if requested.is_file() and WEB_DIR.resolve() in requested.parents:
        return FileResponse(requested)
    return FileResponse(WEB_DIR / "index.html")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    config = _config()
    parser = argparse.ArgumentParser(description="启动 A股盘后选股助手管理面板")
    parser.add_argument("--host", default=config.panel.host)
    parser.add_argument("--port", type=int, default=config.panel.port)
    parser.add_argument("--no-browser", action="store_true")
    return parser.parse_args(argv)


def run_panel(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    should_open = _config().panel.open_browser and not args.no_browser
    url = f"http://127.0.0.1:{args.port}"
    if should_open:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        LOGGER.warning("面板正在监听非本机地址，请在反向代理层配置身份验证和 HTTPS")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    run_panel()
