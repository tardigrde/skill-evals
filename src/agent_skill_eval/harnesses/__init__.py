from __future__ import annotations

import json
import os
import subprocess
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from agent_skill_eval.models import AgentType, TimingData

DEFAULT_TIMEOUT_SECONDS = 600
DEFAULT_MAX_RETRIES = 1
RETRY_BACKOFF_SECONDS = 2.0


class AgentHarness(ABC):
    agent_type: AgentType
    # Environment variable each agent CLI reads its API base URL from.
    base_url_env: Optional[str] = None

    def __init__(
        self,
        workspace: Path,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[int] = None,
        max_retries: Optional[int] = None,
    ):
        self.workspace = workspace
        self.model = model
        self.base_url = base_url
        self.timeout = timeout or int(os.environ.get("ASE_AGENT_TIMEOUT", DEFAULT_TIMEOUT_SECONDS))
        if max_retries is None:
            max_retries = int(os.environ.get("ASE_AGENT_RETRIES", DEFAULT_MAX_RETRIES))
        self.max_retries = max_retries

    @abstractmethod
    def build_command(self, prompt: str, output_dir: Path) -> list[str]:
        pass

    @abstractmethod
    def parse_output(self, stdout: str, stderr: str) -> tuple[str, TimingData]:
        pass

    def finalize_timing(self, timing: TimingData) -> None:
        """Post-process timing after a run (e.g. cost reconciliation)."""
        if timing.cost_usd and timing.cost_usd_source is None:
            timing.cost_usd_source = "cli"

    def _build_env(self) -> Optional[dict[str, str]]:
        if self.base_url and self.base_url_env:
            env = dict(os.environ)
            env[self.base_url_env] = self.base_url
            return env
        return None

    def _workspace_fingerprint(self) -> Optional[tuple[str, str]]:
        """(HEAD sha, porcelain status) of the workspace, or None outside git.

        Used to refuse retries after a failed attempt that already mutated
        the workspace — re-running there would grade the union of both
        attempts' side effects.
        """
        try:
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.workspace,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=15,
                check=False,
            )
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.workspace,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=15,
                check=False,
            )
        except (subprocess.SubprocessError, OSError):
            return None
        if head.returncode != 0 or status.returncode != 0:
            return None
        return (head.stdout.strip(), status.stdout)

    def run(self, prompt: str, output_dir: Path) -> tuple[str, TimingData, str, str]:
        output_dir.mkdir(parents=True, exist_ok=True)

        cmd = self.build_command(prompt, output_dir)
        env = self._build_env()

        attempts = self.max_retries + 1
        stdout = ""
        stderr = ""
        exit_code: Optional[int] = None
        timed_out = False
        retries_used = 0
        start = time.time()
        fingerprint_before = self._workspace_fingerprint()

        for attempt in range(attempts):
            if attempt > 0:
                retries_used = attempt
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
            try:
                result = subprocess.run(
                    cmd,
                    cwd=self.workspace,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=self.timeout,
                    env=env,
                )
                stdout = result.stdout or ""
                stderr = result.stderr or ""
                exit_code = result.returncode
                timed_out = False
                if result.returncode == 0:
                    break
            except subprocess.TimeoutExpired as e:
                stdout = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
                stderr = (e.stderr or b"").decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
                stderr += f"\n[agent-skill-eval] timed out after {self.timeout}s (attempt {attempt + 1}/{attempts})"
                exit_code = None
                timed_out = True

            # Only retry into a pristine workspace: if the failed attempt
            # already committed/wrote files, a second run would produce a
            # graded union of both attempts.
            if attempt < attempts - 1 and fingerprint_before is not None:
                if self._workspace_fingerprint() != fingerprint_before:
                    stderr += "\n[agent-skill-eval] not retrying: the failed attempt modified the workspace"
                    break

        duration_ms = int((time.time() - start) * 1000)

        final_output, timing = self.parse_output(stdout, stderr)
        if timing.duration_ms == 0:
            timing.duration_ms = duration_ms
        timing.exit_code = exit_code
        timing.timed_out = timed_out
        timing.retries = retries_used
        self.finalize_timing(timing)

        with open(output_dir / "stdout.log", "w", encoding="utf-8") as f:
            f.write(stdout)
        with open(output_dir / "stderr.log", "w", encoding="utf-8") as f:
            f.write(stderr)

        return final_output, timing, stdout, stderr


class OpenCodeHarness(AgentHarness):
    agent_type = AgentType.OPENCODE
    base_url_env = "OPENAI_BASE_URL"

    def build_command(self, prompt: str, output_dir: Path) -> list[str]:
        cmd = [
            "opencode",
            "run",
            "--dir",
            str(self.workspace),
            "--format",
            "json",
            "--dangerously-skip-permissions",
        ]
        if self.model:
            cmd.extend(["--model", self.model])
        cmd.append(prompt)
        return cmd

    def parse_output(self, stdout: str, stderr: str) -> tuple[str, TimingData]:
        timing = TimingData()
        messages = []

        for line in stdout.strip().split("\n"):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                etype = event.get("type", "")

                if etype == "text":
                    part = event.get("part", {})
                    text = part.get("text", "")
                    if text:
                        messages.append(text)

                elif etype == "step_finish":
                    part = event.get("part", {})
                    tokens = part.get("tokens", {})
                    timing.input_tokens += tokens.get("input", 0)
                    timing.output_tokens += tokens.get("output", 0)
                    cache = tokens.get("cache", {})
                    timing.cached_tokens += cache.get("read", 0)
                    timing.cost_usd += part.get("cost", 0) or 0

            except json.JSONDecodeError:
                continue

        timing.total_tokens = timing.input_tokens + timing.output_tokens
        return "\n".join(messages), timing


