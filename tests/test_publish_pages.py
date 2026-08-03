from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts import publish_pages


INITIAL_DATE = "2026-07-24"
NEW_DATE = "2026-07-25"


def run_git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )


def report_payload(report_date: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "report_date": report_date,
        "generated_at": f"{report_date}T16:00:00",
        "top50": [],
    }


def report_payload_with_snapshot(
    report_date: str,
    snapshot_type: str,
    is_provisional: bool,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "report_date": report_date,
        "generated_at": f"{report_date}T16:00:00",
        "snapshot_type": snapshot_type,
        "is_provisional": is_provisional,
        "top50": [],
    }


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_snapshot(repo: Path, report_date: str, history_dates: list[str]) -> None:
    payload = report_payload(report_date)
    write_json(repo / "site/data/latest.json", payload)
    write_json(repo / f"site/data/history/{report_date}.json", payload)
    write_json(
        repo / "site/data/history.json",
        [
            {
                "report_date": item_date,
                "path": f"data/history/{item_date}.json",
            }
            for item_date in history_dates
        ],
    )


@pytest.fixture
def publish_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    run_git(tmp_path, "init", "--bare", str(remote))
    run_git(tmp_path, "init", "--initial-branch=main", str(repo))
    run_git(repo, "config", "user.name", "Test Publisher")
    run_git(repo, "config", "user.email", "publisher@example.test")

    (repo / "site/assets").mkdir(parents=True)
    (repo / "site/index.html").write_text("tracked shell", encoding="utf-8")
    (repo / "site/assets/app.css").write_text("tracked css", encoding="utf-8")
    write_snapshot(repo, INITIAL_DATE, [INITIAL_DATE])
    run_git(repo, "add", "--", "site")
    run_git(repo, "commit", "-m", "initial site")
    run_git(repo, "remote", "add", "origin", str(remote))
    run_git(repo, "push", "-u", "origin", "main")

    monkeypatch.setattr(publish_pages, "ROOT", repo)
    monkeypatch.setattr(publish_pages, "RUN_LOCK_PATH", repo / "data" / "run_daily.lock")
    return repo, remote


def remote_head(remote: Path) -> str:
    return run_git(remote, "rev-parse", "refs/heads/main").stdout.strip()


def test_publish_refuses_feature_branch(
    publish_repo: tuple[Path, Path],
) -> None:
    repo, remote = publish_repo
    original_remote_head = remote_head(remote)
    run_git(repo, "checkout", "-b", "feature/report")
    write_snapshot(repo, NEW_DATE, [NEW_DATE, INITIAL_DATE])

    with pytest.raises(RuntimeError, match="只允许从 'main' 分支"):
        publish_pages.main([])

    assert remote_head(remote) == original_remote_head


def test_publish_commits_only_current_generated_report_files(
    publish_repo: tuple[Path, Path],
) -> None:
    repo, remote = publish_repo
    write_snapshot(repo, NEW_DATE, [NEW_DATE, INITIAL_DATE])
    (repo / "site/index.html").write_text("unrelated dirty shell", encoding="utf-8")
    (repo / "site/assets/app.css").write_text("unrelated dirty css", encoding="utf-8")
    run_git(repo, "add", "--", "site/index.html")
    write_json(repo / "site/data/unrelated.json", {"do_not_publish": True})

    assert publish_pages.main([]) == 0

    commit_sha = remote_head(remote)
    changed_paths = {
        line.strip()
        for line in run_git(
            repo,
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            commit_sha,
        ).stdout.splitlines()
        if line.strip()
    }
    assert changed_paths == {
        "site/data/latest.json",
        "site/data/history.json",
        f"site/data/history/{NEW_DATE}.json",
    }
    assert run_git(repo, "show", f"{commit_sha}:site/index.html").stdout == "tracked shell"
    assert run_git(
        repo,
        "cat-file",
        "-e",
        f"{commit_sha}:site/data/unrelated.json",
        check=False,
    ).returncode != 0

    status = run_git(repo, "status", "--short", "--untracked-files=all").stdout
    assert "site/index.html" in status
    assert "site/assets/app.css" in status
    assert "site/data/unrelated.json" in status
    assert run_git(repo, "diff", "--cached", "--name-only").stdout.strip() == "site/index.html"


