from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.run_lock import (
    RUN_LOCK_TOKEN_ENV,
    RunAlreadyLockedError,
    SingleInstanceRunLock,
)


ROOT = Path(__file__).resolve().parents[1]


def test_lock_records_owner_and_releases_cleanly(tmp_path: Path) -> None:
    path = tmp_path / "run_daily.lock"

    with SingleInstanceRunLock(path):
        owner = json.loads(path.read_text(encoding="utf-8"))
        assert owner["pid"] > 0
        assert owner["started_at"]
        assert owner["token"]
        with pytest.raises(RunAlreadyLockedError, match="已有选股任务正在执行"):
            SingleInstanceRunLock(path).acquire()

    assert not path.exists()


def test_dead_process_lock_is_recovered(tmp_path: Path) -> None:
    path = tmp_path / "run_daily.lock"
    path.write_text(
        json.dumps(
            {
                "pid": 99_999_999,
                "started_at": "2020-01-01T00:00:00+08:00",
                "token": "stale",
            }
        ),
        encoding="utf-8",
    )

    with SingleInstanceRunLock(path):
        owner = json.loads(path.read_text(encoding="utf-8"))
        assert owner["pid"] != 99_999_999
        assert owner["token"] != "stale"

    assert not path.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific PID probe")
def test_windows_pid_probe_never_sends_console_signals(monkeypatch) -> None:
    from src import run_lock

    def forbidden_kill(*args: object, **kwargs: object) -> None:
        raise AssertionError("os.kill must not be used to probe PIDs on Windows")

    monkeypatch.setattr(run_lock.os, "kill", forbidden_kill)
    assert run_lock._pid_is_running(os.getpid()) is True
    assert run_lock._pid_is_running(99_999_999) is False


def test_lock_excludes_a_second_python_process(tmp_path: Path) -> None:
    path = tmp_path / "run_daily.lock"
    script = (
        "import sys\n"
        "from src.run_lock import SingleInstanceRunLock\n"
        f"lock = SingleInstanceRunLock({str(path)!r})\n"
        "lock.acquire()\n"
        "print('ready', flush=True)\n"
        "sys.stdin.readline()\n"
        "lock.release()\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "ready"
        with pytest.raises(RunAlreadyLockedError):
            SingleInstanceRunLock(path).acquire()
    finally:
        if process.stdin is not None:
            process.stdin.write("\n")
            process.stdin.flush()
        process.wait(timeout=10)

    assert process.returncode == 0
    assert not path.exists()


def test_child_process_can_reuse_parent_bootstrap_lock(tmp_path: Path) -> None:
    path = tmp_path / "run_daily.lock"
    script = (
        "from src.run_lock import coordinated_run_lock\n"
        f"with coordinated_run_lock({str(path)!r}):\n"
        "    print('inherited', flush=True)\n"
    )

    with SingleInstanceRunLock(path) as lock:
        child_env = os.environ.copy()
        child_env[RUN_LOCK_TOKEN_ENV] = lock.token
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=child_env,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "inherited"
        assert path.exists()

    assert not path.exists()
