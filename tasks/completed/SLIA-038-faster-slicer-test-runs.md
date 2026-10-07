---
id: SLIA-038
title: Run selected Slicer tests, see them live, and stop a hung run
status: completed
branch: feature/SLIA-038-faster-slicer-test-runs
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

*Specified on 2026-10-07.*

What the specification found in the code and in Slicer:

- `run-slicer-tests.ps1` ends its `--python-code` with
  `slicer.testing.runUnitTest(path, "SLIAFlow")`. That function loads every
  `TestCase` in the `SLIAFlow` module namespace, which today is only
  `SLIAFlowTest`: 147 tests on `main`. The "one test more" from an imported
  `ScriptedLoadableModuleTest`, described in `testing_strategy.md`, no longer
  happens, because `SLIAFlow.py` no longer imports that base class.
  `Reload and Test` uses `SLIAFlowTest.runTest` instead, which never passes
  through the runner's code.
- Probed on this laptop with the configured Slicer, headless: Python's
  `print` and `sys.stderr.write` reach the runner's pipes while Slicer runs,
  within the same second. A partial line arrives only together with the rest of
  its line. unittest writes `test_x (...) ... ` when a test starts and `ok` plus
  the newline when it ends, so its own output names a test only once that test
  has finished. A hung test would stay invisible.

## Requirements

