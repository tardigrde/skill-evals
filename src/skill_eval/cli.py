from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

load_dotenv()

from skill_eval.models import AgentType
from skill_eval.runner import EvalRunner

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
    grader_model: str = typer.Option("deepseek/deepseek-v4-flash", "--grader-model", help="LLM model for rubric grading"),
    grader_base_url: Optional[str] = typer.Option(None, "--grader-base-url", help="Custom API base URL for grader"),
    source_repo: Optional[str] = typer.Option(None, "--source-repo", help="Git repo URL to clone as workspace (instead of fresh git init)"),
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


@app.command()
def grade(
    workspace: Path = typer.Option(..., "--workspace", "-w", help="Path to iteration workspace"),
    grader_model: str = typer.Option("deepseek/deepseek-v4-flash", "--grader-model", help="LLM model for rubric grading"),
    grader_base_url: Optional[str] = typer.Option(None, "--grader-base-url", help="Custom API base URL for grader"),
):
    """Re-grade existing eval results with updated assertions."""
    if not workspace.exists():
        console.print(f"[red]Workspace not found: {workspace}[/red]")
        raise typer.Exit(1)

    console.print(f"[yellow]Re-grading results in {workspace}...[/yellow]")

    from skill_eval.graders import LLMGrader, grade_assertions

    llm_grader = LLMGrader(model=grader_model, base_url=grader_base_url)

    for eval_dir in sorted(workspace.glob("eval-*")):
        for config_dir in eval_dir.iterdir():
            if not config_dir.is_dir():
                continue
            grading_path = config_dir / "grading.json"
            output_path = config_dir / "outputs" / "output.txt"

            if not output_path.exists():
                continue

            agent_output = output_path.read_text()
            console.print(f"  Grading {eval_dir.name}/{config_dir.name}...")

    console.print("[green]Re-grading complete![/green]")


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
            console.print(f"\n[bold]Delta (with_skill - without_skill):[/bold]")
            console.print(f"  Pass rate: {delta.get('pass_rate', 0):+.1%}")
            console.print(f"  Time: {delta.get('time_seconds', 0):+.1f}s")
            console.print(f"  Tokens: {delta.get('tokens', 0):+.0f}")

        console.print()

        for eval_dir in sorted(iter_dir.glob("eval-*")):
            console.print(f"\n[bold]{eval_dir.name}[/bold]")
            for config_dir in sorted(eval_dir.iterdir()):
                if not config_dir.is_dir():
                    continue
                grading_path = config_dir / "grading.json"
                if grading_path.exists():
                    with open(grading_path) as f:
                        grading = json.load(f)
                    summary = grading.get("summary", {})
                    console.print(
                        f"  {config_dir.name}: "
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
