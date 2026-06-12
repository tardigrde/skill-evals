# agent-skill-eval

**Evaluate agent skills through the real coding harnesses you use every day — Claude Code, Codex, and OpenCode — not the raw API.**

You wrote a `SKILL.md`. Does it actually make your agent better? agent-skill-eval answers that with data: it installs your skill into a fresh workspace, runs the *actual agent CLI* against your test prompts (with and without the skill), grades the results with deterministic state-diff checks plus an LLM rubric, and reports the measured impact — pass rates, pass@k across repeated runs, token costs, and wall-clock time.

Because the eval goes through the full harness — system prompt, skill discovery, permissions, tool use — you get exactly the behavior you'll see in daily use, including the failure mode that matters most: *the agent never triggering your skill at all*.

## Features

- **Real harnesses, end to end**: OpenCode, Claude Code, and Codex CLIs, in a single run
- **Baseline comparison**: with-skill vs. without-skill, with a per-agent delta
- **pass@k**: `--runs N` repeats every eval and reports full-pass rate and pass@k, because agents are stochastic and single-run numbers lie
- **State-delta grading**: code-based checks compare pre/post git state snapshots, so they don't false-pass on pre-existing branches, commits, or PRs
- **Negative controls**: `should_trigger: false` inverts assertions to catch accidental skill triggering
- **Honest grading**: assertions the grader can't check are *skipped*, not failed; a missing API key warns upfront instead of silently zeroing your pass rate
- **Pinned models**: `--agent-model claude-code=haiku --agent-model codex=gpt-5-mini` makes runs reproducible across machines
- **Recorded effective config**: every run's `run_meta.json` records model, reasoning effort, base URL, agent CLI version, and harness version — so "codex passed 97%" is attributable to an exact configuration, not whatever local config the CLI silently inherited
- **Reasoning control and telemetry**: `--reasoning-effort` pins the reasoning setting for agents that support it (codex), and reasoning output tokens are persisted in `timing.json`/`summary.json` when the agent reports them
- **Targeted reruns**: `--eval-id` runs/validates a single case instead of the whole suite — the cheap inner loop after a one-line skill edit
- **Budget guards**: per-case token/cost/duration limits with `warn`, `fail`, or `stop-suite` actions, so a runaway recovery loop can't silently burn quota
- **Live progress**: per-case console lines plus a tailable `progress.jsonl` — long runs are no longer opaque
- **Lifecycle hooks**: `--pre-run-command`, `--post-grade-command`, `--post-run-command` plug external setup, side-effect graders, and teardown into the run with structured `ASE_*` metadata
- **One-file summaries**: every run writes `summary.json` (pass rates, failures, token/cost totals, cleanup state); `agent-skill-eval status` reads it back without a model call
- **Scoped cleanup**: only removes artifacts recorded in `cleanup.json`; never closes unrelated PRs or deletes unrelated branches
- **Re-grading**: `agent-skill-eval grade` re-grades saved outputs without re-running agents
- **Markdown reports**: paste `agent-skill-eval report --format markdown` straight into a PR or blog post

## Installation

```bash
pip install agent-skill-eval
```

This installs two identical commands: `agent-skill-eval` and the short alias `ase`. The CLI is also runnable as a module — `python -m agent_skill_eval run ...` — which is handy when the scripts directory isn't on your `PATH` or you want to pin the interpreter (e.g. `uv run python -m agent_skill_eval`).

> **Coming soon:** subagent evals — evaluate custom subagent definitions the same way as skills, across the same harnesses.

Or from source with `uv`:

```bash
git clone https://github.com/tardigrde/agent-skill-eval
cd agent-skill-eval
uv venv && uv pip install -e ".[dev]"
```

You also need the agent CLIs you want to evaluate (`claude`, `codex`, `opencode`) installed and authenticated, and an `OPENROUTER_API_KEY` or `OPENAI_API_KEY` for LLM rubric grading.

## Quick Start

```bash
# 1. See what's available
agent-skill-eval list

# 2. Validate an eval suite
agent-skill-eval validate examples/write-release-notes/evals/evals.json

# 3. Run it (pin cheap models while iterating)
agent-skill-eval run \
  --skill ./skills/write-release-notes \
  --evals ./examples/write-release-notes/evals/evals.json \
  --agent claude-code --agent-model claude-code=haiku \
  --agent codex --agent-model codex=gpt-5-mini \
  --runs 3

# 4. Read the results
agent-skill-eval report --workspace ./eval-workspace/write-release-notes-workspace --show-evidence
```

