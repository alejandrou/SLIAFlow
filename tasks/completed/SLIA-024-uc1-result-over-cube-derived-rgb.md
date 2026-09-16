---
id: SLIA-024
title: Show the UC1 result over a colour image derived from its own cube
status: active
branch: feature/SLIA-024-uc1-result-over-cube-derived-rgb
priority: high
depends_on: SLIA-016, SLIA-022, SLIA-023
required_skills: [slicer]
optional_tools: []
related_adrs: [ADR-0001, ADR-0002]
---

# SLIA-024 - Show the UC1 result over a colour image derived from its own cube

## Goal

Close the demonstration loop: camera, capture, cube, UC1, result on screen, with
the class map composited over a colour photograph of the same surgical field
taken from the same cube. This is MS5 point 2.

## Context

Workstream C of `docs/architecture/WP5_MS5_DEMO_PLAN.md`.

UC1 already runs on an announced folder and publishes `UC1_MV_CLASS` on port
18945. `SLIA-023` changes where the cube comes from and nothing else about that
path. What is missing is the background the result is meant to be seen against.

The recorded cases carry a wavelength grid of 440 to 900 nm in 5 nm steps, so
710 nm, 540 nm and 480 nm land on exact grid points - band indices 54, 20 and 8.
Those three bands compose a colour photograph of the field. Because it comes from
the same cube as the map, it agrees with the map pixel for pixel by construction:
same sensor, same capture, same array indices, no registration step that could be
wrong.

The background is never the laptop camera. The camera points somewhere else, and
compositing there would paint a tumour class over whatever is in front of the
laptop. The camera keeps its own LiveView panel, which is where it sits on the
real rig. That distinction is the whole content of `ADR-0001`.

### Why `UC1_RGB` shares port 18945

The plan's port table gave the pseudo-RGB no port, and it needs a transport.
Sending it as a second device name on the UC1 runner's existing connection makes
"same capture" a property of the transport rather than an assumption: one
producer, one cube, one connection, two device names. Two producers on two ports
could each be correct and still be one capture apart, and nothing on screen would
reveal it. It also avoids an eighth port and avoids multiplying the
one-client-at-a-time transport limit recorded in `SLIA-018`.

### What this card inherits and does not fix

UC1 computes five maps and writes one. The other four are discarded because the
write is commented out at `main.cu:164-174`. That is a partner's code; it is on
the request list, the contract already admits all five, and nothing here changes
when they arrive.

## Approval this needs

`ADR-0001` reverses a decision recorded in
`docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md` - *"They are not overlaid
because the laptop RGB image and HSI-derived maps are not registered"* - and
narrows it to forbid overlay on an unregistered background while permitting it on
a cube-derived one.

`ADR-0001` was accepted on 2026-09-15. The card was activated on 2026-09-16 under
`Start the next task`, as step 5 of the execution order in
`docs/architecture/WP5_MS5_DEMO_PLAN.md`.

The review of 2026-09-16 found that the size-mismatch refinement below
contradicted rule 4 of the accepted `ADR-0001`, which a task card may not do. The
project owner chose to supersede that rule, and to enforce "same capture" with a
capture identifier. Both are recorded in
`docs/architecture/decisions/ADR-0002-uc1-background-capture-identity-and-mismatch.md`,
which the project owner accepted on 2026-09-16.

## Specification refinements at activation

Settled on 2026-09-16 from the code as it stands after `SLIA-022` and `SLIA-023`.
None of them loosens a guard; each one either makes a rule exact or picks the
more conservative of two readings.

- **Band tolerance is 2.5 nm**, half the recorded grid's 5 nm step. On a recorded
  case 710, 540 and 480 nm resolve exactly to indices 54, 20 and 8.
- **Fixed scaling.** The calibrated cube is `100 * reflectance`, the quantity UC1
  computes. Each of the three bands is mapped as
  `round(clip(value / 100, 0, 1) * 255)`: reflectance 0 is black and reflectance 1
  is full scale, for every capture. There is no per-image stretch, so two captures
  of the same tissue are displayed on the same scale.
- **A refused background does not stop the map.** When the header has no
  wavelengths or a band misses its target, the runner says so on stderr before the
  GPU run and sends `UC1_MV_CLASS` alone. `UC1_RGB` is never sent from a guessed
  band. The consumer already treats an absent background as the ordinary case.
- **A size mismatch shows the map alone.** The delineation view is one panel, and
  every other panel has its own role, so there is no place to put the two images
  side by side. On a mismatch the class map is displayed exactly as it is today,
  the background is not shown, and the layer status names both sizes. This
  replaced "shown side by side" in the requirement below under `ADR-0002`,
  which supersedes rule 4 of `ADR-0001` and which the owner accepted on
  2026-09-16. Recorded at activation as a card refinement, which was not enough
  on its own: see Review findings.
