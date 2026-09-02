---
id: SLIA-014
title: End-to-end hardware-free workflow verification
status: backlog
branch:
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
  shows the genuine pipeline's `majorityVotingMap` under the SLIA-010 banner
  reading `real UC1 pipeline, synthetic input`.
- Verify the seam by stopping the UC1 runner and starting the SLIA-012 stand-in
  on the same port, with no change to SLIAFlow's configuration, and confirm the
  banner's second line changes to `arithmetic stand-in, not a classifier`.
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
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`
- `tools/simulators/README.md`
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
- Swapping the map producer on port 18945 changes only the banner's second line;
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
| No regression in existing coverage | `run-slicer-tests.ps1` and `tools/simulators/tests/run_tests.py` | automated |

Tests to add or change, and how each one will be shown to fail first:

- No new test is added. Both existing suites are run before and after the
  verification session, and both outputs are recorded, so that a regression
  introduced by configuration during the session cannot pass unnoticed.

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Run both automated suites and record the output | Both pass, establishing the pre-session baseline | |
| 2 | Start the acquisition stand-in, then the genuine UC1 runner, then Slicer; connect both connectors and tick demo mode | The live pane shows streaming frames; the result pane shows the genuine class map under a red banner whose second line reads `real UC1 pipeline, synthetic input` | |
| 3 | Stop the UC1 runner, start the SLIA-012 stand-in on the same port, and change nothing in Slicer | The result pane recovers on its own; the banner's second line now reads `arithmetic stand-in, not a classifier`; SLIAFlow needed no reconfiguration | |
| 4 | Substitute a genuine-marked node for the same role through the approved developer verification path | The banner disappears immediately and the genuine node is displayed in preference to the simulated one | |
| 5 | Stop both producers while Slicer stays connected | SLIAFlow reports a disconnected or stale state without freezing, and no invalid data is presented as success | |
| 6 | Close Slicer while both producers run | Slicer exits cleanly, the producers keep running, and no socket, connector or camera is left locked | |
| 7 | Re-run both automated suites | Both still pass, matching the step 1 baseline | |

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

## Documentation impact

- `docs/development/end_to_end_verification.md`: new. The startup and shutdown
  order, the swap procedure, the measurements, and the recorded evidence.
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`: record the verified
  hardware-free workflow and what changes when real hardware arrives.
- `tools/simulators/README.md`: link the verification procedure.

## Completion evidence

Reserved for implementation evidence. Must include both automated suite outputs
before and after, the achieved live frame rate, the UC1 wall-clock per cycle, and
the observed banner text at each stage of the producer swap.

## Review findings

Reserved for review.

## Human approval

Required before review and completion.
