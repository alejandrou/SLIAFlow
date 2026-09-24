---
id: ADR-0004
title: One IUMA LCTF cube as reference, and IUMA's acquisition app as the future source
status: proposed
date: 2026-09-24
related_tasks: SLIA-031, SLIA-028, SLIA-032, SLIA-033, SLIA-034, SLIA-035, SLIA-030, SLIA-021, SLIA-009
supersedes: ADR-0003 (decision 1 in part, decision 2 in part, decision 5 input validation)
---

# ADR-0004 - One IUMA LCTF cube as reference, and IUMA's acquisition app as the future source

## Status

Proposed on 2026-09-24 from decisions the project owner made in conversation
that day. It is accepted by the project owner during the specification of
`SLIA-031`, which is the first task that depends on it. On acceptance,
`ADR-0003`'s front matter gains `superseded_in_part_by: ADR-0004` and a line in
its Status section. Its body is not rewritten.

## Context

`ADR-0003` made SLIAFlow run the capture and UC1 itself, picking a recorded case
from a shuffled pool of the HSI Human Brain Database (`input/bin/bin`, 61 cases,
93 bands at 440-900 nm, uint16 raw plus white and dark references). It removed
OpenIGTLink from the operator workflow until external hardware existed.

Three things changed on 2026-09-23 and 2026-09-24:

1. **IUMA's acquisition app is the real source.** IUMA installed its
   `AcquisitionSystemApp` on this laptop. It drives Thorlabs cameras and a
   Kurios liquid crystal tunable filter (LCTF) and serves three OpenIGTLink
   ports: 18944 LiveView, 18945 stereo and 18946 HS cube, one IMAGE message per
   band (`docs/hardware/acquisition_app_and_hardware.md`, sections 4 and 8).
2. **The cube it will send is calibrated float32.** IUMA wrote that white and
   dark references are handled by hand and that the app will send the
   calibrated cube as float32 over the same protocol. A real LCTF capture,
   `002-04`, shows the format: `LCTF_Calibrated_Cube_Single`, ENVI data type 4,
   BSQ, 1080 x 1080 x 109 bands at 460-1000 nm in 5 nm steps, values clipped to
   [0, 1.5]. It comes with its raw uint16 cube (4096 x 2160 x 109) and its
   references.
3. **Data permission.** The project owner and IUMA permit use of any data placed
   in the gitignored `input/` folder. The owner wants the work minimal and
   centred on that one cube, and the old 93-band cases archived.

The staged SVM model of UC1 is sized for 93 bands on the 440-900 nm grid.
`main.cu` reads `w_vector.bin` with the header's band count and never checks how
much it read, so a 109-band cube silently produces garbage weights. UC1 also
expects uint16 raw plus full-size references and calibrates them itself. The
owner has ruled out retraining the model, and allows changes to parameters,
calibration and input handling in UC1 as long as each change and its results are
documented simply.

The IUMA email also calls the HSI Human Brain Database cases, made to look like
LCTF captures, "synthetic HELICoiD cubes". This repository keeps its own wording:
they are recorded cases, never synthetic data.

PLUS (PlusServer) was mentioned by IUMA. It adds nothing here: IUMA's app is
already the OpenIGTLink server, and PLUS has no driver for the Kurios filter or
the Thorlabs cameras.

## Decision

1. **One reference cube.** The cube SLIAFlow works with is IUMA's calibrated
   float32 LCTF cube, `002-04`, copied into `input/`. There is no case pool and
   no shuffling. The HSI Human Brain Database cases are archived under a
   clearly named folder in `input/` and are not read by the module. One case
   stays unarchived as the UC1 reference check, because it is the only input on
   which UC1's model is known to behave as its authors intended. This
   supersedes the pool part of `ADR-0003` decision 1; the in-Slicer background
   UC1 run of decision 1 stays.
2. **The product's source is IUMA's app, over OpenIGTLink, with Slicer as
   client.** When reception is built (`SLIA-035`, `SLIA-030`), SLIAFlow connects
   as a client to the app's ports and shows what each port carries. Until then
   the cube is read from disk. This supersedes `ADR-0003` decision 2 for
   external acquisition only: the in-Slicer UC1 run still uses no network hop,
   and Slicer still never serves links to itself.
