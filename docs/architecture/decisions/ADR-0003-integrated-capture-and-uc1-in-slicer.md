---
id: ADR-0003
title: Run capture and UC1 inside Slicer, and show its outputs standalone
status: accepted
date: 2026-09-17
accepted: 2026-09-17
amended: 2026-09-18 (decision 3, ground-truth label overlay)
related_tasks: SLIA-027, SLIA-028, SLIA-029, SLIA-030, SLIA-021
supersedes: ADR-0001 (rules 1-3, demo-mode opt-in, genuine-over-simulated precedence), ADR-0002 (in full)
superseded_in_part_by: ADR-0004
---

# ADR-0003 - Run capture and UC1 inside Slicer, and show its outputs standalone

## Status

Accepted by the project owner on 2026-09-17, during the specification of
`SLIA-027`.

Superseded in part by `ADR-0004` on 2026-09-24, accepted during the
specification of `SLIA-031`: the case pool of decision 1, decision 2 for
external acquisition, and the input validation of decision 5. The rest stands.

Proposed the same day, from decisions the project owner made after a
Slicer-skill review of the task's first draft.

Amended on 2026-09-18 by the project owner, during `SLIA-027`. Decision 3 said
outputs are shown with nothing composited under or over them; the owner then
asked for the recorded case's own ground truth to be drawn over the chosen
output. The amendment is written into decision 3 below rather than into a new
ADR, at the owner's instruction. Nothing else in this ADR changes.

Applied at acceptance: `ADR-0001`'s front matter gained
`superseded_in_part_by: ADR-0002, ADR-0003` and `ADR-0002`'s gained
`superseded_by: ADR-0003`, each with a line in its Status section. Their bodies
are not rewritten.

## Context

Until now the operator workflow has been split across processes. SLIAFlow is a
set of OpenIGTLink clients. A PowerShell session starts Python producers: an
acquisition stand-in that serves LiveView, the HS cube and a control channel,
and a UC1 runner that runs the vendored GPU pipeline and serves its
majority-voting map with a cube-derived colour background. The decisions that
govern this were made for that shape:

- `ADR-0001` allows a result to be composited only over a background derived
  from its own cube, sent by the same producer on the same connection
  (rules 1-3). It keeps the transient demo-mode opt-in and genuine-over-simulated
  precedence as safety behaviours.
- `ADR-0002` makes "same capture" checkable in the scene with a mandatory
  `SLIAFlow.CaptureId`, because OpenIGTLinkIF keeps every metadata key a node
  ever received.
- `SLIA-026` recorded that SLIAFlow does not start producer processes.

The owner wants the built application, `SlicerWithSLIAFlow.exe`, to run the whole
workflow by itself: Start, Capture, a recorded case chosen from a pool, the UC1
executable run in the background, and the results shown, with no console windows
and no external commands.

A review of an earlier draft that kept OpenIGTLink by having Slicer serve links
to itself found that this cannot carry provenance:
`vtkMRMLIGTLConnectorNode::PushNode` clears message metadata and sends only
`MRMLNodeName` and `Status`, so `SLIAFlow.CaptureId`, `SLIAFlow.OutputFile` and
`SLIAFlow.DataOrigin` would not travel. With producer and consumer in one
process, there is also nothing for a network to connect.

The vendored pipeline's intermediate build writes five usable per-stage images
of the case it classified: `pca.bmp`, `svm.bmp`, `knn.bmp`, `kmeans.bmp` and
`imageRGB.bmp`. A sixth, `CalibratedImage_BIP.bmp`, is written without BMP row
padding by `saveBIPtoBMP` and is malformed for any width that is not a multiple
of 4.

## Decision

1. **SLIAFlow runs the capture and UC1 itself.** On Capture it freezes LiveView,
   saves the displayed laptop-camera frame, picks a compatible recorded case,
   and starts the prebuilt `stratum.opt.intermediate.exe` on that case as a
   background `QProcess` with no shell. SLIAFlow owns that process: it applies a
   timeout, and it kills the process and releases the build lock on scene close,
   module exit and shutdown. This supersedes `SLIA-026`'s rule that SLIAFlow
   does not start producer processes.
2. **No OpenIGTLink in the operator workflow.** SLIAFlow creates no connector,
   looks up no received node and reads no `OpenIGTLink.*` attribute. Results are
   module-owned nodes tagged directly. Links return, for external hardware or
   UC2, in their own decision (`SLIA-030`).
