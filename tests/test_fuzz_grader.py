from __future__ import annotations

import random
import string

from skill_eval.graders import DeterministicGrader
from skill_eval.models import AssertionResult, GitStateSnapshot

random.seed(0)


def test_fuzz_check_assertion_never_crashes(tmp_path):
    """Garbage input must never crash _check_assertion."""
    grader = DeterministicGrader()

    for _ in range(500):
        length = random.randint(0, 100)
        garbage_str = "".join(random.choice(string.printable) for _ in range(length))
        res = grader._check_assertion(
            assertion=garbage_str,
            output_dir=tmp_path,
            agent_output="output",
            workspace=tmp_path,
            should_trigger=True,
            diff={},
        )
        assert isinstance(res, AssertionResult)
        assert isinstance(res.text, str)
        assert isinstance(res.passed, bool)
        assert isinstance(res.evidence, str)


def test_routing_branch_to_git_branch_handler():
    """Assertions about branches route to _check_git_branch."""
    grader = DeterministicGrader()
    diff = {"new_branches": ["feature"], "eval_branch": "feature", "current_branch": "feature"}

    res = grader._check_assertion("A new branch was created", None, "out", None, True, diff)
    assert res.passed is True
    assert "feature" in res.evidence


def test_routing_commit_to_git_commit_handler():
    """Assertions about commits route to _check_git_commit."""
    post = GitStateSnapshot(head_sha="b" * 40, commit_shas=["a" * 40, "b" * 40])
    grader = DeterministicGrader(post_state=post)
    diff = {"head_advanced": True, "new_commits": ["fix bug"], "new_commit_shas": ["b" * 40]}

    res = grader._check_assertion("A new commit was created", None, "out", None, True, diff)
    assert res.passed is True
    assert "New commit on current branch" in res.evidence


def test_routing_pushed_to_pushed_handler():
    """Assertions about pushing route to _check_pushed."""
    grader = DeterministicGrader()
    diff = {
        "eval_branch": "feature",
        "eval_branch_pushed": True,
        "eval_branch_pushed_matches_head": True,
        "new_remote_branches": ["origin/feature"],
    }

    res = grader._check_assertion("Pushed the branch to remote", None, "out", None, True, diff)
    assert res.passed is True
    assert "feature" in res.evidence


def test_routing_pr_to_pr_handler(tmp_path):
    """Assertions about PRs route to _check_pr_created."""
    grader = DeterministicGrader()
    diff = {
        "new_open_prs": [{"number": 42, "state": "OPEN", "headRefName": "feature"}],
        "eval_branch": "feature",
    }

    res = grader._check_assertion("A pull request was created", tmp_path, "out", tmp_path, True, diff)
    assert res.passed is True
    assert "42" in res.evidence


def test_routing_file_exists_to_file_handler(tmp_path):
    """Assertions about file creation route to _check_file_exists."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "output.txt").write_text("done")
    output_dir = ws / "with_skill" / "test"
    output_dir.mkdir(parents=True)

    grader = DeterministicGrader()
    res = grader._check_assertion("A file exists at output.txt", output_dir, "out", ws, True, {})
    assert res.passed is True
    assert "output.txt" in res.evidence


def test_routing_command_ran_to_command_handler(tmp_path):
    """Assertions about commands running route to _check_command_ran."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "stdout.log").write_text("Running npm install...")

    grader = DeterministicGrader()
    res = grader._check_assertion("Verify npm command ran", output_dir, "out", tmp_path, True, {})
    assert res.passed is True
    assert "npm" in res.evidence


def test_routing_contains_to_content_handler():
    """Assertions about content containing text route to _check_content_contains."""
    grader = DeterministicGrader()

    res = grader._check_assertion('The output contains "hello"', None, "hello world", None, True, {})
    assert res.passed is True
    assert "hello" in res.evidence


def test_routing_valid_json_to_json_handler():
    """Assertions about valid JSON route to _check_valid_json."""
    grader = DeterministicGrader()

    res = grader._check_assertion("The output is valid json", None, '{"key": "value"}', None, True, {})
    assert res.passed is True
    assert "valid JSON" in res.evidence


def test_unrecognized_assertion_returns_undetermined():
    """Assertions that match no handler return 'Could not deterministically check'."""
    grader = DeterministicGrader()

    res = grader._check_assertion("Something completely unknown", None, "out", None, True, {})
    assert res.passed is False
    assert "Could not deterministically check" in res.evidence
