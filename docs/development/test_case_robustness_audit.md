# Test Case Robustness Audit

Status: review complete; implementation not started

Reviewed branch: `review/test-case-robustness-audit`

Reviewed revision: `e5ea298` (`ENH: Add genuine UC1 runner and tissue phantom`)

Review date: 2026-09-04

## Purpose

This document consolidates both project-owner-provided Claude reviews with an
independent review of the current SLIAFlow and simulator tests. Its purpose is
to identify tests that can pass without protecting their stated requirement,
unexplained values that behave like magic numbers, brittle duplication, flaky
test mechanisms, and important behavior that has no direct automated coverage.

The supplied reviews were produced at different repository states. Findings
that were valid only on an earlier state are retained as resolved history rather
than presented as current defects.

This is a test-quality review, not clinical validation. All reviewed test data
is synthetic, and no assertion should treat the synthetic phantom construction
map as classifier ground truth.

## Outcome

The suite has a strong foundation: it uses synthetic fixtures, injected process
runners, contract validation, explicit failure-path tests, and a real GPU
integration test. However, a green run currently gives more confidence than
some assertions justify.

The most important problems are:

1. Two broad substring assertions do not identify the values they claim to
   check, and one type assertion is tautological.
2. The arithmetic-map test checks only relationships among outputs, so a
   classifier that ignores its input and returns constant maps still passes.
3. Freshness, phantom geometry, and frame-projection tests accept broken
   implementations because their fixtures or proxies do not isolate the
   required property.
4. The routine headless Slicer command reports two layout tests as passing after
   their primary branches return early.
5. Several values are either unexplained heuristics or duplicated pins. Some
   are legitimate external contract anchors and should be made explicit, not
   removed.

## Severity definitions

- **High:** a broken behavior can pass a test that claims to protect it, or a
  reported pass materially overstates coverage.
- **Medium:** an important negative path is missing, a test is flaky, or a proxy
  does not match the named requirement.
- **Low:** maintainability or diagnostic-quality issue that does not currently
  hide a primary behavior failure.

## Confirmed findings

### High priority

#### TST-001: Return-code assertion is non-discriminating

- Location: `tools/simulators/tests/test_uc1_runner.py:267-282`
- Current check: `self.assertIn("3", message)`
- Intended requirement: the failure message reports process exit code `3`.
- Problem: the dataset path contains `sim-20260903-000000`, so the character
  `3` is present independently of the return code. Exit codes `3`, `7`, `42`,
  and `1` all passed this assertion in the audit probe.
- Required change: assert `"code 3"` or, preferably, expose structured error
  fields and assert the exact return code separately from the rendered message.

#### TST-002: Palette offender-count assertion is non-discriminating

- Location: `tools/simulators/tests/test_uc1_runner.py:245-258`
- Current check: `self.assertIn("2", message)`
- Intended requirement: two unmapped pixels are reported.
- Problem: `2` also occurs in the unmapped RGB value `(128, 128, 0)`. A probe
  with only one offender still satisfied the bare `"2"` check.
- Required change: assert `"2 pixel(s)"` and keep the coordinate/color checks.
  A structured exception carrying an offender count would be even stronger.

#### TST-003: Exception type assertion is tautological

- Location: `tools/simulators/tests/test_uc1_runner.py:267-282`
- Current check: `self.assertNotIsInstance(caught.exception, contract.Uc1Maps)`
- Intended requirement: a failed real runner must not fall back to arithmetic
  maps.
- Problem: inside `assertRaises(Uc1ProcessFailedError)`, `caught.exception` is
  necessarily an exception and cannot be a `Uc1Maps` result. The surrounding
  `assertRaises` already proves that no result was returned.
- Required change: delete the assertion and retain the explanatory comment. If
  fallback logic is introduced later, inject a fallback collaborator and assert
  that it was not called.

#### TST-004: Arithmetic map oracle can accept an input-independent result

- Location: `tools/simulators/tests/test_uc1_maps.py:15-52`
- Current check: derives `mean`, classes, TMD, and maximum probability from the
  returned SVM and k-NN maps.
- Intended requirement: `deriveMaps` computes redness, luminance, four logits,
  two softmax maps, and the derived result maps from the supplied cube.
- Problem: the expected values are copied from the system under test's outputs.
  The test proves mutual consistency but not the required arithmetic or any
  dependency on the input. An in-memory mutation returning uniform `0.25`
  probabilities, class `1`, and TMD `0.25` for every input passed the test.