1. **Selected tests.** `run-slicer-tests.ps1 -Test <fragments>` runs only the
   `SLIAFlowTest` methods whose names contain at least one fragment
   (case-sensitive substring). `-Test` takes one or more strings, each of which
   may hold comma-separated fragments, so `-Test a,b` and `-Test "a,b"` are the
   same.
   - The selected tests run in unittest's usual order, the order a full run
     uses. The selection works on both targets, headless and headful.
   - A fragment that matches no test fails the run before any test runs and
     names that fragment. An empty selection, such as `-Test ","`, is refused.
   - A partial run prints `Partial run: N of M SLIAFlowTest tests matching
     <fragments>` before the first test and again as the last line of the
     runner's output. M is the number of `SLIAFlowTest` methods.
   - The fragments reach Slicer only inside the `--python-code` text that the
     runner builds. No environment variable, file or setting carries them, so
     `Reload and Test` and a normal session cannot see a selection.
     `SLIAFlowTest.runTest` is not changed.
   - Without `-Test` the runner loads the module's tests as
     `slicer.testing.runUnitTest` does today, and the count stays every
     `SLIAFlowTest` method (152 with this card's five tests).
2. **Live output.** The runner prints Slicer's standard output and standard
   error line by line as they arrive, with standard error in yellow as today.
   Both full and partial runs print one complete line, `Started: <test id>`,
   before each test body runs.
3. **Timeout.** `-TimeoutSeconds` (default 900, minimum 1) bounds the wait,
   including the wait for Slicer to exit after its output has closed. When it
   expires, the runner:
   - prints `TIMEOUT after <s> s. Last test started: <test id>`, or `no test
     had started`;
   - stops the Slicer process it started and every process descended from it
     (the launcher, `SlicerApp-real` and the stand-in), and only those;
   - reports any of them still running afterwards;
   - exits with code 1.

   The same process-tree stop runs however the run ends: on Ctrl+C, and after
   Slicer exits, so that no process Slicer left running outlives the run.
4. **When to run which.** The owner chose the card's proposal on 2026-10-07.
   `testing_strategy.md` states it, and `implementation-workflow.md` points to
   it:
   - While implementing: headless, with tests selected as wanted.
   - Before reporting a task implemented: the full headless run. Add the full
     headful run when the task touches the layout, the panels or rendering.
   - Before manual verification: rebuild the module with
     `build-sliaflow.ps1`, then run `-Target Build -Headful`.

## Out of scope

- Changing, shortening or deleting existing tests.
- Changing `SLIAFlowTest.runTest` or what `Reload and Test` runs.
- Running several Slicer processes in parallel. The laptop has had 1-2 GB of
  free memory, and the connector tests use local ports.
- CTest.
- Per-test timing or stack dumps (the `workspace\failfirst` runner keeps those).

## Files allowed

- `scripts/development/run-slicer-tests.ps1`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`: the
  command-line selection and live result at module level, and their tests
- `docs/development/testing_strategy.md`
- `.ai/workflows/implementation-workflow.md`: one pointer to the new rule
  (requirement 4)
- `tasks/active/SLIA-038-faster-slicer-test-runs.md`, moved from
  `tasks/backlog/`

`SLIAFlowTest.py` is already deployed by the module `CMakeLists.txt`, so the
build needs no change.

## Relevant skills and references

- Slicer skill: `slicer.testing.runUnitTest`
  (`apps\SR\Slicer-build\bin\Python\slicer\testing.py`, read for this card),
  Slicer's `--testing` and `--python-code` options.
- `docs/development/testing_strategy.md`, sections "Test discovery" and
  "Running the tests".
- `tasks/completed/SLIA-036-receive-app-hs-cube.md`, completion evidence: the
  per-test timings and the hang.
- `workspace\failfirst\run_selected.py`, `run.ps1` and `loop.ps1` (gitignored,
  from `SLIA-036`): a per-test runner, borrowed from for the selection idea.

## Implementation plan

1. Write the tests below in `SLIAFlowTest.py` and run the full headless suite.
   Each new test is expected to raise `NameError` because the code under test
   does not exist yet.
2. Add module-level code to `SLIAFlowTest.py`. The test loader does not
   collect it, because none of it is a `TestCase`:
   - `selectTestNames(testNames, fragments)`: the matching names in the given
     order. Raises `ValueError` naming every fragment that matches nothing, and
     refuses an empty fragment list or an empty fragment.
   - `commandLineSuite(module, testCaseClass, fragments)`: with no fragments,
     `unittest.TestLoader().loadTestsFromModule(module)`, as
     `runUnitTest` loads it. With fragments, the selected `testCaseClass`
     methods and the `Partial run` text.
   - `LiveTextTestResult(unittest.TextTestResult)`: writes and flushes
     `Started: <test id>` as a complete line in `startTest`.
   - `runCommandLineTests(module, testCaseClass, fragments)`: prints the
     partial-run line, runs the suite with `TextTestRunner(verbosity=2,
     resultclass=LiveTextTestResult)`, prints the partial-run line again,
     and returns whether the run succeeded.
3. `run-slicer-tests.ps1`:
   - `-Test` and `-TimeoutSeconds` parameters.
   - Its `--python-code` calls `runCommandLineTests` instead of
     `slicer.testing.runUnitTest`, after the existing module-path guard. The
     fragments are embedded as a JSON literal.
   - The output is read line by line with `ReadLineAsync` on both streams, so
     neither pipe can fill, and the runner remembers the last `Started:` and
     `Partial run:` lines.
   - The timeout, and the process-tree stop in a `finally` block.
   - The partial-run line is printed again after Slicer exits.
4. Update `testing_strategy.md` and `implementation-workflow.md`.
5. Run static analysis, the full headless, headful and Build runs, and the
   manual steps that can run without the owner. Record the results.

## Acceptance criteria

1. `-Test` runs exactly the `SLIAFlowTest` methods that contain a fragment, in
   the order of a full run, on both targets, headless and headful.
2. A fragment that matches nothing fails the run, naming it, before any test
   runs. Without `-Test` the runner runs every test, 152 with this card's five.
   `Reload and Test` still runs every test.
3. A partial run says `Partial run: N of M SLIAFlowTest tests matching ...`
   before its first test and as the last line of the runner's output.
4. Each test's `Started:` line appears while the run is in progress, before the
   test's body runs.
5. A run longer than `-TimeoutSeconds` is stopped. The runner names the last
   test that started, exits nonzero, and leaves no Slicer or stand-in process
   that it started.
6. `testing_strategy.md` documents `-Test`, `-TimeoutSeconds`, live output and
   which runs are needed when, as the owner decided. `implementation-workflow.md`
   points to that rule.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| 1 Selection and order | `test_commandLineSelectionKeepsMatchingTestsInOrder`, `test_commandLineSuiteSelectsOnlyFromTheTestClass`; manual steps 1, 5 | automated, manual |
| 2 No match; no selection; Reload and Test | `test_commandLineSelectionNamesFragmentsMatchingNothing`, `test_commandLineSuiteWithoutSelectionLoadsTheWholeModule`, existing `test_reloadAndTestRunsPastSkippedTests`; manual steps 2, 6, 7 | automated, manual |
| 3 Partial runs say so | `test_commandLineSuiteSelectsOnlyFromTheTestClass` (the text); manual step 1 (its place in the output) | automated, manual |
| 4 Live output | `test_commandLineRunNamesEachTestBeforeItRuns`; manual step 3 | automated, manual |
| 5 Timeout | Manual step 4 | manual |
| 6 Documentation | Review of `testing_strategy.md` and `implementation-workflow.md` | manual |

Tests to add, and how each one will be shown to fail first:

- `test_commandLineSelectionKeepsMatchingTestsInOrder`: fragments select
  names in input order, case-sensitively, and a name matched by two fragments
  appears once.
- `test_commandLineSelectionNamesFragmentsMatchingNothing`: the `ValueError`
  names both unmatched fragments, not the matched one. An empty fragment list
  and an empty fragment are refused.
- `test_commandLineSuiteWithoutSelectionLoadsTheWholeModule`: on a probe
  module with two `TestCase` classes, no fragments give every test the loader
  finds in the module, and no partial-run text.
- `test_commandLineSuiteSelectsOnlyFromTheTestClass`: fragments select only
  from the named class, and the text is `Partial run: 1 of 2 ProbeTest tests
  matching Cube`, named after the class it selects from.
- `test_commandLineRunNamesEachTestBeforeItRuns`: a probe test reads the
  output stream from inside its own body. The stream already ends with the
  complete line `Started: <its id>`.

All five are first run before the code under test exists and fail with
`NameError`. To show that the last test checks the start line and not only
that the class exists, it is also run once with `LiveTextTestResult` replaced
by plain `unittest.TextTestResult`. It must fail on its assertion there.

Criterion 5 cannot be automated inside `SLIAFlowTest`, because the test would
have to stop the Slicer it runs in. Criterion 6 is a document review.

## Manual verification

Run from the repository root in PowerShell. Steps 1-4 use the default Source
target. Step 5 needs a fresh build.

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | `.\scripts\development\run-slicer-tests.ps1 -Test receivedCube` | Only tests whose names contain `receivedCube` run, in alphabetical order. A `Partial run: N of 152 SLIAFlowTest tests matching receivedCube` line comes before the first test and is the last line of the output. Exit 0 (`$LASTEXITCODE`) | |
| 2 | `.\scripts\development\run-slicer-tests.ps1 -Test noSuchTest,receivedCube` | The run fails, naming `noSuchTest` and not `receivedCube`. No `Started:` line appears. Nonzero exit | |
| 3 | `.\scripts\development\run-slicer-tests.ps1 -Headful` | `Started:` lines appear one by one while Slicer runs, not all at once at the end. 152 tests, exit 0 | |
| 4 | `.\scripts\development\run-slicer-tests.ps1 -TimeoutSeconds 20` | After about 20 s the runner prints `TIMEOUT after 20 s. Last test started: ...`, naming a test, and exits 1. Task Manager shows no Slicer, `SlicerApp-real` or stand-in Python process left | |
| 5 | `.\scripts\development\build-sliaflow.ps1`, then `.\scripts\development\run-slicer-tests.ps1 -Target Build -Headful -Test receivedCube,Connections` | The same kind of partial run as step 1, from `build\SLIAFlow`, exit 0 | |
| 6 | `.\scripts\development\run-slicer-tests.ps1` | `Ran 152 tests`, exit 0, no `Partial run` line | |
| 7 | In Slicer, SLIAFlow module, Developer Mode, `Reload and Test` | The Python console shows `Ran 152 tests` and the run passes | |

## Risks

- Streaming must not deadlock on a full pipe. Both streams are always being
  read; neither waits for the other.
- The process-tree stop must not stop processes the run did not start. Every
  2 seconds the runner walks child processes down from its own Slicer process
  and holds each one open, so Windows cannot give that ID to another process
  while the run refers to it. A process counts as a child only if it was
  created no earlier than its listed parent. Its start time is checked again
  when it is opened.
- A process whose parent exits before the next 2-second scan has seen that
  parent cannot be found, and is not stopped.
- A selection that leaks into a normal Slicer session would silently shorten
  `Reload and Test`. The fragments exist only in the runner's
  `--python-code`, and `runTest` is not changed.
- Replacing `runUnitTest` in the full run could change what the full run
  counts. The no-selection path loads from the module as `runUnitTest` does,
  a test guards it, and manual step 6 checks the 152.

## Documentation impact

- `docs/development/testing_strategy.md`: `-Test`, `-TimeoutSeconds`, live
  output, and which runs are needed when.
- `.ai/workflows/implementation-workflow.md`: a pointer under Required checks.

## Completion evidence

*Implementation and automated testing, 2026-10-07, branch
`feature/SLIA-038-faster-slicer-test-runs`. Manual verification, review and
approval are not done.*

### Owner decision

Requirement 4: the card's proposal, chosen on 2026-10-07, including the
pointer in `implementation-workflow.md`.

### Specification findings

- Slicer streams Python's `print` and `sys.stderr` through the runner's pipes
  while it runs (probed headless with the configured Slicer). A partial line
  arrives only with the rest of its line.
- A Python exception in `--testing --python-code` makes Slicer print the
  traceback and exit 1. The no-match failure relies on this.
- `main` had 147 tests, not 145, and no extra base-class test: `SLIAFlow.py`
  no longer imports `ScriptedLoadableModuleTest`. `testing_strategy.md` said
  otherwise and is corrected. With this card's five tests, a full run and
  `Reload and Test` both count 152.

### Fail-first

Full headless run with the five tests written and the code under test absent
(the runner as it was on `main`): `Ran 152 tests`, `FAILED (errors=5,
skipped=19)`, exit 1. Only the five new tests failed, each with `NameError`:

- `test_commandLineRunNamesEachTestBeforeItRuns`: `NameError: name
  'LiveTextTestResult' is not defined`
- `test_commandLineSelectionKeepsMatchingTestsInOrder` and
  `test_commandLineSelectionNamesFragmentsMatchingNothing`: `NameError: name
  'selectTestNames' is not defined`
- `test_commandLineSuiteSelectsOnlyFromTheTestClass` and
  `test_commandLineSuiteWithoutSelectionLoadsTheWholeModule`: `NameError: name
  'commandLineSuite' is not defined`

With the code in place and `LiveTextTestResult` replaced by
`unittest.TextTestResult` (in a Slicer session, the source not changed),
`test_commandLineRunNamesEachTestBeforeItRuns` fails on its assertion:
`AssertionError: 'Started: ...StartProbe.test_probe\n' not found in
'test_probe (...StartProbe.test_probe) ... '`.

### Checks

| Command | Result | Exit |
| --- | --- | --- |
| `.\scripts\development\run-python-quality.ps1` | Ruff 0.15.21, all checks passed on both targets | 0 |
| `.\scripts\development\run-slicer-tests.ps1 -Test commandLine` | `Partial run: 5 of 152 SLIAFlowTest tests matching commandLine` before the tests and as the last line; `Ran 5 tests`, OK | 0 |
| `.\scripts\development\run-slicer-tests.ps1 -Test noSuchTest,receivedCube` (manual step 2) | `ValueError: These test-name fragments match no test: 'noSuchTest'.`; no `Started:` line | 1 |
| `.\scripts\development\run-slicer-tests.ps1 -Test ","` | Refused: `-Test was given without a test-name fragment.` | 1 |
| `.\scripts\development\run-slicer-tests.ps1 -TimeoutSeconds 20` (manual step 4) | `TIMEOUT after 20 s. Last test started: ...test_hsCubeConnectorIsListedButNeverStarted`; `Stopped Slicer (25232) and the 5 processes it started: SlicerApp-real.exe, conhost.exe, python.exe, conhost.exe, python.exe`; no Slicer or Python process listed before the run, and none afterwards | 1 |
| `.\scripts\development\run-slicer-tests.ps1` (manual step 6) | `Ran 152 tests in 35.2s`, `OK (skipped=19)`, 152 `Started:` lines, no `Partial run` line | 0 |
| `.\scripts\development\run-slicer-tests.ps1 -Headful` | `Ran 152 tests in 62.9s`, `OK (skipped=1)`: `test_headlessPresentationFallback`, headless-only as in `SLIA-036` | 0 |
| `.\scripts\development\build-sliaflow.ps1` | Verify: `ok SLIAFlowLib\SLIAFlowTest.py` | 0 |
| `.\scripts\development\run-slicer-tests.ps1 -Target Build -Headful -Test receivedCube,Connections` (manual step 5) | Loaded from `build\SLIAFlow`; `Partial run: 17 of 152 ... matching receivedCube, Connections`; the `Started:` lines arrived one by one, the first at 5.0 s and the last at 17.4 s; `Ran 17 tests`; the partial line is the last line | 0 |
| `.\scripts\development\run-slicer-tests.ps1 -Target Build -Headful` | `Ran 152 tests in 62.3s`, `OK (skipped=1)` | 0 |

The agent ran manual steps 2, 4, 5 and 6 from the terminal as above. The
project owner still has to confirm them. Steps 1, 3 and 7 have not been run:
step 1's fragment ran only as part of step 5, step 3 needs a person watching
the terminal, and step 7 needs Slicer's window.

## Review findings

*Branch review, 2026-10-07, while the task is active. No lifecycle transition
or human verification is recorded by this review.*

In priority order:

1. **High: process-tree cleanup can select unrelated processes.**
   `Stop-ProcessTree` compares every descendant's creation time only with the
   root's time, rather than its immediate parent's time. If a child reuses an
   unrelated process's old PID, surviving children of that old process can
   pass the filter and be killed. An in-memory probe of the unchanged function
   with a synthetic CIM snapshot selected an unrelated process created before
   its supposed parent but after the root. Termination also uses bare PIDs
   without rechecking process identity. Check parent/child identities and
   creation times before selecting and stopping a process.
2. **High: descendants survive an early launcher exit.** The `finally` block
   calls cleanup only when the root has not exited. A probe of the unchanged
   runner block launched a Python parent that spawned a sleeping child and
   exited 7; the runner reported exit 7 and left that child running. The probe
   then stopped its own child. Cleanup must cover descendants even when the
   root has already exited, including descendants whose intermediate parents
   have exited.
3. **Medium: closing both output pipes bypasses the timeout.** Once both
   readers reach EOF, the runner calls unbounded `WaitForExit()`. A probe of
   the unchanged runner block set a one-second timeout and launched a process
   that closed both pipes and slept three seconds. It returned after 3.08 s
   with exit 0 and `timedOut = false`. Keep checking the deadline until the
   process has exited, independently of pipe state.

Validation run by the reviewing agent:

- `run-python-quality.ps1`: both Ruff targets passed, exit 0.
- `run-slicer-tests.ps1 -Test commandLine`: five tests passed, exit 0.
- `run-slicer-tests.ps1`: 152 tests in 29.210 s, OK (skipped=19), exit 0.
- `run-slicer-tests.ps1 -Test noSuchTest,receivedCube`: named only the unmatched
  fragment, no test started, expected exit 1.
- `run-slicer-tests.ps1 -TimeoutSeconds 20`: named the last started test and
  stopped the launcher plus five descendants, expected exit 1. No Slicer or
  Python process was present before or after this run.
- An isolated PowerShell runspace cancellation probe reached cleanup and
  stopped its process. This is not human verification of terminal Ctrl+C.
- `git diff --check`: exit 0. Headful, Build and Reload and Test were not
  rerun during this review; earlier evidence remains above.

The first three findings need fixes and regression checks before this review
can recommend approval. The review probes changed no implementation files.

### Fixes for the review findings

*2026-10-07, same branch. Only `run-slicer-tests.ps1` changed, plus the timeout
section of `testing_strategy.md` and this card.*

1. `Update-ProcessTree` runs every 2 seconds during the run and once more
   before the stop. It accepts a process only if its creation time is no
   earlier than that of its listed parent, which is already in the tree. It
   opens the process and checks that the start time matches the listing to
   within 1 ms. It holds each process open until the run ends, so no tree
   process ID can be reused while the run refers to it. Each process is stopped
   through that held handle, not by bare ID.
2. The `finally` block always calls `Stop-ProcessTree`. Slicer's own handle
   keeps its ID reserved after it exits, so its orphaned children are still
   found. Holding every scanned process does the same for an intermediate
   parent that exits later. Once Slicer has exited, output is read for 2 more
   seconds at most; a pipe still open then is held by a leftover process,
   which the stop ends.
3. The loop checks the deadline until Slicer has exited, with or without open
   pipes. The unbounded `WaitForExit()` is gone.

Checks, run by the implementing agent. The probes live in the session
scratchpad, not in the repository:

| Check | Result | Exit |
| --- | --- | --- |
| Mocked snapshot of real processes loaded into `Update-ProcessTree`: an older process listing a newer tree member as its parent; a real descendant two levels down; a listed ID whose start time no longer matches; a child listed before its parent | All 4 pass. With the parent-time check removed, the first fails (`got [member, unrelated]`). With the start-time check removed, the third fails | 0 |
| Copied runner, stand-in Slicer exits 7 and leaves a child holding the pipes | Exit 7 after 3 s; `Stopped 1 processes this run started`; child gone | 7 |
| Same, child on its own pipes (the review's case) | Exit 7; child stopped and gone | 7 |
| Same, stand-in closes both pipes then sleeps 30 s, `-TimeoutSeconds 1` | `TIMEOUT after 1 s`; returned after 1.8 s; stand-in stopped | 1 |
| `.\scripts\development\run-slicer-tests.ps1` | `Ran 152 tests in 41.0s`, `OK (skipped=19)`, nothing stopped; a second run 41.0 s | 0 |
| `.\scripts\development\run-slicer-tests.ps1 -TimeoutSeconds 20` | `TIMEOUT after 20 s. Last test started: ...test_hsCubeConnectorIsListedButNeverStarted`; `Stopped 6 processes this run started: Slicer.exe, SlicerApp-real.exe, conhost.exe, python.exe, conhost.exe, python.exe`; none left | 1 |
| `.\scripts\development\run-slicer-tests.ps1 -Target Build -Headful` | `Ran 152 tests`, `OK (skipped=1)`, nothing left | 0 |
| Scan cost: one headless and one Build headful run with the scan interval set to 1000 s, restored afterwards | Headless 40.4 s against 41.0 s; Build headful 80.7 s without the scan against 74.8 s with it, within run-to-run variance (104.8 s in another run with the scan) | 0 |
| `git diff --check` | Clean | 0 |

The fail-first evidence for findings 2 and 3 is the review's own probes of the
unchanged runner above. The agent did not rerun them against the old code.
Ctrl+C in a real terminal has not been tried; it reaches the same `finally`
block.

### Follow-up branch review

*2026-10-07, after the fixes above. The task remains active. Only this review
record was edited by the reviewing agent.*

The original three reproduction cases now pass against the current runner:

- An in-memory snapshot using real process handles rejects an older unrelated
  process and a listing whose start time differs from the opened process. It
  also discovers a descendant listed before its parent and keeps the tracked
  handles open. All four checks passed; command exit 0. Holding an open handle
  preserves the Windows process identity until the handle is closed, as
  documented in Microsoft's
  [PROCESS_INFORMATION reference](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/ns-processthreadsapi-process_information).
- The unchanged runner block with a Python parent exiting 7 and leaving a
  sleeping child returns 7 and stops the child, in 0.30 s.
- The unchanged runner block with a process closing its pipes and sleeping
  triggers a one-second timeout and stops the process, returning 1 in 1.23 s.
- `run-slicer-tests.ps1 -Test commandLine`: five tests passed, exit 0.

**Remaining medium-priority finding: continuous output delays the timeout and
the output-drain limit.** The inner loop in `run-slicer-tests.ps1` drains every
completed line from one reader before returning to the deadline, exit-state
and process-scan checks. It has no batch limit or elapsed-time check. A busy
stream can therefore postpone these checks and servicing the other stream.

Two isolated probes used the unchanged runner block with real Python
processes. To model a slow terminal without flooding the review output, only
`Write-Host` was replaced: noise lines called `Thread.Sleep(1)` and other
messages were retained. Sleep scheduling can exceed the requested millisecond.

- With a one-second timeout and continuous noise, the runner printed 415
  lines before returning with the expected timeout exit 1, after 5.29 s.
- With a parent exiting 7 and a noisy child explicitly inheriting its output
  handles, the runner read 315 lines and returned 7 after 4.11 s, exceeding
  the two-second drain interval. The child was then stopped.

Limit the number of lines processed per reader per iteration, or check the
deadline and drain interval inside the read loop. Add a probe covering both
busy streams so output cannot postpone cleanup or starve stderr.

The documented scan-window limitation remains. Real-terminal Ctrl+C and
human manual verification remain unverified. No full-suite, Build or Ruff
rerun was needed for this follow-up, since implementation files were not
changed by the reviewing agent and the implementing agent's results are
recorded above. Approval is not recommended until the remaining output-loop
finding is addressed.

### Agent verification and robustness probes at the owner's request

*2026-10-07, `feature/SLIA-038-faster-slicer-test-runs`. The owner requested
the manual checks and attempts to break them. No implementation files were
changed. The task remains active; human manual verification and approval are
not recorded. The manual table's Result cells remain empty as required by
`manual-verification-workflow.md`.*

The extension was rebuilt first with `build-sliaflow.ps1`: exit 0, all 16
deployed files matched the source. Then `run-slicer-tests.ps1 -Target Build
-Headful` passed all 152 tests in 52.685 s, exit 0, with the one expected
headless-only skip. All Slicer test processes were run sequentially.

Agent observations corresponding to the manual steps:

| Step | Observed result | Exit |
| --- | --- | --- |
| 1 | Source `-Test receivedCube`: exactly 16 matching tests, in unittest's ordinal name order; partial banner before the first Started line and as the final line; 16 tests in 8.109 s, one skip | 0 |
| 2 | Source `-Test noSuchTest,receivedCube`: ValueError named only `noSuchTest`; zero Started lines | 1, expected |
| 3 | Source `-Headful`: 152 tests in 53.947 s, one expected skip; 152 Started lines received while the process ran, first at 3.50 s and last at 57.15 s; runner returned at 58.73 s | 0 |
| 4 | `-TimeoutSeconds 20`: last started test was `test_publishingErrorEndsCaptureAndKeepsPreviousResult`; returned at 20.86 s, stopped its three remaining launcher/app/console processes; no Slicer or Python process left | 1, expected |
| 5 | Build `-Headful -Test receivedCube,Connections`: correct build module path, exactly 17 tests in ordinal order; banners before the first test and as the final line; 17 tests in 11.739 s | 0 |
| 6 | Full Source headless: 152 tests in 29.409 s, 19 expected skips, 152 Started lines, no partial banner | 0 |
| 7 | Launched the rebuilt Slicer in a real window with temporary settings, opened SLIAFlow with Developer Mode and the Python console visible, and triggered its actual Reload and Test QAction. The unittest result recorded 152 tests, zero failures/errors, one expected skip; output reported 58.432 s. Before/after screenshots were inspected. This is programmatic UI execution, not human confirmation of the console output or usability | Interactive session remains open |

Normal runner invocations left no Slicer or Python processes behind. The
interactive Slicer launched for step 7 was deliberately left open for the
owner, separately from those runner invocations. No MCP was used, and no
local configuration or persistent Slicer preferences were edited. The
interactive launch used `--disable-settings --ignore-slicerrc --no-splash
--disable-cli-modules --python-script <temporary verification script>`.

Additional input checks:

- `-Test ","`: rejected before launch, expected exit 1.
- `-Test RECEIVEDCUBE`: case-sensitive rejection, zero tests, expected exit 1.
- `-Test noSuchTest,otherNoSuchTest,receivedCube`: both unmatched fragments
  named, matched fragment excluded from the error, zero tests, expected exit 1.
- `-Test receivedCube,receivedCube,Cube`: exactly 43 unique matching methods,
  in unittest's ordinal order; 43 tests passed, six skips, exit 0; banners
  correctly placed. Overlapping and duplicate fragments did not duplicate tests.
- A fragment containing a double quote and a trailing backslash reached
  Python intact and was rejected by name, zero tests, expected exit 1.
- `-TimeoutSeconds 1`: no test had started; stopped its launcher/app/console
  processes, returned in 1.78 s, expected exit 1, no leftovers.
- `-TimeoutSeconds 0`: parameter validation refused it, expected exit 1.

Process probes extracted the current runner's functions and process loop
unchanged into a temporary harness and used real, nonmedical Python
processes instead of Slicer. A separate unrelated sleeping process survived
every stress probe and was stopped by the harness afterwards.

- Closing both pipes before sleeping: one-second timeout, process stopped,
  loop returned in 1.318 s, expected exit 1.
- Parent exiting 7 while a child held its pipes: returned 7 and stopped the
  child, no leftovers, loop elapsed 2.832 s.
- A real Windows console received an injected Ctrl+C control event while
  the extracted loop ran a sleeping parent and child. The console process
  returned within 0.343 s after the signal and the held child handle confirmed
  termination. This verifies automated console interruption, not a person
  pressing Ctrl+C in their terminal. The tool's interactive PTY launch was
  unavailable (`CreateProcessW`: access denied), so a hidden dedicated Windows
  console was used instead.

**Failures reproduced:**

1. **Busy output delays timeout checks and stderr.** With both streams busy
   and a harness-only `Write-Host` replacement sleeping 1 ms per noise line
   to model a slow terminal, a one-second timeout returned from the loop in
   4.902 s. A Started marker written to stderr before the flood was not
   serviced until 4.684 s. Another run returned in 3.743 s. This reproduces
   the existing follow-up review finding: the unbounded per-reader drain
   postpones deadline checks and servicing the other stream. Exit 1 was
   correct and cleanup succeeded, but the deadline was not respected.
2. **Busy orphan output delays cleanup.** A parent exited 7 after 0.2 s;
   its child emitted 400 lines and held the pipes open. With the same slow
   terminal model, the loop returned in 5.563 s, beyond the intended
   two-second post-exit drain period. The child was eventually stopped.
   This is another manifestation of failure 1.
3. **A short-lived intermediate parent lets its child escape cleanup.**
   A root waited 0.5 s, started an intermediate process that spawned a
   sleeping grandchild, and that intermediate exited before the next scan.
   At the three-second timeout the root was stopped, but the grandchild
   remained alive and was not named as a survivor. The probe harness
   explicitly stopped that grandchild afterwards. This reproduces the
   scan-window limitation already documented under Risks and conflicts
   with the unconditional requirement to stop every descendant.

Raw logs, timestamps, JSON results, screenshots and reproducible probe
scripts are session artifacts under
`%TEMP%\SLIA038-verification-20261007\`, outside the repository. No imagery
was copied into the repository. `git diff --check` passed, exit 0. Ruff was
not rerun because no implementation files changed; earlier Ruff evidence
still applies. The documented testing rules and workflow pointer were read
and match requirement 4.

Normal functionality passed the agent checks, including Reload and Test.
Approval is not recommended until the busy-output defect is fixed and the
descendant-cleanup limitation is resolved or its requirement is explicitly
revised by the owner. Human visual/manual confirmation remains pending.

## Human approval
