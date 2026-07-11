from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="发布最新静态盘后报告到 GitHub Pages")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    latest_path = ROOT / "site" / "data" / "latest.json"
    if not latest_path.exists():
        raise RuntimeError("site/data/latest.json 不存在，请先成功执行盘后任务")
    payload = json.loads(latest_path.read_text(encoding="utf-8"))
    report_date = payload.get("report_date")
    if not report_date:
        raise RuntimeError("静态报告缺少 report_date，已停止发布")
    if not (ROOT / ".git").exists():
        raise RuntimeError("当前目录不是 Git 仓库，无法自动发布")

    git("add", "--", "site")
    changed = git("diff", "--cached", "--quiet", "--", "site", check=False)
    if changed.returncode == 0:
        print("网页报告没有变化，无需发布")
        return 0
    if args.dry_run:
        print(git("diff", "--cached", "--stat", "--", "site").stdout)
        return 0

    message = f"chore(report): publish {report_date}"
    commit = git("commit", "-m", message, "--", "site", check=False)
    if commit.returncode != 0:
        raise RuntimeError("Git 提交失败: " + (commit.stderr or commit.stdout).strip())
    push = git("push", args.remote, f"HEAD:{args.branch}", check=False)
    if push.returncode != 0:
        raise RuntimeError("GitHub 推送失败: " + (push.stderr or push.stdout).strip())
    print(f"已发布 {report_date} 网页报告到 {args.remote}/{args.branch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
