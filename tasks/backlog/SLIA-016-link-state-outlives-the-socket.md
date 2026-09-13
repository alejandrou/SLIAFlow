---
id: SLIA-016
title: Stop reporting displaying for a link whose socket is gone
status: backlog
branch:
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

## Approved dependencies

None.

## Reproduction

1. Start the acquisition stand-in on 18944 and either UC1 producer on 18945.
2. Connect both links in SLIAFlow, tick demo mode, and confirm both state labels
   read `displaying`.
3. Kill both producers. Confirm with `netstat -ano | findstr "18944 18945"` that
   nothing is listening.
4. Press **Refresh Result**.

Observed: both state labels read `displaying`. Expected: both read
`disconnected`, with the result status on its stale wording.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| A refresh over a dead connector does not report `displaying` | New unit test with a fake connector reporting a non-connected state | automated |
| A refresh over a live connector still reports `displaying` | Existing `test_staleResultIsNotReportedAsDisplayingWithoutALink`, extended | automated |
| The retained image and its banner survive the disconnection | Existing coverage, unchanged | automated |

The new test fails first by driving the existing fake connector to a
disconnected state and asserting `disconnected` after a refresh; against the
current code it reports `displaying`.

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Run the reproduction above | Both labels read `disconnected` after the refresh, and the result status keeps its `SIMULATED: ` stale wording | |
| 2 | Restart the producers without touching the panel | Both labels return to `displaying` without a Disconnect/Connect cycle | |

## Risks

The obvious over-correction is to make the state follow the socket so closely
that a momentary retry blanks the panel. `connecting` exists for that, and the
retained image must not move.

## Documentation impact

- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`: the paragraph on what the
  five states mean says `displaying` and `invalid` are claims about a live link.
  It should say what "live" is measured by.

## Completion evidence

Reserved for implementation evidence.

## Review findings

Reserved for review.

## Human approval

Required before review and completion.