3. **UC1 may be changed, reproducibly.** Changes to UC1 are kept as versioned
   patches in this repository and applied at staging by `build-uc1.ps1`. The
   vendored copy in `workspace/components/` stays byte-identical to what was
   delivered, and the staging hash check compares against original plus
   patches. Every change is documented with what it does and the result it
   produced. The SVM model is never retrained.
4. **109 to 93 bands by a documented mapping, not by retraining.** The 89 LCTF
   bands at 460-900 nm match the model grid exactly. The 440-455 nm bands the
   model expects are filled with the 460 nm band, and 905-1000 nm is dropped.
   The mapping is written down in one place and applied in one place. A cube
   whose band count or wavelengths do not match the mapping is refused before
   UC1 starts.
5. **Results on the LCTF cube are behavioural, not validated.** The model was
   trained on another camera's spectral response. A UC1 output on `002-04`
   shows that the pipeline runs and what it produces; it says nothing about
   accuracy. Status text and documents say so.
6. **Input validation for a float32 cube.** A cube is used only if its ENVI
   header and data file agree (data type 4, BSQ, byte order 0, size), its
   wavelengths are present, and it fits the band mapping of decision 4. This
   replaces `ADR-0003` decision 5's "identified recorded case of the HSI Human
   Brain Database whose band count matches the staged SVM model", which remains
   the rule for the reference case only.
7. **Provenance.** While the cube is read from disk, the acquisition is
   simulated: output nodes keep `SLIAFlow.DataOrigin = simulated`, and the
   detail names `002-04` as a recorded IUMA LCTF capture calibrated by IUMA.
   The wording for a cube received live from the app is decided in `SLIA-030`.
   Everything else in `ADR-0003` decision 5 stays.
8. **Ground truth only where it exists.** `002-04` has no `gtMap`. The
   ground-truth overlay of `ADR-0003`'s 2026-09-18 amendment is offered only for
   a cube that carries one, and its absence is stated, not hidden.
9. **PLUS is not adopted.**

## Rationale

The product will receive IUMA's calibrated cube, so the module should be built
and measured against that cube now rather than against a dataset from another
camera. A pool of 61 cases was the right tool when there was no real capture; with
one real capture, the pool, its deferred list and its compatibility rules are
code that no longer serves the product.

Patching at staging keeps the delivered UC1 reference intact and makes every
change reviewable in Git, which a gitignored workspace cannot do.

A band mapping keeps UC1 runnable on the real format without touching the model.
Its limits are stated in decision 5 instead of being discovered later.

## Alternatives considered

**Keep the pool and add 002-04 to it.** Rejected: the owner asked for a minimal,
single-cube base; the pool's rules exist for a dataset the product will not use.

**Retrain the SVM on 109 bands.** Rejected by the owner: the model belongs to
BSC and ULPGC.

**Convert the float32 cube back to uint16 with made-up references.** Rejected:
it invents data UC1 would then calibrate again, and hides the real input format.

**Edit UC1 in place in `workspace/components/`.** Rejected: the folder is
gitignored, so changes would be neither reviewable nor reproducible.

**Use PLUS between the app and Slicer.** Rejected; see Context.

## Consequences

- `input/` holds one primary cube, one reference case and an archive folder.
- `SLIAFlowCasePool.py` is replaced by a single-cube loader (`SLIA-031`).
- The medical-data policy records the owner's and IUMA's permission and the new
  dataset before any code reads it (`SLIA-031`).
- The standalone producers and session scripts are retired, keeping only what a
  stand-in for IUMA's app needs (`SLIA-028`).
- `build-uc1.ps1` gains patch application and a hash check against original
  plus patches (`SLIA-033`).
- `SLIA-029`'s largest-case verification loses its subject and is removed;
  large-cube GPU limits move into `SLIA-034`.

## Validation

- Automated tests assert that the module reads exactly one configured cube and
  refuses a float32 cube whose header and file disagree or whose wavelengths do
  not fit the band mapping.
- The band mapping is asserted by a test that checks which source band feeds
  each of the 93 model bands.
- `build-uc1.ps1` fails when the staged tree differs from original plus patches.
- Each UC1 change has a short written record with the command and result.

## Related tasks

- `SLIA-031` - single-cube cleanup; accepts this ADR.
- `SLIA-028` - retires the standalone producers.
- `SLIA-032` - shows the LCTF cube.
- `SLIA-033` - UC1 accepts the calibrated float32 cube.
- `SLIA-034` - performance and large-cube limits.
- `SLIA-035` - connections panel.
- `SLIA-030` - reception from IUMA's app.
