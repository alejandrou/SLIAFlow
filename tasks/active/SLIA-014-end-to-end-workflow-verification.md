---
id: SLIA-014
title: End-to-end hardware-free workflow verification
status: active
branch: feature/SLIA-014-end-to-end-workflow-verification
priority: high
depends_on: SLIA-008, SLIA-013
required_skills: [slicer]
optional_tools: []
related_adrs: []
---

# SLIA-014 - End-to-end hardware-free workflow verification

## Goal

Run the complete three-box workflow on one machine with no hyperspectral camera -
acquisition stand-in, genuine UC1 CUDA pipeline, SLIAFlow receiving over
OpenIGTLink - and prove that the seam between a stand-in and a real component is
a swap, not a rewrite.

## Context

By this point every piece exists and has been verified in isolation. SLIA-010
gates simulated display behind a transient opt-in and a banner. SLIA-011 writes a
real ENVI dataset and streams `LiveView` on port 18944. SLIA-012 sends five
stand-in maps on port 18945. SLIA-013 sends `UC1_MV_CLASS` from the genuine CUDA
binary on the same port. SLIA-007 and SLIA-008 give SLIAFlow the connectors to
receive both streams.

What has never been exercised is all of them at once, and the property the whole
design exists for: stopping one producer and starting another on the same port,
with SLIAFlow never learning which one it is talking to. That property is what
makes the arrival of real hardware a configuration change rather than a project.

This task adds no production behaviour. It is a verification task, and its
deliverable is a reproducible procedure plus the recorded evidence of having run
it.

## Requirements

- Verify the full loop with the genuine UC1 runner as the map producer: the live
  pane shows the acquisition stand-in's `LiveView` frames, and the result pane
  shows the genuine pipeline's `majorityVotingMap` under the SLIA-010 headline
  `SIMULATED INPUT - REAL UC1 PIPELINE, NOT A CLINICAL RESULT`. The second line
  is the detail the runner reads from the dataset folder: `real UC1 pipeline,
  synthetic tissue phantom` for a phantom dataset, which is the default, and
  `real UC1 pipeline, synthetic input` for a folder without a phantom record.
  Record which one the session saw and which dataset produced it.
- Verify the seam by stopping the UC1 runner and starting the SLIA-012 stand-in
  on the same port, with no change to SLIAFlow's configuration, and confirm the
  banner changes to the stand-in wording: headline `SIMULATED - NOT A GENUINE UC1
  RESULT`, second line `arithmetic stand-in, not a classifier`. Both lines
  change, because the stand-in is not a classifier and the real-pipeline headline
  would be false over its output.
- Verify that substituting a genuine-marked node removes the banner immediately,
  proving the SLIA-010 origin gate still governs display after the network path
  is live.
- Verify that SLIAFlow never infers provenance from the endpoint: both producers
  use `127.0.0.1:18945`, and the displayed provenance follows the data.
- Verify clean shutdown in both directions - stopping a producer while SLIAFlow
  is connected, and closing SLIAFlow while producers run - with no hung sockets,
  no leaked connectors and no locked camera.
- Record the startup order, the achieved live frame rate, the UC1 wall-clock per
  cycle, and every observed failure and its recovery, in
  `docs/development/end_to_end_verification.md`.
- Provide a single-console launcher for the session, so that the procedure does
  not require one shell per producer and so that what the producers are doing is
  visible while the session runs. Added at the project owner's request after the
  first recorded session; `scripts/development/run-end-to-end-session.ps1` and
  its `Files allowed` entry are that request, not a widening of the task by the
  implementer.
- Provide a short quick-start for running a session, separate from the
  procedure document, so that someone testing the pipeline does not have to
  read a verification record to find the command. Requested by the project
  owner in the same review as the launcher, on the grounds that the procedure
  document was not clear about the new commands.
- Make no claim of clinical validity anywhere in the procedure or its evidence,
  and capture no screenshot that shows a result map without its banner.

## Out of scope

- Any new module behaviour, map role, device name or user-interface control.
- Fixing defects found during verification. A defect found here is written up and
  filed as its own task; only its reproduction steps belong in this card.
- The operator-facing runbook, which is SLIA-009.
- Real hyperspectral hardware.

## Files allowed

