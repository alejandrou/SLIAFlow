---
id: ADR-0007
title: Show UC1's tumour class over the colour preview of its own cube
status: proposed
date: 2026-10-09
related_tasks: SLIA-042
supersedes: on acceptance, ADR-0003 (decision 3 for the class outputs on Tumour Delineation; decision 5, narrowed to one exact colour decode)
---

# ADR-0007 - Show UC1's tumour class over the colour preview of its own cube

## Status

Proposed on 2026-10-09 at the project owner's request ("Do all"), from the
project audit of 2026-10-09 and the review of it. Not accepted: until the owner
accepts it, `ADR-0003` decision 3 stands and every output is shown on its own.

Before acceptance, the owner confirms with UNIPV, which the RP2 roadmap names
first for every GUI item, and ULPGC, which it names first for UC1's probability
display, that this display belongs in SLIAFlow and does not duplicate their
work.

## Context

`ADR-0001` (accepted 2026-09-15) allowed a result over a background derived
from the same cube, because such a background is registered with the result by
construction. `ADR-0003` (2026-09-17) withdrew that for the in-Slicer workflow:
"the background would be computed by SLIAFlow from the cube, which puts cube
processing inside the module and brings back the capture-identity problem for
no display the owner asked for." Each of those three reasons has changed:

- **Cube processing in the module.** HS Cube's colour preview (`SLIA-032`)
  already composes the bands nearest 650, 550 and 470 nm on one fixed scale,
  in the module, and says it is a band composite, not a photograph.
- **Capture identity.** Every Capture makes one ID that its outputs carry, and
  a result not from the current capture is marked as previous (`ADR-0003`
  decision 5, `SLIA-040`).
- **Asked for.** The meeting reviewed in
  `workspace/references/STRATUM_reunion_revision_v2.md` (line 570) describes the
  brain image as background, the probability map over it and a colour bar. The
  WP2 meeting deck shows tumour delineation over anatomy with a scale (page 11).
  The RP2 roadmap lists "brain tumour probability maps overlayed on RGB" for
  the EC demonstration of February 2027 (page 11) and UC1's probability display
  for that of November 2026 (page 9).

What UC1 writes today is five BMPs. `svm.bmp`, `knn.bmp` and `imageRGB.bmp`
paint each pixel with its class in the pipeline's palette
(`SLIAFLOW_UC1_IMAGE_CONTRACT.md`): green normal, red tumour, blue
hypervascularized, black background, and white for a pixel `svm.bmp` and
`knn.bmp` leave unlabelled. No number is exported: the SVM's per-class
estimates exist in `functions_cuda.cu` (`dev_prob_estimates_ord`), but their
export is commented out.

The model was trained on another camera (`ADR-0004` decision 5). On
`S-N-002-04` the SVM labels 35.4 % of the image tumour, 2.1 % normal and 62.1 %
background (`uc1_changes.md`): about 93 of every 100 pixels it does not call
background are tumour. A tumour layer will therefore cover most of what the
model does not call background. That is the old model's output, not tumour
extent.

`ADR-0003` decision 5 says SLIAFlow does not "resample, register, recolour,
threshold or interpret an output". Drawing a class as a layer means reading the
class from the picture's colours.

## Decision

Proposed:

1. **One layer, on request.** Tumour Delineation can show the selected class
   output, `svm.bmp`, `knn.bmp` or `imageRGB.bmp`, as a label layer over HS
   Cube's colour preview of the same capture, with an opacity control and
   Slicer's own outline display. One control turns it on; it is off at the
   start of every session, so the standalone view stays the default.
   `pca.bmp` and `kmeans.bmp` carry no class and are never laid over anything.
2. **The background is the cube's own preview, and nothing else.** Never the
   laptop camera, the app's LiveView, or a photograph delivered with a capture
   (`ADR-0001` rule 2, kept). Microscope RGB becomes a background only when
   IUMA defines how its pixels match the cube's, in its own ADR.
3. **Classes are read exactly.** A pixel's class is the palette entry its
   colour equals. Every pixel must equal one entry; any other colour refuses
   the layer, and the output is shown on its own with the reason. No nearest
   colour, threshold, smoothing or resampling. This narrows `ADR-0003` decision
   5 for this one lossless decode, for display; the output file and its
   standalone view do not change.
