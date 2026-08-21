from __future__ import annotations

import errno
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator
from uuid import uuid4


LOCK_WRITE_GRACE_SECONDS = 30
RUN_LOCK_TOKEN_ENV = "STOCK_SELECTOR_RUN_LOCK_TOKEN"


class RunAlreadyLockedError(RuntimeError):
    """Raised when another daily pipeline process owns the run lock."""


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        # os.kill(pid, 0) must never be used on Windows: sig 0 maps to
        # CTRL_C_EVENT and interrupts every process attached to this console.
        return _windows_pid_is_running(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        if exc.errno == errno.ESRCH or getattr(exc, "winerror", None) == 87:
            return False
        return True
    return True


def _windows_pid_is_running(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    ERROR_ACCESS_DENIED = 5
    STILL_ACTIVE = 259
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        # A missing process reports ERROR_INVALID_PARAMETER (87); an existing
        # process we cannot query reports ERROR_ACCESS_DENIED (5).
        return kernel32.GetLastError() == ERROR_ACCESS_DENIED
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


class SingleInstanceRunLock:
    """A small cross-platform lock based on atomic file creation."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.recovery_path = self.path.with_name(f"{self.path.name}.recovery")
        self.token = uuid4().hex
        self._acquired = False

    def _metadata(self) -> dict[str, object]:
        return {
            "pid": os.getpid(),
            "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "token": self.token,
        }

    def _create(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor: int | None = os.open(
            self.path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        )
        try:
            payload = json.dumps(self._metadata(), ensure_ascii=False, indent=2).encode("utf-8")
            os.write(descriptor, payload)
            os.fsync(descriptor)
        except Exception:
            if descriptor is not None:
                os.close(descriptor)
                descriptor = None
            try:
                self.path.unlink()
            except OSError:
                pass
            raise
        finally:
            if descriptor is not None:
                os.close(descriptor)
        self._acquired = True

    def _read_owner(self) -> dict[str, object] | None:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def _age_seconds(self, path: Path) -> float:
        try:
            return max(0.0, time.time() - path.stat().st_mtime)
        except OSError:
            return 0.0

    def _is_stale(self) -> bool:
        owner = self._read_owner()
        if owner is None:
            return self._age_seconds(self.path) >= LOCK_WRITE_GRACE_SECONDS
        try:
            pid = int(owner["pid"])
        except (KeyError, TypeError, ValueError):
            return self._age_seconds(self.path) >= LOCK_WRITE_GRACE_SECONDS
        return not _pid_is_running(pid)

    def _remove_stale_lock(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        recovery_descriptor: int | None = None
        for _attempt in range(2):
            try:
                recovery_descriptor = os.open(
                    self.recovery_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                break
            except FileExistsError:
                if self._age_seconds(self.recovery_path) < LOCK_WRITE_GRACE_SECONDS:
                    return False
                try:
                    self.recovery_path.unlink()
                except OSError:
                    return False
        if recovery_descriptor is None:
            return False

        try:
            if not self.path.exists() or not self._is_stale():
                return False
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            return True
        finally:
            os.close(recovery_descriptor)
            try:
                self.recovery_path.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _owner_description(owner: dict[str, object] | None) -> str:
        if owner is None:
            return "锁文件正在写入"
        pid = owner.get("pid", "未知")
        started_at = owner.get("started_at", "未知")
        return f"PID {pid}，开始时间 {started_at}"

    def acquire(self) -> None:
        for _attempt in range(3):
            try:
                self._create()
                return
            except FileExistsError:
                if self._remove_stale_lock():
                    continue
                owner = self._read_owner()
                raise RunAlreadyLockedError(
                    "已有选股任务正在执行"
                    f"（{self._owner_description(owner)}），为避免并发写入，本次启动已拒绝。"
                )
        raise RunAlreadyLockedError("已有选股任务正在执行，本次启动已拒绝。")

    def release(self) -> None:
        if not self._acquired:
            return
        try:
            owner = self._read_owner()
            if owner is not None and owner.get("token") == self.token:
                self.path.unlink(missing_ok=True)
        finally:
            self._acquired = False

    def __enter__(self) -> SingleInstanceRunLock:
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()


def _inherited_lock_is_valid(path: str | Path) -> bool:
    token = os.environ.get(RUN_LOCK_TOKEN_ENV, "")
    if not token:
        return False
    try:
        owner = json.loads(Path(path).read_text(encoding="utf-8"))
        int(owner["pid"])
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return False
    return owner.get("token") == token


@contextmanager
def coordinated_run_lock(
    path: str | Path,
) -> Iterator[SingleInstanceRunLock | None]:
    """Reuse a live parent bootstrap lock or acquire the lock for a direct command."""
    if _inherited_lock_is_valid(path):
        yield None
        return
    with SingleInstanceRunLock(path) as lock:
        yield lock
