---
name: write-release-notes
description: Turn a commit history into polished, grouped release notes in RELEASE_NOTES.md. Groups changes by type, highlights breaking changes, and never invents changes that are not in the history.
license: MIT
compatibility: opencode, claude-code, codex
metadata:
  workflow: read-summarize-write
---

## What I do

Read the project's commit history and produce a `RELEASE_NOTES.md` file with the changes grouped into clear sections, written for end users rather than developers. I highlight breaking changes prominently and never mention a change that is not present in the history.

## When to use me

Use when the user asks to write release notes, draft a release announcement, or summarize changes for a release. Trigger on phrases like:

- "write release notes"
- "draft the release notes for this release"
- "turn the changelog/commits into release notes"
- "prepare the release announcement"

Do NOT trigger for questions that merely ask about the commit history (counting commits, showing the log, explaining a change).

## Steps

### Step 1: Collect the commit history

Check the sources in this order and use the first that exists:

1. A `commits.txt` file in the repository root (one commit per line).
2. `git log --oneline <last-tag>..HEAD` if the repository has tags (`git describe --tags --abbrev=0`).
3. `git log --oneline` (full history) as a fallback.

### Step 2: Classify each commit

Parse Conventional Commit prefixes when present:

- `feat:` → **Features**
- `fix:` → **Fixes**
- `perf:` → **Performance**
- A `!` after the type (e.g. `feat!:`) or a `BREAKING CHANGE` marker → **Breaking Changes** (in addition to its own section)
- `docs:`, `chore:`, `refactor:`, `test:`, `ci:` → omit from the notes unless they are user-visible

For commits without a conventional prefix, infer the category from the message; if unclear, put them under **Other Changes**.

### Step 3: Write RELEASE_NOTES.md

Create `RELEASE_NOTES.md` in the repository root with this structure:

```markdown
# Release Notes

## Breaking Changes

- ...migration guidance included...

## Features

- ...

## Fixes

- ...
```

Rules:

- **Breaking Changes comes first** when there are any, and each entry explains what users must do to migrate.
- Rewrite commit subjects into user-facing language (e.g. "fix: handle empty input in parser" → "Fixed a crash when the input file is empty").
- One bullet per change. Omit empty sections.
- **Never invent a change.** Every bullet must trace back to a specific commit in the history. Do not embellish with features, dates, version numbers, or contributors that are not in the source data.

### Step 4: Report

Tell the user the file was created and summarize the section counts (e.g. "1 breaking change, 3 features, 4 fixes").