- Required change:
  - retain a narrowly named output-consistency test;
  - add a tiny hand-computed oracle for redness, luminance, logits, probabilities,
    and final maps; and
  - add a metamorphic test showing that materially different input spectra
    change the expected features or output.

#### TST-005: Output freshness coverage exercises only the first failing file

- Location: `tools/simulators/tests/test_uc1_runner.py:205-222`
- Production seam: `tools/simulators/stratum_sim/uc1_runner.py:391-399`
- Intended requirement: `red.txt`, `green.txt`, `blue.txt`, and
  `imageRGB.bmp` must each be newer than the run-start marker.
- Problem: the fixture backdates every output, and the assertion expects only
  `red.txt`. A mutated validator that checked only the first path passed this
  test.
- Required change: use subtests or parameterized cases that make exactly one
  output stale at a time. Do the same for missing outputs so ordering cannot
  hide incomplete validation.

#### TST-006: Phantom connectedness proxy does not test connectedness

- Location: `tools/simulators/tests/test_tissue.py:145-156`
- Current check: more than half of a region's pixels have a same-region pixel
  immediately to their left.
- Intended requirement: each phantom region is one coherent connected area.
- Problems:
  - multiple disconnected wide rectangles pass the horizontal-adjacency ratio;
  - a valid one-pixel-wide vertical vessel can fail despite being connected;
  - `0.5` is an arbitrary proxy threshold rather than the target property.
- Audit evidence: an adversarial map with four disconnected tumour components
  passed every current coherence predicate.
- Required change: count four-neighbor connected components for each required
  region and assert the project-defined component count. If vessel tracks are
  intentionally separate, encode that exact topology instead of saying every
  region is one connected area.

#### TST-007: Phantom containment test checks only the image border

- Location: `tools/simulators/tests/test_tissue.py:158-168`
- Intended requirement: tumour-like and vessel regions lie inside the
  craniotomy field.
- Problem: the test asserts only that those regions do not touch the outer image
  edge and that the edge is drape. It never reconstructs or checks the field
  ellipse.
- Audit evidence: an added tumour patch outside the field but away from the
  image edge passed the current containment predicate.
- Required change: build the expected field mask independently from the public
  geometry contract and assert that every tumour/vessel pixel is inside it.

#### TST-008: Render test does not prove projection from the supplied cube

- Location: `tools/simulators/tests/test_tissue.py:195-208`
- Production seam: `tools/simulators/stratum_sim/tissue.py:378-393`
- Intended requirement: the LiveView frame is a projection of the exact cube
  written to the dataset.
- Problem: shape, dtype, and mean green ordering can all pass when the renderer
  ignores its input and returns a separately generated or hard-coded scene.
- Audit evidence: an in-memory renderer that ignored the supplied cube and
  rebuilt its own phantom passed the test.
- Required change: compare with an independently calculated small projection,
  then perturb one voxel/band in the supplied cube and assert the corresponding
  output change. Keep the region-ordering assertion only as a secondary
  scene-level property.

#### TST-009: Headless Slicer tests silently bypass their primary branches

- Locations:
  - `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py:505-535`
  - `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py:596-601`
  - `scripts/development/run-slicer-tests.ps1`
- Intended requirements: activate the custom layout, verify lifecycle behavior,
  and restore the prior layout.
- Problem: the routine command runs without a main window. When
  `layoutManager()` is `None`, both tests perform fallback assertions and return
  while still being reported as `ok`. Their names therefore overstate what ran.
  The banner tests correctly use `skipTest` under the same condition.
- Required change: split headless fallback behavior from headful layout behavior.
  The headful test should explicitly skip without a layout manager, and a
  maintained headful test target or required manual step must execute it.

### Medium priority

#### TST-010: Enqueue-rate test uses the real clock with a narrow jitter budget

- Location: `tools/simulators/tests/test_acquisition_sim.py:43-60`
- Current setup: `measurementStart = time.perf_counter() - 0.9`, followed by
  an assertion to one decimal place.
- Problem: a delay of only a few milliseconds can move the result across the
  rounding boundary on Windows. The behavior is important, but the mechanism is
  nondeterministic.
- Required change: inject the clock/end time into `enqueueRate`, or patch
  `time.perf_counter` to a fixed value. Assert the exact `(n - 1) / elapsed`
  result and the one-frame/zero-frame boundaries.

#### TST-011: UC1 parsing and per-output negative paths are incomplete

