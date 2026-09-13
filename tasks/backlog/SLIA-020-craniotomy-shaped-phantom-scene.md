---
id: SLIA-020
title: Give the phantom a scene shaped like a craniotomy
status: backlog
branch:
priority: low
depends_on: SLIA-019
required_skills: []
optional_tools: []
related_adrs: []
---

# SLIA-020 - Give the phantom a scene shaped like a craniotomy

## Goal

Replace the phantom's placeholder geometry with a scene whose structure is the
structure of an exposed cortical surface, so that what appears in the live pane
and in a result map is recognisable as the thing the system is for.

## Context

Raised by the project owner after the SLIA-014 session, from the panes on
screen: the rendered scene is not close to anything brain-like.

The current geometry in `tissue.py` is a placeholder and reads as one. It is an
ellipse of cortex on drape, one elliptical blob for the tumour-like region, and
three vessel tracks drawn as `offset + amplitude * sin(k * x + phase) +
slope * x`. Sine ribbons of constant width cross the whole field, do not branch,
do not taper and do not terminate.

The vendored UC2 component ships a reference output made from a real surgical
field, and it shows what the structure actually is: a circular aperture with a
dark rim where the field is bounded, a vessel tree entering from the periphery
and bifurcating into progressively finer branches, sulcal grooves that read as
darker lines following the surface rather than crossing it, saturated specular
highlights from the microscope illuminator, and surgical ring markers laid on
the surface. That image is not reproduced in this repository's documentation and
must not be, but it is available in `workspace/components/blood_vessels_enhancement`
for anyone implementing this card to look at.

The geometry defect is independent of the spectral defect in `SLIA-019`. That
one makes the colours wrong; this one makes the shapes wrong. Both must be fixed
for the scene to read correctly, which is why this card depends on that one.

Re-examined on 2026-09-11: the WP5 demonstrator
(`docs/architecture/WP5_MS5_DEMO_PLAN.md`) shows recorded cases rather than the
phantom, so the original motivation - that what appears in the live pane should be
recognisable as the thing the system is for - is met for the demonstrator by the
data itself. This card is therefore not a blocker for MS5 points 2 or 3 and drops
behind the demonstrator in priority. It is not cancelled: the phantom remains the
input to every test that must run without the recorded database, and a scene
without specular highlights still never exercises the saturated-pixel path that
real intraoperative data always contains.

There is a second, quieter reason to do this. The phantom's structure is the
only structure the algorithms have to find. A vessel that does not taper gives a
vessel-enhancement algorithm nothing to demonstrate, and a scene without
specular highlights never exercises the saturated-pixel path that real
intraoperative data always contains.

## Requirements

- Bound the field with a circular aperture and a rim, rather than an ellipse of
  tissue meeting drape directly.
- Draw vessels as a branching structure: trunks entering from the field
  boundary, bifurcating, with the radius decreasing along each branch, and with
  branches that terminate inside the field rather than crossing it.
- Add sulcal shading, as a modulation of the cortex parameters rather than as a
  separate region, because a sulcus is cortex in shadow and not a different
  tissue.
- Add specular highlights as an additive, spectrally flat term, because surface
  reflection is spectrally flat. State that this is why, in the module.
- Keep the region map a construction record. Adding structure must not turn it
  into a label set, and no agreement between it and any algorithm's output may
  be claimed or reported as accuracy.
- Keep the scene deterministic for a given size and seed, so a dataset remains
  reproducible from its provenance.
- Change no part of the spectral model: absorption, scattering, the diffusion
  approximation and the region optical parameters are all out of scope here.

## Out of scope

- The absorption model, which is `SLIA-019`.
- Surgical ring markers. They are a real feature of the reference image, but
  they are a foreign object with its own reflectance and they add nothing the
  vessel tree does not already provide. Note the omission rather than fake it.
- Any change to UC1, UC2 or `extensions/`.
- Motion. The phantom is a still scene by design, because the live pane and the
  dataset are literally the same array.

## Files allowed

