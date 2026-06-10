# skill-eval

**Evaluate agent skills through the real coding harnesses you use every day — Claude Code, Codex, and OpenCode — not the raw API.**

You wrote a `SKILL.md`. Does it actually make your agent better? skill-eval answers that with data: it installs your skill into a fresh workspace, runs the *actual agent CLI* against your test prompts (with and without the skill), grades the results with deterministic state-diff checks plus an LLM rubric, and reports the measured impact — pass rates, pass@k across repeated runs, token costs, and wall-clock time.

Because the eval goes through the full harness — system prompt, skill discovery, permissions, tool use — you get exactly the behavior you'll see in daily use, including the failure mode that matters most: *the agent never triggering your skill at all*.

## Features

- **Real harnesses, end to end**: OpenCode, Claude Code, and Codex CLIs, in a single run
- **Baseline comparison**: with-skill vs. without-skill, with a per-agent delta
- **pass@k**: `--runs N` repeats every eval and reports full-pass rate and pass@k, because agents are stochastic and single-run numbers lie
- **State-delta grading**: code-based checks compare pre/post git state snapshots, so they don't false-pass on pre-existing branches, commits, or PRs
- **Negative controls**: `should_trigger: false` inverts assertions to catch accidental skill triggering
- **Honest grading**: assertions the grader can't check are *skipped*, not failed; a missing API key warns upfront instead of silently zeroing your pass rate
- **Pinned models**: `--agent-model claude-code=haiku --agent-model codex=gpt-5-mini` makes runs reproducible across machines
- **Scoped cleanup**: only removes artifacts recorded in `cleanup.json`; never closes unrelated PRs or deletes unrelated branches
- **Re-grading**: `skill-eval grade` re-grades saved outputs without re-running agents
- **Markdown reports**: paste `skill-eval report --format markdown` straight into a PR or blog post

## Installation

```bash
pip install skill-eval
```

Or from source with `uv`:

```bash
git clone https://github.com/tardigrde/skill-evals
cd skill-evals
uv venv && uv pip install -e ".[dev]"
```

You also need the agent CLIs you want to evaluate (`claude`, `codex`, `opencode`) installed and authenticated, and an `OPENROUTER_API_KEY` or `OPENAI_API_KEY` for LLM rubric grading.

## Quick Start

```bash
# 1. See what's available
skill-eval list

# 2. Validate an eval suite
skill-eval validate examples/write-release-notes/evals/evals.json

# 3. Run it (pin cheap models while iterating)
skill-eval run \
  --skill ./skills/write-release-notes \
  --evals ./examples/write-release-notes/evals/evals.json \
  --agent claude-code --agent-model claude-code=haiku \
  --agent codex --agent-model codex=gpt-5-mini \
  --runs 3

# 4. Read the results
skill-eval report --workspace ./eval-workspace/write-release-notes-workspace --show-evidence
```

To start a suite for your own skill:

```bash
skill-eval init my-skill
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

A JSON Schema for this format ships at [`schemas/evals.schema.json`](schemas/evals.schema.json) — point your editor at it for autocompletion, and run `skill-eval validate <file>` in CI.

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
skill-eval run \
  --skill <skill-dir> --evals <evals.json> \
  --agent opencode --agent claude-code --agent codex \
  [--agent-model claude-code=haiku] [--agent-model codex=gpt-5-mini] \
  [--harness-base-url https://openrouter.ai/api/v1] \
  [--runs 3] [--concurrency 2] [--iteration 1] \
  [--baseline/--no-baseline] [--cleanup] \
  [--timeout 600] [--retries 1] \
  [--grader-model deepseek/deepseek-v4-flash] [--grader-base-url URL] \
  [--source-repo https://github.com/foo/bar.git] \
  [--workspace ./eval-workspace]
```

Key options:

- `--agent-model, -m`: model per agent as `agent=model`; a bare value applies to all agents. Repeatable.
- `--harness-base-url`: injected as `ANTHROPIC_BASE_URL` (claude-code) / `OPENAI_BASE_URL` (codex, opencode) into the agent process.
- `--runs, -n`: repeat each (eval, agent, config) N times; enables pass@k stats. Results land in `run-1/`, `run-2/`, ... subdirectories.
- `--timeout` / `--retries`: per-run agent timeout (default 600s) and retries on timeout or non-zero exit (default 1). Also settable via `SKILL_EVAL_AGENT_TIMEOUT` / `SKILL_EVAL_AGENT_RETRIES`.

