from __future__ import annotations

import json
import os
import statistics
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

from agent_skill_eval.git_state import capture_git_state, github_repo_slug
from agent_skill_eval.graders import LLMGrader, grade_assertions
from agent_skill_eval.harnesses import get_harness
from agent_skill_eval.models import (
    AgentType,
    BenchmarkResult,
    BenchmarkStats,
    CleanupManifest,
    DeltaStats,
    EvalCase,
    EvalSuite,
    RunMeta,
    StatsPair,
)
from agent_skill_eval.skills import SkillInstaller
from agent_skill_eval.workspace import WorkspaceManager

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
        harness_base_url: Optional[str] = None,
        agent_timeout: Optional[int] = None,
        agent_max_retries: Optional[int] = None,
        runs: int = 1,
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
        self.harness_base_url = harness_base_url
        self.agent_timeout = agent_timeout
        self.agent_max_retries = agent_max_retries
        self.runs = max(1, runs)

        self.run_id = uuid.uuid4().hex[:8]
        self.suite = self._load_suite()
        self.skill_installer = SkillInstaller(skill_path)
        self.workspace_mgr = WorkspaceManager(workspace_base, source_repo=source_repo)
        self.llm_grader = LLMGrader(model=grader_model, base_url=grader_base_url) if grader_model else None

    def _load_suite(self) -> EvalSuite:
        with open(self.evals_path, encoding="utf-8") as f:
            data = json.load(f)
        return EvalSuite(**data)

    def run(self, iteration: int = 1) -> Path:
        iteration_dir = self.workspace_base / f"{self.suite.skill_name}-workspace" / f"iteration-{iteration}"
        iteration_dir.mkdir(parents=True, exist_ok=True)

        self._save_eval_metadata(iteration_dir)

        tasks = []
        for eval_case in self.suite.evals:
            for agent_type in self.agents:
                for run_index in range(1, self.runs + 1):
                    tasks.append((eval_case, agent_type, True, run_index))
                    if self.with_baseline:
                        tasks.append((eval_case, agent_type, False, run_index))

        results: dict[str, dict] = {}
        cleanup_entries: list[CleanupManifest] = []

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
                for eval_case, agent_type, with_skill, run_index in tasks:
                    future = executor.submit(
                        self._run_single,
                        eval_case,
                        agent_type,
                        with_skill,
                        iteration_dir,
                        iteration,
                        run_index,
                    )
                    futures[future] = (eval_case, agent_type, with_skill, run_index)

            for future in as_completed(futures):
                eval_case, agent_type, with_skill, run_index = futures[future]
                key = f"{eval_case.id}-{agent_type.value}-{'with' if with_skill else 'without'}-r{run_index}"
                try:
                    result = future.result()
                    results[key] = result["summary"]
                    if result.get("cleanup_entry"):
                        cleanup_entries.append(result["cleanup_entry"])
                except Exception as e:
                    console.print(f"[red]Error running {key}: {e}[/red]")
                    results[key] = {"error": str(e)}
                progress.advance(task_id)

        benchmark = self._compute_benchmark(results, iteration_dir)

        if self.with_baseline:
            for agent_type in self.agents:
                if agent_type.value not in benchmark.deltas:
                    console.print(
                        f"[yellow]Warning: no with/without-skill delta for {agent_type.value} — "
                        f"all of its runs in one config errored[/yellow]"
                    )

        with open(iteration_dir / "benchmark.json", "w", encoding="utf-8") as f:
            json.dump(benchmark.model_dump(), f, indent=2)

        manifest = self._build_cleanup_manifest(cleanup_entries, iteration_dir)
        with open(iteration_dir / "cleanup.json", "w", encoding="utf-8") as f:
            json.dump(manifest.model_dump(exclude_none=True), f, indent=2)

        console.print(f"\n[green]Results saved to {iteration_dir}[/green]")
        return iteration_dir

    def _save_eval_metadata(self, iteration_dir: Path) -> None:
        meta = {
            "skill_name": self.suite.skill_name,
            "evals": [eval_case.model_dump() for eval_case in self.suite.evals],
            "source_repo": self.source_repo,
        }
        with open(iteration_dir / "evals_meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

    def _build_cleanup_manifest(self, entries: list[CleanupManifest], iteration_dir: Path) -> CleanupManifest:
        all_branches: list[str] = []
        all_prs: list[int] = []
        for entry in entries:
            for b in entry.remote_branches:
                if b not in all_branches:
                    all_branches.append(b)
            for p in entry.pr_numbers:
                if p not in all_prs:
                    all_prs.append(p)

        return CleanupManifest(
            source_repo=self.source_repo,
            source_repo_slug=github_repo_slug(self.source_repo),
            remote_branches=all_branches,
            pr_numbers=all_prs,
            workspaces=[str(p) for p in self.workspace_mgr.workspaces],
        )

    def _run_single(
        self,
        eval_case: EvalCase,
        agent_type: AgentType,
        with_skill: bool,
        iteration_dir: Path,
        iteration: int = 1,
        run_index: int = 1,
    ) -> dict:
        eval_slug = f"eval-{eval_case.id}"
        config_slug = "with_skill" if with_skill else "without_skill"
        agent_slug = agent_type.value
        config_dir = iteration_dir / eval_slug / agent_slug / config_slug
        if self.runs > 1:
            config_dir = config_dir / f"run-{run_index}"
        output_dir = config_dir / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)

        fixture_files = {}
        for file_path in eval_case.files:
            src = self.evals_path.parent / file_path
            if src.exists():
                fixture_files[Path(file_path).name] = src

        workspace_name = f"{eval_case.id}-{agent_type.value}-{'ws' if with_skill else 'bs'}"
        if self.runs > 1:
            workspace_name += f"-r{run_index}"
        workspace = self.workspace_mgr.create_workspace(workspace_name, fixture_files)

        if with_skill:
            self.skill_installer.install(workspace, agent_type)

        if eval_case.stage_files and fixture_files:
            for name in fixture_files:
                subprocess.run(
                    ["git", "add", "--", name],
                    cwd=workspace,
                    capture_output=True,
                    check=False,
                )

        model = self.agent_models.get(agent_type)
        harness = get_harness(
            agent_type,
            workspace,
            model,
            base_url=self.harness_base_url,
            timeout=self.agent_timeout,
            max_retries=self.agent_max_retries,
        )

        prompt = self._build_prompt(eval_case, with_skill)

        pre_state = capture_git_state(workspace, source_repo=self.source_repo)
        with open(output_dir / "pre_state.json", "w", encoding="utf-8") as f:
            json.dump(pre_state.model_dump(), f, indent=2)

        agent_output, timing, stdout, stderr = harness.run(prompt, output_dir)

        post_state = capture_git_state(workspace, source_repo=self.source_repo)
        with open(output_dir / "post_state.json", "w", encoding="utf-8") as f:
            json.dump(post_state.model_dump(), f, indent=2)

        with open(output_dir / "output.txt", "w", encoding="utf-8") as f:
            f.write(agent_output)

        timing_path = output_dir.parent / "timing.json"
        with open(timing_path, "w", encoding="utf-8") as f:
            json.dump(timing.model_dump(), f, indent=2)

        run_meta = RunMeta(
            eval_id=eval_case.id,
            agent=agent_type.value,
            with_skill=with_skill,
            iteration=iteration,
            skill_name=self.suite.skill_name,
            source_repo=self.source_repo,
            run_id=self.run_id,
            run_index=run_index,
        )
        meta_path = output_dir.parent / "run_meta.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(run_meta.model_dump(), f, indent=2)

        grading = grade_assertions(
            eval_case.assertions,
            agent_output,
            output_dir,
            eval_case.expected_output,
            self.llm_grader,
            workspace=workspace,
            pre_state=pre_state,
            post_state=post_state,
            should_trigger=eval_case.should_trigger,
        )

        grading_path = output_dir.parent / "grading.json"
        with open(grading_path, "w", encoding="utf-8") as f:
            json.dump(grading.model_dump(), f, indent=2)

        cleanup_entry = self._build_cleanup_entry(pre_state, post_state)

        if os.environ.get("ASE_KEEP_WORKSPACE"):
            console.print(f"  [dim]Workspace kept: {workspace}[/dim]")
        else:
            self.workspace_mgr.cleanup(workspace)

        return {
            "summary": {
                "eval_id": eval_case.id,
                "agent": agent_type.value,
                "with_skill": with_skill,
                "run_index": run_index,
                "timing": timing.model_dump(),
                "grading": grading.model_dump(),
                "agent_output": agent_output[:2000],
            },
            "cleanup_entry": cleanup_entry,
        }

    def _build_prompt(self, eval_case: EvalCase, with_skill: bool) -> str:
        """Build the prompt sent to the agent.

        With-skill mode means the skill is installed and available, NOT that
        the prompt is rewritten to invoke it. Eval prompts decide for
        themselves whether to mention the skill, except for the explicit
        ``force_skill_invocation`` opt-in (used by tests that need to assert
        the skill is reachable by name).
        """
        if with_skill and eval_case.force_skill_invocation:
            return f"Use the ${self.suite.skill_name} skill. {eval_case.prompt}"
        return eval_case.prompt

    def _build_cleanup_entry(
        self,
        pre_state,
        post_state,
    ) -> CleanupManifest:
        pre_remote = set(pre_state.remote_branches)
        post_remote = set(post_state.remote_branches)
        new_remote_branches = sorted(post_remote - pre_remote)

        pre_pr_numbers = {p.get("number") for p in pre_state.open_prs}
        new_pr_numbers: list[int] = []
        for p in post_state.open_prs:
            number = p.get("number")
            if number is None or number in pre_pr_numbers:
                continue
            # The PR snapshot is taken with --state all: a PR merged or
            # closed during the run needs no cleanup.
            state = (p.get("state") or "OPEN").upper()
            if state != "OPEN":
                continue
            # A PR someone else opened on the source repo mid-run is new in
            # the snapshot but not ours: only record PRs whose head branch
            # this run pushed.
            head = p.get("headRefName")
            if head is not None and head not in new_remote_branches:
                continue
            new_pr_numbers.append(number)

        return CleanupManifest(
            source_repo=self.source_repo,
            remote_branches=new_remote_branches,
            pr_numbers=new_pr_numbers,
        )

    def _compute_benchmark(self, results: dict[str, dict], iteration_dir: Path) -> BenchmarkResult:
        return compute_benchmark(results, self.agents, self.with_baseline)

    def _compute_stats(self, results: list[dict]) -> BenchmarkStats:
        return compute_stats(results)