- **Background provenance must equal the map's.** The consumer composites only
  when the background's origin and simulation detail are identical to the map's
  it is drawn under. Otherwise the map is shown alone with a status. This is the
  consumer-side reading of "carries the same provenance".
- **The background has no result role.** `UC1_RGB` carries device name, origin
  and simulation detail, and no `SLIAFlow.ResultMap`, so it can never be
  discovered as a result.
- **Background lookup is by exact device name only**, never by volume type. A
  node owned by the module (the laptop camera volume included) or declaring the
  `LiveView` device is never accepted, whatever it is named.
- **Wire shape.** `UC1_RGB` is `(1, lines, samples, 3)` `uint8`, the same
  `(k, j, i)` layout as the `(1, lines, samples)` class map, so both arrive with
  identical dimensions for identical cube geometry.
- **Capture identity (added after review, `ADR-0002`).** Every UC1 result map
  carries a newly generated, non-empty `SLIAFlow.CaptureId`, whether or not a
  background is sent; a `UC1_RGB`, when sent, carries the same one. Both
  producers, the runner and the arithmetic stand-in, make one per run - one run
  classifies once - and resend it unchanged in every cycle. The contract's
  metadata builders refuse an empty one. SLIAFlow composites only when map and
  background carry the same non-empty value, and chooses, among every `UC1_RGB`
  in the scene, the one whose capture ID matches the map's. The ID is mandatory
  on maps because OpenIGTLinkIF reuses a node per device name and never removes
  a metadata attribute a later message omits: a map sent without an ID would
  keep the previous run's, and match that run's retained background.
- **Non-finite wavelengths are refused (added after review).** A header whose
  wavelength list contains NaN or infinity is refused like one without
  wavelengths, because a nearest-band search over it can pick an invalid band
  and pass the tolerance check.
- **`SLIAFlowParameterNode.py` is added to `Files allowed`** for the `UC1_RGB`
  device constant and the background presentation node reference, where every
  other device name and reference already lives.

## Requirements

### The producer side

- The UC1 runner composes a three-band colour image from the cube it just
  classified and sends it as device `UC1_RGB` on the same connection as
  `UC1_MV_CLASS`, in the same cycle.
- The three bands are selected **by wavelength** against the header's own
  wavelength list - 710, 540 and 480 nm - and the runner refuses rather than
  guesses when the header carries no wavelengths or when the nearest band misses
  its target by more than a stated tolerance.
- Each run reports which band index every requested wavelength resolved to and by
  how much it missed.
- `UC1_RGB` carries the same provenance as the map it accompanies: origin
  `simulated`, and the simulation detail `SLIA-023` gives the case.
- The composition is a plain three-band assembly with a stated, fixed scaling. It
  is a viewing aid, not a colour-accurate rendering, and the module docstring
  says so.

### The consumer side

- The delineation panel composites `UC1_MV_CLASS` as a foreground layer over
  `UC1_RGB`, with an opacity control.
- **The only safeguard is a size comparison.** If the two images do not have the
  same dimensions they are not composited; the map is shown alone and the
  status names both sizes (`ADR-0002`, accepted 2026-09-16, replacing the
  side-by-side presentation of `ADR-0001` rule 4). SLIAFlow performs no
  registration, resampling or alignment.
- A result whose background has not arrived is displayed alone with its banner,
  exactly as today. The overlay is an addition, never a precondition for display.
- The laptop camera node is never accepted as an overlay background for any
  result role.
- Every safety behaviour is preserved without exception: the simulated banner,
  the transient never-persisted demo-mode opt-in, genuine-over-simulated
  precedence, provenance travelling with the data and never with the endpoint,
  and a black view with an explicit status for missing or invalid data.
- `UC1_RGB` is added to the OpenIGTLink contract table with its component count
  and data type.

## Out of scope

- Any change to UC1, UC2 or `AcquisitionSystemApp` in any copy.
- The four maps UC1 discards.
- Registration, resampling, orientation and the IJK-to-LPS mapping. `ADR-0001`
  records why orientation is consistent without being defined, and leaves the
  definition to its own investigation.
- UC2's layer, which is `SLIA-021`.
- The six-panel layout itself, which is `SLIA-022`. This card fills one of its
  panels.
- Colour bar, capture selection and result saving.
- Any metric computed against `gtMap`.

## Files allowed

- `tools/simulators/stratum_sim/uc1_runner.py`
- `tools/simulators/stratum_sim/contract.py`
- `tools/simulators/tests/test_uc1_runner.py`
- `tools/simulators/tests/test_contract.py`
- `tools/simulators/README.md`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowParameterNode.py`
- `extensions/SLIAFlow/SLIAFlow/Resources/UI/SLIAFlow.ui`
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`
- `docs/architecture/WP5_MS5_DEMO_PLAN.md`
- `docs/architecture/decisions/ADR-0002-uc1-background-capture-identity-and-mismatch.md`
  (added after review, 2026-09-16, owner decision)
