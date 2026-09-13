---
id: SLIA-016
title: Stop reporting displaying for a link whose socket is gone
status: completed
branch: feature/SLIA-016-link-state-follows-socket
priority: high
depends_on: SLIA-008
required_skills: [slicer]
optional_tools: []
related_adrs: []
---

# SLIA-016 - Stop reporting displaying for a link whose socket is gone

## Goal

Make the `displaying` and `invalid` link states depend on the connector actually
being connected, rather than on a connector object existing, so that a panel
that says a link is displaying is telling the truth about the wire.

## Context

Found during the SLIA-014 end-to-end session, step 5. Both producers were killed
while SLIAFlow held both links open, `netstat` confirmed nothing was listening on
either port, and after a 120-second settle window both link state labels still
read `displaying`.

The cause is the presence test added by SLIA-008's review response:

```python
def _linkPresent(self, role: str) -> bool:
    return self.logic is not None and self.logic.connectorNode(role) is not None
```

`connectorNode` returns the module-owned connector object, which lives for as
long as the operator leaves the link open and says nothing about whether that
connector is connected to anything. `_onLinkDisconnected` does set
`disconnected` when the connector reports the loss, but the next
`_refreshResultPresentation` or `_displayLiveViewNode` overwrites it, because
the retained scene node is still discoverable and still validates. Every later
refresh - an operator refresh, a demo-mode toggle, a result-map change,
re-entering the module - re-asserts `displaying` over a dead socket.

That is the same defect the SLIA-008 review raised as its finding 3, fixed one
level too shallowly: the fix distinguished "a connector exists" from "no
connector exists" when the distinction that matters is "the connector is
connected" from "it is not".

The panel's state labels are the only thing on screen that claims to describe the
wire. The result status does degrade correctly to its stale warning when the
disconnection is observed, so the two disagree with each other, which is worse
than either being wrong alone.

This is now a hard dependency of the WP5 demonstrator
(`docs/architecture/WP5_MS5_DEMO_PLAN.md`). The demonstrator runs seven channels
where the verified session ran two, and `SLIA-022` replaces per-link
Connect/Disconnect pairs with one state label per link. A panel with fewer,
larger statements of state concentrates this defect into a more prominent place,
so it is fixed first rather than alongside.

`SLIAFlowLogic.connectorState(role)` already exists and already returns the
connector's own reported state through `connectorStateName(connector.GetState())`.
The authoritative value the fix needs is therefore available; `_linkPresent` is
simply not asking for it.

## Requirements

- Base `displaying` and `invalid` on the connector's own reported state, not on
  the existence of the connector object.
- A refresh of any kind, while the connector is not connected, must leave the
  state at `disconnected` (or `connecting`, if the connector is retrying) and
  must leave the result status at its stale wording.
- Keep what SLIA-008 got right: a lost link still does not blank a pane holding
  an image that really arrived and really validated, and a result that never
  came from a link is still not captioned as though a link had failed.
- The `_linkDropped` bookkeeping introduced alongside `_linkPresent` should be
  re-examined in the same pass; if the connector state is authoritative, some of
  it is redundant.

## Out of scope

- Any change to the five state names or to what the panel looks like.
- Reconnection policy. This card changes what is reported, not what is attempted.

## Files allowed

- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`
- `tasks/{backlog,active,review,completed}/SLIA-016-link-state-outlives-the-socket.md`

## Relevant skills and references

- `docs/development/end_to_end_verification.md`, step 5 and its failure row
- SLIA-008's completion evidence, in particular its review-response section
- `vtkMRMLIGTLConnectorNode` state enum, mirrored in `SLIAFlowLogic`
- [IGSIO/OpenIGTLinkIO connector state loop](https://github.com/IGSIO/OpenIGTLinkIO/blob/master/Logic/igtlioConnector.cxx)
- [SlicerOpenIGTLink image-node update path](https://github.com/openigtlink/SlicerOpenIGTLink/blob/master/OpenIGTLinkIF/MRML/vtkMRMLIGTLConnectorNode.cxx)

## Approved dependencies

None.

## Reproduction

1. Start the acquisition stand-in on 18944 and either UC1 producer on 18945.
2. Connect both links in SLIAFlow, tick demo mode, and confirm both state labels
   read `displaying`.
3. Kill both producers. Confirm with `netstat -ano | findstr "18944 18945"` that
   nothing is listening.
4. Press **Refresh Result**.

Observed: both state labels read `displaying`. Expected: an active client that
is still retrying reads `connecting`, with the result status on its stale
wording. An explicit **Disconnect**/connector stop reads `disconnected`.

## Implementation plan

1. Replace the misleading `_linkPresent` presence check with a
   `_linkConnected` check that consults `SLIAFlowLogic.connectorState()` and
   treats only `CONNECTION_RECEIVING` as a live connector for `displaying` and
   `invalid`.
2. Reconcile both live and result presentation paths with the connector state on
   every refresh, preserving `connecting` during retries and retaining valid
   images without claiming they are still updating.
3. Keep `_linkDropped` only as history that distinguishes a stale received node
   from a result that was never associated with a link. A reconnect clears that
   history only after the same received node changes, so rediscovery is not
   treated as a new wire message.
4. Add regression coverage for `StateOff`, `StateWaitConnection`, operator
   Disconnect, both presentation paths, and reconnect-before-new-data. Document
   the state authority in the UC1 image contract.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| A refresh over a dead connector does not report `displaying` or `invalid` | `test_staleResultIsNotReportedAsDisplayingWithoutALink` and `test_nonConnectedConnectorDoesNotReportInvalid` | automated |
| `StateWaitConnection` remains `connecting`, while `StateOff` maps to `disconnected` | `test_nonConnectedConnectorDoesNotReportInvalid` and `test_invalidResultDoesNotReplaceLastValidState` | automated |
| A refresh over a live connector still reports `displaying` | `test_staleResultIsNotReportedAsDisplayingWithoutALink`, extended with `StateConnected` | automated |
| The retained image and its banner survive the disconnection | `test_invalidResultDoesNotReplaceLastValidState` and `test_simulatedResultShowsPersistentBanner`; manual step 1 | automated; manual |
| Reconnection does not promote the retained result or live frame before new data | `test_reconnectDoesNotRedisplayRetainedResultBeforeNewData` and `test_reconnectDoesNotRedisplayRetainedLiveFrameBeforeNewData` | automated |
| A refresh cannot leave stale PASS wording beside a retrying label when the link had presented data | `test_reconnectDoesNotRedisplayRetainedResultBeforeNewData` and `test_staleWordingSurvivesBrowsingAfterADrop` | automated |
| Browsing to an empty map or toggling the live source after a drop keeps the stale wording | `test_staleWordingSurvivesBrowsingAfterADrop` | automated |
| A connector that only ever waited does not caption a later result as stale | `test_waitingConnectorLeavesNoStaleHistory` | automated |

The new and changed tests fail first by driving the existing fake connector to a
non-connected state while leaving its connector node in place. Against the
pre-change code, `test_staleResultIsNotReportedAsDisplayingWithoutALink` reports
`displaying` after the refresh and `test_nonConnectedConnectorDoesNotReportInvalid`
reports `invalid` for the dead connector.

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Run the reproduction above | While the OpenIGTLink client retries, both labels read `connecting` after the connector processes the loss, and the result status keeps its `SIMULATED: ` stale wording. After explicit Disconnect/Stop, the labels read `disconnected`. | Not recorded |
| 2 | Restart the producers without touching the panel | On TCP reconnect the labels first read `receiving`; the retained image remains stale. Only after a new frame/result arrives do the labels return to `displaying` and the result status return to PASS. | Not recorded |

Manual verification was not run before completion; see Human approval.

## Risks

The obvious over-correction is to make the state follow the socket so closely
that a momentary retry blanks the panel. `connecting` exists for that, and the
retained image must not move. Detection still cannot precede the connector's
own observation of a dead TCP peer; while `GetState()` remains connected, the
panel has no supported evidence that the peer has died.

The reconnect gate relies on the receiver updating the retained MRML node. The
OpenIGTLink image path calls `SetAndObserveImageData()` and `Modified()` when a
received image changes, so the node identity/MTime comparison is evidence of a
new received message rather than a new connector object. Anything else that
calls `Modified()` on the received node while the link is down would clear the
gate early; SLIAFlow's own provenance normalization only writes changed
attributes, so it does not. Manual verification with the OpenIGTLink-enabled
Slicer build remains required.

## Documentation impact

- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`: the paragraph on what the
  five states mean says `displaying` and `invalid` are claims about a live link.
  It should say what "live" is measured by.

## Completion evidence

