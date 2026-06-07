from __future__ import annotations

import json
import subprocess
from pathlib import Path

from skill_eval.graders import DeterministicGrader
from skill_eval.models import GitStateSnapshot

from .conftest import _init_git_workspace


def _snapshot(ws: Path) -> GitStateSnapshot:
    from skill_eval.git_state import capture_git_state

    return capture_git_state(ws)


class TestCheckContentContains:
    def test_passes_when_pattern_found(self, grader):
        result = grader._check_content_contains(
            'The output contains the word "success"',
            "The operation was a success!",
        )
        assert result.passed
        assert "success" in result.evidence

    def test_fails_when_pattern_not_found(self, grader):
        result = grader._check_content_contains(
            'The output contains the word "success"',
            "The operation failed.",
        )
        assert not result.passed

    def test_case_insensitive(self, grader):
        result = grader._check_content_contains(
            'The output contains the word "SUCCESS"',
            "the operation was a success",
        )
        assert result.passed

    def test_backtick_patterns(self, grader):
        result = grader._check_content_contains(
            "The output contains the word `hello`",
            "hello world",
        )
        assert result.passed


class TestCheckCommandRan:
    def test_passes_when_command_found_in_stdout(self, grader, tmp_path):
        stdout_file = tmp_path / "stdout.log"
        stdout_file.write_text("Running git commit...")
        result = grader._check_command_ran("Verify git command ran", tmp_path)
        assert result.passed
        assert "git" in result.evidence
        assert "stdout.log" in result.evidence

    def test_passes_when_command_found_in_stderr(self, grader, tmp_path):
        stderr_file = tmp_path / "stderr.log"
        stderr_file.write_text("Error: python script failed")
        result = grader._check_command_ran("Verify python command ran", tmp_path)
        assert result.passed
        assert "python" in result.evidence
        assert "stderr.log" in result.evidence

    def test_fails_when_logs_empty_or_missing(self, grader, tmp_path):
        result = grader._check_command_ran("Verify npm command ran", tmp_path)
        assert not result.passed
        assert "Command not found in logs" in result.evidence

    def test_fails_when_command_not_in_logs(self, grader, tmp_path):
        stdout_file = tmp_path / "stdout.log"
        stdout_file.write_text("Running some other command...")
        result = grader._check_command_ran("Verify git command ran", tmp_path)
        assert not result.passed

    def test_passes_for_cargo(self, grader, tmp_path):
        (tmp_path / "stdout.log").write_text("Compiling cargo build")
        result = grader._check_command_ran("Verify cargo command ran", tmp_path)
        assert result.passed

    def test_passes_for_go(self, grader, tmp_path):
        (tmp_path / "stdout.log").write_text("go: downloading modules")
        result = grader._check_command_ran("Verify go command ran", tmp_path)
        assert result.passed

    def test_passes_for_yarn(self, grader, tmp_path):
        (tmp_path / "stdout.log").write_text("yarn install v1.22")
        result = grader._check_command_ran("Verify yarn command ran", tmp_path)
        assert result.passed

    def test_passes_for_pnpm(self, grader, tmp_path):
        (tmp_path / "stdout.log").write_text("pnpm install complete")
        result = grader._check_command_ran("Verify pnpm command ran", tmp_path)
        assert result.passed

    def test_fails_for_command_not_in_hardcoded_list(self, grader, tmp_path):
        (tmp_path / "stdout.log").write_text("docker build complete")
        result = grader._check_command_ran("Verify docker command ran", tmp_path)
        assert not result.passed
        assert "docker" not in result.evidence.lower() or "not found" in result.evidence.lower()


