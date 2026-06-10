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

from skill_eval import __version__  # noqa: E402
from skill_eval.graders import LLMGrader, grade_assertions  # noqa: E402
from skill_eval.models import AgentType, CleanupManifest, EvalSuite  # noqa: E402
from skill_eval.runner import EvalRunner  # noqa: E402


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"skill-eval {__version__}")
        raise typer.Exit()


app = typer.Typer(name="skill-eval", help="Evaluate agent skills across OpenCode, Claude Code, Codex, and Fake")
console = Console()
AGENT_CHOICES = ", ".join(t.value for t in AgentType)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: Optional[bool] = typer.Option(
        None, "--version", "-v", callback=_version_callback, is_eager=True, help="Show version and exit"
    ),
) -> None:
    """Evaluate agent skills across OpenCode, Claude Code, Codex, and Fake."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


@app.command()
def run(
    skill: Path = typer.Option(..., "--skill", "-s", help="Path to skill directory containing SKILL.md"),
    evals: Path = typer.Option(..., "--evals", "-e", help="Path to evals.json file"),
    agents: list[str] = typer.Option(
        ["opencode"],
        "--agent",
        "-a",
        help=f"Agent(s) to evaluate: {AGENT_CHOICES}",
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
    agent_models: list[str] = typer.Option(
        [],
        "--agent-model",
        "-m",
        help="Model for an agent as 'agent=model' (e.g. 'claude-code=haiku', 'codex=gpt-5-mini'). "
        "A bare 'model' value applies to all selected agents. Repeatable.",
    ),
    harness_base_url: Optional[str] = typer.Option(
        None,
        "--harness-base-url",
        help="API base URL injected into each agent CLI's environment "
        "(ANTHROPIC_BASE_URL for claude-code, OPENAI_BASE_URL for codex/opencode)",
    ),
    runs: int = typer.Option(1, "--runs", "-n", help="Number of runs per (eval, agent, config) for pass@k stats"),
    agent_timeout: Optional[int] = typer.Option(
        None, "--timeout", help="Per-run agent timeout in seconds (default 600, env SKILL_EVAL_AGENT_TIMEOUT)"
    ),
    agent_retries: Optional[int] = typer.Option(
        None, "--retries", help="Retries on agent timeout/non-zero exit (default 1, env SKILL_EVAL_AGENT_RETRIES)"
    ),
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
            console.print(f"[red]Unknown agent: {a}. Choose from: {AGENT_CHOICES}[/red]")
            raise typer.Exit(1)

    agent_model_map = _parse_agent_models(agent_models, agent_types)

    from skill_eval.skills import SkillInstaller

    try:
        for problem in SkillInstaller(skill).frontmatter_problems():
            console.print(f"[yellow]Warning: {problem}[/yellow]")
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if grader_model and not LLMGrader.has_credentials():
        console.print(
            "[yellow]Warning: no OPENROUTER_API_KEY or OPENAI_API_KEY set. "
            "Assertions that need LLM rubric grading will be SKIPPED (not failed).[/yellow]"
        )

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
        agent_models=agent_model_map,
        harness_base_url=harness_base_url,
        agent_timeout=agent_timeout,
        agent_max_retries=agent_retries,
        runs=runs,
    )

    result_dir = runner.run(iteration)
    console.print(f"\n[bold green]Done! Results in: {result_dir}[/bold green]")

    if auto_cleanup:
        console.print()
        console.print("[yellow]Running cleanup...[/yellow]")
        _cleanup_iteration(result_dir, workspace)
        console.print("[green]Cleanup complete![/green]")


def _parse_agent_models(specs: list[str], agent_types: list[AgentType]) -> dict[AgentType, str]:
    """Parse repeated ``--agent-model`` values into an AgentType -> model map.

    Accepts ``agent=model`` to target one agent, or a bare ``model`` that
    applies to every selected agent.
    """
    mapping: dict[AgentType, str] = {}
    for spec in specs:
        if "=" in spec:
            agent_str, model = spec.split("=", 1)
            try:
                agent = AgentType(agent_str.strip())
            except ValueError:
                console.print(f"[red]Unknown agent in --agent-model '{spec}'. Choose from: {AGENT_CHOICES}[/red]")
                raise typer.Exit(1)
            if not model.strip():
                console.print(f"[red]Empty model in --agent-model '{spec}'[/red]")
                raise typer.Exit(1)
            mapping[agent] = model.strip()
        else:
            for agent in agent_types:
                mapping.setdefault(agent, spec.strip())
    return mapping


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
    console.print(
        "[yellow]Note: LLM-graded assertions are re-evaluated from scratch; "
        "their verdicts may differ from the original run.[/yellow]"
    )

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
            for config_dir in _leaf_config_dirs(agent_dir):
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
                    f"  {eval_dir.name}/{agent_dir.name}/{config_dir.relative_to(agent_dir)}: "
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


def _leaf_config_dirs(agent_dir: Path) -> list[Path]:
    """Yield config dirs that directly contain run artifacts.

    Layouts: ``agent/with_skill/outputs`` (single run) or
    ``agent/with_skill/run-N/outputs`` (``--runs N`` > 1).
    """
    leaves: list[Path] = []
    for config_dir in sorted(agent_dir.iterdir()):
        if not config_dir.is_dir():
            continue
        run_dirs = sorted(p for p in config_dir.glob("run-*") if p.is_dir())
        if run_dirs:
            leaves.extend(run_dirs)
        else:
            leaves.append(config_dir)
    return leaves


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
            for config_dir in _leaf_config_dirs(agent_dir):
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
                with_skill = "with_skill" in config_dir.parts
                eval_id = eval_dir.name[len("eval-") :]
                if meta_path.exists():
                    try:
                        meta = json.loads(meta_path.read_text())
                        agent = meta.get("agent", "unknown")
                        with_skill = bool(meta.get("with_skill", with_skill))
                        eval_id = meta.get("eval_id", eval_id)
                    except (json.JSONDecodeError, ValueError):
                        console.print(f"  [yellow]Could not parse {meta_path}; marking agent as unknown[/yellow]")
                else:
                    console.print(f"  [yellow]No run_meta.json in {config_dir}; agent identity unknown[/yellow]")

                # Include the path relative to the eval dir in the key to
                # avoid collisions when metadata is missing.
                key = f"{eval_dir.name}-{agent}-{'-'.join(config_dir.relative_to(eval_dir).parts)}"
                if key in results:
                    console.print(f"  [yellow]Duplicate result key {key} for {config_dir}; skipping[/yellow]")
                    continue
                results[key] = {
                    "eval_id": eval_id,
                    "agent": agent,
                    "with_skill": with_skill,
                    "timing": timing,
                    "grading": grading,
                }
    return results


def _benchmark_rows(benchmark: dict) -> list[tuple[str, str, str, str, str]]:
    rows = []
    for config, stats in benchmark.get("run_summary", {}).items():
        pass_rate = stats.get("pass_rate", {})
        time_s = stats.get("time_seconds", {})
        tokens = stats.get("tokens", {})
        k = stats.get("k", 1)
        pass_at_k = f"{stats.get('pass_at_k', 0):.0%} (k={k})" if k > 1 else f"{stats.get('full_pass_rate', 0):.0%}"
        rows.append(
            (
                config,
                f"{pass_rate.get('mean', 0):.1%} +/- {pass_rate.get('stddev', 0):.1%}",
                pass_at_k,
                f"{time_s.get('mean', 0):.1f} +/- {time_s.get('stddev', 0):.1f}",
                f"{tokens.get('mean', 0):.0f} +/- {tokens.get('stddev', 0):.0f}",
            )
        )
    return rows


def _benchmark_deltas(benchmark: dict) -> dict[str, dict]:
    deltas = benchmark.get("deltas") or {}
    if not deltas and benchmark.get("delta"):
        deltas = {"all": benchmark["delta"]}
    return deltas


REPORT_COLUMNS = ["Configuration", "Pass Rate", "Full Pass / pass@k", "Time (s)", "Tokens"]


def _print_markdown_report(iter_name: str, benchmark: dict) -> None:
    print(f"\n### {iter_name}\n")
    print("| " + " | ".join(REPORT_COLUMNS) + " |")
    print("|" + "|".join([" --- "] * len(REPORT_COLUMNS)) + "|")
    for row in _benchmark_rows(benchmark):
        print("| " + " | ".join(row) + " |")
    deltas = _benchmark_deltas(benchmark)
    if deltas:
        print("\n**Delta (with_skill - without_skill):**\n")
        for agent, delta in deltas.items():
            print(
                f"- `{agent}`: pass rate {delta.get('pass_rate', 0):+.1%}, "
                f"time {delta.get('time_seconds', 0):+.1f}s, tokens {delta.get('tokens', 0):+.0f}"
            )


def _print_table_report(iter_name: str, benchmark: dict) -> None:
    console.print(f"\n[bold]{iter_name}[/bold]")

    table = Table(title="Results Summary")
    table.add_column(REPORT_COLUMNS[0], style="cyan")
    table.add_column(REPORT_COLUMNS[1], style="green")
    table.add_column(REPORT_COLUMNS[2], style="magenta")
    table.add_column(REPORT_COLUMNS[3], style="yellow")
    table.add_column(REPORT_COLUMNS[4], style="blue")
    for row in _benchmark_rows(benchmark):
        table.add_row(*row)
    console.print(table)

    deltas = _benchmark_deltas(benchmark)
    if deltas:
        console.print("\n[bold]Delta (with_skill - without_skill):[/bold]")
        for agent, delta in deltas.items():
            console.print(
                f"  {agent}: pass rate {delta.get('pass_rate', 0):+.1%}, "
                f"time {delta.get('time_seconds', 0):+.1f}s, tokens {delta.get('tokens', 0):+.0f}"
            )


def _print_eval_details(iter_dir: Path, show_evidence: bool, markdown: bool) -> None:
    for eval_dir in sorted(iter_dir.glob("eval-*")):
        if markdown:
            print(f"\n#### {eval_dir.name}\n")
        else:
            console.print(f"\n[bold]{eval_dir.name}[/bold]")
        for agent_dir in sorted(eval_dir.iterdir()):
            if not agent_dir.is_dir():
                continue
            for config_dir in _leaf_config_dirs(agent_dir):
                grading_path = config_dir / "grading.json"
                if not grading_path.exists():
                    continue
                with open(grading_path) as f:
                    grading = json.load(f)
                summary = grading.get("summary", {})
                label = f"{agent_dir.name}/{config_dir.relative_to(agent_dir)}"
                skipped = summary.get("skipped", 0)
                skipped_note = f", {skipped} skipped" if skipped else ""
                line = (
                    f"{label}: {summary.get('passed', 0)}/{summary.get('total', 0)} passed "
                    f"({summary.get('pass_rate', 0):.0%}{skipped_note})"
                )
                if markdown:
                    print(f"- {line}")
                else:
                    console.print(f"  {line}")
                if show_evidence:
                    for result in grading.get("assertion_results", []):
                        if result.get("passed"):
                            continue
                        status = "SKIPPED" if result.get("skipped") else "FAIL"
                        detail = f"[{status}] {result.get('text')} — {result.get('evidence')}"
                        if markdown:
                            print(f"  - {detail}")
                        else:
                            style = "yellow" if result.get("skipped") else "red"
                            console.print(f"    [{style}]{detail}[/{style}]")


@app.command()
def report(
    workspace: Path = typer.Option(..., "--workspace", "-w", help="Path to workspace containing iteration dirs"),
    iteration: Optional[int] = typer.Option(None, "--iteration", "-i", help="Specific iteration to report on"),
    fmt: str = typer.Option("table", "--format", "-f", help="Output format: table or markdown"),
    show_evidence: bool = typer.Option(
        False, "--show-evidence", help="Show evidence for failed/skipped assertions from grading.json"
    ),
):
    """Display a summary report of eval results."""
    if not workspace.exists():
        console.print(f"[red]Workspace not found: {workspace}[/red]")
        raise typer.Exit(1)
    if fmt not in ("table", "markdown"):
        console.print(f"[red]Unknown format: {fmt}. Choose 'table' or 'markdown'.[/red]")
        raise typer.Exit(1)

    if iteration:
        iteration_dirs = [workspace / f"iteration-{iteration}"]
    else:
        iteration_dirs = sorted(workspace.glob("iteration-*"))

    if not iteration_dirs:
        console.print("[yellow]No iterations found[/yellow]")
        raise typer.Exit(1)

    markdown = fmt == "markdown"
    for iter_dir in iteration_dirs:
        benchmark_path = iter_dir / "benchmark.json"
        if not benchmark_path.exists():
            console.print(f"[yellow]No benchmark.json in {iter_dir.name}[/yellow]")
            continue

        with open(benchmark_path) as f:
            benchmark = json.load(f)

        if markdown:
            _print_markdown_report(iter_dir.name, benchmark)
        else:
            _print_table_report(iter_dir.name, benchmark)

        _print_eval_details(iter_dir, show_evidence, markdown)


@app.command()
def compare(
    workspace: Path = typer.Option(..., "--workspace", "-w", help="Path to workspace containing iteration dirs"),
    iteration_a: int = typer.Argument(..., help="Baseline iteration number"),
    iteration_b: int = typer.Argument(..., help="Comparison iteration number"),
):
    """Compare benchmark results between two iterations of the same skill."""
    benchmarks = {}
    for n in (iteration_a, iteration_b):
        path = workspace / f"iteration-{n}" / "benchmark.json"
        if not path.exists():
            console.print(f"[red]No benchmark.json for iteration-{n} in {workspace}[/red]")
            raise typer.Exit(1)
        with open(path) as f:
            benchmarks[n] = json.load(f)

    summary_a = benchmarks[iteration_a].get("run_summary", {})
    summary_b = benchmarks[iteration_b].get("run_summary", {})
    configs = sorted(set(summary_a) | set(summary_b))

    table = Table(title=f"iteration-{iteration_a} vs iteration-{iteration_b}")
    table.add_column("Configuration", style="cyan")
    table.add_column(f"Pass Rate (it-{iteration_a})", style="green")
    table.add_column(f"Pass Rate (it-{iteration_b})", style="green")
    table.add_column("Change", style="magenta")

    for config in configs:
        a = summary_a.get(config, {}).get("pass_rate", {}).get("mean")
        b = summary_b.get(config, {}).get("pass_rate", {}).get("mean")
        a_str = f"{a:.1%}" if a is not None else "-"
        b_str = f"{b:.1%}" if b is not None else "-"
        change = f"{b - a:+.1%}" if a is not None and b is not None else "-"
        table.add_row(config, a_str, b_str, change)

    console.print(table)


@app.command()
def validate(
    evals: Path = typer.Argument(..., help="Path to an evals.json file to validate"),
):
    """Validate an evals.json file against the eval suite schema."""
    if not evals.exists():
        console.print(f"[red]File not found: {evals}[/red]")
        raise typer.Exit(1)

    try:
        data = json.loads(evals.read_text())
    except json.JSONDecodeError as e:
        console.print(f"[red]Invalid JSON: {e}[/red]")
        raise typer.Exit(1)

    try:
        suite = EvalSuite(**data)
    except Exception as e:
        console.print(f"[red]Schema validation failed:[/red]\n{e}")
        raise typer.Exit(1)

    missing_files = []
    for eval_case in suite.evals:
        for file_path in eval_case.files:
            if not (evals.parent / file_path).exists():
                missing_files.append(f"eval '{eval_case.id}': {file_path}")
    if missing_files:
        console.print("[red]Referenced fixture files not found:[/red]")
        for m in missing_files:
            console.print(f"  - {m}")
        raise typer.Exit(1)

    ids = [str(e.id) for e in suite.evals]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        console.print(f"[red]Duplicate eval ids: {duplicates}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]Valid: {len(suite.evals)} eval(s) for skill '{suite.skill_name}'[/green]")


@app.command(name="list")
def list_suites(
    root: Path = typer.Option(Path.cwd(), "--root", "-r", help="Directory to search for eval suites and skills"),
):
    """List discoverable skills (SKILL.md) and eval suites (evals.json)."""
    suites = sorted(root.glob("*/*/evals/evals.json")) + sorted(root.glob("*/evals/evals.json"))
    skills = sorted(root.glob("skills/*/SKILL.md")) + sorted(root.glob("*/SKILL.md"))

    seen: set[Path] = set()
    table = Table(title=f"Eval suites under {root}")
    table.add_column("Skill", style="cyan")
    table.add_column("Evals file", style="green")
    table.add_column("Cases", style="yellow")
    for path in suites:
        if path in seen:
            continue
        seen.add(path)
        try:
            data = json.loads(path.read_text())
            name = data.get("skill_name", "?")
            count = str(len(data.get("evals", [])))
        except (json.JSONDecodeError, OSError):
            name, count = "(unparseable)", "-"
        table.add_row(name, str(path.relative_to(root)), count)
    if seen:
        console.print(table)
    else:
        console.print(f"[yellow]No evals.json files found under {root}[/yellow]")

    seen_skills: set[Path] = set()
    skill_table = Table(title=f"Skills under {root}")
    skill_table.add_column("Skill dir", style="cyan")
    for path in skills:
        if path in seen_skills:
            continue
        seen_skills.add(path)
        skill_table.add_row(str(path.parent.relative_to(root)))
    if seen_skills:
        console.print(skill_table)


SKILL_MD_TEMPLATE = """\
---
name: {skill_name}
description: One-line description used by the agent to decide when to trigger this skill.
license: MIT
compatibility: opencode, claude-code, codex
---

