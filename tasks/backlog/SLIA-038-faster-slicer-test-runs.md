---
id: SLIA-038
title: Run selected Slicer tests, see them live, and stop a hung run
status: backlog
branch:
priority: medium
depends_on:
required_skills: [slicer]
optional_tools: []
related_adrs: []
---

# SLIA-038 - Run selected Slicer tests, see them live, and stop a hung run

## Goal

While working on one area, a developer can run only the tests for that area in
seconds, see each test as it runs, and get back a named test, not a frozen
terminal, when a run hangs. It is also written down which of the three full
runs is needed when.

## Context

*Created on 2026-10-06, during `SLIA-036`, at the owner's request.*

What `SLIA-036` measured on this laptop:

- The suite is 145 tests. They take about 50 s headful and 29 s headless.
  - 125 of them take under 0.5 s each, 23 s together.
  - Ten network tests take about 23 s: a real stand-in, a reader thread, and
    deliberate waits (a 2 s busy main thread, the 2 s cube idle time that fixed
    a flaky test, and a refused local connection that takes about 2 s on
    Windows).
- Each check ran the whole suite three times: headless, headful, and the build
  target. That made about 3 minutes per check, plus Slicer's start-up each
  time. `.ai/workflows/implementation-workflow.md` requires only the headless
  run. The headful and build runs follow `docs/development/testing_strategy.md`,
  which does not say when they are needed.
- `scripts/development/run-slicer-tests.ps1` collects Slicer's output and
  prints it only when Slicer exits. When the suite hung on 2026-10-06 (an
  OpenIGTLinkIO `Stop()` race, fixed in `SLIA-036`), the terminal showed
  nothing for more than 10 minutes. Finding the test took a separate runner.
  Stopping Slicer by hand also left eight stand-in processes running.

Shortening the deliberate waits is not part of this card. It would save a few
seconds at the risk of bringing the flaky failures back.

## Requirements

To be confirmed at specification.

1. **Selected tests.** `run-slicer-tests.ps1 -Test <names>` runs only the
   `SLIAFlowTest` methods whose names contain any of the given comma-separated
   fragments. They run in the usual order, on either target, headless or
   headful.
   - A fragment that matches no test fails the run and names the fragment, so
     a typo can never give a green run of zero tests.
   - The start and the end of the output say `Partial run: N of M tests`,
     with the fragments, so a partial run cannot be mistaken for the suite.
   - `Reload and Test` and a run without `-Test` always run every test.
     The selection reaches `SLIAFlowTest` only from this runner.
2. **Live output.** Slicer's output is printed as it is written, so each test's
   name is shown when it starts.
3. **Timeout.** `-TimeoutSeconds` (default 900) ends a run that takes longer.
   - The runner stops Slicer and every process Slicer started, such as the
     stand-in.
   - It names the last test that started and exits nonzero.
4. **When to run which.** `docs/development/testing_strategy.md` says which
   runs are needed when. Proposal, for the owner to decide at specification:
   - While implementing: headless, selected tests as wanted.
   - Before reporting a task implemented: the full headless run, as the
     implementation workflow requires today. Add the full headful run when
     the task touches the layout, the panels or rendering.
   - Before manual verification: rebuild the module, then run the build
     target, headful.

## Out of scope

- Changing, shortening or deleting existing tests.
- Running several Slicer processes in parallel. The laptop has had 1-2 GB of
  free memory, and the connector tests use local ports.
- CTest.

## Files allowed

To be confirmed at specification. Expected:

- `scripts/development/run-slicer-tests.ps1`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py` (the selection in
  `runTest`, and its tests)
- `docs/development/testing_strategy.md`
- `.ai/workflows/implementation-workflow.md`, only if the owner changes the
  required checks in requirement 4
- `tasks/active/SLIA-038-faster-slicer-test-runs.md`

## Relevant skills and references

- Slicer skill: `slicer.testing.runUnitTest`, Slicer's `--testing` and
  `--python-code` options.
- `docs/development/testing_strategy.md`, sections "Test discovery" and
  "Running the tests".
- `tasks/active/SLIA-036-receive-app-hs-cube.md`, completion evidence: the
  per-test timings and the hang.
- `workspace\failfirst\run_selected.py` and `loop.ps1` (gitignored, from
  `SLIA-036`): a working per-test runner with timing and stack dumps, to
  borrow from.

## Implementation plan

To be defined at specification. Expected order:

1. Tests first for the selection rule in `SLIAFlowTest`: fragments, no match,
   and no selection.
2. The selection in `SLIAFlowTest.runTest`, passed from the runner, for
   example in an environment variable set only on the Slicer process.
3. Live output, the timeout, and stopping the process tree in
   `run-slicer-tests.ps1`.
4. `testing_strategy.md`, and the workflow if requirement 4 changes it.

## Acceptance criteria

To be confirmed at specification.

1. `-Test` runs exactly the matching tests in the usual order, on both targets,
   headless and headful.
2. A fragment that matches nothing fails the run, naming it. No `-Test` runs
   every test, as does `Reload and Test`.
3. Partial runs say so at the start and the end.
4. Each test's name appears while the run is in progress, not only at the end.
5. A run longer than `-TimeoutSeconds` is stopped. It names the last test
   started, exits nonzero, and leaves no Slicer or stand-in process running.
6. `testing_strategy.md` says which runs are needed when, as the owner
   decided.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| 1 Selection | `SLIAFlowTest` test of the selection rule, to be named; manual step 1 | automated, manual |
| 2 No match, no selection | `SLIAFlowTest` test of the selection rule; manual step 2 | automated, manual |
| 3 Partial runs say so | Manual step 1 | manual |
| 4 Live output | Manual step 3 | manual |
| 5 Timeout | Manual step 4 | manual |
| 6 Documentation | Review of `testing_strategy.md` | manual |

Tests to add or change, and how each one will be shown to fail first:

- The selection-rule test is run before the selection exists, and fails on
  its import or attribute.

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | `.\scripts\development\run-slicer-tests.ps1 -Test receivedCube` | Only the tests whose names contain `receivedCube` run; the output starts and ends with `Partial run: N of 145 tests`; exit 0 | |
| 2 | `.\scripts\development\run-slicer-tests.ps1 -Test noSuchTest` | The run fails, naming `noSuchTest`; no test runs; nonzero exit | |
| 3 | `.\scripts\development\run-slicer-tests.ps1 -Headful` | Test names appear one by one while Slicer runs | |
| 4 | `.\scripts\development\run-slicer-tests.ps1 -TimeoutSeconds 20` | After about 20 s the run stops, naming the test that was running; nonzero exit; Task Manager shows no Slicer and no `stratum_sim` Python process left | |

## Risks

- Streaming Slicer's output must not deadlock on a full pipe. Today's runner
  reads both streams asynchronously for that reason.
- Stopping the process tree must not stop processes that the run did not
  start.
- A selection mechanism that leaks into a normal Slicer session would silently
  shorten `Reload and Test`. The selection must come only from the runner.

## Documentation impact

- `docs/development/testing_strategy.md`: `-Test`, `-TimeoutSeconds`, live
  output, and which runs are needed when.
- `.ai/workflows/implementation-workflow.md`, only if the owner changes the
  required checks.

## Completion evidence

## Review findings

## Human approval
