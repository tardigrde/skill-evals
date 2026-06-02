from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from skill_eval.models import AgentType, EvalCase
from skill_eval.runner import EvalRunner


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


def _init_workspace_with_changes(workspace: Path) -> tuple[Path, Path]:
    """Set up a workspace that has both a pre-state and a new branch+commit."""
    pre_ws = workspace
    pre_ws.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=pre_ws, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=pre_ws, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=pre_ws, capture_output=True, check=True)
    (pre_ws / "init.txt").write_text("hi")
    subprocess.run(["git", "add", "."], cwd=pre_ws, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=pre_ws, capture_output=True, check=True)
    return pre_ws, pre_ws


class TestPromptConstruction:
    def test_with_skill_does_not_prepend_skill_invocation(self, tmp_path, evals_path):
        skill_path = tmp_path / "skill"
        skill_path.mkdir()
        (skill_path / "SKILL.md").write_text(
            "---\nname: demo\ndescription: d\nlicense: MIT\ncompatibility: opencode\n---\nbody"
        )

        captured_prompts: list[str] = []

        class FakeHarness:
            agent_type = None

            def __init__(self, agent_type=None, workspace=None, model=None):
                pass

            def run(self, prompt, output_dir):
                captured_prompts.append(prompt)
                return "", type("T", (), {"model_dump": lambda self: {}})(), "", ""

        with patch("skill_eval.runner.get_harness", side_effect=FakeHarness):
            runner = EvalRunner(
                skill_path=skill_path,
                evals_path=evals_path,
                workspace_base=tmp_path / "ws",
                agents=[],
                with_baseline=False,
            )
            runner._run_single(
                EvalCase(id="implicit", prompt="Get this into a PR.", expected_output="ok"),
                agent_type=AgentType.OPENCODE,
                with_skill=True,
                iteration_dir=tmp_path / "iter",
            )

        assert captured_prompts == ["Get this into a PR."]

    def test_with_skill_prepends_when_force_skill_invocation(self, tmp_path, evals_path):
        skill_path = tmp_path / "skill"
        skill_path.mkdir()
        (skill_path / "SKILL.md").write_text(
            "---\nname: demo\ndescription: d\nlicense: MIT\ncompatibility: opencode\n---\nbody"
        )

        captured_prompts: list[str] = []

        class FakeHarness:
            agent_type = None

            def __init__(self, agent_type=None, workspace=None, model=None):
                pass

            def run(self, prompt, output_dir):
                captured_prompts.append(prompt)
                return "", type("T", (), {"model_dump": lambda self: {}})(), "", ""

        with patch("skill_eval.runner.get_harness", side_effect=FakeHarness):
            runner = EvalRunner(
                skill_path=skill_path,
                evals_path=evals_path,
                workspace_base=tmp_path / "ws",
                agents=[],
                with_baseline=False,
            )
            runner._run_single(
                EvalCase(
                    id="explicit",
                    prompt="Use the $demo skill to push this.",
                    expected_output="ok",
                    force_skill_invocation=True,
                ),
                agent_type=AgentType.OPENCODE,
                with_skill=True,
                iteration_dir=tmp_path / "iter",
            )

        assert captured_prompts == ["Use the $demo skill. Use the $demo skill to push this."]

    def test_without_skill_never_prepends(self, tmp_path, evals_path):
        skill_path = tmp_path / "skill"
        skill_path.mkdir()
        (skill_path / "SKILL.md").write_text(
            "---\nname: demo\ndescription: d\nlicense: MIT\ncompatibility: opencode\n---\nbody"
        )

        captured_prompts: list[str] = []

        class FakeHarness:
            agent_type = None

            def __init__(self, agent_type=None, workspace=None, model=None):
                pass

            def run(self, prompt, output_dir):
                captured_prompts.append(prompt)
                return "", type("T", (), {"model_dump": lambda self: {}})(), "", ""

        with patch("skill_eval.runner.get_harness", side_effect=FakeHarness):
            runner = EvalRunner(
                skill_path=skill_path,
                evals_path=evals_path,
                workspace_base=tmp_path / "ws",
                agents=[],
                with_baseline=False,
            )
            runner._run_single(
                EvalCase(id="implicit", prompt="Get this into a PR.", expected_output="ok"),
                agent_type=AgentType.OPENCODE,
                with_skill=False,
                iteration_dir=tmp_path / "iter",
            )

        assert captured_prompts == ["Get this into a PR."]


