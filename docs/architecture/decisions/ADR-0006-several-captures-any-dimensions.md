---
id: ADR-0006
title: Several IUMA LCTF captures, chosen by the operator, of any dimensions
status: accepted
date: 2026-10-08
accepted: 2026-10-08
related_tasks: SLIA-040, SLIA-041
supersedes: ADR-0004 (decision 1, what remained of it; decision 7, the naming of 002-04), ADR-0005 (decisions 2 and 3, the single cube)
---

# ADR-0006 - Several IUMA LCTF captures, chosen by the operator, of any dimensions

## Status

Accepted by the project owner on 2026-10-08, in conversation, when IUMA's new
captures arrived. The implementing task accepts the details marked as open
below.

On acceptance, `ADR-0004` and `ADR-0005` gain `superseded_in_part_by: ADR-0006`
in their front matter and a line in their Status sections. Their bodies are not
rewritten.

## Context

`ADR-0004` decision 1 made `002-04` the one cube SLIAFlow works with, with no
case pool and no shuffling, and `ADR-0005` left it alone in `input/`.

On 2026-10-08 IUMA delivered 16 LCTF captures, `S-N-PPP-CC`, from five patients
(002, 003, 005, 006 and 007), each laid out as `002-04` was: the calibrated
float32 cube `LCTF_Calibrated_Cube_Single`, its raw cube, its references and
photographs. `S-N-002-04` is byte for byte the cube `002-04`, and the owner
removed `input/002-04`. Measured from their headers that day:

- all 16 have 109 bands at 460-1000 nm in 5 nm steps, the grid of `ADR-0004`
  decision 4;
- 14 are 1080 lines x 1301 samples, and two, `S-N-002-04` and `S-N-003-01`,
  are 1080 x 1080. No cube of 1301 samples has yet run through UC1, UC2 or the
  panels;
- each lies one folder deeper than `002-04` did:
  `input/S-N-002-01/S-N-002-01/`.

Every file in `input/` may be used (medical-data policy, 2026-10-08). The
module, the build checks and the stand-in still point at `input/002-04`, which
no longer exists.

## Decision

1. **Every capture in `input/` is offered.** A capture is a folder in `input/`
   that holds `LCTF_Calibrated_Cube_Single.hdr`, directly or in one nested
   folder of the same name. The operator picks the capture Capture runs on. No
   capture is picked at random. This supersedes what remained of `ADR-0004`
   decision 1 and `ADR-0005` decision 2.
2. **Any dimensions.** Lines and samples are read from each cube's header. No
   part of the module, the UC1 and UC2 runs, the panels or the reception of the
   app's cube assumes a square cube or a given size. The band grid must still
   fit `ADR-0004` decision 4's mapping, and decision 6's input validation is
   unchanged.
3. **Captures that cannot run are listed, not hidden.** Every capture appears.
   One that an algorithm cannot run on says why when it is chosen, and is
   recorded in one compatibility document with the reason and the possible
   fixes. The document names captures by ID only and holds no image data.
4. **Provenance names the capture.** `ADR-0004` decision 7 stands, with the
   chosen capture's ID where it named `002-04`.
5. **The build checks run on `S-N-002-04`.** It is the cube the recorded
   hashes of `check-uc1.py` and `check-uc2.py` were made on, so they stay valid.
   This supersedes `ADR-0005` decision 3 in its folder only.

Decided by the project owner during the specification of `SLIA-040`
(2026-10-08): every session starts on `S-N-002-04`, and the choice is not
remembered between sessions. Within a session it may be changed.

## Rationale

The product will receive cubes from different patients and, as the delivery
shows, of different widths. Developing against one square cube hid that. An
explicit choice keeps every result traceable to its capture; a random pick
would not. Listing what does not run keeps failures visible and gives them a
place to be fixed from.

## Alternatives considered

**A shuffled pool, as `ADR-0003` had.** Rejected by the owner: an explicit
choice is reproducible, and the provenance always names the capture.

**Offer only the captures that run.** Rejected by the owner: a capture that
fails is information about the algorithms, and is recorded with its reason.

**Edit `ADR-0004` in place.** Not allowed: an accepted decision is changed by
a new ADR that supersedes it (`AGENTS.md`).

## Consequences

- The module's configured cube becomes the chosen capture; `input/002-04`
  disappears from code, tests, scripts and the stand-in.
- Tests cover a non-square cube through loading, the band mapping, the UC1 and
  UC2 runs, the panels and reception.
- A compatibility document lists every capture and its result.
- `input/README.txt` describes the captures instead of `002-04`.

## Validation

- An automated test asserts that every capture folder, nested or not, is
  offered, and that a folder without the calibrated cube is not.
- An automated test runs a non-square placeholder cube through every path that
  reads lines and samples.
- `check-uc1.py` and `check-uc2.py` pass on `S-N-002-04` with their recorded
  hashes.
- The compatibility document lists all 16 captures.

## Related tasks

- `SLIA-040` - every capture, any dimensions, compatibility check.
- `SLIA-041` - sends a capture from another computer.