def test_failed_push_is_retained_and_retried(
    publish_repo: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    repo, remote = publish_repo
    original_remote_head = remote_head(remote)
    write_snapshot(repo, NEW_DATE, [NEW_DATE, INITIAL_DATE])
    missing_remote = tmp_path / "missing.git"
    run_git(repo, "remote", "set-url", "--push", "origin", str(missing_remote))

    with pytest.raises(RuntimeError, match="已保留，下次会先重试"):
        publish_pages.main([])

    pending_sha = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    assert pending_sha != original_remote_head
    assert remote_head(remote) == original_remote_head
    assert publish_pages.PUBLISH_TRAILER in run_git(
        repo,
        "show",
        "-s",
        "--format=%B",
        pending_sha,
    ).stdout

    run_git(repo, "remote", "set-url", "--push", "origin", str(remote))
    assert publish_pages.main([]) == 0
    assert remote_head(remote) == pending_sha
    assert run_git(repo, "status", "--short", "--", "site/data").stdout == ""


def test_publish_refuses_unrelated_local_commit(
    publish_repo: tuple[Path, Path],
) -> None:
    repo, remote = publish_repo
    original_remote_head = remote_head(remote)
    (repo / "README.md").write_text("local commit", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "unreviewed local change")

    with pytest.raises(RuntimeError, match="非发布提交"):
        publish_pages.main([])

    assert remote_head(remote) == original_remote_head


def test_publish_refuses_dirty_report_source(
    publish_repo: tuple[Path, Path],
) -> None:
    repo, remote = publish_repo
    original_remote_head = remote_head(remote)
    source = repo / "src" / "scoring.py"
    source.parent.mkdir(parents=True)
    source.write_text("UNREVIEWED = True\n", encoding="utf-8")
    write_snapshot(repo, NEW_DATE, [NEW_DATE, INITIAL_DATE])

    with pytest.raises(RuntimeError, match="源码或配置存在未提交修改"):
        publish_pages.main([])

    assert remote_head(remote) == original_remote_head


def test_push_uses_validated_commit_when_local_branch_moves(
    publish_repo: tuple[Path, Path],
) -> None:
    repo, remote = publish_repo
    write_snapshot(repo, NEW_DATE, [NEW_DATE, INITIAL_DATE])
    snapshot = publish_pages._load_report_snapshot()
    publish_sha = publish_pages._commit_report(snapshot, "main")

    (repo / "README.md").write_text("later unrelated commit", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "later unrelated commit")
    moved_sha = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    assert moved_sha != publish_sha

    publish_pages._fetch_target("origin", "main")
    publish_pages._push_branch("origin", "main", publish_sha)

    assert remote_head(remote) == publish_sha
    assert remote_head(remote) != moved_sha


def test_publish_refuses_modified_retained_history(
    publish_repo: tuple[Path, Path],
) -> None:
    repo, _ = publish_repo
    write_snapshot(repo, NEW_DATE, [NEW_DATE, INITIAL_DATE])
    write_json(
        repo / f"site/data/history/{INITIAL_DATE}.json",
        {"report_date": INITIAL_DATE, "unexpected": "manual edit"},
    )

    with pytest.raises(RuntimeError, match="既有历史报告存在额外修改"):
        publish_pages.main([])


def test_publish_upgrades_intraday_to_close_for_retained_history(
    publish_repo: tuple[Path, Path],
) -> None:
    repo, remote = publish_repo
    intraday_payload = report_payload_with_snapshot(INITIAL_DATE, "intraday", True)
    write_json(repo / "site/data/latest.json", intraday_payload)
    write_json(repo / f"site/data/history/{INITIAL_DATE}.json", intraday_payload)
    run_git(
        repo,
        "add",
        "--",
        "site/data/latest.json",
        f"site/data/history/{INITIAL_DATE}.json",
    )
    run_git(repo, "commit", "-m", "provisional intraday for initial date")
    run_git(repo, "push", "origin", "main")

    close_payload = report_payload_with_snapshot(INITIAL_DATE, "close", False)
    write_json(repo / f"site/data/history/{INITIAL_DATE}.json", close_payload)
    write_snapshot(repo, NEW_DATE, [NEW_DATE, INITIAL_DATE])

    assert publish_pages.main([]) == 0

    commit_sha = remote_head(remote)
    changed_paths = {
        line.strip()
        for line in run_git(
            repo,
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            commit_sha,
        ).stdout.splitlines()
        if line.strip()
    }
    assert f"site/data/history/{INITIAL_DATE}.json" in changed_paths
    assert "site/data/history.json" in changed_paths
    assert f"site/data/history/{NEW_DATE}.json" in changed_paths
    assert "site/data/latest.json" in changed_paths
    upgraded = json.loads(
        run_git(repo, "show", f"{commit_sha}:site/data/history/{INITIAL_DATE}.json").stdout
    )
    assert upgraded["is_provisional"] is False
    assert upgraded["snapshot_type"] == "close"


def test_publish_refuses_close_to_intraday_revert_of_retained_history(
    publish_repo: tuple[Path, Path],
) -> None:
    repo, _ = publish_repo
    write_snapshot(repo, NEW_DATE, [NEW_DATE, INITIAL_DATE])
    write_json(
        repo / f"site/data/history/{INITIAL_DATE}.json",
        report_payload_with_snapshot(INITIAL_DATE, "intraday", True),
    )

    with pytest.raises(RuntimeError, match="既有历史报告存在额外修改"):
        publish_pages.main([])


def test_publish_applies_only_retention_deletions(
    publish_repo: tuple[Path, Path],
) -> None:
    repo, remote = publish_repo
    write_snapshot(repo, NEW_DATE, [NEW_DATE])
    (repo / f"site/data/history/{INITIAL_DATE}.json").unlink()

    assert publish_pages.main([]) == 0

    commit_sha = remote_head(remote)
    status = run_git(
        repo,
        "diff-tree",
        "--no-commit-id",
        "--name-status",
        "-r",
        commit_sha,
    ).stdout
    assert f"D\tsite/data/history/{INITIAL_DATE}.json" in status
    assert f"A\tsite/data/history/{NEW_DATE}.json" in status


def test_dry_run_does_not_touch_index(
    publish_repo: tuple[Path, Path],
) -> None:
    repo, remote = publish_repo
    original_remote_head = remote_head(remote)
    write_snapshot(repo, NEW_DATE, [NEW_DATE, INITIAL_DATE])

    assert publish_pages.main(["--dry-run"]) == 0

    assert remote_head(remote) == original_remote_head
    assert run_git(repo, "diff", "--cached", "--name-only").stdout == ""
    assert run_git(repo, "rev-parse", "HEAD").stdout.strip() == original_remote_head
