from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from skill_eval.graders import DeterministicGrader
from skill_eval.models import GitStateSnapshot


def _init_git_workspace(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, capture_output=True, check=True)
    (path / "file.txt").write_text("hello")
    subprocess.run(["git", "add", "."], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=path, capture_output=True, check=True)


def _snapshot(ws: Path) -> GitStateSnapshot:
    from skill_eval.git_state import capture_git_state

    return capture_git_state(ws)


@pytest.fixture
def grader():
    return DeterministicGrader()


@pytest.fixture
def git_workspace(tmp_path):
    _init_git_workspace(tmp_path)
    return tmp_path


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


class TestCheckGitBranch:
    def test_passes_when_new_branch_appeared_in_state(self, grader, git_workspace):
        _ = _snapshot(git_workspace)
        subprocess.run(
            ["git", "checkout", "-b", "feature/test"],
            cwd=git_workspace,
            capture_output=True,
            check=True,
        )
        _ = _snapshot(git_workspace)
        diff = {
            "new_branches": ["feature/test"],
            "new_remote_branches": [],
            "current_branch_changed": True,
            "head_advanced": False,
            "new_commits": [],
            "new_open_prs": [],
        }
        result = grader._check_git_branch("A new git branch was created", diff, should_trigger=True)
        assert result.passed

    def test_fails_when_no_new_branch(self, grader):
        diff = {
            "new_branches": [],
            "new_remote_branches": [],
            "current_branch_changed": False,
            "head_advanced": False,
            "new_commits": [],
            "new_open_prs": [],
        }
        result = grader._check_git_branch("A new git branch was created", diff, should_trigger=True)
        assert not result.passed

    def test_negative_control_passes_when_no_new_branch(self, grader):
        diff = {
            "new_branches": [],
            "new_remote_branches": [],
            "current_branch_changed": False,
            "head_advanced": False,
            "new_commits": [],
            "new_open_prs": [],
        }
        result = grader._check_git_branch("A new git branch was created", diff, should_trigger=False)
        assert result.passed
        assert "did not trigger" in result.evidence

    def test_negative_control_fails_when_branch_was_created(self, grader):
        diff = {
            "new_branches": ["feature/unwanted"],
            "new_remote_branches": [],
            "current_branch_changed": True,
            "head_advanced": False,
            "new_commits": [],
            "new_open_prs": [],
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
            "current_branch_changed": False,
            "head_advanced": False,
            "new_commits": [],
            "new_open_prs": [],
        }
        result = grader._check_git_branch("A new git branch was created", diff, should_trigger=True)
        assert not result.passed


