from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.run_lock import coordinated_run_lock
from src.atomic_io import atomic_write_text


RUN_LOCK_PATH = ROOT / "data" / "run_daily.lock"
PUBLISH_TRAILER = "Stock-Selector-Publish: v1"
SITE_DIR = "site"
LATEST_PATH = "site/data/latest.json"
HISTORY_INDEX_PATH = "site/data/history.json"
HISTORY_PATH_RE = re.compile(r"^site/data/history/(\d{4}-\d{2}-\d{2})\.json$")
ASSET_PATH_RE = re.compile(r"^site/assets/[^/]+$")
SITE_TEMPLATE_PATHS = frozenset({"site/index.html", "site/404.html", "site/.nojekyll"})
ALLOWED_SITE_DIRS = frozenset({"site/assets", "site/data", "site/data/history"})
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
REMOTE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
BRANCH_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


@dataclass(frozen=True)
class ReportSnapshot:
    report_date: str
    history_dates: tuple[str, ...]


_sleep = time.sleep

# 访问 GitHub 的 ls-remote/clone/push 常被瞬时网络故障打断（2026-09-02/03/18
# 各丢过一次发布），因此对可识别的瞬时错误做有限重试；认证失败等确定性错误不重试。
_TRANSIENT_NET_ERROR_RE = re.compile(
    r"SSL_ERROR_SYSCALL|SSL_connect|GnuTLS|Failed to connect|"
    r"Connection (?:reset|refused|aborted|closed)|Could not resolve host|"
    r"Recv failure|Empty reply from server|timed? ?out|"
    r"RPC failed|remote end hung up|early EOF|invalid index-pack output",
    re.IGNORECASE,
)
_NET_RETRY_DELAYS = (5, 10)


def git(
    *args: str,
    check: bool = True,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd or ROOT,
        check=check,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )


def _git_network(
    *args: str,
    check: bool = True,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """执行会访问网络的 git 命令，对瞬时网络故障有限重试。"""
    result = git(*args, check=check, cwd=cwd)
    for attempt, delay in enumerate(_NET_RETRY_DELAYS, start=2):
        if result.returncode == 0:
            return result
        stderr = result.stderr or ""
        if not _TRANSIENT_NET_ERROR_RE.search(stderr):
            return result
        verb = args[0] if args else "git"
        detail = stderr.strip().splitlines()[-1] if stderr.strip() else "未知网络错误"
        print(f"git {verb} 疑似瞬时网络故障，{delay} 秒后第 {attempt} 次尝试：{detail}")
        _sleep(delay)
        result = git(*args, check=check, cwd=cwd)
    return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="安全发布最新静态盘后报告到 GitHub Pages")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="gh-pages")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def _git_error(prefix: str, result: subprocess.CompletedProcess[str]) -> RuntimeError:
    detail = (result.stderr or result.stdout).strip()
    return RuntimeError(f"{prefix}: {detail}" if detail else prefix)


def _history_days() -> int:
    from src.config import load_config

    return load_config(ROOT / "config").report.history_days


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_allowed_site_path(relative: str) -> bool:
    if relative in SITE_TEMPLATE_PATHS:
        return True
    if relative == LATEST_PATH or relative == HISTORY_INDEX_PATH:
        return True
    if HISTORY_PATH_RE.fullmatch(relative) is not None:
        return True
    return ASSET_PATH_RE.fullmatch(relative) is not None


