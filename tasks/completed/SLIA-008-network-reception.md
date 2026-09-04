---
id: SLIA-008
title: Receive live and UC1 images over OpenIGTLink
status: active
branch: feature/SLIA-008-network-reception
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
| 1 | With the SLIA-012 stand-in sending on 18945, print `GetAttributeNames()` and every value for the received node in the Python console, and paste the output into the contract document | The exact attribute names this build produces are recorded, whether bare or prefixed. The translation layer is written against that output, not against an assumption | Pass, scripted under `build\SLIAFlow\SlicerWithSLIAFlow.exe`. All five map nodes carried only the prefixed spelling - `OpenIGTLink.SLIAFlow.{DataOrigin,DeviceName,ResultMap,SimulationDetail}` - plus `OriginalNodeName`, which OpenIGTLinkIF writes itself. The bare spelling appeared on no node. Node classes and scalar types matched the result-roles table exactly. Recorded in the contract document |
| 2 | Run the acquisition stand-in and a map producer, and connect both connectors | LiveView frames appear only in the left pane; the selected UC1 map appears only in the right | Pass, scripted headful against both stand-ins. LiveView bound to the live pane with the result pane background `None`; the UC1 result bound to the result pane with the live pane background `None`. Project-owner confirmation by eye is still outstanding |
| 3 | Observe a received simulated map with demo mode off, then on | Off: the right pane stays black with the waiting status. On: the map appears and carries its banner | Pass. Off: `WARN Waiting for genuine UC1_TMD result.` and no result reference. On: `PASS: SIMULATED: Displaying TMD probability from UC1_TMD.`, `dataOrigin=simulated`, detail `arithmetic stand-in, not a classifier`, banner actor present |
| 4 | Stop the sender, restart it, then switch the live source between camera and LiveView several times | Slicer never freezes; the status moves through disconnected and receiving; no module-owned connector is left behind after cleanup | Pass. States moved disconnected -> receiving -> displaying -> disconnected; three camera/LiveView round trips left exactly one connector; `cleanup()` left zero `vtkMRMLIGTLConnectorNode` in the scene. On disconnect the last valid result stayed on screen under the stale status |
| 5 | Run `git status --short` under `workspace/components/` | No sender source file is modified | Pass. `git status --short workspace/components/` prints nothing |

## Risks

Device names and output layouts may change in the external wrapper. The documented
contract is exact; incompatible data is rejected visibly rather than guessed.

## Documentation impact

Finalize sender endpoint, device-name, and validation instructions, and record
the observed incoming attribute names for the pinned SlicerOpenIGTLink build
alongside the four canonical provenance keys.

## Completion evidence

### What was built

`SLIAFlowLogic` gained an OpenIGTLink reception section and a connector-
ownership section. `normalizeReceivedProvenance` is the single place that
reconciles the wire spelling with the canonical one, and it runs at the top of
`presentSelectedResult`, before discovery; `findResultSource`, the validation
boundary and the SLIA-010 origin gate were left reading canonical attributes
only. `receivedOrigin` recognizes exactly the two contract origins and returns
`None` for anything else, and `unrecognizedProvenanceNode` turns a role claim
without a recognized origin into a `FAIL` carrying `provenance="unrecognized"`,
so it is reported invalid rather than as a source that never arrived.

Connectors are held by the logic instance rather than looked up from the scene,
which is what makes the lifecycle testable in a Slicer with no OpenIGTLink and
makes it impossible for cleanup to miss one. Only a node carrying
`SLIAFlow.Owner = Connectors` is stopped and removed. The connector state and
event enums are mirrored from the pinned header for the same reason.

`SLIAFlowWidget` gained the two link controls, the live-source switch, the
connector observers and the five-state reporting. Two behaviours are worth
naming: a lost link keeps a pane that is already showing something valid and
says the image is stale, rather than blanking work that really did arrive and
really did validate; and wire-triggered result refreshes are throttled to
`RESULT_REFRESH_INTERVAL_SEC`, while an operator refresh never is.

