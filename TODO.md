# TODO

Notes from a repo audit on `main`. Items are grouped by area and ranked within each group by impact.

## Top 3 (highest leverage)

- [x] **Fix the default grader model and add `tests/test_llm_grader.py`** *(small, critical)*
  - `deepseek/deepseek-v4-flash` is a valid OpenRouter model — no replacement needed. Default grader model left unchanged.
  - Added `tests/test_llm_grader.py` covering: prompt shape, JSON response parsing, malformed/partial response handling, missing API key, workspace file listing bounds.

- [x] **Add an end-to-end CI smoke test that actually invokes `skill-eval`** *(medium, highest payoff)*
  - Add a non-network fixture skill (e.g. `format-json`) under `tests/fixtures/skills/format-json/SKILL.md`.
  - Add a matching `tests/fixtures/evals/format-json.json` with 2–3 cases (explicit-invoke, negative-control, content-contains).
  - Add a `--harness fake` mode (or monkey-patch) so the test does not need `opencode`/`claude`/`codex` CLIs installed in CI.
  - Assert on outputs: `benchmark.json`, per-task `grading.json`, `cleanup.json` exist; `skill-eval report` exits 0 and prints a row per (agent, with_skill).
  - Right now CI catches broken grader/harness/git-state/cleanup logic but not broken wiring (typer option parsing, `run` → `EvalRunner` flow, `eval-*`/`with_skill`/`without_skill` naming, progress bar, `--cleanup` flag, `init`). The README's "Quick Start" is not exercised by any test.

- [x] **Add a second, offline example skill + improve `init` template** *(medium)*
  - Shipped `skills/fix-failing-tests/SKILL.md` — agent runs tests, diagnoses 3 subtle bugs (off-by-one, wrong denominator, missing case normalization), fixes source code, verifies all pass.
  - Shipped `examples/fix-failing-tests/evals/evals.json` with 4 cases (explicit-invoke, implicit-invoke, contextual-invoke, negative-control).
  - Buggy source: `examples/fix-failing-tests/evals/files/calculator.py` (3 bugs → 8 test failures). Tests: `test_calculator.py` (15 assertions).
  - Tests highest-signal agent capability: error recovery / iterative refinement (Reflexion, SWE-bench).
  - Improve `cli.init` to scaffold: a SKILL.md frontmatter template, a `negative-control` example by default, a `should_trigger: false` + inverted-assertion template.
  - Add a `skill-eval list` subcommand that surfaces all `examples/*/evals/evals.json` as discoverable test cases.
  - The repo's value is "evaluate your skill"; one network-heavy example (`commit-push-pr`) is a poor "hello world" and blocks offline use.

---

## Bugs / dead code

- [ ] `src/skill_eval/harnesses/__init__.py:140` reads `cost_usd` and discards it; the surrounding `if cost:` block is a no-op that only coerces `total_tokens` to 0 if it is already 0. Delete the dead read.
- [ ] `runner.compute_benchmark` returns a delta of `0.0` for multi-agent runs (`runner.py:364`) with no warning. A user running `--agent opencode --agent claude-code` will see "Delta: 0.0%" and conclude skills do not help. Either compute the delta correctly or warn explicitly.
- [ ] `skill-eval grade --recompute-benchmark` re-runs the LLM grader fresh, so previously cached LLM grades can flip verdicts silently. Surface this in CLI output and document it in the README.
- [ ] `LLMGrader.grade` swallows all errors and returns "LLM grading error" for every undetermined assertion. The CLI does not warn before running. Consider skipping failed assertions (with a warning) instead of marking them all fail.
- [ ] `DeterministicGrader._resolve_workspace` (`graders/__init__.py:192`) uses brittle substring matching on `with_skill`/`without_skill`. If a user passes a workspace layout without those literal substrings, it silently falls back to `output_dir.parent`. Pass the workspace explicitly or warn.
- [ ] `DeterministicGrader._check_assertion` silently marks unknown assertion shapes as "Could not deterministically check" and falls through to LLM grading. No user-facing schema lists supported assertion patterns.

## Test coverage gaps

