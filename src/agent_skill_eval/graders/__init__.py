from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

from openai import OpenAI, OpenAIError
from rich.console import Console

from agent_skill_eval.git_state import capture_git_state, github_repo_slug, state_diff
from agent_skill_eval.models import AssertionResult, GitStateSnapshot, GradingResult, GradingSummary

console = Console(stderr=True)


def classify_assertion(assertion: str) -> str:
    """Return the deterministic check an assertion text routes to, or ``"llm"``.

    Mirrors the routing in ``DeterministicGrader._check_assertion`` exactly.
    ``validate`` uses this to show suite authors which assertions will fall
    through to the LLM rubric (nondeterministic, needs an API key) instead of
    that happening silently at run time.
    """
    assertion_lower = assertion.lower()

    if "branch" in assertion_lower and (
        "created" in assertion_lower or "exists" in assertion_lower or "new" in assertion_lower
    ):
        return "git-branch"

    if "commit" in assertion_lower and (
        "created" in assertion_lower or "exists" in assertion_lower or "new" in assertion_lower
    ):
        return "git-commit"

    if "push" in assertion_lower and (
        "remote" in assertion_lower or "branch" in assertion_lower or "pushed" in assertion_lower
    ):
        return "pushed"

    # Word-boundary match: a bare "pr" substring would also match
    # "prominently", "present", "approach", etc.
    if re.search(r"\bprs?\b|\bpull request", assertion_lower):
        return "pr-created"

    if (
        "file exists" in assertion_lower
        or ("file" in assertion_lower and "exists" in assertion_lower)
        or ("created" in assertion_lower and any(c in assertion_lower for c in [".", "file"]))
    ):
        return "file-exists"

    if "ran" in assertion_lower and (
        "command" in assertion_lower or any(cmd in assertion_lower for cmd in ["npm", "git", "python", "cargo", "go"])
    ):
        return "command-ran"

    if "contains" in assertion_lower or "includes" in assertion_lower:
        # Without a quoted/backticked pattern this is a prose assertion that
        # happens to contain "contains"/"includes"; it goes to the LLM rubric.
        if re.findall(r'"([^"]+)"', assertion) or re.findall(r"`([^`]+)`", assertion):
            return "content-contains"
        return "llm"

    if "valid json" in assertion_lower:
        return "valid-json"

    return "llm"


def _resolve_workspace_path(output_dir: Path, workspace: Path | None) -> Path:
    """Resolve the agent workspace used for file-based checks.

    Prefers the explicitly passed workspace. Falls back to guessing from the
    output directory layout, which is unreliable (e.g. when re-grading after
    the per-eval workspace was deleted) — so the fallback warns instead of
    happening silently.
    """
    if workspace is not None and workspace.exists():
        return workspace
    if "with_skill" in str(output_dir) or "without_skill" in str(output_dir):
        guess = output_dir.parent.parent
    else:
        guess = output_dir.parent
    key = str(output_dir)
    if key not in _warned_fallback_dirs:
        _warned_fallback_dirs.add(key)
        console.print(
            f"[yellow]Warning: no live workspace for {output_dir}; file-based checks fall back to "
            f"{guess} (saved artifacts only). Results may differ from the original run.[/yellow]"
        )
    return guess


# Output dirs we already warned about, so the deterministic and LLM graders
# don't each repeat the same workspace-fallback warning for one run.
_warned_fallback_dirs: set[str] = set()


def _is_open_pr_state(state: Optional[str]) -> bool:
    """True if a PR state string represents an open PR.

    ``gh pr list --state all`` returns PRs with state ``OPEN``, ``CLOSED``,
    or ``MERGED``. A missing/empty state is treated as not-open so we never
    falsely satisfy a PR-created assertion on a stale or partial snapshot.
    """
    if not state:
        return False
    return str(state).upper() == "OPEN"


