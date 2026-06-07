# Skill Evaluation Framework

A Python framework for systematically evaluating agent skills across **OpenCode**, **Claude Code**, and **Codex**.

## Features

- **Multi-agent support**: Test skills across OpenCode, Claude Code, and Codex in a single run
- **Baseline comparison**: Automatically runs with-skill and without-skill configurations to measure skill impact
- **State-delta grading**: Code-based checks compare pre/post git state snapshots, so they don't false-pass on pre-existing branches, commits, or PRs
- **Scoped cleanup**: Cleanup only removes artifacts recorded in `cleanup.json`; never closes all PRs or deletes all branches
- **Re-grading**: `skill-eval grade` re-grades existing outputs using saved `evals_meta.json` and state snapshots
- **Negative controls**: `should_trigger: false` inverts branch/commit/push/PR assertions to catch accidental triggering
- **Configurable concurrency**: Run multiple evals in parallel
- **Full token/timing extraction**: Parse each agent's native output format for comprehensive metrics
- **Workspace isolation**: Fresh temp directories with git repos for each eval run
- **Auto skill installation**: Automatically installs SKILL.md into the correct location for each agent type

## Installation

This project uses `pyproject.toml` with optional dev dependencies. The recommended workflow is `uv`:

```bash
cd skill-eval
uv venv
uv pip install -e ".[dev]"
```

Or run directly via uv without activating the venv:

```bash
uv run --extra dev skill-eval --help
```

You can also run the module directly without installing the console script:

```bash
python -m skill_eval --help
```

## Development

Run tests and lints with the dev extras:

```bash
uv run --extra dev pytest -q
uv run --extra dev ruff check src/ tests/
uv run --extra dev ruff format --check src/ tests/
```

A writable uv cache directory is required in some sandboxes:

```bash
UV_CACHE_DIR=/path/to/cache uv run --extra dev pytest -q
```

CI uses `pip install -e ".[dev]"` and runs `pytest -v` plus `ruff check` and `ruff format --check`.

## Quick Start

### 1. Create an eval suite

```bash
skill-eval init my-skill
```

This creates:
```
my-skill/
└── evals/
    ├── evals.json
    └── files/
```

### 2. Define test cases in `evals.json`

```json
{
  "skill_name": "commit-push-pr",
  "evals": [
    {
      "id": "explicit-invoke",
      "prompt": "Use the $commit-push-pr skill to commit and push my changes",
      "expected_output": "A new branch is created, changes committed, pushed, and PR created",
      "files": [],
      "force_skill_invocation": true,
      "stage_files": true,
      "assertions": [
        "A new git branch was created",
        "A git commit was created",
        "A pull request was created or the PR URL is mentioned in the output"
      ]
    },
    {
      "id": "negative-control",
      "prompt": "Show me the git log for the last 10 commits",
      "expected_output": "The skill should NOT trigger.",
      "should_trigger": false,
      "assertions": [
        "A new git branch was created",
        "A git commit was created",
        "Changes were pushed to remote",
        "A pull request was created",
        "The output contains the word `commit` or `Initial`"
      ]
    }
  ]
}
```

The negative-control assertions are intentionally broad: they check branch, commit, push, PR, **and** content to ensure the skill did not accidentally trigger. The `should_trigger: false` flag inverts the deterministic checks so they pass only when those artifacts are absent.

### 3. Run evaluations

```bash
skill-eval run \
  --skill ./skills/commit-push-pr \
  --evals ./examples/commit-push-pr/evals/evals.json \
  --agent opencode \
  --agent claude-code \
  --agent codex \
  --concurrency 2
```

### 4. View results

```bash
skill-eval report --workspace ./eval-workspace/commit-push-pr-workspace
```

## CLI Commands

### `run` - Execute evaluations

```bash
skill-eval run \
  --skill <path-to-skill-dir> \
  --evals <path-to-evals.json> \
  --agent opencode \
  --agent claude-code \
  --agent codex \
  --workspace ./eval-workspace \
  --iteration 1 \
  --concurrency 2 \
  --baseline \
  --source-repo https://github.com/foo/bar.git \
  --grader-model gpt-4o
```

**Options:**
- `--skill, -s`: Path to skill directory containing SKILL.md (required)
- `--evals, -e`: Path to evals.json file (required)
- `--agent, -a`: Agent(s) to evaluate: opencode, claude-code, codex (default: opencode)
- `--workspace, -w`: Base directory for eval workspace (default: ./eval-workspace)
- `--iteration, -i`: Iteration number (default: 1)
- `--concurrency, -c`: Number of parallel eval runs (default: 1)
- `--baseline/--no-baseline`: Run without-skill baseline (default: enabled)
- `--source-repo`: Git repo URL to clone as workspace (instead of fresh git init)
- `--cleanup`: Run cleanup of recorded artifacts after the run
- `--grader-model`: LLM model for rubric grading (default: `deepseek/deepseek-v4-flash`)
- `--grader-base-url`: Custom API base URL for grader (uses OPENAI_BASE_URL env var)

