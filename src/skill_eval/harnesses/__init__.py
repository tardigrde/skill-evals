from __future__ import annotations

import json
import subprocess
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from skill_eval.models import AgentType, TimingData


class AgentHarness(ABC):
    agent_type: AgentType

    def __init__(self, workspace: Path, model: Optional[str] = None):
        self.workspace = workspace
        self.model = model

    @abstractmethod
    def build_command(self, prompt: str, output_dir: Path) -> list[str]:
        pass

    @abstractmethod
    def parse_output(self, stdout: str, stderr: str) -> tuple[str, TimingData]:
        pass

    def run(self, prompt: str, output_dir: Path) -> tuple[str, TimingData, str, str]:
        output_dir.mkdir(parents=True, exist_ok=True)

        cmd = self.build_command(prompt, output_dir)

        start = time.time()
        result = subprocess.run(
            cmd,
            cwd=self.workspace,
            capture_output=True,
            text=True,
            timeout=600,
        )
        duration_ms = int((time.time() - start) * 1000)

        stdout = result.stdout or ""
        stderr = result.stderr or ""

        final_output, timing = self.parse_output(stdout, stderr)
        if timing.duration_ms == 0:
            timing.duration_ms = duration_ms

        with open(output_dir / "stdout.log", "w") as f:
            f.write(stdout)
        with open(output_dir / "stderr.log", "w") as f:
            f.write(stderr)

        return final_output, timing, stdout, stderr


class OpenCodeHarness(AgentHarness):
    agent_type = AgentType.OPENCODE

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

            except json.JSONDecodeError:
                continue

        timing.total_tokens = timing.input_tokens + timing.output_tokens
        return "\n".join(messages), timing


class ClaudeCodeHarness(AgentHarness):
    agent_type = AgentType.CLAUDE_CODE

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
                timing.total_tokens = timing.input_tokens + timing.output_tokens
                duration_s = data.get("duration_ms", 0)
                if duration_s:
                    timing.duration_ms = duration_s
                cost = data.get("cost_usd", 0)
                if cost:
                    timing.total_tokens = timing.total_tokens or 0
        except json.JSONDecodeError:
            final_text = stdout

        return final_text, timing


class CodexHarness(AgentHarness):
    agent_type = AgentType.CODEX

    def build_command(self, prompt: str, output_dir: Path) -> list[str]:
        cmd = [
            "codex",
            "exec",
            "--json",
            "--full-auto",
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


HARNESSES: dict[AgentType, type[AgentHarness]] = {
    AgentType.OPENCODE: OpenCodeHarness,
    AgentType.CLAUDE_CODE: ClaudeCodeHarness,
    AgentType.CODEX: CodexHarness,
}


def get_harness(agent_type: AgentType, workspace: Path, model: Optional[str] = None) -> AgentHarness:
    cls = HARNESSES[agent_type]
    return cls(workspace, model)