class TestStateCapture:
    def test_pre_and_post_state_files_written(self, tmp_path, evals_path):
        skill_path = tmp_path / "skill"
        skill_path.mkdir()
        (skill_path / "SKILL.md").write_text(
            "---\nname: demo\ndescription: d\nlicense: MIT\ncompatibility: opencode\n---\nbody"
        )

        class FakeHarness:
            agent_type = None

            def __init__(self, agent_type=None, workspace=None, model=None):
                self.workspace = workspace

            def run(self, prompt, output_dir):
                subprocess.run(
                    ["git", "checkout", "-b", "feature/agent-branch"],
                    cwd=self.workspace,
                    capture_output=True,
                    check=True,
                )
                (self.workspace / "x.txt").write_text("y")
                subprocess.run(["git", "add", "."], cwd=self.workspace, capture_output=True, check=True)
                subprocess.run(
                    ["git", "commit", "-m", "agent work"],
                    cwd=self.workspace,
                    capture_output=True,
                    check=True,
                )
                return (
                    "I did the work",
                    type(
                        "T",
                        (),
                        {
                            "model_dump": lambda self: {
                                "total_tokens": 0,
                                "input_tokens": 0,
                                "output_tokens": 0,
                                "cached_tokens": 0,
                                "duration_ms": 0,
                            }
                        },
                    )(),
                    "",
                    "",
                )

        with patch("skill_eval.runner.get_harness", side_effect=FakeHarness):
            runner = EvalRunner(
                skill_path=skill_path,
                evals_path=evals_path,
                workspace_base=tmp_path / "ws",
                agents=[],
                with_baseline=False,
            )
            runner._run_single(
                EvalCase(id="implicit", prompt="do it", expected_output="ok"),
                agent_type=AgentType.OPENCODE,
                with_skill=True,
                iteration_dir=tmp_path / "iter",
            )

        output_dir = tmp_path / "iter" / "eval-implicit" / "with_skill" / "outputs"
        assert (output_dir / "pre_state.json").exists()
        assert (output_dir / "post_state.json").exists()
        post = json.loads((output_dir / "post_state.json").read_text())
        assert "feature/agent-branch" in post["local_branches"]


class TestCleanupScope:
    def test_cleanup_only_targets_manifest_entries(self, tmp_path):
        from skill_eval.cli import _cleanup_manifest
        from skill_eval.models import CleanupManifest

        calls: list[list[str]] = []

        def fake_run(cmd, *args, **kwargs):
            calls.append(cmd)
            r = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            return r

        manifest = CleanupManifest(
            source_repo="https://github.com/foo/bar.git",
            source_repo_slug="foo/bar",
            branches=["feature/eval-1"],
            pr_numbers=[123],
        )

        with patch("subprocess.run", side_effect=fake_run):
            _cleanup_manifest(manifest, source_repo=manifest.source_repo)

        deleted_branches = [c for c in calls if "DELETE" in c]
        closed_prs = [c for c in calls if "pr" in c and "close" in c]
        assert any("feature/eval-1" in c[-1] for c in deleted_branches)
        assert any("123" in c for c in closed_prs)
        # Must NOT call "pr list" with --state open (the old broad cleanup)
        assert not any("pr" in c and "list" in c and "open" in c for c in calls)

    def test_cleanup_manifest_without_source_repo_is_safe(self, tmp_path):
        from skill_eval.cli import _cleanup_manifest
        from skill_eval.models import CleanupManifest

        calls: list[list[str]] = []

        def fake_run(cmd, *args, **kwargs):
            calls.append(cmd)
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        manifest = CleanupManifest(branches=["x"], pr_numbers=[1])
        _cleanup_manifest(manifest, source_repo=None)
        assert calls == [], f"Expected no subprocess calls without source repo, got {calls}"