def _fetch_pr_for_branch(branch: str, source_repo: str) -> Optional[dict]:
    """Look up a PR for ``branch`` in ``source_repo`` via ``gh pr view``.

    Returns the parsed JSON dict on success, or ``None`` if ``gh`` is not
    available, the repo is not configured, the PR is not found, or the
    output cannot be parsed. Never raises.
    """
    if not source_repo or not branch:
        return None
    slug = github_repo_slug(source_repo)
    if not slug:
        return None
    try:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "view",
                branch,
                "--repo",
                slug,
                "--json",
                "number,headRefName,baseRefName,url,state",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


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
        method = classify_assertion(assertion)

        if method == "git-branch":
            return self._check_git_branch(assertion, diff, should_trigger)
        if method == "git-commit":
            return self._check_git_commit(assertion, diff, should_trigger)
        if method == "pushed":
            return self._check_pushed(assertion, diff, agent_output, should_trigger)
        if method == "pr-created":
            return self._check_pr_created(assertion, diff, agent_output, should_trigger, output_dir)
        if method == "file-exists":
            return self._check_file_exists(assertion, output_dir, workspace)
        if method == "command-ran":
            return self._check_command_ran(assertion, output_dir)
        if method == "content-contains":
            return self._check_content_contains(assertion, agent_output)
        if method == "valid-json":
            return self._check_valid_json(assertion, output_dir, agent_output, workspace)

        return AssertionResult(
            text=assertion,
            passed=False,
            evidence=f"Could not deterministically check: {assertion}",
            method="unknown",
        )

    def _resolve_workspace(self, output_dir: Path, workspace: Path | None) -> Path:
        return _resolve_workspace_path(output_dir, workspace)

    def _invert(self, should_trigger: bool) -> bool:
        """For negative controls, branch/commit/push/pr assertions are inverted."""
        return not should_trigger

    def _source_repo_from_meta(self, output_dir: Path | None) -> Optional[str]:
        """Read ``source_repo`` from ``run_meta.json`` adjacent to ``outputs/``.

        Returns ``None`` when no metadata is available or the field is unset.
        The grader uses this to optionally corroborate PR checks via
        ``gh pr view <branch>`` for a real-time validation pass.
        """
        if output_dir is None:
            return None
        meta_path = output_dir.parent / "run_meta.json"
        if not meta_path.exists():
            return None
        try:
            data = json.loads(meta_path.read_text())
        except (json.JSONDecodeError, OSError, ValueError):
            return None
        repo = data.get("source_repo")
        return str(repo) if repo else None

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

        if not patterns:
            # No quoted/backticked pattern to search for: this is a prose
            # assertion that happens to contain "contains"/"includes".
            # Fall through to the LLM grader instead of failing it.
            return AssertionResult(
                text=assertion,
                passed=False,
                evidence=f"Could not deterministically check: {assertion}",
                method="unknown",
            )

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
        eval_branch = diff.get("eval_branch")
        current_branch = diff.get("current_branch", "")
        branch_changed = diff.get("current_branch_changed", False)

        if inverted:
            if new_branches:
                return AssertionResult(
                    text=assertion,
                    passed=False,
                    evidence=(f"Skill should not have triggered, but new branches appeared: {new_branches}"),
                )
            if branch_changed and eval_branch:
                return AssertionResult(
                    text=assertion,
                    passed=False,
                    evidence=(
                        f"Skill should not have triggered, but current branch changed to "
                        f"new eval branch {current_branch!r}"
                    ),
                )
            return AssertionResult(
                text=assertion,
                passed=True,
                evidence="No new branch was created (skill did not trigger)",
            )

        if not new_branches:
            return AssertionResult(
                text=assertion,
                passed=False,
                evidence=(
                    f"No new branch appeared in this run. current_branch={current_branch!r}; no eval-created branch."
                ),
            )
        if eval_branch is None:
            return AssertionResult(
                text=assertion,
                passed=False,
                evidence=(
                    f"New branches {new_branches} appeared, but none is the current/eval branch. "
                    f"current_branch={current_branch!r}"
                ),
            )
        return AssertionResult(
            text=assertion,
            passed=True,
            evidence=f"New eval branch created and checked out: {eval_branch}",
        )

    def _check_git_commit(self, assertion: str, diff: dict, should_trigger: bool) -> AssertionResult:
        inverted = self._invert(should_trigger)
        advanced = diff.get("head_advanced", False)
        new_commits = diff.get("new_commits", []) or []
        new_commit_shas = diff.get("new_commit_shas", []) or []
        post_head = self.post_state.head_sha if self.post_state else ""

        if inverted:
            if new_commit_shas or new_commits:
                return AssertionResult(
                    text=assertion,
                    passed=False,
                    evidence="Skill should not have triggered, but new commit(s) were created",
                )
            return AssertionResult(
                text=assertion,
                passed=True,
                evidence="No new commit was created (skill did not trigger)",
            )

        if not new_commit_shas and not new_commits:
            return AssertionResult(
                text=assertion,
                passed=False,
                evidence=(
                    "HEAD may have moved, but no new commit was created in this run. "
                    f"head_advanced={advanced}, new_commits={new_commits}"
                ),
            )
        if new_commit_shas and post_head and post_head not in new_commit_shas:
            return AssertionResult(
                text=assertion,
                passed=False,
                evidence=(
                    f"New commit(s) appeared ({len(new_commit_shas)}), but current HEAD "
                    f"({post_head[:12]}) is not one of them. The new commit is not on the "
                    f"current branch."
                ),
            )
        return AssertionResult(
            text=assertion,
            passed=True,
            evidence=f"New commit on current branch (HEAD {post_head[:12] if post_head else '?'})",
        )

    def _check_pushed(self, assertion: str, diff: dict, agent_output: str, should_trigger: bool) -> AssertionResult:
        inverted = self._invert(should_trigger)
        new_remote_branches = diff.get("new_remote_branches", []) or []
        eval_branch = diff.get("eval_branch")
        eval_branch_pushed = diff.get("eval_branch_pushed", False)
        eval_branch_pushed_matches_head = diff.get("eval_branch_pushed_matches_head", False)
        post_head = self.post_state.head_sha if self.post_state else ""

        if inverted:
            if new_remote_branches:
                return AssertionResult(
                    text=assertion,
                    passed=False,
                    evidence=(
                        f"Skill should not have triggered, but new remote branches appeared: {new_remote_branches}"
                    ),
                )
            if eval_branch_pushed:
                return AssertionResult(
                    text=assertion,
                    passed=False,
                    evidence="Skill should not have triggered, but eval branch was pushed",
                )
            return AssertionResult(
                text=assertion,
                passed=True,
                evidence="No new remote branches (skill did not trigger)",
            )

        if not eval_branch:
            return AssertionResult(
                text=assertion,
                passed=False,
                evidence=("No eval-created branch in this run; cannot verify that the right branch was pushed."),
            )
        if not eval_branch_pushed:
            return AssertionResult(
                text=assertion,
                passed=False,
                evidence=(f"Eval branch {eval_branch!r} was not pushed. new_remote_branches={new_remote_branches}"),
            )
        if not eval_branch_pushed_matches_head:
            return AssertionResult(
                text=assertion,
                passed=False,
                evidence=(
                    f"Eval branch {eval_branch!r} was pushed, but its remote HEAD does not "
                    f"match the local HEAD ({post_head[:12] if post_head else '?'})."
                ),
            )
        return AssertionResult(
            text=assertion,
            passed=True,
            evidence=(f"Eval branch {eval_branch!r} pushed with HEAD {post_head[:12] if post_head else '?'}"),
        )

    def _check_pr_created(
        self,
        assertion: str,
        diff: dict,
        agent_output: str,
        should_trigger: bool,
        output_dir: Path | None = None,
    ) -> AssertionResult:
        inverted = self._invert(should_trigger)
        new_prs = diff.get("new_open_prs", []) or []
        eval_branch = diff.get("eval_branch")

        source_repo = self._source_repo_from_meta(output_dir)
        live_pr: Optional[dict] = None
        if source_repo and eval_branch:
            live_pr = _fetch_pr_for_branch(eval_branch, source_repo)

        if inverted:
            if new_prs:
                return AssertionResult(
                    text=assertion,
                    passed=False,
                    evidence=(
                        f"Skill should not have triggered, but new PR(s) appeared: {[p.get('number') for p in new_prs]}"
                    ),
                )
            if live_pr and _is_open_pr_state(live_pr.get("state")):
                return AssertionResult(
                    text=assertion,
                    passed=False,
                    evidence=(
                        f"Skill should not have triggered, but gh pr view reports an "
                        f"open PR for {eval_branch!r} (#{live_pr.get('number')})"
                    ),
                )
            return AssertionResult(
                text=assertion,
                passed=True,
                evidence="No new PRs were opened (skill did not trigger)",
            )

        if not new_prs:
            if live_pr and _is_open_pr_state(live_pr.get("state")):
                return AssertionResult(
                    text=assertion,
                    passed=True,
                    evidence=(
                        f"State snapshot shows no new PRs, but gh pr view confirms an "
                        f"open PR #{live_pr.get('number')} for eval branch {eval_branch!r}"
                    ),
                )
            return AssertionResult(
                text=assertion,
                passed=False,
                evidence="No new PRs appeared in this run (state diff shows no new PRs)",
            )
        if not eval_branch:
            return AssertionResult(
                text=assertion,
                passed=False,
                evidence=(
                    f"New PR(s) {[p.get('number') for p in new_prs]} appeared, but no "
                    f"eval-created branch was identified in this run; cannot verify the "
                    f"PR is for the eval branch."
                ),
            )
        matching = [p for p in new_prs if p.get("headRefName") == eval_branch and _is_open_pr_state(p.get("state"))]
        if not matching:
            return AssertionResult(
                text=assertion,
                passed=False,
                evidence=(
                    f"New PR(s) {[p.get('number') for p in new_prs]} appeared, but none "
                    f"have headRefName matching eval branch {eval_branch!r} with state OPEN. "
                    f"head refs: {[p.get('headRefName') for p in new_prs]}, "
                    f"states: {[p.get('state') for p in new_prs]}"
                ),
            )

        if live_pr is not None and not _is_open_pr_state(live_pr.get("state")):
            return AssertionResult(
                text=assertion,
                passed=False,
                evidence=(
                    f"State snapshot shows open PR(s) {[p.get('number') for p in matching]} "
                    f"for eval branch {eval_branch!r}, but gh pr view reports the PR is "
                    f"{live_pr.get('state')!r}; the PR was likely closed/merged between "
                    f"snapshot and grading."
                ),
            )

        numbers = [p.get("number") for p in matching]
        evidence = f"PR(s) for eval branch {eval_branch!r}: {numbers}"
        if live_pr is not None:
            evidence += f" (corroborated by gh pr view: state={live_pr.get('state')!r})"
        return AssertionResult(
            text=assertion,
            passed=True,
            evidence=evidence,
        )


