"""End-to-end pipeline tests.

These exercise the real CLI (``agent-skill-eval run`` / ``agent-skill-eval report``) as a
subprocess — the same path ``make cheap-eval`` takes — rather than calling
internals, so they catch wiring problems unit tests cannot (CLI arg parsing,
workspace layout, artifact serialization, report aggregation).

Two tiers:

* Free tier (default, runs in ``make test`` / CI): fake harness only, no
  network, no API keys.
* Live tier (``make test-live``): real agent CLIs (claude-code, opencode,
  codex) plus the LLM grader. Locks in the "every harness completes with real
  output and real grades" milestone. Requires ASE_LIVE=1, OpenRouter
  routing env vars, opencode Zen auth, and ~/.codex auth. Costs real (small)
  money, so it is opt-in via the ``live`` pytest marker.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "skills" / "fix-failing-tests"
EVALS = REPO_ROOT / "examples" / "fix-failing-tests" / "evals" / "evals.json"

# Eval ids in EVALS where the skill should trigger and fix the bugs.
POSITIVE_EVALS = ["explicit-invoke", "implicit-invoke", "contextual-invoke"]
ALL_EVALS = POSITIVE_EVALS + ["negative-control"]

LIVE_AGENTS = ["claude-code", "opencode", "codex"]


def _run_cli(args: list[str], timeout: int = 1800) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "agent_skill_eval", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _iteration_dir(workspace: Path) -> Path:
    return workspace / "fix-failing-tests-workspace" / "iteration-1"


def _load(path: Path) -> dict:
    assert path.is_file(), f"missing artifact: {path}"
    return json.loads(path.read_text())


def _assert_run_artifacts(run_dir: Path, min_tokens: int) -> dict:
    """Assert one (eval, agent, config) run dir is complete; return grading."""
    timing = _load(run_dir / "timing.json")
    assert timing["exit_code"] == 0, f"{run_dir}: agent exit code {timing['exit_code']}"
    assert not timing["timed_out"], f"{run_dir}: agent timed out"
    assert timing["total_tokens"] >= min_tokens, f"{run_dir}: tokens {timing['total_tokens']} < {min_tokens}"
    assert "cost_usd" in timing, f"{run_dir}: timing.json missing cost_usd"

    output = run_dir / "outputs" / "output.txt"
    assert output.is_file() and output.read_text().strip(), f"{run_dir}: empty or missing output.txt"

    grading = _load(run_dir / "grading.json")
    assert grading["summary"]["total"] > 0, f"{run_dir}: no assertions graded"
    return grading


class TestFakePipelineE2E:
    """Free, network-less full-pipeline run. Guards the CLI -> runner ->
    artifacts -> report chain on every `make test`."""

    @pytest.fixture(scope="class")
    def fake_run(self, tmp_path_factory):
        workspace = tmp_path_factory.mktemp("e2e-fake-ws")
        result = _run_cli(
            [
                "run",
                "--skill",
                str(SKILL),
                "--evals",
                str(EVALS),
                "--agent",
                "fake",
                "--grader-model",
                "",
                "--workspace",
                str(workspace),
                "--concurrency",
                "1",
                "--no-baseline",
            ],
            timeout=300,
        )
        return workspace, result

    def test_run_exits_zero(self, fake_run):
        _, result = fake_run
        assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"

    def test_every_eval_produces_complete_artifacts(self, fake_run):
        workspace, result = fake_run
        assert result.returncode == 0
        for eval_id in ALL_EVALS:
            run_dir = _iteration_dir(workspace) / f"eval-{eval_id}" / "fake" / "with_skill"
            _assert_run_artifacts(run_dir, min_tokens=1)

    def test_report_renders(self, fake_run):
        workspace, result = fake_run
        assert result.returncode == 0
        report = _run_cli(
            ["report", "--workspace", str(workspace / "fix-failing-tests-workspace")],
            timeout=120,
        )
        assert report.returncode == 0, report.stderr
        assert "fake" in report.stdout


def _live_preflight() -> str | None:
    """Return a skip reason if the live environment is not set up."""
    if os.environ.get("ASE_LIVE") != "1":
        return "ASE_LIVE != 1 (use `make test-live`)"
    if not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return "ANTHROPIC_AUTH_TOKEN not set (OpenRouter routing for claude-code)"
    for cli in ("claude", "opencode", "codex"):
        if shutil.which(cli) is None:
            return f"{cli} CLI not on PATH"
    return None


@pytest.mark.live
class TestLiveAgentsE2E:
    """Paid milestone lock: every real harness completes the suite with real
    model output and the LLM grader produces real (non-skipped) grades."""

    # Conservative floor: current baseline is ~92% per agent; negative-control
    # has one known-strict assertion, so 0.7 mean still catches regressions
    # (a broken harness or skipped grader lands at 0).
    MIN_MEAN_PASS_RATE = 0.7
    GRADER_MODEL = os.environ.get("GRADER_MODEL", "deepseek/deepseek-v4-flash")

    @pytest.fixture(scope="class")
    def live_run(self, tmp_path_factory):
        reason = _live_preflight()
        if reason:
            pytest.skip(reason)
        workspace = tmp_path_factory.mktemp("e2e-live-ws")
        args = [
            "run",
            "--skill",
            str(SKILL),
            "--evals",
            str(EVALS),
            "--grader-model",
            self.GRADER_MODEL,
            "--workspace",
            str(workspace),
            "--concurrency",
            "3",
            "--no-baseline",
        ]
        for agent in LIVE_AGENTS:
            args += ["--agent", agent]
        for spec in (
            f"claude-code={os.environ.get('CLAUDE_CODE_MODEL', 'claude-haiku-4-5-20251001')}",
            f"opencode={os.environ.get('OPENCODE_MODEL', 'opencode/deepseek-v4-flash-free')}",
            f"codex={os.environ.get('CODEX_MODEL', 'gpt-5.4-mini')}",
        ):
            args += ["--agent-model", spec]
        result = _run_cli(args, timeout=1800)
        return workspace, result

    def test_run_exits_zero(self, live_run):
        _, result = live_run
        assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"

    @pytest.mark.parametrize("agent", LIVE_AGENTS)
    def test_agent_completes_with_real_output_and_grades(self, live_run, agent):
        workspace, result = live_run
        assert result.returncode == 0
        pass_rates = []
        for eval_id in ALL_EVALS:
            run_dir = _iteration_dir(workspace) / f"eval-{eval_id}" / agent / "with_skill"
            # Real models burn well over 100 tokens on these evals; the fake
            # harness reports 1. This catches silently-dead model routing.
            grading = _assert_run_artifacts(run_dir, min_tokens=100)
            skipped = [a["text"] for a in grading["assertion_results"] if a.get("skipped")]
            assert not skipped, f"{agent}/{eval_id}: grader skipped assertions: {skipped}"
            pass_rates.append(grading["summary"]["pass_rate"])
        mean = sum(pass_rates) / len(pass_rates)
        assert mean >= self.MIN_MEAN_PASS_RATE, f"{agent}: mean pass rate {mean:.2f} (per-eval: {pass_rates})"

    @pytest.mark.parametrize("agent", LIVE_AGENTS)
    def test_agent_fully_passes_at_least_one_positive_eval(self, live_run, agent):
        workspace, result = live_run
        assert result.returncode == 0
        full_passes = 0
        for eval_id in POSITIVE_EVALS:
            run_dir = _iteration_dir(workspace) / f"eval-{eval_id}" / agent / "with_skill"
            summary = _load(run_dir / "grading.json")["summary"]
            if summary["pass_rate"] == 1.0:
                full_passes += 1
        assert full_passes >= 1, f"{agent}: no positive eval fully passed"
