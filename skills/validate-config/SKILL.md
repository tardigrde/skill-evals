---
name: validate-config
description: Validate a project configuration file against the team's structural requirements and naming/range conventions, then write a CONFIG_REPORT.md listing every violation.
license: MIT
compatibility: opencode, claude-code, codex
metadata:
  workflow: validate-report
---

## What I do

Validate a JSON configuration file (e.g. `app_config.json`) in two passes:

1. **Structural pass**: run the bundled validation script, which checks required keys and value types.
2. **Convention pass**: check every value against the team's convention rules, which are documented in this skill's `references/config-rules.md`.

Then write a `CONFIG_REPORT.md` in the workspace root listing every violation found, and summarize the result to the user.

## When to use me

Use when the user asks to validate, audit, lint, or check a configuration file, or asks whether a config follows team conventions or policy. Trigger on phrases like:
- "validate the config"
- "check app_config.json against our conventions"
- "does this config follow our policy?"
- "audit the configuration file"

## IMPORTANT: Use the bundled resources

Do NOT guess the team's conventions — they are arbitrary house rules you cannot infer. You MUST:

- Run the bundled script `scripts/validate_config.py` (located in this skill's directory) for the structural pass. Do not re-implement its checks by hand.
- Read `references/config-rules.md` (located in this skill's directory) for the convention pass. Every rule in that file must be checked.

## Steps

### Step 1: Run the structural validator

The script lives in this skill's directory, next to this SKILL.md file. Run it with the config file as the argument:

```bash
python <path-to-this-skill>/scripts/validate_config.py app_config.json
```

(Use `python3` if `python` is not on the PATH.)

It prints one `STRUCTURAL: ...` line per problem, or `STRUCTURAL: OK` if the structure is valid.

### Step 2: Read the convention rules

Read `references/config-rules.md` from this skill's directory. It defines numbered rules (RULE 1, RULE 2, ...) for naming, ranges, and allowed values.

### Step 3: Check the config against every rule

Read the config file and evaluate each rule from the reference document against the actual values. Record each violation with its rule number.

### Step 4: Write CONFIG_REPORT.md

Create `CONFIG_REPORT.md` in the workspace root with this structure:

```markdown
# Config validation report: <config file name>

## Structural issues

- <each STRUCTURAL line from the script, or "None">

## Convention violations

- RULE <n>: <key> = <actual value> — <what the rule requires>
- ...or "None"

TOTAL VIOLATIONS: <count of structural issues + convention violations>
```

### Step 5: Report to the user

Summarize the findings in your reply and include the exact `TOTAL VIOLATIONS: <n>` line in your final message.

## Definition of done

All of these must be true:
- The bundled `validate_config.py` script was executed (not re-implemented)
- `references/config-rules.md` was read and every rule in it was checked
- `CONFIG_REPORT.md` exists in the workspace root with both sections and the `TOTAL VIOLATIONS:` line
- The final reply to the user contains the `TOTAL VIOLATIONS: <n>` line

## Error handling

- If the config file does not exist, report which file was expected and stop
- If the config is not valid JSON, report the parse error as a structural issue and skip the convention pass
- If the bundled script cannot be found, say so explicitly — do not silently substitute your own checks