3. **Outputs are shown standalone, but for the case's own ground truth.**
   The five valid per-stage images are selectable in the Tumour Delineation
   panel, one at a time, with no image composited under or over them and no
   opacity control on the background or foreground layers. There is no
   cube-derived background. This supersedes `ADR-0001` rules 1-3 and `ADR-0002`
   in full. What remains of `ADR-0001` rule 2 is kept as a plain statement:
   the laptop camera image stays in its own panel and is never drawn with a
   result.

   *Amended 2026-09-18.* One overlay is allowed: the recorded case's own
   `gtMap`, on Slicer's Label layer, over the output chosen last. This does not
   reopen what rules 1-3 guarded. That guard was against a result composited
   over an image from **another** capture. The ground truth is read from the
   same recorded case folder UC1 classified, carries that run's
   `SLIAFlow.CaptureId`, and the module refuses to lay it over a result whose
   ID differs. It is labels rather than an image, so what the operator sees is
   a comparison against a stated legend rather than a blend of two pictures,
   and the Label layer's own opacity and outline controls are what work it.
   The rest of the rule stands: no foreground image, no cube-derived
   background, no opacity control on the background or foreground layers, and
   nothing composited on the HS Cube panel.
4. **No demo-mode opt-in and no origin precedence.** Every result SLIAFlow can
   show comes from its own run on a recorded case, so every result is
   `simulated` and there is nothing genuine for it to be preferred against. The
   demo-mode checkbox, its gate, and the simulated banners are removed. This
   supersedes those safety behaviours as listed in `ADR-0001`'s Consequences.
5. **What stays mandatory.**
   - *Provenance.* Every output node carries `SLIAFlow.DataOrigin = simulated`,
     `SLIAFlow.RecordedCase`, `SLIAFlow.OutputFile`, `SLIAFlow.CaptureId` and a
     `SLIAFlow.SimulationDetail` that names the recorded case and says the
     acquisition was simulated. The result status reads
     `Recorded case <case> - simulated acquisition`.
   - *One capture ID per run.* Every Capture makes a new opaque ID, shared by the
     five outputs of that run and never reused (`ADR-0002` rule 2, kept in
     substance).
   - *Input validation.* A case runs only if it is an identified recorded case
     whose headers and data files agree and whose band count matches the staged
     SVM model. Deferred cases are never picked.
   - *Output validation.* The five outputs are accepted together or not at all.
     Each must be newer than the run start, a well-formed uncompressed 24-bit
     padded BMP, and the case's `samples x lines`. A failed run leaves the
     previous accepted result on screen, marked as not from the current capture.
   - *No alteration of algorithm pixels.* SLIAFlow decodes the BMP losslessly
     (bottom-up rows reversed, BGR to RGB) and displays it with fixed upright
     directions. It does not resample, register, recolour, threshold or
     interpret an output.
   - *Non-clinical status.* The "Prototype only - not clinically validated"
     notice stays at the top of the module. Nothing SLIAFlow shows is a clinical
     result.

## Rationale

The previous decisions protected against two failure modes that a separate
producer created: a result composited over an image from another capture, and a
simulated result mistaken for a genuine one. Neither can arise in this workflow.

A composite needs two images; this workflow shows one. Once nothing is
composited, a background's capture identity has nothing to guard, and the
guards in `ADR-0001` rules 1-3 and `ADR-0002` protect a path that no longer
exists. Keeping them would keep hundreds of lines of code and tests that can
never be exercised.

Demo mode and precedence existed because a genuine producer and a simulated one
could both feed the same pane. When SLIAFlow is the only producer, and it only
ever runs recorded cases, the opt-in would be a checkbox the operator must tick
before the application can do the one thing it is for. The protection that
matters - that the viewer knows what they are looking at - moves to provenance
on every node and to status text that names the case.

Running the process in Slicer rather than behind a network is what makes
provenance reliable again: the tags are set by the same code that validated the
files, instead of travelling through a connector that drops them.

The validation boundary does not weaken. It moves from "is this node what it
claims to be" to "did this run produce these five files, correctly formed, just
now", which is checkable against the file system and the case headers.

## Alternatives considered

**Keep OpenIGTLink and have Slicer serve links to itself.** Rejected: `PushNode`
does not carry the metadata provenance depends on, and a loopback link adds
failure modes with no benefit.

**Keep the Python producers and start them from Slicer.** Rejected: it keeps two
processes, ports and a network contract to show a result the module could read
from disk, and it still needs a Python environment outside Slicer.

