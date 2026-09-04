# Test-case robustness audit: Slice 1 review

Date: 2026-09-04

## Scope

This change implements only Slice 1 from
`docs/development/test_case_robustness_audit.md`: TST-001 through TST-004. The
project owner explicitly requested implementation without a task card, so no
task was selected, created, or moved. No production code changed.

The existing branch `review/test-case-robustness-audit` was used. No Git branch
or history mutation was performed.

## Files reviewed

- `docs/development/test_case_robustness_audit.md`
- `tools/simulators/tests/test_uc1_runner.py`
- `tools/simulators/tests/test_uc1_maps.py`
- `tools/simulators/stratum_sim/uc1_runner.py`
- `tools/simulators/stratum_sim/uc1_maps.py`
- `tools/simulators/tests/run_tests.py`

## Changes

| Finding | Test change | Review result |
| --- | --- | --- |
| TST-001 | Replaced the bare `"3"` return-code check with the semantic fragment `"code 3"`. | The assertion now distinguishes the requested return code from digits in the dataset path. |
| TST-002 | Replaced the bare `"2"` palette count check with `"2 pixel(s)"`. | The assertion now distinguishes the offender count from digits in an RGB tuple. |
| TST-003 | Removed `assertNotIsInstance(caught.exception, contract.Uc1Maps)`. | `assertRaises(Uc1ProcessFailedError)` already proves that classification raised instead of returning maps; the comment now states that directly. |
| TST-004 | Renamed the existing consistency test, added a test-side arithmetic oracle for redness, luminance, logits, both probability maps, the tumour map, majority class, and majority probability, and added a same-luminance/different-redness input-dependency test. | A mutually consistent but input-independent constant result can no longer pass. The oracle uses fixed expected arrays evaluated independently from the production output. |

Files modified:

- `tools/simulators/tests/test_uc1_runner.py`
- `tools/simulators/tests/test_uc1_maps.py`

File created:

- `docs/development/test_case_robustness_slice1_review.md`

## Red-first mutation evidence

The mutations were applied in memory with `unittest.mock`; repository files were
not changed by the probes.

| Probe | Defect reproduced | Result |
| --- | --- | --- |
| TST-001 wrong return code | Rendered code `7` while retaining the timestamped dataset path containing `3`. | RED confirmed: 1 assertion failure. |
| TST-002 wrong offender count | Rendered `1 pixel(s)` while retaining `(128, 128, 0)`. | RED confirmed: 1 assertion failure. |
| TST-004 constant-map oracle | Returned uniform `0.25` probabilities, class `1`, and TMD `0.25`. | RED confirmed: 1 assertion failure. |
| TST-004 input independence | Returned those same constant maps for red-dominant and green-dominant spectra. | RED confirmed: 1 assertion failure. |

TST-003 removes a tautological assertion rather than adding a behavioral
expectation, so it has no meaningful red-first mutation. The surrounding
`assertRaises` remains the behavioral check.

## Validation

| Command/check | Result | Exit code |
| --- | --- | --- |
| `.\.venv\Scripts\python.exe tools\simulators\tests\run_tests.py` | 83 tests passed, including the staged real-binary GPU integration. | 0 |
| `.\scripts\development\run-python-quality.ps1` | Ruff 0.15.21 passed the extension and simulator targets. | 0 |
| `git diff --check` | No whitespace errors. | 0 |

Slicer application tests were not run because Slice 1 changes only the plain
Python simulator test suite and imports no Slicer APIs. No physical or private
medical data was used.

## Review disposition

Slice 1 is ready for review. Manual Slicer verification is not applicable. To
review locally, run the simulator command above and inspect the two modified
test modules together with this record.
