# skill-eval Makefile
#
# Usage:
#   make cheap-eval SKILL=examples/fix-failing-tests EVALS=examples/fix-failing-tests/evals/evals.json
#   make fake-eval  SKILL=examples/fix-failing-tests EVALS=examples/fix-failing-tests/evals/evals.json
#   make test
#   make lint
#
# OpenRouter setup (set in shell or .env):
#   OPENROUTER_API_KEY=sk-or-...
#   ANTHROPIC_BASE_URL=https://openrouter.ai/api      # claude-code reads this
#   ANTHROPIC_AUTH_TOKEN=$OPENROUTER_API_KEY           # claude-code auth via OpenRouter
#   ANTHROPIC_API_KEY=                                 # must be blank when using OpenRouter
#   OPENAI_BASE_URL=https://openrouter.ai/api/v1       # opencode reads this

# ── Defaults ────────────────────────────────────────────────────────────────

# Read OPENROUTER_API_KEY from .env if not already in shell
OPENROUTER_API_KEY ?= $(shell grep -s '^OPENROUTER_API_KEY' .env | cut -d= -f2- | tr -d '"' | tr -d "'")

SKILL  ?= skills/fix-failing-tests
EVALS  ?= examples/fix-failing-tests/evals/evals.json

# Pinned free/cheap OpenRouter models (see config/baseline.env to override)
CLAUDE_CODE_MODEL  ?= deepseek/deepseek-v4-flash:free
OPENCODE_MODEL     ?= deepseek/deepseek-v4-flash:free
CODEX_MODEL        ?= gpt-5.4-mini
GRADER_MODEL       ?= deepseek/deepseek-v4-flash:free

# Agents to run (space-separated). Override: make cheap-eval AGENTS="fake codex"
AGENTS ?= fake claude-code opencode

WORKSPACE   ?= eval-workspace
CONCURRENCY ?= 3

-include config/baseline.env

AGENT_FLAGS = $(foreach a,$(AGENTS),--agent $(a))

# ── Targets ──────────────────────────────────────────────────────────────────

.PHONY: cheap-eval full-eval fake-eval test test-e2e test-live lint help

## cheap-eval: $(AGENTS) in parallel with cheap/free models
## claude-code routes via OpenRouter (needs OPENROUTER_API_KEY in .env).
## opencode routes via its own Zen provider (needs zen auth, no extra env).
## codex uses ~/.codex auth + config.toml model (run via full-eval or AGENTS=).
cheap-eval: export ANTHROPIC_BASE_URL    = https://openrouter.ai/api
cheap-eval: export ANTHROPIC_AUTH_TOKEN  = $(OPENROUTER_API_KEY)
cheap-eval: export ANTHROPIC_API_KEY     =
cheap-eval:
	uv run skill-eval run \
		--skill $(SKILL) \
		--evals $(EVALS) \
		$(AGENT_FLAGS) \
		--agent-model "claude-code=$(CLAUDE_CODE_MODEL)" \
		--agent-model "opencode=$(OPENCODE_MODEL)" \
		--agent-model "codex=$(CODEX_MODEL)" \
		--grader-model "$(GRADER_MODEL)" \
		--workspace $(WORKSPACE) \
		--concurrency $(CONCURRENCY) \
		--no-baseline

## full-eval: cheap-eval plus codex (needs ~/.codex/auth.json login)
full-eval: AGENTS = fake claude-code opencode codex
full-eval: cheap-eval

## fake-eval: fake harness only — zero API cost, CI-safe, no env vars needed
fake-eval:
	uv run skill-eval run \
		--skill $(SKILL) \
		--evals $(EVALS) \
		--agent fake \
		--grader-model "" \
		--workspace $(WORKSPACE) \
		--concurrency 1

## test: run unit + smoke tests (includes free e2e pipeline test)
test:
	uv run pytest -v --cov=skill_eval --cov-report=term-missing tests/

## test-e2e: free end-to-end pipeline tests only (fake harness, no API calls)
test-e2e:
	uv run pytest -v tests/test_e2e.py -m "not live"

## test-live: paid e2e tests against real agents + grader (claude-code, opencode, codex)
test-live: export SKILL_EVAL_LIVE        = 1
test-live: export ANTHROPIC_BASE_URL     = https://openrouter.ai/api
test-live: export ANTHROPIC_AUTH_TOKEN   = $(OPENROUTER_API_KEY)
test-live: export ANTHROPIC_API_KEY      =
test-live:
	uv run pytest -v tests/test_e2e.py -m live

## lint: ruff check + format check
lint:
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/

## help: list targets
help:
	@grep -E '^## ' Makefile | sed 's/## /  /'
