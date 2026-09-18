from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import publish_pages


INITIAL_DATE = "2026-07-24"
NEW_DATE = "2026-07-25"
PAGES_BRANCH = "gh-pages"


def run_git(
    repo: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )


def report_payload(report_date: str, snapshot_type: str = "close") -> dict[str, object]:
    return {
        "schema_version": 1,
        "report_date": report_date,
        "generated_at": f"{report_date}T16:00:00",
        "snapshot_type": snapshot_type,
        "is_provisional": snapshot_type == "intraday",
        "top50": [],
    }


def serialize(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_snapshot(
    repo: Path,
    report_date: str,
    history_dates: list[str],
    snapshot_type: str = "close",
) -> None:
    """按 web_report.write_static_report 的落盘形态重建 site/。"""
    payload = serialize(report_payload(report_date, snapshot_type))
    site = repo / "site"
    (site / "assets").mkdir(parents=True, exist_ok=True)
    (site / "data/history").mkdir(parents=True, exist_ok=True)
    (site / "index.html").write_text("site shell", encoding="utf-8")
    (site / "404.html").write_text("not found", encoding="utf-8")
    (site / ".nojekyll").write_text("", encoding="utf-8")
    (site / "assets/app.css").write_text("body{}", encoding="utf-8")
    (site / "data/latest.json").write_text(payload, encoding="utf-8")
    (site / f"data/history/{report_date}.json").write_text(payload, encoding="utf-8")
    for item_date in history_dates:
        if item_date != report_date:
            (site / f"data/history/{item_date}.json").write_text(
                serialize(report_payload(item_date, "close")), encoding="utf-8"
            )
    history = [
        {"report_date": item_date, "path": f"data/history/{item_date}.json"}
        for item_date in sorted(set(history_dates) | {report_date}, reverse=True)
    ]
    write_json(site / "data/history.json", history)


@pytest.fixture
def publish_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test Publisher")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "publisher@example.test")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test Publisher")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "publisher@example.test")
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    run_git(tmp_path, "init", "--bare", str(remote))
    run_git(tmp_path, "init", "--initial-branch=main", str(repo))
    run_git(repo, "config", "user.name", "Test Publisher")
    run_git(repo, "config", "user.email", "publisher@example.test")

    (repo / "config").mkdir(parents=True, exist_ok=True)
    write_json(
        repo / "config/strategy.yml",
        {"report": {"history_days": 90}},
    )
    workflow = repo / ".github" / "workflows" / "pages.yml"
    workflow.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text("name: Deploy report to GitHub Pages\n", encoding="utf-8")
    run_git(repo, "remote", "add", "origin", str(remote))
    write_snapshot(repo, INITIAL_DATE, [INITIAL_DATE])

    monkeypatch.setattr(publish_pages, "ROOT", repo)
    monkeypatch.setattr(publish_pages, "RUN_LOCK_PATH", repo / "data" / "run_daily.lock")
    return repo, remote


def seed_pages_branch(
    repo: Path,
    remote: Path,
    history_dates: list[str],
    *,
    latest_date: str | None = None,
    snapshot_type: str = "close",
) -> None:
    """向远端预置一个已有内容的 gh-pages 分支（模拟此前发布）。"""
    work = remote.parent / "seed-pages"
    if not (work / ".git").exists():
        run_git(remote.parent, "clone", str(remote), str(work), check=False)
    if not (work / ".git").exists():
        run_git(remote.parent, "init", str(work))
        run_git(work, "remote", "add", "origin", str(remote))
    run_git(work, "checkout", "--orphan", PAGES_BRANCH, check=False)
    for item in work.iterdir():
        if item.name == ".git":
            continue
        shutil.rmtree(item) if item.is_dir() else item.unlink()
    (work / "assets").mkdir(parents=True, exist_ok=True)
    (work / "data/history").mkdir(parents=True, exist_ok=True)
    (work / "index.html").write_text("site shell", encoding="utf-8")
    (work / "assets/app.css").write_text("body{}", encoding="utf-8")
    for item_date in history_dates:
        item_type = snapshot_type if item_date == latest_date else "close"
        write_json(work / f"data/history/{item_date}.json", report_payload(item_date, item_type))
    write_json(
        work / "data/latest.json",
        report_payload(latest_date or max(history_dates), snapshot_type),
    )
    history = [
        {"report_date": item_date, "path": f"data/history/{item_date}.json"}
        for item_date in sorted(history_dates, reverse=True)
    ]
    write_json(work / "data/history.json", history)
    run_git(work, "add", "-A")
    run_git(work, "commit", "-m", "seed gh-pages")
    run_git(work, "push", "-u", "origin", PAGES_BRANCH)


