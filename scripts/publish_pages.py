from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.run_lock import coordinated_run_lock


RUN_LOCK_PATH = ROOT / "data" / "run_daily.lock"
PUBLISH_TRAILER = "Stock-Selector-Publish: v1"
REPORT_PATHS = ("site/data/latest.json", "site/data/history.json")
HISTORY_PATH_RE = re.compile(r"^site/data/history/(\d{4}-\d{2}-\d{2})\.json$")
REMOTE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
REPORT_INPUT_PATHS = (
    "src",
    "config",
    "scripts",
    "web",
    "run_daily.py",
    "requirements.txt",
)


@dataclass(frozen=True)
class ReportSnapshot:
    report_date: str
    managed_paths: tuple[str, ...]


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=check,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="安全发布最新静态盘后报告到 GitHub Pages")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def _git_error(prefix: str, result: subprocess.CompletedProcess[str]) -> RuntimeError:
    detail = (result.stderr or result.stdout).strip()
    return RuntimeError(f"{prefix}: {detail}" if detail else prefix)


def _validate_ref_arguments(remote: str, branch: str) -> None:
    if not REMOTE_NAME_RE.fullmatch(remote):
        raise RuntimeError(f"远端名称不合法: {remote}")
    checked = git("check-ref-format", "--branch", branch, check=False)
    if checked.returncode != 0:
        raise RuntimeError(f"目标分支名称不合法: {branch}")


def _is_ancestor(older: str, newer: str) -> bool:
    result = git("merge-base", "--is-ancestor", older, newer, check=False)
    if result.returncode not in {0, 1}:
        raise _git_error("无法校验 Git 提交关系", result)
    return result.returncode == 0


def _is_managed_report_path(path: str) -> bool:
    return path in REPORT_PATHS or HISTORY_PATH_RE.fullmatch(path) is not None


def _validate_publish_commit(commit_sha: str) -> None:
    parents = git("rev-list", "--parents", "-n", "1", commit_sha).stdout.split()
    if len(parents) != 2:
        raise RuntimeError(f"待推送提交 {commit_sha[:10]} 不是单父提交，已停止自动发布")

    message = git("show", "-s", "--format=%B", commit_sha).stdout.splitlines()
    if PUBLISH_TRAILER not in {line.strip() for line in message}:
        raise RuntimeError(
            f"本地分支包含非发布提交 {commit_sha[:10]}，请通过正常 PR 流程推送"
        )

    paths = [
        line.strip()
        for line in git(
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            commit_sha,
        ).stdout.splitlines()
        if line.strip()
    ]
    if not paths or any(not _is_managed_report_path(path) for path in paths):
        raise RuntimeError(
            f"待推送提交 {commit_sha[:10]} 含有非报告文件，已停止自动发布"
        )


def _validate_pending_commits(remote_sha: str, local_sha: str) -> list[str]:
    commits = [
        line.strip()
        for line in git("rev-list", "--reverse", f"{remote_sha}..{local_sha}").stdout.splitlines()
        if line.strip()
    ]
    if not commits:
        raise RuntimeError("无法识别本地领先提交，已停止自动发布")
    for commit_sha in commits:
        _validate_publish_commit(commit_sha)
    return commits


def _fetch_target(remote: str, branch: str) -> str:
    remotes = {line.strip() for line in git("remote").stdout.splitlines() if line.strip()}
    if remote not in remotes:
        raise RuntimeError(f"Git 远端 {remote!r} 不存在，已停止发布")
    remote_url = git("remote", "get-url", remote, check=False)
    if remote_url.returncode != 0 or not remote_url.stdout.strip():
        raise _git_error(f"无法读取 Git 远端 {remote!r}", remote_url)

    remote_ref = f"refs/remotes/{remote}/{branch}"
    refspec = f"+refs/heads/{branch}:{remote_ref}"
    fetched = git("fetch", "--no-tags", remote, refspec, check=False)
    if fetched.returncode != 0:
        raise _git_error(f"无法更新 {remote}/{branch}，未创建发布提交", fetched)
    resolved = git("rev-parse", "--verify", remote_ref, check=False)
    if resolved.returncode != 0:
        raise RuntimeError(f"远端分支 {remote}/{branch} 不存在，已停止发布")
    return resolved.stdout.strip()


def _push_branch(remote: str, branch: str, commit_sha: str) -> None:
    if not _is_ancestor(
        git("rev-parse", "--verify", f"refs/remotes/{remote}/{branch}").stdout.strip(),
        commit_sha,
    ):
        raise RuntimeError("发布提交无法快进目标远端分支，已停止推送")
    pushed = git(
        "push",
        remote,
        f"{commit_sha}:refs/heads/{branch}",
        check=False,
    )
    if pushed.returncode != 0:
        raise _git_error(
            f"GitHub 推送失败；发布提交 {commit_sha[:10]} 已保留，下次会先重试",
            pushed,
        )


