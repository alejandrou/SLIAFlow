---
id: SLIA-024
title: Show the UC1 result over a colour image derived from its own cube
status: backlog
branch:
priority: high
depends_on: SLIA-016, SLIA-022, SLIA-023
required_skills: [slicer]
optional_tools: []
related_adrs: [ADR-0001]
---

# SLIA-024 - Show the UC1 result over a colour image derived from its own cube

# Blocked until ADR-0001 is accepted. See "Approval this needs" below.

## Goal

Close the demonstration loop: camera, capture, cube, UC1, result on screen, with
the class map composited over a colour photograph of the same surgical field
taken from the same cube. This is MS5 point 2.

## Context

Workstream C of `docs/architecture/WP5_MS5_DEMO_PLAN.md`.

UC1 already runs on an announced folder and publishes `UC1_MV_CLASS` on port
18945. `SLIA-023` changes where the cube comes from and nothing else about that
path. What is missing is the background the result is meant to be seen against.

The recorded cases carry a wavelength grid of 440 to 900 nm in 5 nm steps, so
710 nm, 540 nm and 480 nm land on exact grid points - band indices 54, 20 and 8.
Those three bands compose a colour photograph of the field. Because it comes from
the same cube as the map, it agrees with the map pixel for pixel by construction:
same sensor, same capture, same array indices, no registration step that could be
wrong.

The background is never the laptop camera. The camera points somewhere else, and
compositing there would paint a tumour class over whatever is in front of the
laptop. The camera keeps its own LiveView panel, which is where it sits on the
real rig. That distinction is the whole content of `ADR-0001`.

### Why `UC1_RGB` shares port 18945

The plan's port table gave the pseudo-RGB no port, and it needs a transport.
Sending it as a second device name on the UC1 runner's existing connection makes
"same capture" a property of the transport rather than an assumption: one
producer, one cube, one connection, two device names. Two producers on two ports
could each be correct and still be one capture apart, and nothing on screen would
reveal it. It also avoids an eighth port and avoids multiplying the
one-client-at-a-time transport limit recorded in `SLIA-018`.

### What this card inherits and does not fix

UC1 computes five maps and writes one. The other four are discarded because the
write is commented out at `main.cu:164-174`. That is a partner's code; it is on
the request list, the contract already admits all five, and nothing here changes
when they arrive.

## Approval this needs

`ADR-0001` reverses a decision recorded in
`docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md` - *"They are not overlaid
because the laptop RGB image and HSI-derived maps are not registered"* - and
narrows it to forbid overlay on an unregistered background while permitting it on
a cube-derived one. This card must not be activated until that ADR is accepted.
Nothing else about this card is open.

## Requirements

### The producer side

- The UC1 runner composes a three-band colour image from the cube it just
  classified and sends it as device `UC1_RGB` on the same connection as
  `UC1_MV_CLASS`, in the same cycle.
- The three bands are selected **by wavelength** against the header's own
  wavelength list - 710, 540 and 480 nm - and the runner refuses rather than
  guesses when the header carries no wavelengths or when the nearest band misses
  its target by more than a stated tolerance.
- Each run reports which band index every requested wavelength resolved to and by
  how much it missed.
- `UC1_RGB` carries the same provenance as the map it accompanies: origin
  `simulated`, and the simulation detail `SLIA-023` gives the case.
- The composition is a plain three-band assembly with a stated, fixed scaling. It
  is a viewing aid, not a colour-accurate rendering, and the module docstring
  says so.

### The consumer side

- The delineation panel composites `UC1_MV_CLASS` as a foreground layer over
  `UC1_RGB`, with an opacity control.
- **The only safeguard is a size comparison.** If the two images do not have the
  same dimensions they are not composited; they are shown side by side with an
  explicit status. SLIAFlow performs no registration, resampling or alignment.
- A result whose background has not arrived is displayed alone with its banner,
  exactly as today. The overlay is an addition, never a precondition for display.
- The laptop camera node is never accepted as an overlay background for any
  result role.
- Every safety behaviour is preserved without exception: the simulated banner,
  the transient never-persisted demo-mode opt-in, genuine-over-simulated
  precedence, provenance travelling with the data and never with the endpoint,
  and a black view with an explicit status for missing or invalid data.
- `UC1_RGB` is added to the OpenIGTLink contract table with its component count
  and data type.

## Out of scope

- Any change to UC1, UC2 or `AcquisitionSystemApp` in any copy.
- The four maps UC1 discards.
- Registration, resampling, orientation and the IJK-to-LPS mapping. `ADR-0001`
  records why orientation is consistent without being defined, and leaves the
  definition to its own investigation.
- UC2's layer, which is `SLIA-021`.
- The six-panel layout itself, which is `SLIA-022`. This card fills one of its
  panels.
- Colour bar, capture selection and result saving.
- Any metric computed against `gtMap`.

## Files allowed

