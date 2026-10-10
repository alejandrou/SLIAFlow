---
id: ADR-0005
title: Retire the HSI Human Brain Database inputs and the ground-truth overlay
status: accepted
date: 2026-10-07
accepted: 2026-10-07
related_tasks: SLIA-039
supersedes: ADR-0004 (decision 8; decision 1, the reference case and the archive), ADR-0003 (the 2026-09-18 amendment of decision 3)
superseded_in_part_by: ADR-0006
---

# ADR-0005 - Retire the HSI Human Brain Database inputs and the ground-truth overlay

## Status

Accepted by the project owner on 2026-10-07. The owner decided that day, while
`SLIA-038` was in progress, that nothing kept only for the old inputs stays in
the project, and made the two decisions on `020-01` and the archive during the
specification of `SLIA-039`.

Superseded in part by `ADR-0006` on 2026-10-08: decision 2 (`input/` holds
`002-04` only) and the folder of decision 3. `input/` holds IUMA's 16
`S-N-PPP-CC` captures, and the build checks run on `S-N-002-04`, the same cube.

On acceptance, `ADR-0003` and `ADR-0004` gain `superseded_in_part_by: ADR-0005`
in their front matter and a line in their Status sections. Their bodies are not
rewritten.

## Context

Since `SLIA-033` SLIAFlow runs UC1 on IUMA's calibrated LCTF cube `002-04`, and
since `SLIA-036` also on a cube received from IUMA's app. Neither has a `gtMap`.
What remained of the HSI Human Brain Database on 2026-10-07:

- `input/reference_hsi_brain_db/020-01/`, kept by `ADR-0004` decision 1 as the
  UC1 reference check, read only by `check-uc1.py` and `check-uc2.py`;
- `input/archive_hsi_brain_db_93_bands/`, read by nothing;
- the ground-truth overlay of `ADR-0003`'s 2026-09-18 amendment, offered by
  `ADR-0004` decision 8 only for a cube with a `gtMap` beside it. No cube the
  module can now be given has one, so the overlay could no longer appear, while
  its code and about a dozen tests remained.

The patched UC1 build gave the same four hashes as the delivered build on
`020-01`, and the patched UC2 build the same PNG, in the last run of both checks
on 2026-10-07 (`SLIA-039`).

## Decision

1. **The ground-truth overlay is retired.** The Tumour Delineation panel offers
   the five UC1 outputs and nothing else. `ADR-0003` decision 3 reads again as it
   did before its 2026-09-18 amendment: each output is shown on its own, with
   nothing composited under or over it. This supersedes `ADR-0004` decision 8.
2. **`input/` holds `002-04` only.** The reference case `020-01` and the archive
   are removed from `input/` by the owner. This supersedes the parts of
   `ADR-0004` decision 1 that keep one case unarchived as the UC1 reference
   check and archive the rest.
3. **The build checks run on `002-04`.** `check-uc1.py` runs UC1 on `002-04`
   mapped as `ADR-0004` decision 4 states, and `check-uc2.py` runs UC2 on
   `002-04`. Each compares with a run of the patched build recorded on
   2026-10-07, besides the independent oracles they already had (the predicted
   calibrated image, NumPy's principal component, the NumPy replica of UC2).
4. **Nothing compares the patched builds with the delivered ones any more.**
   That comparison needed a case the delivered builds could run on, and the last
   one goes with decision 2. The 2026-10-07 run is the last evidence; it is kept
   in `docs/development/uc1_changes.md` and `uc2_changes.md`.
5. **The UC1 colour legend stays as documentation.** `svm.bmp` and `knn.bmp` are
   painted from `FOUR_COLORS_MAP`, and the module README, the panel tooltip and
   the image contract say what the colours mean. No code keeps a copy of the
   table for SLIAFlow to draw with.

## Rationale

Code that cannot run is still read, tested and maintained. The overlay had no
input left to show, and its tests exercised only placeholder files. Keeping
`020-01` would have kept a dataset in `input/` for one comparison against a
build SLIAFlow never runs.

## Alternatives considered

**Keep `020-01` for the build checks only.** It keeps the one proof that the
patches leave the delivered algorithm unchanged. Rejected by the owner: the
recorded 002-04 runs catch any later change to a patch, and the final `020-01`
run is kept as evidence.

**Keep the overlay in case a labelled cube arrives.** Rejected: no such cube is
planned. A labelled cube would come with its own format and its own decision.

## Consequences

- `SLIAFlowCube.py` holds only the ENVI header parser.
- A scene saved with `gtMap` selected opens on the default output.
- A changed GPU, driver or nvcc may change the recorded 002-04 hashes with no
  patch changed. The check then fails and names the file; the run is reviewed
  and recorded again (`check-uc1.py --save-baseline`).
- The medical-data policy keeps its approval of the HSI Human Brain Database,
  because UC1's model was trained on it, but no case of it lies in `input/`.

## Validation

- An automated test asserts that the Delineation output box lists exactly the
  five outputs, and another that a stored `gtMap` selection binds to the default
  output.
- `check-uc1.py` and `check-uc2.py` pass on `002-04`, and fail when a recorded
  hash or the saved run does not match.

## Related tasks

- `SLIA-039` - removes what the old inputs left behind; accepts this ADR.
