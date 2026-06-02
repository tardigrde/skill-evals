from __future__ import annotations

import subprocess

import pytest

from skill_eval.graders import DeterministicGrader


@pytest.fixture
def grader():
    return DeterministicGrader()


@pytest.fixture
def git_workspace(tmp_path):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True, check=True)
    (tmp_path / "file.txt").write_text("hello")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=tmp_path, capture_output=True, check=True)
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
    def test_passes_when_feature_branch_exists(self, grader, git_workspace):
        subprocess.run(
            ["git", "checkout", "-b", "feature/test"],
            cwd=git_workspace,
            capture_output=True,
            check=True,
        )
        result = grader._check_git_branch(
            "A new git branch was created",
            git_workspace / "output",
            workspace=git_workspace,
        )
        assert result.passed

    def test_fails_when_only_main(self, grader, git_workspace):
        result = grader._check_git_branch(
            "A new git branch was created",
            git_workspace / "output",
            workspace=git_workspace,
        )
        assert not result.passed


class TestCheckGitCommit:
    def test_passes_when_multiple_commits(self, grader, git_workspace):
        (git_workspace / "file2.txt").write_text("new")
        subprocess.run(["git", "add", "."], cwd=git_workspace, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Second commit"],
            cwd=git_workspace,
            capture_output=True,
            check=True,
        )
        result = grader._check_git_commit(
            "A git commit was created",
            git_workspace / "output",
            workspace=git_workspace,
        )
        assert result.passed

    def test_fails_with_only_initial_commit(self, grader, git_workspace):
        result = grader._check_git_commit(
            "A git commit was created",
            git_workspace / "output",
            workspace=git_workspace,
        )
        assert not result.passed


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
    def test_passes_when_push_in_output(self, grader, tmp_path):
        result = grader._check_pushed(
            "Changes were pushed to remote",
            tmp_path / "output",
            "Pushed to origin/main",
        )
        assert result.passed

    def test_fails_when_no_push_evidence(self, grader, tmp_path):
        result = grader._check_pushed(
            "Changes were pushed to remote",
            tmp_path / "output",
            "Nothing happened",
        )
        assert not result.passed


class TestCheckPrCreated:
    def test_passes_when_pr_url_in_output(self, grader, tmp_path):
        result = grader._check_pr_created(
            "A pull request was created",
            tmp_path / "output",
            "PR created: https://github.com/user/repo/pull/1",
        )
        assert result.passed

    def test_passes_when_pull_request_in_output(self, grader, tmp_path):
        result = grader._check_pr_created(
            "A pull request was created",
            tmp_path / "output",
            "A pull request has been opened for your changes.",
        )
        assert result.passed

    def test_fails_when_no_pr_evidence(self, grader, tmp_path):
        result = grader._check_pr_created(
            "A pull request was created",
            tmp_path / "output",
            "Nothing happened",
        )
        assert not result.passed