## What I do

Describe the skill's behavior here.

## When to use me

Trigger on phrases like:
- "..."

## Steps

1. ...
"""


@app.command()
def init(
    skill_name: str = typer.Argument(..., help="Name of the skill to create eval structure for"),
    output: Path = typer.Option(Path.cwd(), "--output", "-o", help="Output directory"),
):
    """Initialize an eval structure (and a SKILL.md template) for a skill."""
    evals_dir = output / skill_name / "evals"
    evals_dir.mkdir(parents=True, exist_ok=True)

    example_evals = {
        "skill_name": skill_name,
        "evals": [
            {
                "id": "explicit-invoke",
                "prompt": f"Use the ${skill_name} skill to do its primary function",
                "expected_output": "Description of what success looks like",
                "files": [],
                "force_skill_invocation": True,
                "assertions": [
                    "The output contains expected content",
                ],
            },
            {
                "id": "negative-control",
                "prompt": "Show me the git log for the last 10 commits",
                "expected_output": "The skill should NOT trigger.",
                "should_trigger": False,
                "assertions": [
                    "A new git branch was created",
                    "A git commit was created",
                ],
            },
        ],
    }

    evals_path = evals_dir / "evals.json"
    with open(evals_path, "w") as f:
        json.dump(example_evals, f, indent=2)

    (evals_dir / "files").mkdir(exist_ok=True)

    skill_md_path = output / skill_name / "SKILL.md"
    if not skill_md_path.exists():
        skill_md_path.write_text(SKILL_MD_TEMPLATE.format(skill_name=skill_name))

    console.print(f"[green]Created eval structure at {evals_dir}[/green]")
    console.print(f"  - {evals_path}")
    console.print(f"  - {evals_dir / 'files'}/ (add fixture files here)")
    console.print(f"  - {skill_md_path} (skill template; edit before evaluating)")


if __name__ == "__main__":
    app()