- Production seams:
  - `tools/simulators/stratum_sim/uc1_runner.py:330-351`
  - `tools/simulators/stratum_sim/uc1_runner.py:242-281`
- Existing coverage tests one missing channel first, all outputs stale together,
  one missing model file, and one short weight vector.
- Missing direct cases include malformed/empty channel content, an individual
  channel shape mismatch, each channel missing/stale in isolation, a stale or
  missing class BMP in isolation, and representative wrong-size failures for
  model files other than the weight vector.
- Required change: table-drive these cases by file name and corruption type so
  every loop member is independently observable.

#### TST-012: Sender/service behavior lacks direct automated coverage

- Locations:
  - `tools/simulators/stratum_sim/uc1_sim.py`
  - `tools/simulators/stratum_sim/uc1_runner.py:502-592`
- Current coverage verifies map-message construction and the real classifier,
  but does not directly exercise the full `sendMaps`/`streamMaps` path with an
  injected fake server and interrupt/clock seams.
- Risk: validation ordering, disconnect handling, completed-cycle accounting,
  notice behavior, and propagation of scene-specific provenance can regress
  while lower-level map-message tests stay green.
- Required change: add fake-server tests for successful sends, a send failure in
  each position, zero/finite cycle behavior, optional notice handling, and both
  scene-detail values through the service-level call.

#### TST-013: `frames.py` has no direct test module

- Location: `tools/simulators/stratum_sim/frames.py`
- Missing behavior: deterministic seeded synthetic frames, frame motion,
  protocol conformance, resize no-op, OpenCV resize argument order, NumPy
  fallback resize, webcam read failure, capture release, and factory routing.
- Required change: add `test_frames.py` with injected/fake OpenCV and capture
  objects. No physical webcam should be required by the automated suite.

#### TST-014: Spectral separation threshold is unexplained

- Location: `tools/simulators/tests/test_tissue.py:180-193`
- Current check: pairwise normalized spectral-shape difference is greater than
  `0.02`.
- Problem: the test gives no specification, sensor-quantization, or noise-floor
  rationale for `0.02`, so it appears tuned to the current output.
- Required change: either define and document a named minimum separation based
  on a real simulator requirement, or replace the threshold with the exact
  qualitative invariant the project needs. Do not derive the expected floor
  from the same generated spectra under test.

### Low priority and maintainability

#### TST-015: Broadcast dimensions duplicate the fixture lengths

- Location: `tools/simulators/tests/test_tissue.py:93-111`
- Problem: `(5, 3, 3, 3)` repeats the lengths of four arrays defined just above.
  Extending one parameter vector causes a broadcast error rather than extending
  coverage.
- Required change: use `numpy.broadcast_arrays`/`numpy.broadcast_shapes` or
  derive the expected shape from the parameter array lengths.

#### TST-016: BMP golden reference is valid but opaque

- Location: `tools/simulators/tests/test_bmp.py:15-75`
- Assessment: the independent hand-computed byte reference is valuable and
  should remain independent of production constants.
- Problem: the DIB fields are an unlabeled integer list, while header size `54`
  is repeated as a bare literal.
- Required change: define test-side names such as `BMP_FILE_HEADER_BYTES = 14`,
  `BMP_INFO_HEADER_BYTES = 40`, and `BMP_PIXEL_OFFSET = 54`; build labeled
  fields with `struct.pack` or assert named byte ranges. Preserve the exact
  golden-byte comparison.

#### TST-017: Headwall wavelength test mixes an external anchor with SUT values

- Location: `tools/simulators/tests/test_spectra.py:100-111`
- Current checks: endpoints are compared with production constants, while the
  first step is independently pinned to `6.5244`.
- Reconciliation: `6.5244` is not arbitrary; it is traceable to the documented
  93-band Headwall grid. Removing it without another independent anchor would
  make the test more self-referential. Conversely, leaving only a bare step
  literal obscures why it is fixed.
- Required change: define a test-side documented sensor contract (first
  wavelength `400.482`, last wavelength `1000.73`, band count `93`) or read an
  authoritative public fixture, construct the expected grid independently, and
  compare the full array. A deliberate sensor-contract change should require an
  explicit test update.

#### TST-018: Dependency-pin tests should cross-check their manifests

- Locations:
  - `tools/simulators/tests/test_igtl_transport.py:97-103`
  - `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py:345-366`
  - `tools/simulators/requirements.txt`
  - `extensions/SLIAFlow/SLIAFlow/Resources/requirements.txt`