- `tools/simulators/stratum_sim/uc1_sim.py`
- `tools/simulators/tests/test_uc1_sim.py`
  (both added after the owner's review of `ADR-0002`, 2026-09-16, which requires
  the arithmetic stand-in to send a capture ID on its maps)
- `docs/architecture/decisions/ADR-0001-overlay-result-on-cube-derived-rgb.md`
  (added when the owner accepted `ADR-0002`, 2026-09-16, for the
  `superseded_in_part_by` field and notes that the owner's review asked for;
  no other change)
- `tasks/{backlog,active,review,completed}/SLIA-024-uc1-result-over-cube-derived-rgb.md`

## Relevant skills and references

- `docs/architecture/decisions/ADR-0001-overlay-result-on-cube-derived-rgb.md`
- `docs/architecture/WP5_MS5_DEMO_PLAN.md`, workstream C
- `tools/simulators/stratum_sim/uc1_runner.py`, `mapMessages` and
  `simulationDetailForDataset`
- `.ai/policies/algorithm-boundary-policy.md`
- WP2 EPIC 4, for what the layered view is asked to offer

## Approved dependencies

None.

## Implementation plan

1. Write the wavelength resolver and its two refusal cases first, against a
   header with no wavelengths and a header whose nearest band misses.
2. Send `UC1_RGB` beside the map and prove both carry the same provenance and
   arrive in the same cycle.
3. Write the size-mismatch test on the consumer side and show it failing.
4. Add the layered presentation and the opacity control.
5. Re-run the whole existing SLIAFlow safety suite unmodified.

## Acceptance criteria

- The runner sends `UC1_RGB` and `UC1_MV_CLASS` from the same cube in one cycle,
  with identical provenance.
- Bands are resolved by wavelength, the resolution is reported, and a header
  without wavelengths is refused rather than defaulted.
- A class map is composited over its cube-derived background with a working
  opacity control.
- Two images of different dimensions are not composited and produce an explicit
  status.
- The laptop camera is never used as an overlay background.
- Every existing safety test passes unmodified.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| Bands resolve to the nearest by wavelength | `test_uc1_runner.test_resolvesRgbBandsByWavelength` | automated |
| A header without wavelengths is refused | `test_uc1_runner.test_refusesRgbWithoutWavelengths` | automated |
| A band too far from target is refused | `test_uc1_runner.test_refusesWhenNearestRgbBandExceedsTolerance` | automated |
| Map and background share provenance and cycle | `test_uc1_runner.test_rgbAccompaniesMapWithSameProvenance` | automated |
| The RGB is a fixed-scale three-band assembly | `test_uc1_runner.test_rgbUsesFixedReflectanceScaling` | automated |
| A refused background still sends the map | `test_uc1_runner.test_refusedRgbStillSendsMap` | automated |
| `UC1_RGB` metadata has no result role | `test_contract.test_uc1RgbMetadataCarriesNoResultRole` | automated |
| A matching background is composited under the map | `SLIAFlowTest.test_backgroundIsCompositedUnderClassMap` | automated |
| Mismatched sizes are not composited | `SLIAFlowTest.test_mismatchedBackgroundIsNotComposited` | automated |
| A background with different provenance is not composited | `SLIAFlowTest.test_backgroundWithDifferentProvenanceIsNotComposited` | automated |
| The camera is never an overlay background | `SLIAFlowTest.test_cameraNodeIsNeverAnOverlayBackground` | automated |
| A background from another capture is not composited | `SLIAFlowTest.test_backgroundFromAnotherCaptureIsNotComposited` | automated |
| Among several backgrounds, the map's own capture is chosen | `SLIAFlowTest.test_backgroundMatchingTheMapsCaptureIsChosen` | automated |
| Map and background share one capture ID per run | `test_uc1_runner.test_rgbAndMapShareOneCaptureIdPerRun` | automated |
| Non-finite wavelengths are refused | `test_uc1_runner.test_refusesNonFiniteWavelengths` | automated |
| Map and background metadata require a non-empty capture ID | `test_contract.test_captureIdIsRequiredOnMapAndBackground` | automated |
| A map sent without a background still carries the run's capture ID | `test_uc1_runner.test_mapSentAloneStillCarriesTheRunsCaptureId` | automated |
| The stand-in sends one capture ID per run on every map | `test_uc1_sim.test_everyMapCarriesOneCaptureIdPerRun` | automated |
| A later map-only run never reuses an earlier run's background | `SLIAFlowTest.test_laterMapOnlyRunDoesNotReuseTheEarlierBackground` | automated |
| Banner, demo mode, precedence, black view | existing `SLIAFlowTest` safety tests, unmodified | automated |
| The overlay reads correctly by eye | Manual step 1 | manual |
| Opacity works across its range | Manual step 2 | manual |
| A missing background still shows the result | Manual step 3 | manual |