- `tools/simulators/stratum_sim/uc1_runner.py`
- `tools/simulators/stratum_sim/contract.py`
- `tools/simulators/tests/test_uc1_runner.py`
- `tools/simulators/tests/test_contract.py`
- `tools/simulators/README.md`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `extensions/SLIAFlow/SLIAFlow/Resources/UI/SLIAFlow.ui`
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`
- `docs/architecture/WP5_MS5_DEMO_PLAN.md`
- `tasks/{backlog,active,review,completed}/SLIA-024-uc1-result-over-cube-derived-rgb.md`

## Relevant skills and references

- `docs/architecture/decisions/ADR-0001-overlay-result-on-cube-derived-rgb.md`
- `docs/architecture/WP5_MS5_DEMO_PLAN.md`, workstream C
- `tools/simulators/stratum_sim/uc1_runner.py`, `mapMessages` and
  `simulationDetailForDataset`
- `.ai/policies/algorithm-boundary-policy.md`
- WP2 EPIC 4, for what the layered view is asked to offer

## Approved dependencies

None.

## Implementation plan

1. Write the wavelength resolver and its two refusal cases first, against a
   header with no wavelengths and a header whose nearest band misses.
2. Send `UC1_RGB` beside the map and prove both carry the same provenance and
   arrive in the same cycle.
3. Write the size-mismatch test on the consumer side and show it failing.
4. Add the layered presentation and the opacity control.
5. Re-run the whole existing SLIAFlow safety suite unmodified.

## Acceptance criteria

- The runner sends `UC1_RGB` and `UC1_MV_CLASS` from the same cube in one cycle,
  with identical provenance.
- Bands are resolved by wavelength, the resolution is reported, and a header
  without wavelengths is refused rather than defaulted.
- A class map is composited over its cube-derived background with a working
  opacity control.
- Two images of different dimensions are not composited and produce an explicit
  status.
- The laptop camera is never used as an overlay background.
- Every existing safety test passes unmodified.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| Bands resolve to the nearest by wavelength | `test_uc1_runner.test_resolves_rgb_bands_by_wavelength` | automated |
| A header without wavelengths is refused | `test_uc1_runner.test_refuses_rgb_without_wavelengths` | automated |
| A band too far from target is refused | `test_uc1_runner.test_refuses_when_nearest_rgb_band_exceeds_tolerance` | automated |
| Map and background share provenance and cycle | `test_uc1_runner.test_rgb_accompanies_map_with_same_provenance` | automated |
| Mismatched sizes are not composited | `SLIAFlowTest.test_mismatchedBackgroundIsNotComposited` | automated |
| The camera is never an overlay background | `SLIAFlowTest.test_cameraNodeIsNeverAnOverlayBackground` | automated |
| Banner, demo mode, precedence, black view | existing `SLIAFlowTest` safety tests, unmodified | automated |
| The overlay reads correctly by eye | Manual step 1 | manual |
| Opacity works across its range | Manual step 2 | manual |
| A missing background still shows the result | Manual step 3 | manual |

Tests to add or change, and how each one will be shown to fail first:

- `test_mismatchedBackgroundIsNotComposited` is written before the size check
  exists and shown compositing two differently sized images, so the check is
  demonstrated to be the thing that stops it.
- `test_cameraNodeIsNeverAnOverlayBackground` is shown failing against a first
  implementation that accepts any RGB volume as a background.
- No existing safety test may be modified by this card. If one needs modifying,
  that is the signal that a guard is being changed and the card stops.

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Run a full session on a recorded case and look at the delineation panel | The class map sits over a recognisable colour image of the same field; structures in the map follow structures in the background | |
| 2 | Move the opacity control from 0 to 100 per cent | The background is visible alone at one end, the map alone at the other, and every intermediate value is stable | |
| 3 | Stop the runner before a background arrives, then connect | The result is displayed alone under its banner, with no empty or black overlay layer | |
| 4 | Confirm the banner is present in every state of steps 1 to 3 | The simulated banner is on screen throughout; no screenshot is taken of a result without it | |

## Risks

The overlay is the one feature in this project that can place a class label over
anatomy it was not computed from, and a wrong overlay looks exactly like a right
one. Every defence is structural rather than visual: the background comes from the
same producer, the same cube and the same connection as the map, and the only
run-time check is a refusal to composite mismatched sizes. The tempting
improvement - resample the result onto the background so a mismatch is repaired
rather than refused - would put a geometric transform inside a module whose whole
design rests on never altering a result, and is forbidden by `ADR-0001`.

A background that makes the scene look convincing raises the stakes on the
provenance markers rather than lowering them, in exactly the way `SLIA-020`
records for the phantom. The banner tests are re-run unmodified for that reason.

The pseudo-RGB is a three-band assembly, not a colour-accurate rendering. If it
is described as "the RGB image" anywhere in the panel or the documentation, a
viewer may take it for the microscope's own view, which it is not.

## Documentation impact

- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`: `UC1_RGB` in the
  contract table; the user-visible behaviour section rewritten to state the
  narrowed overlay rule and point at `ADR-0001`.
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`: the background layer, the
  size check and what is not done.
- `tools/simulators/README.md`: the `UC1_RGB` device, its band selection and its
  refusals.
- `docs/architecture/WP5_MS5_DEMO_PLAN.md`: mark workstream C done.

## Completion evidence

Reserved.

## Review findings

Reserved for review.

## Human approval

Required before activation, because `ADR-0001` must be accepted first, and again
before completion.