To start a suite for your own skill:

```bash
agent-skill-eval init my-skill
```

This scaffolds `my-skill/SKILL.md` (frontmatter template), `my-skill/evals/evals.json` (one positive case and one negative control), and `my-skill/evals/files/` for fixtures.

## Defining evals

```json
{
  "skill_name": "write-release-notes",
  "evals": [
    {
      "id": "explicit-invoke",
      "prompt": "Write release notes for the commit history in commits.txt.",
      "expected_output": "A RELEASE_NOTES.md grouping changes by type with breaking changes highlighted.",
      "files": ["files/commits.txt"],
      "force_skill_invocation": true,
      "assertions": [
        "The file `RELEASE_NOTES.md` exists",
        "The breaking change is mentioned prominently",
        "The release notes do not mention any change that is not in commits.txt"
      ]
    },
    {
      "id": "negative-control",
      "prompt": "How many commits are listed in commits.txt?",
      "expected_output": "The skill should NOT trigger.",
      "files": ["files/commits.txt"],
      "should_trigger": false,
      "assertions": [
        "A new git branch was created",
        "A git commit was created",
        "The agent only answered the question without creating files"
      ]
    }
  ]
}
```

A JSON Schema for this format ships at [`schemas/evals.schema.json`](schemas/evals.schema.json) — point your editor at it for autocompletion, and run `agent-skill-eval validate <file>` in CI.

### Eval fields

| Field | Type | Purpose |
| --- | --- | --- |
| `id` | int \| str | Unique id within the suite |
| `prompt` | str | Prompt sent to the agent verbatim |
| `expected_output` | str | Reference output for LLM rubric grading |
| `files` | list[str] | Fixture file paths (resolved relative to the evals directory) |
| `stage_files` | bool | If true, fixture files are also `git add`-ed before the agent runs (default: false) |
| `assertions` | list[str] | Assertions to grade against |
| `should_trigger` | bool | If false, branch/commit/push/PR assertions are inverted (default: true) |
| `force_skill_invocation` | bool | If true, the prompt is prefixed with `Use the $<skill> skill.` (default: false) |

## How grading works

Each assertion is graded by the first matching method:

1. **Deterministic** — code-based checks against the pre/post git state delta and run logs. No LLM involved.
2. **LLM rubric** — anything the deterministic grader doesn't recognize goes to an LLM judge with the agent output, expected output, and workspace file listing.
3. **Skipped** — if no LLM grader is configured (missing API key) or the grader errors, the assertion is marked *skipped* and excluded from the pass rate, never silently failed.

### Recognized deterministic assertion patterns

The deterministic grader matches assertion text against these patterns (case-insensitive):

| Pattern in assertion text | Check performed |
| --- | --- |
| `branch` + `created`/`exists`/`new` | A new branch appeared in the state diff and is checked out |
| `commit` + `created`/`exists`/`new` | A new commit appeared and is on the current branch |
| `push` + `remote`/`branch`/`pushed` | The eval-created branch was pushed AND remote HEAD matches local HEAD |
| `pr` or `pull request` | A new open PR targets the eval-created branch (corroborated by `gh pr view` when available) |
| `file exists` or `created` + a filename | File matching the backticked/quoted name exists in the workspace |
| `ran` + a command name (`npm`, `git`, ...) | Command name appears in the run logs |
| `contains` or `includes` + `"quoted"`/`` `backticked` `` text | Agent output contains the text |
| `valid json` | Agent output (or a workspace file) parses as JSON |

Anything else falls through to the LLM rubric. With `should_trigger: false`, the branch/commit/push/PR checks invert: they pass only when those artifacts did **not** appear.

## CLI Commands

### `run`

```bash
agent-skill-eval run \
  --skill <skill-dir> --evals <evals.json> \
  --agent opencode --agent claude-code --agent codex \
  [--agent-model claude-code=haiku] [--agent-model codex=gpt-5-mini] \
  [--reasoning-effort medium] \
  [--harness-base-url https://openrouter.ai/api/v1] \
  [--runs 3] [--concurrency 2] [--iteration 1] \
  [--baseline/--no-baseline] [--cleanup] \
  [--timeout 600] [--retries 1] \
  [--eval-id wif-too-long-stop] \
  [--max-total-tokens-per-case 200000] [--budget-action fail] \
  [--pre-run-command "python scripts/setup.py"] \
  [--post-grade-command "python scripts/grade_external.py"] \
  [--post-run-command "python scripts/teardown.py"] \
  [--pricing-config pricing.json] \
  [--grader-model deepseek/deepseek-v4-flash] [--grader-base-url URL] \
  [--source-repo https://github.com/foo/bar.git] \
  [--workspace ./eval-workspace]
```

