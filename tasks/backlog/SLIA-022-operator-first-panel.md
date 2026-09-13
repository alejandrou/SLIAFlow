---
id: SLIA-022
title: Six-panel operator surface with a capture button
status: backlog
branch:
priority: high
depends_on: SLIA-016, SLIA-023
required_skills: [slicer]
optional_tools: []
related_adrs: [ADR-0001]
---

# SLIA-022 - Six-panel operator surface with a capture button

# Blocked until ADR-0001 is accepted. The two decisions this card was previously blocked on are answered below.

## Goal

Replace the two-pane engineering console with the six-view operator surface the
WP5 demonstrator needs: a layer list with opacity, one honest statement of
connection state per link, a capture button, and a black panel with a written
reason wherever a producer does not exist yet.

## Context

Originally raised by the project owner after the `SLIA-014` session: too many
buttons and too many swaps for two obvious images, and some controls with no
evident purpose. Counted from
`extensions/SLIAFlow/SLIAFlow/Resources/UI/SLIAFlow.ui`: eight push buttons, two
combo boxes, two spin boxes and one check box - thirteen interactive controls -
alongside twenty-one labels, to put two images on screen.

`docs/architecture/WP5_MS5_DEMO_PLAN.md` widens this card. It is no longer only a
subtraction. The screen it has to produce is:

```
┌────────────────┬────────────────┬────────────────┐
│ LiveView       │ Stereoscopic   │ HS Cube        │
│ laptop camera  │ BLACK          │ band browser   │
│                │ "no producer"  │                │
├────────────────┼────────────────┼────────────────┤
│ Relative StO2  │ Enhanced       │ Tumour         │
│ BLACK          │ Vascularization│ Delineation    │
│ "no algorithm" │ UC2            │ UC1            │
└────────────────┴────────────────┴────────────────┘
```

Four of the six panels have a producer after `SLIA-023`, `SLIA-024` and
`SLIA-021`. Two are deliberately black, with their reason written on them and a
port reserved, so that the day UPM delivers depth and ULPGC delivers the
optical-parameter algorithm, a process is started on that port and the panel
lights up with no change inside `extensions/`.

There is also a structural reason this cannot wait. `SLIA-021` and `SLIA-024`
produce simultaneous layers over one capture - a classification, a vascular
enhancement and a background - and a single `Result map` combo box can only show
one thing at a time. The current control cannot express the product.

## The decisions this card was blocked on, now answered

**Does the laptop-camera path retire? No, and it keeps its own panel.** The
demonstrator's LiveView panel is the camera's panel, which is where the live view
sits on the real rig. `SLIA-009`'s camera-only demonstration keeps working. What
changes is that the camera path stops being five controls in the operator's way:
the index spin box and the OpenCV install button move to a developer or advanced
section, since neither is something an operator would recognise a reason for.

Note the constraint from `SLIA-023`: only one process can hold the laptop camera.
If the acquisition stand-in streams the webcam on `LiveView`, SLIAFlow's own
camera path must not also open it. The panel has one live source at a time and
says which.

**Do the two panes become one view with an overlay? Yes, but only over a
cube-derived background.** This is `ADR-0001`. The roadmap's recorded reason -
*"They are not overlaid because the laptop RGB image and HSI-derived maps are not
registered"* - was never "results must not be overlaid"; it was "results must not
be overlaid on an image they are not registered to". A background composed from
the same cube as the result is registered with it by construction. The laptop
camera never is, and never becomes an overlay background.

Orientation and the IJK-to-LPS mapping stay open and out of scope. `ADR-0001`
records why the overlay is internally consistent without that mapping being
defined: both images travel with the same identity matrix and LPS, so both are
rotated identically or not at all.

## Requirements

- Present six views in the layout above. Every view has a name on screen.
- Present the available layers as a list, with per-layer show, hide and opacity,
  rather than a selector that admits one map at a time. At least three layers can
  be present at once: `UC1_RGB`, `UC1_MV_CLASS` and `UC2_BV`.
