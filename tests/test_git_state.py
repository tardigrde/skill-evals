from __future__ import annotations

from skill_eval.git_state import capture_git_state, github_repo_slug, state_diff
from skill_eval.models import GitStateSnapshot

from .conftest import _init_git_workspace


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


class TestGitHubRepoSlug:
    def test_parses_https_clone_url(self):
        assert github_repo_slug("https://github.com/owner/repo.git") == "owner/repo"

    def test_parses_ssh_clone_url(self):
        assert github_repo_slug("git@github.com:owner/repo.git") == "owner/repo"

    def test_parses_ssh_url(self):
        assert github_repo_slug("ssh://git@github.com/owner/repo.git") == "owner/repo"

    def test_rejects_non_github_url(self):
        assert github_repo_slug("https://example.com/owner/repo.git") is None

    def test_parses_https_url_no_git_suffix(self):
        assert github_repo_slug("https://github.com/owner/repo") == "owner/repo"

    def test_parses_ssh_url_no_git_suffix(self):
        assert github_repo_slug("git@github.com:owner/repo") == "owner/repo"

    def test_parses_github_com_slug_no_git_suffix(self):
        assert github_repo_slug("github.com/owner/repo") == "owner/repo"

    def test_parses_raw_slug(self):
        assert github_repo_slug("owner/repo") == "owner/repo"

    def test_capture_uses_normalized_slug_for_gh(self, tmp_path, monkeypatch):
        gh_calls: list[list[str]] = []
        sha = "a" * 40

        def fake_run(args, cwd):
            if args[0] == "gh":
                gh_calls.append(args)
                return "[]"
            if args[:3] == ["git", "branch", "-a"]:
                return "* main\n"
            if args[:3] == ["git", "rev-parse", "--abbrev-ref"]:
                return "main\n"
            if args[:2] == ["git", "rev-parse"]:
                return f"{sha}\n"
            if args[:3] == ["git", "rev-list", "--all"]:
                return "1\n"
            if args[:3] == ["git", "log", "--all"] and "%H" in args[-1]:
                return sha
            if args[:3] == ["git", "log", "--all"]:
                return "aaaaaaa init"
            if args[:3] == ["git", "for-each-ref", "refs/heads"]:
                return f"main {sha}\n"
            if args[:3] == ["git", "for-each-ref", "refs/remotes"]:
                return ""
            if args[:2] == ["git", "remote"]:
                return "origin git@github.com:owner/repo.git (fetch)\n"
            return ""

        monkeypatch.setattr("skill_eval.git_state._run", fake_run)

        capture_git_state(tmp_path, source_repo="git@github.com:owner/repo.git")

        assert gh_calls
        assert gh_calls[0][gh_calls[0].index("--repo") + 1] == "owner/repo"
