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
- Local location, both gitignored, since 2026-09-24 (`SLIA-031`, `ADR-0004`):
  - `input/reference_hsi_brain_db/020-01/`, the one case the module reads, kept
    as the UC1 reference check;
  - `input/archive_hsi_brain_db_93_bands/`, every other case (`bin/`) and the
    full-size images (`bin_full_size_images/`), kept but not read by the module.

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
  against the bundled `gtMap` and presented in the interface or in a deliverable.
  The database's labels are the database's; this repository does not evaluate
  algorithms.

### IUMA LCTF capture 002-04

- Source: IUMA, Universidad de Las Palmas de Gran Canaria (ULPGC), which
  delivered it to the project owner for this project.
- Nature: an in vivo hyperspectral capture made with IUMA's LCTF acquisition
  system: the calibrated float32 cube `LCTF_Calibrated_Cube_Single`, its raw
  uint16 cube `raw_data`, the references `WR`, `DR`, `DR_WR` and `DR_DC`, and a
  photograph `M01.jpg`. It is not public data.
- Permission: given by the project owner and by IUMA on 2026-09-24 for any data
  placed in `input/`, and recorded here before any code in this repository reads
  or names the capture (`ADR-0004`, `SLIA-031`).
- Local location: `input/002-04/`, which is gitignored, copied from the owner's
  delivery folder. **No file of it may enter version control**, and none may be
  copied into `docs/`, `workspace/` or any published material, in whole or in
  part, including screenshots of it.
- Approved for: development and demonstration of SLIAFlow, as the reference cube
  of `ADR-0004`: display, and input to the UC1 and UC2 pipelines.
- Read-only. The folder is never a write target.
- Provenance: while it is read from disk the acquisition is simulated, so data
  derived from it travels as `SLIAFlow.DataOrigin = simulated`, and the detail
  names `002-04` as a recorded IUMA LCTF capture calibrated by IUMA
  (`ADR-0004` decision 7).
- Results on it are behavioural, not validated: the UC1 model was trained on
  another camera, so an output shows that the pipeline runs and what it
  produces, never how accurate it is (`ADR-0004` decision 5).
- The approval lasts until IUMA or the project owner withdraws it; on
  withdrawal the folder is deleted and this entry removed.

## Prohibited Data

- Private patient data.
- Non-anonymized DICOM files.
- Sensitive medical images.
- Real clinical reports.
- Private hospital data.

Outputs must clearly identify mock or demo data and must not imply clinical validity.