### `report` - Display results summary

```bash
skill-eval report --workspace ./eval-workspace/commit-push-pr-workspace
skill-eval report --workspace ./eval-workspace/commit-push-pr-workspace --iteration 1
```

### `grade` - Re-grade existing results

```bash
skill-eval grade --workspace ./eval-workspace/commit-push-pr-workspace/iteration-1
skill-eval grade --workspace ./eval-workspace/commit-push-pr-workspace/iteration-1 --recompute-benchmark
```

Re-grades each config using `evals_meta.json`, the pre/post state snapshots, and writes updated `grading.json` files. With `--recompute-benchmark`, also rebuilds `benchmark.json` from per-run metadata.

### `cleanup` - Remove recorded eval artifacts

```bash
skill-eval cleanup --workspace ./eval-workspace
skill-eval cleanup --iteration ./eval-workspace/commit-push-pr-workspace/iteration-1
skill-eval cleanup --workspace ./eval-workspace --yes
```

Only closes PRs and deletes remote branches that were recorded in `cleanup.json` for the iteration. It never closes unrelated PRs or deletes unrelated branches.

### `init` - Initialize eval structure

```bash
skill-eval init my-skill --output ./skills
```

### `--version` - Show version

```bash
skill-eval --version
```

## Directory Convention: `examples/` vs `skills/`

The repo uses two top-level directories for a reason:

- **`skills/`** — Contains the agent skill definitions (`SKILL.md` files). These are the artifacts being evaluated. Pass a skill directory to `--skill`.
- **`examples/`** — Contains eval suites (`evals.json` + fixture files). These define the test cases, prompts, and assertions. Pass an evals file to `--evals`.

The separation lets you test the same skill against different eval suites, or the same eval suite against different versions of a skill. The `init` command creates the `examples/` layout:

```bash
skill-eval init my-skill            # creates ./my-skill/evals/
skill-eval init my-skill --output ./examples  # creates ./examples/my-skill/evals/
```

The `skills/` directory is typically managed manually or by your skill authoring workflow.

## Workspace Structure

Results follow this layout (per skill, per iteration, per eval, per agent, per config):

```
eval-workspace/
└── commit-push-pr-workspace/
    └── iteration-1/
        ├── evals_meta.json
        ├── cleanup.json
        ├── benchmark.json
        ├── eval-explicit-invoke/
        │   ├── opencode/
        │   │   ├── with_skill/
        │   │   │   ├── outputs/
        │   │   │   │   ├── output.txt
        │   │   │   │   ├── stdout.log
        │   │   │   │   ├── stderr.log
        │   │   │   │   ├── pre_state.json
        │   │   │   │   └── post_state.json
        │   │   │   ├── timing.json
        │   │   │   ├── grading.json
        │   │   │   └── run_meta.json
        │   │   └── without_skill/
        │   │       └── ...
        │   ├── claude-code/
        │   │   ├── with_skill/
        │   │   └── without_skill/
        │   └── codex/
        │       ├── with_skill/
        │       └── without_skill/
        └── eval-implicit-invoke/
            └── ...
```

Per-config files:
- `outputs/output.txt`: final agent output
- `outputs/stdout.log` / `outputs/stderr.log`: raw harness I/O
- `outputs/pre_state.json`: git/PR state snapshot captured before the agent ran
- `outputs/post_state.json`: git/PR state snapshot captured after the agent ran
- `timing.json`: token usage and wall-clock timing
- `grading.json`: assertion results (deterministic + LLM)
- `run_meta.json`: eval id, agent, with_skill, iteration, run id (used by `grade --recompute-benchmark`)

Per-iteration files:
- `evals_meta.json`: full eval case definitions used to re-grade
- `cleanup.json`: manifest of remote branches, PR numbers, and workspace paths created by this run
- `benchmark.json`: aggregate pass rate / time / tokens per (agent, with_skill)

## Eval Schema

Each entry in `evals.json` supports these fields:

| Field | Type | Purpose |
| --- | --- | --- |
| `id` | int \| str | Unique id within the suite |
| `prompt` | str | Prompt sent to the agent (verbatim, with-skill mode only prepends `Use the $skill` if `force_skill_invocation` is true) |
| `expected_output` | str | Reference output for LLM rubric grading |
| `files` | list[str] | Fixture file paths (resolved relative to the evals directory) |
| `stage_files` | bool | If true, fixture files are copied AND `git add`-ed before the agent runs (default: false) |
| `assertions` | list[str] | Assertions to grade against |
| `should_trigger` | bool | If false, branch/commit/push/PR assertions are inverted (default: true) |
| `force_skill_invocation` | bool | If true, the prompt is rewritten to start with `Use the $<skill> skill.` (default: false) |

