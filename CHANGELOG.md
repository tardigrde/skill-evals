# Changelog

All notable changes to this project will be documented in this file.

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
