---
id: SLIA-019
title: Close the haemoglobin absorption valley in the tissue phantom
status: superseded
branch:
priority: medium
depends_on: SLIA-011
required_skills: []
optional_tools: []
related_adrs: []
---

# SLIA-019 - Close the haemoglobin absorption valley in the tissue phantom

> **Superseded on 2026-09-16 by `SLIA-025` (Retire the synthetic phantom path).**
> The project owner decided on 2026-09-14 that the project uses recorded data
> only, and `SLIA-025` deleted the tissue phantom this card was built on. The card
> is kept as history and is never eligible for activation.

## Goal

Make `tissue.py`'s haemoglobin extinction hold across the whole sensor range
rather than only at its peaks, so that phantom reflectance lands in a
physiologically plausible band and algorithm parameters tuned on real tissue
behave the way their authors intended.

## Context

Found while checking whether the vendored UC2 component can consume a simulator
dataset, during the SLIA-014 direction review.

`tissue.py` builds both haemoglobin extinction spectra as a sum of Gaussians on
a constant floor - `OXYHAEMOGLOBIN_FLOOR = 2.0e2`, `DEOXYHAEMOGLOBIN_FLOOR =
3.0e2`. The module's docstring is candid that these are analytic approximations
at the feature positions and not a transcribed extinction table, and warns they
must not be used for quantitative oximetry. This finding is not about oximetry.
It is that a sum of Gaussians at 415, 542 and 576 nm leaves a valley between the
Soret band and the alpha/beta pair which real haemoglobin does not have, and the
valley is deep enough to change what every downstream algorithm sees.

Measured on the 93-band grid against standard tabulated decadic molar extinction
coefficients, rounded to the two significant figures the comparison needs:

| Band | HbO2 model | HbO2 tabulated | Ratio | Hb model | Hb tabulated | Ratio |
| --- | --- | --- | --- | --- | --- | --- |
| 414 nm | 4.97e5 | 5.0e5 | 0.99 | 1.71e5 | 2.2e5 | 0.78 |
| 453 nm | 3.87e3 | 6.2e4 | 0.06 | 9.19e4 | 1.0e5 | 0.92 |
| 479 nm | 2.73e2 | 2.7e4 | **0.01** | 1.73e3 | 3.3e4 | **0.05** |
| 498 nm | 6.78e2 | 2.0e4 | 0.03 | 4.85e3 | 2.0e4 | 0.24 |
| 544 nm | 5.25e4 | 5.4e4 | 0.97 | 4.82e4 | 4.5e4 | 1.07 |
| 577 nm | 5.77e4 | 5.8e4 | 0.99 | 3.99e4 | 3.8e4 | 1.05 |
| 648 nm | 6.14e2 | 3.2e2 | 1.92 | 4.11e3 | 3.7e3 | 1.11 |
| 707 nm | 8.20e2 | 3.9e2 | 2.10 | 2.91e3 | 1.3e3 | 2.24 |
| 798 nm | 1.14e3 | 8.2e2 | 1.39 | 1.54e3 | 7.6e2 | 2.02 |

The peaks are excellent. The valley is two orders of magnitude low, and the near
infrared overshoots by roughly a factor of two.

The consequence is measurable rather than theoretical. On dataset
`workspace/simulators/datasets/sim-20260904-150404`, calibrated reflectance
`(raw - dark) / (white - dark)` spans 0.0031 to 0.8485, and the cortex region
reads about 0.85 at 479 nm where exposed cortex should sit around 0.1 to 0.3.
The genuine UC2 blood-vessel enhancement hard-codes its contrast stretch at
`high_in = 0.15`, a value chosen against real calibrated data; on this phantom
that stretch saturates over 87 per cent of the frame at UC2's own band index and
100 per cent at the wavelength-correct one. `I1` clips to 1, `I2 = 1 - I1`
collapses to nearly zero, and the enhancement stage becomes inert - the output
is close to a plain rendering of the calibrated bands.

So a parameter that is correct for the algorithm looks broken against our data,
and the phantom is the thing that is wrong.

### Re-examined on 2026-09-11, against recorded data

The WP5 demonstrator (`docs/architecture/WP5_MS5_DEMO_PLAN.md`) moves the demo on
to the recorded HSI Human Brain Database cases, so the phantom is no longer on the
demonstrator's critical path. Two things follow, and neither cancels this card.

**The `high_in` finding above stands as a phantom finding and does not transfer.**
Measured on the four BVMaps UC2 has already produced from recorded cases, the
blue output channel is saturated in 47 to 96 per cent of pixels - so real data
saturates too, but through a different mechanism. The blue channel is
`|I2 * bValue - calibrated[0]|` with `bValue = 3`, clamped at 1.0 by
`clip_array` before normalization; it is the `bValue` multiply clipping, not the
`high_in` stretch. The phantom's 87-to-100 per cent figure above was measured at
the stretch, and that measurement is still correct about the phantom.

**The card's own value is unchanged.** The reason to close the valley was never
that UC2 looks better afterwards - the card forbids exactly that - it is that the
phantom claims to have the spectral shape of tissue and does not. The phantom is
still the input to every test that must run without the recorded database, and
every recorded UC1 result in the repository was produced against the current
spectra.

