from __future__ import annotations

import json
import os
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

from skill_eval.graders import LLMGrader, grade_assertions
from skill_eval.harnesses import get_harness
from skill_eval.models import (
    AgentType,
    BenchmarkResult,
    BenchmarkStats,
    DeltaStats,
    EvalCase,
    EvalSuite,
    StatsPair,
)
from skill_eval.skills import SkillInstaller
from skill_eval.workspace import WorkspaceManager

console = Console()


class EvalRunner:
    def __init__(
        self,
        skill_path: Path,
        evals_path: Path,
        workspace_base: Path,
        agents: list[AgentType],
        concurrency: int = 1,
        with_baseline: bool = True,
        grader_model: str = "deepseek/deepseek-v4-flash",
        grader_base_url: Optional[str] = None,
        agent_models: Optional[dict[AgentType, str]] = None,
        source_repo: Optional[str] = None,
    ):
        self.skill_path = skill_path
        self.evals_path = evals_path
        self.workspace_base = workspace_base
        self.agents = agents
        self.concurrency = concurrency
        self.with_baseline = with_baseline
        self.grader_model = grader_model
        self.grader_base_url = grader_base_url
        self.agent_models = agent_models or {}
        self.source_repo = source_repo

        self.suite = self._load_suite()
        self.skill_installer = SkillInstaller(skill_path)
        self.workspace_mgr = WorkspaceManager(workspace_base, source_repo=source_repo)
        self.llm_grader = LLMGrader(model=grader_model, base_url=grader_base_url) if grader_model else None

    def _load_suite(self) -> EvalSuite:
        with open(self.evals_path) as f:
            data = json.load(f)
        return EvalSuite(**data)

    def run(self, iteration: int = 1) -> Path:
        iteration_dir = self.workspace_base / f"{self.suite.skill_name}-workspace" / f"iteration-{iteration}"
        iteration_dir.mkdir(parents=True, exist_ok=True)

        tasks = []
        for eval_case in self.suite.evals:
            for agent_type in self.agents:
                tasks.append((eval_case, agent_type, True))
                if self.with_baseline:
                    tasks.append((eval_case, agent_type, False))

        results: dict[str, dict] = {}

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task_id = progress.add_task("Running evals...", total=len(tasks))

            with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
                futures = {}
                for eval_case, agent_type, with_skill in tasks:
                    future = executor.submit(
                        self._run_single,
                        eval_case,
                        agent_type,
                        with_skill,
                        iteration_dir,
                    )
                    futures[future] = (eval_case, agent_type, with_skill)

                for future in as_completed(futures):
                    eval_case, agent_type, with_skill = futures[future]
                    key = f"{eval_case.id}-{agent_type.value}-{'with' if with_skill else 'without'}"
                    try:
                        results[key] = future.result()
                    except Exception as e:
                        console.print(f"[red]Error running {key}: {e}[/red]")
                        results[key] = {"error": str(e)}
                    progress.advance(task_id)

        benchmark = self._compute_benchmark(results, iteration_dir)

        with open(iteration_dir / "benchmark.json", "w") as f:
            json.dump(benchmark.model_dump(), f, indent=2)

        console.print(f"\n[green]Results saved to {iteration_dir}[/green]")
        return iteration_dir

    def _run_single(
        self,
        eval_case: EvalCase,
        agent_type: AgentType,
        with_skill: bool,
        iteration_dir: Path,
    ) -> dict:
        eval_slug = f"eval-{eval_case.id}"
        config_slug = "with_skill" if with_skill else "without_skill"
        output_dir = iteration_dir / eval_slug / config_slug / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)

        fixture_files = {}
        for file_path in eval_case.files:
            src = self.evals_path.parent / file_path
            if src.exists():
                fixture_files[Path(file_path).name] = src

        workspace = self.workspace_mgr.create_workspace(
            f"{eval_case.id}-{agent_type.value}-{'ws' if with_skill else 'bs'}",
            fixture_files,
        )

        if with_skill:
            self.skill_installer.install(workspace, agent_type)

        model = self.agent_models.get(agent_type)
        harness = get_harness(agent_type, workspace, model)

        prompt = eval_case.prompt
        if with_skill:
            prompt = f"Use the ${self.suite.skill_name} skill. {prompt}"

        agent_output, timing, stdout, stderr = harness.run(prompt, output_dir)

        with open(output_dir / "output.txt", "w") as f:
            f.write(agent_output)

        timing_path = output_dir.parent / "timing.json"
        with open(timing_path, "w") as f:
            json.dump(timing.model_dump(), f, indent=2)

        grading = grade_assertions(
            eval_case.assertions,
            agent_output,
            output_dir,
            eval_case.expected_output,
            self.llm_grader,
            workspace=workspace,
        )

        grading_path = output_dir.parent / "grading.json"
        with open(grading_path, "w") as f:
            json.dump(grading.model_dump(), f, indent=2)

        if os.environ.get("SKILL_EVAL_KEEP_WORKSPACE"):
            console.print(f"  [dim]Workspace kept: {workspace}[/dim]")
        else:
            self.workspace_mgr.cleanup(workspace)

        return {
            "eval_id": eval_case.id,
            "agent": agent_type.value,
            "with_skill": with_skill,
            "timing": timing.model_dump(),
            "grading": grading.model_dump(),
            "agent_output": agent_output[:2000],
        }

    def _compute_benchmark(self, results: dict[str, dict], iteration_dir: Path) -> BenchmarkResult:
        run_summary = {}

        for agent_type in self.agents:
            with_results = [
                r
                for k, r in results.items()
                if r.get("agent") == agent_type.value and r.get("with_skill") and "error" not in r
            ]
            without_results = [
                r
                for k, r in results.items()
                if r.get("agent") == agent_type.value and not r.get("with_skill") and "error" not in r
            ]

            with_stats = self._compute_stats(with_results)
            without_stats = self._compute_stats(without_results)

            run_summary[f"{agent_type.value}_with_skill"] = with_stats
            if self.with_baseline:
                run_summary[f"{agent_type.value}_without_skill"] = without_stats

        delta = DeltaStats(
            pass_rate=0.0,
            time_seconds=0.0,
            tokens=0.0,
        )

        if self.with_baseline and len(self.agents) == 1:
            agent = self.agents[0]
            with_key = f"{agent.value}_with_skill"
            without_key = f"{agent.value}_without_skill"
            if with_key in run_summary and without_key in run_summary:
                delta = DeltaStats(
                    pass_rate=run_summary[with_key].pass_rate.mean - run_summary[without_key].pass_rate.mean,
                    time_seconds=run_summary[with_key].time_seconds.mean - run_summary[without_key].time_seconds.mean,
                    tokens=run_summary[with_key].tokens.mean - run_summary[without_key].tokens.mean,
                )

        return BenchmarkResult(run_summary=run_summary, delta=delta)

    def _compute_stats(self, results: list[dict]) -> BenchmarkStats:
        if not results:
            return BenchmarkStats(
                pass_rate=StatsPair(mean=0.0, stddev=0.0),
                time_seconds=StatsPair(mean=0.0, stddev=0.0),
                tokens=StatsPair(mean=0.0, stddev=0.0),
            )

        pass_rates = [r["grading"]["summary"]["pass_rate"] for r in results]
        times = [r["timing"]["duration_ms"] / 1000.0 for r in results]
        tokens = [r["timing"]["total_tokens"] for r in results]

        return BenchmarkStats(
            pass_rate=StatsPair(
                mean=statistics.mean(pass_rates) if pass_rates else 0.0,
                stddev=statistics.stdev(pass_rates) if len(pass_rates) > 1 else 0.0,
            ),
            time_seconds=StatsPair(
                mean=statistics.mean(times) if times else 0.0,
                stddev=statistics.stdev(times) if len(times) > 1 else 0.0,
            ),
            tokens=StatsPair(
                mean=statistics.mean(tokens) if tokens else 0.0,
                stddev=statistics.stdev(tokens) if len(tokens) > 1 else 0.0,
            ),
        )
