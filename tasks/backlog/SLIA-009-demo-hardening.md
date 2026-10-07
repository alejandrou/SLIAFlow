---
id: SLIA-009
title: Operator runbook and shutdown hardening for the built application
status: backlog
branch:
priority: low
depends_on: SLIA-036
required_skills: [slicer]
optional_tools: []
related_adrs: [ADR-0003, ADR-0004]
---

# SLIA-009 - Operator runbook and shutdown hardening for the built application

## Goal

A person who has never seen the code can start `SlicerWithSLIAFlow.exe`, run a
capture on the cube read from disk or received from IUMA's app, read what the
panels show, and shut down cleanly, following one short runbook.

## Context

*Rewritten on 2026-09-24.* The original card documented camera-only, simulated
stand-in and demo-mode operation, with banners marking simulated results.
`ADR-0003` removed demo mode, banners and the stand-in producers, and `ADR-0004`
reduces the data to one cube and makes IUMA's app the source. What remains
worth doing is the runbook and the clean-shutdown checks, written for the
application as it will be after `SLIA-036`, which receives the app's cube.

## Requirements

- One operator runbook, `docs/operator/SLIAFLOW_RUNBOOK.md`, covering:
  - starting the built application and the laptop camera;
  - Capture on the cube read from disk;
  - connecting to IUMA's app and reading the Connections panel;
  - Capture on a cube received from the app;
  - what each panel shows, what "not validated" means, and that nothing shown
    is a clinical result;
  - clean shutdown.
- A troubleshooting section: camera busy (another program holds index 0), app
  not running, bands missing, UC1 failed or timed out, GPU out of memory.
- Shutdown leaves no locked camera, no running UC1 process, no build lock and no
  module-owned connector. Add tests where the module's cleanup does not already
  prove this.
- Reload and Reload and Test instructions for developers, in a short appendix.
- No screenshot of a result without its provenance text visible.

### Fixes and cleanup collected for this card

*Added on 2026-10-06.* This card also takes the defects and cleanup found
since `SLIA-030`, so that the runbook describes an application without them.
The stand-in and recorder test findings of the same review, and the flaky
band-count test, moved to `SLIA-036`, which rewrites those tests.

1. **Camera volume left in other panels.** `SLIAFlowLogic._removeVolumeNode`
   removes a volume that a panel still shows. During `RemoveNode`, that panel's
   background switches to the remaining volume, "Laptop camera". After
   Reload and Test, HS Cube and Tumour Delineation both show "B: Laptop
   camera". It is one node: HS Cube shows black because its offset,
   S = 1 mm, is past the camera's single slice. Traced in 57 places across
   about 40 `_captureSession` tests, through `_forgetCube`, `_forgetResult`
   and `_forgetVascularMap`, in Enhanced Vascularization too. The switch most
   likely comes from the slice controller's layer combo box selecting another
   volume (read in Slicer's source, not traced).
   - Fix: before removing a node, empty every SLIAFlow panel layer that
     references it.
   - Test: after a capture session, only LiveView shows the camera volume, and
     no panel layer names a removed node.
   - Check at specification: whether any path outside the tests removes a
     volume without redrawing its panel, such as Reload, a failed capture, or
     a second capture while the camera runs.
2. **Nested Reload and Test.** The tests spin the Qt event loop, so a second
   click on Reload and Test starts a run inside the first one. Each `setUp`
   then clears the scene under the other run, and unrelated tests fail. Refuse
   or ignore a run while one is in progress.
3. **Unused simulator code.**
   - `igtl_transport.prepareFrameForWire` has only test callers. Retire it
     with `test_frameIsPreparedAsKjiComponentsAndRotates`.
   - `allowSharedPort` has no producer since `ADR-0003`, and no command line
     still offers `--allow-shared-port`. Retire `_SharedPortServer`,
     `sharedPortWarning`, the shared-port branches of `portInUseMessage` and
     `assertPortCanBeServed`, the README paragraph, and the tests that pass
     `allowSharedPort=True`. Keep the tests for occupied-port refusal and
     client reconnection.
   - Keep the ground-truth, camera, BMP, UC1 and UC2 failure-path and 93-band
     mapping tests. They protect supported behaviour. Ground-truth tests that
     look similar check different layers: selection, MRML data and view
     binding.

## Out of scope

- An installer.
- Clinical deployment or validation.
- Algorithm changes.

## Files allowed

To be defined at specification. Expected: `docs/operator/SLIAFLOW_RUNBOOK.md`
(new), `README.md`, `README_SLIAFlow_Build.md`, `SLIAFlowLogic.py`,
`SLIAFlowWidget.py`, `SLIAFlowTest.py`, and for the simulator cleanup
`tools/simulators/stratum_sim/igtl_transport.py`,
`tools/simulators/tests/test_igtl_transport.py` and
`tools/simulators/README.md`.

## Relevant skills and references

- `.ai/workflows/manual-verification-workflow.md`
- `docs/development/uc1_demo_runbook.md`, which the new runbook replaces for
  operators
- `docs/hardware/acquisition_app_and_hardware.md`

## Implementation plan

To be defined at specification.

## Acceptance criteria

To be defined at specification. At minimum: a first-time reader completes a
capture and a clean shutdown from the runbook alone, and records what they had
to guess.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
|  |  |  |

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 |  |  |  |

## Risks

A runbook can suggest a readiness the prototype does not have. The prototype
and non-clinical status stay at the top of it.

## Documentation impact

The new runbook, linked from `README.md`.

## Completion evidence

## Review findings

## Human approval