- [x] `LLMGrader` is mocked in every existing test and never tested directly. Lock down the prompt template and JSON parsing (see Top #1).
- [x] `DeterministicGrader._check_command_ran` has 0 tests. Pin its behavior.
- [ ] `harness.build_command` (the actual CLI invocation) is never called in any test. A regression in the opencode/claude/codex invocation will pass CI.
- [x] CLI `init` command is not tested (file/dir creation not pinned).
- [x] CLI `report` command is not tested (table rendering not pinned).
- [x] CLI `run` command is only tested via `EvalRunner._run_single` direct calls, never via `typer.testing.CliRunner.invoke(app, ["run", ...])`. CLI option parsing (e.g. `--workspace` default, repeated `--agent` flags, `--cleanup` flag) is untested.
- [x] `SkillInstaller.uninstall` has only 2 tests. The `parent.rmdir()` cleanup of empty `skills/` parents is not covered.
- [x] Negative-control `force_skill_invocation` interaction is untested. If both `force_skill_invocation=True` and `should_trigger=False` are set, the framework does not validate the contradiction.
- [x] `compute_benchmark` with multi-agent runs (delta=0) has no test — would have caught the silent zero-delta bug above.
- [ ] `runner._build_cleanup_entry` is tested for one case only. PR-number handling for merged/closed/external PRs is not covered.
- [x] `WorkspaceManager._clone_repo` is never tested. The clone-and-config flow is untested.
- [x] `github_repo_slug` does not cover `https://github.com/owner/repo` with no `.git` suffix. `git_state.py:38-40` may not handle it.
- [x] No `conftest.py`, no shared fixtures (`git_workspace`, `evals_path`, `grader`). `_init_git_workspace` is re-implemented in 4 test files (`test_graders.py`, `test_git_state.py`, `test_runner.py`).
- [x] No property-based/fuzz tests for `_check_assertion` (substring matcher).
- [ ] `Report` does not show per-assertion evidence from `grading.json`, only the summary count. The richest data the framework produces is invisible to CLI users.

## Documentation / metadata

- [ ] Add a `LICENSE` file. The README claims MIT but the text is missing.
- [ ] Add a `CHANGELOG.md`. The 8 git commits tell the story; the user-visible feature history is invisible.
- [ ] Add `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, and `.github/ISSUE_TEMPLATE/`.
- [ ] Fill out `pyproject.toml`: `authors`, `readme`, `homepage`, `repository`, `keywords`, `classifiers`. Version is `0.1.0` and is duplicated in `pyproject.toml` and `src/skill_eval/__init__.py` with no central source — pick one.
- [ ] Document `python -m skill_eval`. `src/skill_eval/__main__.py` exists but is not mentioned in the README.
- [ ] Document the `examples/` vs `skills/` directory convention explicitly. Currently only inferred from the Quick Start.
- [ ] Add a custom `--version` flag (typer default is fine but should be wired to the package version).
- [ ] Document the Quick Start negative-control example's assertion breadth. The README example is less rigorous than the actual `examples/commit-push-pr/evals/evals.json` (which adds `push` and content-contains assertions).
- [ ] Add a section explaining how to read `grading.json` evidence when an assertion fails. The "Iterating on Skills" section describes a workflow but not how to debug it.

## CI

- [x] Add a Python version matrix (3.11, 3.12, 3.13) to `.github/workflows/ci.yml`. `requires-python = ">=3.11"` is declared but only 3.11 is tested.
- [x] Add `actions/cache` for pip/uv, a `concurrency` block, and an explicit `permissions:` block.
- [x] Add `pytest --junitxml` upload and coverage upload. No coverage tool is configured.
- [x] Share the install step between `lint` and `test` jobs (composite action or job dependency).
- [x] Wire the smoke test from Top #2 into CI as a third job (or a third step in `test`).

## Code organization

- [ ] Split `graders/__init__.py` (708 lines) into `graders/deterministic.py`, `graders/llm.py`, and a thin `__init__.py`.
- [ ] Split `cli.py` (500 lines) into `cli/run.py`, `cli/grade.py`, `cli/report.py`, `cli/cleanup.py`, `cli/init.py`.
- [ ] Split `runner.py` (375 lines) into `runner/run.py` and `runner/benchmark.py`.
- [ ] Add module-level docstrings explaining intent (the codebase mostly has minimal docstrings; only `cli.py:91-99` `_cleanup_iteration` is well documented).
- [ ] Add a `docs/` directory once the module structure is settled.

## Examples & skills

- [x] Add a second example skill (see Top #3) so the framework is demonstrable offline.
- [ ] Expand `examples/commit-push-pr/evals/files/sample_change.py` (currently 2 lines) into a more realistic fixture (e.g. a function with a bug, a TODO) so the "look at the file" branch of the skill is actually exercised.
- [ ] Add an example showing how to **interpret** the `report` command's `with_skill` vs `without_skill` delta across agents. None of the current examples is a multi-agent comparison.
- [ ] Enforce SKILL.md frontmatter at install time. Currently `test_skill_validation.py` is the only enforcement and it lives in `tests/`, not in the install path. A user running `skill-eval run` will not see a missing `description` until something silently misbehaves.

## Harnesses

- [ ] Expose `agent_models` in CLI and support OpenRouter / OpenAI-compatible models in any harness. `EvalRunner` already accepts `agent_models: dict[AgentType, str]` (`runner.py:46`) but `cli.py` never wires it. Add `--agent-model provider/model` flag to `skill-eval run` so harnesses can use a specific model. Additionally, add a `--harness-base-url` flag (or per-agent variant) so users can point any harness at OpenRouter or a local OpenAI-compatible endpoint (e.g. `--harness-base-url https://openrouter.ai/api/v1 --agent-model openrouter/anthropic/claude-sonnet-4`). This makes evals reproducible across environments and decouples them from each agent's default model.
- [ ] No retry/backoff in harnesses. A 600s timeout means a single hung agent blocks a worker indefinitely. On `TimeoutExpired`, the runner prints an error and continues but does not retry, does not record partial credit, and does not surface the harness exit code.
- [ ] `SkillInstaller.uninstall` is never called by the runner. The install/uninstall symmetry is a smell (currently safe because `WorkspaceManager.create_workspace` does `shutil.rmtree` first, but worth cleaning up).

## Cleanup

- [ ] Delete the stale local branches `feat/improve-commit-push-pr-skill` and `fix/login-bug` once their content is confirmed merged. They confuse `git branch -a`.

---

## Honorable mention (would be #4)

Refactor the three large files above. The code is correct but not navigable; a one-time split would make every subsequent TODO on this list roughly 2x cheaper. Effort: medium.
