---
name: fix-failing-tests
description: Run the test suite, identify failing tests, diagnose the root cause in the source code, fix the bugs, and verify all tests pass.
license: MIT
compatibility: opencode, claude-code, codex
metadata:
  workflow: debug-fix-verify
---

## What I do

Run the project's test suite, identify which tests fail, read the failing test code to understand what is expected, find and fix the bugs in the source code (NOT in the tests), and re-run the tests until all pass. You execute this as an autonomous loop without asking the user for permission between steps.

## When to use me

Use when the user asks to fix failing tests, debug broken code, or make tests pass. Trigger on phrases like:
- "fix the failing tests"
- "the tests are broken, make them pass"
- "debug the test failures"
- "something's wrong with the code, the tests fail"

## IMPORTANT: Do NOT modify test files

The test files define the correct behavior. You must fix the source code to match the tests, never the other way around. If you believe a test is genuinely wrong, explain why to the user and ask before changing it.

## IMPORTANT: Autonomous execution

Execute all steps below in sequence WITHOUT asking the user for confirmation. Do NOT ask "should I run the tests?" or "should I fix this?". Just do it.

## Steps

Execute these steps in order. Repeat the loop until all tests pass.

### Step 1: Run the test suite

```bash
python -m pytest -v 2>&1
```

If `pytest` is not available, try:
```bash
python -m unittest discover -v 2>&1
```

Capture all output. Identify which tests failed and what the failure messages say.

### Step 2: Read the failing test code

For each failing test, read the test file to understand:
- What function is being tested
- What input is provided
- What output is expected

### Step 3: Read the source code

Read the source file containing the function(s) that failed. Compare the implementation against what the tests expect.

### Step 4: Fix the source code

Edit the source file to fix the bug(s). Common bug patterns:
- Off-by-one errors in ranges or indexing
- Wrong comparison operator (`>` vs `>=`, `<` vs `<=`)
- Missing or wrong case normalization (`.lower()`, `.upper()`)
- Incorrect accumulation (wrong initial value, wrong operator)
- Missing edge case handling (empty input, zero, None)
- Wrong return value or missing return

### Step 5: Re-run the tests

```bash
python -m pytest -v 2>&1
```

If tests still fail, go back to Step 2 with the new failure information. If all tests pass, report success.

## Definition of done

All of these must be true:
- The test suite was run at least once
- All test failures were diagnosed by reading both test and source code
- Source code was edited to fix the bugs (tests were NOT modified)
- The test suite passes with zero failures when re-run
- A summary of what was fixed is reported to the user

## Error handling

- If no test files are found, inform the user and stop
- If the test runner itself fails to start (import errors, missing deps), report the error and stop
- If a test appears to be testing the wrong behavior (asserting something incorrect), explain your reasoning to the user and ask before modifying the test
- If you cannot determine the root cause after 3 attempts, stop and explain what you tried