- `docs/development/end_to_end_verification.md`
- `docs/development/pipeline_test_quickstart.md`
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`
- `tools/simulators/README.md`
- `scripts/development/run-end-to-end-session.ps1`
- `tasks/{backlog,active,review,completed}/SLIA-014-end-to-end-workflow-verification.md`

## Relevant skills and references

- SLIA-010 through SLIA-013 cards and their completion evidence
- SLIA-008's connector behaviour and device-name matching
- `.ai/workflows/manual-verification-workflow.md`
- `.ai/policies/medical-data-policy.md`

## Approved dependencies

None. This task adds no code and no package.

## Implementation plan

1. Write the startup and shutdown order into
   `docs/development/end_to_end_verification.md` before running anything, so the
   procedure is reproducible rather than reconstructed afterwards.
2. Run the loop with the genuine UC1 runner and record every measurement.
3. Perform the producer swap without touching SLIAFlow and record what changes
   and what does not.
4. Perform the genuine-node substitution and the shutdown checks.
5. File any defect found as a separate backlog task and reference it here.

## Acceptance criteria

- The full loop runs with the genuine UC1 pipeline producing the displayed map,
  and the banner identifies it as a real pipeline on synthetic input.
- Swapping the map producer on port 18945 changes the banner and nothing else;
  SLIAFlow needs no reconfiguration and no restart.
- A genuine-marked node removes the banner immediately and takes precedence over
  any simulated source for the same role.
- Neither producer's identity is inferable by SLIAFlow from the endpoint; the
  displayed provenance follows the data in every case.
- Both shutdown directions leave no hung socket, leaked connector or locked
  camera.
- The recorded procedure is complete enough for a second person to repeat the
  whole run from the document alone.

## Test plan

This task's verification is manual by nature; its automated coverage is the
existing suites, re-run as a regression gate.

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| The full loop runs with the genuine pipeline | Manual step 2 | manual |
| The producer swap needs no SLIAFlow change | Manual step 3 | manual |
| A genuine node removes the banner and takes precedence | Manual step 4 | manual |
| Provenance never follows the endpoint | Manual steps 3 and 4 | manual |
| Clean shutdown in both directions | Manual steps 5 and 6 | manual |
| No regression in existing coverage | `run-slicer-tests.ps1` headless and `-Headful`, and `tools/simulators/tests/run_tests.py` | automated |

Tests to add or change, and how each one will be shown to fail first:

- No new test is added. Both existing suites are run before and after the
  verification session, and every output is recorded, so that a regression
  introduced by configuration during the session cannot pass unnoticed. The
  SLIAFlow suite is run twice: headless, which skips six view tests for want of a
  layout manager, and `-Headful`, which skips one and is therefore the run that
  covers the panes this session is about.

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Run the simulator suite and the SLIAFlow suite headless and headful, and record the output | All three pass, establishing the pre-session baseline | Pass. 110 / OK, 45 / OK (skipped=6), 45 / OK (skipped=1); all exit 0 |
| 2 | Start the acquisition stand-in, then the genuine UC1 runner, then Slicer; set the live source to the LiveView stream, set the result map to `majorityVotingMap`, connect both links and tick demo mode; then disconnect the acquisition link, measure the delivered rate with `liveview_client.py`, and reconnect it | The live pane shows streaming frames; the result pane shows the genuine class map under a red banner headed `SIMULATED INPUT - REAL UC1 PIPELINE, NOT A CLINICAL RESULT`, whose second line names the dataset the runner read; the measuring client is served only once the acquisition link is down, because a producer serves one client at a time, and the live pane returns on reconnect | Pass, scripted headful. Live pane bound to `LiveView` with the result pane background `None`; banner `SIMULATED INPUT - REAL UC1 PIPELINE, NOT A CLINICAL RESULT` over `real UC1 pipeline, synthetic tissue phantom` from the phantom dataset `sim-20260904-150404`; 8.94 fps delivered against a 10 fps target, served only with the link down; live pane returned to `displaying` on reconnect. Confirmation by eye still outstanding |
| 3 | Stop the UC1 runner, start the SLIA-012 stand-in on the same port, and change nothing in Slicer | The retained map stays on screen with its banner while no producer is listening; the result pane then recovers on its own; the banner now reads `SIMULATED - NOT A GENUINE UC1 RESULT` over `arithmetic stand-in, not a classifier`; SLIAFlow needed no reconfiguration | Pass on the substance, one row of evidence unmet. Both banner lines changed and nothing in SLIAFlow was touched. The retained map stayed on screen with its banner. The panel state during the gap was not sampled, because the driver was released only after the replacement was already listening |
| 4 | Substitute a genuine-marked node for the same role through the approved developer verification path | The banner disappears immediately and the genuine node is displayed in preference to the simulated one | Pass. Banner released, `dataOrigin = external-genuine`, source `UC1_MV_CLASS-genuine`, status with no `SIMULATED: ` prefix, with demo mode still ticked. Removing the node returned the received simulated one and its banner |
| 5 | Stop both producers while Slicer stays connected | SLIAFlow reports a disconnected or stale state without freezing, and no invalid data is presented as success | **Fail.** Both state labels kept reporting `displaying` for 120 s after both producers were killed, with nothing listening on either port, and the result status stayed `PASS: SIMULATED: ...` instead of the stale `WARN`. Nothing froze, nothing was blanked, no invalid data was shown as success, and the banner stayed on the retained image. Filed as `SLIA-016` |
| 6 | Close Slicer while both producers run, then reconnect a fresh Slicer session to both | Slicer exits cleanly; each producer prints a pyigtl traceback and `Error while sending data` as it releases the connection, keeps running, and accepts the next client without being restarted; no socket, connector or camera is left locked | Pass. Slicer exited with no surviving process; both producers printed the `WinError 10054` then `10053` tracebacks and stayed up; a fresh launcher session reconnected both links to `displaying` without either producer being restarted, and `cleanup()` left zero connectors. `netstat` showed exactly two listening sockets while the producers ran and nothing after they stopped |
| 7 | Re-run all three automated runs | All still pass, matching the step 1 baseline | Pass. 110 / OK, 45 / OK (skipped=6), 45 / OK (skipped=1); all exit 0, matching step 1 |

## Risks

The most valuable outcome of this task is a discovered defect, and the most
likely way to lose that value is to fix it in place and lose the reproduction.
Every defect is therefore written up and filed as its own task before any fix is
attempted.

A verification session that produces screenshots is the one place where an
unbannered result image could escape into a document or a slide deck. No
screenshot may show a result map without its banner.

Port 18945 carrying two different producers in one session is exactly the
condition under which an endpoint-based provenance shortcut would look correct
and be wrong. Step 3 exists specifically to catch that.

`pyigtl.OpenIGTLinkServer` is a plain `socketserver.TCPServer`: it serves one
client at a time, and its request handler only lets go of a dead connection when
a send to it fails. Two consequences are built into the procedure rather than
left to be discovered. The delivered frame rate cannot be measured while SLIAFlow
holds the acquisition connection, so it is measured with that link down. And
reconnecting after Slicer closes depends on the producer attempting a send
afterwards; both producers send on an interval, so a producer that will not
accept a second client is a finding to file, not an expected state.

## Documentation impact

- `docs/development/end_to_end_verification.md`: new. The startup and shutdown
  order, the swap procedure, the measurements, and the recorded evidence.
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`: record the verified
  hardware-free workflow and what changes when real hardware arrives.