class ClaudeCodeHarness(AgentHarness):
    agent_type = AgentType.CLAUDE_CODE
    base_url_env = "ANTHROPIC_BASE_URL"

    def build_command(self, prompt: str, output_dir: Path) -> list[str]:
        cmd = [
            "claude",
            "-p",
            "--output-format",
            "json",
            "--dangerously-skip-permissions",
        ]
        if self.model:
            cmd.extend(["--model", self.model])
        cmd.append(prompt)
        return cmd

    def parse_output(self, stdout: str, stderr: str) -> tuple[str, TimingData]:
        timing = TimingData()
        final_text = ""

        try:
            data = json.loads(stdout)
            if isinstance(data, dict):
                final_text = data.get("result", "")
                usage = data.get("usage", {})
                timing.input_tokens = usage.get("input_tokens", 0)
                timing.output_tokens = usage.get("output_tokens", 0)
                timing.cached_tokens = usage.get("cache_read_input_tokens", 0)
                timing.cache_creation_tokens = usage.get("cache_creation_input_tokens", 0)
                timing.cost_usd = data.get("total_cost_usd", 0.0) or 0.0
                timing.total_tokens = timing.input_tokens + timing.output_tokens
                duration_s = data.get("duration_ms", 0)
                if duration_s:
                    timing.duration_ms = duration_s
        except json.JSONDecodeError:
            final_text = stdout

        return final_text, timing

    def finalize_timing(self, timing: TimingData) -> None:
        """Reconcile the CLI's cost estimate when running via OpenRouter.

        The claude CLI prices runs at Anthropic list prices regardless of the
        endpoint it talks to. When ANTHROPIC_BASE_URL points at OpenRouter,
        actual billing follows OpenRouter's per-model pricing, so we recompute
        from token counts (the generation API would be exact but needs
        per-request ids the CLI does not expose). The CLI's own number is kept
        in cost_usd_cli.
        """
        base = self.base_url or os.environ.get("ANTHROPIC_BASE_URL", "")
        if "openrouter" not in base.lower():
            super().finalize_timing(timing)
            return

        from agent_skill_eval.openrouter import reconcile_claude_cost

        reconciled = reconcile_claude_cost(timing, self.model)
        if reconciled is None:
            timing.cost_usd_source = "cli-unreconciled"
            return
        timing.cost_usd_cli = timing.cost_usd
        timing.cost_usd = reconciled
        timing.cost_usd_source = "openrouter-pricing"


class CodexHarness(AgentHarness):
    agent_type = AgentType.CODEX
    base_url_env = "OPENAI_BASE_URL"

    def build_command(self, prompt: str, output_dir: Path) -> list[str]:
        cmd = [
            "codex",
            "exec",
            "--json",
            "--sandbox",
            "workspace-write",
            # Eval workspaces are freshly git-inited dirs codex has never
            # seen; without this codex blocks on its trust prompt.
            "--skip-git-repo-check",
        ]
        if self.model:
            cmd.extend(["--model", self.model])
        cmd.append(prompt)
        return cmd

    def parse_output(self, stdout: str, stderr: str) -> tuple[str, TimingData]:
        timing = TimingData()
        messages = []

        for line in stdout.strip().split("\n"):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                etype = event.get("type", "")

                if etype == "item.completed":
                    item = event.get("item", {})
                    if item.get("type") == "agent_message":
                        messages.append(item.get("text", ""))

                elif etype == "turn.completed":
                    usage = event.get("usage", {})
                    timing.input_tokens += usage.get("input_tokens", 0)
                    timing.output_tokens += usage.get("output_tokens", 0)
                    timing.cached_tokens += usage.get("cached_input_tokens", 0)

            except json.JSONDecodeError:
                continue

        timing.total_tokens = timing.input_tokens + timing.output_tokens
        return "\n".join(messages), timing


class FakeHarness(AgentHarness):
    agent_type = AgentType.FAKE

    def build_command(self, prompt: str, output_dir: Path) -> list[str]:
        return ["fake-agent", prompt]

    def parse_output(self, stdout: str, stderr: str) -> tuple[str, TimingData]:
        timing = TimingData(total_tokens=1, input_tokens=1, duration_ms=1)
        return stdout, timing

    def run(self, prompt: str, output_dir: Path) -> tuple[str, TimingData, str, str]:
        output_dir.mkdir(parents=True, exist_ok=True)
        skill_installed = any((self.workspace / ".fake" / "skills").glob("*/SKILL.md"))
        if skill_installed and ("format" in prompt.lower() or "$format-json" in prompt.lower()):
            final_output = '{\n  "formatted": true,\n  "status": "formatted-json-ok"\n}'
        else:
            final_output = "fake-agent baseline output: no formatting performed"

        stdout = final_output
        stderr = ""
        timing = TimingData(
            total_tokens=1, input_tokens=1, output_tokens=0, cached_tokens=0, duration_ms=1, exit_code=0
        )

        with open(output_dir / "stdout.log", "w", encoding="utf-8") as f:
            f.write(stdout)
        with open(output_dir / "stderr.log", "w", encoding="utf-8") as f:
            f.write(stderr)

        return final_output, timing, stdout, stderr


HARNESSES: dict[AgentType, type[AgentHarness]] = {
    AgentType.OPENCODE: OpenCodeHarness,
    AgentType.CLAUDE_CODE: ClaudeCodeHarness,
    AgentType.CODEX: CodexHarness,
    AgentType.FAKE: FakeHarness,
}


def get_harness(
    agent_type: AgentType,
    workspace: Path,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: Optional[int] = None,
    max_retries: Optional[int] = None,
) -> AgentHarness:
    cls = HARNESSES[agent_type]
    return cls(workspace, model, base_url=base_url, timeout=timeout, max_retries=max_retries)