def _validate_report_inputs() -> ReportSnapshot:
    """发布前对 site/ 做纯磁盘校验：正式报告、索引一致、文件白名单。

    历史不可变（与 gh-pages 的对比）在克隆远端后另行校验。
    """
    site = ROOT / SITE_DIR
    if not site.is_dir():
        raise RuntimeError("site/ 目录不存在，无法发布")

    latest_path = ROOT / LATEST_PATH
    if not latest_path.exists():
        raise RuntimeError("缺少 site/data/latest.json，无法发布")
    latest = _read_json(latest_path)
    if not isinstance(latest, dict):
        raise RuntimeError("latest.json 不是 JSON 对象，无法发布")
    if latest.get("is_provisional") is True or latest.get("snapshot_type") == "intraday":
        raise RuntimeError("latest.json 为盘中临时快照，不作为正式报告发布")
    report_date = str(latest.get("report_date") or "")
    if DATE_RE.fullmatch(report_date) is None:
        raise RuntimeError(f"latest.json 的 report_date 非法: {report_date!r}")

    same_day_history = ROOT / f"site/data/history/{report_date}.json"
    if not same_day_history.exists():
        raise RuntimeError(f"缺少当日历史报告 {same_day_history}，无法发布")
    if latest_path.read_bytes() != same_day_history.read_bytes():
        raise RuntimeError("latest.json 与同日期历史报告内容不一致，已停止发布")

    index_path = ROOT / HISTORY_INDEX_PATH
    index = _read_json(index_path)
    if not isinstance(index, list):
        raise RuntimeError("site/data/history.json 不是列表，无法发布")
    for item in index:
        if not isinstance(item, dict):
            raise RuntimeError("history.json 条目不是对象，无法发布")
        item_date = str(item.get("report_date") or "")
        item_path = str(item.get("path") or "")
        if DATE_RE.fullmatch(item_date) is None or item_path != f"data/history/{item_date}.json":
            raise RuntimeError(f"history.json 条目非法: {item}")
        if not (ROOT / "site" / item_path).exists():
            raise RuntimeError("历史索引与磁盘文件不一致，未找到 " + item_path)

    history_dir = ROOT / "site/data/history"
    disk_dates: list[str] = []
    for item in sorted(history_dir.glob("*.json")):
        payload = _read_json(item)
        if not isinstance(payload, dict) or str(payload.get("report_date")) != item.stem:
            raise RuntimeError(f"历史报告 {item.name} 的 report_date 与文件名日期不一致")
        disk_dates.append(item.stem)

    for dirpath, _dirnames, filenames in site.walk():
        for name in filenames:
            relative = (dirpath / name).relative_to(ROOT).as_posix()
            if not _is_allowed_site_path(relative):
                raise RuntimeError(f"{relative} 不属于可发布文件，已停止发布")

    return ReportSnapshot(
        report_date=report_date,
        history_dates=tuple(sorted(disk_dates, reverse=True)),
    )


def _remote_url(remote: str) -> str:
    remotes = {line.strip() for line in git("remote").stdout.splitlines() if line.strip()}
    if remote not in remotes:
        raise RuntimeError(f"Git 远端 {remote!r} 不存在，已停止发布")
    resolved = git("remote", "get-url", remote, check=False)
    if resolved.returncode != 0 or not resolved.stdout.strip():
        raise _git_error(f"无法读取 Git 远端 {remote!r}", resolved)
    return resolved.stdout.strip()


def _pages_branch_exists(remote_url: str, branch: str) -> bool:
    listing = _git_network(
        "ls-remote", "--heads", remote_url, f"refs/heads/{branch}", check=False
    )
    if listing.returncode != 0:
        raise _git_error(f"无法查询远端分支 {branch}", listing)
    return listing.stdout.strip() != ""


def _prepare_pages_worktree(remote_url: str, branch: str, workdir: Path) -> None:
    """把远端 gh-pages 分支检出到临时目录；分支不存在时初始化为孤儿分支。"""
    if _pages_branch_exists(remote_url, branch):
        cloned = _git_network(
            "-c", "core.autocrlf=false",
            "clone", "--single-branch", "--branch", branch, remote_url, str(workdir),
            check=False,
        )
        if cloned.returncode != 0:
            raise _git_error(f"无法克隆远端分支 {branch}", cloned)
        return
    initialized = git("init", "--quiet", str(workdir), check=False)
    if initialized.returncode != 0:
        raise _git_error("无法初始化发布临时目录", initialized)
    git_dir = workdir / ".git"
    git("--git-dir", str(git_dir), "symbolic-ref", "HEAD", f"refs/heads/{branch}")
    added = git(
        "--git-dir", str(git_dir), "remote", "add", "origin", remote_url, check=False
    )
    if added.returncode != 0:
        raise _git_error("无法为发布临时目录配置远端", added)


def _sync_site_to_pages(workdir: Path) -> None:
    """用本地 site/ 完整替换发布工作区的已检出内容（保留 .git）。

    同时带入 Pages 部署工作流：Actions 的 push 触发要求工作流文件存在于
    被推送的分支上，孤儿分支不会继承 main 的 .github。
    """
    for item in workdir.iterdir():
        if item.name == ".git":
            continue
        shutil.rmtree(item) if item.is_dir() else item.unlink()
    shutil.copytree(ROOT / SITE_DIR, workdir, dirs_exist_ok=True)
    workflow = ROOT / ".github" / "workflows" / "pages.yml"
    if workflow.is_file():
        target = workdir / ".github" / "workflows" / "pages.yml"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(workflow, target)


def _backfill_and_prune_history(workdir: Path, history_days: int) -> None:
    """以 gh-pages 为历史持久层：回填本地缺失的保留期文件，删除超期文件。

    保留集合 = gh-pages 日期 ∪ 本地日期 中最新的 history_days 个。换机重装后
    本地只剩当天文件时，历史从 gh-pages 回填，而不是把线上历史清空。
    """
    local_dir = ROOT / "site/data/history"
    pages_dir = workdir / "data/history"
    local_dates = {item.stem for item in local_dir.glob("*.json")}
    pages_dates = {item.stem for item in pages_dir.glob("*.json")} if pages_dir.is_dir() else set()
    retained = set(sorted(local_dates | pages_dates, reverse=True)[: max(1, history_days)])

    for item_date in sorted(retained - local_dates):
        source = pages_dir / f"{item_date}.json"
        if source.exists():
            shutil.copyfile(source, local_dir / source.name)

    for item in local_dir.glob("*.json"):
        if item.stem not in retained:
            item.unlink()

    history = [
        {"report_date": item.stem, "path": f"data/history/{item.name}"}
        for item in sorted(local_dir.glob("*.json"), reverse=True)
    ]
    atomic_write_text(
        ROOT / HISTORY_INDEX_PATH, json.dumps(history, ensure_ascii=False, indent=2)
    )


