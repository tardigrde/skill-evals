# CHANGELOG


## v0.4.0 (2026-06-11)

### Bug Fixes

- Address Gemini review findings
  ([`641b98b`](https://github.com/tardigrde/agent-skill-eval/commit/641b98be6f791832eb396f00939eca5da3522316))

- cost accumulation test: float-safe compare via pytest.approx - Makefile: default CLAUDE_CODE_MODEL
  to a real Anthropic ID so the target works even without config/baseline.env - test-live: export
  model vars so e2e tests use configured models instead of hardcoded fallbacks

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

### Continuous Integration

- Replace tag-triggered publish with semantic-release on main
  ([`64a4cca`](https://github.com/tardigrde/agent-skill-eval/commit/64a4cca2a8c1461eef50339ad6eb909ed35658df))

Pushing to main now handles version bump, tag, GitHub release, and PyPI publish (trusted publishing)
  automatically from conventional commits — no manual tag push. Pattern borrowed from gcpath.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

### Features

- Codex harness fix, cost_usd metric, e2e milestone tests
  ([`bb34a28`](https://github.com/tardigrde/agent-skill-eval/commit/bb34a287521bd1f4deb07176d4d396bdf1429e83))

- CodexHarness: replace deprecated --full-auto with --sandbox workspace-write and add
  --skip-git-repo-check so codex runs in freshly git-inited eval workspaces without its trust
  prompt. - TimingData: new cost_usd field; claude-code parses total_cost_usd, opencode sums
  per-step cost. Cost, time, and accuracy are now all machine-readable per run for downstream skill
  optimization. - tests/test_e2e.py: two-tier end-to-end tests exercising the real CLI as a
  subprocess. Free tier (fake harness, no network) runs in every pytest invocation; live tier
  (claude-code, opencode, codex + LLM grader) is opt-in via the `live` marker and locks in the
  all-harnesses-complete-with-real-grades milestone. - Makefile: AGENTS variable, full-eval
  (includes codex), test-e2e and test-live targets; config/baseline.env pins
  claude-haiku-4-5-20251001 for claude-code (claude CLI validates --model client-side, so
  OpenRouter-only slugs are rejected).

Verified: make test-live 7/7 passed; 232 unit tests; lint clean.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

- Converge all names on agent-skill-eval, add ase alias
  ([`33f1084`](https://github.com/tardigrde/agent-skill-eval/commit/33f10842d56d2849fb04866bfbd0b230800de9a4))

Repo (skill-evals), CLI (skill-eval), and module (skill_eval) now all match the PyPI package name
  agent-skill-eval. Short alias `ase` installs alongside the full command. Env var prefix
  SKILL_EVAL_* renamed to ASE_*. Version 0.4.0.

Skills remain the only eval target for now; subagent evals are noted as coming soon in the README.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>


## v0.3.0 (2026-06-11)

### Features

- 0.3.0 — validate-config + review-diff skills, changelog, PR template
  ([`0423a50`](https://github.com/tardigrde/agent-skill-eval/commit/0423a50d03f3620428c790fd665959ae58ce9e74))


## v0.2.1 (2026-06-11)

### Chores

- Rename package to agent-skill-eval, bump to 0.2.1
  ([`6a42b78`](https://github.com/tardigrde/agent-skill-eval/commit/6a42b78a73e8668da5c85d21ac7dd6b5141e9679))

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>


## v0.2.0 (2026-06-10)

### Bug Fixes

- Address review findings (Gemini + self-review)
  ([`5316e99`](https://github.com/tardigrde/agent-skill-eval/commit/5316e997d4a09676cdf760287fa592aa18cdb40b))

- explicit UTF-8 encoding on all file reads/writes and subprocess output capture (Windows cp1252
  would corrupt agent output) - LLM judge workspace listing uses os.walk with in-place pruning so
  excluded trees (.git, skill dirs) are never traversed - reject blank bare --agent-model specs -
  harness no longer retries when the failed attempt already mutated the workspace (a second run
  would grade the union of both attempts) - warn when an agent ends up with no with/without-skill
  delta because all runs in one config errored - publish workflow verifies the git tag matches
  pyproject version - README documents that re-grading judges from saved artifacts, not the deleted
  live workspace

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

- Assertion routing bugs found by live smoke runs
  ([`dd31f03`](https://github.com/tardigrde/agent-skill-eval/commit/dd31f035ef95f4035d35c611fb62534c61fac144))

- "pr" matched as substring routed "prominently"/"present" prose assertions to the PR check; now
  word-boundary (\bprs?\b, pull request) - "The file `X` exists" did not match the file-existence
  check - contains/includes assertions with no quoted pattern now fall through to the LLM grader
  instead of failing deterministically

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

- Complete handoff review fixes and tighten PR grading
  ([`311bd88`](https://github.com/tardigrde/agent-skill-eval/commit/311bd885da5126b22ee27e6a436ebb920625ffed))

Address all remaining findings from the review handoff:

- Branch grading requires a newly created eval branch (Finding A): state_diff exposes eval_branch,
  post.current_branch; grader fails on checkout-of-existing-branch scenarios. - Commit grading
  requires a new commit on the eval branch (Finding B): full SHAs captured in branch_heads,
  commit_shas, head_sha; grader fails on HEAD-advanced-without-new-commit. - Push grading matches
  created branch and commit (Finding C): remote_branch_heads captured via for-each-ref; grader
  requires remote branch head to match local HEAD for the eval branch. - PR grading matches the
  created branch and requires OPEN state (Finding D, remaining gap): headRefName match, state ==
  OPEN filter, optional gh pr view direct-lookup corroboration, and rescue when state-delta is
  empty. - Cleanup manifest uses remote branch delta only (Finding E): CleanupManifest.branches
  renamed to remote_branches; deleted branches come from post.remote_branches - pre.remote_branches.
  - Cleanup only deletes recorded workspaces (Finding F): no more glob-delete of skill-eval-*;
  missing-manifest now warns and skips. - grade --recompute-benchmark recovers agent identity from
  run_meta.json (Finding G): RunMeta model, per-config persistence, backwards-compatible fallback to
  'unknown'. - Negative-control eval has inverted branch/commit/push/PR assertions (Finding H). -
  Test/lint command documentation updated to uv run --extra dev (Finding I). - uv.lock gitignored;
  CI stays on pip (Finding J, option b). - README documents new files, flags, schema, cleanup
  warning (Finding K). - Output directory layout includes agent segment eval-<id>/<agent>/<config>/
  (Finding L).

Also remove dead duplicate return in _check_pr_created and update PR test fixtures with state
  fields.

98 tests pass.

- Give LLM judge real workspace context
  ([`70fce85`](https://github.com/tardigrde/agent-skill-eval/commit/70fce85004a9dfb75a278f312715cf5c88985a9d))

The rubric grader derived the workspace from the results dir, so the judge never saw the agent's
  artifacts and failed content assertions with "cannot verify". Now grade_assertions passes the live
  workspace through, small text files (<=4KB, max 10) are inlined into the judge prompt, and
  skill-install/VCS dirs are excluded so the skill text does not leak into grading.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

- Grader model validation, add tests, and address review issues
  ([`d642c59`](https://github.com/tardigrde/agent-skill-eval/commit/d642c598b7545c6421c1fdf96c05a88283c00a03))

Source fixes: - Add EvalCase contradiction validator (force_skill_invocation + should_trigger) - Fix
  LLMGrader to fail missing assertions instead of silently dropping them

Test improvements: - Add conftest.py with shared fixtures (deduplicate _init_git_workspace, grader,
  evals_path) - Add test_llm_grader.py: 18 tests covering client property, base_url, prompt shape,
  JSON parsing, API errors, partial results, missing fields, file listing - Rewrite
  test_fuzz_grader.py: real handler tests instead of mocked dispatch - Add _check_command_ran
  coverage for all hardcoded commands + unknown command - Add test_compute_benchmark with xfail for
  known multi-agent delta=0 bug - Add EvalCase validation tests (valid, negative control,
  contradiction) - Add SkillInstaller.uninstall tests (empty parent removal) - Add
  WorkspaceManager._clone_repo test - Add github_repo_slug tests for URLs without .git suffix -
  Remove dead _init_workspace_with_changes helper from test_runner.py

Note: deepseek/deepseek-v4-flash is a valid OpenRouter model, not fictitious as claimed in TODO.md.
  Default grader model left unchanged.

- Implement github_repo_slug function to parse GitHub URLs and update related usages
  ([`a20e817`](https://github.com/tardigrde/agent-skill-eval/commit/a20e8177fbbfb42c08b15000f6c54d957ae64981))

- Openrouter grader, opencode parser, workspace-aware grading, dotenv support
  ([`ff851a8`](https://github.com/tardigrde/agent-skill-eval/commit/ff851a87bf6934dd1ba69e5fcb9b2c9759484df2))

- Tighten evals with state-delta grading, scoped cleanup, and proper re-grading
  ([`1b175d3`](https://github.com/tardigrde/agent-skill-eval/commit/1b175d30d1522b78b1b7564a25bf2da07077065a))

Addresses review findings from PR #2:

- Add pre/post git state capture (GitStateSnapshot) including PR list from the source repo,
  persisted as pre_state.json / post_state.json per run. - Rework DeterministicGrader to grade
  against the state delta (new branches, HEAD advance, new remote refs, new PRs) instead of loose
  workspace state or agent output text. Existing branches/commits/PRs at baseline can no longer
  satisfy "new branch", "new commit", or "new PR" assertions. - Implement should_trigger=False
  semantics: branch/commit/push/pr assertions are inverted to "MUST NOT" for negative controls, so
  the negative-control eval fails if the skill incorrectly triggers. - Stop auto-prepending 'Use the
  $skill' to every with-skill prompt. Eval prompts decide for themselves; opt in via
  force_skill_invocation: true on EvalCase for tests that need to assert the skill is reachable by
  name. - Add stage_files: true to EvalCase so eval prompts that say 'I have changes staged'
  actually have staged changes. - Replace broad cleanup (closes all open PRs, deletes all
  non-default branches) with manifest-driven cleanup: each run records the exact branches and PRs it
  created in cleanup.json, and _cleanup_manifest removes only those. Falls back to workspace-only
  cleanup when no manifest is present. - Make 'skill-eval grade' re-grade with the saved eval
  metadata and state artifacts, persist grading.json, and optionally recompute benchmark.json.
  Persist evals_meta.json during run. - Refactor _compute_benchmark / _compute_stats into
  module-level compute_benchmark / compute_stats so they can be called from the grade command
  without an EvalRunner instance. - Update evals.json: explicit-invoke and no-changes opt in to
  force_skill_invocation; explicit-invoke stages its fixtures. - Tests: rewrite grader tests around
  state deltas, add negative-control tests, add 'existing artifact does not satisfy' tests, add
  scoped cleanup tests, add prompt-construction tests, add grade-command persistence tests, add
  evals_meta persistence test. 73/73 tests pass.

### Continuous Integration

- Add Python version matrix, caching, coverage, and smoke test job
  ([`f1d2a88`](https://github.com/tardigrde/agent-skill-eval/commit/f1d2a880e5fa66ad67f26d999a0614c86b6b1e39))

- Add Python 3.11/3.12/3.13 matrix to lint and test jobs - Add composite action
  (.github/actions/setup) with pip caching - Add concurrency block (cancel-in-progress) and
  permissions (contents: read) - Add pytest --junitxml and --cov with artifact upload - Add smoke
  test as separate job (runs after lint+test) - Add pytest-cov to dev dependencies

### Documentation

- Add LICENSE, CHANGELOG, CONTRIBUTING, issue templates, --version flag, and fill pyproject metadata
  ([#6](https://github.com/tardigrde/agent-skill-eval/pull/6),
  [`7a1db3d`](https://github.com/tardigrde/agent-skill-eval/commit/7a1db3d71a7a6b8c87f397053d2e94cf0ac571f0))

* docs: add LICENSE, CHANGELOG, CONTRIBUTING, issue templates, --version flag, and fill pyproject
  metadata

- Add MIT LICENSE file - Add CHANGELOG.md from git history (3 releases) - Add CONTRIBUTING.md,
  CODE_OF_CONDUCT.md, .github/ISSUE_TEMPLATE/ - Fill pyproject.toml: authors, readme, homepage,
  repository, keywords, classifiers - Unify version source: pyproject.toml is single source,
  __init__.py reads via importlib.metadata - Add --version/-v flag to CLI via typer callback -
  Document python -m skill_eval entry point in README - Document examples/ vs skills/ directory
  convention - Update negative-control example to match real evals.json assertions (push + content
  checks) - Add grading.json evidence debugging section to README

* fix: correct repo URLs, move project.urls, fix CLI help fallback, reorder CHANGELOG

- CONTRIBUTING.md: fix clone URL and cd dir to tardigrde/skill-evals - pyproject.toml: move
  homepage/repository out of [project] into [project.urls] as PEP 621-compliant Homepage/Repository
  keys; update URLs to tardigrde/skill-evals - src/skill_eval/cli.py: print help and exit when
  skill-eval is invoked with no subcommand - CHANGELOG.md: reorder to newest-first per Keep a
  Changelog convention; relabel earliest entry [0.1.0] -> [0.1.0-alpha.1]

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

---------

Co-authored-by: Claude Fable 5 <noreply@anthropic.com>

### Features

- 0.2.0 — pass@k, per-agent deltas, model pinning, validate/list/compare, write-release-notes
  example
  ([`0d0ac3b`](https://github.com/tardigrde/agent-skill-eval/commit/0d0ac3b1aa737475228bdd8a22c8bc877934d596))

- fix multi-agent benchmark: per-agent deltas instead of silent 0.0 - --runs N with full_pass_rate /
  pass@k in benchmark.json - --agent-model agent=model, --harness-base-url, --timeout, --retries -
  harness retry/backoff; exit_code/timed_out/retries recorded in timing.json - ungradeable
  assertions skipped (not failed); method/skipped in grading.json - new commands: validate, list,
  compare; report --format markdown --show-evidence - richer init scaffold (SKILL.md template +
  negative control) - write-release-notes example skill (LLM-rubric-heavy, offline) - evals.json
  JSON Schema + sync test; SKILL.md frontmatter warnings - PyPI trusted-publishing workflow; README
  restructured; demo script

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

- Add CI workflow, improve project structure, and enhance testing coverage
  ([`a20cf73`](https://github.com/tardigrde/agent-skill-eval/commit/a20cf738368eba65b2e237ab2b569af46486adc0))

- Add fix-failing-tests skill for error recovery evaluation
  ([#7](https://github.com/tardigrde/agent-skill-eval/pull/7),
  [`d9f1464`](https://github.com/tardigrde/agent-skill-eval/commit/d9f1464a87ca451c179c511bf127d46d190660eb))

* feat: add fix-failing-tests skill for error recovery evaluation

Add second example skill that tests the highest-signal agent capability: error recovery / iterative
  refinement (Reflexion, SWE-bench).

Skill: agent runs pytest, diagnoses 3 subtle bugs in calculator.py, fixes source code (not tests),
  verifies all 15 tests pass.

Bugs: - average: divides by (count-1) instead of count → ZeroDivisionError + wrong results -
  factorial: range(1,n) instead of range(1,n+1) → off-by-one - is_palindrome: missing .lower() →
  case-sensitive comparison fails

4 eval cases: explicit-invoke, implicit-invoke, contextual-invoke, negative-control. Offline, zero
  dependencies, deterministic grading via pytest pass/fail.

Verified with opencode: agent fixed all 3 bugs in ~30s.

* fix: add conftest.py sys.path fixture and tighten fix-failing-tests evals

- Add files/conftest.py that inserts its own directory into sys.path so pytest can resolve `from
  calculator import ...` regardless of the working directory from which pytest is invoked. - Add
  "files/conftest.py" to the files array of every eval case that includes test_calculator.py
  (explicit-invoke, implicit-invoke, contextual-invoke). - Remove "files/test_calculator.py" from
  the negative-control case, matching the commit-push-pr convention of minimal fixture files and
  avoiding baiting the agent into running tests.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

---------

Co-authored-by: Claude Fable 5 <noreply@anthropic.com>

- Check actual outcomes (branches, commits, PRs) instead of just agent text output
  ([`9127fe7`](https://github.com/tardigrde/agent-skill-eval/commit/9127fe7ec69d12b0c0d60df72dae8aa525fe366f))

- Improve commit-push-pr skill to 100% pass rate and add cleanup command
  ([`8e6dfc9`](https://github.com/tardigrde/agent-skill-eval/commit/8e6dfc9b61311f2cc3d32ed283040663e2c8d6db))

- Fix evals.json file paths (evals/files/ -> files/) - Fix assertion quotes for grader parsing
  (single quotes -> backticks) - Improve SKILL.md with autonomous execution directive - Clarify what
  counts as changes (include untracked, exclude agent config) - Add cleanup command to close PRs,
  delete branches, remove workspaces - Add --cleanup flag to run command for automatic post-eval
  cleanup
