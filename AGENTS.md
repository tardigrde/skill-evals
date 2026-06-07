# AGENTS.md

## Project

Python CLI framework (`skill-eval`) for evaluating agent skills across OpenCode, Claude Code, and Codex. Uses Typer, Pydantic, OpenAI SDK, and Rich.

## Quick commands

```bash
# Install (editable + dev deps)
uv pip install -e ".[dev]"

# Run tests
uv run --extra dev pytest -q

# Lint + format check (CI runs both)
uv run --extra dev ruff check src/ tests/
uv run --extra dev ruff format --check src/ tests/

# Run all checks before committing
uv run --extra dev ruff check src/ tests/ && uv run --extra dev ruff format --check src/ tests/ && uv run --extra dev pytest -q
```

## Architecture

```
src/skill_eval/
├── cli.py            # Typer CLI app (run, report, grade, cleanup, init)
├── runner.py         # EvalRunner orchestrates eval execution
├── graders/__init__.py   # DeterministicGrader + LLMGrader (700+ lines, single file)
├── harnesses/__init__.py # Agent harnesses (opencode, claude-code, codex, fake)
├── models.py         # Pydantic models for eval config
├── git_state.py      # Pre/post git/PR state snapshots
├── skills.py         # Skill installer
└── workspace.py      # Workspace creation (fresh git init or clone)
```

- Entry point: `skill_eval.cli:app` (registered as `skill-eval` console script)
- Package layout: `src/skill_eval/` (hatchling build, wheel packages `src/skill_eval`)
- The `fake` harness (used in tests) is a no-op agent that produces deterministic output

## Testing

- Test files mirror source: `test_runner.py`, `test_graders.py`, `test_harnesses.py`, etc.
- Fixtures live in `tests/fixtures/` — skills and evals JSON used by smoke tests
- `test_cli_smoke.py` is the integration test: runs full `run -> report -> init` cycle with `--agent fake`
- Tests use `tmp_path` for workspace isolation; no shared state
- Shared fixtures in `tests/conftest.py` (`_init_git_workspace`, `grader`, `evals_path`)

## Conventions

- Python 3.11+ required (`requires-python = ">=3.11"`)
- Ruff config: `line-length = 120`, rules `["E", "F", "I"]`
- All imports use `from __future__ import annotations`
- Pydantic v2 models throughout
- CLI uses Typer with `CliRunner` for testing
- `.env` file loaded via `python-dotenv` (not committed)

## Key gotchas

- Default grader model `deepseek/deepseek-v4-flash` is a valid OpenRouter model. Override with `--grader-model` or set a real model.
- `graders/__init__.py` is a monolith (700+ lines) containing both deterministic and LLM graders
- `harnesses/__init__.py` has a dead `cost_usd` read at line ~140 (no-op code)
- `compute_benchmark` returns delta=0.0 for multi-agent runs (known bug)
- Workspace paths must contain literal `with_skill`/`without_skill` substrings or grading breaks silently
- `uv.lock` is gitignored — not tracked in version control