def _is_full_pass(result: dict) -> bool:
    summary = result["grading"]["summary"]
    return summary.get("total", 1) > 0 and summary.get("pass_rate", 0.0) >= 1.0


def compute_stats(results: list[dict]) -> BenchmarkStats:
    if not results:
        return BenchmarkStats(
            pass_rate=StatsPair(mean=0.0, stddev=0.0),
            time_seconds=StatsPair(mean=0.0, stddev=0.0),
            tokens=StatsPair(mean=0.0, stddev=0.0),
            cost_usd=StatsPair(mean=0.0, stddev=0.0),
        )

    pass_rates = [r["grading"]["summary"]["pass_rate"] for r in results]
    times = [r["timing"]["duration_ms"] / 1000.0 for r in results]
    tokens = [r["timing"]["total_tokens"] for r in results]
    # .get: timing.json from runs before cost_usd existed lacks the field.
    costs = [r["timing"].get("cost_usd", 0.0) or 0.0 for r in results]

    full_passes = [_is_full_pass(r) for r in results]

    # pass@k: group runs by eval id; an eval counts as passed if ANY of its
    # runs fully passed. With one run per eval this equals full_pass_rate.
    by_eval: dict[str, list[bool]] = {}
    for r, fp in zip(results, full_passes):
        by_eval.setdefault(str(r.get("eval_id", "?")), []).append(fp)
    k = max(len(v) for v in by_eval.values())
    pass_at_k = sum(1 for v in by_eval.values() if any(v)) / len(by_eval)

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
        cost_usd=StatsPair(
            mean=statistics.mean(costs) if costs else 0.0,
            stddev=statistics.stdev(costs) if len(costs) > 1 else 0.0,
        ),
        full_pass_rate=sum(full_passes) / len(full_passes),
        pass_at_k=pass_at_k,
        k=k,
    )


