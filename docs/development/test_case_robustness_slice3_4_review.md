# Test-case robustness audit: Slices 3 and 4 review

Date: 2026-09-04

## Scope

This change implements Slice 3 and Slice 4 from
`docs/development/test_case_robustness_audit.md`: TST-009, TST-010,
TST-012 through TST-023. The Slice 2 work already completed TST-011. The
project owner explicitly requested implementation without a task card, so no
task was selected, created, or moved. No production module code changed.

The existing branch `review/test-case-robustness-audit` was used. No Git branch
or history mutation was performed. Existing Slice 1 and Slice 2 changes were
preserved.

## Files reviewed

- `docs/development/test_case_robustness_audit.md`
- `docs/development/testing_strategy.md`
- `scripts/development/run-slicer-tests.ps1`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/Resources/requirements.txt`
- `tools/simulators/requirements.txt`
- `tools/simulators/stratum_sim/acquisition_sim.py`
- `tools/simulators/stratum_sim/frames.py`
- `tools/simulators/stratum_sim/uc1_sim.py`
- `tools/simulators/stratum_sim/uc1_runner.py`
- `tools/simulators/tests/`

## Slice 3 changes

| Finding | Test change | Review result |
| --- | --- | --- |
| TST-009 | Split the layout XML contract, no-main-window fallback, and headful layout lifecycle into separately named tests. Headful-only tests now explicitly skip without a layout manager. Added `-Headful` to the Slicer test runner and documented the maintained target. | A headless run no longer reports layout activation/restoration as passed. The headful run executes those branches in a real Slicer window. |
| TST-010 | Patched `acquisition_sim.time.perf_counter` to a fixed end time and asserted the exact interval-based calculation and zero/one-frame boundaries. | Scheduler delay can no longer move the assertion across a rounding boundary. |
| TST-012 | Added fake-server arithmetic sender/service tests for pre-send and between-send validation, successful map order, failure at each map position, disconnect behavior, finite and unbounded cycle modes, completed-cycle accounting, and optional notice retry. Added genuine-runner send failure and service-level provenance tests for generic synthetic and tissue-phantom datasets. | The full service paths are exercised without sockets, sleeps, CUDA, or an OpenIGTLink client. |
| TST-013 | Added direct `test_frames.py` coverage for seeded determinism, motion, protocol conformance, resize no-op, OpenCV argument order, NumPy fallback sampling, closed/read-failing webcam behavior, capture release, and factory routing. | Automated coverage requires no physical webcam and independently observes every frame-source branch named by the audit. |
| TST-023 | Replaced the fixed 20-turn event-loop helper with a named two-second bounded wait for the actual renderer or presentation predicate. Timeout diagnostics name the unmet predicate. | UI assertions wait only until their observable state is ready and fail explicitly when it never becomes ready. |

Files created for Slice 3:

- `tools/simulators/tests/test_frames.py`
- `tools/simulators/tests/test_uc1_sim.py`

Files modified for Slice 3:

- `tools/simulators/tests/test_acquisition_sim.py`
- `tools/simulators/tests/test_uc1_runner.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `scripts/development/run-slicer-tests.ps1`
- `docs/development/testing_strategy.md`

## Slice 4 changes

| Finding | Test change | Review result |
| --- | --- | --- |
| TST-014 | Replaced the unexplained `0.02` distance with the qualitative, test-side optical invariant that normalized green-band reflectance orders drape, cortex, tumour, then vessel. | Every region remains spectrally distinct without a tuned distance floor. |
| TST-015 | Used `numpy.broadcast_arrays` and derived the expected result shape from the broadcast parameter shape and wavelength count. | Extending a parameter vector extends coverage instead of failing against duplicated dimensions. |
| TST-016 | Named the BMP file header, info header, and pixel offset and rebuilt the independent golden header with labeled `struct.pack` fields. | The byte oracle remains independent while its format semantics are readable. |
| TST-017 | Defined the independent Headwall contract as 400.482–1000.73 nm over 93 bands and compared the complete generated array to an independently constructed grid. | Endpoint, count, spacing, and every intermediate sample now drift together only after an explicit contract-test update. |
| TST-018 | Parsed the simulator and extension requirements manifests. The installed `pyigtl` distribution and `SLIAFlowLogic.OPENCV_REQUIREMENT` must match their respective pins in separately named dependency-consistency tests. | Literal copies can no longer conceal manifest/runtime or manifest/logic drift. |
| TST-019 | Split default preset selection, the exact documented preset table, and BMP row-alignment invariants. Named the documented band and port contracts in the test. | Product contracts and derived implementation invariants are now visibly distinct. |
| TST-020 | Normalized whitespace and asserted the three required safety clauses independently on the module docstring and operator notice, while retaining equality between the deliberately identical first-paragraph surfaces. | Harmless wrapping is accepted; removal of any safety clause is not. |
| TST-021 | Moved the shared tiny ENVI dimensions and cube builder into `tests/support.py`; `test_contract.py` no longer imports another test module. | ENVI test-module edits cannot silently redefine contract-test coverage. |
| TST-022 | Replaced the bare path-limit diagnostic literal with `support.UC1_MAX_PATH_LENGTH`. | The diagnostic assertion follows the named test-side UC1 parser contract. |

