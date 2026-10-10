# Medical Data Policy

This repository is an active SLIAFlow-related 3D Slicer development project and prototype. It is not production clinical software and must not contain private or sensitive medical data.

## Allowed Data

- Test fixtures in automated tests: placeholder arrays that stand for no
  imagery, are labelled as test fixtures, and are never presented as data. A
  test may write them to a temporary folder it deletes afterwards, laid out like
  an approved dataset and carrying that dataset's identifying marker, when the
  test exercises reading or identifying that layout. Such a folder never leaves
  the test's temporary directory.
- Public Slicer sample data.
- Anonymized test data.
- Mock JSON/results.
- Medical data explicitly approved below, public or provided for this project.

## Explicitly Approved Medical Data

Approval is recorded here, per dataset, with its conditions. A dataset that is
not listed here is not approved, whatever its licence says.

### HSI Human Brain Database (ULPGC)

- Source: `https://hsibraindatabase.iuma.ulpgc.es/`, published by IUMA, ULPGC.
- Nature: public, anonymized in vivo hyperspectral brain-surface imagery.
- Local location: none since `SLIA-039` (`ADR-0005`). The cases lay in the
  gitignored `input/`, archived there by `SLIA-031`, until the project owner
  removed them after `SLIA-039`. Nothing in the repository reads
  them. A case the owner places in `input/` again is covered by the entry
  below.

  **No case may enter version control**, and no case may be copied into
  `docs/`, `workspace/` or any published material.
- Approved for: use as recorded input to the UC1 and UC2 pipelines and as the
  cube behind the WP5 demonstrator, under `SLIA-023`, `SLIA-024`, `SLIA-021` and
  `SLIA-031`.
- Read-only. The case folders are never a write target.
- Provenance: the acquisition event in this repository is always simulated, so
  data derived from these cases travels as `SLIAFlow.DataOrigin = simulated`. The
  simulation detail must nonetheless name the case and must never describe a
  recorded cube as synthetic input. `simulated` describes the acquisition, not
  the cube, and a detail that says otherwise misleads, with nothing else on
  screen to correct it.
- Not approved for: any accuracy, sensitivity or agreement metric computed
  against the database's `gtMap` labels and presented in the interface or in a
  deliverable.
  The database's labels are the database's; this repository does not evaluate
  algorithms.

### Any data placed in `input/`

- Permission: the project owner and IUMA permit the use of **any file the
  project owner places in `input/`**, for any purpose of this project. Given on
  2026-09-24 and extended to every file in the folder on 2026-10-08. A new
  delivery needs no entry or task here before code reads it.
- Today the folder holds IUMA's LCTF captures `S-N-PPP-CC` (PPP a patient
  number, CC a capture number), delivered on 2026-10-08. Each holds the
  calibrated float32 cube `LCTF_Calibrated_Cube_Single`, its raw uint16 cube
  `raw_data`, the references `WR`, `DR`, `DR_WR` and `DR_DC`, and up to four
  photographs `M0n.jpg`. They are in vivo captures from IUMA, Universidad de
  Las Palmas de Gran Canaria (ULPGC), and are not public data. `S-N-002-04` is
  the capture called `002-04` before 2026-10-08 (`ADR-0004`).
- Local location: the gitignored `input/`. **No file of it may enter version
  control**, because the repository must not contain medical data. For the same
  reason none is copied into `docs/` or `workspace/`.
- Read-only. Code never writes into `input/`; the project owner adds and
  removes its files.
- Provenance: while a capture is read from disk the acquisition is simulated,
  so data derived from it travels as `SLIAFlow.DataOrigin = simulated`, and the
  detail names the capture as a recorded IUMA LCTF capture calibrated by IUMA
  (`ADR-0004` decision 7, `ADR-0006`).
- Results on these captures are behavioural, not validated: the UC1 model was
  trained on another camera, so an output shows that the pipeline runs and what
  it produces, never how accurate it is (`ADR-0004` decision 5).
- The permission lasts until IUMA or the project owner withdraws it; on
  withdrawal the affected files are deleted and this entry updated.

## Prohibited Data

- Private patient data.
- Non-anonymized DICOM files.
- Sensitive medical images.
- Real clinical reports.
- Private hospital data.

Outputs must clearly identify mock or demo data and must not imply clinical validity.
