from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional

from openai import OpenAI, OpenAIError

from skill_eval.git_state import capture_git_state, state_diff
from skill_eval.models import AssertionResult, GitStateSnapshot, GradingResult, GradingSummary


def _load_state(path: Path) -> Optional[GitStateSnapshot]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return GitStateSnapshot(**data)
    except (json.JSONDecodeError, ValueError):
        return None


class DeterministicGrader:
    """Grades assertions against the *delta* caused by the agent during a run.

    Prefers persisted pre/post git state snapshots (``pre_state.json``,
    ``post_state.json``) written by the runner so that regrading works even
    after the workspace is deleted. Falls back to capturing live state from
    the workspace when snapshots are missing.
    """

    def __init__(
        self,
        pre_state: GitStateSnapshot | None = None,
        post_state: GitStateSnapshot | None = None,
    ):
        self.pre_state = pre_state
        self.post_state = post_state

    def grade(
        self,
        assertions: list[str],
        output_dir: Path,
        agent_output: str,
        workspace: Path | None = None,
        should_trigger: bool = True,
    ) -> list[AssertionResult]:
        pre, post = self._resolve_states(output_dir, workspace)
        self.pre_state = pre
        self.post_state = post
        diff = state_diff(pre, post) if pre and post else {}

        results = []
        for assertion in assertions:
            result = self._check_assertion(assertion, output_dir, agent_output, workspace, should_trigger, diff)
            results.append(result)
        return results

    def _resolve_states(
        self, output_dir: Path, workspace: Path | None
    ) -> tuple[Optional[GitStateSnapshot], Optional[GitStateSnapshot]]:
        if self.pre_state is not None and self.post_state is not None:
            return self.pre_state, self.post_state

        pre_path = output_dir / "pre_state.json"
        post_path = output_dir / "post_state.json"
        pre = _load_state(pre_path)
        post = _load_state(post_path)

        if pre is not None and post is not None:
            return pre, post

        if workspace is None:
            workspace = self._resolve_workspace(output_dir, None)

        try:
            captured = capture_git_state(workspace)
        except Exception:
            return pre, post

        return pre or GitStateSnapshot(), captured

    def _check_assertion(
        self,
        assertion: str,
        output_dir: Path,
        agent_output: str,
        workspace: Path | None,
        should_trigger: bool,
        diff: dict,
    ) -> AssertionResult:
        assertion_lower = assertion.lower()

        if "branch" in assertion_lower and (
            "created" in assertion_lower or "exists" in assertion_lower or "new" in assertion_lower
        ):
            return self._check_git_branch(assertion, diff, should_trigger)

        if "commit" in assertion_lower and (
            "created" in assertion_lower or "exists" in assertion_lower or "new" in assertion_lower
        ):
            return self._check_git_commit(assertion, diff, should_trigger)

        if "push" in assertion_lower and (
            "remote" in assertion_lower or "branch" in assertion_lower or "pushed" in assertion_lower
        ):
            return self._check_pushed(assertion, diff, agent_output, should_trigger)

        if "pr" in assertion_lower or "pull request" in assertion_lower:
            return self._check_pr_created(assertion, diff, agent_output, should_trigger)

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

    def _invert(self, should_trigger: bool) -> bool:
        """For negative controls, branch/commit/push/pr assertions are inverted."""
        return not should_trigger

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

        if not ws.exists():
            return AssertionResult(
                text=assertion,
                passed=False,
                evidence=f"Workspace not available. Searched for: {patterns}",
            )

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
        if not ws.exists():
            return AssertionResult(text=assertion, passed=False, evidence="Workspace not available for JSON check")

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

    def _check_git_branch(self, assertion: str, diff: dict, should_trigger: bool) -> AssertionResult:
        inverted = self._invert(should_trigger)
        new_branches = diff.get("new_branches", []) or []
        branch_changed = diff.get("current_branch_changed", False)

        if inverted:
            if new_branches or branch_changed:
                return AssertionResult(
                    text=assertion,
                    passed=False,
                    evidence=(
                        f"Skill should not have triggered, but new branches appeared: "
                        f"{new_branches or 'current branch changed'}"
                    ),
                )
            return AssertionResult(
                text=assertion,
                passed=True,
                evidence="No new branch was created (skill did not trigger)",
            )

        if not new_branches and not branch_changed:
            return AssertionResult(
                text=assertion,
                passed=False,
                evidence="No new branch appeared in this run (pre/post state unchanged)",
            )
        return AssertionResult(
            text=assertion,
            passed=True,
            evidence=(
                f"New branch(es) created: {', '.join(new_branches)}"
                if new_branches
                else f"Current branch changed to: {diff.get('current_branch', '?')}"
            ),
        )

    def _check_git_commit(self, assertion: str, diff: dict, should_trigger: bool) -> AssertionResult:
        inverted = self._invert(should_trigger)
        advanced = diff.get("head_advanced", False)
        new_commits = diff.get("new_commits", []) or []

        if inverted:
            if advanced:
                return AssertionResult(
                    text=assertion,
                    passed=False,
                    evidence="Skill should not have triggered, but HEAD advanced",
                )
            return AssertionResult(
                text=assertion,
                passed=True,
                evidence="HEAD did not advance (skill did not trigger)",
            )

        if not advanced:
            return AssertionResult(
                text=assertion,
                passed=False,
                evidence="HEAD did not advance from baseline (no new commit)",
            )
        return AssertionResult(
            text=assertion,
            passed=True,
            evidence=f"HEAD advanced; {len(new_commits)} new commit(s)",
        )

    def _check_pushed(self, assertion: str, diff: dict, agent_output: str, should_trigger: bool) -> AssertionResult:
        inverted = self._invert(should_trigger)
        new_remote_branches = diff.get("new_remote_branches", []) or []

        if inverted:
            if new_remote_branches:
                return AssertionResult(
                    text=assertion,
                    passed=False,
                    evidence=(
                        f"Skill should not have triggered, but new remote branches appeared: {new_remote_branches}"
                    ),
                )
            return AssertionResult(
                text=assertion,
                passed=True,
                evidence="No new remote branches (skill did not trigger)",
            )

        if new_remote_branches:
            return AssertionResult(
                text=assertion,
                passed=True,
                evidence=f"New remote branches: {', '.join(new_remote_branches)}",
            )

        return AssertionResult(
            text=assertion,
            passed=False,
            evidence="No new remote branches appeared in this run",
        )

    def _check_pr_created(self, assertion: str, diff: dict, agent_output: str, should_trigger: bool) -> AssertionResult:
        inverted = self._invert(should_trigger)
        new_prs = diff.get("new_open_prs", []) or []

        if inverted:
            if new_prs:
                return AssertionResult(
                    text=assertion,
                    passed=False,
                    evidence=f"Skill should not have triggered, but new PR(s) appeared: "
                    f"{[p.get('number') for p in new_prs]}",
                )
            return AssertionResult(
                text=assertion,
                passed=True,
                evidence="No new PRs were opened (skill did not trigger)",
            )

        if new_prs:
            numbers = [p.get("number") for p in new_prs]
            return AssertionResult(
                text=assertion,
                passed=True,
                evidence=f"New PR(s) opened: {numbers}",
            )

        return AssertionResult(
            text=assertion,
            passed=False,
            evidence="No new PRs appeared in this run (state diff shows no new PRs)",
        )


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
    pre_state: GitStateSnapshot | None = None,
    post_state: GitStateSnapshot | None = None,
    should_trigger: bool = True,
) -> GradingResult:
    det_grader = DeterministicGrader(pre_state=pre_state, post_state=post_state)
    det_results = det_grader.grade(
        assertions, output_dir, agent_output, workspace=workspace, should_trigger=should_trigger
    )

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