- A panel with no producer is black and carries a written reason naming what is
  missing and which port is reserved for it. It is never empty, never a spinner,
  and never a placeholder image.
- Reduce connection controls to one statement of state per link. With seven
  channels, one control pair per link is not viable and one truthful state label
  per link is the requirement.
- Add a capture button that sends the trigger STRING on the control channel
  (18950) and reflects what the stand-in reports back: capturing, ready, or
  refused. This is the Slicer half of `SLIA-023`'s control channel: an outgoing
  text node on a third connector.
- The capture button is disabled when the control link is not connected, and says
  why.
- The HS Cube panel browses the received cube by band, with the band index and
  its wavelength shown.
- Every control that survives has a stated reason in its own tooltip that an
  operator would accept. A control whose reason is "an engineer needed it once"
  belongs in a developer section or nowhere.
- Preserve every safety behaviour without exception: the simulated banner, the
  transient never-persisted demo-mode opt-in, genuine-over-simulated precedence,
  provenance travelling with the data and never with the endpoint, and a black
  view with an explicit status when data is missing or invalid.
- Preserve the rule that SLIAFlow never creates a result. Neither the layer list
  nor the cube browser may compute anything.

## Out of scope

- Colour bar, capture selection and result saving. They are EPIC 4 items and each
  deserves its own card.
- Orientation and the IJK-to-LPS mapping.
- Any change to producers, to `tools/simulators/` or to the OpenIGTLink contract.
  This card consumes the channels `SLIA-023` opens; it does not define them.
- The UC1 overlay's own producer-side work, which is `SLIA-024`, and UC2's, which
  is `SLIA-021`. This card provides the panels they fill.
- Reworking `SLIA-009`'s runbook, which follows this rather than leading it.
- Opening the stereoscopic or StO2 ports. Reserved means reserved.

## Files allowed

