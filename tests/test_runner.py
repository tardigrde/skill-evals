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

        output_dir = tmp_path / "iter" / "eval-implicit" / "opencode" / "with_skill" / "outputs"
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
            remote_branches=["feature/eval-1"],
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

        manifest = CleanupManifest(remote_branches=["x"], pr_numbers=[1])
        _cleanup_manifest(manifest, source_repo=None)
        assert calls == [], f"Expected no subprocess calls without source repo, got {calls}"

    def test_cleanup_uses_remote_branch_delta_not_local(self, tmp_path):
        """A branch in local delta that ALSO existed in pre remote branches
        must NOT appear in the cleanup manifest."""
        from skill_eval.git_state import GitStateSnapshot
        from skill_eval.runner import EvalRunner

        skill_path = tmp_path / "skill"
        skill_path.mkdir()
        (skill_path / "SKILL.md").write_text(
            "---\nname: demo\ndescription: d\nlicense: MIT\ncompatibility: opencode\n---\nbody"
        )

        evals_p = tmp_path / "evals.json"
        evals_p.write_text(json.dumps({"skill_name": "demo", "evals": []}))

        runner = EvalRunner(
            skill_path=skill_path,
            evals_path=evals_p,
            workspace_base=tmp_path / "ws",
            agents=[],
            with_baseline=False,
        )

        pre = GitStateSnapshot(local_branches=[], remote_branches=["feature/shared"], current_branch="main")
        post = GitStateSnapshot(
            local_branches=["feature/shared"],
            remote_branches=["feature/shared"],
            current_branch="feature/shared",
        )
        entry = runner._build_cleanup_entry(
            pre_state=pre,
            post_state=post,
        )
        # Local delta has feature/shared, but it was in pre.remote_branches.
        # The cleanup manifest must NOT record it for remote deletion.
        assert entry.remote_branches == []

        pre2 = GitStateSnapshot(local_branches=[], remote_branches=[], current_branch="main")
        post2 = GitStateSnapshot(
            local_branches=["feature/eval-new"],
            remote_branches=["feature/eval-new"],
            current_branch="feature/eval-new",
        )
        entry2 = runner._build_cleanup_entry(
            pre_state=pre2,
            post_state=post2,
        )
        assert entry2.remote_branches == ["feature/eval-new"]


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
        eval_dir = iter_dir / "eval-implicit" / "opencode" / "with_skill" / "outputs"
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
                    "branch_heads": {"main": "a" * 40},
                    "remote_branch_heads": {},
                    "commit_shas": ["a" * 40],
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
                    "branch_heads": {"main": "a" * 40, "feature/agent-branch": "b" * 40},
                    "remote_branch_heads": {"feature/agent-branch": "b" * 40},
                    "commit_shas": ["a" * 40, "b" * 40],
                }
            )
        )
        (eval_dir.parent / "run_meta.json").write_text(
            json.dumps(
                {
                    "eval_id": "implicit",
                    "agent": "opencode",
                    "with_skill": True,
                    "iteration": 1,
                    "skill_name": "demo",
                    "source_repo": None,
                    "run_id": "abc12345",
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

        grading = json.loads((iter_dir / "eval-implicit" / "opencode" / "with_skill" / "grading.json").read_text())
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
        eval_dir = iter_dir / "eval-negative" / "opencode" / "with_skill" / "outputs"
        eval_dir.mkdir(parents=True)
        (eval_dir / "output.txt").write_text("commit abc123 Initial commit")
        baseline_state = {
            "local_branches": ["main"],
            "remote_branches": [],
            "current_branch": "main",
            "head_sha": "a" * 40,
            "commit_count": 1,
            "commits": ["init"],
            "remote_names": [],
            "open_prs": [],
            "branch_heads": {"main": "a" * 40},
            "remote_branch_heads": {},
            "commit_shas": ["a" * 40],
        }
        (eval_dir / "pre_state.json").write_text(json.dumps(baseline_state))
        (eval_dir / "post_state.json").write_text(json.dumps(baseline_state))
        (eval_dir.parent / "run_meta.json").write_text(
            json.dumps(
                {
                    "eval_id": "negative",
                    "agent": "opencode",
                    "with_skill": True,
                    "iteration": 1,
                    "skill_name": "demo",
                    "source_repo": None,
                    "run_id": "abc12345",
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

        grading = json.loads((iter_dir / "eval-negative" / "opencode" / "with_skill" / "grading.json").read_text())
        # Both should pass because no artifacts were created (skill should not have triggered)
        assert grading["summary"]["passed"] == 2

    def test_grade_recompute_benchmark_uses_run_meta(self, tmp_path, evals_path):
        """`grade --recompute-benchmark` should recover the real agent name from
        ``run_meta.json`` and produce benchmark.run_summary keyed by
        ``<agent>_with_skill`` / ``<agent>_without_skill``."""
        from skill_eval.cli import grade

        iter_dir = tmp_path / "iter"
        iter_dir.mkdir()

        baseline_state = {
            "local_branches": ["main"],
            "remote_branches": [],
            "current_branch": "main",
            "head_sha": "a" * 40,
            "commit_count": 1,
            "commits": ["init"],
            "remote_names": [],
            "open_prs": [],
            "branch_heads": {"main": "a" * 40},
            "remote_branch_heads": {},
            "commit_shas": ["a" * 40],
        }

        for agent in ("opencode", "claude-code"):
            for with_skill in (True, False):
                config = iter_dir / "eval-implicit" / agent / ("with_skill" if with_skill else "without_skill")
                (config / "outputs").mkdir(parents=True)
                (config / "outputs" / "output.txt").write_text("hi")
                (config / "outputs" / "pre_state.json").write_text(json.dumps(baseline_state))
                (config / "outputs" / "post_state.json").write_text(json.dumps(baseline_state))
                (config / "timing.json").write_text(
                    json.dumps(
                        {
                            "total_tokens": 0,
                            "input_tokens": 0,
                            "output_tokens": 0,
                            "cached_tokens": 0,
                            "duration_ms": 0,
                        }
                    )
                )
                (config / "grading.json").write_text(
                    json.dumps(
                        {
                            "assertion_results": [],
                            "summary": {"passed": 1, "failed": 0, "total": 1, "pass_rate": 1.0},
                        }
                    )
                )
                (config / "run_meta.json").write_text(
                    json.dumps(
                        {
                            "eval_id": "implicit",
                            "agent": agent,
                            "with_skill": with_skill,
                            "iteration": 1,
                            "skill_name": "demo",
                            "source_repo": None,
                            "run_id": "abc",
                        }
                    )
                )

        # Use a content-contains assertion so regrade produces a 1/1 result
        meta = {
            "skill_name": "demo",
            "evals": [
                {
                    "id": "implicit",
                    "prompt": "x",
                    "expected_output": "ok",
                    "assertions": ["The output contains `hi`"],
                }
            ],
            "source_repo": None,
        }
        (iter_dir / "evals_meta.json").write_text(json.dumps(meta))

        with patch("skill_eval.cli.LLMGrader") as MockLLM:
            MockLLM.side_effect = Exception("no key")
            grade(workspace=iter_dir, grader_model="x", recompute_benchmark=True)

        benchmark = json.loads((iter_dir / "benchmark.json").read_text())
        run_summary = benchmark.get("run_summary", {})
        # Both agents should have with_skill and without_skill entries
        assert "opencode_with_skill" in run_summary
        assert "opencode_without_skill" in run_summary
        assert "claude-code_with_skill" in run_summary
        assert "claude-code_without_skill" in run_summary
        # Pass rate should be 1.0 (the regrade finds `hi` in the output)
        assert run_summary["opencode_with_skill"]["pass_rate"]["mean"] == 1.0


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


class TestRunMetaPersistence:
    def test_run_writes_run_meta_per_config(self, tmp_path, evals_path):
        """Each config directory should have a run_meta.json describing it."""
        from skill_eval.runner import EvalRunner

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
                agents=[AgentType.OPENCODE],
                with_baseline=True,
            )
            iter_dir = runner.run(iteration=1)

        # Each eval has with_skill and without_skill
        for eval_dir in iter_dir.glob("eval-*"):
            for agent_dir in eval_dir.iterdir():
                for config_dir in agent_dir.iterdir():
                    meta_path = config_dir / "run_meta.json"
                    assert meta_path.exists(), f"missing {meta_path}"
                    meta = json.loads(meta_path.read_text())
                    assert meta["agent"] == "opencode"
                    assert meta["with_skill"] in (True, False)
                    assert meta["eval_id"]
                    assert meta["run_id"]


class TestAgentDirectoryLayout:
    def test_two_agents_produce_separate_output_dirs(self, tmp_path, evals_path):
        """Two agents running the same eval must produce separate config dirs."""
        from skill_eval.runner import EvalRunner

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
                agents=[AgentType.OPENCODE, AgentType.CLAUDE_CODE],
                with_baseline=False,
            )
            iter_dir = runner.run(iteration=1)

        implicit_dir = iter_dir / "eval-implicit"
        assert (implicit_dir / "opencode" / "with_skill").exists()
        assert (implicit_dir / "claude-code" / "with_skill").exists()
        # Each agent should have its own output.txt
        assert (implicit_dir / "opencode" / "with_skill" / "outputs" / "output.txt").exists()
        assert (implicit_dir / "claude-code" / "with_skill" / "outputs" / "output.txt").exists()


class TestCleanupWorkspaceScope:
    def test_cleanup_only_removes_manifest_workspaces(self, tmp_path):
        """Sibling skill-eval-* workspaces not in the manifest must NOT be deleted."""
        from skill_eval.cli import _cleanup_iteration
        from skill_eval.models import CleanupManifest

        iter_dir = tmp_path / "iter"
        iter_dir.mkdir()
        workspace_base = tmp_path / "ws"
        workspace_base.mkdir()

        # A workspace recorded in the manifest
        manifest_ws = workspace_base / "skill-eval-A"
        manifest_ws.mkdir()
        (manifest_ws / "file.txt").write_text("x")

        # A sibling workspace NOT in the manifest
        sibling_ws = workspace_base / "skill-eval-other"
        sibling_ws.mkdir()
        (sibling_ws / "file.txt").write_text("x")

        manifest = CleanupManifest(workspaces=[str(manifest_ws)])
        with open(iter_dir / "cleanup.json", "w") as f:
            json.dump(manifest.model_dump(), f)

        _cleanup_iteration(iter_dir, workspace_base)

        # Manifest workspace is removed
        assert not manifest_ws.exists()
        # Sibling workspace is preserved
        assert sibling_ws.exists()

    def test_cleanup_without_manifest_skips_workspace_deletion(self, tmp_path):
        """If cleanup.json is missing, _cleanup_iteration must NOT delete
        unrecorded workspaces under the workspace base."""
        from skill_eval.cli import _cleanup_iteration

        iter_dir = tmp_path / "iter"
        iter_dir.mkdir()
        workspace_base = tmp_path / "ws"
        workspace_base.mkdir()
        sibling_ws = workspace_base / "skill-eval-other"
        sibling_ws.mkdir()
        (sibling_ws / "file.txt").write_text("x")

        # No cleanup.json
        _cleanup_iteration(iter_dir, workspace_base)

        # Sibling workspace must be preserved
        assert sibling_ws.exists()


class TestExampleNegativeControl:
    def test_negative_control_has_inverted_assertions(self):
        """The example negative-control eval must include branch/commit/PR
        assertions so that inverted grading actually catches accidental
        triggering."""
        examples_dir = Path(__file__).parent.parent / "examples" / "commit-push-pr" / "evals"
        with open(examples_dir / "evals.json") as f:
            data = json.load(f)

        negative = next(e for e in data["evals"] if e["id"] == "negative-control")
        assert negative["should_trigger"] is False
        assertions = " ".join(negative["assertions"]).lower()
        assert "branch" in assertions, "negative-control must assert branch was not created"
        assert "commit" in assertions, "negative-control must assert commit was not created"
        assert "pull request" in assertions, "negative-control must assert PR was not created"
        assert "push" in assertions, "negative-control must assert push did not happen"