class TestCheckGitBranch:
    def test_passes_when_new_branch_appeared_in_state(self, grader, git_workspace):
        _ = _snapshot(git_workspace)
        subprocess.run(
            ["git", "checkout", "-b", "feature/test"],
            cwd=git_workspace,
            capture_output=True,
            check=True,
        )
        post = _snapshot(git_workspace)
        diff = {
            "new_branches": ["feature/test"],
            "new_remote_branches": [],
            "current_branch": "feature/test",
            "current_branch_changed": True,
            "head_advanced": False,
            "new_commits": [],
            "new_open_prs": [],
            "eval_branch": "feature/test",
        }
        grader_with_state = DeterministicGrader(post_state=post)
        result = grader_with_state._check_git_branch("A new git branch was created", diff, should_trigger=True)
        assert result.passed
        assert "feature/test" in result.evidence

    def test_fails_when_no_new_branch(self, grader):
        diff = {
            "new_branches": [],
            "new_remote_branches": [],
            "current_branch": "main",
            "current_branch_changed": False,
            "head_advanced": False,
            "new_commits": [],
            "new_open_prs": [],
            "eval_branch": None,
        }
        result = grader._check_git_branch("A new git branch was created", diff, should_trigger=True)
        assert not result.passed

    def test_negative_control_passes_when_no_new_branch(self, grader):
        diff = {
            "new_branches": [],
            "new_remote_branches": [],
            "current_branch": "main",
            "current_branch_changed": False,
            "head_advanced": False,
            "new_commits": [],
            "new_open_prs": [],
            "eval_branch": None,
        }
        result = grader._check_git_branch("A new git branch was created", diff, should_trigger=False)
        assert result.passed
        assert "did not trigger" in result.evidence

    def test_negative_control_fails_when_branch_was_created(self, grader):
        diff = {
            "new_branches": ["feature/unwanted"],
            "current_branch": "feature/unwanted",
            "current_branch_changed": True,
            "new_remote_branches": [],
            "head_advanced": False,
            "new_commits": [],
            "new_open_prs": [],
            "eval_branch": "feature/unwanted",
        }
        result = grader._check_git_branch("A new git branch was created", diff, should_trigger=False)
        assert not result.passed
        assert "should not have triggered" in result.evidence

    def test_existing_branch_does_not_satisfy_new_branch_assertion(self, grader, git_workspace):
        """An existing branch from the baseline must NOT satisfy 'new branch'."""
        _ = _snapshot(git_workspace)
        diff = {
            "new_branches": [],
            "new_remote_branches": [],
            "current_branch": "main",
            "current_branch_changed": False,
            "head_advanced": False,
            "new_commits": [],
            "new_open_prs": [],
            "eval_branch": None,
        }
        result = grader._check_git_branch("A new git branch was created", diff, should_trigger=True)
        assert not result.passed

    def test_checking_out_existing_branch_does_not_count_as_new(self, grader, git_workspace):
        """Regression: pre-state has main + feature/existing; agent only checks out
        feature/existing. New branch assertion must fail because no branch was
        actually created during the run."""
        # Create an existing branch in the baseline
        subprocess.run(
            ["git", "checkout", "-b", "feature/existing"],
            cwd=git_workspace,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=git_workspace,
            capture_output=True,
            check=True,
        )
        pre = _snapshot(git_workspace)

        # Agent "checks out" the existing branch (no new branch created)
        subprocess.run(
            ["git", "checkout", "feature/existing"],
            cwd=git_workspace,
            capture_output=True,
            check=True,
        )
        post = _snapshot(git_workspace)

        from skill_eval.git_state import state_diff

        diff = state_diff(pre, post)
        # Sanity: no new branch was actually created
        assert diff["new_branches"] == []
        assert diff["current_branch_changed"] is True

        grader_with_state = DeterministicGrader(pre_state=pre, post_state=post)
        result = grader_with_state._check_git_branch("A new git branch was created", diff, should_trigger=True)
        assert not result.passed, "Branch assertion must fail when the agent only checks out an existing branch"