### Implementation

`SLIAFlowWidget` now treats the logic-reported `StateConnected`/`receiving`
state as the only basis for promoting a link to `displaying` or `invalid`.
Every live and result refresh also synchronizes the panel state back to the
connector's `disconnected`, `connecting`, or `receiving` state, so a retained
scene node cannot resurrect a stronger claim after the socket is gone. A
queued refresh also records a drop when it sees the socket state change before
the event callback. The existing `_linkDropped` flag remains only for
stale-image history and does not override the current connector state; a
reconnect must change the retained node before that history is cleared.
The misleading `_linkPresent` name is gone, and unchanged state writes no
longer rebuild the connection controls.

The retained result and simulated banner still survive a loss. Reconnection is
now explicitly stale until a changed received node proves new data. The UC1
image contract documents that `StateConnected` is the required authority for
`displaying` and `invalid`.

The contract's claim that a retrying client reports `StateWaitConnection` was
checked against the OpenIGTLinkIO source vendored in the build tree
(`build/SlicerOpenIGTLink/OpenIGTLinkIO/Logic/igtlioConnector.cxx`): a lost
peer sets `STATE_WAIT_CONNECTION` and requests `DisconnectedEvent`; only a stop
sets `STATE_OFF`, with `DeactivatedEvent`.

### Validation

The pre-change regression run established the failure before production code
was changed:

| Command | Result |
| --- | --- |
| `scripts/development/run-slicer-tests.ps1` before implementation | 46 tests, 2 failures, 6 skipped, exit 1; the dead-connector test reported `invalid` and the retained-result test reported `displaying` |
| `scripts/development/run-python-quality.ps1` after review fixes | Passed, 6 + 31 files, exit 0 |
| `scripts/development/run-slicer-tests.ps1` after review fixes | 50 tests, OK, 6 skipped, exit 0 |
| `scripts/development/run-slicer-tests.ps1 -Headful` after review fixes | 50 tests, OK, 1 skipped, exit 0 |
| `git diff --check` | Passed, exit 0 |
| Configured `apps/SR/Slicer-build/Slicer.exe` OpenIGTLink probe | Exit 0; `vtkMRMLIGTLConnectorNode` unavailable in this base Slicer build |
| Existing `build/SLIAFlow/SlicerWithSLIAFlow.exe` OpenIGTLink probe | Exit 0; `vtkMRMLIGTLConnectorNode` available, but this launcher has not been rebuilt from the current working tree |

The Build target and CTest were not run because they would modify generated
local build outputs, and the configured source test target has no OpenIGTLink
connector class. The existing OpenIGTLink-enabled launcher is stale with
respect to this working tree. All connector coverage uses the fake connector.

## Review findings

Review of the working-tree implementation, 2026-09-13.

1. **Fixed - stale wording was lost by ordinary panel actions.** The stale
   caption was gated on `_resultEverDisplayed`/`_liveViewEverDisplayed` as well
   as `_linkDropped`. Browsing to a map with no data (WARN) resets the first,
   and toggling the live source resets the second, so returning to the
   retained image over a dropped link showed a plain PASS status beside a
   `connecting` label, contrary to requirement 2. The stale decision now rests
   on `_linkDropped` alone. To keep "a result that never came from a link is
   not captioned as a failure", `_linkDropped` is set only when the lost link
   had reached `receiving`/`displaying`/`invalid` or its pane held an image
   (`_linkHadSession`); a connector that only ever waited leaves no history.
   Covered by `test_staleWordingSurvivesBrowsingAfterADrop` and
   `test_waitingConnectorLeavesNoStaleHistory`.
2. **Fixed - DeactivatedEvent lost the prior state.** `_onConnectorEvent`
   overwrote the panel state before handing a deactivation to
   `_onLinkDisconnected`, which then could not tell what the link had been.
   Deactivation is now handled with disconnection, before the overwrite.
3. **Fixed - minor.** Redundant `connectorState` re-reads in the FAIL and WARN
   result branches were removed.
4. **Accepted risk - reconnect gate depends on node MTime.** See Risks. Not
   testable without a real connector.
5. **Open - manual verification.** Steps 1 and 2 are the only check against a
   real socket and have not been recorded.

## Human approval

The project owner directed review fixes and completion on 2026-09-13. Manual
verification steps 1 and 2 were not recorded at that time and remain the
outstanding real-connector evidence.
