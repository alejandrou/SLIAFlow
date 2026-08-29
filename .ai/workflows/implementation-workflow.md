# Implementation Workflow

Implementation changes files for the active task only.

## Steps

1. Read `AGENTS.md`.
2. Read the only task in `tasks/active/`.
3. Read required policies, workflows, ADRs, and skills declared by the task.
4. Read `docs/development/testing_strategy.md`.
5. Inspect existing project code before using external examples.
6. Fill in the task card's `## Test plan` and `## Manual verification`, then
   state both to the project owner before writing implementation code.
7. Make the smallest change that satisfies the acceptance criteria.
8. Run the checks listed under `Required checks` below.
9. Record evidence, changed files, test results, observed failures, and any
   skipped checks in the task card or completion report.

## Announce the test plan first

Before any implementation code is written, report to the project owner:

- how each acceptance criterion will be verified, automated or manual;
- which test methods will be added or changed;
- how each new or changed test will be shown to fail against the current code;
- which criteria cannot be covered automatically, and why.

This ordering is what keeps tests derived from the specification. A test
written after the implementation tends to assert whatever the implementation
already does, which passes forever and catches nothing.

## Required checks

All three must be accounted for before reporting the task as implemented.

1. Static analysis:

   ```powershell
   .\scripts\development\run-python-quality.ps1
   ```

2. Automated Slicer tests against the working tree:

   ```powershell
   .\scripts\development\run-slicer-tests.ps1
   ```

3. The manual steps in the task card, performed in a real Slicer window by the
   project owner. Codex prepares and reports them; it does not mark them done.

Report the exact command, the test names, the counts, and the exit code for
each. A check that could not be run is reported as not run, with the reason. It
is never reported as passing.

## Test evidence

A new or changed automated test is accepted only once it has been observed
failing against the code as it was before the change. Record the actual failure
message in `## Completion evidence`. Rules and rationale live in
`docs/development/testing_strategy.md`.

## Limits

- Do not modify files outside the task's allowed paths.
- Follow `.ai/policies/git-workflow.md`.
- Follow `.ai/policies/mcp-policy.md`.
- Follow `.ai/policies/dependency-policy.md`.