- Assessment: verifying the installed `pyigtl` distribution and the OpenCV pin
  is useful environment/reproducibility coverage. It is distinct from behavior
  coverage, which already checks metadata pack/unpack and camera fallbacks.
- Problem: each test repeats the pin as a literal and does not detect drift
  between code and the requirements file.
- Required change: parse the relevant requirements file, compare the runtime or
  logic constant with that pin, and keep the behavioral tests separate. Give
  the tests names that identify them as dependency consistency checks.

#### TST-019: Configuration literals mix contracts and implementation copies

- Location: `tools/simulators/tests/test_config.py:22-33,50-61`
- Assessment: `demo`, `160x120`, 93 bands, and port `18944` are traceable product,
  model, or OpenIGTLink integration contracts; they are not automatically magic
  numbers. The `medium` and `full` dimensions may also be legitimate documented
  presets if exact sizes are part of the supported interface.
- Problems: `test_demoIsTheDefaultPreset` checks all preset dimensions despite
  its name, and the tests do not distinguish external contract pins from
  implementation invariants such as BMP row alignment.
- Required change: split default selection, exact documented preset table, and
  row-alignment invariants into separate tests. Remove exact medium/full values
  only if they are not promised by configuration documentation.

#### TST-020: Exact docstring equality couples policy coverage to formatting

- Location: `tools/simulators/tests/test_uc1_maps.py:90-111`
- Assessment: the non-clinical disclaimer is load-bearing and must stay tested.
- Problem: equality against the entire first line fails on harmless wrapping or
  wording changes that preserve the required safety statements.
- Required change: normalize whitespace and independently require the clauses
  `"not a classifier"`, `"was never validated"`, and
  `"no diagnostic meaning"` in both operator-facing surfaces. Keep equality
  only where two surfaces are deliberately required to display identical text.

#### TST-021: Shared fixtures live in another test module

- Location: `tools/simulators/tests/test_contract.py:12`
- Problem: importing `TEST_BANDS`, `TEST_LINES`, `TEST_SAMPLES`, and
  `buildTinyCubes` from `test_envi.py` couples two test modules and lets an ENVI
  fixture edit silently change contract-test coverage.
- Required change: move cross-module fixtures to
  `tools/simulators/tests/support.py`. Keep test-specific fixtures local.

#### TST-022: Path-limit diagnostic repeats a test-support constant

- Location: `tools/simulators/tests/test_envi.py:106-116`
- Current check: `self.assertIn("128", str(overLongPath.exception))`
- Assessment: 128 is an independently documented limit from the vendored UC1
  parser, and `tests/support.py` already gives it the semantic name
  `UC1_MAX_PATH_LENGTH`.
- Required change: assert `str(support.UC1_MAX_PATH_LENGTH)` so a deliberate
  update to the test-side consumer model cannot leave the diagnostic check
  behind. This is a maintainability change, not a behavior defect.

#### TST-023: Event-loop settling uses an unexplained iteration count

- Location:
  `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py:501-503`
- Current check: `_settleEventLoop()` calls `slicer.app.processEvents()` exactly
  20 times before the UI assertion.
- Assessment: processing the event loop is necessary and fixed the earlier
  false-positive annotation test. The concern is not that `20` is inherently
  wrong, but that an iteration count is neither a readiness condition nor a
  time bound. It may do unnecessary work when the actor is ready immediately,
  and it offers no clear guarantee when asynchronous work needs more turns.
- Required change: wait for the observable UI predicate with a named, bounded
  timeout while processing events. On timeout, report the unmet predicate.
  Keep a fixed iteration helper only if Slicer guarantees that number of turns,
  and document that authority.

## Magic-number assessment

The goal is not to eliminate numeric literals. A number is problematic when its
meaning or authority is hidden, not merely because it is numeric.