def _ensure_report_inputs_clean() -> None:
    dirty = git(
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        *REPORT_INPUT_PATHS,
    )
    if dirty.stdout.strip():
        paths = [
            line[3:].strip()
            for line in dirty.stdout.splitlines()
            if len(line) >= 4
        ]
        detail = "、".join(paths[:8])
        if len(paths) > 8:
            detail += f" 等 {len(paths)} 项"
        raise RuntimeError(
            "报告输入源码或配置存在未提交修改，已停止自动发布；"
            f"请先通过正常 PR/提交确认这些变更：{detail}"
        )


def _prepare_branch(remote: str, branch: str, *, dry_run: bool) -> bool:
    if not (ROOT / ".git").exists():
        raise RuntimeError("当前目录不是 Git 仓库，无法自动发布")
    inside = git("rev-parse", "--is-inside-work-tree", check=False)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        raise RuntimeError("当前目录不是 Git 工作区，无法自动发布")

    _validate_ref_arguments(remote, branch)
    current = git("symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if current.returncode != 0:
        raise RuntimeError("当前处于 detached HEAD，已停止自动发布")
    current_branch = current.stdout.strip()
    if current_branch != branch:
        raise RuntimeError(
            f"当前分支是 {current_branch!r}，自动发布只允许从 {branch!r} 分支执行"
        )

    _ensure_report_inputs_clean()
    remote_sha = _fetch_target(remote, branch)
    local_sha = git("rev-parse", "--verify", "HEAD").stdout.strip()
    if local_sha == remote_sha:
        return False

    if _is_ancestor(remote_sha, local_sha):
        commits = _validate_pending_commits(remote_sha, local_sha)
        if dry_run:
            print(
                f"检测到 {len(commits)} 个待推送发布提交；dry-run 不会执行推送："
                f" {local_sha[:10]}"
            )
            return True
        _push_branch(remote, branch, local_sha)
        print(f"已重试并推送待发布提交 {local_sha[:10]}")
        return False

    if _is_ancestor(local_sha, remote_sha):
        raise RuntimeError(
            f"本地 {branch} 落后于 {remote}/{branch}，请先执行 git pull --ff-only "
            "并重新生成报告"
        )
    raise RuntimeError(
        f"本地 {branch} 与 {remote}/{branch} 已分叉，不能安全快进；"
        "请先人工处理分支差异"
    )


def _read_json(path: Path, description: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"{description}不存在: {path.relative_to(ROOT).as_posix()}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{description}不是有效 JSON: {exc}") from exc


def _validate_report_date(value: object, description: str) -> str:
    if not isinstance(value, str):
        raise RuntimeError(f"{description}缺少合法的 report_date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise RuntimeError(f"{description}的 report_date 格式错误: {value!r}") from exc
    if parsed.isoformat() != value:
        raise RuntimeError(f"{description}的 report_date 格式错误: {value!r}")
    return value


def _is_tracked(path: str) -> bool:
    return git("ls-files", "--error-unmatch", "--", path, check=False).returncode == 0


def _is_dirty_against_head(path: str) -> bool:
    return git("diff", "--quiet", "HEAD", "--", path, check=False).returncode != 0


def _load_report_snapshot() -> ReportSnapshot:
    latest_path = ROOT / REPORT_PATHS[0]
    latest = _read_json(latest_path, "site/data/latest.json ")
    if not isinstance(latest, dict):
        raise RuntimeError("site/data/latest.json 顶层必须是 JSON 对象")
    report_date = _validate_report_date(latest.get("report_date"), "静态报告")

    history_index_path = ROOT / REPORT_PATHS[1]
    history_index = _read_json(history_index_path, "site/data/history.json ")
    if not isinstance(history_index, list):
        raise RuntimeError("site/data/history.json 顶层必须是 JSON 数组")

    listed_paths: list[str] = []
    listed_dates: list[str] = []
    for item in history_index:
        if not isinstance(item, dict):
            raise RuntimeError("历史报告索引包含非对象条目，已停止发布")
        item_date = _validate_report_date(item.get("report_date"), "历史报告索引")
        expected_relative = f"data/history/{item_date}.json"
        if item.get("path") != expected_relative:
            raise RuntimeError(f"历史报告路径不合法: {item.get('path')!r}")
        repository_path = f"site/{expected_relative}"
        if repository_path in listed_paths:
            raise RuntimeError(f"历史报告索引包含重复日期: {item_date}")

        payload_path = ROOT / repository_path
        payload = _read_json(payload_path, f"历史报告 {item_date} ")
        if not isinstance(payload, dict):
            raise RuntimeError(f"历史报告 {item_date} 顶层必须是 JSON 对象")
        if _validate_report_date(payload.get("report_date"), f"历史报告 {item_date}") != item_date:
            raise RuntimeError(f"历史报告文件名与 report_date 不一致: {repository_path}")

        listed_paths.append(repository_path)
        listed_dates.append(item_date)

    if listed_dates != sorted(listed_dates, reverse=True):
        raise RuntimeError("历史报告索引未按日期倒序排列，已停止发布")

    current_history = f"site/data/history/{report_date}.json"
    if current_history not in listed_paths:
        raise RuntimeError("历史报告索引未包含最新报告日期，已停止发布")
    if latest_path.read_bytes() != (ROOT / current_history).read_bytes():
        raise RuntimeError("latest.json 与同日期历史报告内容不一致，已停止发布")

    for path in listed_paths:
        if path == current_history:
            continue
        if not _is_tracked(path):
            raise RuntimeError(f"历史索引包含非本次生成的未跟踪文件: {path}")
        if _is_dirty_against_head(path):
            raise RuntimeError(f"既有历史报告存在额外修改，未纳入自动发布: {path}")

    tracked_history = {
        line.strip()
        for line in git("ls-files", "--", "site/data/history").stdout.splitlines()
        if HISTORY_PATH_RE.fullmatch(line.strip())
    }
    intended_history = set(listed_paths)
    stale_history = sorted(tracked_history - intended_history)
    for path in stale_history:
        if (ROOT / path).exists():
            raise RuntimeError(f"历史索引与磁盘文件不一致，未自动删除: {path}")

    managed = (*REPORT_PATHS, current_history, *stale_history)
    return ReportSnapshot(report_date=report_date, managed_paths=tuple(dict.fromkeys(managed)))


def _has_worktree_changes(paths: Sequence[str]) -> bool:
    for path in paths:
        target = ROOT / path
        if not _is_tracked(path):
            if target.exists():
                return True
            continue
        if _is_dirty_against_head(path):
            return True
    return False


def _ensure_managed_index_clean(paths: Sequence[str]) -> None:
    staged = git("diff", "--cached", "--name-only", "--", *paths).stdout.splitlines()
    if any(line.strip() for line in staged):
        raise RuntimeError("待发布报告文件已有暂存修改，请先处理暂存区后再发布")


def _commit_report(snapshot: ReportSnapshot, branch: str) -> str:
    _ensure_managed_index_clean(snapshot.managed_paths)
    added = git("add", "-A", "--", *snapshot.managed_paths, check=False)
    if added.returncode != 0:
        raise _git_error("无法暂存生成的报告文件", added)

    message = f"chore(report): publish {snapshot.report_date}"
    committed = git(
        "commit",
        "--only",
        "-m",
        message,
        "-m",
        PUBLISH_TRAILER,
        "--",
        *snapshot.managed_paths,
        check=False,
    )
    if committed.returncode != 0:
        git("reset", "--quiet", "HEAD", "--", *snapshot.managed_paths, check=False)
        raise _git_error("Git 提交失败", committed)

    commit_sha = git("rev-parse", "--verify", f"refs/heads/{branch}").stdout.strip()
    _validate_publish_commit(commit_sha)
    return commit_sha


def _main_unlocked(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    pending_only = _prepare_branch(args.remote, args.branch, dry_run=args.dry_run)
    if pending_only:
        return 0

    snapshot = _load_report_snapshot()
    if not _has_worktree_changes(snapshot.managed_paths):
        print("网页报告没有变化，无需发布")
        return 0

    if args.dry_run:
        print(
            f"dry-run：将发布 {snapshot.report_date}，仅包含以下生成文件：\n"
            + "\n".join(f"- {path}" for path in snapshot.managed_paths)
        )
        return 0

    commit_sha = _commit_report(snapshot, args.branch)
    remote_sha = _fetch_target(args.remote, args.branch)
    if not _is_ancestor(remote_sha, commit_sha):
        raise RuntimeError(
            f"{args.remote}/{args.branch} 在发布期间发生变化；"
            f"发布提交 {commit_sha[:10]} 已保留，未执行非快进推送"
        )
    _push_branch(args.remote, args.branch, commit_sha)
    print(
        f"已发布 {snapshot.report_date} 网页报告到 {args.remote}/{args.branch} "
        f"({commit_sha[:10]})"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    with coordinated_run_lock(RUN_LOCK_PATH):
        return _main_unlocked(argv)


if __name__ == "__main__":
    raise SystemExit(main())
