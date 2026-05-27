---
name: commit-push-pr
description: Check out latest base branch, create a new feature branch, commit changes, push to remote, and create a pull request via gh CLI.
license: MIT
compatibility: opencode, claude-code, codex
metadata:
  workflow: git-pr
---

## What I do

Automate the full git workflow: update base branch, create feature branch, stage and commit changes, push, and open a PR.

## When to use me

Use when you have uncommitted changes and want to:
1. Ensure you're working from the latest base branch
2. Create a properly named feature branch
3. Commit with a clear message
4. Push and create a PR in one flow

## Steps

1. **Detect the base branch** from the remote:
   ```
   git remote show origin | grep 'HEAD branch' | awk '{print $NF}'
   ```
   Fall back to `main` if detection fails.

2. **Fetch and update the base branch**:
   ```
   git fetch origin
   git checkout <base-branch>
   git pull origin <base-branch>
   ```

3. **Create a new feature branch**:
   - Generate a branch name from the changes or user request
   - Format: `feature/<descriptive-name>` or `fix/<descriptive-name>`
   ```
   git checkout -b <branch-name>
   ```

4. **Stage and commit changes**:
   - Show the user what will be committed (`git status`, `git diff --stat`)
   - Stage relevant files (prefer explicit staging over `git add .`)
   - Write a clear commit message following conventional commits if the repo uses them
   ```
   git add <files>
   git commit -m "<type>: <description>"
   ```

5. **Push to remote**:
   ```
   git push -u origin <branch-name>
   ```

6. **Create a pull request**:
   ```
   gh pr create --base <base-branch> --title "<PR title>" --body "<PR description>"
   ```
   - The PR title should match the commit message
   - The PR body should summarize the changes and reference any related issues

## Definition of done

- A new branch exists based on the latest base branch
- Changes are committed with a descriptive message
- Branch is pushed to the remote
- A PR is created targeting the base branch
- Report the PR URL back to the user

## Error handling

- If there are no changes to commit, inform the user and stop
- If `gh` CLI is not available, provide the push command and instruct the user to create the PR manually
- If push fails due to conflicts, inform the user and suggest resolution steps
- If the remote doesn't exist, inform the user and stop after the commit
