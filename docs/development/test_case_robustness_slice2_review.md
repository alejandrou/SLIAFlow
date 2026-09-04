# Test-case robustness audit: Slice 2 review

Date: 2026-09-04

## Scope

This change implements only Slice 2 from
`docs/development/test_case_robustness_audit.md`: TST-005 through TST-008 and
the Slice 2 portion of TST-011. The project owner explicitly requested
implementation without a task card, so no task was selected, created, or
moved. No production code changed.

The existing branch `review/test-case-robustness-audit` was used. No Git branch
or history mutation was performed. The existing Slice 1 changes were preserved.

## Files reviewed

- `docs/development/test_case_robustness_audit.md`
- `docs/development/test_case_robustness_slice1_review.md`
- `tools/simulators/tests/test_uc1_runner.py`
- `tools/simulators/tests/test_tissue.py`
- `tools/simulators/tests/support.py`
- `tools/simulators/tests/run_tests.py`
- `tools/simulators/stratum_sim/uc1_runner.py`
- `tools/simulators/stratum_sim/tissue.py`
- `tools/simulators/stratum_sim/spectra.py`

## Changes

| Finding | Test change | Review result |
| --- | --- | --- |
| TST-005 | Replaced the all-stale and first-missing cases with subtests that make exactly one of `red.txt`, `green.txt`, `blue.txt`, and `imageRGB.bmp` stale or missing. | Every required output is independently observable; validation order can no longer hide an omitted check. |
| TST-006 | Replaced horizontal adjacency and its `0.5` threshold with an independent four-neighbor flood-fill count. The expected 48x64 topology is pinned per semantic region. | Disconnected regions fail even when most pixels have a same-label neighbor. The expected counts account for vessel drawing order splitting the cortex and tumour labels and for two vessel tracks meeting at this resolution. |
| TST-007 | Reconstructed the documented craniotomy ellipse from test-side geometry pins and checked every tumour/vessel pixel against that mask. The outside-field drape is also checked. | A region outside the field but away from the image border now fails. |
| TST-008 | Added a fixed 2x2, three-band projection oracle with independently evaluated BGR bytes, a one-voxel perturbation with a spatially attributable output change, and retained green-region ordering as a separate scene-level property. | A renderer that ignores its cube or reverses output channels can no longer pass. |
| TST-011 | Table-drove empty, malformed, and individual shape-mismatch cases across all three channel files. Missing/stale isolation includes the class BMP. Missing and wrong-size checks now cover every staged model file. | Each parsing, output-validation, and model-validation loop member is exercised independently. Model failures are verified to occur before process execution. |

Files modified:

- `tools/simulators/tests/test_uc1_runner.py`
- `tools/simulators/tests/test_tissue.py`

File created:

- `docs/development/test_case_robustness_slice2_review.md`

## Red-first mutation evidence

The mutations were applied in memory with `unittest.mock`; repository files
were not changed by the probes.

| Probe | Defect reproduced | Result |
| --- | --- | --- |
| TST-005 first-output-only freshness | `_assertFresh` inspected only the first required path. | RED confirmed: 3 failures. |
| TST-005 first-output-only existence | `_assertFresh` inspected only the first required path. | RED confirmed: 1 failure and 2 errors; later missing files escaped the required domain exception. |
| TST-011 first-model-only missing check | Model validation inspected only the weight vector. | RED confirmed: 4 failures. |
| TST-011 first-model-only size check | Model validation inspected only the weight vector. | RED confirmed: 4 failures. |
| TST-006 disconnected topology | Added an isolated tumour pixel inside a cortex area. | RED confirmed: 1 failure. |
| TST-007 field containment | Added a tumour pixel outside the field but away from the image edge. | RED confirmed: 1 failure. |
| TST-008 input-independent rendering | Returned the fixed oracle frame for both the baseline and perturbed cubes. | RED confirmed: 1 failure. |
| TST-008 reversed channels | Reversed the projected BGR channel order. | RED confirmed: 1 failure. |

