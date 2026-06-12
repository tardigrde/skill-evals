"""Tests for the 2026-06-11 harness feedback batch: --eval-id case
filtering, per-case budget guards, live progress + progress.jsonl,
lifecycle hooks (pre-run / post-grade / post-run), summary.json + status,
unavailable-vs-zero cost semantics with --pricing-config, reasoning token
persistence, --reasoning-effort, and effective-model-config recording in
run_meta.json."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent_skill_eval import __version__
from agent_skill_eval.cli import app
from agent_skill_eval.harnesses import ClaudeCodeHarness, CodexHarness, OpenCodeHarness
from agent_skill_eval.models import AgentType, BudgetConfig, EvalSuite, TimingData
from agent_skill_eval.runner import compute_benchmark, compute_stats

FIXTURES = Path(__file__).parent / "fixtures"
SKILL = FIXTURES / "skills" / "format-json"
EVALS = FIXTURES / "evals" / "format-json.json"
ALL_EVAL_IDS = ["explicit-invoke", "negative-control", "content-contains"]


def _run_cli(workspace: Path, *extra: str):
    runner = CliRunner()
    return runner.invoke(
        app,
        [
            "run",
            "--skill",
            str(SKILL),
            "--evals",
            str(EVALS),
            "--agent",
            "fake",
            "--workspace",
            str(workspace),
            "--grader-model",
            "",
            "--no-baseline",
            *extra,
        ],
    )


def _iteration_dir(workspace: Path) -> Path:
    return workspace / "format-json-workspace" / "iteration-1"


def _suite(ids: list[str]) -> EvalSuite:
    return EvalSuite(
        skill_name="demo",
        evals=[{"id": i, "prompt": "p", "expected_output": "ok"} for i in ids],
    )


class TestEvalIdFiltering:
    def test_no_filter_returns_same_suite(self):
        suite = _suite(["a", "b"])
        assert suite.filtered_by_ids([]) is suite
        assert suite.filtered_by_ids(None) is suite

    def test_filter_selects_subset_preserving_order(self):
        suite = _suite(["a", "b", "c"])
        filtered = suite.filtered_by_ids(["c", "a"])
        assert [e.id for e in filtered.evals] == ["a", "c"]
        # The original suite is untouched.
        assert [e.id for e in suite.evals] == ["a", "b", "c"]

    def test_unknown_id_lists_available_ids(self):
        with pytest.raises(ValueError, match=r"Unknown eval id\(s\): nope.*Available eval ids: a, b"):
            _suite(["a", "b"]).filtered_by_ids(["nope"])

    def test_int_ids_match_string_filters(self):
        suite = _suite([1, 2])
        assert [e.id for e in suite.filtered_by_ids(["2"]).evals] == [2]

    def test_run_with_eval_id_only_runs_selected_cases(self, tmp_path):
        result = _run_cli(tmp_path, "--eval-id", "explicit-invoke")
        assert result.exit_code == 0, result.output

        iteration_dir = _iteration_dir(tmp_path)
        eval_dirs = sorted(p.name for p in iteration_dir.glob("eval-*"))
        assert eval_dirs == ["eval-explicit-invoke"]

        meta = json.loads((iteration_dir / "evals_meta.json").read_text())
        assert meta["selected_eval_ids"] == ["explicit-invoke"]
        assert [e["id"] for e in meta["evals"]] == ["explicit-invoke"]

        summary = json.loads((iteration_dir / "summary.json").read_text())
        assert summary["eval_ids"] == ["explicit-invoke"]

    def test_run_with_unknown_eval_id_fails_before_running(self, tmp_path):
        result = _run_cli(tmp_path, "--eval-id", "missing-case")
        assert result.exit_code == 1
        assert "Unknown eval id(s): missing-case" in result.output
        assert not _iteration_dir(tmp_path).exists()

    def test_validate_with_eval_id(self):
        runner = CliRunner()
        ok = runner.invoke(app, ["validate", str(EVALS), "--eval-id", "explicit-invoke"])
        assert ok.exit_code == 0, ok.output
        assert "1 eval(s)" in ok.output
        assert "selected by --eval-id" in ok.output

        bad = runner.invoke(app, ["validate", str(EVALS), "--eval-id", "missing-case"])
        assert bad.exit_code == 1
        assert "Unknown eval id(s): missing-case" in bad.output


class TestBudgetGuards:
    def test_violations(self):
        budget = BudgetConfig(max_total_tokens=100, max_duration_seconds=1.0, max_cost_usd=0.5)
        timing = TimingData(total_tokens=150, input_tokens=150, duration_ms=2000, cost_usd=1.0)
        problems = budget.violations(timing)
        assert len(problems) == 3

    def test_cost_limit_skipped_when_cost_unavailable(self):
        budget = BudgetConfig(max_cost_usd=0.5)
        assert budget.violations(TimingData(total_tokens=10, cost_usd=None)) == []

    def test_disabled_when_no_limits(self):
        assert not BudgetConfig().enabled
        assert BudgetConfig(max_total_tokens=1).enabled

    def test_budget_fail_adds_failed_assertion_and_marks_timing(self, tmp_path):
        # The fake harness reports 1 total token, so a 0-token budget trips.
        result = _run_cli(tmp_path, "--eval-id", "explicit-invoke", "--max-total-tokens-per-case", "0")
        assert result.exit_code == 0, result.output

        config_dir = _iteration_dir(tmp_path) / "eval-explicit-invoke" / "fake" / "with_skill"
        timing = json.loads((config_dir / "timing.json").read_text())
        assert timing["budget_exceeded"] is True
        assert "total tokens 1 > 0" in timing["budget_reason"]

        grading = json.loads((config_dir / "grading.json").read_text())
        budget_results = [a for a in grading["assertion_results"] if a["method"] == "budget"]
        assert len(budget_results) == 1
        assert budget_results[0]["passed"] is False
        assert grading["summary"]["failed"] >= 1

    def test_budget_warn_does_not_touch_grading(self, tmp_path):
        result = _run_cli(
            tmp_path,
            "--eval-id",
            "explicit-invoke",
            "--max-total-tokens-per-case",
            "0",
            "--budget-action",
            "warn",
        )
        assert result.exit_code == 0, result.output

        config_dir = _iteration_dir(tmp_path) / "eval-explicit-invoke" / "fake" / "with_skill"
        timing = json.loads((config_dir / "timing.json").read_text())
        assert timing["budget_exceeded"] is True
        grading = json.loads((config_dir / "grading.json").read_text())
        assert not [a for a in grading["assertion_results"] if a["method"] == "budget"]

    def test_stop_suite_skips_unstarted_runs(self, tmp_path):
        result = _run_cli(
            tmp_path,
            "--max-total-tokens-per-case",
            "0",
            "--budget-action",
            "stop-suite",
            "--concurrency",
            "1",
        )
        assert result.exit_code == 0, result.output

        summary = json.loads((_iteration_dir(tmp_path) / "summary.json").read_text())
        # First run completes (and trips the budget), the rest are skipped.
        assert summary["runs_completed"] == 1
        assert len(summary["skipped_runs"]) == len(ALL_EVAL_IDS) - 1
        assert summary["budget"]["exceeded_runs"]
        assert "stopped early by budget" in result.output

    def test_unknown_budget_action_rejected(self, tmp_path):
        result = _run_cli(tmp_path, "--budget-action", "explode")
        assert result.exit_code == 1
        assert "Unknown --budget-action" in result.output


class TestLifecycleHooks:
    def test_failing_pre_run_hook_aborts_before_any_case(self, tmp_path):
        result = _run_cli(tmp_path, "--pre-run-command", "echo setup broken >&2; exit 3")
        assert result.exit_code == 1
        assert "pre-run hook failed (exit 3)" in result.output
        assert "setup broken" in result.output
        assert not list(_iteration_dir(tmp_path).glob("eval-*"))

    def test_pre_run_hook_receives_ase_env(self, tmp_path):
        out_file = tmp_path / "hook-env.txt"
        result = _run_cli(
            tmp_path,
            "--eval-id",
            "explicit-invoke",
            "--pre-run-command",
            f'echo "$ASE_SKILL_NAME|$ASE_ITERATION|$ASE_EVAL_IDS" > {out_file}',
        )
        assert result.exit_code == 0, result.output
        assert out_file.read_text().strip() == "format-json|1|explicit-invoke"

    def test_post_grade_hook_merges_json_results_into_grading(self, tmp_path):
        hook_json = '[{"text": "remote MR exists", "passed": false, "evidence": "no MR found"}]'
        result = _run_cli(
            tmp_path,
            "--eval-id",
            "explicit-invoke",
            "--post-grade-command",
            f"echo '{hook_json}'",
        )
        assert result.exit_code == 0, result.output

        config_dir = _iteration_dir(tmp_path) / "eval-explicit-invoke" / "fake" / "with_skill"
        grading = json.loads((config_dir / "grading.json").read_text())
        hook_results = [a for a in grading["assertion_results"] if a["method"] == "hook"]
        assert len(hook_results) == 1
        assert hook_results[0]["text"] == "remote MR exists"
        assert hook_results[0]["passed"] is False
        assert grading["summary"]["total"] == len(grading["assertion_results"])
        assert (config_dir / "outputs" / "post_grade_hooks.json").exists()

    def test_failing_post_grade_hook_adds_failed_check(self, tmp_path):
        result = _run_cli(
            tmp_path,
            "--eval-id",
            "explicit-invoke",
            "--post-grade-command",
            "echo external grader crashed >&2; exit 7",
        )
        assert result.exit_code == 0, result.output

        config_dir = _iteration_dir(tmp_path) / "eval-explicit-invoke" / "fake" / "with_skill"
        grading = json.loads((config_dir / "grading.json").read_text())
        hook_results = [a for a in grading["assertion_results"] if a["method"] == "hook"]
        assert len(hook_results) == 1
        assert hook_results[0]["passed"] is False
        assert "exited 7" in hook_results[0]["evidence"]

    def test_post_grade_hook_can_read_run_artifacts(self, tmp_path):
        out_file = tmp_path / "post-grade-env.txt"
        result = _run_cli(
            tmp_path,
            "--eval-id",
            "explicit-invoke",
            "--post-grade-command",
            f'echo "$ASE_EVAL_ID|$ASE_AGENT|$ASE_WITH_SKILL" > {out_file}; test -f "$ASE_TIMING_PATH"',
        )
        assert result.exit_code == 0, result.output
        assert out_file.read_text().strip() == "explicit-invoke|fake|1"

    def test_failing_post_run_hook_does_not_fail_the_run(self, tmp_path):
        result = _run_cli(tmp_path, "--eval-id", "explicit-invoke", "--post-run-command", "exit 5")
        assert result.exit_code == 0, result.output

        summary = json.loads((_iteration_dir(tmp_path) / "summary.json").read_text())
        assert summary["hooks"]["post_run"][0]["exit_code"] == 5
        assert "post-run hook failed" in result.output


class TestProgressLog:
    def test_progress_jsonl_records_lifecycle_events(self, tmp_path):
        result = _run_cli(tmp_path, "--eval-id", "explicit-invoke")
        assert result.exit_code == 0, result.output

        progress_path = _iteration_dir(tmp_path) / "progress.jsonl"
        events = [json.loads(line) for line in progress_path.read_text().splitlines()]
        names = [e["event"] for e in events]
        for expected in ("suite_started", "run_started", "agent_started", "agent_finished", "run_finished"):
            assert expected in names, f"missing {expected} in {names}"
        assert names[-1] == "suite_finished"

        finished = next(e for e in events if e["event"] == "run_finished")
        assert finished["eval_id"] == "explicit-invoke"
        assert "pass_rate" in finished and "duration_s" in finished
        assert all("ts" in e and "elapsed_s" in e for e in events)


class TestSummaryAndStatus:
    def test_summary_json_contents(self, tmp_path):
        result = _run_cli(tmp_path)
        assert result.exit_code == 0, result.output

        summary = json.loads((_iteration_dir(tmp_path) / "summary.json").read_text())
        assert summary["skill_name"] == "format-json"
        assert summary["agents"] == ["fake"]
        assert sorted(summary["eval_ids"]) == sorted(ALL_EVAL_IDS)
        assert summary["runs_completed"] == len(ALL_EVAL_IDS)
        assert summary["tokens"]["total"] == len(ALL_EVAL_IDS)  # fake reports 1 token per run
        # The fake harness is known-free: cost is a real 0.0, not unavailable.
        assert summary["cost"]["total_usd"] == 0.0
        assert summary["cost"]["runs_with_cost"] == len(ALL_EVAL_IDS)
        assert "fake_with_skill" in summary["pass_rates"]

    def test_status_command_reads_summary(self, tmp_path):
        run_result = _run_cli(tmp_path)
        assert run_result.exit_code == 0, run_result.output

        runner = CliRunner()
        result = runner.invoke(app, ["status", "--workspace", str(tmp_path / "format-json-workspace")])
        assert result.exit_code == 0, result.output
        assert "iteration-1" in result.output
        assert "Pass rates" in result.output
        assert "cost:" in result.output

    def test_status_rebuilds_summary_for_old_runs(self, tmp_path):
        run_result = _run_cli(tmp_path)
        assert run_result.exit_code == 0, run_result.output
        (_iteration_dir(tmp_path) / "summary.json").unlink()

        runner = CliRunner()
        result = runner.invoke(app, ["status", "--workspace", str(tmp_path / "format-json-workspace")])
        assert result.exit_code == 0, result.output
        assert "rebuilt a reduced summary" in result.output
        assert "Pass rates" in result.output

    def test_status_without_iterations_fails_cleanly(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(app, ["status", "--workspace", str(tmp_path)])
        assert result.exit_code == 1
        assert "No iterations found" in result.output


class TestCostSemantics:
    def test_codex_cost_is_unavailable_not_zero(self, tmp_path):
        harness = CodexHarness(tmp_path)
        stdout = json.dumps(
            {"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 10, "cached_input_tokens": 60}}
        )
        _, timing = harness.parse_output(stdout, "")
        harness.finalize_timing(timing)
        assert timing.cost_usd is None
        assert timing.cost_usd_source is None

    def test_codex_pricing_config_computes_cost(self, tmp_path):
        pricing = {"gpt-test": {"prompt": 1e-6, "completion": 2e-6, "input_cache_read": 1e-7}}
        harness = CodexHarness(tmp_path, model="gpt-test", pricing=pricing)
        stdout = json.dumps(
            {"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 10, "cached_input_tokens": 60}}
        )
        _, timing = harness.parse_output(stdout, "")
        harness.finalize_timing(timing)
        # codex input_tokens INCLUDE cache reads: 40 non-cached + 60 cached.
        assert timing.cost_usd == pytest.approx(40 * 1e-6 + 60 * 1e-7 + 10 * 2e-6)
        assert timing.cost_usd_source == "pricing-config"

    def test_pricing_config_ignored_for_unknown_model(self, tmp_path):
        harness = CodexHarness(tmp_path, model="other-model", pricing={"gpt-test": {"prompt": 1e-6}})
        timing = TimingData(input_tokens=100, total_tokens=100)
        harness.finalize_timing(timing)
        assert timing.cost_usd is None

    def test_opencode_without_cost_fields_is_unavailable(self, tmp_path):
        harness = OpenCodeHarness(tmp_path)
        stdout = json.dumps({"type": "step_finish", "part": {"tokens": {"input": 10, "output": 2}}})
        _, timing = harness.parse_output(stdout, "")
        assert timing.cost_usd is None

    def test_opencode_zero_cost_step_is_real_zero(self, tmp_path):
        harness = OpenCodeHarness(tmp_path)
        stdout = json.dumps({"type": "step_finish", "part": {"cost": 0, "tokens": {"input": 10, "output": 2}}})
        _, timing = harness.parse_output(stdout, "")
        assert timing.cost_usd == 0.0

    def test_claude_missing_total_cost_is_unavailable(self, tmp_path):
        harness = ClaudeCodeHarness(tmp_path)
        stdout = json.dumps({"result": "done", "usage": {"input_tokens": 5}})
        _, timing = harness.parse_output(stdout, "")
        assert timing.cost_usd is None

    def test_claude_non_cached_input_excludes_nothing(self, tmp_path):
        # Anthropic usage reports input_tokens already excluding cache reads.
        harness = ClaudeCodeHarness(tmp_path)
        timing = TimingData(input_tokens=100, cached_tokens=60)
        assert harness.non_cached_input_tokens(timing) == 100
        assert CodexHarness(tmp_path).non_cached_input_tokens(timing) == 40

    def test_opencode_non_cached_input_excludes_nothing(self, tmp_path):
        # OpenCode also reports input_tokens excluding cache reads: live runs
        # consistently show cached > input (e.g. 12,481 input vs 93,184
        # cached), impossible if input contained the cache reads. The codex
        # subtraction would clamp this to a bogus 0.
        timing = TimingData(input_tokens=12481, cached_tokens=93184)
        assert OpenCodeHarness(tmp_path).non_cached_input_tokens(timing) == 12481

    def test_summary_cached_pct_uses_non_cached_plus_cached(self):
        from agent_skill_eval.summary import _token_totals

        # claude/opencode style: input excludes cache reads, so the cached
        # share is cached / (non_cached + cached), not the bogus 100% that
        # cached / max(input, cached) produced.
        totals = _token_totals(
            [{"input_tokens": 100, "cached_tokens": 300, "non_cached_input_tokens": 100, "total_tokens": 110}]
        )
        assert totals["cached_pct"] == pytest.approx(0.75)
        assert totals["non_cached_input"] == 100

    def test_compute_stats_cost_unavailable_when_no_run_reported(self):
        results = [
            {
                "eval_id": "e1",
                "agent": "codex",
                "with_skill": True,
                "grading": {"summary": {"pass_rate": 1.0, "total": 1}},
                "timing": {"duration_ms": 1000, "total_tokens": 100, "cost_usd": None},
            }
        ]
        stats = compute_stats(results)
        assert stats.cost_usd is None
        assert stats.cost_runs == 0

    def test_compute_stats_cost_means_only_reported_runs(self):
        def r(cost):
            return {
                "eval_id": "e1",
                "agent": "a",
                "with_skill": True,
                "grading": {"summary": {"pass_rate": 1.0, "total": 1}},
                "timing": {"duration_ms": 1000, "total_tokens": 100, "cost_usd": cost},
            }

        stats = compute_stats([r(0.5), r(None), r(1.5)])
        assert stats.cost_usd is not None
        assert stats.cost_usd.mean == pytest.approx(1.0)
        assert stats.cost_runs == 2

    def test_delta_cost_none_when_one_side_unavailable(self):
        def r(agent, with_skill, cost):
            return {
                "eval_id": "e1",
                "agent": agent,
                "with_skill": with_skill,
                "grading": {"summary": {"pass_rate": 1.0, "total": 1}},
                "timing": {"duration_ms": 1000, "total_tokens": 100, "cost_usd": cost},
            }

        results = {"a": r("codex", True, None), "b": r("codex", False, 0.5)}
        benchmark = compute_benchmark(results, [AgentType.CODEX], with_baseline=True)
        assert benchmark.deltas["codex"].cost_usd is None

    def test_report_renders_unavailable_cost_as_na(self, tmp_path):
        from agent_skill_eval.cli import _benchmark_rows

        benchmark = {
            "run_summary": {
                "codex_with_skill": {
                    "pass_rate": {"mean": 1.0, "stddev": 0.0},
                    "time_seconds": {"mean": 1.0, "stddev": 0.0},
                    "tokens": {"mean": 100.0, "stddev": 0.0},
                    "cost_usd": None,
                }
            }
        }
        rows = _benchmark_rows(benchmark)
        assert rows[0][-1] == "n/a"


class TestReasoningTokens:
    def test_codex_persists_reasoning_tokens_across_turns(self, tmp_path):
        harness = CodexHarness(tmp_path)
        events = [
            json.dumps(
                {
                    "type": "turn.completed",
                    "usage": {"input_tokens": 100, "output_tokens": 10, "reasoning_output_tokens": 200},
                }
            ),
            json.dumps(
                {
                    "type": "turn.completed",
                    "usage": {"input_tokens": 50, "output_tokens": 5, "reasoning_output_tokens": 47},
                }
            ),
        ]
        _, timing = harness.parse_output("\n".join(events), "")
        assert timing.reasoning_output_tokens == 247

    def test_codex_without_reasoning_telemetry_is_none_not_zero(self, tmp_path):
        harness = CodexHarness(tmp_path)
        stdout = json.dumps({"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 10}})
        _, timing = harness.parse_output(stdout, "")
        assert timing.reasoning_output_tokens is None

    def test_opencode_persists_reasoning_tokens(self, tmp_path):
        harness = OpenCodeHarness(tmp_path)
        stdout = json.dumps({"type": "step_finish", "part": {"tokens": {"input": 10, "output": 2, "reasoning": 30}}})
        _, timing = harness.parse_output(stdout, "")
        assert timing.reasoning_output_tokens == 30

    def test_opencode_without_reasoning_telemetry_is_none(self, tmp_path):
        harness = OpenCodeHarness(tmp_path)
        stdout = json.dumps({"type": "step_finish", "part": {"tokens": {"input": 10, "output": 2}}})
        _, timing = harness.parse_output(stdout, "")
        assert timing.reasoning_output_tokens is None

    def test_reasoning_budget_violation(self):
        budget = BudgetConfig(max_reasoning_tokens=100)
        timing = TimingData(reasoning_output_tokens=150)
        assert budget.violations(timing) == ["reasoning tokens 150 > 100"]

    def test_reasoning_budget_skipped_when_unreported(self):
        # Like cost: an agent that exposes no reasoning telemetry must not
        # fail a reasoning budget over an unknown quantity.
        budget = BudgetConfig(max_reasoning_tokens=100)
        assert budget.violations(TimingData(reasoning_output_tokens=None)) == []

    def test_non_cached_budget_violation_and_skip(self):
        budget = BudgetConfig(max_non_cached_input_tokens=10)
        assert budget.violations(TimingData(non_cached_input_tokens=25)) == ["non-cached input tokens 25 > 10"]
        assert budget.violations(TimingData(non_cached_input_tokens=None)) == []

    def test_summary_reasoning_total_none_when_unreported(self, tmp_path):
        result = _run_cli(tmp_path, "--eval-id", "explicit-invoke")
        assert result.exit_code == 0, result.output
        summary = json.loads((_iteration_dir(tmp_path) / "summary.json").read_text())
        # The fake agent reports no reasoning telemetry: unknown, not 0.
        assert summary["tokens"]["reasoning_output"] is None
        # The fake harness records its billable input split per run.
        assert summary["tokens"]["non_cached_input"] == 1


class TestModelConfigRecording:
    def test_run_meta_records_effective_config(self, tmp_path):
        result = _run_cli(tmp_path, "--eval-id", "explicit-invoke")
        assert result.exit_code == 0, result.output

        config_dir = _iteration_dir(tmp_path) / "eval-explicit-invoke" / "fake" / "with_skill"
        meta = json.loads((config_dir / "run_meta.json").read_text())
        assert meta["harness_version"] == __version__
        assert meta["model"] is None
        assert meta["reasoning_effort"] is None
        assert meta["base_url"] is None
        # The fake agent has no version command.
        assert meta["agent_cli_version"] is None

        timing = json.loads((config_dir / "timing.json").read_text())
        assert timing["non_cached_input_tokens"] == 1

    def test_codex_command_includes_reasoning_effort(self, tmp_path):
        harness = CodexHarness(tmp_path, reasoning_effort="medium")
        cmd = harness.build_command("fix it", tmp_path)
        assert "-c" in cmd
        assert 'model_reasoning_effort="medium"' in cmd

    def test_codex_command_omits_reasoning_effort_when_unset(self, tmp_path):
        cmd = CodexHarness(tmp_path).build_command("fix it", tmp_path)
        assert "-c" not in cmd

    def test_unsupported_harness_ignores_reasoning_effort(self, tmp_path):
        # claude-code/opencode have no pass-through flag: the effective value
        # is None and run_meta must not claim an effort that was never set.
        assert ClaudeCodeHarness(tmp_path, reasoning_effort="medium").reasoning_effort is None
        assert OpenCodeHarness(tmp_path, reasoning_effort="medium").reasoning_effort is None
        assert CodexHarness(tmp_path, reasoning_effort="medium").reasoning_effort == "medium"

    def test_run_warns_when_agent_ignores_reasoning_effort(self, tmp_path):
        result = _run_cli(tmp_path, "--eval-id", "explicit-invoke", "--reasoning-effort", "medium")
        assert result.exit_code == 0, result.output
        assert "--reasoning-effort is not supported by fake" in result.output

        config_dir = _iteration_dir(tmp_path) / "eval-explicit-invoke" / "fake" / "with_skill"
        meta = json.loads((config_dir / "run_meta.json").read_text())
        assert meta["reasoning_effort"] is None
