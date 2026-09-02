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

The senders may be either the real applications or the SLIA-011 to SLIA-013
stand-ins. SLIAFlow must not be able to tell which, except through the
provenance attributes that travel with the data.

## Requirements

- Create an acquisition client connector for `127.0.0.1:18944` and device `LiveView`.
- Create a UC1 client connector for `127.0.0.1:18945`.
- Support exact UC1 device names `UC1_TMD`, `UC1_MV_CLASS`, `UC1_MV_PROB`, `UC1_SVM_PROB`, and `UC1_KNN_PROB`.
- Allow live-source switching between laptop camera and OpenIGTLink `LiveView`.
- Match incoming nodes by device name, then store stable MRML node IDs.
- Run the SLIA-006 validation boundary before displaying any result node.
- Establish the incoming metadata contract before writing any discovery code.
  The converter does not set an incoming metadata key as an MRML attribute of the
  same name. At commit `85e5f764f3ad3d4adbaa568db0104b2b8f5998e8` - the commit
  SLIA-007 pins, so this is the build in question and not upstream drift -
  `OpenIGTLinkIF/MRML/vtkMRMLIGTLConnectorNode.cxx` closes its device-modified
  handler by walking the message's metadata map and writing each entry as
  `std::string tag = "OpenIGTLink." + iter->first;` followed by
  `modifiedNode->SetAttribute(tag.c_str(), ...)`, with no condition around it. So
  a message sent as `SLIAFlow.DataOrigin` arrives as the attribute
  `OpenIGTLink.SLIAFlow.DataOrigin`, and the bare spelling never appears at all.
  That is read from source, so the observation step below is confirming that the
  built binary behaves like the source it was built from - cheap, and worth doing
  once - rather than resolving an open question: send one message from the
  SLIA-012 stand-in, dump every attribute of the received node with
  `GetAttributeNames()`, and record the exact observed names in
  `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`. Everything below depends on
  that recorded observation.
- Translate the observed wire attributes into the canonical `SLIAFlow.*`
  attributes on the received node, in one place, before any discovery call, and
  accept both the bare and the prefixed spelling of all four keys
  (`SLIAFlow.ResultMap`, `SLIAFlow.DeviceName`, `SLIAFlow.DataOrigin`,
  `SLIAFlow.SimulationDetail`). The prefixed spelling is what the source above
  produces and is the one that must work; accepting the bare spelling as well
  costs a line and keeps the receiver working if the pin ever moves to a build
  that behaves differently. Discovery,
  validation and the SLIA-010 origin gate then operate only on canonical
  attributes and stay unaware that a network exists.
- Treat a received node whose provenance attributes are absent or unrecognized as
  not displayable: it is neither genuine nor simulated, so it is reported as
  invalid rather than shown. A missing attribute must never widen into a default.
- Route any incoming node carrying the SLIA-010 simulated origin through
  `findResultSource(..., allowSimulated=True)` and the demo-mode gate; never
  infer provenance from the connector, port or hostname. Both a stand-in and
  the genuine UC1 runner use `127.0.0.1:18945`, so the endpoint carries no
  provenance information.
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
- The attribute names the pinned SlicerOpenIGTLink build actually produces are
  recorded in the contract document, and the translation layer accepts both the
  bare and the prefixed spelling of all four provenance keys.
- A received simulated-origin node is displayed only under the SLIA-010
  demo-mode gate and always carries its banner.
- A received node with absent or unrecognized provenance is reported invalid and
  never displayed.
- Missing or invalid UC1 data cannot replace the black/last-valid result state as successful output.
- Disconnect/reconnect and source switching do not freeze Slicer or leak connectors.
- Sender source code remains unchanged.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| A conforming `LiveView` stream appears only in the left pane | `SLIAFlowTest.test_liveViewNodeBindsToLivePaneOnly` | automated; manual step 2 |
| A conforming UC1 stream appears only in the right pane | `SLIAFlowTest.test_resultNodeBindsToResultPaneOnly` | automated; manual step 2 |
| Both attribute spellings translate to the canonical names | `SLIAFlowTest.test_prefixedAndBareWireAttributesBothTranslate` | automated; manual step 1 |
| A received simulated node obeys the demo-mode gate and is bannered | `SLIAFlowTest.test_receivedSimulatedNodeObeysDemoModeGate` | automated; manual step 3 |
| Absent or unrecognized provenance is invalid, not displayed | `SLIAFlowTest.test_unknownProvenanceIsRejectedNotDefaulted` | automated |
| Invalid data never replaces black or last-valid as success | `SLIAFlowTest.test_invalidResultDoesNotReplaceLastValidState` | automated |
| Disconnect, reconnect and source switching leak nothing | `SLIAFlowTest.test_connectorLifecycleIsCleanAcrossTransitions` | automated; manual step 4 |
| Sender source code remains unchanged | Manual step 5 | manual |

Tests to add or change, and how each one will be shown to fail first:

- `test_prefixedAndBareWireAttributesBothTranslate` is written from the attribute
  names observed in manual step 1, and is shown red against a receiver that reads
  `SLIAFlow.DataOrigin` directly off the received node - which is the assumption
  this card exists to disprove.
- `test_unknownProvenanceIsRejectedNotDefaulted` is shown red against a receiver
  that treats a missing origin as genuine, and again against one that treats it
  as simulated. Both directions must fail, because either default is a fabricated
  provenance.
- `test_receivedSimulatedNodeObeysDemoModeGate` is shown red against a receiver
  that calls `findResultSource(..., allowSimulated=True)` unconditionally,
  bypassing the SLIA-010 opt-in.
- The remaining tests fail with `AttributeError` for the connector attributes
  before those exist; record the output.
- Run Python quality, the focused CTest, Reload, and Reload and Test after
  implementation.

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | With the SLIA-012 stand-in sending on 18945, print `GetAttributeNames()` and every value for the received node in the Python console, and paste the output into the contract document | The exact attribute names this build produces are recorded, whether bare or prefixed. The translation layer is written against that output, not against an assumption | |
| 2 | Run the acquisition stand-in and a map producer, and connect both connectors | LiveView frames appear only in the left pane; the selected UC1 map appears only in the right | |
| 3 | Observe a received simulated map with demo mode off, then on | Off: the right pane stays black with the waiting status. On: the map appears and carries its banner | |
| 4 | Stop the sender, restart it, then switch the live source between camera and LiveView several times | Slicer never freezes; the status moves through disconnected and receiving; no module-owned connector is left behind after cleanup | |
| 5 | Run `git status --short` under `workspace/components/` | No sender source file is modified | |

## Risks

Device names and output layouts may change in the external wrapper. The documented
contract is exact; incompatible data is rejected visibly rather than guessed.

## Documentation impact

Finalize sender endpoint, device-name, and validation instructions, and record
the observed incoming attribute names for the pinned SlicerOpenIGTLink build
alongside the four canonical provenance keys.

## Completion evidence

Reserved for implementation evidence.

## Review findings

Reserved for review.

## Human approval

Required before review and completion.