- `tools/simulators/stratum_sim/tissue.py`
- `tools/simulators/tests/test_tissue.py`
- `tools/simulators/README.md`
- `docs/development/synthetic_tissue_phantom.md`
- `tasks/{backlog,active,review,completed}/SLIA-020-craniotomy-shaped-phantom-scene.md`

## Relevant skills and references

- `workspace/components/blood_vessels_enhancement/C_BVMap.png` and
  `matlab_BVMap.png`, for what the structure is. Reference only; neither is to
  be copied into documentation or reproduced in any published material.
- `docs/development/synthetic_tissue_phantom.md`, which states the current
  geometry and what is asserted of it
- `.ai/policies/medical-data-policy.md`

## Approved dependencies

None. The branching structure is drawn with the existing NumPy dependency.

## Implementation plan

1. Write the geometry assertions first - branch count, radius monotonicity along
   a branch, aperture containment, highlight count - and show them failing.
2. Replace the field ellipse with the aperture and rim.
3. Replace `VESSEL_TRACKS` with a recursive branch generator, keeping the
   generation deterministic in the seed.
4. Add sulcal modulation and specular highlights.
5. Render every preset and look at each one before claiming the card is done.
6. Re-run the UC1 runner and the UC2 binary on a new dataset and record what
   each says, without adjusting anything to improve either.

## Acceptance criteria

- The field is bounded by an aperture and a rim, and no tissue region extends
  outside the aperture.
- The vessel structure branches, and the radius is non-increasing from a branch
  to each of its children.
- Sulcal shading varies cortex parameters without introducing a region value.
- Specular highlights are additive and spectrally flat.
- The scene is reproducible: the same size and seed produce an identical region
  map and cube.
- The region map's status as a construction record is unchanged in code, in the
  sidecar legend and in the documentation.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| Aperture bounds every tissue region | `test_tissue.test_no_tissue_outside_aperture` | automated |
| Vessels branch and taper | `test_tissue.test_vessel_tree_branches_and_tapers` | automated |
| Sulci add no region value | `test_tissue.test_region_values_unchanged_by_sulci` | automated |
| Highlights are spectrally flat | `test_tissue.test_specular_term_is_flat_across_bands` | automated |
| Same size and seed reproduce the scene | `test_tissue.test_scene_is_deterministic` | automated |
| The legend still disclaims ground truth | `test_tissue.test_region_legend_states_construction_record` | automated |
| The scene reads as a craniotomy | Manual step 1 | manual |
| UC1 and UC2 outputs recorded, not tuned | Manual step 2 | manual |

Tests to add or change, and how each one will be shown to fail first:

- `test_vessel_tree_branches_and_tapers` is written against the current
  sine-track geometry and shown failing, because the current tracks have exactly
  one segment each and a constant half width.
- `test_no_tissue_outside_aperture` is shown failing while the field is an
  ellipse rather than a circle within a rim.

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Render every preset and view the scene image for each | Each reads as a bounded surgical field with a branching vessel tree, not as ribbons on an ellipse | |
| 2 | Run the genuine UC1 runner and the built UC2 binary on one new dataset | Both produce output; whatever each says is recorded as observed, with no parameter changed to improve it | |

## Risks

The scene now looks like something, which makes it easier to mistake for
something. Every existing safeguard - the simulated marker in the header, the
sidecar legend, the banner in SLIAFlow, the wording of the region legend - is
load-bearing in a way it was not when the scene was obviously a drawing. None of
them may be weakened by this card, and the documentation should say plainly that
a more convincing phantom is a greater hazard, not a lesser one.

The second risk is drifting from geometry into tuning. Once the scene looks
right it is tempting to nudge a region parameter because the result map looks
better. That is `SLIA-019`'s prohibition and it applies here unchanged.

## Documentation impact

- `docs/development/synthetic_tissue_phantom.md`: the new geometry, what is
  asserted of it, and the note that a more realistic phantom raises rather than
  lowers the importance of the provenance markers.
- `tools/simulators/README.md`: the scene description, if it names the tracks.

## Completion evidence

Reserved.

## Review findings

Reserved for review.

## Human approval

Required before activation and before completion.
