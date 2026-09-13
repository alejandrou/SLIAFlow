# Medical Data Policy

This repository is an active SLIAFlow-related 3D Slicer development project and prototype. It is not production clinical software and must not contain private or sensitive medical data.

## Allowed Data

- Synthetic data.
- Public Slicer sample data.
- Anonymized test data.
- Mock JSON/results.
- Explicitly approved public medical data.

## Explicitly Approved Public Medical Data

Approval is recorded here, per dataset, with its conditions. A dataset that is
not listed here is not approved, whatever its licence says.

### HSI Human Brain Database (ULPGC)

- Source: `https://hsibraindatabase.iuma.ulpgc.es/`, published by IUMA, ULPGC.
- Nature: public, anonymized in vivo hyperspectral brain-surface imagery.
- Local location: `input/bin/bin/`, which is gitignored. **No case may enter
  version control**, and no case may be copied into `docs/`, `workspace/` or any
  published material.
- Approved for: use as recorded input to the UC1 and UC2 pipelines and as the
  cube behind the WP5 demonstrator, under `SLIA-023`, `SLIA-024` and `SLIA-021`.
- Read-only. The case folders are never a write target.
- Provenance: the acquisition event in this repository is always simulated, so
  data derived from these cases travels as `SLIAFlow.DataOrigin = simulated`. The
  simulation detail must nonetheless name the case and must never describe a
  recorded cube as synthetic input. `simulated` describes the acquisition, not
  the cube, and a detail that says otherwise misleads in the one direction the
  banner and demo-mode interlock do not protect against.
- Not approved for: any accuracy, sensitivity or agreement metric computed
  against the bundled `gtMap` and presented in the interface or in a deliverable.
  The database's labels are the database's; this repository does not evaluate
  algorithms.

## Prohibited Data

- Private patient data.
- Non-anonymized DICOM files.
- Sensitive medical images.
- Real clinical reports.
- Private hospital data.

Outputs must clearly identify mock or demo data and must not imply clinical validity.
