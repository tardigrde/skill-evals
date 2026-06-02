from __future__ import annotations

import json
import os
import re
from pathlib import Path

from openai import OpenAI, OpenAIError

from skill_eval.models import AssertionResult, GradingResult, GradingSummary


class DeterministicGrader:
    def grade(
        self, assertions: list[str], output_dir: Path, agent_output: str, workspace: Path | None = None
    ) -> list[AssertionResult]:
        results = []
        for assertion in assertions:
            result = self._check_assertion(assertion, output_dir, agent_output, workspace)
            results.append(result)
        return results

    def _check_assertion(
        self, assertion: str, output_dir: Path, agent_output: str, workspace: Path | None = None
    ) -> AssertionResult:
        assertion_lower = assertion.lower()

        if "branch" in assertion_lower and (
            "created" in assertion_lower or "exists" in assertion_lower or "new" in assertion_lower
        ):
            return self._check_git_branch(assertion, output_dir, workspace)

        if "commit" in assertion_lower and (
            "created" in assertion_lower or "exists" in assertion_lower or "new" in assertion_lower
        ):
            return self._check_git_commit(assertion, output_dir, workspace)

        if "push" in assertion_lower and (
            "remote" in assertion_lower or "branch" in assertion_lower or "pushed" in assertion_lower
        ):
            return self._check_pushed(assertion, output_dir, agent_output, workspace)

        if "pr" in assertion_lower or "pull request" in assertion_lower:
            return self._check_pr_created(assertion, output_dir, agent_output, workspace)

        if "file exists" in assertion_lower or (
            "created" in assertion_lower and any(c in assertion_lower for c in [".", "file"])
        ):
            return self._check_file_exists(assertion, output_dir, workspace)

        if "ran" in assertion_lower and (
            "command" in assertion_lower
            or any(cmd in assertion_lower for cmd in ["npm", "git", "python", "cargo", "go"])
        ):
            return self._check_command_ran(assertion, output_dir)

        if "contains" in assertion_lower or "includes" in assertion_lower:
            return self._check_content_contains(assertion, agent_output)

        if "valid json" in assertion_lower:
            return self._check_valid_json(assertion, output_dir, agent_output, workspace)

        return AssertionResult(
            text=assertion,
            passed=False,
            evidence=f"Could not deterministically check: {assertion}",
        )

    def _resolve_workspace(self, output_dir: Path, workspace: Path | None) -> Path:
        if workspace:
            return workspace
        if "with_skill" in str(output_dir) or "without_skill" in str(output_dir):
            return output_dir.parent.parent
        return output_dir.parent

    def _check_file_exists(self, assertion: str, output_dir: Path, workspace: Path | None = None) -> AssertionResult:
        ws = self._resolve_workspace(output_dir, workspace)

        patterns = re.findall(r"`([^`]+)`", assertion)
        if not patterns:
            patterns = re.findall(r'"([^"]+)"', assertion)
        if not patterns:
            words = assertion.split()
            for w in words:
                if "." in w and "/" not in w:
                    patterns.append(w)

        for pattern in patterns:
            candidates = list(ws.rglob(pattern))
            if candidates:
                return AssertionResult(
                    text=assertion,
                    passed=True,
                    evidence=f"Found: {candidates[0].relative_to(ws)}",
                )

        return AssertionResult(
            text=assertion,
            passed=False,
            evidence=f"File not found in workspace. Searched for: {patterns}",
        )

    def _check_command_ran(self, assertion: str, output_dir: Path) -> AssertionResult:
        stderr_log = output_dir / "stderr.log"
        stdout_log = output_dir / "stdout.log"

        commands_to_check = []
        for cmd in ["npm", "git", "python", "cargo", "go", "yarn", "pnpm"]:
            if cmd in assertion.lower():
                commands_to_check.append(cmd)

        for log_file in [stderr_log, stdout_log]:
            if not log_file.exists():
                continue
            content = log_file.read_text().lower()
            for cmd in commands_to_check:
                if cmd in content:
                    return AssertionResult(
                        text=assertion,
                        passed=True,
                        evidence=f"Found '{cmd}' in {log_file.name}",
                    )

        return AssertionResult(
            text=assertion,
            passed=False,
            evidence="Command not found in logs",
        )

    def _check_content_contains(self, assertion: str, agent_output: str) -> AssertionResult:
        patterns = re.findall(r'"([^"]+)"', assertion)
        if not patterns:
            patterns = re.findall(r"`([^`]+)`", assertion)

        output_lower = agent_output.lower()
        for pattern in patterns:
            if pattern.lower() in output_lower:
                return AssertionResult(
                    text=assertion,
                    passed=True,
                    evidence=f"Found '{pattern}' in output",
                )

        return AssertionResult(
            text=assertion,
            passed=False,
            evidence=f"Pattern not found in output. Searched for: {patterns}",
        )

    def _check_valid_json(
        self, assertion: str, output_dir: Path, agent_output: str, workspace: Path | None = None
    ) -> AssertionResult:
        try:
            json.loads(agent_output)
            return AssertionResult(text=assertion, passed=True, evidence="Output is valid JSON")
        except json.JSONDecodeError:
            pass

        ws = self._resolve_workspace(output_dir, workspace)
        for json_file in ws.rglob("*.json"):
            try:
                json.loads(json_file.read_text())
                return AssertionResult(
                    text=assertion,
                    passed=True,
                    evidence=f"Found valid JSON: {json_file.relative_to(ws)}",
                )
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

        return AssertionResult(text=assertion, passed=False, evidence="No valid JSON found")

    def _check_git_branch(self, assertion: str, output_dir: Path, workspace: Path | None = None) -> AssertionResult:
        import subprocess

        ws = self._resolve_workspace(output_dir, workspace)

        try:
            result = subprocess.run(
                ["git", "branch", "-a"],
                cwd=ws,
                capture_output=True,
                text=True,
            )
            branches = result.stdout.strip().split("\n")
            branches = [b.strip().lstrip("* ") for b in branches if b.strip()]

            non_main_branches = [b for b in branches if "main" not in b and "HEAD" not in b]

            if non_main_branches:
                return AssertionResult(
                    text=assertion,
                    passed=True,
                    evidence=f"Branches found: {', '.join(non_main_branches[:3])}",
                )
        except Exception as e:
            return AssertionResult(text=assertion, passed=False, evidence=f"Git error: {e}")

        return AssertionResult(text=assertion, passed=False, evidence="No new branch found")

    def _check_git_commit(self, assertion: str, output_dir: Path, workspace: Path | None = None) -> AssertionResult:
        import subprocess

        ws = self._resolve_workspace(output_dir, workspace)

        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "-5"],
                cwd=ws,
                capture_output=True,
                text=True,
            )
            commits = result.stdout.strip().split("\n")
            if len(commits) > 1:
                return AssertionResult(
                    text=assertion,
                    passed=True,
                    evidence=f"Commits found: {len(commits)}",
                )
        except Exception as e:
            return AssertionResult(text=assertion, passed=False, evidence=f"Git error: {e}")

        return AssertionResult(text=assertion, passed=False, evidence="No new commits found")

    def _check_pushed(
        self, assertion: str, output_dir: Path, agent_output: str, workspace: Path | None = None
    ) -> AssertionResult:
        import subprocess

        ws = self._resolve_workspace(output_dir, workspace)

        try:
            result = subprocess.run(
                ["git", "log", "--remotes", "--oneline", "-5"],
                cwd=ws,
                capture_output=True,
                text=True,
            )
            if result.stdout.strip():
                return AssertionResult(
                    text=assertion,
                    passed=True,
                    evidence=f"Remote branches have commits: {result.stdout.strip()[:100]}",
                )
        except Exception:
            pass

        push_indicators = ["push", "pushed", "git push", "origin"]
        output_lower = agent_output.lower()

        for indicator in push_indicators:
            if indicator in output_lower:
                return AssertionResult(
                    text=assertion,
                    passed=True,
                    evidence=f"Found push indicator '{indicator}' in output",
                )

        stderr_log = output_dir / "stderr.log"
        if stderr_log.exists():
            stderr_content = stderr_log.read_text().lower()
            for indicator in push_indicators:
                if indicator in stderr_content:
                    return AssertionResult(
                        text=assertion,
                        passed=True,
                        evidence=f"Found push indicator '{indicator}' in stderr",
                    )

        return AssertionResult(text=assertion, passed=False, evidence="No push evidence found")

    def _check_pr_created(
        self, assertion: str, output_dir: Path, agent_output: str, workspace: Path | None = None
    ) -> AssertionResult:
        import subprocess

        ws = self._resolve_workspace(output_dir, workspace)

        try:
            result = subprocess.run(
                ["gh", "pr", "list", "--state", "open", "--limit", "5"],
                cwd=ws,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                return AssertionResult(
                    text=assertion,
                    passed=True,
                    evidence=f"Open PRs found: {result.stdout.strip()[:100]}",
                )
        except Exception:
            pass

        pr_indicators = ["pull request", "/pull/", "merge request"]
        output_lower = agent_output.lower()

        for indicator in pr_indicators:
            if indicator in output_lower:
                return AssertionResult(
                    text=assertion,
                    passed=True,
                    evidence=f"Found PR indicator '{indicator}' in output",
                )

        stderr_log = output_dir / "stderr.log"
        if stderr_log.exists():
            stderr_content = stderr_log.read_text().lower()
            for indicator in pr_indicators:
                if indicator in stderr_content:
                    return AssertionResult(
                        text=assertion,
                        passed=True,
                        evidence=f"Found PR indicator '{indicator}' in stderr",
                    )

        return AssertionResult(text=assertion, passed=False, evidence="No PR creation evidence found")


class LLMGrader:
    def __init__(self, model: str = "deepseek/deepseek-v4-flash", base_url: str | None = None):
        self.model = model
        self.base_url = base_url
        self._client = None

    @property
    def client(self):
        if self._client is None:
            api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                raise OpenAIError("OPENROUTER_API_KEY or OPENAI_API_KEY not set. Set it via environment variable.")
            base_url = self.base_url or os.environ.get("OPENAI_BASE_URL") or "https://openrouter.ai/api/v1"
            self._client = OpenAI(
                api_key=api_key,
                base_url=base_url,
            )
        return self._client

    def grade(
        self,
        assertions: list[str],
        agent_output: str,
        output_dir: Path,
        expected_output: str,
    ) -> list[AssertionResult]:
        if not assertions:
            return []

        workspace = output_dir.parent.parent if "with_skill" in str(output_dir) else output_dir.parent
        file_listing = self._list_workspace_files(workspace)

        prompt = f"""You are grading an AI agent's output against specific assertions.

## Expected Output
{expected_output}

## Agent's Actual Output
{agent_output}

## Workspace Files
{file_listing}

## Assertions to Grade
{chr(10).join(f"{i + 1}. {a}" for i, a in enumerate(assertions))}

For each assertion, respond with JSON:
{{
  "results": [
    {{"text": "<assertion text>", "passed": true/false, "evidence": "<specific evidence from output>"}}
  ]
}}

Be strict: only mark PASS if there is clear evidence. Quote the output in evidence."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0,
            )
            data = json.loads(response.choices[0].message.content)
            results = []
            for r in data.get("results", []):
                results.append(
                    AssertionResult(
                        text=r["text"],
                        passed=r["passed"],
                        evidence=r["evidence"],
                    )
                )
            return results
        except Exception as e:
            return [AssertionResult(text=a, passed=False, evidence=f"LLM grading error: {e}") for a in assertions]

    def _list_workspace_files(self, workspace: Path) -> str:
        files = []
        for f in workspace.rglob("*"):
            if f.is_file() and ".git" not in str(f):
                try:
                    rel = f.relative_to(workspace)
                    size = f.stat().st_size
                    files.append(f"{rel} ({size} bytes)")
                except Exception:
                    continue
        return "\n".join(files[:50]) if files else "(empty workspace)"


def grade_assertions(
    assertions: list[str],
    agent_output: str,
    output_dir: Path,
    expected_output: str,
    llm_grader: LLMGrader | None = None,
    workspace: Path | None = None,
) -> GradingResult:
    det_grader = DeterministicGrader()
    det_results = det_grader.grade(assertions, output_dir, agent_output, workspace=workspace)

    undetermined = [r for r in det_results if "Could not deterministically check" in r.evidence]
    determined = [r for r in det_results if "Could not deterministically check" not in r.evidence]

    if undetermined and llm_grader:
        undetermined_texts = [r.text for r in undetermined]
        llm_results = llm_grader.grade(undetermined_texts, agent_output, output_dir, expected_output)
        all_results = determined + llm_results
    else:
        all_results = det_results

    passed = sum(1 for r in all_results if r.passed)
    failed = sum(1 for r in all_results if not r.passed)
    total = len(all_results)

    return GradingResult(
        assertion_results=all_results,
        summary=GradingSummary(
            passed=passed,
            failed=failed,
            total=total,
            pass_rate=passed / total if total > 0 else 0.0,
        ),
    )
