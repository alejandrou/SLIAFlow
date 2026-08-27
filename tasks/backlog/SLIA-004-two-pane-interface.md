---
id: SLIA-004
title: Implement the two-pane Slicer interface
status: backlog
branch:
priority: high
depends_on: SLIA-003
required_skills: [slicer]
optional_tools: []
related_adrs: []
---

# SLIA-004 - Implement the two-pane Slicer interface

## Goal

Create the simple side-by-side visualization interface shown by the STRATUM
concept without displaying any input or result data.

## Context

The left view will later show either a laptop camera or AcquisitionSystemApp
`LiveView`. The right view will only show validated genuine UC1 output.

## Requirements

- Register custom Slicer layout ID `701`.
- Create horizontal slice views named `SLIAFlowLive` and `SLIAFlowResult`.
- Label the views `Live Image` and `UC1 Result`.
- Keep both views black when they have no assigned volume.
- Show `Waiting for genuine UC1 result` in the result-view corner annotation.
- Add live-source, camera-index, Start, Stop, result-map, result-class, and status controls.
- Default live source to laptop camera, camera index to 0, and result map to `tmdMap`.
- Keep controls that depend on future tasks disabled with explanatory status text.
- Restore the previous Slicer layout when appropriate on cleanup/reload.

## Out of scope

- Capturing a camera frame.
- Creating test images for display.
- Receiving or rendering a UC1 result.
- OpenIGTLink dependencies or connectors.

## Files allowed

- `extensions/SLIAFlow/SLIAFlow/Resources/UI/SLIAFlow.ui`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowParameterNode.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `extensions/SLIAFlow/SLIAFlow/Testing/**`
- `tasks/{backlog,active,review,completed}/SLIA-004-two-pane-interface.md`

## Relevant skills and references

- Slicer custom layout, slice-view, MRML, and corner-annotation APIs.
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`

## Implementation plan

1. Add parameter defaults and the minimal UI controls.
2. Register and activate the two-view layout while the module is entered.
3. Configure black backgrounds, view labels, and waiting annotations.
4. Add lifecycle cleanup and focused tests.

## Acceptance criteria

- Entering SLIAFlow produces exactly two side-by-side image views.
- Both views are black and contain no diagnostic image.
- The right view visibly communicates that genuine UC1 data is required.
- Leaving, re-entering, Reload, and scene close do not duplicate layouts or observers.

## Test plan

- Verify layout registration, view-node names, defaults, and cleanup in Slicer tests.
- Run Python quality and focused CTest.
- Manually inspect the layout and run Reload and Reload and Test.

## Manual verification

Confirm the two black panes and controls match the roadmap and remain stable after Reload.

## Risks

Custom layout registration can conflict with other IDs or leave stale annotations.
ID 701 and module-owned view names are fixed for this module.

## Documentation impact

None beyond task evidence unless implementation reveals a required operator note.

## Completion evidence

Reserved for implementation evidence.

## Review findings

Reserved for review.

## Human approval

Required before review and completion.