Tests to add or change, and how each one will be shown to fail first:

- `test_mismatchedBackgroundIsNotComposited` is written before the size check
  exists and shown compositing two differently sized images, so the check is
  demonstrated to be the thing that stops it.
- `test_cameraNodeIsNeverAnOverlayBackground` is shown failing against a first
  implementation that accepts any RGB volume as a background.
- No existing safety test may be modified by this card. If one needs modifying,
  that is the signal that a guard is being changed and the card stops.

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Run a full session on a recorded case and look at the delineation panel | The class map sits over a recognisable colour image of the same field; structures in the map follow structures in the background; the Background line says the map is composited | PASS, 2026-09-16. Case `004-02` ran through the genuine UC1 producer. `UC1_MV_CLASS` and `UC1_RGB` were displayed with matching `(1, 389, 345)` geometry, matching simulated provenance and detail, and the same non-empty capture ID. The panel read `The map is composited over UC1_RGB, three bands of its own cube.` The 50% view showed the class structures aligned with the colour field. |
| 2 | Move the opacity control from 0 to 100 per cent | The background is visible alone at one end, the map alone at the other, and every intermediate value is stable | PASS, 2026-09-16. Values 0, 25, 50, 75 and 100% were applied. At 0% the cube-derived colour field was recognisable; at 100% the class map was shown alone; the 50% overlay was stable. The result status stayed PASS and the composited Background line remained unchanged at every value. |
| 3 | Serve the same recorded case with the arithmetic stand-in (`uc1`), which sends `UC1_MV_CLASS` and never `UC1_RGB`, and look at the delineation panel. The stand-in refuses a case without the `STRATUM SIMULATED CUBE` marker, and recorded cases do not carry it (`SLIA-023` opened that guard for the genuine runner only), so this step uses `--force-unmarked`, approved by the project owner on 2026-09-16 for this check on public anonymized case `004-02` only | The result is displayed alone under its banner, with no empty or black overlay layer; the Background line says no `UC1_RGB` has arrived | PASS with the owner-approved override, 2026-09-16. First run, before the override was part of the step: the stand-in command exited 1 before listening, as its guard intends: `raw.hdr lacks the STRATUM SIMULATED CUBE marker`. With `--force-unmarked` on the public anonymized case `004-02`, the stand-in sent `UC1_MV_CLASS` and no `UC1_RGB`; SLIAFlow reconnected and displayed the map alone under its banner, with no background node. The Background line read `No UC1_RGB from the map's capture has arrived. A background from another capture is never used; the map is shown alone.` The owner then approved the override for this step instead of changing the stand-in, which `SLIA-025` retires. |
| 4 | Confirm the banner is present in every state of steps 1 to 3 | The simulated banner is on screen throughout; no screenshot is taken of a result without it | PASS, 2026-09-16. The banner was visible in the genuine overlay, at every tested opacity, and in the arithmetic stand-in map-only state; no result view was observed without it. |

## Risks

The overlay is the one feature in this project that can place a class label over
anatomy it was not computed from, and a wrong overlay looks exactly like a right
one. Every defence is structural rather than visual: the background comes from the
same producer, the same cube and the same connection as the map, and the only
run-time check is a refusal to composite mismatched sizes. The tempting
improvement - resample the result onto the background so a mismatch is repaired
rather than refused - would put a geometric transform inside a module whose whole
design rests on never altering a result, and is forbidden by `ADR-0001`.

A background that makes the scene look convincing raises the stakes on the
provenance markers rather than lowering them, in exactly the way `SLIA-020`
records for the phantom. The banner tests are re-run unmodified for that reason.

The pseudo-RGB is a three-band assembly, not a colour-accurate rendering. If it
is described as "the RGB image" anywhere in the panel or the documentation, a
viewer may take it for the microscope's own view, which it is not.

## Documentation impact

- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`: `UC1_RGB` in the
  contract table; the user-visible behaviour section rewritten to state the
  narrowed overlay rule and point at `ADR-0001`.
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`: the background layer, the
  size check and what is not done.
- `tools/simulators/README.md`: the `UC1_RGB` device, its band selection and its
  refusals.
- `docs/architecture/WP5_MS5_DEMO_PLAN.md`: mark workstream C done.

## Completion evidence

### Implementation, 2026-09-16

Branch `feature/SLIA-024-uc1-result-over-cube-derived-rgb`, from `main` at
`dbb2e47`. Nothing is committed.

Producer (`tools/simulators/stratum_sim/`):

- `contract.py`: `UC1_RGB_DEVICE_NAME` and `uc1RgbMetadata`, which carries device,
  origin and detail and no result role.