4. **Same capture, same grid.** The layer is drawn only when the output carries
   the capture ID of the preview shown and has the cube's samples x lines;
   otherwise the output is shown on its own with a status saying why. A result
   marked as previous is never laid over a new capture's preview.
5. **What the words say.** The layer and its legend name the stage (SVM, KNN
   filtering, majority voting) and say it is the old model, trained on another
   camera, not validated. Nothing on the panel says tumour extent, margin or
   boundary.
6. **Numbers replace the colours when they arrive.** When the algorithm
   partners deliver an agreed float32 score map with its metadata (capture,
   model version, stage, class order, range, invalid pixels), it replaces the
   colour decode: a heat map with a colour bar, and an outline at the
   threshold the partners give. It is read by a reader of its own, never by the
   calibrated-cube loader and never with invented wavelengths. The colour
   decode is then removed with its tests. SLIAFlow never chooses a threshold to
   make a picture look like an example.

## Rationale

A preview built from the same cube as the result is registered with it by
construction, the argument of `ADR-0001` that `ADR-0003` never disputed; what
`ADR-0003` objected to, cube processing and identity, now exists for other
reasons. The capture-ID and size checks of decision 4 do the work that rule 3
of `ADR-0001` (same producer, same connection) did when results arrived over a
network.

An exact palette decode is lossless and checkable: the same file always gives
the same labels, and a colour outside the palette is a refusal, not a guess.
Slicer draws a label layer's outline itself, so SLIAFlow computes no contour
and moves no boundary. Keeping the layer off at start keeps the display the
operator knows unless they ask for the other.

## Alternatives considered

**Keep every output standalone (`ADR-0003` as it is).** Honest and free, and
right if UNIPV or ULPGC take the display on. It does not give the display the
meeting and the roadmap ask for.

**Blend the whole BMP over the preview, without decoding.** Rejected: the black
background class darkens the preview everywhere, and an RGB picture has no
outline to draw.

**Lay the result over the app's LiveView or the laptop camera.** Rejected:
neither is registered with the cube (`ADR-0001` rule 2).

**Compute a contour in SLIAFlow.** Rejected: Slicer outlines a label layer, and
a contour SLIAFlow computed would be a boundary it drew.

**Wait for numeric scores.** Viable, and decision 6 takes them when they come.
Until then it leaves the panel as it is.

**Threshold or smooth the classes in SLIAFlow.** Rejected: SLIAFlow never
creates a classification (`SLIAFLOW_IMPLEMENTATION_ROADMAP.md`).

## Consequences

- On acceptance, `ADR-0003` decision 3 no longer applies to the class outputs
  on Tumour Delineation, and decision 5 allows the decode of decision 3 here.
  The rest of `ADR-0003` stands. `ADR-0001` rule 1 returns in substance.
- A task card implements it: the control, the decode, the layer, the legend,
  their tests, the module README and `SLIAFLOW_UC1_IMAGE_CONTRACT.md`.
- A blank or single-colour output from a failed run would draw a layer of one
  class. `SLIA-042` makes such a run a failure first.
- The roadmap's rule that SLIAFlow never creates a classification, probability
  map or diagnostic result stands: the layer shows UC1's own classes.
- Decision 6 needs a result format agreed with the partners, by its own card.

## Validation

- Automated tests assert that each palette colour decodes to its class; that a
  pixel of any other colour refuses the layer, with the reason; that `pca.bmp`
  and `kmeans.bmp` are never laid over anything; that an output of another
  capture or another size is shown on its own with a status; that on an
  asymmetric placeholder the layer's pixel at a row and column lies over the
  preview's pixel at the same row and column; that the laptop camera and the
  app's LiveView are never a background; that the legend names the stage and
  says not validated; and that with the layer off the output shown is
  pixel-identical to the file.
- Manual verification shows the layer on `S-N-002-04` and on a 1080 x 1301
  capture at several opacities, with the outline on and off, and that after
  choosing another capture the previous result is not laid over its preview.

## Related tasks

- An implementation card, written when this ADR is accepted.
- `SLIA-042` - UC1 failures shown as failures, so a failed run is never drawn as
  a layer.

## Superseded ADRs

None until accepted. On acceptance: `ADR-0003` in part, decision 3 for the class
outputs on Tumour Delineation, and decision 5 narrowed to the decode of
decision 3. Their bodies are not rewritten; their front matter gains
`superseded_in_part_by: ADR-0007`.
