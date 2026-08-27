---
id: SLIA-006
title: Present genuine UC1 result volumes
status: backlog
branch:
priority: high
depends_on: SLIA-005
required_skills: [slicer]
optional_tools: []
related_adrs: []
---

# SLIA-006 - Present genuine UC1 result volumes

## Goal

Validate and display genuine UC1 result volumes already present in the MRML
scene, without adding networking or generating result data.

## Context

This task establishes the result-display boundary before OpenIGTLink is added.
The operator/demo workflow must never expose generated test fixtures.

## Requirements

- Support `tmdMap`, majority-voting class, majority-voting probability, SVM probability, and KNN probability selections.
- Default to `tmdMap` and expose class selection only for four-component SVM/KNN maps.
- Require positive image dimensions and finite values.
- Require `float32` values in `[0,1]` for probability maps.
- Require one-component `uint8` values in `{1,2,3,4}` for the class map.
- Require four components for SVM/KNN maps and display the selected class component through a module-owned transient scalar volume.
- Apply continuous colour presentation to probability maps and a discrete four-class presentation to the class map.
- Store source and display node IDs in the parameter node.
- Reject invalid data before assigning it to the result view.
- Leave the view black and display a clear waiting/invalid status when no valid genuine result is selected.

## Out of scope

- Deriving or normalizing any UC1 map in Slicer.
- OpenIGTLink connectors.
- Overlaying result data on the camera view.
- Persisting or reporting diagnostic conclusions.

## Files allowed

- `extensions/SLIAFlow/SLIAFlow/Resources/UI/SLIAFlow.ui`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowParameterNode.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `extensions/SLIAFlow/SLIAFlow/Testing/**`
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`
- `tasks/{backlog,active,review,completed}/SLIA-006-genuine-result-presentation.md`

## Relevant skills and references

- Slicer MRML volume, display-node, NumPy, and colour-node APIs.
- `.ai/policies/algorithm-boundary-policy.md`
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`

## Implementation plan

1. Define map descriptors and strict validation in the logic layer.
2. Add result source and class controls to the widget.
3. Create module-owned display resources and assign only validated nodes.
4. Add focused in-memory test fixtures that never enter the demo path.
5. Document the producer/consumer contract.

## Acceptance criteria

- Each supported valid map type can be displayed in the right pane.
- Invalid maps are rejected before display and cannot be reported as success.
- SVM/KNN class selection changes only the selected genuine probability component.
- No test or simulated result is selectable through the user interface.
- Missing data restores the black waiting state.

## Test plan

- Test valid and invalid scalar type, component count, dimensions, finite values, ranges, and classes.
- Test node-ID persistence and deletion handling.
- Test four-component extraction using private in-memory arrays.
- Run Python quality, focused CTest, Reload, and Reload and Test.

## Manual verification

Use only approved synthetic developer fixtures through the test runner. In the
normal module UI, confirm that no result appears without an externally supplied
valid node.

## Risks

Incorrect component or range handling could make malformed output look valid.
Validation occurs before scene display state is changed.

## Documentation impact

Add the exact UC1 image and class contract.

## Completion evidence

Reserved for implementation evidence.

## Review findings

Reserved for review.

## Human approval

Required before review and completion.