What does change is priority. This card is not a blocker for MS5 points 2 or 3,
and it sits behind the demonstrator rather than in front of it. Acceptance
criterion four below - the before-and-after saturation measurement - should now be
recorded against both the phantom and a recorded case, so the two mechanisms stay
distinguishable in the evidence.

The same brightness error is why the rendered scene reads as pink rather than as
tissue: too little absorption in the blue-green raises every channel.

## Requirements

- Represent haemoglobin extinction so that the modelled value stays within a
  stated tolerance of tabulated values at named anchor wavelengths spanning the
  whole 400 to 1000 nm range, including at least two anchors inside the 450 to
  520 nm valley and two in the near infrared.
- State the tolerance and the source of the anchor values in the module, and
  assert it in a test, so that a future edit that reopens the valley fails
  rather than passes.
- Keep the reflectance model itself unchanged. This task corrects the absorption
  input, not the diffusion approximation, the scattering power law or the region
  parameters.
- Assert that each modelled region's reflectance falls inside a stated
  physiological band at named wavelengths, so the outcome is checked in
  reflectance and not only in extinction.
- Record in `docs/development/synthetic_tissue_phantom.md` that datasets written
  before this change carry the old spectra, and that comparisons across the
  change are not valid.
- Change nothing on the basis of what makes UC1 or UC2 produce a better-looking
  result. The anchors are published values; the classifiers are characterised
  after the fact, never optimised against.

## Out of scope

- Scene geometry, which is `SLIA-020`.
- Any change to UC1, UC2 or `extensions/`.
- Regenerating or deleting existing datasets under `workspace/`.
- Quantitative oximetry claims of any kind. Closing the valley makes the shape
  right; it does not make the phantom a measurement instrument.

## Files allowed

- `tools/simulators/stratum_sim/tissue.py`
- `tools/simulators/tests/test_tissue.py`
- `tools/simulators/README.md`
- `docs/development/synthetic_tissue_phantom.md`
- `tasks/{backlog,active,review,completed}/SLIA-019-haemoglobin-absorption-valley.md`

## Relevant skills and references

- `tools/simulators/stratum_sim/tissue.py` module docstring, which states what
  was deliberately not done and why
- `.ai/policies/algorithm-boundary-policy.md`
- `.ai/policies/medical-data-policy.md`
- The SLIA-014 direction review, for the UC2 saturation measurement

## Approved dependencies

None. The anchor values are transcribed constants, not a package.

## Implementation plan

1. Write the anchor table and its tolerance test first, and show it failing
   against the current model.
2. Replace the floor-plus-Gaussian construction with one that holds across the
   range, keeping the existing peak fidelity.
3. Measure region reflectance at the named wavelengths and record it.
4. Re-run the UC2 saturation measurement and record what `high_in = 0.15` now
   does, without changing UC2.

## Acceptance criteria

- Modelled extinction is within the stated tolerance of the anchors at every
  named wavelength, for both haemoglobins.
- Peak fidelity at 414, 544 and 577 nm is no worse than it is today.
- Each region's reflectance lies inside its stated physiological band.
- The fraction of the frame that saturates UC2's `high_in = 0.15` stretch is
  measured and recorded, before and after.
- The phantom documentation states that pre-change datasets are not comparable.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| Extinction within tolerance at every anchor | `test_tissue.test_extinction_matches_published_anchors` | automated |
| Peak fidelity not degraded | `test_tissue.test_peak_extinction_preserved` | automated |
| Region reflectance inside its physiological band | `test_tissue.test_region_reflectance_is_physiological` | automated |
| UC2 saturation measured before and after | Manual step 1 | manual |
| Documentation states the discontinuity | Manual step 2 | manual |

Tests to add or change, and how each one will be shown to fail first:

- `test_extinction_matches_published_anchors` is written against the current
  model and shown failing at 479 and 498 nm for both haemoglobins before any
  change is made. The failure output is recorded in the completion evidence.
- `test_region_reflectance_is_physiological` is shown failing for cortex at
  479 nm, which currently reads about 0.85 against a band topping out near 0.3.

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Write a dataset before and after the change and run the built UC2 binary on both, recording the saturated fraction of the enhancer band | The saturated fraction falls; the recorded numbers appear in the completion evidence | |
| 2 | Read `docs/development/synthetic_tissue_phantom.md` | It states that datasets written before this change carry different spectra and must not be compared across it | |

## Risks

The tempting error is to tune the absorption until UC2 or UC1 produces a picture
someone likes. That would produce an adversarial input that looks like a working
detector and means less than nothing, and the module's own docstring already
forbids it. The anchors come from published extinction tables and the
classifiers are only ever characterised afterwards.

The second risk is silent invalidation of past evidence. Every recorded UC1
result in the repository was produced against the current spectra. The change
must be documented as a discontinuity, not slipped in.

## Documentation impact

- `docs/development/synthetic_tissue_phantom.md`: the new absorption model, its
  anchors and tolerance, and the statement that the change is a discontinuity.
- `tools/simulators/README.md`: a pointer, if the phantom section names the
  absorption construction.

## Completion evidence

Reserved.

## Review findings

Reserved for review.

## Human approval

Required before activation and before completion.
