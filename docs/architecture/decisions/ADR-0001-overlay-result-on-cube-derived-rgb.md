---
id: ADR-0001
title: Overlay algorithm results on a cube-derived RGB, never on the laptop camera
status: accepted
date: 2026-09-11
accepted: 2026-09-15
related_tasks: SLIA-022, SLIA-024, SLIA-021
supersedes:
superseded_in_part_by: ADR-0002
---

# ADR-0001 - Overlay algorithm results on a cube-derived RGB, never on the laptop camera

## Status

Accepted by the project owner on 2026-09-15, when activating `SLIA-022`.

Proposed on 2026-09-11. Accepting it unblocked `SLIA-022` and `SLIA-024`.

Superseded in part by `ADR-0002`, accepted 2026-09-16: the side-by-side
presentation in rule 4 and the first Validation bullet. Every other rule stands.

Applied at acceptance: rule 3 is why a result is composited only over a
background from its own producer. `UC2_BV` therefore has its own panel and is
never drawn over `UC1_RGB`, which comes from a different producer on a
different connection.

## Context

`docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md` records a decision in its
user-visible behaviour section:

> The live and result images are placed in separate views. They are not overlaid
> because the laptop RGB image and HSI-derived maps are not registered.

That was correct when it was written. The live pane showed the laptop camera,
which points at whatever is in front of the laptop, and an HSI-derived class map
computed from an unrelated cube. Overlaying those two would place a tumour class
over a coffee mug. Keeping them apart was the only honest option.

WP2's EPIC 4 asks for the opposite shape: a background RGB image, the algorithm
result as a foreground layer, an opacity control, and pixel-to-pixel alignment as
an acceptance criterion. The deliverable's own reference images show a result
composited over the surgical field, not beside it. `SLIA-022` records that the
conflict cannot be resolved by an implementer and needs an ADR, and that section
5.6 of the meeting review - images arriving rotated with no defined IJK-to-LPS
mapping - has to be settled alongside it.

The WP5 demonstrator plan (`docs/architecture/WP5_MS5_DEMO_PLAN.md`) supplies the
missing piece. UC1 and UC2 both consume one hyperspectral cube, and that cube
contains the bands needed to compose a colour photograph of the same field:
710 nm, 540 nm and 480 nm, which land on exact grid points of the recorded
data's 440-900 nm / 5 nm grid. A background composed from the same cube as the
result is registered with it **by construction** - same sensor, same capture,
same array indices - rather than by a registration step that could be wrong.

So the original reason to forbid overlay has not weakened; it has become
specific. It was never "results must not be overlaid". It was "results must not
be overlaid on an image they are not registered to", and the laptop camera is
exactly such an image.

## Decision

1. An algorithm result may be displayed as a foreground layer with an opacity
   control **only** over a background derived from the same hyperspectral cube
   the result was computed from.
2. The laptop camera image is never a background for an algorithm result. It
   keeps its own panel, which is where it sits on the real rig.
3. The cube-derived background is produced by the same producer that produces
   the result, sent on the same connection, so that "same capture" is a property
   of the transport rather than an assumption. For UC1 this is `UC1_RGB` beside
   `UC1_MV_CLASS` on port 18945.
4. SLIAFlow performs no registration, resampling or alignment. Its only
   safeguard is a size comparison: if background and result do not have the same
   dimensions, they are **not** composited and are shown side by side with an
   explicit status. SLIAFlow does not attempt to make two mismatched images
   agree.
   *(The side-by-side presentation is superseded by `ADR-0002`: the map is
   shown alone with an explicit status. The rest of this rule stands.)*
5. Orientation is out of this decision's scope and stays as it is. Both images
   travel with the identity `ijk_to_world_matrix` and LPS that
   `igtl_transport.buildImageMessage` already sends, so both are rotated
   identically or not at all, and the overlay is internally consistent whichever
   it turns out to be. A defined IJK-to-LPS mapping remains open and needs its
   own investigation.

## Rationale