- `tools/simulators/README.md`: link the verification procedure.

## Completion evidence

The procedure is written and the pre-session automated baseline has been
recorded. The session itself is manual verification and is still outstanding.

Written:

- `scripts/development/run-end-to-end-session.ps1` - the one-console session
  launcher: port preflight, both producers started in the fixed order with their
  output tailed side by side, a client-count status line, Slicer, and the
  producer swap and rate measurement on a keypress. Smoke-tested on 2026-09-04
  with `-MapProducer standin -NoSlicer -RunSeconds 45`: both producers came up
  and were torn down with nothing left listening on either port, a connecting
  client was reflected in the status line, and the acquisition rate line that
  the first session lost to stdout buffering reached the console.

- `docs/development/end_to_end_verification.md` - the startup and shutdown order,
  the seven session steps, and empty measurement tables to be filled in during
  the run.
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md` - what SLIA-014 verifies
  and what changes when real hardware arrives.
- `tools/simulators/README.md` - link to the procedure.

Pre-session baseline, run on 2026-09-04 on `main` as branched:

| Command | Result | Exit code |
| --- | --- | --- |
| `.\.venv\Scripts\python.exe tools\simulators\tests\run_tests.py` | `Ran 110 tests in 1.536s` / `OK` | 0 |
| `.\scripts\development\run-slicer-tests.ps1` | `Ran 45 tests in 0.737s` / `OK (skipped=6)` | 0 |
| `.\scripts\development\run-slicer-tests.ps1 -Headful` | `Ran 45 tests in 3.680s` / `OK (skipped=1)` | 0 |

### The session

Run on 2026-09-04 against `build\SLIAFlow\SlicerWithSLIAFlow.exe` headful, on
dataset `workspace\simulators\datasets\sim-20260904-150404`. Every table in
`docs/development/end_to_end_verification.md` is filled in from it.

Six of the seven steps passed. The property this card exists to test held: the
genuine UC1 runner and the SLIA-012 stand-in were swapped on `127.0.0.1:18945`
with nothing in SLIAFlow touched, and the same connector reported `real UC1
pipeline, synthetic tissue phantom` for one and `arithmetic stand-in, not a
classifier` for the other. A genuine-marked node dropped the banner immediately
with demo mode still ticked. Provenance followed the data at every stage and was
never inferable from the endpoint.

The measurements: 8.94 fps delivered over `LiveView` against a 10 fps target,
measured with the acquisition link down because a pyigtl producer serves one
client at a time; 271.857 ms of UC1 `Time simulation` per cycle; a recovered
`majorityVotingMap` of `(1, 120, 160) uint8` with classes `{2, 4}`, differing by
two pixels between two runs over the same cube because the pipeline's k-means is
not seeded.

### Step 5 failed, and that is the session's main product

With both producers killed and nothing listening on either port, both link state
labels went on reporting `displaying` through a 120-second settle window, and
the result status stayed on its `PASS` wording instead of degrading to the stale
`WARN`. The cause is `SLIAFlowWidget._linkPresent`, which tests that a connector
object exists rather than that it is connected, so every later refresh
re-asserts `displaying` over a dead socket and overwrites what
`_onLinkDisconnected` had correctly set.

That is SLIA-008's review finding 3 fixed one level too shallowly. It is filed
as `SLIA-016` with its reproduction, and it is not fixed here: this card's own
rule is that a defect found during verification is written up before any fix is
attempted, and `extensions/` is outside this card's `Files allowed` in any case.

A second finding was made during setup rather than in the session: three
processes were found listening on `127.0.0.1:18945` at once, because
`socketserver.TCPServer.allow_reuse_address` lets a second producer bind a port
another producer is actively serving on Windows. A producer swap can therefore
appear to happen without happening. That run was discarded and the session
restarted from a port verified free; the finding is filed as `SLIA-017`.

A third finding came from the project owner reporting that the pipeline "is not
working" with no further symptom. Every automated suite passed against that
worktree - Ruff on both targets, 110 simulator tests, 45 Slicer tests with the
6 headful skips - and the rig came up correctly in a `-NoSlicer` run. The cause
was a Slicer left running from an earlier session, which had been retrying both
ports since its own producers died and took both links the moment new producers
appeared.

`pyigtl.OpenIGTLinkServer` inherits `socketserver.TCPServer` rather than its
threading variant, so it serves one client at a time. Measured directly against
`pyigtl` 0.3.4 at 20 Hz: the first client received 20 of 20 polls, a second
client attached alongside it received 0 of 20 while reporting `is_connected()`
as true, and received 20 of 20 immediately after the first disconnected. So the
starved client is indistinguishable from a broken module from the panel, from
the socket table, and from the producer log.

The launcher gained a preflight for it under this card, since the launcher is
this card's own deliverable: `Assert-NoStaleClients` refuses to start when any
process is already dialling 18944 or 18945 and names it, and `Show-LinkState`
prints a red line when a port reports more than one client. Verified against the
stale process: the launcher refused, naming `PID 38676 (SlicerApp-real)`. The
producer-side diagnostic - a producer saying it has a second client it is
starving - is out of this card's scope and is filed as `SLIA-018`.

### What the session cannot attest to

It was driven from a script, with the shell and the Slicer process handing off
through marker files, so that the swap and both shutdown directions happened at
points the record can name. Everything recorded is a value read from the running
module - state labels, status text, banner actor contents, pane bindings, node
attributes - rather than an inference from the code. But a script cannot say what
an operator sees, so confirmation by eye of the panes and the banner is still
outstanding, and one row of step 3 - the panel state during the gap when no
producer was listening - was never sampled and is recorded as unmet rather than
as a pass.

No screenshot was taken during the session, so the rule that no result image may
appear without its banner was not put at risk.

## Review findings

Reserved for review.

## Human approval

Required before review and completion.
