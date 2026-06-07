from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

load_dotenv()

from skill_eval.graders import LLMGrader, grade_assertions  # noqa: E402
from skill_eval.models import AgentType, CleanupManifest  # noqa: E402
from skill_eval.runner import EvalRunner  # noqa: E402

app = typer.Typer(name="skill-eval", help="Evaluate agent skills across OpenCode, Claude Code, and Codex")
console = Console()


@app.command()
def run(
    skill: Path = typer.Option(..., "--skill", "-s", help="Path to skill directory containing SKILL.md"),
    evals: Path = typer.Option(..., "--evals", "-e", help="Path to evals.json file"),
    agents: list[str] = typer.Option(
        ["opencode"],
        "--agent",
        "-a",
        help="Agent(s) to evaluate: opencode, claude-code, codex",
    ),
    workspace: Path = typer.Option(
        Path.cwd() / "eval-workspace",
        "--workspace",
        "-w",
        help="Base directory for eval workspace",
    ),
    iteration: int = typer.Option(1, "--iteration", "-i", help="Iteration number"),
    concurrency: int = typer.Option(1, "--concurrency", "-c", help="Number of parallel eval runs"),
    baseline: bool = typer.Option(True, "--baseline/--no-baseline", help="Run without-skill baseline"),
    grader_model: str = typer.Option(
        "deepseek/deepseek-v4-flash", "--grader-model", help="LLM model for rubric grading"
    ),
    grader_base_url: Optional[str] = typer.Option(None, "--grader-base-url", help="Custom API base URL for grader"),
    source_repo: Optional[str] = typer.Option(
        None, "--source-repo", help="Git repo URL to clone as workspace (instead of fresh git init)"
    ),
    auto_cleanup: bool = typer.Option(False, "--cleanup", help="Auto-cleanup PRs, branches, and workspaces after run"),
):
    """Run skill evaluations."""
    if not skill.exists():
        console.print(f"[red]Skill path not found: {skill}[/red]")
        raise typer.Exit(1)
    if not evals.exists():
        console.print(f"[red]Evals file not found: {evals}[/red]")
        raise typer.Exit(1)

    agent_types = []
    for a in agents:
        try:
            agent_types.append(AgentType(a))
        except ValueError:
            console.print(f"[red]Unknown agent: {a}. Choose from: opencode, claude-code, codex[/red]")
            raise typer.Exit(1)

    runner = EvalRunner(
        skill_path=skill,
        evals_path=evals,
        workspace_base=workspace,
        agents=agent_types,
        concurrency=concurrency,
        with_baseline=baseline,
        grader_model=grader_model,
        grader_base_url=grader_base_url,
        source_repo=source_repo,
    )

    result_dir = runner.run(iteration)
    console.print(f"\n[bold green]Done! Results in: {result_dir}[/bold green]")

    if auto_cleanup:
        console.print()
        console.print("[yellow]Running cleanup...[/yellow]")
        _cleanup_iteration(result_dir, workspace)
        console.print("[green]Cleanup complete![/green]")


def _cleanup_iteration(iteration_dir: Path, workspace_base: Path) -> None:
    """Clean up only artifacts recorded for this iteration's cleanup manifest.

    Reads ``cleanup.json`` from the iteration dir. If the manifest is missing,
    we do NOT touch remote state (no "delete all branches" or "close all PRs"
    inference). We also do NOT glob-delete unrecorded ``skill-eval-*``
    workspaces under the workspace base, because those may belong to other
    runs or manual debugging. The only workspaces removed are those listed
    in the manifest.
    """
    manifest = _load_manifest(iteration_dir)

    if manifest and (manifest.remote_branches or manifest.pr_numbers):
        _cleanup_manifest(manifest, source_repo=manifest.source_repo)
    elif manifest is None and iteration_dir.exists():
        console.print(
            f"  [yellow]No cleanup.json in {iteration_dir}; skipping source repo cleanup "
            f"and unrecorded workspace deletion[/yellow]"
        )

    if manifest:
        for ws_path in manifest.workspaces:
            ws = Path(ws_path)
            if ws.exists():
                shutil.rmtree(ws)
                console.print(f"  [dim]Removed {ws.name}[/dim]")


def _load_manifest(iteration_dir: Path) -> Optional[CleanupManifest]:
    manifest_path = iteration_dir / "cleanup.json"
    if not manifest_path.exists():
        return None
    try:
        data = json.loads(manifest_path.read_text())
        return CleanupManifest(**data)
    except (json.JSONDecodeError, ValueError) as e:
        console.print(f"  [red]Could not parse cleanup.json: {e}[/red]")
        return None