def pages_branch_files(remote: Path) -> set[str]:
    listing = run_git(
        remote,
        "ls-tree",
        "-r",
        "--name-only",
        f"refs/heads/{PAGES_BRANCH}",
        check=False,
    )
    if listing.returncode != 0:
        return set()
    return {line.strip() for line in listing.stdout.splitlines() if line.strip()}


def pages_history_dates(remote: Path) -> set[str]:
    return {
        line.strip().rsplit("/", 1)[-1][: -len(".json")]
        for line in pages_branch_files(remote)
        if line.strip().startswith("data/history/") and line.strip().endswith(".json")
    }


def _ssl_connect_failure(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=list(args),
        returncode=128,
        stdout="",
        stderr=(
            "fatal: unable to access 'https://github.com/Super-YYQ/stock_selector.git/': "
            "OpenSSL SSL_connect: SSL_ERROR_SYSCALL in connection to github.com:443"
        ),
    )


def _install_flaky_git(
    monkeypatch: pytest.MonkeyPatch,
    verb: str,
    failures: int,
    failure_factory=_ssl_connect_failure,
) -> dict[str, object]:
    """让前 failures 次指定 git 子命令以网络故障应答失败，其余照常执行。

    calls["n"] 是已注入的失败次数；calls["restore"] 返回恢复真实 git 的函数。
    """
    real_git = publish_pages.git
    calls: dict[str, object] = {"n": 0}

    def flaky_git(*args: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if args and args[0] == verb and calls["n"] < failures:
            calls["n"] = calls["n"] + 1
            return failure_factory(*args)
        return real_git(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(publish_pages, "git", flaky_git)
    monkeypatch.setattr(publish_pages, "_sleep", lambda seconds: None, raising=False)
    calls["restore"] = lambda: monkeypatch.setattr(publish_pages, "git", real_git)
    return calls


# ---------- 磁盘预检 ----------


def test_publish_refuses_provisional_latest(
    publish_repo: tuple[Path, Path],
) -> None:
    """盘中临时快照不得作为正式报告发布到 Pages。"""
    repo, remote = publish_repo
    write_snapshot(repo, NEW_DATE, [NEW_DATE, INITIAL_DATE], snapshot_type="intraday")

    with pytest.raises(RuntimeError, match="盘中临时快照"):
        publish_pages.main([])

    assert pages_branch_files(remote) == set()


def test_publish_refuses_latest_history_mismatch(
    publish_repo: tuple[Path, Path],
) -> None:
    """latest.json 与同日期历史文件内容不一致时拒绝发布。"""
    repo, remote = publish_repo
    write_snapshot(repo, NEW_DATE, [NEW_DATE, INITIAL_DATE])
    write_json(
        repo / f"site/data/history/{NEW_DATE}.json",
        report_payload(NEW_DATE, "close") | {"top50": [{"code": "000001"}]},
    )

    with pytest.raises(RuntimeError, match="不一致"):
        publish_pages.main([])

    assert pages_branch_files(remote) == set()


def test_publish_refuses_history_index_missing_file(
    publish_repo: tuple[Path, Path],
) -> None:
    """索引列出的历史文件在磁盘上缺失时拒绝发布。"""
    repo, remote = publish_repo
    write_snapshot(repo, NEW_DATE, [NEW_DATE, INITIAL_DATE])
    (repo / f"site/data/history/{INITIAL_DATE}.json").unlink()

    with pytest.raises(RuntimeError, match="历史索引与磁盘文件不一致"):
        publish_pages.main([])

    assert pages_branch_files(remote) == set()


def test_publish_refuses_invalid_history_payload(
    publish_repo: tuple[Path, Path],
) -> None:
    """历史文件必须是 report_date 与文件名一致的合法 JSON。"""
    repo, remote = publish_repo
    write_snapshot(repo, NEW_DATE, [NEW_DATE, INITIAL_DATE])
    write_json(
        repo / f"site/data/history/{INITIAL_DATE}.json",
        report_payload("1999-01-01", "close"),
    )

    with pytest.raises(RuntimeError, match="与文件名日期不一致"):
        publish_pages.main([])

    assert pages_branch_files(remote) == set()


def test_publish_refuses_unexpected_site_files(
    publish_repo: tuple[Path, Path],
) -> None:
    """site/ 中出现白名单之外的文件时拒绝发布，防止误传非站点内容。"""
    repo, remote = publish_repo
    write_snapshot(repo, NEW_DATE, [NEW_DATE, INITIAL_DATE])
    (repo / "site/data/secret.db").write_text("x", encoding="utf-8")

    with pytest.raises(RuntimeError, match="不属于可发布文件"):
        publish_pages.main([])

    assert pages_branch_files(remote) == set()


# ---------- 发布与 gh-pages 同步 ----------


def test_first_publish_creates_pages_branch_with_site_content(
    publish_repo: tuple[Path, Path],
) -> None:
    """远端没有 gh-pages 分支时首次发布应创建并推送完整站点内容。"""
    repo, remote = publish_repo
    write_snapshot(repo, NEW_DATE, [NEW_DATE, INITIAL_DATE])

    assert publish_pages.main([]) == 0

    assert pages_branch_files(remote) == {
        ".nojekyll",
        ".github/workflows/pages.yml",
        "404.html",
        "index.html",
        "assets/app.css",
        "data/latest.json",
        "data/history.json",
        f"data/history/{NEW_DATE}.json",
        f"data/history/{INITIAL_DATE}.json",
    }
    published = run_git(
        remote, "show", f"refs/heads/{PAGES_BRANCH}:data/latest.json"
    ).stdout
    assert json.loads(published)["report_date"] == NEW_DATE


def test_publish_updates_latest_and_appends_history(
    publish_repo: tuple[Path, Path],
) -> None:
    """第二次发布更新 latest 并追加新历史，旧历史保留。"""
    repo, remote = publish_repo
    write_snapshot(repo, INITIAL_DATE, [INITIAL_DATE])
    assert publish_pages.main([]) == 0

    write_snapshot(repo, NEW_DATE, [NEW_DATE, INITIAL_DATE])
    assert publish_pages.main([]) == 0

    assert pages_history_dates(remote) == {INITIAL_DATE, NEW_DATE}
    published = run_git(
        remote, "show", f"refs/heads/{PAGES_BRANCH}:data/latest.json"
    ).stdout
    assert json.loads(published)["report_date"] == NEW_DATE


def test_publish_no_changes_skips_push(
    publish_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """内容没有变化时不产生新提交也不推送。"""
    repo, remote = publish_repo
    write_snapshot(repo, NEW_DATE, [NEW_DATE, INITIAL_DATE])
    assert publish_pages.main([]) == 0
    head_before = run_git(remote, "rev-parse", f"refs/heads/{PAGES_BRANCH}").stdout.strip()

    assert publish_pages.main([]) == 0
    assert "没有变化" in capsys.readouterr().out
    head_after = run_git(remote, "rev-parse", f"refs/heads/{PAGES_BRANCH}").stdout.strip()
    assert head_after == head_before


# ---------- 历史回填与保留 ----------


def test_publish_backfills_history_missing_locally_from_pages_branch(
    publish_repo: tuple[Path, Path],
) -> None:
    """本地 site/ 只剩最新一天时（如换机重装），gh-pages 上的历史被回填并继续保留。"""
    repo, remote = publish_repo
    old_dates = ["2026-07-10", "2026-07-15", "2026-07-20"]
    seed_pages_branch(repo, remote, [*old_dates, INITIAL_DATE], latest_date=INITIAL_DATE)

    # 本地重装后只剩今天刚生成的报告
    write_snapshot(repo, NEW_DATE, [NEW_DATE])

    assert publish_pages.main([]) == 0

    assert pages_history_dates(remote) == {*old_dates, INITIAL_DATE, NEW_DATE}
    # 回填发生在发布前：本地索引也已包含回填日期
    local_index = json.loads(
        (repo / "site/data/history.json").read_text(encoding="utf-8")
    )
    assert {item["report_date"] for item in local_index} == {
        *old_dates,
        INITIAL_DATE,
        NEW_DATE,
    }


def test_publish_applies_retention_deletions(
    publish_repo: tuple[Path, Path],
) -> None:
    """超过保留期的历史从 gh-pages 删除，保留期内缺失的本地文件被回填。"""
    repo, remote = publish_repo
    write_json(repo / "config/strategy.yml", {"report": {"history_days": 3}})
    dates = ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04", INITIAL_DATE]
    seed_pages_branch(repo, remote, dates, latest_date=INITIAL_DATE)

    write_snapshot(repo, NEW_DATE, [NEW_DATE])

    assert publish_pages.main([]) == 0

    # 保留最近 3 天：NEW_DATE、INITIAL_DATE、2026-07-04；更早的删除
    assert pages_history_dates(remote) == {"2026-07-04", INITIAL_DATE, NEW_DATE}


# ---------- 历史不可变 ----------


def test_publish_tolerates_line_ending_only_differences(
    publish_repo: tuple[Path, Path],
) -> None:
    """本地历史与 gh-pages 只差行尾（CRLF/LF 混杂）时应放行，不算改写历史。

    真实场景：旧报告由不同写入机制生成 CRLF，git add 的 clean filter 又把
    blob 规范化为 LF，字节比对会把未改动的文件误判为已修改。
    """
    repo, remote = publish_repo
    seed_pages_branch(repo, remote, [INITIAL_DATE], latest_date=INITIAL_DATE)

    write_snapshot(repo, NEW_DATE, [NEW_DATE, INITIAL_DATE])
    # 把本地 INITIAL_DATE 历史改写为 LF（read_text 归一化后按原样写出），
    # gh-pages 上是 CRLF —— 内容相同、仅行尾不同
    rel = f"site/data/history/{INITIAL_DATE}.json"
    content = (repo / rel).read_text(encoding="utf-8")
    (repo / rel).write_text(content, encoding="utf-8", newline="")

    assert publish_pages.main([]) == 0

    assert pages_history_dates(remote) == {INITIAL_DATE, NEW_DATE}


def test_publish_refuses_modified_past_history(
    publish_repo: tuple[Path, Path],
) -> None:
    """早于最新报告日的历史内容与 gh-pages 不一致时拒绝覆盖。"""
    repo, remote = publish_repo
    seed_pages_branch(repo, remote, [INITIAL_DATE, "2026-07-20"], latest_date=INITIAL_DATE)

    write_snapshot(repo, NEW_DATE, [NEW_DATE, INITIAL_DATE, "2026-07-20"])
    write_json(
        repo / "site/data/history/2026-07-20.json",
        report_payload("2026-07-20", "close") | {"top50": [{"code": "000001"}]},
    )

    with pytest.raises(RuntimeError, match="已发布历史报告内容不一致"):
        publish_pages.main([])

    assert pages_history_dates(remote) == {INITIAL_DATE, "2026-07-20"}


def test_publish_allows_intraday_to_close_upgrade_for_latest_date(
    publish_repo: tuple[Path, Path],
) -> None:
    """同一天 gh-pages 上是盘中快照、本地已是收盘正式报告时允许升级覆盖。"""
    repo, remote = publish_repo
    seed_pages_branch(
        repo,
        remote,
        [INITIAL_DATE],
        latest_date=INITIAL_DATE,
        snapshot_type="intraday",
    )

    write_snapshot(repo, INITIAL_DATE, [INITIAL_DATE], snapshot_type="close")

    assert publish_pages.main([]) == 0

    published = run_git(
        remote, "show", f"refs/heads/{PAGES_BRANCH}:data/latest.json"
    ).stdout
    payload = json.loads(published)
    assert payload["report_date"] == INITIAL_DATE
    assert payload["snapshot_type"] == "close"


def test_publish_refuses_reissued_close_for_published_date(
    publish_repo: tuple[Path, Path],
) -> None:
    """已发布的收盘报告被本地重跑改写后不得静默覆盖线上历史。"""
    repo, remote = publish_repo
    seed_pages_branch(repo, remote, [INITIAL_DATE], latest_date=INITIAL_DATE)

    reissued = serialize(report_payload(INITIAL_DATE, "close") | {"top50": [{"code": "000001"}]})
    write_snapshot(repo, INITIAL_DATE, [INITIAL_DATE])
    (repo / f"site/data/history/{INITIAL_DATE}.json").write_text(reissued, encoding="utf-8")
    (repo / "site/data/latest.json").write_text(reissued, encoding="utf-8")

    with pytest.raises(RuntimeError, match="已发布历史报告内容不一致"):
        publish_pages.main([])


# ---------- 网络故障 ----------


def test_push_retries_transient_network_failure(
    publish_repo: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """push 遇到 SSL 瞬时失败应重试并成功。"""
    repo, remote = publish_repo
    write_snapshot(repo, NEW_DATE, [NEW_DATE, INITIAL_DATE])
    calls = _install_flaky_git(monkeypatch, "push", failures=1)

    assert publish_pages.main([]) == 0

    assert calls["n"] == 1
    assert json.loads(
        run_git(remote, "show", f"refs/heads/{PAGES_BRANCH}:data/latest.json").stdout
    )["report_date"] == NEW_DATE


def test_publish_recovers_after_permanent_push_failure_on_next_run(
    publish_repo: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """推送彻底失败后无需人工清理，下一次发布自然重试成功。"""
    repo, remote = publish_repo
    write_snapshot(repo, NEW_DATE, [NEW_DATE, INITIAL_DATE])
    auth_failure = lambda *args: subprocess.CompletedProcess(
        args=list(args),
        returncode=128,
        stdout="",
        stderr="fatal: Authentication failed for 'https://github.com/Super-YYQ/stock_selector.git/'",
    )
    calls = _install_flaky_git(
        monkeypatch, "push", failures=1, failure_factory=auth_failure
    )

    with pytest.raises(RuntimeError, match="GitHub 推送失败"):
        publish_pages.main([])

    calls["restore"]()
    assert publish_pages.main([]) == 0
    assert json.loads(
        run_git(remote, "show", f"refs/heads/{PAGES_BRANCH}:data/latest.json").stdout
    )["report_date"] == NEW_DATE


def test_dry_run_publishes_nothing(
    publish_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """dry-run 只做检查并列出将发布的文件，不创建分支不推送。"""
    repo, remote = publish_repo
    write_snapshot(repo, NEW_DATE, [NEW_DATE, INITIAL_DATE])

    assert publish_pages.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert NEW_DATE in out

    assert pages_branch_files(remote) == set()
