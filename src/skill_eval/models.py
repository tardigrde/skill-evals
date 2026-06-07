from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


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


class EvalSuite(BaseModel):
    skill_name: str
    evals: list[EvalCase]


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
    duration_ms: int = 0


class AssertionResult(BaseModel):
    text: str
    passed: bool
    evidence: str


class GradingResult(BaseModel):
    assertion_results: list[AssertionResult]
    summary: GradingSummary


class GradingSummary(BaseModel):
    passed: int
    failed: int
    total: int
    pass_rate: float


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


class StatsPair(BaseModel):
    mean: float
    stddev: float


class BenchmarkResult(BaseModel):
    run_summary: dict[str, BenchmarkStats]
    delta: DeltaStats


class DeltaStats(BaseModel):
    pass_rate: float
    time_seconds: float
    tokens: float