**Keep compositing `imageRGB.bmp` over a cube-derived background.** Rejected for
this workflow: the background would be computed by SLIAFlow from the cube, which
puts cube processing inside the module and brings back the capture-identity
problem for no display the owner asked for.

**Show `CalibratedImage_BIP.bmp` too.** Rejected: it is malformed for common case
widths. Decoding it anyway would mean repairing a file the pipeline wrote wrong.

**Keep demo mode as a no-op checkbox.** Rejected: a control that changes nothing
teaches the operator that safety controls are decorative.

## Consequences

- The module's OpenIGTLink reception, link panel, link waiting text, control
  channel, UC2 reception, HS cube band browser, layer table, background
  compositing, demo mode and banners are removed, with their tests.
- The Enhanced Vascularization panel is black with a stated reason, like the
  other reserved panels. UC2 has no producer yet (`SLIA-021`). The HS Cube
  panel is no longer reserved: it shows the recorded cube the capture stands
  for, band by band, as soon as the case is chosen.
- The ground-truth overlay of the 2026-09-18 amendment lives on the Tumour
  Delineation panel's Label layer and nowhere else. The HS Cube panel keeps no
  label layer: its bands run along S, so a one-band label map placed in that
  stack would be off the plane the operator scrolls and would draw nothing
  while the status text claimed a comparison.
- `build-uc1.ps1` builds the intermediate binary beside the release one.
- `tools/simulators` and the session scripts no longer serve the operator
  workflow. Their retirement is `SLIA-028`. Until then they share the staged
  build's output folder, and the build lock is the only protection against
  running both at once.
- The largest case, `058-02`, is deferred until `SLIA-029` verifies it.
- The OpenIGTLink image contract no longer describes the operator workflow. Its
  documents say so and point here.
- `.ai/policies/medical-data-policy.md` refers to the demo-mode interlock as a
  protection; that wording needs a follow-up edit. Its rule that a detail must
  name the recorded case still holds and is enforced.

## Validation

- Automated tests assert that the panel has no link, demo-mode, layer or class
  controls and that the result selector lists exactly the five output names.
- Automated tests assert that case selection excludes deferred and incompatible
  cases, never repeats before the pool is exhausted, and writes nothing under
  `input/`.
- Automated tests assert that the UC1 process is started without a shell with
  the expected program, argument and working directory, that it is refused
  without an intact build, a free lock or short enough paths, and that a
  timeout, nonzero exit or crash is a failure.
- Automated tests assert that each output is refused when missing, stale,
  malformed, unpadded or the wrong size, and that results are accepted only when
  all five validate.
- Automated tests assert that a displayed output is pixel-identical to the
  decoded file, upright and unmirrored, and carries the shared capture ID and
  every provenance attribute in decision 5.
- Automated tests assert the ground-truth overlay of the 2026-09-18 amendment
  where it is read: that choosing `gtMap` binds it to the Tumour Delineation
  composite node's Label layer at the stated opacity while the chosen output
  stays on the background layer, that deselecting it clears that layer, and
  that the HS Cube panel carries no label layer whatever the selection.
- Automated tests assert that the chosen case is re-read immediately before the
  run and the run refused, not moved to another case, if the folder changed;
  that a build lock whose PID cannot be written is removed rather than left
  unowned; and that an output check failing in a way the checks did not foresee
  is still reported as a failed run rather than leaving the module capturing.
- Manual verification shows a full run from `SlicerWithSLIAFlow.exe` with no
  console window, a failure that keeps the previous result marked stale, and a
  clean shutdown during a run.

## Related tasks

- `SLIA-027` - implements this decision.
- `SLIA-028` - retires the standalone producers and session scripts.
- `SLIA-029` - verifies the largest case before it leaves the deferred list.
- `SLIA-030` - reintroduces OpenIGTLink links for external hardware or UC2.
- `SLIA-021` - the UC2 producer.

## Superseded ADRs

- `ADR-0001`, in part: rules 1-3; the demo-mode opt-in and genuine-over-simulated
  precedence listed under Consequences; the Validation bullets that test the
  overlay, banner, demo-mode and precedence behaviours. Rule 2's substance - the
  laptop camera never drawn with a result - is restated in decision 3. Rule 5
  (orientation out of scope) was already settled for the camera by `SLIA-026`
  and is not restated.
- `ADR-0002`, in full. Its identity rule (one opaque ID per classification,
  never reused) is kept in substance by decision 5.