The malformed, empty, and shape-mismatch channel cases also directly exercise
all three channel names; they do not require a repository mutation to reach
their negative paths.

## Validation

| Command/check | Result | Exit code |
| --- | --- | --- |
| `..\..\.venv\Scripts\python.exe -m unittest tests.test_uc1_runner tests.test_tissue` from `tools/simulators` | 45 focused tests passed. | 0 |
| `.\.venv\Scripts\python.exe tools\simulators\tests\run_tests.py` | 87 tests passed, including the staged real-binary GPU integration. | 0 |
| `.\scripts\development\run-python-quality.ps1` | Ruff 0.15.21 passed the extension and simulator targets. | 0 |
| `git diff --check` | No whitespace errors. | 0 |

An initial direct `unittest` invocation from the repository root could not
resolve `stratum_sim` because that bypassed the simulator suite's import setup.
The focused command above was rerun from `tools/simulators`, matching the
project's module layout, and passed.

Slicer application tests were not run because Slice 2 changes only the plain
Python simulator test suite and imports no Slicer APIs. No physical or private
medical data was used.

## Review disposition

Slice 2 is ready for review. Manual Slicer verification is not applicable. To
review locally, run the simulator command above and inspect the two modified
test modules together with this record.

## Correction, 2026-09-04

A review of this record found two of its claims unsupported, and both have been
corrected in `tools/simulators/tests/test_tissue.py`.

**TST-006 pinned a resolution artifact, and pinned it against the contract.**
The expected counts enshrined one- and two-pixel specks in the cortex and
tumour labels, while `phantomRegionMap`'s docstring promised "every region is a
connected area rather than scattered pixels". The counts were not a property of
the scene either: the vessel label falls into 15 components at 24x32, 2 at
48x64 and 3 at 96x128. Absorbing the sub-eight-pixel specks - a strictly
cleaner phantom - failed the test with `AssertionError: 6 != 8`, which is a
change detector, not a contract test, and it violated the testing-strategy rule
this audit had just added.

The counts are replaced by the properties the drawn geometry actually promises
and that hold at every frame size: the craniotomy field is one connected area
and so is the drape; every label owns an area covering at least 1 % of the
frame; the vessel label never falls into more areas than there are tracks; and
sub-eight-pixel slivers are held to 1 % of the frame and must each border two
other labels, since a sliver appears only where two drawn boundaries cross.
That last rule is what keeps single-pixel sensitivity without a golden number,
and `test_theCoherenceRulesRejectAScatteredMap` holds the budget itself to
failing on a scattered map.

**TST-007's "documented craniotomy ellipse" was not documented.** The pinned
centre and radii were copies of `tissue.FIELD_CENTRE` and `FIELD_RADII`, and
the phantom document said only that the regions are "ellipses and sine tracks
drawn on a grid" - so under the audit's own three-authority rule they were an
internal implementation detail duplicated rather than an external contract
pinned. The geometry is now published in
`docs/development/synthetic_tissue_phantom.md`, both ellipses are checked
against it, and the docstring that overstated the coherence guarantee has been
corrected.

Red-first evidence for the replacements, mutations applied in memory:

| Probe | Result |
| --- | --- |
| Salt-and-pepper scatter of one label | RED: 4 failures. |
| Craniotomy field cut in two | RED: 2 failures. |
| Vessel tracks broken into dashes | RED: 3 failures. |
| One stray tumour pixel inside cortex | RED: 2 failures. |
| Field ellipse drifts from the document | RED: 1 failure. |
| Tumour ellipse drifts from the document | RED: 2 failures. |
| A fourth vessel track drawn | RED: 1 failure. |
| Sub-minimum slivers absorbed (a cleaner phantom) | GREEN on every topology rule, where the pinned counts had reported `6 != 8`. The crude absorption the probe uses relabels one pixel outside the documented tumour ellipse, which the containment test rejects on its own terms. |
