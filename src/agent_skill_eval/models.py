from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class AgentType(str, Enum):
    OPENCODE = "opencode"
    CLAUDE_CODE = "claude-code"
    CODEX = "codex"
    FAKE = "fake"


class EvalCase(BaseModel):
    id: int | str
    prompt: str
    expected_output: str
    files: list[str] = Field(default_factory=list)
    assertions: list[str] = Field(default_factory=list)
    should_trigger: bool = True
    force_skill_invocation: bool = False
    stage_files: bool = False

    @model_validator(mode="after")
    def validate_contradiction(self) -> EvalCase:
        if self.force_skill_invocation and not self.should_trigger:
            raise ValueError("Contradiction: force_skill_invocation=True cannot be set when should_trigger=False.")
        return self


class EvalSuite(BaseModel):
    skill_name: str
    evals: list[EvalCase]

    def filtered_by_ids(self, eval_ids: Optional[list[str]] = None) -> EvalSuite:
        """Return a copy containing only the requested eval ids.

        With no ids the suite is returned unchanged. Unknown ids raise a
        ValueError listing the available ids, so a typo fails fast before
        any workspace or model work starts.
        """
        if not eval_ids:
            return self

        requested = [str(eval_id) for eval_id in eval_ids]
        requested_set = set(requested)
        available = {str(eval_case.id) for eval_case in self.evals}
        missing = [eval_id for eval_id in requested if eval_id not in available]
        if missing:
            raise ValueError(
                "Unknown eval id(s): " + ", ".join(missing) + ". Available eval ids: " + ", ".join(sorted(available))
            )

        selected = [eval_case for eval_case in self.evals if str(eval_case.id) in requested_set]
        return self.model_copy(update={"evals": selected})


class GitStateSnapshot(BaseModel):
    local_branches: list[str] = Field(default_factory=list)
    remote_branches: list[str] = Field(default_factory=list)
    current_branch: str = ""
    head_sha: str = ""
    commit_count: int = 0
    commits: list[str] = Field(default_factory=list)
    remote_names: list[str] = Field(default_factory=list)
    open_prs: list[dict] = Field(default_factory=list)
    branch_heads: dict[str, str] = Field(default_factory=dict)
    remote_branch_heads: dict[str, str] = Field(default_factory=dict)
    commit_shas: list[str] = Field(default_factory=list)


class RunMeta(BaseModel):
    eval_id: int | str
    agent: str
    with_skill: bool
    iteration: int = 1
    skill_name: str = ""
    source_repo: Optional[str] = None
    run_id: str = ""
    run_index: int = 1
    # Effective model configuration, recorded so results are reproducible:
    # two users running "codex" can otherwise unknowingly benchmark different
    # models or reasoning settings inherited from local user config.
    model: Optional[str] = None
    # Reasoning effort the harness itself passed to the agent CLI
    # (--reasoning-effort). None means the harness did not set one — the
    # agent then uses whatever its own user/default config says, which this
    # harness cannot see.
    reasoning_effort: Optional[str] = None
    # API base URL injected into the agent CLI's environment
    # (--harness-base-url). None = the CLI's own default endpoint.
    base_url: Optional[str] = None
    harness_version: str = ""
    # Output of the agent CLI's --version, best effort (None if the probe
    # failed or the agent has no version command).
    agent_cli_version: Optional[str] = None


class CleanupManifest(BaseModel):
    source_repo: Optional[str] = None
    source_repo_slug: Optional[str] = None
    remote_branches: list[str] = Field(default_factory=list)
    pr_numbers: list[int] = Field(default_factory=list)
    workspaces: list[str] = Field(default_factory=list)


class TimingData(BaseModel):
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cache_creation_tokens: int = 0
    # Input tokens billed at the non-cached rate, filled in after the run by
    # the harness that knows its CLI's semantics (codex/opencode report
    # input_tokens INCLUDING cache reads, claude-code excludes them). None
    # only for timing.json files written before this field existed.
    non_cached_input_tokens: Optional[int] = None
    # Reasoning/thinking output tokens when the agent CLI exposes them
    # (codex turn.completed usage, opencode step_finish tokens). None means
    # the agent reported none — unknown, not zero.
    reasoning_output_tokens: Optional[int] = None
    # USD cost as reported by the agent CLI itself (claude: total_cost_usd,
    # opencode: per-step cost). None when no cost is available (codex reports
    # nothing and no --pricing-config entry matched) — unavailable cost must
    # not be confused with a real $0.00 run. For claude-code routed through
    # OpenRouter, this is reconciled against OpenRouter pricing (see
    # cost_usd_source / cost_usd_cli).
    cost_usd: Optional[float] = None
    # Where cost_usd came from: "cli" (the agent CLI's own number),
    # "openrouter-pricing" (recomputed from token counts and OpenRouter's
    # published per-model rates), "pricing-config" (recomputed from a
    # user-provided --pricing-config file), or "cli-unreconciled" (claude-code
    # ran via OpenRouter but reconciliation failed, so this is the CLI's
    # Anthropic-list-price estimate and actual billing differs).
    cost_usd_source: Optional[str] = None
    # The CLI's original estimate, kept when cost_usd was reconciled.
    cost_usd_cli: Optional[float] = None
    duration_ms: int = 0
    exit_code: Optional[int] = None
    timed_out: bool = False
    retries: int = 0
    # Budget guard verdict (see BudgetConfig). Filled in by the runner after
    # the agent process exits; enforcement is post-run, mid-run kills remain
    # the timeout's job.
    budget_exceeded: bool = False
    budget_reason: Optional[str] = None


