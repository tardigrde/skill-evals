# Skill Evaluation Framework

A Python framework for systematically evaluating agent skills across **OpenCode**, **Claude Code**, and **Codex**.

## Features

- **Multi-agent support**: Test skills across OpenCode, Claude Code, and Codex in a single run
- **Baseline comparison**: Automatically runs with-skill and without-skill configurations to measure skill impact
- **Deterministic + LLM grading**: Code-based checks for mechanical assertions + LLM rubric grading for qualitative assessments
- **Configurable concurrency**: Run multiple evals in parallel
- **Full token/timing extraction**: Parse each agent's native output format for comprehensive metrics
- **Workspace isolation**: Fresh temp directories with git repos for each eval run
- **Auto skill installation**: Automatically installs SKILL.md into the correct location for each agent type

## Installation

```bash
cd skill-eval
uv venv
source .venv/bin/activate
uv pip install -e .
```

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
      "assertions": [
        "A new git branch was created",
        "A git commit was created",
        "A pull request was created"
      ]
    }
  ]
}
```

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
- `--grader-model`: LLM model for rubric grading (default: gpt-4o)
- `--grader-base-url`: Custom API base URL for grader (uses OPENAI_BASE_URL env var)

### `report` - Display results summary

```bash
skill-eval report --workspace ./eval-workspace/commit-push-pr-workspace
skill-eval report --workspace ./eval-workspace/commit-push-pr-workspace --iteration 1
```

### `grade` - Re-grade existing results

```bash
skill-eval grade --workspace ./eval-workspace/commit-push-pr-workspace/iteration-1
```

### `init` - Initialize eval structure

```bash
skill-eval init my-skill --output ./skills
```

## Workspace Structure

Results follow the agentskills.io layout:

```
eval-workspace/
└── commit-push-pr-workspace/
    └── iteration-1/
        ├── eval-explicit-invoke/
        │   ├── with_skill/
        │   │   ├── outputs/
        │   │   │   ├── output.txt
        │   │   │   ├── stdout.log
        │   │   │   └── stderr.log
        │   │   ├── timing.json
        │   │   └── grading.json
        │   └── without_skill/
        │       ├── outputs/
        │       ├── timing.json
        │       └── grading.json
        ├── eval-implicit-invoke/
        │   ├── with_skill/
        │   └── without_skill/
        └── benchmark.json
```

## Assertion Types

### Deterministic checks (code-based)

- **File existence**: "package.json was created", "The file `README.md` exists"
- **Command execution**: "Ran npm install", "git commit was executed"
- **Content matching**: "Output contains 'success'", "Includes the phrase 'PR created'"
- **Valid JSON**: "The output is valid JSON"
- **Git operations**: "A new branch was created", "A commit was created"
- **PR creation**: "A pull request was created"

### LLM rubric grading

For assertions that can't be checked deterministically, the framework uses an LLM (configurable via `--grader-model` and `OPENAI_API_KEY` / `OPENAI_BASE_URL` env vars) to grade against a rubric.

## Environment Variables

- `OPENAI_API_KEY`: API key for LLM grading (required for rubric grading)
- `OPENAI_BASE_URL`: Custom API endpoint (optional, for Azure/OpenRouter/etc.)

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

## License

MIT