class LLMGrader:
    def __init__(self, model: str = "deepseek/deepseek-v4-flash", base_url: str | None = None):
        self.model = model
        self.base_url = base_url
        self._client = None

    @staticmethod
    def has_credentials() -> bool:
        """True if an API key for the grader is available in the environment."""
        return bool(os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY"))

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
        workspace: Path | None = None,
    ) -> list[AssertionResult]:
        if not assertions:
            return []

        workspace = _resolve_workspace_path(output_dir, workspace)
        file_listing = self._list_workspace_files(workspace)
        file_contents = self._read_workspace_files(workspace)

        prompt = f"""You are grading an AI agent's output against specific assertions.

## Expected Output
{expected_output}

## Agent's Actual Output
{agent_output}

## Workspace Files
{file_listing}

## Workspace File Contents
{file_contents}

## Assertions to Grade
{chr(10).join(f"{i + 1}. {a}" for i, a in enumerate(assertions))}

For each assertion, respond with JSON:
{{
  "results": [
    {{"text": "<assertion text>", "passed": true/false, "evidence": "<specific evidence from output>"}}
  ]
}}

Be strict: only mark PASS if there is clear evidence. Quote the output or file contents in evidence."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0,
            )
            data = json.loads(response.choices[0].message.content)
            results = []
            returned_texts = set()
            for r in data.get("results", []):
                results.append(
                    AssertionResult(
                        text=r["text"],
                        passed=r["passed"],
                        evidence=r["evidence"],
                        method="llm",
                    )
                )
                returned_texts.add(r["text"])
            missing = [a for a in assertions if a not in returned_texts]
            if missing:
                # The grader dropping an assertion is a grader failure, not an
                # agent failure: skip it so it doesn't drag down the pass rate.
                console.print(
                    f"[yellow]Warning: LLM grader returned no result for {len(missing)} assertion(s); "
                    f"skipped (not failed)[/yellow]"
                )
            for a in missing:
                results.append(
                    AssertionResult(
                        text=a,
                        passed=False,
                        evidence="LLM grader did not return a result for this assertion (skipped, not failed)",
                        method="llm",
                        skipped=True,
                    )
                )
            return results
        except Exception as e:
            # A grader failure is not an agent failure: mark the assertions as
            # skipped so they don't drag down the pass rate.
            console.print(
                f"[yellow]Warning: LLM grading failed ({e}); {len(assertions)} assertion(s) skipped, "
                f"not failed[/yellow]"
            )
            return [
                AssertionResult(
                    text=a,
                    passed=False,
                    evidence=f"LLM grading error (assertion skipped, not failed): {e}",
                    method="llm",
                    skipped=True,
                )
                for a in assertions
            ]

    # Skill-install and VCS dirs: listing them would leak the skill text into
    # the judge's context and drown out the agent's actual artifacts.
    _EXCLUDED_DIRS = (".git", ".claude", ".opencode", ".codex", ".fake")

    def _workspace_files(self, workspace: Path) -> list[Path]:
        files = []
        for root, dirs, filenames in os.walk(workspace):
            # Prune in-place so excluded trees are never traversed at all
            # (rglob would walk a full .git or node_modules before filtering).
            dirs[:] = [d for d in dirs if d not in self._EXCLUDED_DIRS]
            for filename in filenames:
                files.append(Path(root) / filename)
        return sorted(files)

    def _list_workspace_files(self, workspace: Path) -> str:
        files = []
        for f in self._workspace_files(workspace):
            try:
                rel = f.relative_to(workspace)
                size = f.stat().st_size
                files.append(f"{rel} ({size} bytes)")
            except Exception:
                continue
        return "\n".join(files[:50]) if files else "(empty workspace)"

    def _read_workspace_files(self, workspace: Path, max_files: int = 10, max_bytes: int = 4096) -> str:
        """Inline small text files so the judge can grade content assertions
        (e.g. "RELEASE_NOTES.md groups changes by type") against the actual
        artifacts, not just the agent's final message."""
        sections = []
        for f in self._workspace_files(workspace)[:max_files]:
            try:
                if f.stat().st_size > max_bytes:
                    continue
                content = f.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            rel = f.relative_to(workspace)
            sections.append(f"### {rel}\n```\n{content}\n```")
        return "\n\n".join(sections) if sections else "(no readable files)"


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
        llm_results = llm_grader.grade(
            undetermined_texts, agent_output, output_dir, expected_output, workspace=workspace
        )
        all_results = determined + llm_results
    elif undetermined:
        # No LLM grader available: skip these assertions instead of failing
        # them, so a missing API key doesn't masquerade as agent failure.
        skipped_results = [
            AssertionResult(
                text=r.text,
                passed=False,
                evidence=(
                    "Not deterministically checkable and no LLM grader configured "
                    "(set OPENROUTER_API_KEY or OPENAI_API_KEY); assertion skipped"
                ),
                method="skipped",
                skipped=True,
            )
            for r in undetermined
        ]
        all_results = determined + skipped_results
    else:
        all_results = det_results

    passed = sum(1 for r in all_results if r.passed)
    skipped = sum(1 for r in all_results if r.skipped)
    failed = sum(1 for r in all_results if not r.passed and not r.skipped)
    total = len(all_results)
    graded = total - skipped

    return GradingResult(
        assertion_results=all_results,
        summary=GradingSummary(
            passed=passed,
            failed=failed,
            total=total,
            pass_rate=passed / graded if graded > 0 else 0.0,
            skipped=skipped,
        ),
    )
