from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from skill_eval.cli import app

FIXTURES = Path(__file__).parent / "fixtures"


class TestSkillEvalCliSmoke:
    def test_run_report_and_init_with_fake_harness(self, tmp_path):
        runner = CliRunner()
        workspace = tmp_path / "workspace"
        skill = FIXTURES / "skills" / "format-json"
        evals = FIXTURES / "evals" / "format-json.json"

        run_result = runner.invoke(
            app,
            [
                "run",
                "--skill",
                str(skill),
                "--evals",
                str(evals),
                "--agent",
                "fake",
                "--workspace",
                str(workspace),
                "--grader-model",
                "",
                "--cleanup",
            ],
        )

        assert run_result.exit_code == 0, run_result.output

        iteration_dir = workspace / "format-json-workspace" / "iteration-1"
        assert (iteration_dir / "benchmark.json").exists()
        assert (iteration_dir / "cleanup.json").exists()

        benchmark = json.loads((iteration_dir / "benchmark.json").read_text())
        assert "fake_with_skill" in benchmark["run_summary"]
        assert "fake_without_skill" in benchmark["run_summary"]

        eval_ids = ["explicit-invoke", "negative-control", "content-contains"]
        for eval_id in eval_ids:
            for config in ["with_skill", "without_skill"]:
                config_dir = iteration_dir / f"eval-{eval_id}" / "fake" / config
                assert (config_dir / "grading.json").exists(), f"missing grading for {eval_id}/{config}"
                assert (config_dir / "run_meta.json").exists(), f"missing run_meta for {eval_id}/{config}"
                assert (config_dir / "timing.json").exists(), f"missing timing for {eval_id}/{config}"
                assert (config_dir / "outputs" / "output.txt").exists(), f"missing output for {eval_id}/{config}"
                assert (config_dir / "outputs" / "pre_state.json").exists()
                assert (config_dir / "outputs" / "post_state.json").exists()

        report_result = runner.invoke(
            app,
            [
                "report",
                "--workspace",
                str(workspace / "format-json-workspace"),
            ],
        )

        assert report_result.exit_code == 0, report_result.output
        assert "fake/with_skill" in report_result.output
        assert "fake/without_skill" in report_result.output

        # The rich table truncates long config names at narrow widths, so
        # assert the full names via the markdown format.
        md_result = runner.invoke(
            app,
            [
                "report",
                "--workspace",
                str(workspace / "format-json-workspace"),
                "--format",
                "markdown",
            ],
        )
        assert md_result.exit_code == 0, md_result.output
        assert "fake_with_skill" in md_result.output
        assert "fake_without_skill" in md_result.output

        init_output = tmp_path / "init-output"
        init_result = runner.invoke(app, ["init", "format-json", "--output", str(init_output)])

        assert init_result.exit_code == 0, init_result.output
        assert (init_output / "format-json" / "evals" / "evals.json").exists()
