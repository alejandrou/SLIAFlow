---
id: SLIA-015
title: Align the class map palette with the UC1 pipeline
status: backlog
branch:
priority: medium
depends_on: SLIA-010
required_skills: [slicer]
optional_tools: []
related_adrs: []
---

# SLIA-015 - Align the class map palette with the UC1 pipeline

## Goal

Make SLIAFlow paint each UC1 class in the colour the UC1 pipeline itself assigns
to that class, so a map read on screen means the same thing as the map read from
the pipeline's own output.

## Context

Found while implementing SLIA-010 and deliberately left unfixed there, because a
palette change is a display-semantics change and had nothing to do with that
task's provenance boundary.

`_getOrCreateClassColorNode` in `SLIAFlowLib/SLIAFlowLogic.py` (around line 646)
builds a five-entry table:

| Index | Label | SLIAFlow colour |
| --- | --- | --- |
| 0 | Unused | transparent |
| 1 | Normal | green `(0.1, 0.8, 0.2)` |
| 2 | Tumour | red `(0.9, 0.1, 0.1)` |
| 3 | Hypervascularized | orange `(1.0, 0.65, 0.0)` |
| 4 | Background | dark grey `(0.2, 0.2, 0.2)` |

The UC1 pipeline writes blue for class 3 and black for class 4. Classes 1 and 2
agree. So a hypervascularized region and the image background are both rendered
in a colour the pipeline does not use, and orange in particular reads as a
warning tone for a class that is not the tumour class.

This is a real disagreement between two components about what a pixel means, not
a preference. Nothing in the current tests would catch it, because the tests
assert that a class map uses four discrete colours, not which four.

## Requirements

- Establish the authoritative palette from the UC1 source rather than from
  screenshots or memory, and record where it was read from.
- Change the class 3 and class 4 entries to match it, leaving classes 1 and 2
  untouched.
- Keep index 0 fully transparent. It is the "no class" entry and must not become
  a visible colour just because the pipeline has a fourth colour.
- Document the palette in `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`
  alongside the rest of the class map contract, so the next disagreement is a
  documentation diff rather than a discovery.
- Add a test asserting the specific RGBA of every entry, so a future edit to the
  table fails loudly instead of silently changing what a map means.

## Out of scope

- The probability colour ramp. Only the discrete class table is in question.
- Any change to window/level handling, to `_configureResultDisplay`, or to which
  map roles are class maps.
- Colour-blind-safe or otherwise "improved" palettes. The goal is agreement with
  UC1, not a better palette; a different palette is a separate conversation with
  the pipeline's owner.

## Files allowed

- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`
- `tasks/{backlog,active,review,completed}/SLIA-015-class-palette-alignment.md`

## Acceptance criteria

- The class colour table matches the UC1 palette entry for entry, with the
  source of truth cited in the card.
- The image contract document states the palette.
- A test fails if any entry's RGBA changes.
- `scripts/development/run-python-quality.ps1` and
  `scripts/development/run-slicer-tests.ps1` both pass.

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Present a class map containing all four classes | Each class is drawn in the UC1 colour for that class | |
| 2 | Compare the pane against the pipeline's own rendering of the same map | The two are indistinguishable in class colouring | |

## Risks

Reading the palette from the wrong place would encode a second wrong answer that
looks authoritative because it is now documented and tested. The requirement to
cite the source exists for that reason.