def _cleanup_manifest(manifest: CleanupManifest, source_repo: Optional[str]) -> None:
    if not source_repo or not manifest.source_repo_slug:
        return

    slug = manifest.source_repo_slug

    for pr_number in manifest.pr_numbers:
        result = subprocess.run(
            ["gh", "pr", "close", str(pr_number), "--repo", slug, "--delete-branch"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            console.print(f"  [dim]Closed PR #{pr_number}[/dim]")
        else:
            console.print(
                f"  [yellow]Could not close PR #{pr_number}: {result.stderr.strip() or 'unknown error'}[/yellow]"
            )

    for branch in manifest.remote_branches:
        result = subprocess.run(
            ["gh", "api", "-X", "DELETE", f"repos/{slug}/git/refs/heads/{branch}"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            console.print(f"  [dim]Deleted branch {branch}[/dim]")
        else:
            console.print(
                f"  [yellow]Could not delete branch {branch}: {result.stderr.strip() or 'unknown error'}[/yellow]"
            )


@app.command()
def cleanup(
    iteration: Optional[Path] = typer.Option(
        None,
        "--iteration",
        "-i",
        help="Path to an iteration directory (e.g. eval-workspace/<skill>-workspace/iteration-1). "
        "If omitted, all iteration dirs under --workspace are cleaned up.",
    ),
    workspace: Path = typer.Option(
        Path.cwd() / "eval-workspace",
        "--workspace",
        "-w",
        help="Base directory for eval workspace (used when --iteration is omitted)",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Clean up eval artifacts from cleanup.json manifests.

    This command is SAFE: it only closes PRs and deletes branches that were
    recorded in ``cleanup.json`` by a previous ``run`` invocation. It will
    never close unrelated PRs or delete unrelated branches.
    """
    iteration_dirs: list[Path] = []
    if iteration:
        if not iteration.exists():
            console.print(f"[red]Iteration directory not found: {iteration}[/red]")
            raise typer.Exit(1)
        iteration_dirs = [iteration]
    else:
        if not workspace.exists():
            console.print(f"[yellow]Workspace directory not found: {workspace}[/yellow]")
            return
        iteration_dirs = sorted(p for p in workspace.glob("*/iteration-*") if p.is_dir())

    if not iteration_dirs:
        console.print("[yellow]No iteration directories found[/yellow]")
        return

    for iter_dir in iteration_dirs:
        manifest = _load_manifest(iter_dir)
        if manifest is None:
            console.print(f"[yellow]{iter_dir.name}: no cleanup.json, skipping source repo cleanup[/yellow]")
        elif manifest.remote_branches or manifest.pr_numbers:
            console.print(
                f"[cyan]{iter_dir.name}: cleaning {len(manifest.remote_branches)} branch(es), "
                f"{len(manifest.pr_numbers)} PR(s) on {manifest.source_repo_slug}[/cyan]"
            )

            if not yes:
                confirm = typer.confirm("Proceed?", default=False)
                if not confirm:
                    console.print("  [dim]Skipped[/dim]")
                    continue

            _cleanup_manifest(manifest, source_repo=manifest.source_repo)

        if manifest and manifest.workspaces:
            for ws_path in manifest.workspaces:
                ws = Path(ws_path)
                if ws.exists():
                    shutil.rmtree(ws)

    console.print("[green]Cleanup complete![/green]")


@app.command()
def grade(
    workspace: Path = typer.Option(..., "--workspace", "-w", help="Path to iteration workspace"),
    grader_model: str = typer.Option(
        "deepseek/deepseek-v4-flash", "--grader-model", help="LLM model for rubric grading"
    ),
    grader_base_url: Optional[str] = typer.Option(None, "--grader-base-url", help="Custom API base URL for grader"),
    recompute_benchmark: bool = typer.Option(
        False, "--recompute-benchmark", help="Recompute benchmark.json from updated grading.json files"
    ),
):
    """Re-grade existing eval results using saved eval metadata and state snapshots."""
    if not workspace.exists():
        console.print(f"[red]Workspace not found: {workspace}[/red]")
        raise typer.Exit(1)

    console.print(f"[yellow]Re-grading results in {workspace}...[/yellow]")

    meta_path = workspace / "evals_meta.json"
    if not meta_path.exists():
        console.print(
            f"[red]No evals_meta.json in {workspace}. Cannot determine assertions. "
            f"Re-run 'skill-eval run' to generate it.[/red]"
        )
        raise typer.Exit(1)

    with open(meta_path) as f:
        meta = json.load(f)

    eval_lookup: dict[str, dict] = {}
    for eval_case in meta.get("evals", []):
        eval_lookup[str(eval_case["id"])] = eval_case

    try:
        llm_grader = LLMGrader(model=grader_model, base_url=grader_base_url)
    except Exception:
        llm_grader = None

    updated = 0
    for eval_dir in sorted(workspace.glob("eval-*")):
        eval_id = eval_dir.name[len("eval-") :]
        eval_case = eval_lookup.get(eval_id)
        if not eval_case:
            console.print(f"  [yellow]No metadata for {eval_dir.name}, skipping[/yellow]")
            continue

        assertions = eval_case.get("assertions", [])
        should_trigger = eval_case.get("should_trigger", True)

        for agent_dir in sorted(eval_dir.iterdir()):
            if not agent_dir.is_dir():
                continue
            for config_dir in sorted(agent_dir.iterdir()):
                if not config_dir.is_dir():
                    continue
                output_path = config_dir / "outputs" / "output.txt"
                if not output_path.exists():
                    continue

                agent_output = output_path.read_text()
                grading = grade_assertions(
                    assertions,
                    agent_output,
                    config_dir / "outputs",
                    eval_case.get("expected_output", ""),
                    llm_grader,
                    pre_state=None,
                    post_state=None,
                    should_trigger=should_trigger,
                )

                grading_path = config_dir / "grading.json"
                with open(grading_path, "w") as f:
                    json.dump(grading.model_dump(), f, indent=2)

                console.print(
                    f"  {eval_dir.name}/{agent_dir.name}/{config_dir.name}: "
                    f"{grading.summary.passed}/{grading.summary.total} passed"
                )
                updated += 1

    if recompute_benchmark:
        from skill_eval.runner import compute_benchmark

        results = _collect_results(workspace)
        agents = sorted({r.get("agent") for r in results.values() if r.get("agent") and r.get("agent") != "unknown"})
        agent_types = [AgentType(a) for a in agents if a in {t.value for t in AgentType}]
        benchmark = compute_benchmark(
            results, agent_types, with_baseline=any(not r.get("with_skill", True) for r in results.values())
        )
        with open(workspace / "benchmark.json", "w") as f:
            json.dump(benchmark.model_dump(), f, indent=2)
        console.print("[green]benchmark.json recomputed[/green]")
    else:
        console.print(
            "[yellow]benchmark.json NOT recomputed. Re-run 'skill-eval run' or pass --recompute-benchmark.[/yellow]"
        )

    console.print(f"[green]Re-grading complete! Updated {updated} grading file(s).[/green]")


def _collect_results(workspace: Path) -> dict[str, dict]:
    """Reconstruct per-run results for benchmark recompute.

    Reads ``run_meta.json`` written by ``_run_single`` to recover the real
    agent and ``with_skill`` flag (the directory layout now includes the
    agent, but we use the metadata file as the source of truth). Falls back
    to ``"unknown"`` only if the metadata is missing, and disambiguates
    collisions by including the agent directory name in the key.
    """
    results: dict[str, dict] = {}
    for eval_dir in sorted(workspace.glob("eval-*")):
        for agent_dir in sorted(eval_dir.iterdir()):
            if not agent_dir.is_dir():
                continue
            for config_dir in sorted(agent_dir.iterdir()):
                if not config_dir.is_dir():
                    continue
                grading_path = config_dir / "grading.json"
                timing_path = config_dir / "timing.json"
                if not grading_path.exists() or not timing_path.exists():
                    continue
                with open(grading_path) as f:
                    grading = json.load(f)
                with open(timing_path) as f:
                    timing = json.load(f)

                meta_path = config_dir / "run_meta.json"
                agent = "unknown"
                with_skill = config_dir.name == "with_skill"
                if meta_path.exists():
                    try:
                        meta = json.loads(meta_path.read_text())
                        agent = meta.get("agent", "unknown")
                        with_skill = bool(meta.get("with_skill", with_skill))
                    except (json.JSONDecodeError, ValueError):
                        console.print(f"  [yellow]Could not parse {meta_path}; marking agent as unknown[/yellow]")
                else:
                    console.print(f"  [yellow]No run_meta.json in {config_dir}; agent identity unknown[/yellow]")

                # Include agent_dir.name in the key to avoid collisions when
                # multiple configs in the same eval are missing metadata.
                key = f"{eval_dir.name}-{agent}-{agent_dir.name}-{config_dir.name}"
                if key in results:
                    console.print(f"  [yellow]Duplicate result key {key} for {config_dir}; skipping[/yellow]")
                    continue
                results[key] = {
                    "agent": agent,
                    "with_skill": with_skill,
                    "timing": timing,
                    "grading": grading,
                }
    return results


@app.command()
def report(
    workspace: Path = typer.Option(..., "--workspace", "-w", help="Path to workspace containing iteration dirs"),
    iteration: Optional[int] = typer.Option(None, "--iteration", "-i", help="Specific iteration to report on"),
):
    """Display a summary report of eval results."""
    if not workspace.exists():
        console.print(f"[red]Workspace not found: {workspace}[/red]")
        raise typer.Exit(1)

    if iteration:
        iteration_dirs = [workspace / f"iteration-{iteration}"]
    else:
        iteration_dirs = sorted(workspace.glob("iteration-*"))

    if not iteration_dirs:
        console.print("[yellow]No iterations found[/yellow]")
        raise typer.Exit(1)

    for iter_dir in iteration_dirs:
        benchmark_path = iter_dir / "benchmark.json"
        if not benchmark_path.exists():
            console.print(f"[yellow]No benchmark.json in {iter_dir.name}[/yellow]")
            continue

        with open(benchmark_path) as f:
            benchmark = json.load(f)

        console.print(f"\n[bold]{iter_dir.name}[/bold]")

        table = Table(title="Results Summary")
        table.add_column("Configuration", style="cyan")
        table.add_column("Pass Rate", style="green")
        table.add_column("Time (s)", style="yellow")
        table.add_column("Tokens", style="blue")

        run_summary = benchmark.get("run_summary", {})
        for config, stats in run_summary.items():
            pass_rate = stats.get("pass_rate", {})
            time_s = stats.get("time_seconds", {})
            tokens = stats.get("tokens", {})

            table.add_row(
                config,
                f"{pass_rate.get('mean', 0):.1%} +/- {pass_rate.get('stddev', 0):.1%}",
                f"{time_s.get('mean', 0):.1f} +/- {time_s.get('stddev', 0):.1f}",
                f"{tokens.get('mean', 0):.0f} +/- {tokens.get('stddev', 0):.0f}",
            )

        console.print(table)

        delta = benchmark.get("delta", {})
        if delta:
            console.print("\n[bold]Delta (with_skill - without_skill):[/bold]")
            console.print(f"  Pass rate: {delta.get('pass_rate', 0):+.1%}")
            console.print(f"  Time: {delta.get('time_seconds', 0):+.1f}s")
            console.print(f"  Tokens: {delta.get('tokens', 0):+.0f}")

        console.print()

        for eval_dir in sorted(iter_dir.glob("eval-*")):
            console.print(f"\n[bold]{eval_dir.name}[/bold]")
            for agent_dir in sorted(eval_dir.iterdir()):
                if not agent_dir.is_dir():
                    continue
                for config_dir in sorted(agent_dir.iterdir()):
                    if not config_dir.is_dir():
                        continue
                    grading_path = config_dir / "grading.json"
                    if grading_path.exists():
                        with open(grading_path) as f:
                            grading = json.load(f)
                        summary = grading.get("summary", {})
                        console.print(
                            f"  {agent_dir.name}/{config_dir.name}: "
                            f"{summary.get('passed', 0)}/{summary.get('total', 0)} passed "
                            f"({summary.get('pass_rate', 0):.0%})"
                        )


@app.command()
def init(
    skill_name: str = typer.Argument(..., help="Name of the skill to create eval structure for"),
    output: Path = typer.Option(Path.cwd(), "--output", "-o", help="Output directory"),
):
    """Initialize an eval structure for a skill."""
    evals_dir = output / skill_name / "evals"
    evals_dir.mkdir(parents=True, exist_ok=True)

    example_evals = {
        "skill_name": skill_name,
        "evals": [
            {
                "id": 1,
                "prompt": f"Use the ${skill_name} skill to do its primary function",
                "expected_output": "Description of what success looks like",
                "files": [],
                "assertions": [
                    "The output contains expected content",
                ],
            },
        ],
    }

    evals_path = evals_dir / "evals.json"
    with open(evals_path, "w") as f:
        json.dump(example_evals, f, indent=2)

    (evals_dir / "files").mkdir(exist_ok=True)

    console.print(f"[green]Created eval structure at {evals_dir}[/green]")
    console.print(f"  - {evals_path}")
    console.print(f"  - {evals_dir / 'files'}/ (add fixture files here)")


if __name__ == "__main__":
    app()
