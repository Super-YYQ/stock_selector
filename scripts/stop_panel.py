from __future__ import annotations

import http.client
import json
import os
import signal
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PID_FILE = ROOT / "data" / "panel.pid"


def read_health(port: int) -> dict[str, object] | None:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        connection.request("GET", "/api/health")
        response = connection.getresponse()
        if response.status != 200:
            return None
        payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, dict) else None
    except (OSError, http.client.HTTPException, json.JSONDecodeError):
        return None
    finally:
        connection.close()


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def stop_panel(port: int) -> bool:
    if not PID_FILE.exists():
        print("面板当前没有运行。")
        return False
    try:
        pid = int(PID_FILE.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        print("面板进程记录无效，未执行停止操作。")
        return False

    health = read_health(port)
    if not health or health.get("app") != "stock-selector" or health.get("pid") != pid:
        if not process_exists(pid):
            PID_FILE.unlink(missing_ok=True)
            print("面板当前没有运行。")
            return False
        print("无法确认目标进程属于本项目，未执行停止操作。")
        return False

    os.kill(pid, signal.SIGTERM)
    for _ in range(30):
        if not process_exists(pid):
            break
        time.sleep(0.1)
    PID_FILE.unlink(missing_ok=True)
    print("面板已停止。")
    return True


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from src.config import load_config

    port = load_config(ROOT / "config").panel.port
    stop_panel(port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