def _same_report_content(left: bytes, right: bytes) -> bool:
    """比较报告内容，行尾差异（CRLF/LF 混杂）不算改写。

    历史文件由不同时期的写入机制生成，行尾并不统一；git 的 autocrlf 也会在
    检出时转换行尾。字节级比较会把未改动的文件误判为已修改。
    """
    return left == right or left.replace(b"\r\n", b"\n") == right.replace(b"\r\n", b"\n")


def _validate_history_immutability(workdir: Path, latest_date: str) -> None:
    """已发布历史不得被静默改写；当日盘中快照升级为收盘正式报告除外。"""
    local_dir = ROOT / "site/data/history"
    pages_dir = workdir / "data/history"
    if not pages_dir.is_dir():
        return
    for item in sorted(pages_dir.glob("*.json")):
        local_file = local_dir / item.name
        if not local_file.exists():
            continue  # 超过保留期已被清剪，或本地从未有过
        if _same_report_content(local_file.read_bytes(), item.read_bytes()):
            continue
        if item.stem == latest_date:
            pages_payload = _read_json(item)
            local_payload = _read_json(local_file)
            pages_is_intraday = (
                isinstance(pages_payload, dict)
                and pages_payload.get("snapshot_type") == "intraday"
            )
            local_is_close = (
                isinstance(local_payload, dict)
                and local_payload.get("snapshot_type") == "close"
                and local_payload.get("is_provisional") is not True
            )
            if pages_is_intraday and local_is_close:
                continue  # 当日盘中快照 → 收盘正式报告的升级
        raise RuntimeError(
            f"已发布历史报告内容不一致: data/history/{item.name}，"
            "如确需修正请手动处理 gh-pages 分支"
        )


def _commit_and_push(workdir: Path, branch: str, report_date: str) -> None:
    git("add", "-A", cwd=workdir)
    # 变化检测必须基于暂存区内容：本机系统级 autocrlf=true 会让 CRLF/LF 行尾
    # 差异在 `git status` 里表现为幽灵修改（diff 为空、add 后无可提交内容），
    # 直接信任 porcelain 会误入提交流程并报 "nothing to commit"。
    has_head = (
        git("rev-parse", "--verify", "--quiet", "HEAD", cwd=workdir, check=False).returncode == 0
    )
    if has_head:
        staged = git("diff", "--cached", "--name-only", "HEAD", cwd=workdir)
        if not staged.stdout.strip():
            print("网页报告没有变化，无需发布")
            return
    message = f"chore(report): publish {report_date}"
    committed = git(
        "commit", "-m", message, "-m", PUBLISH_TRAILER, cwd=workdir, check=False
    )
    if committed.returncode != 0:
        raise _git_error("Git 提交失败", committed)
    pushed = _git_network(
        "push", "origin", f"HEAD:refs/heads/{branch}", cwd=workdir, check=False
    )
    if pushed.returncode != 0:
        raise _git_error("GitHub 推送失败；发布内容未丢失，下次运行会重试", pushed)
    print(f"已发布 {report_date} 网页报告到 gh-pages 分支")


def _main_unlocked(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not REMOTE_NAME_RE.fullmatch(args.remote):
        raise RuntimeError(f"远端名称不合法: {args.remote}")
    if not BRANCH_NAME_RE.fullmatch(args.branch):
        raise RuntimeError(f"目标分支名称不合法: {args.branch}")

    snapshot = _validate_report_inputs()
    if args.dry_run:
        print(
            f"dry-run：将发布 {snapshot.report_date}，仅包含 site/ 下的生成文件；"
            "不会克隆或推送远端"
        )
        return 0

    remote_url = _remote_url(args.remote)
    with tempfile.TemporaryDirectory(prefix="publish-pages-") as tmp:
        workdir = Path(tmp) / "pages"
        _prepare_pages_worktree(remote_url, args.branch, workdir)
        _backfill_and_prune_history(workdir, _history_days())
        _validate_history_immutability(workdir, snapshot.report_date)
        _sync_site_to_pages(workdir)
        _commit_and_push(workdir, args.branch, snapshot.report_date)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    with coordinated_run_lock(RUN_LOCK_PATH):
        return _main_unlocked(argv)


if __name__ == "__main__":
    raise SystemExit(main())
