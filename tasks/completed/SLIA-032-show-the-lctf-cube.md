---
id: SLIA-032
title: Show the calibrated LCTF cube - bands, colour preview and pixel spectrum
status: backlog
branch:
priority: high
depends_on: SLIA-031
required_skills: [slicer]
optional_tools: []
related_adrs: [ADR-0004]
---

# SLIA-032 - Show the calibrated LCTF cube - bands, colour preview and pixel spectrum

## Goal

Load IUMA's calibrated float32 cube `002-04` into SLIAFlow and let the operator
look at it:

- browse it band by band, with the wavelength of the current band shown;
- see a colour preview built from three bands;
- click a pixel and see its spectrum (reflectance against wavelength).

This is the first task that works with the future data format, and it does not
need UC1.

## Context

`LCTF_Calibrated_Cube_Single` is ENVI data type 4 (float32), BSQ, byte order 0,
1080 x 1080 x 109, wavelengths 460-1000 nm in 5 nm steps, values in [0, 1.5]. At
about 485 MiB it is larger than the 93-band cases the HS Cube panel shows today.

The HS Cube panel already shows a cube as a module-owned scalar volume with the
band on the third axis, so a slice view scrolls it band by band
(`SLIAFlowLogic.acceptCube`), with one window and level for the whole cube. That
code reads uint16 only and has no notion of wavelength.

The IUMA app also offers a cube viewer ("Load HS Cube",
`docs/hardware/acquisition_app_and_hardware.md` section 3.5); it is a reference
for what the IUMA team expects to see, not something to copy.

## Requirements

- Read a float32 BSQ ENVI cube with its wavelengths, checking header against
  file size before reshaping, as the uint16 reader does.
- Show it in the HS Cube panel as the configured cube. UC1 keeps running on the
  reference case until `SLIA-033`; the panel states which cube it shows, and the
  Tumour Delineation panel states which cube its result came from, so the two
  are never confused.
- Band browsing shows the band number and its wavelength in nm.
- A colour preview from three bands chosen by wavelength, with defaults near
  red, green and blue (for example 650, 550 and 470 nm), stated in the panel.
  The preview is labelled as a band composite, not a photograph.
- Clicking a pixel in the cube view shows that pixel's spectrum as a Slicer plot,
  with the axis units stated (reflectance, nm).
- No resampling, smoothing or rescaling of the stored values. Display window and
  level are display settings only.
- Provenance on the cube node as `ADR-0004` decision 7 states.

## Out of scope

- Running UC1 on this cube (`SLIA-033`).
- Reading the raw uint16 cube and calibrating it ourselves. IUMA calibrates.
- Receiving the cube over the network (`SLIA-030`).

## Files allowed

To be defined at specification. Expected: the single-cube loader from
`SLIA-031`, `SLIAFlowLogic.py`, `SLIAFlowWidget.py`, `SLIAFlow.ui`,
`SLIAFlowTest.py`, the module README.

## Relevant skills and references

- Slicer skill: scalar volumes from numpy, slice view interaction (pixel pick),
  plot chart and plot series nodes, layout of a plot inside the panel. The APIs
  are checked in the skill at specification, not assumed.
- `docs/architecture/decisions/ADR-0004-iuma-lctf-cube-and-acquisition-app.md`
- `docs/hardware/acquisition_app_and_hardware.md`, sections 3.4 and 3.5

## Implementation plan

To be defined at specification.

## Acceptance criteria

To be defined at specification. At minimum:

- the cube loads with the stored float32 values unchanged;
- each band shows its wavelength;
- the colour preview names its three wavelengths;
- a clicked pixel's spectrum matches the stored values at that pixel;
- a cube whose header and file disagree is refused with the reason.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
|  |  |  |

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 |  |  |  |

## Risks

- Memory: the cube plus a float32 volume copy plus the preview. Measure Slicer's
  memory after load and record it.
- A spectrum plot can look like an analysis result. It shows stored values only
  and says so.

## Documentation impact

Module README; the operator section of the UC1 demo runbook.

## Completion evidence

## Review findings

## Human approval