### Validation

| Command | Result |
| --- | --- |
| `scripts/development/run-python-quality.ps1` | Passed, exit 0, 6 + 31 files |
| `scripts/development/run-slicer-tests.ps1` | 45 tests, OK (skipped=6), exit 0 |
| `scripts/development/run-slicer-tests.ps1 -Headful` | 45 tests, OK (skipped=1), exit 0 |
| `cmake --build build/SLIAFlow --config Release` | Succeeded |
| `scripts/development/run-slicer-tests.ps1 -Target Build -Headful` | 45 tests, OK (skipped=1), exit 0 |

The `Build -Headful` run is the one that matters most here: it is the only
target whose Slicer actually has `vtkMRMLIGTLConnectorNode`, so it is where the
real-connector branch of `test_connectorLifecycleIsCleanAcrossTransitions`
runs and where a leaked connector node would be caught.

Seven new tests were added, plus one for source switching. Before the
implementation existed they failed as described in the test plan; the three
worth recording specifically are that
`test_prefixedAndBareWireAttributesBothTranslate` asserts discovery finds
nothing before translation - which is the assumption this card existed to
disprove - that `test_unknownProvenanceIsRejectedNotDefaulted` fails a receiver
defaulting a missing origin in either direction, and that
`test_receivedSimulatedNodeObeysDemoModeGate` fails a receiver that passes
`allowSimulated=True` unconditionally.

### Changes made after review

A code review of the working tree raised six findings. Four were defects and
were fixed, one was a genuine gap that is only partly ours to close, and one was
a documentation error rather than a code one. Four tests were added.

`normalizeReceivedProvenance` now mirrors the wire instead of accumulating from
it: for a node whose producer speaks the prefixed dialect, a canonical
attribute whose prefixed counterpart is absent is removed. The review's exact
scenario - a producer that sends provenance once and then stops - remains
undetectable here, because the connector removes no attribute it has ever
written, so the earlier message's prefixed keys are still on the node when the
next one arrives. Nothing at this layer can distinguish that from a message
that resent them. The requirement it places on producers is now stated in the
contract document, and the part that is ours is fixed and tested by
`test_provenanceMirrorsTheWireInsteadOfAccumulating`.

The live-source selector was disabled by `_configureResultControls` on every
call, which left the switching requirement unmet however good the code behind
it was. It is now enabled wherever OpenIGTLink is present, and the widget test
asserts that rather than asserting the bug.

`displaying` and `invalid` are now reported only while a connector exists.
Previously any later refresh rediscovered the retained scene node and reported
`displaying` for a link that had been disconnected. The related distinction
matters too and is now kept: a result that arrives with no link ever having
been opened is not captioned as though a link had failed, and a stale simulated
result keeps its SIMULATED prefix, because the banner is still on the image and
the status has to agree with it.

The acquisition link reports `displaying` and `invalid` as well, so both links
expose all five states rather than only the socket's three.

Throttled wire events now schedule a trailing refresh, so the last event of a
burst - a one-shot send, or the tail of a five-map cycle - is delayed rather
than dropped.

The review's sixth finding, that switching away from LiveView leaves the
acquisition connector running, is behaviour I kept and documentation I
corrected. The camera belongs to the pane; the link belongs to the operator,
who opened it with its own button, and tearing it down because a pane changed
source would be surprising. What the switch does now release is the pane's hold
on the stream, which it previously did not: the `liveSourceVolume` reference is
cleared. The contract sentence that promised more than that was wrong and has
been rewritten.

### Not done here

No CTest run was made beyond the two script targets; `ctest --test-dir
build/SLIAFlow` was not re-run because this card changed no CMake or C++.

The bare attribute spelling is accepted but no build produces it, so that half
of the translation is exercised only by its unit test. That is deliberate: it
is insurance against the pin moving, not a path in use.

## Review findings

Reserved for review.

## Human approval

Required before review and completion.