- `uc1_runner.py`: `resolveRgbBands` (by wavelength, 2.5 nm tolerance, refuses a
  header with no or mismatched wavelengths), `describeRgbBands`,
  `loadRgbBackground` (reads only the three bands, UC1's calibration, fixed
  reflectance scaling), `prepareRgbBackground` (before the GPU run; a refusal is a
  stderr `WARNING` and the map is still sent). `mapMessages` and `sendMaps` send
  `UC1_RGB` before the map when there is a background.

Consumer (`extensions/SLIAFlow/SLIAFlow/`):

- `SLIAFlowParameterNode.py`: `UC1_RGB_DEVICE_NAME`, and the
  `resultBackgroundSourceVolume` / `resultBackgroundVolume` references.
- `SLIAFlowLogic.py`: `isResultBackgroundCandidate` (exact device name only; never
  a module-owned node or a node with a result role), `findResultBackgroundSource`,
  `presentResultBackground` (class map only; three-component `uint8`; origin and
  detail identical; dimensions identical; otherwise the map stands alone), and
  the owned `SLIAFlow UC1 Background` node.
- `SLIAFlowWidget.py`: the background is decided after the map passes and before
  the single view flush; `_bindLayer` puts the background in the background slot
  and the map in the foreground at the layer opacity; every path that withdraws
  the map withdraws its background.
- `Resources/UI/SLIAFlow.ui`: a read-only **Background** line under the result
  source. No new interactive control; the opacity control is SLIA-022's.

Docs: `SLIAFLOW_IMPLEMENTATION_ROADMAP.md`, `SLIAFLOW_UC1_IMAGE_CONTRACT.md`,
`WP5_MS5_DEMO_PLAN.md`, `tools/simulators/README.md`.

One existing producer test was changed mechanically:
`test_servicePropagatesBothDatasetSceneDetails` patches `sendMaps` with a lambda,
which now also accepts the new positional background argument. What it asserts is
unchanged. No `SLIAFlowTest` test was modified.

Manual step 3 was reworded at implementation: the genuine runner sends the
background and the map in one cycle, so "stop the runner before a background
arrives" cannot be staged with it. The stand-in, which never sends `UC1_RGB`, is
the producer that shows a map without one.

### Automated tests

| Command | Result | Exit |
| --- | --- | ---: |
| `.venv\Scripts\python.exe tools\simulators\tests\run_tests.py` | 167 tests, OK | 0 |
| `scripts\development\run-python-quality.ps1` | Ruff: both targets, all checks passed | 0 |
| `scripts\development\run-slicer-tests.ps1 -Headful` (Source) | 71 tests, OK, 1 skipped (`test_headlessPresentationFallback`, headless-only) | 0 |
| `scripts\development\run-slicer-tests.ps1` (Source, headless) | 71 tests, OK, 7 skipped (headful-only) | 0 |

`main` defines 67 `SLIAFlowTest` tests; 67 + 4 new = 71, all run.

The Build target was not run: the build copy under `build/SLIAFlow/` has not
been rebuilt for this change, and testing it would test the previous snapshot.

### Observed failing first

Producer tests, first run before any implementation: all seven red (six on
missing symbols; `test_refusedRgbStillSendsMap` on
`AssertionError: Lists differ` because nothing was sent). The first
implementation then exposed a wrong test, not wrong code:
`test_refusesWhenNearestRgbBandExceedsTolerance` used a 5 nm grid shifted by
3 nm, on which no target can miss by more than 2.5 nm. It now uses a 10 nm grid.

Because the Slicer tests were written after the logic, each was run against a
mutated copy of the module in the session scratchpad, loaded through
`--additional-module-paths` and confirmed by the loaded-path line:

| Test | Mutation | Failure observed |
| --- | --- | --- |
| `test_mismatchedBackgroundIsNotComposited` | size check removed | `AssertionError: <vtkMRMLVectorVolumeNode ...> is not None` (a background was composited) |
| `test_cameraNodeIsNeverAnOverlayBackground` | any three-component RGB volume accepted | `AssertionError: <vtkMRMLVectorVolumeNode ...> is not None` |
| `test_backgroundWithDifferentProvenanceIsNotComposited` | provenance check removed | fails in all three sub-cases |
| `test_backgroundIsCompositedUnderClassMap` | widget binds without the background | `'vtkMRMLScalarVolumeNode2' != 'vtkMRMLVectorVolumeNode2'` |

Producer tests against wrong implementations, patched in-process:

| Test | Mutation | Failure observed |
| --- | --- | --- |
| `test_rgbUsesFixedReflectanceScaling` | per-image min-max stretch | array mismatch (64 became 255) |
| `test_refusesWhenNearestRgbBandExceedsTolerance` | no tolerance | `Uc1RgbBandError not raised` |
| `test_refusesRgbWithoutWavelengths` | fixed indices 54, 20, 8 | `Uc1RgbBandError not raised` |
| `test_rgbAccompaniesMapWithSameProvenance` | background given a result role | `'SLIAFlow.ResultMap' unexpectedly found` |