Key options:

- `--agent-model, -m`: model per agent as `agent=model`; a bare value applies to all agents. Repeatable.
- `--reasoning-effort`: reasoning setting passed to agents that support it (codex: `model_reasoning_effort`, e.g. `minimal`/`low`/`medium`/`high`/`xhigh`). Without it, agents silently inherit their own local config (e.g. `~/.codex/config.toml`) — two machines can then benchmark different reasoning settings under the same command line. Agents without a pass-through flag print a warning and record `null`. The effective value lands in `run_meta.json`.
- `--harness-base-url`: injected as `ANTHROPIC_BASE_URL` (claude-code) / `OPENAI_BASE_URL` (codex, opencode) into the agent process.
- `--runs, -n`: repeat each (eval, agent, config) N times; enables pass@k stats. Results land in `run-1/`, `run-2/`, ... subdirectories.
- `--timeout` / `--retries`: per-run agent timeout (default 600s) and retries on timeout or non-zero exit (default 1). Also settable via `ASE_AGENT_TIMEOUT` / `ASE_AGENT_RETRIES`.
- `--eval-id`: run only the named case(s); repeatable. Unknown ids fail fast with the list of available ids, before any model call. The applied filter is recorded in `evals_meta.json` (`selected_eval_ids`) and `summary.json` (`eval_ids`), and all artifacts naturally describe only the selected cases. The cheap inner loop after a small skill edit is `validate --eval-id X` then `run --eval-id X`.
- Budget guards (`--max-input-tokens-per-case`, `--max-non-cached-input-tokens-per-case`, `--max-output-tokens-per-case`, `--max-total-tokens-per-case`, `--max-reasoning-tokens-per-case`, `--max-cost-per-case`, `--max-duration-per-case`, `--budget-action warn|fail|stop-suite`): per-case limits checked after each agent run (mid-run kills remain `--timeout`'s job — budgets exist because a case can finish within the timeout and still be far too expensive). A violation is recorded in `timing.json` (`budget_exceeded`, `budget_reason`); with `fail` (the default) it also appends a failed `method: "budget"` assertion to the run's `grading.json`, and with `stop-suite` it additionally skips every run that hasn't started yet — useful to stop a live side-effect suite before more remote branches/PRs get created. `--max-cost-per-case` only fires when the run has a cost source (see Cost reporting); likewise `--max-reasoning-tokens-per-case` and `--max-non-cached-input-tokens-per-case` only fire when the run reported those values — an agent exposing less telemetry is never failed over an unknown quantity.
- Lifecycle hooks (`--pre-run-command`, `--post-grade-command`, `--post-run-command`): see [Lifecycle hooks](#lifecycle-hooks).
- `--pricing-config`: JSON file with USD-per-token rates for agents whose CLI reports no cost (see Cost reporting).

While the suite runs, each case prints start/finish lines (elapsed, tokens in/cached/out, cost), and `progress.jsonl` in the iteration directory gets one JSON event per line (`suite_started`, `run_started`, `agent_started`, `agent_finished`, `run_finished`, `budget_exceeded`, ...) — `tail -f` it from another shell to watch a long run.

### `report`

```bash
agent-skill-eval report --workspace <skill-workspace> [--iteration N] [--format table|markdown] [--show-evidence] [--failures-only]
```

`--show-evidence` prints the evidence string for every failed or skipped assertion — the state diff for deterministic checks, the judge's reasoning for LLM checks. `--failures-only` limits the per-eval detail to runs that had at least one failed assertion. `--format markdown` emits a paste-ready table.

### `status`

```bash
agent-skill-eval status --workspace <skill-workspace> [--iteration N]
```

Answers "what happened in the last run?" without a model call: pass rates per configuration, failed/skipped/errored runs, token totals with the cached share, total cost (or `unavailable`), budget violations, hook outcomes, and whether `cleanup.json` recorded remote side effects. Reads the iteration's `summary.json`; for runs that predate it, a reduced summary is rebuilt from the saved artifacts.

### `compare`

```bash
agent-skill-eval compare --workspace <skill-workspace> 1 2
```

Side-by-side pass rates of two iterations, per configuration, with pass-rate, time, and token deltas — the feedback loop for iterating on a SKILL.md.

### `validate`

```bash
agent-skill-eval validate path/to/evals.json [--eval-id <id>]
```

Schema check plus referenced-fixture existence and duplicate-id detection. Exit code 1 on any problem (CI-friendly). `--eval-id` validates only the selected case(s) (duplicate-id detection still covers the whole file); pair it with `run --eval-id` to confirm a targeted case is well-formed before spending a model call on it.

### `list`

```bash
agent-skill-eval list [--root .]
```

Discovers eval suites (`evals.json`) and skills (`SKILL.md`) under a directory.

### `grade`

```bash
agent-skill-eval grade --workspace <iteration-dir> [--recompute-benchmark]
```

Re-grades existing outputs using saved `evals_meta.json` and state snapshots. Two caveats: LLM-graded assertions are re-evaluated from scratch and may flip verdicts, and because the original agent workspace is deleted after the run, the judge re-grades from the saved artifacts (agent output, logs) rather than the live workspace files.

### `cleanup`

```bash
agent-skill-eval cleanup --workspace ./eval-workspace [--yes]
```

Only closes PRs and deletes remote branches recorded in `cleanup.json`. Never touches unrelated PRs, branches, or workspaces.

### `init`

```bash
agent-skill-eval init my-skill [--output ./examples]
```

## Lifecycle hooks

Skills with external side effects (push, PR/MR creation, provider APIs) need setup, provider-specific grading, and teardown that the harness can't know about. Instead of hard-coding providers, `run` exposes three shell-command hook points; each receives run metadata as `ASE_*` environment variables on top of the parent environment:

- `--pre-run-command` (repeatable): runs once before any agent case — seed or reset a scratch repo, run static checks on the skill text. A non-zero exit **aborts the suite before a single model call**. Env: `ASE_SKILL_NAME`, `ASE_SKILL_DIR`, `ASE_EVALS_PATH`, `ASE_ITERATION`, `ASE_ITERATION_DIR`, `ASE_WORKSPACE_BASE`, `ASE_SOURCE_REPO`, `ASE_RUN_ID`, `ASE_EVAL_IDS` (comma-separated).
- `--post-grade-command` (repeatable): runs once per (eval, agent, config) run, after `grading.json` is written and **before the workspace is deleted** — verify remote state, check side-effect files. On top of the suite-level vars it gets `ASE_EVAL_ID`, `ASE_AGENT`, `ASE_WITH_SKILL` (`1`/`0`), `ASE_RUN_INDEX`, `ASE_WORKSPACE_PATH`, `ASE_OUTPUT_DIR`, `ASE_PRE_STATE_PATH`, `ASE_POST_STATE_PATH`, `ASE_TIMING_PATH`, `ASE_RUN_META_PATH`, `ASE_GRADING_PATH`. If the hook prints a JSON array of `{"text": ..., "passed": ..., "evidence": ...}` objects to stdout, they are appended to the run's `grading.json` as `method: "hook"` assertion results and the summary is recomputed — external checks land in the same artifact `report` reads. A non-zero exit appends one failed hook check. Raw hook output is saved to `outputs/post_grade_hooks.json`.
- `--post-run-command` (repeatable): runs once after the suite (teardown, cleanup verification). Failures are recorded in `summary.json` and printed, but don't fail the run — the results already exist.

Hook commands run through the shell from the invocation directory, with a timeout of `ASE_HOOK_TIMEOUT` seconds (default 600).

```bash
agent-skill-eval run --skill ./skills/my-skill --evals ./evals/evals.json --agent codex \
  --eval-id feature-branch \
  --pre-run-command  "python scripts/setup_source_repo.py" \
  --post-grade-command "python scripts/grade_remote_state.py" \
  --post-run-command "python scripts/teardown_remote.py"
```

## Example skills

Five example skills ship with the repo, chosen to exercise different grading surfaces:

| Skill | Tests | Grading surface |
| --- | --- | --- |
| [`commit-push-pr`](skills/commit-push-pr/SKILL.md) | git workflow automation | deterministic state-diff checks (branch/commit/push/PR); needs a `--source-repo` |
| [`fix-failing-tests`](skills/fix-failing-tests/SKILL.md) | error recovery / iterative refinement | deterministic + file checks; fully offline |
| [`write-release-notes`](skills/write-release-notes/SKILL.md) | subjective writing quality, anti-fabrication | LLM rubric grading; fully offline |
| [`validate-config`](skills/validate-config/SKILL.md) | bundled resources: does the agent run the skill's `scripts/` and read its `references/`? | command-ran + file + content checks; fully offline |
| [`review-diff`](skills/review-diff/SKILL.md) | read-only analysis: planted bugs found, documented decoy not flagged, nothing modified | chat-output-only grading (content + LLM rubric); fully offline |

Each has a matching eval suite under [`examples/`](examples/). `skills/` holds the artifacts being evaluated; `examples/` holds the test cases — so you can test one skill against many suites or one suite against many skill versions.

## Reading results

### Workspace layout

```
eval-workspace/
└── <skill>-workspace/
    └── iteration-1/
        ├── evals_meta.json          # eval definitions + selected_eval_ids (used by `grade`)
        ├── cleanup.json             # manifest of artifacts created by this run
        ├── benchmark.json           # aggregate stats per (agent, config)
        ├── summary.json             # one-file run summary (used by `status`)
        ├── progress.jsonl           # live per-run events; tail -f during the run
        └── eval-<id>/<agent>/<config>/   # config = with_skill | without_skill
            ├── run-N/               # only when --runs > 1
            ├── outputs/
            │   ├── output.txt       # final agent output
            │   ├── stdout.log / stderr.log
            │   ├── post_grade_hooks.json   # only with --post-grade-command
            │   └── pre_state.json / post_state.json
            ├── timing.json          # tokens (incl. non-cached/reasoning splits), duration, exit_code, timed_out, retries, budget verdict
            ├── grading.json         # per-assertion results
            └── run_meta.json        # agent, with_skill, run_index, model, reasoning_effort, base_url, agent_cli_version, harness_version, ...
```

### grading.json

```json
{
  "assertion_results": [
    {
      "text": "A new git branch was created",
      "passed": false,
      "method": "deterministic",
      "skipped": false,
      "evidence": "No new branch appeared in this run. current_branch='main'"
    }
  ],
  "summary": {"passed": 2, "failed": 1, "skipped": 0, "total": 3, "pass_rate": 0.667}
}
```

To debug a failure: find `"passed": false` entries, read `evidence`, compare `pre_state.json`/`post_state.json`, then check `outputs/output.txt` for the agent's full response. Or just run `agent-skill-eval report --show-evidence`.

### Iterating on a skill

1. `agent-skill-eval run ...` → 2. `agent-skill-eval report --show-evidence` → 3. edit SKILL.md → 4. `agent-skill-eval run --iteration 2 ...` → 5. `agent-skill-eval compare --workspace ... 1 2`

### Comparing agents: reading with/without-skill deltas

Run several agents in one invocation and every agent gets its own baseline comparison:

```bash
agent-skill-eval run \
  --skill ./skills/fix-failing-tests \
  --evals ./examples/fix-failing-tests/evals/evals.json \
  --agent claude-code --agent-model claude-code=claude-haiku-4-5-20251001 \
  --agent opencode --agent-model opencode=deepseek/deepseek-v4-flash:free \
  --runs 3

agent-skill-eval report --workspace ./eval-workspace/fix-failing-tests-workspace --format markdown
```

The report shows one row per (agent, config) and a delta per agent (numbers below are illustrative):

| Configuration | Pass Rate | Full Pass / pass@k | Time (s) | Tokens | Cost (USD) |
| --- | --- | --- | --- | --- | --- |
| claude-code_with_skill | 91.7% +/- 14.4% | 67% (k=3) | 41.2 +/- 8.0 | 1840 +/- 312 | 0.0042 +/- 0.0011 |
| claude-code_without_skill | 58.3% +/- 14.4% | 33% (k=3) | 52.7 +/- 12.1 | 2410 +/- 405 | 0.0058 +/- 0.0019 |
| opencode_with_skill | 83.3% +/- 0.0% | 67% (k=3) | 64.9 +/- 9.3 | 2980 +/- 220 | 0.0000 +/- 0.0000 |
| opencode_without_skill | 50.0% +/- 25.0% | 33% (k=3) | 71.5 +/- 15.8 | 3340 +/- 510 | 0.0000 +/- 0.0000 |

**Delta (with_skill - without_skill):**

- `claude-code`: pass rate +33.3%, time -11.5s, tokens -570, cost -0.0016 USD
- `opencode`: pass rate +33.3%, time -6.6s, tokens -360, cost +0.0000 USD

How to read it: the **delta rows** are the skill's measured value per agent — here the skill lifts pass rate by ~33 points on both agents *and* saves time/tokens, the strongest possible signal. A positive pass-rate delta with a large token increase means the skill works but is verbose; a near-zero delta means that agent doesn't benefit (check `report --show-evidence` to see whether it never triggered the skill). The same numbers are machine-readable in `benchmark.json`: per-config stats under `run_summary`, per-agent deltas under `deltas`, keyed by agent name.

## Environment variables

- `OPENROUTER_API_KEY` / `OPENAI_API_KEY`: API key for LLM rubric grading
- `OPENAI_BASE_URL`: custom grader endpoint (defaults to OpenRouter)
- `ASE_AGENT_TIMEOUT` / `ASE_AGENT_RETRIES`: harness timeout/retry defaults
- `ASE_HOOK_TIMEOUT`: lifecycle hook command timeout in seconds (default 600)
- `ASE_KEEP_WORKSPACE`: keep per-eval workspaces for debugging

## Agent-specific details

| Agent | Command | Skill install path |
| --- | --- | --- |
| OpenCode | `opencode run --format json --dangerously-skip-permissions` | `.opencode/skills/<name>/SKILL.md` |
| Claude Code | `claude -p --output-format json --dangerously-skip-permissions` | `.claude/skills/<name>/SKILL.md` |
| Codex | `codex exec --json --sandbox workspace-write --skip-git-repo-check` | `.codex/skills/<name>/SKILL.md` |

### Cost reporting

`timing.json` records `cost_usd` per run, taken from the agent CLI itself (claude: `total_cost_usd`, opencode: per-step `cost`). When no cost is available, `cost_usd` is `null` — **unavailable, not $0.00** — and reports/`benchmark.json` show `n/a` instead of a misleading zero. Cost stats are computed only over the runs that reported a cost (`cost_runs` in `benchmark.json`, `runs_with_cost` in `summary.json`).

Codex's CLI reports token counts but no cost. To get cost numbers anyway, pass `--pricing-config pricing.json` with your provider's USD-per-token rates, keyed by the exact `--agent-model` value (fields mirror OpenRouter's pricing schema):

```json
{
  "gpt-5.4-mini": {
    "prompt": 2.5e-07,
    "completion": 2e-06,
    "input_cache_read": 2.5e-08
  }
}
```

The computed value lands in `cost_usd` with `cost_usd_source: "pricing-config"`. Cached input is billed at `input_cache_read` (falling back to `prompt`); note that codex reports `input_tokens` *including* cache reads while claude-code and opencode report them separately — the harness accounts for this per agent. `summary.json` splits the totals (`tokens.cached`, `tokens.non_cached_input`, `tokens.cached_pct`), because on long agent sessions most input tokens are cache reads and the raw `input_tokens` number wildly overstates billable spend. Each run's `timing.json` also persists `non_cached_input_tokens` (computed with that run's CLI semantics) and `reasoning_output_tokens` when the agent reports reasoning telemetry (codex `turn.completed`, opencode `step_finish`) — `null` means unreported, not zero.

One sharp edge: the claude CLI prices runs at **Anthropic list prices** regardless of the endpoint it talks to. When you route claude-code through OpenRouter (`--harness-base-url` or `ANTHROPIC_BASE_URL`), agent-skill-eval reconciles the cost by recomputing it from the run's token counts and OpenRouter's published per-model rates. `timing.json` then shows:

- `cost_usd_source`: `"cli"` (the CLI's own number), `"openrouter-pricing"` (reconciled), `"pricing-config"` (computed from `--pricing-config`), or `"cli-unreconciled"` (reconciliation failed — e.g. a short model alias like `haiku` that can't be mapped to an OpenRouter slug — so `cost_usd` is the CLI's list-price estimate and actual billing differs)
- `cost_usd_cli`: the CLI's original estimate, kept alongside the reconciled value

Pin full model IDs (`claude-haiku-4-5-20251001`, not `haiku`) to keep reconciliation working.

## Development

```bash
uv run --extra dev pytest -q
uv run --extra dev ruff check src/ tests/
uv run --extra dev ruff format --check src/ tests/
```

A `fake` agent type exists for offline testing of the full run→grade→report pipeline (used by the CI smoke test). To record a demo cast: `./scripts/record-demo.sh`.

## License

MIT