| Value | Assessment | Action |
| --- | --- | --- |
| `0.5` adjacency ratio | Arbitrary proxy that does not express connectedness | Replace with a topology check |
| `0.02` spectral distance | Unexplained heuristic | Name and justify it, or replace it with the actual invariant |
| `0.9` elapsed time | Clear example value, but combined with a real clock it is flaky | Freeze/inject the clock |
| `20` event-loop turns | Unexplained settling count, not a readiness condition | Poll the observable predicate with a named timeout |
| bare `"2"` and `"3"` message fragments | Ambiguous string matching | Assert semantic fragments or structured fields |
| `54` BMP offset | Stable file-format value but opaque where repeated | Give it a test-side semantic name |
| `6.5244` nm | Traceable Headwall grid value, not arbitrary | Anchor the full external sensor contract independently |
| `93` bands | Model/sensor contract | Keep an independent contract check with documented authority |
| `128` bytes | Vendored UC1 parser buffer contract | Use the existing test-support name in diagnostics |
| `18944` / `18945` | OpenIGTLink endpoint contracts | Keep exact checks and document their source |
| `160x120`, `320x240`, `640x480` | Supported preset contract if documented | Separate exact preset checks from general alignment invariants |
| class values `1..4` and palette RGB triples | UC1 interoperability contract | Keep independent exact checks |
| probability tolerance `1e-5` | Numerical contract/tolerance | Keep, preferably under a named tolerance shared by contract tests |

## Reconciliation of the supplied Claude reviews

Every item from both supplied reviews was checked against the current revision.
The first review is reconciled below; repeated observations in the second review
are linked to the same finding instead of creating duplicates.

| Supplied observation | Audit decision |
| --- | --- |
| Bare `"3"` return-code assertion | Confirmed as TST-001 with a local multi-code probe |
| Bare `"2"` offender-count assertion | Confirmed as TST-002 with a one-offender probe |
| `assertNotIsInstance` inside `assertRaises` | Confirmed as TST-003 |
| Hard-coded `6.5244` wavelength step | Nuanced as TST-017: it is a real external anchor, but the full sensor contract should be explicit |
| Hard-coded `"128"` diagnostic check | Confirmed as low-priority TST-022 |
| Opaque BMP byte fixture and bare `54` | Confirmed as TST-016; preserve its independent golden-reference role |
| Unexplained `0.02` spectral distance | Confirmed as TST-014 |
| Horizontal `0.5` connectedness proxy | Confirmed and strengthened by adversarial evidence in TST-006 |
| Hard-coded broadcast shape `(5, 3, 3, 3)` | Confirmed as TST-015 |
| Literal installed `pyigtl` version | Reframed in TST-018 as a useful environment check that should cross-check the manifest |
| Literal OpenCV requirement in Slicer test | Reframed in TST-018 as a manifest/code consistency check |
| Configuration table/default literals | Separated into external contracts and internal invariants in TST-019 |
| Exact four-sentence disclaimer | Confirmed as formatting-brittle TST-020 while preserving the safety clauses |
| `test_contract.py` importing `test_envi.py` fixtures | Confirmed as TST-021 |
| Real-clock enqueue-rate test | Confirmed as TST-010 |
| No direct `frames.py` tests | Confirmed as TST-013 |
| `uc1_sim.py` touched only incidentally | Confirmed and expanded into service-path gap TST-012 |

The second supplied review is reconciled separately because two of its leading
observations describe an earlier repository state:

| Supplied observation | Audit decision |
| --- | --- |
| Literal NUL byte prevents `test_uc1_runner.py` import | Historically valid but resolved on the reviewed revision; the simulator suite now imports and all 81 tests pass |
| Wire-metadata test bypasses tissue-specific service provenance | Historically valid but resolved on the reviewed revision; tissue and generic synthetic provenance are now distinguished and tested |
| Arithmetic classifier accepts hard-coded output | Confirmed as TST-004, including the constant-map mutation probe |
| Phantom connectedness, containment, and rendering proxies | Confirmed as TST-006, TST-007, and TST-008, including adversarial probes |
| UC1 safety test exercises only the first output and lacks negative cases | Confirmed as TST-005 and TST-011; its broad offender-count assertion is TST-002 |
| Headless Slicer tests return successfully without exercising layout behavior | Confirmed as TST-009 |
| Enqueue-rate test depends on scheduler timing | Confirmed as TST-010 |
| `0.5`, `0.02`, and `0.9` are questionable behavioral thresholds | Confirmed or nuanced in TST-006, TST-014, and TST-010 |
| Fixed 20 event-loop iterations | Added as TST-023; replace the settling count with a predicate and bounded timeout |
| Headwall endpoints are compared with production constants | Confirmed as TST-017; independently pin the full external sensor contract |

## Test-strategy rule that needs refinement

`docs/development/testing_strategy.md` currently says never to duplicate a
production constant in an expected literal. That rule is safe for internal
implementation details, but unsafe when the production constant itself is the
thing being checked against an external contract. If both implementation and
test import the same wrong value, they drift together and the test stays green.