The alignment claim has to be structural, because a viewer cannot check it.
Someone looking at a class map over a cortical surface has no way to tell a
one-pixel offset from a correct result, and no way to tell a correct result from
one composited over the wrong capture entirely. Deriving the background from the
same array the algorithm read removes the question instead of answering it: there
is no transform to get wrong and no capture to confuse.

Rule 3 is what keeps that true over the wire. Two producers on two ports could
each be correct and still be one capture apart, and the only thing that would
reveal it is a visual mismatch nobody can reliably see. One producer sending both
from one cube cannot be one capture apart.

Rule 4 is deliberately weak. The tempting version of this safeguard is to resample
the result onto the background so a mismatch is repaired rather than refused. That
would put a geometric transform inside SLIAFlow, which the roadmap's safety
boundary forbids for good reason: a module that can move a result's pixels is a
module that can move a tumour boundary. Refusing to composite is the honest
failure.

## Alternatives considered

**Keep the two panes separate, as today.** Costs MS5 point 2, which asks for UC1
results *over* RGB, and leaves the deliverable's reference layout unreachable. The
reason for the original decision no longer applies to a cube-derived background,
so keeping it would be preserving the letter of a decision against its own
rationale.

**Overlay on the laptop camera anyway, with a warning.** Rejected outright. The
camera sees a different scene, and a warning is not a defence against an image
that looks correct. This is the one arrangement that could paint a class over
anatomy it was never computed from.

**Let SLIAFlow register the two images.** Rejected. It moves a geometric
transform into a module whose whole design rests on never creating or altering a
result, and it would be solving a problem that rule 3 prevents from existing.

**Send the background from the acquisition stand-in on the cube channel
(18947).** Workable and cheaper in one sense - the cube is already there - but it
puts background and result on two connections from two processes, which is
exactly the arrangement rule 3 exists to avoid. It also makes the size check
load-bearing rather than a backstop.

**Composite outside SLIAFlow and send one pre-blended image.** Rejected. Opacity
stops being adjustable, the result stops being separable from its background, and
a blended image cannot be validated as a class map at all.

## Consequences

- The roadmap's "not overlaid because not registered" paragraph is superseded and
  must be rewritten to state the narrower rule, pointing here.
- `SLIA-022`'s second open decision is answered: the panes become layered views
  with opacity, but only over a cube-derived background. Its first decision - does
  the laptop camera path retire - is answered separately and independently: it
  does not, it keeps its own panel.
- `SLIA-024` gains the `UC1_RGB` device name, which must be added to the
  OpenIGTLink contract table with its component count and data type.
- UC2's result is a per-image-normalized RGB (see `SLIA-021`), so it is a
  foreground layer whose colours are not comparable between captures. That is a
  property of the algorithm's output, not of this decision, and it is on the
  partner request list.
- A result whose background is absent is displayed alone, with its banner, exactly
  as it is today. The overlay is an addition, not a precondition for display.
- Every safety behaviour is unchanged: the simulated banner, the transient
  demo-mode opt-in, genuine-over-simulated precedence, provenance travelling with
  the data, and a black view with an explicit status for missing or invalid data.

## Validation

- An automated test asserts that a result and a background of different
  dimensions are not composited and produce the side-by-side presentation with an
  explicit status. *(Superseded by `ADR-0002`: the test asserts that the map is
  displayed alone and the status names both sizes.)*
- An automated test asserts that the laptop camera node is never accepted as an
  overlay background for any result role.
- An automated test asserts that the existing banner, demo-mode and precedence
  tests pass unmodified with an overlay present.
- Manual verification shows a UC1 class map over its cube-derived RGB at varying
  opacity, and confirms by eye that structures in the map follow structures in
  the background.

## Related tasks

- `SLIA-022` - the panel that hosts the layered views and the opacity control.
- `SLIA-024` - UC1's result over its cube-derived RGB; the first consumer.
- `SLIA-021` - UC2's result as a second simultaneous layer.

## Superseded ADRs

None. This is the first ADR in the repository. It supersedes a decision recorded
in prose in `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md` rather than a
previous ADR.
