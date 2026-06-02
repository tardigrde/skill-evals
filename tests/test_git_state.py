from __future__ import annotations

import subprocess
from pathlib import Path

from skill_eval.git_state import capture_git_state, state_diff
from skill_eval.models import GitStateSnapshot


def _init_git_workspace(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=path, capture_output=True, check=True)
    (path / "init.txt").write_text("init")
    subprocess.run(["git", "add", "."], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, capture_output=True, check=True)


def _make_snapshot(local_branches, remote_branches, current, head, commit_shas, remote_branch_heads=None):
    return GitStateSnapshot(
        local_branches=local_branches,
        remote_branches=remote_branches,
        current_branch=current,
        head_sha=head,
        commit_count=len(commit_shas),
        commits=[s[:7] for s in commit_shas],
        commit_shas=commit_shas,
        remote_names=["origin"],
        open_prs=[],
        branch_heads={b: head for b in local_branches},
        remote_branch_heads=remote_branch_heads or {},
    )


class TestStateDiffEvalBranch:
    def test_eval_branch_is_post_current_when_new(self):
        pre = _make_snapshot(["main"], [], "main", "a" * 40, ["a" * 40])
        post = _make_snapshot(["main", "feature/x"], [], "feature/x", "a" * 40, ["a" * 40])
        diff = state_diff(pre, post)
        assert diff["eval_branch"] == "feature/x"

    def test_eval_branch_is_none_when_only_existing_branch_checked_out(self):
        pre = _make_snapshot(["main", "feature/existing"], [], "main", "a" * 40, ["a" * 40])
        post = _make_snapshot(["main", "feature/existing"], [], "feature/existing", "a" * 40, ["a" * 40])
        diff = state_diff(pre, post)
        assert diff["eval_branch"] is None
        assert diff["new_branches"] == []

    def test_eval_branch_pushed_matches_head(self):
        pre = _make_snapshot(["main"], [], "main", "a" * 40, ["a" * 40])
        post = _make_snapshot(
            ["main", "feature/x"],
            ["feature/x"],
            "feature/x",
            "b" * 40,
            ["a" * 40, "b" * 40],
            remote_branch_heads={"feature/x": "b" * 40},
        )
        diff = state_diff(pre, post)
        assert diff["eval_branch"] == "feature/x"
        assert diff["eval_branch_pushed"] is True
        assert diff["eval_branch_pushed_matches_head"] is True

    def test_eval_branch_pushed_but_head_mismatch(self):
        pre = _make_snapshot(["main"], [], "main", "a" * 40, ["a" * 40])
        post = _make_snapshot(
            ["main", "feature/x"],
            ["feature/x"],
            "feature/x",
            "b" * 40,
            ["a" * 40, "b" * 40],
            remote_branch_heads={"feature/x": "0" * 40},
        )
        diff = state_diff(pre, post)
        assert diff["eval_branch"] == "feature/x"
        assert diff["eval_branch_pushed"] is True
        assert diff["eval_branch_pushed_matches_head"] is False


class TestStateDiffNewCommitShas:
    def test_new_commit_shas_detected(self):
        pre = _make_snapshot(["main"], [], "main", "a" * 40, ["a" * 40])
        post = _make_snapshot(["main"], [], "main", "b" * 40, ["a" * 40, "b" * 40])
        diff = state_diff(pre, post)
        assert diff["new_commit_shas"] == ["b" * 40]
        assert diff["head_advanced"] is True

    def test_no_new_commit_shas_when_only_branch_checkout(self):
        pre = _make_snapshot(["main", "feature/existing"], [], "main", "a" * 40, ["a" * 40])
        post = _make_snapshot(["main", "feature/existing"], [], "feature/existing", "a" * 40, ["a" * 40])
        diff = state_diff(pre, post)
        assert diff["new_commit_shas"] == []
        assert diff["head_advanced"] is False


class TestCaptureGitStateFullShas:
    def test_capture_records_full_shas(self, tmp_path):
        _init_git_workspace(tmp_path)
        snap = capture_git_state(tmp_path)
        assert snap.head_sha
        assert len(snap.head_sha) == 40
        assert all(len(s) == 40 for s in snap.commit_shas)
        assert "main" in snap.branch_heads
        assert snap.branch_heads["main"] == snap.head_sha