def compute_benchmark(results: dict[str, dict], agents: list[AgentType], with_baseline: bool) -> BenchmarkResult:
    """Compute the benchmark summary from a results dict.

    Module-level so it can be called from the ``grade`` command without a
    full ``EvalRunner`` instance. Computes a with/without-skill delta for
    EVERY agent (``deltas``); ``delta`` is kept for backward compatibility
    and is only set when exactly one agent was run.
    """
    run_summary = {}
    deltas: dict[str, DeltaStats] = {}

    for agent_type in agents:
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

        with_stats = compute_stats(with_results)
        without_stats = compute_stats(without_results)

        run_summary[f"{agent_type.value}_with_skill"] = with_stats
        if with_baseline:
            run_summary[f"{agent_type.value}_without_skill"] = without_stats
            if with_results and without_results:
                deltas[agent_type.value] = DeltaStats(
                    pass_rate=with_stats.pass_rate.mean - without_stats.pass_rate.mean,
                    time_seconds=with_stats.time_seconds.mean - without_stats.time_seconds.mean,
                    tokens=with_stats.tokens.mean - without_stats.tokens.mean,
                    cost_usd=with_stats.cost_usd.mean - without_stats.cost_usd.mean,
                )

    delta = None
    if len(agents) == 1 and agents[0].value in deltas:
        delta = deltas[agents[0].value]

    return BenchmarkResult(run_summary=run_summary, deltas=deltas, delta=delta)