### Genuine pipeline smoke, not manual verification

`python -m stratum_sim uc1-real input\bin\bin\004-02 --port 18995 --cycles 5`
on the local GPU, with `tests\uc1_client.py --port 18995 --session-seconds 4`:

- Runner: `UC1_RGB bands: 710 nm -> index 54 at 710 nm (miss 0.00 nm); 540 nm ->
  index 20 at 540 nm (miss 0.00 nm); 480 nm -> index 8 at 480 nm (miss 0.00 nm)`.
  Class map `(1, 389, 345)`: 1: 41.7%, 2: 5.9%, 3: 23.5%, 4: 28.8%.
- Client: `UC1_RGB` `(1, 389, 345, 3)` `uint8` and `UC1_MV_CLASS` `(1, 389, 345)`
  `uint8`, 4 messages each in 4 s, identical `SLIAFlow.DataOrigin` and
  `SLIAFlow.SimulationDetail`, no `SLIAFlow.ResultMap` on `UC1_RGB`.
- Measured on the same case without the GPU: assembling the background takes
  about 14 ms. Channel means 177.7 / 55.7 / 67.2; 16.8% of red pixels sit at 255,
  2.1% of green and 2.4% of blue. The red saturation is fixed-scale clipping of
  reflectance above 1, reported and not compensated for.

The client disconnecting after four cycles left the runner waiting for its fifth;
it was stopped by hand. The `ConnectionAbortedError` traceback it printed on the
disconnect is the transport's existing logging.

### Review follow-up, 2026-09-16

Findings 1, 3 and 4 fixed and finding 2 referred to `ADR-0002` (see Review
findings). Changes:

- `contract.py`: `METADATA_CAPTURE_ID_KEY`; `uc1RgbMetadata` and
  `resultMapMetadata` take an optional `captureId` and send no key without one.
- `uc1_runner.py`: `newCaptureId`, made once per run in `streamMaps` and passed
  through `sendMaps` and `mapMessages` to both messages; `resolveRgbBands`
  refuses a non-finite wavelength.
- `SLIAFlowParameterNode.py`: `RESULT_SOURCE_CAPTURE_ATTRIBUTE`, added to
  `RESULT_SOURCE_ATTRIBUTES` so wire translation carries it.