Files modified for Slice 4:

- `tools/simulators/tests/support.py`
- `tools/simulators/tests/test_bmp.py`
- `tools/simulators/tests/test_config.py`
- `tools/simulators/tests/test_contract.py`
- `tools/simulators/tests/test_envi.py`
- `tools/simulators/tests/test_igtl_transport.py`
- `tools/simulators/tests/test_spectra.py`
- `tools/simulators/tests/test_tissue.py`
- `tools/simulators/tests/test_uc1_maps.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `docs/development/testing_strategy.md`

The testing-strategy rule now distinguishes internal implementation details,
independently pinned external/public contracts, and independently derived
invariants instead of prohibiting every duplicated literal.

## Red-first mutation evidence

The mutations were applied in memory with `unittest.mock`; repository files
were not changed by the probes.

| Probe | Defect reproduced | Result |
| --- | --- | --- |
| TST-009 headless false success | Forced `_activatePresentation()` to return true in the headless fallback test. | RED confirmed: 1 failure. |
| TST-010 frame-count divisor | Replaced the interval formula with `n / elapsed`. | RED confirmed: 1 failure. |
| TST-012 ignored send failures | Forced the arithmetic sender to report success at every failed map position. | RED confirmed: 5 subtest failures. |
| TST-012 incomplete-cycle accounting | Bypassed real per-map sends while the service claimed two completed cycles. | RED confirmed: 1 failure. |
| TST-012 collapsed provenance | Forced genuine service provenance to use the generic detail for both scene types. | RED confirmed: 1 failure. |
| TST-013 frozen animation | Returned the same synthetic frame on consecutive reads. | RED confirmed: 1 failure. |
| TST-013 ignored resize | Returned the source frame without invoking OpenCV with the target dimensions. | RED confirmed: 1 failure. |
| TST-013 capture leak | Replaced webcam `close()` with a no-op. | RED confirmed: 1 failure. |
| TST-013 factory misrouting | Returned an unrelated object for every frame-source name. | RED confirmed: 1 failure. |
| TST-014 collapsed spectra | Returned one identical normalized spectral curve for every region. | RED confirmed: 1 failure. |
| TST-017 sensor drift | Shifted the generated first wavelength while preserving the final wavelength and band count. | RED confirmed: 1 failure. |
| TST-018 simulator dependency drift | Reported a manifest pin different from the installed `pyigtl` distribution. | RED confirmed: 1 failure. |
| TST-018 extension dependency drift | Changed the logic OpenCV requirement without changing the extension manifest. | RED confirmed: 1 failure. |
| TST-019 preset drift | Changed the medium width from its independently documented value. | RED confirmed: 1 failure. |
| TST-020 removed safety clause | Removed `no diagnostic meaning` from the operator notice. | RED confirmed: 2 assertions failed. |
| TST-023 unmet UI predicate | Supplied a predicate that never became true to the bounded event-loop wait. | RED confirmed: timeout raised an assertion naming the predicate. |

TST-015, TST-016, TST-021, and TST-022 are maintainability refactors that
preserve existing behavioral assertions, so they have no distinct behavioral
mutation. The sender validation-order cases directly mutate a map during a fake
send and verify that no subsequent map crosses the boundary.

## Validation

| Command/check | Result | Exit code |
| --- | --- | --- |
| `.\.venv\Scripts\python.exe tools\simulators\tests\run_tests.py` | 107 tests passed; the staged real-binary GPU integration executed. | 0 |
| `.\scripts\development\run-slicer-tests.ps1` | 33 tests ran headless; 5 headful-only tests explicitly skipped and the dedicated headless fallback passed. | 0 |
| `.\scripts\development\run-slicer-tests.ps1 -Headful` | 33 tests ran with a main window; all layout/renderer branches passed and only the headless-only fallback explicitly skipped. | 0 |
| `.\scripts\development\run-python-quality.ps1` | Ruff 0.15.21 passed the extension and simulator targets. | 0 |
| `git diff --check` | No whitespace errors; Git emitted only line-ending conversion warnings. | 0 |

An initial full simulator run caught an invalid strict adjacent-pair iteration
in the new spectral-order test. It was corrected to use `itertools.pairwise`,
and the complete 107-test run then passed. An initial ad hoc Slicer mutation
probe had command-line quoting and headless `selectModule` setup errors; it was
rerun through Slicer's argument-list API without `selectModule`, and all three
intended mutation checks produced the recorded red evidence.

The compiled `-Target Build` Slicer tests were not run because no build was
performed and this work changes source tests and the source test runner only.
No physical webcam, external service, private medical data, or MCP resource was
used.

## Manual review

For a source review, run both Slicer commands in the validation table. In the
headful output, confirm that `test_layoutContractAndLifecycle`,
`test_layoutRestoreIgnoresTransientEmptyLayout`, and the banner tests report
`ok`, not `skipped`. In an already open development Slicer, open SLIAFlow and
use **Reload and Test** for the same source-level suite; no patient data or
camera is required.

## Review disposition

Slices 3 and 4 are ready for review. The automated headful layout target has
been executed successfully; visual legibility remains a human manual-
verification concern and is not claimed complete here.
