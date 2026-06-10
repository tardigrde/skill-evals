# Changelog

All notable changes to this project will be documented in this file.

## [0.3.0] - 2026-06-11

### Added
- `validate-config` example skill + eval suite: exercises bundled resources (agent runs skill's `scripts/` and reads its `references/`); graded via command-ran + file + content checks; fully offline
- `review-diff` example skill + eval suite: read-only analysis (planted bugs found, documented decoy not flagged, nothing modified); graded via chat-output-only content + LLM rubric; fully offline

## [0.2.1] - 2026-06-11

### Changed
- Renamed package from `skill-eval` to `agent-skill-eval` (PyPI name collision)

## [0.2.0] - 2026-06-10

### Added
- `write-release-notes` example skill + eval suite: exercises LLM rubric grading (grouping, breaking-change prominence, anti-fabrication) instead of git-state checks
- `--runs N` repeats every (eval, agent, config); `benchmark.json` now reports `full_pass_rate`, `pass_at_k`, and `k`
- `--agent-model agent=model` (repeatable) and `--harness-base-url` to pin models and endpoints per agent CLI
- `--timeout` / `--retries` flags; harnesses retry on timeout or non-zero exit with backoff and record `exit_code`, `timed_out`, `retries` in `timing.json`
- `skill-eval validate`: schema + fixture-existence + duplicate-id checks for evals.json
- `skill-eval list`: discover eval suites and skills under a directory
- `skill-eval compare`: side-by-side pass rates of two iterations
- `report --format markdown` and `report --show-evidence` (failed/skipped assertion evidence)
- JSON Schema for the eval suite format at `schemas/evals.schema.json` (with a sync test)
- SKILL.md frontmatter validation warning on `run` (missing name/description, name mismatch)
- Richer `init` scaffold: SKILL.md frontmatter template + negative-control eval case
- PyPI trusted-publishing workflow on version tags (`.github/workflows/publish.yml`)
- Demo recording script (`scripts/record-demo.sh`)

### Changed
- Assertions that cannot be graded (no API key, LLM grader error) are now **skipped** and excluded from the pass rate instead of counted as failures; `grading.json` gains `method` and `skipped` fields
- `run` warns upfront when no grader API key is set; `grade` warns that LLM verdicts may flip on re-grade
- README restructured around the full-harness pitch, with a documented table of recognized deterministic assertion patterns

### Fixed
- Multi-agent runs no longer report a misleading `Delta: 0.0%`: `benchmark.json` now has per-agent `deltas`; the legacy `delta` field is only set for single-agent runs (otherwise `null`)
- Removed dead `cost_usd` handling in the Claude Code output parser

## [0.1.0-alpha.3] - 2026-06-07

### Added
- Shared test fixtures in `conftest.py`
- `test_llm_grader.py`: 18 tests covering client, prompts, JSON parsing, errors
- `test_fuzz_grader.py` rewrite: real handler tests instead of mocked dispatch
- `test_compute_benchmark` with xfail for known multi-agent delta=0 bug
- EvalCase validation tests (valid, negative control, contradiction)
- `SkillInstaller.uninstall` tests, `WorkspaceManager._clone_repo` test
- `github_repo_slug` tests for URLs without `.git` suffix

### Changed
- CI uses setup-python's built-in cache instead of separate `actions/cache`

### Fixed
- EvalCase contradiction validator (`force_skill_invocation` + `should_trigger`)
- LLMGrader now fails on missing assertions instead of silently dropping them

## [0.1.0-alpha.2] - 2026-06-02

### Added
- CI workflow with Python 3.11/3.12/3.13 matrix, caching, coverage, and smoke test
- CLI smoke test (`test_cli_smoke.py`) for full run -> report -> init cycle

### Changed
- Tightened evals with state-delta grading and scoped cleanup
- Improved `commit-push-pr` skill to 100% pass rate

### Fixed
- `github_repo_slug` function to parse GitHub URLs correctly
- Handoff review fixes and PR grading tightening

## [0.1.0-alpha.1] - 2026-05-27

### Added
- Initial release: skill evaluation framework for OpenCode, Claude Code, and Codex
- `run`, `report`, `grade`, `cleanup`, and `init` CLI commands
- Multi-agent support with baseline (with-skill / without-skill) comparison
- State-delta grading using pre/post git snapshots (`pre_state.json` / `post_state.json`)
- Deterministic assertions: branch, commit, push, PR, file existence, content matching
- LLM rubric grading via configurable model (`--grader-model`)
- Negative-control support (`should_trigger: false`) to catch accidental skill triggering
- Scoped cleanup via `cleanup.json` manifest (never closes unrelated PRs)
- `commit-push-pr` example skill with 5 eval cases
- Lazy-initialized OpenAI client with API key validation
- OpenRouter grader support via `OPENROUTER_API_KEY`
- Workspace isolation with fresh git repos per eval run
- Token/timing extraction from each agent's native output format
- `python -m skill_eval` entry point

### Fixed
- OpenRouter grader model resolution and opencode parser output handling
- Workspace-aware grading and dotenv loading