- `SLIAFlowLogic.py`: `findResultBackgroundSources` (every candidate) and
  `findResultBackgroundSource(captureId)` (only the map's capture);
  `presentResultBackground` reports `captureMismatch` when the map has no capture
  ID or no candidate carries it.
- `SLIAFlowTest.py`: the shared helper `_receivedResultVolume` gained an optional
  `captureId` keyword, default unchanged, so existing callers send what they sent
  before. This card's own helpers default to a fixed capture ID, and
  `test_cameraNodeIsNeverAnOverlayBackground` now asserts that
  `findResultBackgroundSources()` is empty. No pre-existing test was modified.
- `ADR-0002` written as proposed; contract document, roadmap, demo plan and
  simulators README updated.

Observed failing first, before any logic change:

| Test | Failure observed |
| --- | --- |
| `test_uc1_runner.test_refusesNonFiniteWavelengths` | `Uc1RgbBandError not raised`, for NaN and for infinity |
| `test_uc1_runner.test_rgbAndMapShareOneCaptureIdPerRun` | `AssertionError: None is not true` (no capture ID sent) |
| `test_contract.test_captureIdIsCarriedWhenGiven` | `TypeError: ... unexpected keyword argument 'captureId'` |
| `SLIAFlowTest.test_backgroundFromAnotherCaptureIsNotComposited` | all four sub-cases composited the other capture's background (`... is not None`) |
| `SLIAFlowTest.test_backgroundMatchingTheMapsCaptureIsChosen` | with the stale node first, it was chosen (`'vtkMRMLVectorVolumeNode1' != 'vtkMRMLVectorVolumeNode2'`) |
| `SLIAFlowTest.test_cameraNodeIsNeverAnOverlayBackground` | `AttributeError: ... no attribute 'findResultBackgroundSources'` |

The first Slicer red run was not accepted as evidence:
`test_backgroundFromAnotherCaptureIsNotComposited` failed on `'WARN' != 'PASS'`
because it enabled demo mode before `slicer.mrmlScene.Clear()`, which withdraws
it. The test was corrected and rerun, and failed for the reason above.

| Command | Result | Exit |
| --- | --- | ---: |
| `.venv\Scripts\python.exe tools\simulators\tests\run_tests.py` | 170 tests, OK | 0 |
| `scripts\development\run-python-quality.ps1` | Ruff: all checks passed | 0 |
| `scripts\development\run-slicer-tests.ps1 -Headful` (Source) | 73 tests, OK, 1 skipped | 0 |
| `scripts\development\run-slicer-tests.ps1` (Source, headless) | 73 tests, OK, 7 skipped | 0 |

Genuine pipeline on the wire, `uc1-real` on `004-02`, port 18995, 3 cycles, read
with `tests\uc1_client.py --session-seconds 6` (client exit 0, runner exited
after its 3 cycles): `UC1_RGB` `(1, 389, 345, 3)` and `UC1_MV_CLASS`
`(1, 389, 345)`, 3 messages each, both carrying
`SLIAFlow.CaptureId = e346201fd9194de78e81e685ff7499a3` with identical origin and
detail.

### Owner review of `ADR-0002`, 2026-09-16

The owner's review of the first `ADR-0002` draft (see Review findings) made the
capture ID mandatory on every UC1 map. This supersedes the previous section's
statement that the metadata builders send no key without an ID.

Checked before changing anything: in OpenIGTLinkIF
`MRML/vtkMRMLIGTLConnectorNode.cxx` (checkout at `85e5f76`, 2026-06-03), incoming
metadata is copied onto the node with
`modifiedNode->SetAttribute("OpenIGTLink." + key, value)` for each key present,
and nothing removes an attribute. SLIAFlow's `normalizeReceivedProvenance`
mirrors those prefixed attributes, so a retained one is still read.

Changes:

- `contract.py`: `newCaptureId` moved here from `uc1_runner.py`, so both
  producers share it. `uc1RgbMetadata` and `resultMapMetadata` take `captureId`
  as a required keyword and raise `ValueError` for an empty, blank or non-string
  value.
- `uc1_runner.py`: uses `contract.newCaptureId`. `mapMessages` and `sendMaps`
  default `captureId` to `None`, which makes a new ID for that call, so the four
  existing direct callers in the tests keep working and never send a map without
  an ID. `streamMaps` still passes one ID per run.
- `uc1_sim.py`: `streamMaps` makes one ID per run and passes it through
  `sendMaps` and `mapMessages` to all five maps, with the same `None` default.
- `SLIAFlowLogic.py` and `SLIAFlowWidget.py`: unchanged. The consumer rule was
  already an exact non-empty match.
- `ADR-0002` revised: the ID is mandatory on every map; identity scope; a section
  on what the consumer can enforce, and why; the Status sentence completed;
  Validation covers a map-only run after a map-plus-background run.
- Contract document (five wire keys, the ID required on every map, the connector
  behaviour), simulators README (the stand-in's ID, the client's five keys), and
  demo plan.

Existing tests changed:

- `test_uc1_runner.test_realRunnerSendsOnlyTheClassMapWithCompleteProvenance`,
  which predates this card and compares the map's metadata exactly. It now
  requires a non-empty `SLIAFlow.CaptureId`, removes it, and compares the other
  four keys exactly as before. Nothing it checked before was relaxed.
- `test_contract.test_uc1RgbMetadataCarriesNoResultRole`, added by this card,
  now passes an ID and expects it.
- `test_contract.test_captureIdIsCarriedWhenGiven`, added by this card, is
  replaced by `test_captureIdIsRequiredOnMapAndBackground`, because the
  behaviour it asserted, no key without an ID, is the one the review removed.

Observed failing first, before any code change: 173 tests, 10 failures, 1
error, exit 1.

| Test | Failure observed |
| --- | --- |
| `test_contract.test_captureIdIsRequiredOnMapAndBackground` | 8 subtests: `TypeError not raised` without the keyword and `ValueError not raised` for `""`, `"   "` and `None`, on both builders |
| `test_contract.test_newCaptureIdIsNonEmptyAndNeverRepeats` | `AttributeError: module 'stratum_sim.contract' has no attribute 'newCaptureId'` |
| `test_uc1_sim.test_everyMapCarriesOneCaptureIdPerRun` | `AssertionError: None is not true` (the stand-in sent no ID) |
| `test_uc1_runner.test_realRunnerSendsOnlyTheClassMapWithCompleteProvenance` | `mapMessages` called without an ID sent none |

Not seen failing, and why:

- `test_uc1_runner.test_mapSentAloneStillCarriesTheRunsCaptureId` passed on its
  first run. The runner already put the run's ID on the map when it refused the
  background. The test guards that behaviour; it did not expose a defect.
- `SLIAFlowTest.test_laterMapOnlyRunDoesNotReuseTheEarlierBackground` passed on
  its first run, because the consumer was not changed. It reproduces the
  sequence the review describes: the map node overwritten with a new ID, and the
  earlier `UC1_RGB` retained. The consumer's capture check was already shown
  failing without the ID by `test_backgroundFromAnotherCaptureIsNotComposited`
  in the previous section.

| Command | Result | Exit |
| --- | --- | ---: |
| `.venv\Scripts\python.exe tools\simulators\tests\run_tests.py` | 173 tests, OK | 0 |
| `scripts\development\run-python-quality.ps1` | Ruff: all checks passed | 0 |
| `scripts\development\run-slicer-tests.ps1 -Headful` (Source) | 74 tests, OK, 1 skipped | 0 |
| `scripts\development\run-slicer-tests.ps1` (Source, headless) | 74 tests, OK, 7 skipped; the new test ran in both modes | 0 |

Not run: the wire smoke was not repeated. The runner's send path changed only in
where `newCaptureId` lives, and the previous smoke showed one ID on both
messages. The stand-in was not run on the wire, because it needs a dataset
carrying the simulated-cube marker.

### Not yet done

- Moving the card to review, independent AI review, human approval and
  completion. Nothing is committed; moving and committing each need the owner's
  authorization.

### ADR acceptance and manual verification, 2026-09-16

- `ADR-0002` accepted by the owner on 2026-09-16. Applied: `ADR-0002`
  `status: accepted` and `accepted: 2026-09-16`; `ADR-0001` added to
  `Files allowed`, then given `superseded_in_part_by: ADR-0002` and notes at its
  Status, rule 4 and first Validation bullet; "(proposed)" removed from the
  contract document and the demo plan. No code or test changed.
- Manual verification was performed on 2026-09-16 with
  `build\SLIAFlow\SlicerWithSLIAFlow.exe` (Slicer `5.13.0-2026-07-02`); the
  scripted module was reloaded before connecting, and recorded case `004-02`
  was used. Steps 1 to 4 passed. Step 3 needed `--force-unmarked`, because the
  stand-in refuses a case without the simulated-cube marker; the owner approved
  the override for that check on 2026-09-16, and step 3 was amended to name it.
  No code changed.
- Manual evidence used the local Slicer MCP bridge only for visible UI actions,
  state inspection and screenshots. The input was the public anonymized case
  `004-02`; no private or identifiable medical data was used.

## Review findings

### Review of 2026-09-16, before manual verification

| # | Severity | Finding | Disposition |
| --- | --- | --- | --- |
| 1 | High | "Same capture" was not enforced: a retained `UC1_RGB` from an earlier run, with the same origin, detail and size, would be composited under a later map sent without one | Fixed: `SLIAFlow.CaptureId`, one per run, on both messages; composited only on an exact non-empty match (`ADR-0002`) |
| 2 | High | Showing the map alone on a size mismatch contradicts rule 4 of accepted `ADR-0001` ("side by side"); a card refinement cannot override an ADR | Owner chose to supersede rule 4: `ADR-0002`, accepted 2026-09-16. Code unchanged |
| 3 | Medium | A NaN wavelength passes the tolerance guard (`argmin` picks it, `NaN > 2.5` is false), so all three channels can resolve to one invalid band | Fixed: non-finite wavelengths are refused |
| 4 | Medium | `findResultBackgroundSource` returned the first `UC1_RGB`, so a stale one could hide the matching one, or be composited if its metadata happened to match | Fixed: the candidate whose capture ID matches the map's is chosen |
| 5 | Medium-low | The wire and render path is unverified end to end: producer tests mock the server, consumer tests inject nodes | Closed by the 2026-09-16 manual run: steps 1 to 4 passed, step 3 with the owner-approved `--force-unmarked` on case `004-02` |

### Owner review of proposed `ADR-0002`, 2026-09-16

| # | Severity | Finding | Disposition |
| --- | --- | --- | --- |
| 1 | High | The capture ID was optional for producers without a background. OpenIGTLinkIF sets each incoming metadata key on the reused node and never removes an omitted one, so a map-only run after a map-plus-background run keeps the old ID and matches the retained background | Fixed: the ID is required on every UC1 map; the contract builders refuse an empty one; the stand-in generates one per run |
| 2 | High | "A map without a capture ID is never composited" promised more than SLIAFlow can see, since it observes a persistent node, not the message | Fixed in `ADR-0002`: the connector behaviour is documented, and the guarantee is stated as resting on producers sending the ID on every map |
| 3 | Medium | Showing a mismatched map alone is supported | No change |
| 4 | Medium | Identity scope was stated loosely | Fixed in `ADR-0002`: an ID is never reused for another cube or another classification; retransmissions of one computed result reuse it |
| 5 | Low | ADR bookkeeping | `related_adrs` updated and the incomplete Status sentence fixed now; Validation covers the map-only-after-background sequence. On acceptance, 2026-09-16: `accepted:` filled in, and `ADR-0001` added to `Files allowed` and given `superseded_in_part_by` |

## Human approval

Required before activation, because `ADR-0001` must be accepted first, and again
before completion.