The replacement guidance should distinguish three cases:

1. **Internal implementation detail:** import the production constant and test
   behavior around it.
2. **External/public contract:** use an independently maintained expected value
   or authoritative fixture so drift is detected.
3. **Derived invariant:** calculate the expectation from the specification or a
   small independent oracle, never from the SUT output being judged.

This distinction resolves the apparent conflict between removing duplicated
pins and retaining meaningful Headwall, UC1, BMP, palette, and port anchors.

## Coverage and abstraction strengths to preserve

- Process execution is injected in runner unit tests, so crash and output
  scenarios do not require a GPU.
- A separate real staged-binary integration test exercises the actual CUDA path
  when available.
- The map contract checks shapes, dtypes, finite values, probability ranges,
  sums, and class values.
- OpenIGTLink metadata is tested through a real pack/unpack round trip, including
  the known header-version failure mode.
- Dataset overwrite and simulated-marker interlocks have direct negative tests.
- Slicer result discovery, provenance, presentation ownership, and malformed
  map rejection have substantial automated coverage.
- Test data is synthetic, and the suite correctly avoids grading the genuine
  classifier against phantom construction labels.

## Recommended implementation order

### Slice 1: eliminate false-green assertions

1. Fix TST-001 and TST-002 with semantic message fragments.
2. Remove TST-003.
3. Add the independent arithmetic oracle and input-dependency case from TST-004.
4. Observe each new/changed test failing against the prior implementation and
   record that red-first evidence.

### Slice 2: make file and phantom properties exact

1. Parameterize individual stale/missing/malformed outputs (TST-005, TST-011).
2. Replace geometry proxies with connected-component and field-mask checks
   (TST-006, TST-007).
3. Add an independent projection oracle and perturbation test (TST-008).

### Slice 3: close execution-path gaps

1. Split headless and headful layout coverage (TST-009).
2. Add deterministic clock seams (TST-010).
3. Add direct `frames.py`, sender, and service tests (TST-012, TST-013).
4. Replace the fixed event-loop settling count with a predicate-based bounded
   wait (TST-023).

### Slice 4: reduce brittleness and document contracts

Address TST-014 through TST-022, then update the testing-strategy rule so future
tests classify values by authority instead of treating every literal the same.

## Validation evidence for this audit

| Command/check | Result |
| --- | --- |
| `.\.venv\Scripts\python.exe tools\simulators\tests\run_tests.py` | Exit 0; 81 tests passed; staged GPU integration executed |
| `.\scripts\development\run-slicer-tests.ps1` | Exit 0; 30 tests ran; 3 explicit layout-manager skips |
| `.\scripts\development\run-python-quality.ps1` | Exit 0; Ruff 0.15.21 passed both targets |
| `git diff --check` before writing this report | Exit 0 |
| Return-code diagnostic | Bare `"3"` matched messages for codes 3, 7, 42, and 1 |
| Offender-count diagnostic | Bare `"2"` matched a message reporting only 1 offender |
| Constant-map mutation | `test_derivedMapsAreSelfConsistent` still passed |
| First-output-only freshness mutation | `test_staleOutputIsRejectedNotAccepted` still passed |
| Input-ignoring renderer mutation | `test_renderedFrameIsAProjectionOfTheCube` still passed |
| Adversarial phantom geometry | Current coherence/containment predicates passed with 4 tumour components and tumour pixels outside the field |

The mutation probes were performed in memory; they did not modify repository
files.

## Reconciled findings that are already resolved

Two issues reported by the second supplied review no longer exist at the
reviewed revision and should not be reopened as current defects:

- `test_uc1_runner.py` no longer contains a literal NUL byte; the full simulator
  suite imports and passes.
- The real UC1 wire provenance now distinguishes a synthetic tissue phantom
  from generic synthetic input, and the distinction is documented and tested.

## Definition of done for a future test-hardening task

- Every high- and medium-priority finding is fixed or explicitly accepted with
  rationale in the task card.
- Each changed behavioral test has recorded red-first evidence against the
  defect or a deliberately introduced mutation.
- Contract literals cite their authority; heuristic thresholds are named and
  justified.
- Headless output does not report headful-only behavior as passed.
- Simulator, Slicer, Ruff, and relevant real-binary checks pass, with skips and
  unavailable hardware clearly reported.
- No private medical data is introduced, and phantom labels remain construction
  metadata rather than classifier truth.
