from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from agent_skill_eval.graders import DeterministicGrader


def _init_git_workspace(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, capture_output=True, check=True)
    (path / "file.txt").write_text("hello")
    subprocess.run(["git", "add", "."], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=path, capture_output=True, check=True)


@pytest.fixture
def git_workspace(tmp_path):
    _init_git_workspace(tmp_path)
    return tmp_path


@pytest.fixture
def grader():
    return DeterministicGrader()


@pytest.fixture
def evals_path(tmp_path):
    p = tmp_path / "evals.json"
    p.write_text(
        json.dumps(
            {
                "skill_name": "demo",
                "evals": [
                    {
                        "id": "implicit",
                        "prompt": "Get this into a PR.",
                        "expected_output": "ok",
                        "assertions": ["A new git branch was created"],
                    },
                    {
                        "id": "explicit",
                        "prompt": "Use the $demo skill to push this.",
                        "expected_output": "ok",
                        "assertions": ["A new git branch was created"],
                        "force_skill_invocation": True,
                    },
                    {
                        "id": "negative",
                        "prompt": "Show git log.",
                        "expected_output": "ok",
                        "should_trigger": False,
                        "assertions": ["The output contains `commit`"],
                    },
                ],
            }
        )
    )
    return p
