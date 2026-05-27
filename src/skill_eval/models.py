from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class AgentType(str, Enum):
    OPENCODE = "opencode"
    CLAUDE_CODE = "claude-code"
    CODEX = "codex"


class EvalCase(BaseModel):
    id: int | str
    prompt: str
    expected_output: str
    files: list[str] = Field(default_factory=list)
    assertions: list[str] = Field(default_factory=list)
    should_trigger: bool = True


class EvalSuite(BaseModel):
    skill_name: str
    evals: list[EvalCase]


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