class TestCheckGitCommit:
    def test_passes_when_new_commit_on_current_branch(self, grader, git_workspace):
        """Real commit created on the eval branch should pass."""
        pre = _snapshot(git_workspace)
        (git_workspace / "x.txt").write_text("y")
        subprocess.run(["git", "add", "."], cwd=git_workspace, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "agent work"], cwd=git_workspace, capture_output=True, check=True)
        post = _snapshot(git_workspace)

        from skill_eval.git_state import state_diff

        diff = state_diff(pre, post)
        grader_with_state = DeterministicGrader(pre_state=pre, post_state=post)
        result = grader_with_state._check_git_commit("A git commit was created", diff, should_trigger=True)
        assert result.passed

    def test_fails_when_no_new_commit(self, grader, git_workspace):
        diff = {
            "new_branches": [],
            "new_remote_branches": [],
            "current_branch": "main",
            "current_branch_changed": False,
            "head_advanced": False,
            "new_commits": [],
            "new_commit_shas": [],
            "new_open_prs": [],
            "eval_branch": None,
        }
        post = GitStateSnapshot(head_sha="a" * 40)
        grader_with_state = DeterministicGrader(post_state=post)
        result = grader_with_state._check_git_commit("A git commit was created", diff, should_trigger=True)
        assert not result.passed

    def test_existing_commit_does_not_satisfy_new_commit_assertion(self, grader, git_workspace):
        """An existing commit at baseline must NOT satisfy 'new commit'."""
        diff = {
            "new_branches": [],
            "new_remote_branches": [],
            "current_branch": "main",
            "current_branch_changed": False,
            "head_advanced": False,
            "new_commits": [],
            "new_commit_shas": [],
            "new_open_prs": [],
            "eval_branch": None,
        }
        post = GitStateSnapshot(head_sha="a" * 40)
        grader_with_state = DeterministicGrader(post_state=post)
        result = grader_with_state._check_git_commit("A git commit was created", diff, should_trigger=True)
        assert not result.passed

    def test_negative_control_fails_when_new_commit(self, grader, git_workspace):
        diff = {
            "new_branches": [],
            "new_remote_branches": [],
            "current_branch": "main",
            "current_branch_changed": False,
            "head_advanced": True,
            "new_commits": ["abc123 new commit"],
            "new_commit_shas": ["b" * 40],
            "new_open_prs": [],
            "eval_branch": None,
        }
        post = GitStateSnapshot(head_sha="b" * 40)
        grader_with_state = DeterministicGrader(post_state=post)
        result = grader_with_state._check_git_commit("A git commit was created", diff, should_trigger=False)
        assert not result.passed
        assert "should not have triggered" in result.evidence

    def test_negative_control_passes_when_no_commit(self, grader):
        diff = {
            "new_branches": [],
            "new_remote_branches": [],
            "current_branch": "main",
            "current_branch_changed": False,
            "head_advanced": False,
            "new_commits": [],
            "new_commit_shas": [],
            "new_open_prs": [],
            "eval_branch": None,
        }
        post = GitStateSnapshot(head_sha="a" * 40)
        grader_with_state = DeterministicGrader(post_state=post)
        result = grader_with_state._check_git_commit("A git commit was created", diff, should_trigger=False)
        assert result.passed

    def test_negative_control_passes_when_only_head_moves(self, grader):
        diff = {
            "new_branches": [],
            "new_remote_branches": [],
            "current_branch": "feature/existing",
            "current_branch_changed": True,
            "head_advanced": True,
            "new_commits": [],
            "new_commit_shas": [],
            "new_open_prs": [],
            "eval_branch": None,
        }
        post = GitStateSnapshot(head_sha="b" * 40)
        grader_with_state = DeterministicGrader(post_state=post)
        result = grader_with_state._check_git_commit("A git commit was created", diff, should_trigger=False)
        assert result.passed

    def test_checking_out_existing_branch_does_not_count_as_new_commit(self, grader, git_workspace):
        """Regression: agent checks out an existing branch, HEAD changes (different
        SHA) but no new commit is created. The commit assertion must fail."""
        # Create two branches with distinct commits
        subprocess.run(
            ["git", "checkout", "-b", "feature/x"],
            cwd=git_workspace,
            capture_output=True,
            check=True,
        )
        (git_workspace / "x.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=git_workspace, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "x work"], cwd=git_workspace, capture_output=True, check=True)
        subprocess.run(["git", "checkout", "main"], cwd=git_workspace, capture_output=True, check=True)
        pre = _snapshot(git_workspace)

        # Agent only checks out feature/x — no new commit
        subprocess.run(
            ["git", "checkout", "feature/x"],
            cwd=git_workspace,
            capture_output=True,
            check=True,
        )
        post = _snapshot(git_workspace)

        from skill_eval.git_state import state_diff

        diff = state_diff(pre, post)
        # Sanity: HEAD moved but no new commits
        assert diff["head_advanced"] is True
        assert diff["new_commit_shas"] == []
        assert diff["new_commits"] == []

        grader_with_state = DeterministicGrader(pre_state=pre, post_state=post)
        result = grader_with_state._check_git_commit("A git commit was created", diff, should_trigger=True)
        assert not result.passed, "Commit assertion must fail when the agent only checks out an existing branch"


class TestCheckFileExists:
    def test_passes_when_file_exists(self, grader, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        result = grader._check_file_exists(
            "The file `package.json` was created",
            tmp_path / "output",
            workspace=tmp_path,
        )
        assert result.passed

    def test_fails_when_file_missing(self, grader, tmp_path):
        result = grader._check_file_exists(
            "The file `package.json` was created",
            tmp_path / "output",
            workspace=tmp_path,
        )
        assert not result.passed


class TestCheckValidJson:
    def test_passes_for_valid_json_output(self, grader, tmp_path):
        result = grader._check_valid_json(
            "The output is valid JSON",
            tmp_path / "output",
            '{"key": "value"}',
        )
        assert result.passed

    def test_fails_for_invalid_json(self, grader, tmp_path):
        result = grader._check_valid_json(
            "The output is valid JSON",
            tmp_path / "output",
            "not json at all",
        )
        assert not result.passed


class TestCheckPushed:
    def test_passes_when_new_branch_pushed_with_matching_head(self, grader, git_workspace):
        """Eval branch was pushed and remote HEAD matches local HEAD."""
        pre = _snapshot(git_workspace)
        subprocess.run(
            ["git", "checkout", "-b", "feature/x"],
            cwd=git_workspace,
            capture_output=True,
            check=True,
        )
        (git_workspace / "x.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=git_workspace, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "x work"], cwd=git_workspace, capture_output=True, check=True)
        # Simulate push by creating a remote ref pointing to current HEAD
        post_state = _snapshot(git_workspace)
        # Manually create remote branch heads (since no real remote)
        head_sha = post_state.head_sha
        post_state.remote_branches = list(post_state.remote_branches) + ["feature/x"]
        post_state.remote_branch_heads = {**post_state.remote_branch_heads, "feature/x": head_sha}

        from skill_eval.git_state import state_diff

        diff = state_diff(pre, post_state)
        assert diff["eval_branch"] == "feature/x"
        assert diff["eval_branch_pushed"] is True
        assert diff["eval_branch_pushed_matches_head"] is True

        grader_with_state = DeterministicGrader(post_state=post_state)
        result = grader_with_state._check_pushed(
            "Changes were pushed to remote",
            diff,
            agent_output="",
            should_trigger=True,
        )
        assert result.passed

    def test_fails_when_local_branch_created_but_not_pushed(self, grader, git_workspace):
        """Local branch + new commit exist, but no matching remote branch head."""
        pre = _snapshot(git_workspace)
        subprocess.run(
            ["git", "checkout", "-b", "feature/x"],
            cwd=git_workspace,
            capture_output=True,
            check=True,
        )
        (git_workspace / "x.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=git_workspace, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "x work"], cwd=git_workspace, capture_output=True, check=True)
        post_state = _snapshot(git_workspace)

        from skill_eval.git_state import state_diff

        diff = state_diff(pre, post_state)
        assert diff["eval_branch"] == "feature/x"
        assert diff["eval_branch_pushed"] is False

        grader_with_state = DeterministicGrader(post_state=post_state)
        result = grader_with_state._check_pushed(
            "Changes were pushed to remote",
            diff,
            agent_output="I pushed",
            should_trigger=True,
        )
        assert not result.passed
        assert "not pushed" in result.evidence

    def test_fails_when_unrelated_remote_branch_appears(self, grader, git_workspace):
        """A new remote branch that does NOT match the eval branch must not pass."""
        pre = _snapshot(git_workspace)
        subprocess.run(
            ["git", "checkout", "-b", "feature/eval-branch"],
            cwd=git_workspace,
            capture_output=True,
            check=True,
        )
        (git_workspace / "x.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=git_workspace, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "x work"], cwd=git_workspace, capture_output=True, check=True)
        post_state = _snapshot(git_workspace)
        # Add an unrelated remote branch pointing to an old commit
        post_state.remote_branches = list(post_state.remote_branches) + ["unrelated-branch"]
        post_state.remote_branch_heads = {
            **post_state.remote_branch_heads,
            "unrelated-branch": "0" * 40,
        }

        from skill_eval.git_state import state_diff

        diff = state_diff(pre, post_state)
        # Sanity: a new remote branch appeared but it isn't the eval branch
        assert diff["eval_branch"] == "feature/eval-branch"
        assert "unrelated-branch" in diff["new_remote_branches"]
        assert diff["eval_branch_pushed"] is False

        grader_with_state = DeterministicGrader(post_state=post_state)
        result = grader_with_state._check_pushed(
            "Changes were pushed to remote",
            diff,
            agent_output="",
            should_trigger=True,
        )
        assert not result.passed

    def test_existing_remote_refs_do_not_satisfy_pushed(self, grader):
        """Existing remote refs at baseline must NOT satisfy 'pushed'."""
        diff = {
            "new_branches": [],
            "new_remote_branches": [],
            "current_branch": "main",
            "current_branch_changed": False,
            "head_advanced": False,
            "new_commits": [],
            "new_commit_shas": [],
            "new_open_prs": [],
            "eval_branch": None,
            "eval_branch_pushed": False,
            "eval_branch_pushed_matches_head": False,
        }
        post = GitStateSnapshot(head_sha="a" * 40)
        grader_with_state = DeterministicGrader(post_state=post)
        result = grader_with_state._check_pushed(
            "Changes were pushed to remote",
            diff,
            agent_output="I pushed to origin",
            should_trigger=True,
        )
        assert not result.passed

    def test_output_text_alone_does_not_pass(self, grader):
        """Agent saying 'I pushed' is not enough; state must show new remote refs."""
        diff = {
            "new_branches": [],
            "new_remote_branches": [],
            "current_branch": "main",
            "current_branch_changed": False,
            "head_advanced": False,
            "new_commits": [],
            "new_commit_shas": [],
            "new_open_prs": [],
            "eval_branch": None,
            "eval_branch_pushed": False,
            "eval_branch_pushed_matches_head": False,
        }
        post = GitStateSnapshot(head_sha="a" * 40)
        grader_with_state = DeterministicGrader(post_state=post)
        result = grader_with_state._check_pushed(
            "Changes were pushed to remote",
            diff,
            agent_output="I successfully pushed to origin/main",
            should_trigger=True,
        )
        assert not result.passed
        assert "No eval-created branch" in result.evidence or "not pushed" in result.evidence

    def test_negative_control_fails_when_pushed(self, grader):
        diff = {
            "new_branches": ["feature/x"],
            "new_remote_branches": ["feature/x"],
            "current_branch": "feature/x",
            "current_branch_changed": True,
            "head_advanced": True,
            "new_commits": ["abc new"],
            "new_commit_shas": ["b" * 40],
            "new_open_prs": [],
            "eval_branch": "feature/x",
            "eval_branch_pushed": True,
            "eval_branch_pushed_matches_head": True,
        }
        post = GitStateSnapshot(head_sha="b" * 40)
        grader_with_state = DeterministicGrader(post_state=post)
        result = grader_with_state._check_pushed(
            "Changes were pushed to remote",
            diff,
            agent_output="",
            should_trigger=False,
        )
        assert not result.passed


class TestCheckPrCreated:
    def test_passes_when_new_pr_for_eval_branch(self, grader):
        diff = {
            "new_branches": ["feature/x"],
            "new_remote_branches": ["feature/x"],
            "current_branch": "feature/x",
            "current_branch_changed": True,
            "head_advanced": True,
            "new_commits": ["abc new"],
            "new_commit_shas": ["b" * 40],
            "new_open_prs": [
                {
                    "number": 42,
                    "headRefName": "feature/x",
                    "url": "x",
                    "state": "OPEN",
                }
            ],
            "eval_branch": "feature/x",
        }
        post = GitStateSnapshot(head_sha="b" * 40)
        grader_with_state = DeterministicGrader(post_state=post)
        result = grader_with_state._check_pr_created(
            "A pull request was created",
            diff,
            agent_output="",
            should_trigger=True,
        )
        assert result.passed
        assert "42" in result.evidence

    def test_fails_when_new_pr_targets_unrelated_branch(self, grader):
        """A new PR whose head ref does not match the eval branch must fail."""
        diff = {
            "new_branches": ["feature/eval-branch"],
            "new_remote_branches": [],
            "current_branch": "feature/eval-branch",
            "current_branch_changed": True,
            "head_advanced": True,
            "new_commits": ["abc new"],
            "new_commit_shas": ["b" * 40],
            "new_open_prs": [
                {
                    "number": 7,
                    "headRefName": "unrelated-branch",
                    "url": "x",
                    "state": "OPEN",
                }
            ],
            "eval_branch": "feature/eval-branch",
        }
        post = GitStateSnapshot(head_sha="b" * 40)
        grader_with_state = DeterministicGrader(post_state=post)
        result = grader_with_state._check_pr_created(
            "A pull request was created",
            diff,
            agent_output="",
            should_trigger=True,
        )
        assert not result.passed
        assert "feature/eval-branch" in result.evidence

    def test_fails_when_new_pr_but_no_eval_branch(self, grader):
        """If a new PR appears but no eval-created branch was identified
        (e.g. a PR from an external run leaked into the post-snapshot), the
        PR assertion must fail rather than falling through to a generic pass."""
        diff = {
            "new_branches": [],
            "new_remote_branches": [],
            "current_branch": "main",
            "current_branch_changed": False,
            "head_advanced": False,
            "new_commits": [],
            "new_commit_shas": [],
            "new_open_prs": [
                {
                    "number": 99,
                    "headRefName": "feature/something",
                    "state": "OPEN",
                }
            ],
            "eval_branch": None,
        }
        post = GitStateSnapshot(head_sha="a" * 40)
        grader_with_state = DeterministicGrader(post_state=post)
        result = grader_with_state._check_pr_created(
            "A pull request was created",
            diff,
            agent_output="",
            should_trigger=True,
        )
        assert not result.passed
        assert "no eval-created branch" in result.evidence

    def test_existing_pr_does_not_satisfy_pr_created(self, grader):
        """An existing PR at baseline must NOT satisfy 'PR created'."""
        diff = {
            "new_branches": [],
            "new_remote_branches": [],
            "current_branch": "main",
            "current_branch_changed": False,
            "head_advanced": False,
            "new_commits": [],
            "new_commit_shas": [],
            "new_open_prs": [],
            "eval_branch": None,
        }
        post = GitStateSnapshot(head_sha="a" * 40)
        grader_with_state = DeterministicGrader(post_state=post)
        result = grader_with_state._check_pr_created(
            "A pull request was created",
            diff,
            agent_output="I created a PR",
            should_trigger=True,
        )
        assert not result.passed

    def test_output_text_alone_does_not_pass(self, grader):
        """Agent saying 'I created a PR' is not enough without state evidence."""
        diff = {
            "new_branches": [],
            "new_remote_branches": [],
            "current_branch": "main",
            "current_branch_changed": False,
            "head_advanced": False,
            "new_commits": [],
            "new_commit_shas": [],
            "new_open_prs": [],
            "eval_branch": None,
        }
        post = GitStateSnapshot(head_sha="a" * 40)
        grader_with_state = DeterministicGrader(post_state=post)
        result = grader_with_state._check_pr_created(
            "A pull request was created",
            diff,
            agent_output="I successfully created a pull request at https://github.com/u/r/pull/99",
            should_trigger=True,
        )
        assert not result.passed
        assert "No new PRs" in result.evidence

    def test_fails_when_new_pr_is_closed(self, grader):
        """A new PR with matching headRefName but state=CLOSED must fail.

        Regression: ``gh pr list --state all`` returns OPEN, CLOSED, and
        MERGED PRs. Without a state filter, a closed/merged PR with the
        right headRefName would falsely satisfy the PR-created assertion.
        """
        diff = {
            "new_branches": ["feature/x"],
            "new_remote_branches": [],
            "current_branch": "feature/x",
            "current_branch_changed": True,
            "head_advanced": True,
            "new_commits": ["abc new"],
            "new_commit_shas": ["b" * 40],
            "new_open_prs": [
                {
                    "number": 11,
                    "headRefName": "feature/x",
                    "url": "x",
                    "state": "CLOSED",
                }
            ],
            "eval_branch": "feature/x",
        }
        post = GitStateSnapshot(head_sha="b" * 40)
        grader_with_state = DeterministicGrader(post_state=post)
        result = grader_with_state._check_pr_created(
            "A pull request was created",
            diff,
            agent_output="",
            should_trigger=True,
        )
        assert not result.passed
        assert "state OPEN" in result.evidence

    def test_fails_when_new_pr_is_merged(self, grader):
        """A new PR with state=MERGED must not satisfy the assertion."""
        diff = {
            "new_branches": ["feature/x"],
            "new_remote_branches": [],
            "current_branch": "feature/x",
            "current_branch_changed": True,
            "head_advanced": True,
            "new_commits": ["abc new"],
            "new_commit_shas": ["b" * 40],
            "new_open_prs": [
                {
                    "number": 12,
                    "headRefName": "feature/x",
                    "url": "x",
                    "state": "MERGED",
                }
            ],
            "eval_branch": "feature/x",
        }
        post = GitStateSnapshot(head_sha="b" * 40)
        grader_with_state = DeterministicGrader(post_state=post)
        result = grader_with_state._check_pr_created(
            "A pull request was created",
            diff,
            agent_output="",
            should_trigger=True,
        )
        assert not result.passed
        assert "state OPEN" in result.evidence

    def test_fails_when_new_pr_state_field_missing(self, grader):
        """A PR dict with no ``state`` field must be treated as not-open.

        This protects against partial/stale snapshots and against hand-rolled
        test fixtures that omit the state field by accident.
        """
        diff = {
            "new_branches": ["feature/x"],
            "new_remote_branches": [],
            "current_branch": "feature/x",
            "current_branch_changed": True,
            "head_advanced": True,
            "new_commits": ["abc new"],
            "new_commit_shas": ["b" * 40],
            "new_open_prs": [{"number": 13, "headRefName": "feature/x", "url": "x"}],
            "eval_branch": "feature/x",
        }
        post = GitStateSnapshot(head_sha="b" * 40)
        grader_with_state = DeterministicGrader(post_state=post)
        result = grader_with_state._check_pr_created(
            "A pull request was created",
            diff,
            agent_output="",
            should_trigger=True,
        )
        assert not result.passed
        assert "state OPEN" in result.evidence

    def test_negative_control_fails_when_pr_was_created(self, grader):
        diff = {
            "new_branches": ["feature/x"],
            "new_remote_branches": [],
            "current_branch": "feature/x",
            "current_branch_changed": True,
            "head_advanced": True,
            "new_commits": ["abc new"],
            "new_commit_shas": ["b" * 40],
            "new_open_prs": [{"number": 1, "headRefName": "feature/x", "state": "OPEN"}],
            "eval_branch": "feature/x",
        }
        post = GitStateSnapshot(head_sha="b" * 40)
        grader_with_state = DeterministicGrader(post_state=post)
        result = grader_with_state._check_pr_created(
            "A pull request was created",
            diff,
            agent_output="",
            should_trigger=False,
        )
        assert not result.passed
        assert "should not have triggered" in result.evidence

    def test_gh_pr_view_rescues_when_state_delta_empty(self, grader, tmp_path, monkeypatch):
        """When the state-delta shows no new PRs but gh pr view reports an
        open PR for the eval branch, the assertion should pass via the
        real-time corroboration path."""
        output_dir = tmp_path / "outputs"
        output_dir.mkdir()
        meta_path = output_dir.parent / "run_meta.json"
        meta_path.write_text(json.dumps({"source_repo": "https://github.com/owner/repo"}))

        monkeypatch.setattr(
            "skill_eval.graders._fetch_pr_for_branch",
            lambda branch, repo: (
                {
                    "number": 99,
                    "headRefName": branch,
                    "state": "OPEN",
                    "url": "x",
                }
                if branch == "feature/x" and "owner/repo" in repo
                else None
            ),
        )

        diff = {
            "new_branches": ["feature/x"],
            "new_remote_branches": [],
            "current_branch": "feature/x",
            "current_branch_changed": True,
            "head_advanced": True,
            "new_commits": ["abc new"],
            "new_commit_shas": ["b" * 40],
            "new_open_prs": [],
            "eval_branch": "feature/x",
        }
        post = GitStateSnapshot(head_sha="b" * 40)
        grader_with_state = DeterministicGrader(post_state=post)
        result = grader_with_state._check_pr_created(
            "A pull request was created",
            diff,
            agent_output="",
            should_trigger=True,
            output_dir=output_dir,
        )
        assert result.passed
        assert "gh pr view" in result.evidence

    def test_gh_pr_view_fails_assertion_when_pr_was_closed_since_snapshot(self, grader, tmp_path, monkeypatch):
        """If state-delta says the PR is open but gh pr view says it is now
        CLOSED/MERGED, the assertion must fail (the agent's PR was closed
        between snapshot and grading)."""
        output_dir = tmp_path / "outputs"
        output_dir.mkdir()
        meta_path = output_dir.parent / "run_meta.json"
        meta_path.write_text(json.dumps({"source_repo": "https://github.com/owner/repo"}))

        monkeypatch.setattr(
            "skill_eval.graders._fetch_pr_for_branch",
            lambda branch, repo: (
                {
                    "number": 99,
                    "headRefName": branch,
                    "state": "CLOSED",
                    "url": "x",
                }
                if branch == "feature/x" and "owner/repo" in repo
                else None
            ),
        )

        diff = {
            "new_branches": ["feature/x"],
            "new_remote_branches": [],
            "current_branch": "feature/x",
            "current_branch_changed": True,
            "head_advanced": True,
            "new_commits": ["abc new"],
            "new_commit_shas": ["b" * 40],
            "new_open_prs": [
                {
                    "number": 99,
                    "headRefName": "feature/x",
                    "url": "x",
                    "state": "OPEN",
                }
            ],
            "eval_branch": "feature/x",
        }
        post = GitStateSnapshot(head_sha="b" * 40)
        grader_with_state = DeterministicGrader(post_state=post)
        result = grader_with_state._check_pr_created(
            "A pull request was created",
            diff,
            agent_output="",
            should_trigger=True,
            output_dir=output_dir,
        )
        assert not result.passed
        assert "CLOSED" in result.evidence or "closed/merged" in result.evidence


class TestStateDeltaGradingIntegration:
    def test_grader_uses_state_deltas(self, tmp_path):
        """End-to-end: a branch created AFTER the pre-state snapshot should pass,
        but a pre-existing branch should not."""
        _init_git_workspace(tmp_path)
        pre = _snapshot(tmp_path)
        post = _snapshot(tmp_path)

        grader = DeterministicGrader(pre_state=pre, post_state=post)
        results = grader.grade(
            assertions=["A new git branch was created"],
            output_dir=tmp_path / "outputs",
            agent_output="",
            workspace=tmp_path,
        )
        assert not results[0].passed