## Assertion Types

### Deterministic checks (code-based, against pre/post state deltas)

- **File existence**: "package.json was created", "The file `README.md` exists"
- **Command execution**: "Ran npm install", "git commit was executed"
- **Content matching**: "Output contains 'success'", "Includes the phrase 'PR created'"
- **Valid JSON**: "The output is valid JSON"
- **Git operations**: "A new branch was created", "A commit was created"
- **Push check**: "Changes were pushed to remote" — passes only if the eval-created branch was pushed AND the remote HEAD matches the local HEAD
- **PR check**: "A pull request was created" — passes only if a new PR targets the eval-created branch

The deterministic grader prefers persisted `pre_state.json` / `post_state.json` so that re-grading works even after the workspace is deleted.

### Negative-control / `should_trigger: false`

When `should_trigger: false`, the deterministic branch/commit/push/PR assertions are inverted. They PASS only if those artifacts did NOT appear during the run. This catches accidental triggering of the skill.

### LLM rubric grading

For assertions that can't be checked deterministically, the framework uses an LLM (configurable via `--grader-model` and `OPENAI_API_KEY` / `OPENAI_BASE_URL` env vars) to grade against a rubric.

## Environment Variables

- `OPENAI_API_KEY`: API key for LLM grading (required for rubric grading)
- `OPENROUTER_API_KEY`: Alternative API key (used if `OPENAI_API_KEY` is unset)
- `OPENAI_BASE_URL`: Custom API endpoint (optional, for Azure/OpenRouter/etc.)
- `SKILL_EVAL_KEEP_WORKSPACE`: If set, eval workspaces are not deleted between runs

## Agent-Specific Details

### OpenCode
- Command: `opencode run --format json --dangerously-skip-permissions`
- Skill path: `.opencode/skills/<name>/SKILL.md`
- Output: JSON events with usage data

### Claude Code
- Command: `claude -p --output-format json --dangerously-skip-permissions`
- Skill path: `.claude/skills/<name>/SKILL.md`
- Output: JSON with usage and cost data

### Codex
- Command: `codex exec --json --full-auto`
- Skill path: `.codex/skills/<name>/SKILL.md`
- Output: JSONL stream with structured events

## Example: commit-push-pr skill

The included example skill automates the git workflow:
1. Detects base branch from remote
2. Fetches and updates base branch
3. Creates feature branch
4. Commits changes
5. Pushes to remote
6. Creates PR via `gh` CLI

Run it:
```bash
skill-eval run \
  --skill ./skills/commit-push-pr \
  --evals ./examples/commit-push-pr/evals/evals.json \
  --agent opencode
```

## Iterating on Skills

1. Run evals: `skill-eval run ...`
2. Review results: `skill-eval report ...`
3. Analyze failed assertions in `grading.json` files
4. Update SKILL.md based on failures
5. Re-run with incremented iteration: `skill-eval run --iteration 2 ...`
6. Compare benchmarks across iterations

## Reading `grading.json` Evidence

When an assertion fails, `grading.json` contains the details you need to debug it. Each file has this structure:

```json
{
  "assertions": [
    {
      "assertion": "A new git branch was created",
      "passed": false,
      "method": "deterministic",
      "evidence": "pre_state.heads = ['main']; post_state.heads = ['main'] — no new branch appeared"
    },
    {
      "assertion": "The output mentions the PR URL",
      "passed": true,
      "method": "llm",
      "evidence": "The output contains 'https://github.com/foo/bar/pull/42'"
    }
  ],
  "summary": {
    "passed": 2,
    "total": 3,
    "pass_rate": 0.667
  }
}
```

Key fields:

- **`method`**: `"deterministic"` means the grader compared `pre_state.json` and `post_state.json` snapshots. `"llm"` means an LLM graded the assertion against the rubric.
- **`evidence`**: For deterministic checks, this shows the exact state values that caused the pass/fail. For LLM checks, this is the model's reasoning.
- **`assertion`**: The original assertion string from `evals.json`.

To debug a failure:
1. Open `grading.json` in the failing config directory (e.g. `eval-explicit-invoke/opencode/with_skill/grading.json`)
2. Find assertions with `"passed": false`
3. Check `"evidence"` — deterministic failures show the state diff; LLM failures show the model's rationale
4. Compare `pre_state.json` and `post_state.json` to see what actually changed in the workspace
5. Check `outputs/output.txt` for the agent's full response

## Cleanup Safety

The `cleanup` command and `--cleanup` flag only remove artifacts recorded in `cleanup.json`. They will:
- Close PRs whose numbers are listed in the manifest
- Delete remote branches listed in the manifest
- Remove local workspace paths listed in the manifest

They will NOT:
- Close all open PRs in the source repo
- Delete all non-default branches
- Remove unrecorded `skill-eval-*` workspaces

## License

MIT