- `extensions/SLIAFlow/SLIAFlow/Resources/UI/SLIAFlow.ui`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowParameterNode.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`
- `docs/architecture/WP5_MS5_DEMO_PLAN.md`
- `tasks/{backlog,active,review,completed}/SLIA-022-operator-first-panel.md`

## Relevant skills and references

- `docs/architecture/decisions/ADR-0001-overlay-result-on-cube-derived-rgb.md`
- `docs/architecture/WP5_MS5_DEMO_PLAN.md`, the target screen and the port table
- WP2 EPIC 4 and section 5.6 in
  `workspace/references/STRATUM_reunion_revision_v2.md`
- The SNS concept render in
  `workspace/references/STRATUM_WP2_Meeting_Ebatinca.pdf`
- `SLIA-004`, `SLIA-005`, `SLIA-006` and `SLIA-010` completion evidence, for what
  each control was added to do
- `SLIA-016`, which must land first: a panel with fewer, larger statements of
  state is worse than a cluttered one if those statements are wrong
- `.ai/policies/algorithm-boundary-policy.md`

## Approved dependencies

None.

## Implementation plan

1. Run the existing safety suite and record it. It is re-run unmodified at the
   end; no existing safety test may be edited by this card.
2. Count the interactive controls before touching anything.
3. Build the six-view layout with all six panels black and their reasons written,
   before any producer is wired in. A panel that is black for the right reason is
   the deliverable's baseline state.
4. Add the layer list with show, hide and opacity.
5. Add the control connector and the capture button.
6. Add the cube band browser.
7. Re-count the controls and re-run the safety suite unmodified.

## Acceptance criteria

- Six named views in the stated layout, with the two producerless panels black
  and carrying their written reason and reserved port.
- Three layers can be present at once and each can be shown, hidden and faded
  independently of the others.
- One truthful state label per link, with `SLIA-016`'s fix in place beneath it.
- The capture button sends the trigger, reflects the stand-in's answer, and is
  disabled with a reason when the control link is down.
- The HS Cube panel browses bands and shows each band's wavelength.
- The interactive control count in the operator section is materially reduced,
  and the count before and after is recorded.
- Every surviving control has a stated operator-facing reason.
- Every safety behaviour passes the same tests it passes today, unmodified.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| Simulated banner still displayed for simulated data | existing `SLIAFlowTest` banner tests, unmodified | automated |
| Demo mode still transient and never persisted | existing `SLIAFlowTest` demo-mode tests, unmodified | automated |
| Genuine still takes precedence over simulated | existing `SLIAFlowTest` precedence tests, unmodified | automated |
| Invalid or missing data still yields a black view and a status | existing `SLIAFlowTest` validation tests, unmodified | automated |
| A producerless panel is black with its reason | `SLIAFlowTest.test_reservedPanelIsBlackWithStatedReason` | automated |
| Three layers coexist and fade independently | `SLIAFlowTest.test_threeLayersAreIndependentlyControlled` | automated |
| The capture button is disabled without a control link | `SLIAFlowTest.test_captureDisabledWithoutControlLink` | automated |
| The capture button sends one trigger per press | `SLIAFlowTest.test_capturePressSendsOneTrigger` | automated |
| The band browser reports the right wavelength | `SLIAFlowTest.test_bandBrowserReportsWavelength` | automated |
| Control count reduced | Manual step 1 | manual |
| The six-panel screen reads correctly | Manual step 2 | manual |
| Two results shown at once over one background | Manual step 3 | manual |

Tests to add or change, and how each one will be shown to fail first:

- `test_threeLayersAreIndependentlyControlled` is written against the current
  single-selector widget and shown failing, because the current control cannot
  hold more than one result.
- `test_reservedPanelIsBlackWithStatedReason` is shown failing while no such
  panel exists, then again against a first implementation that leaves the panel
  black but says nothing.
- No existing safety test may be modified by this card. If one needs modifying,
  that is the signal that a guard is being changed and the card stops.

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Count interactive controls in the operator section before and after | The count is materially lower and every survivor has a stated reason | |
| 2 | Open the module with no producer running | Six named panels, all black, the two reserved ones naming what is missing and which port waits for it | |
| 3 | Run a full session with UC1 and UC2 producing | Both results are present over one background; each can be shown, hidden and faded without disturbing the other | |
| 4 | Press capture with the control link down, then up | Disabled with a reason, then sends the trigger and reflects capturing and ready | |
| 5 | Browse the HS Cube panel across its bands | The index and wavelength move together and match the header | |
| 6 | Kill every producer and refresh | Every state label reports disconnected; no panel claims to be displaying | |

## Risks

The largest risk is that simplification removes a guard. Controls in this panel
are not decoration: the demo-mode check box is a safety interlock, and the result
status is the only place an operator learns that what they are looking at is
stale. The rule that no existing safety test may be modified exists to make that
failure loud.

The second risk is doing this before `SLIA-016`. A panel with fewer, larger
statements of state concentrates a known lie into a more prominent place, and
today a link reports `displaying` over a dead socket. It is a hard dependency.

The third is scope. Every EPIC 4 item is tempting to add while the panel is open.
Colour bar, capture selection and saving are deliberately excluded, and adding
them here would turn a subtraction into an expansion - which this card has
already partly become by absorbing the six-view layout and the capture button.

The fourth is the reserved panels. A black panel with a reason is a promise about
what is missing; a black panel that is black because something broke is a defect.
The two must never look the same, which is why the reason is a tested
requirement rather than a label.

## Documentation impact

- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`: the user-visible
  behaviour section, the six-view layout, and the overlay rationale pointing at
  `ADR-0001`.
- `docs/architecture/WP5_MS5_DEMO_PLAN.md`: mark the target screen delivered.

## Completion evidence

Reserved.

## Review findings

Reserved for review.

## Human approval

Required before activation, because `ADR-0001` must be accepted first, and again
before completion.
