from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional

from skill_eval.models import GitStateSnapshot


def _run(args: list[str], cwd: Path) -> str:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
    return result.stdout or ""


def capture_git_state(workspace: Path, source_repo: Optional[str] = None) -> GitStateSnapshot:
    """Snapshot the git and PR state of a workspace.

    Captures branches, current HEAD, commit count, recent commits, and (if a
    source repo is configured) the list of PRs currently open on the remote.
    """
    raw_branches = _run(["git", "branch", "-a"], workspace).strip().split("\n")
    local_branches: set[str] = set()
    remote_branches: set[str] = set()
    for line in raw_branches:
        b = line.strip().lstrip("* ")
        if not b or "HEAD" in b:
            continue
        if b.startswith("remotes/"):
            stripped = b[len("remotes/") :]
            if "/" in stripped:
                remote_branches.add(stripped.split("/", 1)[1])
        else:
            local_branches.add(b)

    current = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], workspace).strip()
    head = _run(["git", "rev-parse", "HEAD"], workspace).strip()
    count_raw = _run(["git", "rev-list", "--all", "--count"], workspace).strip()
    log = _run(["git", "log", "--all", "--pretty=format:%h %s"], workspace).strip()
    commits = [line for line in log.split("\n") if line.strip()]
    remotes_raw = _run(["git", "remote", "-v"], workspace).strip()
    remote_names = sorted({line.split()[0] for line in remotes_raw.split("\n") if line.strip()})

    open_prs: list[dict] = []
    if source_repo:
        slug = source_repo.rstrip("/").split("github.com/")[-1].removesuffix(".git")
        prs_raw = _run(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                slug,
                "--state",
                "all",
                "--json",
                "number,headRefName,baseRefName,url,state",
            ],
            Path.cwd(),
        )
        if prs_raw.strip():
            try:
                open_prs = json.loads(prs_raw)
            except json.JSONDecodeError:
                open_prs = []

    return GitStateSnapshot(
        local_branches=sorted(local_branches),
        remote_branches=sorted(remote_branches),
        current_branch=current,
        head_sha=head,
        commit_count=int(count_raw) if count_raw.isdigit() else len(commits),
        commits=commits[:20],
        remote_names=remote_names,
        open_prs=open_prs,
    )


def state_diff(pre: GitStateSnapshot, post: GitStateSnapshot) -> dict:
    """Compute the delta between two state snapshots.

    Returns a dict of the form::

        {
            "new_branches": [...],
            "new_remote_branches": [...],
            "current_branch_changed": bool,
            "head_advanced": bool,
            "new_commits": [...],
            "new_open_prs": [...],
        }
    """
    pre_local = set(pre.local_branches)
    pre_remote = set(pre.remote_branches)
    pre_pr_numbers = {p.get("number") for p in pre.open_prs}

    new_open_prs = [p for p in post.open_prs if p.get("number") not in pre_pr_numbers]

    return {
        "new_branches": sorted(set(post.local_branches) - pre_local),
        "new_remote_branches": sorted(set(post.remote_branches) - pre_remote),
        "current_branch_changed": pre.current_branch != post.current_branch,
        "head_advanced": pre.head_sha != post.head_sha and bool(post.head_sha),
        "new_commits": [c for c in post.commits if c not in pre.commits],
        "new_open_prs": new_open_prs,
    }
