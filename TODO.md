# TODO

Audit of `main` originally done at 0.1.0; pruned and updated 2026-06-11 (v0.4.0, post PR #9/#10).
Done items are kept briefly for history; anything obsolete or low-value was deleted.

## How to work this list (for the implementing agent)

- Do NOT bundle everything into one PR. Group into separate PRs by section (one for Bugs, one for Docs, one per Feature) with conventional-commit messages — semantic-release on main derives versions and the changelog from them.
- `make test` (includes free e2e tier) + `make lint` must pass per PR; run `make test-live` once before the final merge of the batch (costs cents, needs `.env` OpenRouter key + opencode/codex auth).
- Items marked *(judgment)* are optional — skip unless already touching that code.

## Features (next up)

- [ ] **Subagent evals** — evaluate custom subagent definitions (e.g. `~/.claude/agents/*.md`) the same way as skills: generalize `SkillInstaller` to an artifact installer with a type field; harnesses/runner/graders/metrics stay as-is. Add one example subagent + eval suite. README already announces it as coming soon.

## Done

- [x] **Names converged on `agent-skill-eval`** (PR #10): repo, CLI, module, PyPI all match; `ase` short alias; env prefix `ASE_*`. Repo renames redirect from `skill-evals`/`agent-evals`.
- [x] **Release fully automated** (gcpath pattern): push to main → python-semantic-release bumps version, tags, GitHub release, publishes to PyPI via trusted publishing. v0.4.0 shipped this way end-to-end. Trusted publisher re-created for renamed repo (workflow `release.yml`, env `pypi`); old one deleted.

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

- [x] `negative-control` eval: reworded "output contains the source code" assertion to behavior ("read and displayed or described its contents").
- [x] `grade` re-running the LLM grader fresh is surfaced in CLI output and README (was already done on main; verified).
- [x] `LLMGrader.grade`: grading errors and missing per-assertion results are now skipped (not failed) with a console warning.
- [x] `DeterministicGrader._resolve_workspace`: workspace fallback now warns (once per run dir) instead of silently guessing; shared with the LLM grader.
- [x] Assertion patterns documented in README (was already done on main); `validate` now also reports which assertions will fall through to the LLM rubric (`classify_assertion`).
- [ ] claude-code's `cost_usd` is the CLI's Anthropic-list-price estimate; actual OpenRouter billing differs. Document or reconcile via OpenRouter generation API.
- [x] CHANGELOG.md: curated pre-0.4 entries restored (PSR-style headings), PSR configured with `mode = "update"` + insertion flag, vendored templates in `templates/` render summary lines only (no commit bodies / Co-Authored-By trailers).

## Test coverage gaps

- [ ] `build_command` tested for codex only; pin claude-code and opencode invocations too.
- [ ] `runner._build_cleanup_entry`: merged/closed/external PR-number handling uncovered.
- [x] Report shows per-assertion evidence via `report --show-evidence` (was already done on main; verified).

## Docs

- [ ] Fill out `pyproject.toml` `authors` with a real author (rest of metadata was already filled on main).
- [x] Version single-sourced in `pyproject.toml`: PSR `version_variables` removed, `__init__.py` falls back to `0.0.0` when not installed.
- [ ] Document `python -m agent_skill_eval` in README (`examples/` vs `skills/` and `grading.json` debugging were already documented on main).
- [x] `--version` wired to package version (was already done on main; verified).

## Improvements

- [x] Cost column in `agent-skill-eval report`: `benchmark.json` gains per-config `cost_usd` mean/stddev and per-agent cost deltas; report shows a Cost (USD) column.
- [x] `init` scaffold: SKILL.md frontmatter template + negative-control example (was already done on main; verified).
- [ ] Multi-agent comparison example showing how to read with/without-skill deltas.
- [ ] Expand `examples/commit-push-pr/evals/files/sample_change.py` into a realistic fixture.
- [ ] *(judgment)* Split `graders/__init__.py`, `cli.py`, `runner.py` once they next need surgery — one-time split makes everything after cheaper.

## Cleanup

- [ ] Delete stale local branches (`feat/improve-commit-push-pr-skill`, `fix/login-bug`, `smoke-test-ci`, merged feature branches) after confirming merged.
- [ ] Delete `HANDOFF.md` (untracked, stale — its mission completed 2026-06-11) and the leftover `.claude/worktrees/` copy of the old module tree.
- [ ] *(judgment)* `SkillInstaller.uninstall` never called by the runner (safe today via `rmtree`, but asymmetric).