class BudgetConfig(BaseModel):
    """Per-case budget limits checked after each agent run.

    Any limit left at None is not enforced. ``action`` decides what a
    violation does: "warn" only prints, "fail" appends a failed
    ``budget`` assertion to the run's grading, "stop-suite" additionally
    skips all runs that have not started yet.
    """

    max_input_tokens: Optional[int] = None
    max_non_cached_input_tokens: Optional[int] = None
    max_output_tokens: Optional[int] = None
    max_total_tokens: Optional[int] = None
    max_reasoning_tokens: Optional[int] = None
    max_cost_usd: Optional[float] = None
    max_duration_seconds: Optional[float] = None
    action: Literal["warn", "fail", "stop-suite"] = "fail"

    @property
    def enabled(self) -> bool:
        return any(
            limit is not None
            for limit in (
                self.max_input_tokens,
                self.max_non_cached_input_tokens,
                self.max_output_tokens,
                self.max_total_tokens,
                self.max_reasoning_tokens,
                self.max_cost_usd,
                self.max_duration_seconds,
            )
        )

    def violations(self, timing: TimingData) -> list[str]:
        problems: list[str] = []
        if self.max_input_tokens is not None and timing.input_tokens > self.max_input_tokens:
            problems.append(f"input tokens {timing.input_tokens} > {self.max_input_tokens}")
        # Like cost: only enforced when the run actually reported the value.
        # A None is "unavailable", and failing a run over an unknown quantity
        # would punish agents for exposing less telemetry.
        if (
            self.max_non_cached_input_tokens is not None
            and timing.non_cached_input_tokens is not None
            and timing.non_cached_input_tokens > self.max_non_cached_input_tokens
        ):
            problems.append(
                f"non-cached input tokens {timing.non_cached_input_tokens} > {self.max_non_cached_input_tokens}"
            )
        if self.max_output_tokens is not None and timing.output_tokens > self.max_output_tokens:
            problems.append(f"output tokens {timing.output_tokens} > {self.max_output_tokens}")
        if (
            self.max_reasoning_tokens is not None
            and timing.reasoning_output_tokens is not None
            and timing.reasoning_output_tokens > self.max_reasoning_tokens
        ):
            problems.append(f"reasoning tokens {timing.reasoning_output_tokens} > {self.max_reasoning_tokens}")
        if self.max_total_tokens is not None and timing.total_tokens > self.max_total_tokens:
            problems.append(f"total tokens {timing.total_tokens} > {self.max_total_tokens}")
        if self.max_cost_usd is not None and timing.cost_usd is not None and timing.cost_usd > self.max_cost_usd:
            problems.append(f"cost {timing.cost_usd:.4f} USD > {self.max_cost_usd:.4f} USD")
        if self.max_duration_seconds is not None and timing.duration_ms / 1000.0 > self.max_duration_seconds:
            problems.append(f"duration {timing.duration_ms / 1000.0:.1f}s > {self.max_duration_seconds:.1f}s")
        return problems


class AssertionResult(BaseModel):
    text: str
    passed: bool
    evidence: str
    method: str = "deterministic"
    skipped: bool = False


class GradingResult(BaseModel):
    assertion_results: list[AssertionResult]
    summary: GradingSummary


class GradingSummary(BaseModel):
    passed: int
    failed: int
    total: int
    pass_rate: float
    skipped: int = 0


GradingResult.model_rebuild()


class RunConfig(BaseModel):
    skill_path: Path
    evals_path: Path
    workspace_path: Path
    agents: list[AgentType]
    concurrency: int = 1
    with_baseline: bool = True
    grader_model: str = "deepseek/deepseek-v4-flash"
    grader_base_url: Optional[str] = None


class BenchmarkStats(BaseModel):
    pass_rate: StatsPair
    time_seconds: StatsPair
    tokens: StatsPair
    # USD cost per run (see TimingData.cost_usd), computed over the runs
    # that reported a cost. None when no run had a usable cost — cost is
    # unavailable, not zero.
    cost_usd: Optional[StatsPair] = None
    # How many of the runs had a usable cost_usd.
    cost_runs: int = 0
    # Fraction of runs where ALL assertions passed (pass@1 estimate).
    full_pass_rate: float = 0.0
    # Fraction of evals where at least one of k runs fully passed.
    pass_at_k: float = 0.0
    k: int = 1


class StatsPair(BaseModel):
    mean: float
    stddev: float


class BenchmarkResult(BaseModel):
    run_summary: dict[str, BenchmarkStats]
    # Per-agent with_skill - without_skill deltas, keyed by agent value.
    deltas: dict[str, DeltaStats] = Field(default_factory=dict)
    # Kept for backward compatibility: equals the single agent's delta when
    # exactly one agent was run, otherwise None.
    delta: Optional[DeltaStats] = None


class DeltaStats(BaseModel):
    pass_rate: float
    time_seconds: float
    tokens: float
    # None when either side of the comparison had no usable cost.
    cost_usd: Optional[float] = None
