---
name: commit-push-pr
description: Check out latest base branch, create a new feature branch, commit changes, push to remote, and create a pull request via gh CLI.
license: MIT
compatibility: opencode, claude-code, codex
metadata:
  workflow: git-pr
---

## What I do

Automate the full git workflow: update base branch, create feature branch, stage and commit changes, push, and open a PR. You execute ALL steps autonomously without asking the user for confirmation.

## When to use me

Use when the user asks to commit, push, create a PR, or get changes into a branch. Trigger on phrases like:
- "commit and push my changes"
- "get this into a PR"
- "push this up and make a PR"
- "create a pull request"

## IMPORTANT: Autonomous execution

You MUST execute all steps below in sequence WITHOUT asking the user for confirmation. Do NOT ask "would you like me to proceed?" or "should I stage these files?". Just do it.

## IMPORTANT: What counts as changes

- **Changes include**: any modified tracked files AND any untracked files (new files not yet in git)
- **Changes EXCLUDE**: agent/skill configuration directories (`.opencode/`, `.claude/`, `.codex/`)
- When staging files, stage ALL changed files EXCEPT those in agent config directories
- If the user mentions specific files, prioritize those but also include other changes

## Steps

Execute these steps in order. Do not stop or ask for confirmation between steps.

### Step 1: Detect the base branch

```bash
git remote show origin | grep 'HEAD branch' | awk '{print $NF}'
```
Fall back to `main` if detection fails or no remote exists.

### Step 2: Fetch and update the base branch

```bash
git fetch origin
git checkout <base-branch>
git pull origin <base-branch>
```

### Step 3: Identify changes to commit

Run `git status` to find all modified and untracked files. Filter out agent config directories:
- Ignore anything under `.opencode/`
- Ignore anything under `.claude/`
- Ignore anything under `.codex/`

If after filtering there are NO changes (no modified files, no untracked files outside agent config dirs), then inform the user "No changes to commit" and STOP. Do not proceed.

### Step 4: Create a new feature branch

Generate a descriptive branch name from the changes or user request:
- Use `feature/<descriptive-name>` for new features
- Use `fix/<descriptive-name>` for bug fixes

```bash
git checkout -b <branch-name>
```

### Step 5: Stage and commit changes

Stage all changed files (modified + untracked), excluding agent config directories:

```bash
git add <files>
git commit -m "<type>: <description>"
```

- Use conventional commit format: `feat:`, `fix:`, `chore:`, etc.
- Write a clear, descriptive commit message based on the changes

### Step 6: Push to remote

```bash
git push -u origin <branch-name>
```

### Step 7: Create a pull request

```bash
gh pr create --base <base-branch> --title "<PR title>" --body "<PR description>"
```

- The PR title should match the commit message
- The PR body should summarize the changes
- Report the PR URL back to the user

## Definition of done

All of these must be true:
- A new feature branch was created based on the latest base branch
- All changes (excluding agent config) are committed with a descriptive message
- Branch is pushed to the remote with `git push`
- A PR is created targeting the base branch via `gh pr create`
- The PR URL is reported back to the user

## Error handling

- If there are no changes to commit (after excluding agent config dirs), inform the user and stop
- If `gh` CLI is not available, provide the push command and instruct the user to create the PR manually
- If push fails due to conflicts, inform the user and suggest resolution steps
- If the remote doesn't exist, inform the user and stop after the commit