### `report`

```bash
skill-eval report --workspace <skill-workspace> [--iteration N] [--format table|markdown] [--show-evidence]
```

`--show-evidence` prints the evidence string for every failed or skipped assertion — the state diff for deterministic checks, the judge's reasoning for LLM checks. `--format markdown` emits a paste-ready table.

### `compare`

```bash
skill-eval compare --workspace <skill-workspace> 1 2
```

Side-by-side pass rates of two iterations, per configuration, with the change — the feedback loop for iterating on a SKILL.md.

### `validate`

```bash
skill-eval validate path/to/evals.json
```

Schema check plus referenced-fixture existence and duplicate-id detection. Exit code 1 on any problem (CI-friendly).

### `list`

```bash
skill-eval list [--root .]
```

Discovers eval suites (`evals.json`) and skills (`SKILL.md`) under a directory.

### `grade`

```bash
skill-eval grade --workspace <iteration-dir> [--recompute-benchmark]
```

Re-grades existing outputs using saved `evals_meta.json` and state snapshots. Two caveats: LLM-graded assertions are re-evaluated from scratch and may flip verdicts, and because the original agent workspace is deleted after the run, the judge re-grades from the saved artifacts (agent output, logs) rather than the live workspace files.

### `cleanup`

```bash
skill-eval cleanup --workspace ./eval-workspace [--yes]
```

Only closes PRs and deletes remote branches recorded in `cleanup.json`. Never touches unrelated PRs, branches, or workspaces.

### `init`

```bash
skill-eval init my-skill [--output ./examples]
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
        ├── evals_meta.json          # eval definitions (used by `grade`)
        ├── cleanup.json             # manifest of artifacts created by this run
        ├── benchmark.json           # aggregate stats per (agent, config)
        └── eval-<id>/<agent>/<config>/   # config = with_skill | without_skill
            ├── run-N/               # only when --runs > 1
            ├── outputs/
            │   ├── output.txt       # final agent output
            │   ├── stdout.log / stderr.log
            │   └── pre_state.json / post_state.json
            ├── timing.json          # tokens, duration, exit_code, timed_out, retries
            ├── grading.json         # per-assertion results
            └── run_meta.json        # agent, with_skill, run_index, ...
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

To debug a failure: find `"passed": false` entries, read `evidence`, compare `pre_state.json`/`post_state.json`, then check `outputs/output.txt` for the agent's full response. Or just run `skill-eval report --show-evidence`.

### Iterating on a skill

1. `skill-eval run ...` → 2. `skill-eval report --show-evidence` → 3. edit SKILL.md → 4. `skill-eval run --iteration 2 ...` → 5. `skill-eval compare --workspace ... 1 2`

## Environment variables

- `OPENROUTER_API_KEY` / `OPENAI_API_KEY`: API key for LLM rubric grading
- `OPENAI_BASE_URL`: custom grader endpoint (defaults to OpenRouter)
- `SKILL_EVAL_AGENT_TIMEOUT` / `SKILL_EVAL_AGENT_RETRIES`: harness timeout/retry defaults
- `SKILL_EVAL_KEEP_WORKSPACE`: keep per-eval workspaces for debugging

## Agent-specific details

| Agent | Command | Skill install path |
| --- | --- | --- |
| OpenCode | `opencode run --format json --dangerously-skip-permissions` | `.opencode/skills/<name>/SKILL.md` |
| Claude Code | `claude -p --output-format json --dangerously-skip-permissions` | `.claude/skills/<name>/SKILL.md` |
| Codex | `codex exec --json --full-auto` | `.codex/skills/<name>/SKILL.md` |

## Development

```bash
uv run --extra dev pytest -q
uv run --extra dev ruff check src/ tests/
uv run --extra dev ruff format --check src/ tests/
```

A `fake` agent type exists for offline testing of the full run→grade→report pipeline (used by the CI smoke test). To record a demo cast: `./scripts/record-demo.sh`.

## License

MIT