class TestCheckGitCommit:
    def test_passes_when_head_advanced(self, grader):
        diff = {
            "new_branches": [],
            "new_remote_branches": [],
            "current_branch_changed": False,
            "head_advanced": True,
            "new_commits": ["abc123 new commit"],
            "new_open_prs": [],
        }
        result = grader._check_git_commit("A git commit was created", diff, should_trigger=True)
        assert result.passed

    def test_fails_when_head_did_not_advance(self, grader):
        diff = {
            "new_branches": [],
            "new_remote_branches": [],
            "current_branch_changed": False,
            "head_advanced": False,
            "new_commits": [],
            "new_open_prs": [],
        }
        result = grader._check_git_commit("A git commit was created", diff, should_trigger=True)
        assert not result.passed

    def test_existing_commit_does_not_satisfy_new_commit_assertion(self, grader, git_workspace):
        """An existing commit at baseline must NOT satisfy 'new commit'."""
        diff = {
            "new_branches": [],
            "new_remote_branches": [],
            "current_branch_changed": False,
            "head_advanced": False,
            "new_commits": [],
            "new_open_prs": [],
        }
        result = grader._check_git_commit("A git commit was created", diff, should_trigger=True)
        assert not result.passed

    def test_negative_control_fails_when_head_advanced(self, grader):
        diff = {
            "new_branches": [],
            "new_remote_branches": [],
            "current_branch_changed": False,
            "head_advanced": True,
            "new_commits": ["abc123 new commit"],
            "new_open_prs": [],
        }
        result = grader._check_git_commit("A git commit was created", diff, should_trigger=False)
        assert not result.passed
        assert "should not have triggered" in result.evidence

    def test_negative_control_passes_when_no_commit(self, grader):
        diff = {
            "new_branches": [],
            "new_remote_branches": [],
            "current_branch_changed": False,
            "head_advanced": False,
            "new_commits": [],
            "new_open_prs": [],
        }
        result = grader._check_git_commit("A git commit was created", diff, should_trigger=False)
        assert result.passed


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
    def test_passes_when_new_remote_branch_appeared(self, grader):
        diff = {
            "new_branches": ["feature/x"],
            "new_remote_branches": ["feature/x"],
            "current_branch_changed": True,
            "head_advanced": True,
            "new_commits": ["abc new"],
            "new_open_prs": [],
        }
        result = grader._check_pushed(
            "Changes were pushed to remote",
            diff,
            agent_output="",
            should_trigger=True,
        )
        assert result.passed

    def test_existing_remote_refs_do_not_satisfy_pushed(self, grader):
        """Existing remote refs at baseline must NOT satisfy 'pushed'."""
        diff = {
            "new_branches": [],
            "new_remote_branches": [],
            "current_branch_changed": False,
            "head_advanced": False,
            "new_commits": [],
            "new_open_prs": [],
        }
        result = grader._check_pushed(
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
            "current_branch_changed": False,
            "head_advanced": False,
            "new_commits": [],
            "new_open_prs": [],
        }
        result = grader._check_pushed(
            "Changes were pushed to remote",
            diff,
            agent_output="I successfully pushed to origin/main",
            should_trigger=True,
        )
        assert not result.passed
        assert "No new remote branches" in result.evidence

    def test_negative_control_fails_when_pushed(self, grader):
        diff = {
            "new_branches": ["feature/x"],
            "new_remote_branches": ["feature/x"],
            "current_branch_changed": True,
            "head_advanced": True,
            "new_commits": ["abc new"],
            "new_open_prs": [],
        }
        result = grader._check_pushed(
            "Changes were pushed to remote",
            diff,
            agent_output="",
            should_trigger=False,
        )
        assert not result.passed


class TestCheckPrCreated:
    def test_passes_when_new_pr_appeared(self, grader):
        diff = {
            "new_branches": ["feature/x"],
            "new_remote_branches": ["feature/x"],
            "current_branch_changed": True,
            "head_advanced": True,
            "new_commits": ["abc new"],
            "new_open_prs": [{"number": 42, "headRefName": "feature/x", "url": "x"}],
        }
        result = grader._check_pr_created(
            "A pull request was created",
            diff,
            agent_output="",
            should_trigger=True,
        )
        assert result.passed
        assert "42" in result.evidence

    def test_existing_pr_does_not_satisfy_pr_created(self, grader):
        """An existing PR at baseline must NOT satisfy 'PR created'."""
        diff = {
            "new_branches": [],
            "new_remote_branches": [],
            "current_branch_changed": False,
            "head_advanced": False,
            "new_commits": [],
            "new_open_prs": [],
        }
        result = grader._check_pr_created(
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
            "current_branch_changed": False,
            "head_advanced": False,
            "new_commits": [],
            "new_open_prs": [],
        }
        result = grader._check_pr_created(
            "A pull request was created",
            diff,
            agent_output="I successfully created a pull request at https://github.com/u/r/pull/99",
            should_trigger=True,
        )
        assert not result.passed
        assert "No new PRs" in result.evidence

    def test_negative_control_fails_when_pr_was_created(self, grader):
        diff = {
            "new_branches": ["feature/x"],
            "new_remote_branches": [],
            "current_branch_changed": True,
            "head_advanced": True,
            "new_commits": ["abc new"],
            "new_open_prs": [{"number": 1, "headRefName": "feature/x"}],
        }
        result = grader._check_pr_created(
            "A pull request was created",
            diff,
            agent_output="",
            should_trigger=False,
        )
        assert not result.passed
        assert "should not have triggered" in result.evidence


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
