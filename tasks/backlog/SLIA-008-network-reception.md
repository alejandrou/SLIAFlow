---
id: SLIA-008
title: Receive live and UC1 images over OpenIGTLink
status: backlog
branch:
priority: high
depends_on: SLIA-007
required_skills: [slicer]
optional_tools: []
related_adrs: []
---

# SLIA-008 - Receive live and UC1 images over OpenIGTLink

## Goal

Receive the acquisition live view and genuine UC1 maps in SLIAFlow using two
independent OpenIGTLink client connectors.

## Context

The external applications remain separate processes. SLIAFlow is only a validated
consumer and visualization surface.

## Requirements

- Create an acquisition client connector for `127.0.0.1:18944` and device `LiveView`.
- Create a UC1 client connector for `127.0.0.1:18945`.
- Support exact UC1 device names `UC1_TMD`, `UC1_MV_CLASS`, `UC1_MV_PROB`, `UC1_SVM_PROB`, and `UC1_KNN_PROB`.
- Allow live-source switching between laptop camera and OpenIGTLink `LiveView`.
- Match incoming nodes by device name, then store stable MRML node IDs.
- Run the SLIA-006 validation boundary before displaying any result node.
- Do not derive `UC1_TMD` or normalize incoming values in Slicer.
- Expose disconnected, connecting, receiving, invalid, and displaying states.
- On connection loss, keep the last valid image with a stale/disconnected status or return to black when no valid image exists.
- Remove observers and stop module-owned connectors during cleanup without deleting externally owned nodes.

## Out of scope

- Changes to sender applications or algorithms.
- Registration or overlay between RGB and HSI-derived images.
- Automatic clinical interpretation, persistence, or reporting.

## Files allowed

- `extensions/SLIAFlow/SLIAFlow/Resources/UI/SLIAFlow.ui`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowParameterNode.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `extensions/SLIAFlow/SLIAFlow/Testing/**`
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`
- `tasks/{backlog,active,review,completed}/SLIA-008-network-reception.md`

## Relevant skills and references

- SlicerOpenIGTLink `vtkMRMLIGTLConnectorNode` client and observer APIs.
- `.ai/policies/algorithm-boundary-policy.md`
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`

## Implementation plan

1. Add connector configuration and ownership to module logic/state.
2. Observe connector and scene events without polling the UI thread aggressively.
3. Resolve exact device names to MRML nodes and validate their data.
4. Bind the active live and result nodes to their separate views.
5. Cover connection transitions, malformed data, cleanup, and source switching.

## Acceptance criteria

- A conforming `LiveView` stream appears in only the left pane.
- A conforming selected UC1 stream appears in only the right pane.
- Missing or invalid UC1 data cannot replace the black/last-valid result state as successful output.
- Disconnect/reconnect and source switching do not freeze Slicer or leak connectors.
- Sender source code remains unchanged.

## Test plan

- Test connector creation and configuration with no remote server.
- Run local loopback tests for all device names and valid/invalid image contracts.
- Test disconnection, reconnection, node removal, and cleanup.
- Run Python quality, focused CTest, Reload, and Reload and Test.

## Manual verification

Connect an approved sender when available. Without one, verify clean disconnected
states and that the laptop camera continues to provide the camera-only demo.

## Risks

Device names and output layouts may change in the external wrapper. The documented
contract is exact; incompatible data is rejected visibly rather than guessed.

## Documentation impact

Finalize sender endpoint, device-name, and validation instructions.

## Completion evidence

Reserved for implementation evidence.

## Review findings

Reserved for review.

## Human approval

Required before review and completion.
