# Contributing

## Setup

```bash
git clone https://github.com/anthropics/skill-eval.git
cd skill-eval
uv venv
uv pip install -e ".[dev]"
```

## Running checks

```bash
uv run --extra dev pytest -q
uv run --extra dev ruff check src/ tests/
uv run --extra dev ruff format --check src/ tests/
```

Run all three before committing:

```bash
uv run --extra dev ruff check src/ tests/ && uv run --extra dev ruff format --check src/ tests/ && uv run --extra dev pytest -q
```

## Code style

- Python 3.11+ required
- Ruff for linting and formatting (`line-length = 120`)
- All imports use `from __future__ import annotations`
- Pydantic v2 models throughout

## Pull requests

1. Fork the repo and create a feature branch.
2. Add tests for new functionality.
3. Ensure all checks pass.
4. Open a PR with a clear description of the change.

## Issues

Use the GitHub issue templates to report bugs or request features.
