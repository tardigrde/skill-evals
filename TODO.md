# TODO

Audit of `main` originally done at 0.1.0; pruned and updated 2026-06-11 (v0.3.0, PR #9 era).
Done items are kept briefly for history; anything obsolete or low-value was deleted.

## Done

- [x] **Grader fixed + tested** — `deepseek/deepseek-v4-flash` via OpenRouter, `tests/test_llm_grader.py` covers prompt shape, JSON parsing, malformed responses, missing key.
- [x] **Fake harness + CI smoke test** — `--agent fake`, no network, wired into CI.
- [x] **Offline example skill** — `skills/fix-failing-tests` + 4-case eval suite (`examples/fix-failing-tests`).
- [x] **All 4 harnesses verified live** (2026-06-11): fake, claude-code (haiku via OpenRouter), opencode (Zen free), codex (`gpt-5.4-mini`, ChatGPT plan). Codex needed `--sandbox workspace-write` + `--skip-git-repo-check` (eval workspaces are fresh git dirs).
- [x] **Cost/time/accuracy all machine-readable per run** — `timing.json` gained `cost_usd` (claude: `total_cost_usd`, opencode: per-step `cost`); `duration_ms`, tokens, and `grading.json` pass rates already existed.
- [x] **Two-tier e2e tests** (`tests/test_e2e.py`) — free tier (fake harness, real CLI subprocess, artifact + report assertions) runs in every `make test`; live tier (`make test-live`, `live` marker) runs all real agents + LLM grader and enforces ≥0.7 mean pass rate, zero skipped grades.
- [x] **Makefile** — `cheap-eval`, `full-eval` (adds codex), `fake-eval`, `test`, `test-e2e`, `test-live`, `lint`; `AGENTS` + per-agent model vars; `config/baseline.env` pins models.
- [x] `--agent-model` and `--harness-base-url` CLI flags wired.
- [x] Harness retry/backoff with pristine-workspace guard; timeout + exit code recorded in `timing.json`.
- [x] Per-agent benchmark deltas for multi-agent runs (no more silent 0.0).
- [x] SKILL.md frontmatter problems warned at `run` time.
- [x] LICENSE, CHANGELOG.md, CONTRIBUTING.md, issue templates, PR template, `agent-skill-eval list`, conftest fixtures, fuzz tests for assertion matcher, CI matrix + coverage.

## Bugs / sharp edges

- [ ] `negative-control` eval: assertion "The output contains the source code of calculator.py" is grader-run-dependent (failed for all agents in one run, passed in another). Reword to behavior ("file read, not modified, no tests run").
- [ ] `agent-skill-eval grade --recompute-benchmark` re-runs the LLM grader fresh; cached grades can flip silently. Surface in CLI output + README.
- [ ] `LLMGrader.grade` swallows errors and marks undetermined assertions as failed. Prefer skip-with-warning.
- [ ] `DeterministicGrader._resolve_workspace` relies on `with_skill`/`without_skill` substrings; silently falls back to `output_dir.parent`. Pass workspace explicitly or warn.
- [ ] No user-facing schema of supported deterministic assertion patterns; unknown shapes fall through to LLM silently.
- [ ] claude-code's `cost_usd` is the CLI's Anthropic-list-price estimate; actual OpenRouter billing differs. Document or reconcile via OpenRouter generation API.

## Test coverage gaps

- [ ] `build_command` tested for codex only; pin claude-code and opencode invocations too.
- [ ] `runner._build_cleanup_entry`: merged/closed/external PR-number handling uncovered.
- [ ] Report does not show per-assertion evidence from `grading.json` — the richest output is invisible in the CLI.

## Docs

- [ ] Fill out `pyproject.toml` metadata (`authors`, `readme`, `homepage`, `keywords`, `classifiers`); single-source the version (currently duplicated with `__init__.py`).
- [ ] Document `examples/` vs `skills/` convention, `python -m agent_skill_eval`, and how to debug a failing assertion via `grading.json` evidence.
- [ ] Wire `--version` to package version.

## Improvements

- [ ] Cost column in `agent-skill-eval report` (data already in `timing.json`).
- [ ] `init` scaffold: SKILL.md frontmatter template + negative-control example by default.
- [ ] Multi-agent comparison example showing how to read with/without-skill deltas.
- [ ] Expand `examples/commit-push-pr/evals/files/sample_change.py` into a realistic fixture.
- [ ] Split `graders/__init__.py`, `cli.py`, `runner.py` once they next need surgery — one-time split makes everything after cheaper.

## Cleanup

- [ ] Delete stale local branches (`feat/improve-commit-push-pr-skill`, `fix/login-bug`, `smoke-test-ci`, merged feature branches) after confirming merged.
- [ ] `SkillInstaller.uninstall` never called by the runner (safe today via `rmtree`, but asymmetric).