class TestGradeCommand:
    def test_grade_persists_updated_grading(self, tmp_path, evals_path):
        from skill_eval.cli import grade

        skill_path = tmp_path / "skill"
        skill_path.mkdir()
        (skill_path / "SKILL.md").write_text(
            "---\nname: demo\ndescription: d\nlicense: MIT\ncompatibility: opencode\n---\nbody"
        )

        iter_dir = tmp_path / "iter"
        iter_dir.mkdir()
        eval_dir = iter_dir / "eval-implicit" / "with_skill" / "outputs"
        eval_dir.mkdir(parents=True)
        (eval_dir / "output.txt").write_text("I did it")
        (eval_dir / "pre_state.json").write_text(
            json.dumps(
                {
                    "local_branches": ["main"],
                    "remote_branches": [],
                    "current_branch": "main",
                    "head_sha": "a" * 40,
                    "commit_count": 1,
                    "commits": ["init"],
                    "remote_names": [],
                    "open_prs": [],
                }
            )
        )
        (eval_dir / "post_state.json").write_text(
            json.dumps(
                {
                    "local_branches": ["main", "feature/agent-branch"],
                    "remote_branches": ["feature/agent-branch"],
                    "current_branch": "feature/agent-branch",
                    "head_sha": "b" * 40,
                    "commit_count": 2,
                    "commits": ["init", "agent work"],
                    "remote_names": ["origin"],
                    "open_prs": [{"number": 7, "headRefName": "feature/agent-branch"}],
                }
            )
        )

        meta = {
            "skill_name": "demo",
            "evals": [
                {
                    "id": "implicit",
                    "prompt": "x",
                    "expected_output": "ok",
                    "assertions": [
                        "A new git branch was created",
                        "A git commit was created",
                        "A pull request was created",
                    ],
                }
            ],
            "source_repo": None,
        }
        (iter_dir / "evals_meta.json").write_text(json.dumps(meta))

        with patch("skill_eval.cli.LLMGrader") as MockLLM:
            MockLLM.side_effect = Exception("no key")
            grade(workspace=iter_dir, grader_model="x")

        grading = json.loads((iter_dir / "eval-implicit" / "with_skill" / "grading.json").read_text())
        assert grading["summary"]["total"] == 3
        assert grading["summary"]["passed"] >= 1

    def test_grade_uses_should_trigger_for_inversion(self, tmp_path, evals_path):
        from skill_eval.cli import grade

        skill_path = tmp_path / "skill"
        skill_path.mkdir()
        (skill_path / "SKILL.md").write_text(
            "---\nname: demo\ndescription: d\nlicense: MIT\ncompatibility: opencode\n---\nbody"
        )

        iter_dir = tmp_path / "iter"
        iter_dir.mkdir()
        eval_dir = iter_dir / "eval-negative" / "with_skill" / "outputs"
        eval_dir.mkdir(parents=True)
        (eval_dir / "output.txt").write_text("commit abc123 Initial commit")
        (eval_dir / "pre_state.json").write_text(
            json.dumps(
                {
                    "local_branches": ["main"],
                    "remote_branches": [],
                    "current_branch": "main",
                    "head_sha": "a" * 40,
                    "commit_count": 1,
                    "commits": ["init"],
                    "remote_names": [],
                    "open_prs": [],
                }
            )
        )
        (eval_dir / "post_state.json").write_text(
            json.dumps(
                {
                    "local_branches": ["main"],
                    "remote_branches": [],
                    "current_branch": "main",
                    "head_sha": "a" * 40,
                    "commit_count": 1,
                    "commits": ["init"],
                    "remote_names": [],
                    "open_prs": [],
                }
            )
        )

        meta = {
            "skill_name": "demo",
            "evals": [
                {
                    "id": "negative",
                    "prompt": "x",
                    "expected_output": "ok",
                    "should_trigger": False,
                    "assertions": [
                        "A new git branch was created",
                        "A git commit was created",
                    ],
                }
            ],
            "source_repo": None,
        }
        (iter_dir / "evals_meta.json").write_text(json.dumps(meta))

        with patch("skill_eval.cli.LLMGrader") as MockLLM:
            MockLLM.side_effect = Exception("no key")
            grade(workspace=iter_dir, grader_model="x")

        grading = json.loads((eval_dir.parent / "grading.json").read_text())
        # Both should pass because no artifacts were created (skill should not have triggered)
        assert grading["summary"]["passed"] == 2


class TestEvalsMetaPersistence:
    def test_run_saves_evals_meta(self, tmp_path, evals_path):
        skill_path = tmp_path / "skill"
        skill_path.mkdir()
        (skill_path / "SKILL.md").write_text(
            "---\nname: demo\ndescription: d\nlicense: MIT\ncompatibility: opencode\n---\nbody"
        )

        with patch("skill_eval.runner.get_harness") as mock_harness:
            mock_harness.return_value.run.return_value = (
                "ok",
                type(
                    "T",
                    (),
                    {
                        "model_dump": lambda self: {
                            "total_tokens": 0,
                            "input_tokens": 0,
                            "output_tokens": 0,
                            "cached_tokens": 0,
                            "duration_ms": 0,
                        }
                    },
                )(),
                "",
                "",
            )

            runner = EvalRunner(
                skill_path=skill_path,
                evals_path=evals_path,
                workspace_base=tmp_path / "ws",
                agents=[],
                with_baseline=False,
            )
            iter_dir = runner.run(iteration=1)

        meta_path = iter_dir / "evals_meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["skill_name"] == "demo"
        assert any(e["id"] == "implicit" for e in meta["evals"])
