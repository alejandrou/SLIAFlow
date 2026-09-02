---
id: SLIA-009
title: Harden and document the SLIAFlow demonstration
status: backlog
branch:
priority: medium
depends_on: SLIA-014
required_skills: [slicer]
optional_tools: []
related_adrs: []
---

# SLIA-009 - Harden and document the SLIAFlow demonstration

## Goal

Provide a simple Windows operator workflow that can demonstrate the Slicer
interface safely with only a laptop camera and can later receive genuine project
outputs without changing the interface.

## Context

Hardware and external algorithms may be unavailable during early demonstrations.
The camera is a genuine live source. The result pane stays explicitly empty
unless a producer supplies a result: a genuine one, or - only under the
transient demo-mode opt-in introduced in SLIA-010 - an externally produced
simulated one, always shown under its banner. The runbook has to describe both
modes without letting an operator confuse one for the other.

## Requirements

- Add a short operator runbook and startup/shutdown checklist.
- Document one-time camera support installation and dependency checks.
- Document camera-only, acquisition-connected, simulated (stand-in producers),
  and full-integration modes.
- Document that the SLIA-011 webcam frame source and `SLIAFlowLogic.startCamera`
  both want camera index 0 and that Windows will fail the second open, so the
  simulator defaults to its synthetic frame source.
- State in the runbook that a banner on the result pane means the displayed map
  is not a genuine clinical result, and that demo mode is never persisted.
- Make missing camera, missing OpenIGTLink, disconnected sender, malformed result, and clean shutdown messages understandable.
- Ensure stopping the module releases cameras, timers, observers, and module-owned connectors.
- Record Reload and Reload and Test instructions.
- State clearly that the module is a prototype and not clinically validated.
- Include no fabricated result screenshots, and no screenshot of a simulated
  result without its banner visible.

## Out of scope

- Packaging an installer.
- Clinical-trial deployment or validation.
- Algorithm changes, performance claims, or automated clinical reporting.

## Files allowed

- `extensions/SLIAFlow/SLIAFlow/SLIAFlow.py`
- `extensions/SLIAFlow/SLIAFlow/Resources/UI/SLIAFlow.ui`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `extensions/SLIAFlow/SLIAFlow/Testing/**`
- `docs/operator/SLIAFLOW_DEMO_RUNBOOK.md`
- `README.md`
- `README_SLIAFlow_Build.md`
- `tasks/{backlog,active,review,completed}/SLIA-009-demo-hardening.md`

## Relevant skills and references

- Slicer scripted-module lifecycle and manual verification guidance.
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`

## Implementation plan

1. Audit the full module lifecycle and user-facing failure messages.
2. Add targeted cleanup and state-transition tests where gaps exist.
3. Write the camera-only, simulated, and connected-mode runbook.
4. Execute automated checks and the complete manual demonstration checklist,
   including the simulated mode and its banner.

## Acceptance criteria

- A non-technical operator can start and stop the camera-only demonstration from the runbook.
- The result pane remains black and clearly waiting whenever nothing is being
  displayed - that is, when no genuine output exists and demo mode is off.
- An operator following the runbook can enter the simulated mode, recognize the
  banner as the marker of a non-genuine result, and return to a clean
  camera-only state, without reading any code.
- All expected failure modes are understandable and recoverable without restarting Windows.
- Shutdown leaves no locked camera or running module-owned connector.
- Documentation makes no clinical claim and shows no unbannered result image.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| A non-technical operator can run the camera-only demonstration from the runbook | Manual step 1 | manual |
| The result pane is black and waiting whenever nothing is displayed | `SLIAFlowTest.test_resultPaneWaitsWhenNothingIsDisplayed` | automated; manual step 2 |
| The simulated mode is operable from the runbook and its banner is understood | Manual step 3 | manual |
| Every documented failure mode is understandable and recoverable | Manual step 4 | manual |
| Shutdown leaves no locked camera or module-owned connector | `SLIAFlowTest.test_cleanupReleasesCameraTimersAndConnectors` | automated; manual step 5 |
| The documentation makes no clinical claim and shows no unbannered result | Manual step 6 | manual |

Tests to add or change, and how each one will be shown to fail first:

- `test_resultPaneWaitsWhenNothingIsDisplayed` asserts the black pane and the
  waiting status across both the no-source and the simulated-source-with-demo-off
  cases; before implementation it is shown red against a build where demo mode is
  left on across `enter()`, which is the state the runbook must never produce.
- `test_cleanupReleasesCameraTimersAndConnectors` extends the existing lifecycle
  coverage to module-owned connectors; it is shown red against a `cleanup()` with
  the connector teardown removed.
- Run the full extension CTest suite and Python quality checks before and after,
  and record both outputs.
- Exercise repeated enter/exit, camera start/stop, connection loss, scene close,
  and Reload as part of manual step 4.

## Manual verification

Follow the runbook from a clean Slicer launch, without relying on developer
knowledge, and record what a first-time reader had to guess.

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Follow the camera-only section end to end from a clean Slicer launch | The demonstration starts and stops from the runbook alone; the live pane shows the camera and the result pane stays black with its waiting status | |
| 2 | With a simulated producer running and demo mode off, watch the result pane | It stays black and clearly waiting; nothing about the running producer changes that | |
| 3 | Follow the simulated-mode section: enable demo mode, observe the banner, then return to camera-only | The map appears under its banner; the runbook states plainly that a banner means the result is not genuine; disabling demo mode returns the pane to black, and demo mode is off again after leaving and re-entering the module | |
| 4 | Work through each documented failure mode: no camera, missing OpenIGTLink, sender disconnected, malformed result | Each produces an understandable message and a documented recovery, and none requires restarting Windows | |
| 5 | Shut down following the checklist, then start the camera in another application | The camera opens immediately, and no module-owned connector or timer survives the shutdown | |
| 6 | Read the finished runbook end to end | It states the prototype and non-clinical status prominently, makes no clinical claim, and contains no result screenshot without a visible banner | |

## Risks

A runbook can imply unsupported readiness if limitations are not prominent. Prototype,
data, and genuine-result boundaries remain visible throughout the instructions.

## Documentation impact

Add the final operator-facing demonstration guide and link it from project entry points.

## Completion evidence

Reserved for implementation evidence.

## Review findings

Reserved for review.

## Human approval

Required before review and completion.
