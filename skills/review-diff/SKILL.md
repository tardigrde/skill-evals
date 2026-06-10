---
name: review-diff
description: Review a proposed code change (a .diff/.patch file) against the current source code and deliver a structured, severity-tagged review verdict in chat, without modifying or creating any files.
license: MIT
compatibility: opencode, claude-code, codex
metadata:
  workflow: read-analyze-report
---

## What I do

Review a proposed code change — provided as a unified diff file — against the current source code in the workspace. I read both, look for real defects, and deliver a structured review directly in my reply. I am strictly read-only: I never apply the diff, never edit source files, and never write report files.

## When to use me

Use when the user asks to review a diff, patch, or proposed change before merging. Trigger on phrases like:
- "review this diff"
- "can you review changes.diff before I merge?"
- "is this patch safe to apply?"
- "look over this proposed change"

## IMPORTANT: Read-only

Do NOT apply the diff. Do NOT modify any source file. Do NOT create any new files (no report files, no notes). The entire deliverable is the review text in your reply.

## IMPORTANT: Precision over volume

Only flag real defects. Do not pad the review with style nits, speculation, or restatements of what the diff does. Code that looks unusual but is correct and documented is not a finding. A wrong finding is worse than a missing one.

## Steps

### Step 1: Read the diff

Read the diff file the user pointed at. Identify which files and functions it touches.

### Step 2: Read the current source

Read the current version of every file the diff touches, so you understand the context the change lands in.

### Step 3: Analyze the change

Mentally apply the diff and look for defects:
- Off-by-one errors in loops, ranges, slicing
- Wrong comparison operators (`>` vs `>=`, boundary conditions vs the documented behavior)
- Logic that contradicts the function's own docstring or naming
- Broken callers, changed return types, missed edge cases (empty input, zero, None)

Check claimed behavior against actual behavior: if the docstring says "threshold or more", the code must use `>=`.

### Step 4: Deliver the review

Reply with this exact structure:

```
## Review: <diff file name>

### Findings

- <file>:<approx line>: [HIGH|MEDIUM|LOW] <what is wrong and why>
- ...or "No findings."

VERDICT: APPROVE
```

or, if there is at least one HIGH or MEDIUM finding:

```
VERDICT: REQUEST_CHANGES
```

The reply MUST end with exactly one `VERDICT:` line containing either `APPROVE` or `REQUEST_CHANGES`.

## Definition of done

All of these must be true:
- The diff file and every touched source file were read
- Each finding names the file, approximate location, severity, and the concrete defect
- No source file was modified and no new file was created
- The reply ends with exactly one `VERDICT:` line

## Error handling

- If the diff file does not exist, say which file was expected and stop
- If the diff does not apply cleanly to the current source (context mismatch), report that as a HIGH finding
- If the diff is empty, reply with "No findings." and `VERDICT: APPROVE`
