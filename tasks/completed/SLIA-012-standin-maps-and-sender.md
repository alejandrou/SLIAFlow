---
id: SLIA-012
title: Stand-in UC1 maps and map sender
status: completed
branch: feature/SLIA-012-standin-maps-and-sender
priority: high
depends_on: SLIA-011
required_skills: []
optional_tools: []
related_adrs: []
---

# SLIA-012 - Stand-in UC1 maps and map sender

## Goal

Complete the end-to-end seam with a CUDA-free stand-in that turns a simulated
cube into all five contract maps and sends them over OpenIGTLink as `simulated`,
so that SLIA-013 can swap the real UC1 binary in behind an already-proven
transport.

## Context

The real UC1 binary, as shipped, writes **only** the RGB classification image;
`outMV_V14.txt` is inside a comment block at `main.cu` lines 164-174. Of the five
maps in the SLIAFlow image contract it yields `majorityVotingMap` and nothing
else. `tmdMap`, `majorityVotingProbabilityMap`, `svmProbability` and
`knnProbability` are computed on the GPU and then discarded, and surfacing them
would require a source change the roadmap forbids.

So this stand-in has two jobs. It supplies the four maps the real pipeline
discards, and it is a complete CUDA-free fallback for machines without a CUDA
toolkit - a reviewer's laptop or CI, not this machine, which has a proven
toolchain. It implements the `Classifier` protocol from SLIA-011 so SLIA-013 can
displace it without touching the sender.

This task deliberately precedes the real UC1 work. It proves the whole seam -
cube in, maps out, OpenIGTLink, banner - with code that cannot fail for
environmental reasons. SLIA-013 then swaps one implementation behind that proven
seam, which is exactly the plug-and-unplug property being built. Reversed, a
failure in the first end-to-end run would be ambiguous between the contract, the
transport and the CUDA pipeline.

No UC1-to-OpenIGTLink wrapper exists anywhere upstream; port 18945 appears only
in this project's roadmap. This sender therefore becomes the de-facto
specification and must be recorded as a gap being filled, never as something that
already existed.

## Requirements

- Add `uc1_maps.py`, `bmp.py` and `uc1_sim.py` to `tools/simulators/stratum_sim/`
  and `scripts/development/run-uc1-simulator.ps1`.
- Open `uc1_maps.py` with this module docstring, first line, verbatim:

  > This is not a classifier. It is a fixed arithmetic rule with hand-chosen
  > constants, written so that a demo pipeline has something to draw. It was not
  > fitted to data, it was never validated, and its output has no diagnostic
  > meaning whatsoever.

- Derive exactly two scalars from the calibrated cube - `rednessIndex` (mean over
  600-700 nm minus mean over 500-560 nm) and `luminance` (mean over all bands) -
  and feed them to four logits whose constants all live in a single
  `ARBITRARY_CONSTANTS` dictionary.
- Derive the two probability maps first, then define
  `mean = (svmProbability + knnProbability) / 2` as the elementwise per-pixel
  average across the four class channels, and derive the remaining three maps
  from it. Every occurrence of `mean` below is that array and nothing else.
- Produce the five maps as follows, self-consistent by construction:

  | Output | Definition | Shape and type |
  | --- | --- | --- |
  | `svmProbability` | `softmax(z)` | `(1, lines, samples, 4)` float32 |
  | `knnProbability` | `softmax(z / 1.6)` | `(1, lines, samples, 4)` float32 |
  | `majorityVotingMap` | `argmax(mean) + 1` | `(1, lines, samples)` uint8 |
  | `majorityVotingProbabilityMap` | `max(mean)` | `(1, lines, samples)` float32 |
  | `tmdMap` | `mean[..., 1]`, the tumour channel | `(1, lines, samples)` float32 |

- Document `knnProbability` explicitly as the same arithmetic at a different
  temperature, not a second algorithm.
- Before every send, run the producer's own NumPy copy of the image contract
  check: finite values, correct ranges, class set `{1,2,3,4}`, probability rows
  summing to 1 within 1e-5, `majorityVotingMap == argmax(mean) + 1`, and
  `tmdMap == mean[..., 1]`.
- Port `writeBMP` byte-faithfully in `bmp.py`: 14-byte file header, 40-byte info
  header with its trailing 24 bytes all zero, rows bottom-up, pixels in B, G, R
  order, rows padded to a multiple of 4, and the C code's `filesize = 54 + 3*w*h`
  reproduced with a comment noting that it omits padding.
- Use the verified UC1 palette as the single shared table: 1 normal is green, 2
  tumour is red, 3 hyper is blue, 4 background is black. Export both the forward
  map and its inverse from one definition so SLIA-013's palette inverse cannot
  drift from this one.
- Send over OpenIGTLink on `127.0.0.1:18945` through SLIA-011's
  `igtl_transport.py`, using the SLIAFlow device names `UC1_TMD`,
  `UC1_MV_CLASS`, `UC1_MV_PROB`, `UC1_SVM_PROB` and `UC1_KNN_PROB`.
- Send the **complete** wire metadata contract on every map, not the origin
  alone: `SLIAFlow.ResultMap` set to the map role, `SLIAFlow.DeviceName` set to
  the device name, `SLIAFlow.DataOrigin = simulated`, and
  `SLIAFlow.SimulationDetail = "arithmetic stand-in, not a classifier"`.
  SLIAFlow's `findResultSource` matches on role, device and origin together, so a
  message carrying origin alone arrives and is then never discovered - a failure
  that looks exactly like a broken transport and is not one.
- Send with pyigtl header version 2, which SLIA-011 sets centrally. Version 1 is
  pyigtl's default and carries no metadata whatsoever: the same five messages
  sent at version 1 arrive well-formed and complete, with every provenance key
  gone and nothing but a logger warning on the sending side to show for it.
- Refuse to classify any cube whose `raw.hdr` description lacks the
  `STRATUM SIMULATED CUBE` marker unless `--force-unmarked` is passed. Default
  `requireSimulatedMarker` to true. Treat this interlock as non-optional; it is
  the code-level enforcement of the medical-data policy, ensuring the fake
  classifier physically cannot be pointed at a real patient cube.
- Print a banner on stdout each cycle stating that the output is a simulated
  stand-in and not a classifier.
- Optionally send a `UC1_SIM_NOTICE` STRING message so SLIAFlow has a wire-level
  provenance signal independent of the operator's checkbox.

## Out of scope

- Any CUDA code, compilation, or use of the real UC1 binary; that is SLIA-013.
- Any change inside `extensions/`.
- Any claim, in code, output or documentation, that these maps are a
  classification. They are arithmetic with hand-chosen constants.
- Fitting, tuning or validating the rule against any data.

## Files allowed

- `tools/simulators/**`
- `scripts/development/run-uc1-simulator.ps1`
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`
- `tasks/{backlog,active,review,completed}/SLIA-012-standin-maps-and-sender.md`

## Relevant skills and references

- `.ai/policies/medical-data-policy.md` - the "must not imply clinical validity"
  requirement that the docstring, banner and marker interlock implement.
- `.ai/policies/algorithm-boundary-policy.md`
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`
- `workspace/components/UC1_Brain_Tumor-GPU_optimization/.../source/functions.cu`
  lines 291-346 (`writeBMP`) and lines 264-272 (palette de-swizzle)
- `workspace/components/.../source/functions_cuda.cu` lines 1554-1592 (palette)
- `workspace/components/.../source/main.cu` lines 164-174 (the commented-out
  `outMV_V14.txt` write that limits the real binary to one map)
- SLIA-011's `Classifier` protocol in `stratum_sim/contract.py`

## Approved dependencies

None beyond those already approved in SLIA-011. This task adds no new package.

## Implementation plan

1. Write `bmp.py` and the shared palette table with its forward and inverse maps,
   and their byte-exact and round-trip tests.
2. Write `uc1_maps.py`: the docstring, `ARBITRARY_CONSTANTS`, the two scalars, the
   four logits, and the five derived maps.
3. Write the NumPy contract self-check, including its deliberate negative cases,
   so violations fail in this package's tests rather than as a red FAIL in Slicer
   three layers away.
4. Implement the marker interlock and its `--force-unmarked` escape.
5. Write `uc1_sim.py`: load the dataset, calibrate, classify through the
   `Classifier` protocol, self-check, and send all five maps with simulated
   provenance and the per-cycle stdout banner.
6. Add the launcher script and update the image contract document.

## Acceptance criteria

- The five maps are mutually consistent: probability rows sum to 1 within 1e-5,
  `majorityVotingMap` equals `argmax(mean) + 1`, `tmdMap` equals the tumour
  channel of the mean, and every class value is in `{1,2,3,4}`.
- The contract self-check rejects each deliberately corrupted map, so it is
  demonstrably not vacuous.
- `bmp.py` output is byte-exact against a hand-computed 2x2 reference.
- Forward-mapping classes 1 to 4 to RGB and inverse-mapping back is the identity.
- The stand-in refuses a dataset whose header lacks the simulated marker, and
  proceeds only with `--force-unmarked`.
- A pyigtl client on `127.0.0.1:18945` receives all five device names with the
  contract's shapes and scalar types, each carrying all four wire metadata keys -
  role, device name, `simulated` origin, and the stand-in's simulation detail.
- The module docstring, the `ARBITRARY_CONSTANTS` name, and the per-cycle stdout
  banner all state plainly that this is not a classifier.

## Test plan

Automated tests run through `tools/simulators/tests/run_tests.py` using the
standard-library `unittest` runner, **not** the Slicer test runner.

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| The five maps are mutually consistent | `test_uc1_maps.test_derivedMapsAreSelfConsistent` | automated |
| The contract self-check is not vacuous | `test_uc1_maps.test_contractCheckRejectsCorruptedMaps` | automated |
| BMP output is byte-exact | `test_bmp.test_bmpMatchesHandComputedReference` | automated |
| Palette forward and inverse round-trip | `test_bmp.test_paletteRoundTripsForAllClasses` | automated |
| The palette reaches the BMP on the contract shape | `test_bmp.test_classMapBmpUsesThePaletteOnTheContractShape` | automated; manual step 5 |
| The unmarked-cube refusal holds | `test_uc1_maps.test_unmarkedCubeIsRefusedWithoutForceFlag` | automated; manual step 3 |
| All five device names arrive with simulated provenance | Manual step 2 | manual |
| The output is plainly labelled as not a classifier | `test_uc1_maps.test_moduleDocstringStatesItIsNotAClassifier` | automated; manual step 4 |

Tests to add or change, and how each one will be shown to fail first:

- Before the implementation modules existed, `tools\simulators\tests\run_tests.py`
  ran 35 tests and exited 1 with two import errors: `ImportError: cannot import
  name 'bmp'` and `ImportError: cannot import name 'uc1_maps'` from the current
  `stratum_sim` package.
- `test_contractCheckRejectsCorruptedMaps` is additionally shown red against a
  self-check that returns true unconditionally, proving the check has teeth.
- `test_paletteRoundTripsForAllClasses` is shown red against an inverse table
  written independently of the forward one, which is the drift this shared
  definition prevents.

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Generate a `demo` dataset with the SLIA-011 acquisition simulator, then run `scripts/development/run-uc1-simulator.ps1` against it | Each cycle prints a banner stating the output is an arithmetic stand-in and not a classifier | Pass, 2026-09-03. Dataset `sim-20260903-184930` (160x120, 93 bands) written with `-DatasetOnly`; `run-uc1-simulator.ps1 -Cycles 1 -SendNotice` printed `SIMULATED UC1 OUTPUT cycle 1: arithmetic stand-in, not a classifier.` and then `UC1 stand-in stopped after 1 complete map cycle(s).`, exit 0. The launcher's own `This output is simulated, non-clinical arithmetic and is not a classifier.` line and the `UC1_SIM_NOTICE` STRING message both appeared as well |
| 2 | Connect the small pyigtl client to `127.0.0.1:18945` and print the full metadata dictionary of each received message | All five device names arrive with the contract's shapes and scalar types, and each metadata dictionary contains all four keys: `SLIAFlow.ResultMap`, `SLIAFlow.DeviceName`, `SLIAFlow.DataOrigin = simulated`, and `SLIAFlow.SimulationDetail = arithmetic stand-in, not a classifier`. An empty metadata dictionary means the sender fell back to header version 1 | Pass, 2026-09-03. All five arrived in contract order: `UC1_TMD`, `UC1_MV_CLASS` and `UC1_MV_PROB` at `(1, 120, 160)`, `UC1_SVM_PROB` and `UC1_KNN_PROB` at `(1, 120, 160, 4)`; `uint8` for `UC1_MV_CLASS` and `float32` for the other four. Every message reported header version 2 and carried all four metadata keys with the expected values. No empty metadata dictionary |
| 3 | Point the stand-in at a folder whose `raw.hdr` lacks the `STRATUM SIMULATED CUBE` marker | It refuses to run and names the missing marker; it proceeds only when `--force-unmarked` is passed explicitly | Pass, 2026-09-03. Against a copy whose `raw.hdr` description read `{UNMARKED - synthetic, non-clinical}` the run refused with `ERROR: Refusing to classify ...: raw.hdr lacks the STRATUM SIMULATED CUBE marker. Pass --force-unmarked only for an explicitly approved synthetic test dataset.` and exit 1. The same folder started only with `-ForceUnmarked`, and only behind the `WARNING: --force-unmarked is enabled...` line |
| 4 | Read the first line of the `uc1_maps.py` docstring | It states verbatim that this is not a classifier, was not fitted to data, was never validated, and has no diagnostic meaning | Pass, 2026-09-03. Read back verbatim: `This is not a classifier. It is a fixed arithmetic rule with hand-chosen constants, written so that a demo pipeline has something to draw. It was not fitted to data, it was never validated, and its output has no diagnostic meaning whatsoever.` All four clauses present |
| 5 | Write a BMP from a known class map and open it | Colours match the UC1 palette exactly: green normal, red tumour, blue hyper, black background | Pass, 2026-09-03. A 120x120 BMP written from the class map `[[1, 2], [3, 4]]` read back as top-left `(0, 255, 0)` green, top-right `(255, 0, 0)` red, bottom-left `(0, 0, 255)` blue, bottom-right `(0, 0, 0)` black, matching `CLASS_TO_RGB` exactly. File size 43254 bytes = 54 + 3*120*120, as the C writer computes it |

Two incidental observations from the run, neither a defect in this branch.
When a client disconnects, pyigtl's own handler thread logs a
`ConnectionAbortedError: [WinError 10053]` traceback to stderr from inside
`pyigtl/comm.py`; the sender itself is unaffected and still exits 0. And
`--cycles N` counts complete five-map sends, so a client that leaves after one
pass leaves the sender waiting for the next client rather than exiting; that is
the intended meaning of the flag, not a hang.

## Risks

The single largest risk in this task is that a plausible-looking colour image
gets mistaken for a classification result. The mitigations are deliberately
redundant and none of them is optional: the docstring, the
`ARBITRARY_CONSTANTS` name, the per-cycle stdout banner, the `sim-` folder
prefix, the wire-level `SimulationDetail`, the optional `UC1_SIM_NOTICE`
message, and the marker interlock that physically prevents the rule from being
pointed at a real patient cube. SLIA-013 inherits the same interlock.

Running the producer's own copy of the contract check before every send keeps
violations inside this package's test suite rather than surfacing as an
unexplained red FAIL in Slicer three layers away.

## Documentation impact

- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`: record the `UC1_*` sender
  endpoint on port 18945 as a gap this project fills rather than an upstream
  component, and document the simulated provenance attributes the sender stamps.
- `tools/simulators/README.md`: add the UC1 stand-in to the run and stop
  instructions.

## Completion evidence

- Selected as the next eligible task because `SLIA-011` is present in
  `tasks/completed/` with its acquisition toolchain merged to `main`; it is the
  highest-priority eligible backlog card, ahead of medium-priority `SLIA-015`.
- Red-first evidence: before `bmp.py` and `uc1_maps.py` existed, the simulator
  runner reported 35 tests with 2 import errors and exited 1, as recorded in the
  test-plan section above.
- `.\.venv\Scripts\python.exe tools\simulators\tests\run_tests.py`: 39 tests,
  all passed, exit code 0.
- `.\scripts\development\run-python-quality.ps1`: Ruff 0.15.21 checked 6
  SLIAFlow files and 25 simulator files; all checks passed, exit code 0.
- `.\scripts\development\run-slicer-tests.ps1`: 28 Slicer tests passed,
  2 skipped because the no-main-window session has no layout manager; exit code 0.
- `git diff --check`: passed, exit code 0.
- Generated a `demo` dataset with
  `run-acquisition-simulator.ps1 -DatasetOnly`: dataset rank 9, exit code 0.
- Ran `run-uc1-simulator.ps1 -DatasetFolder ... -Cycles 1 -SendNotice` with
  `tests\uc1_client.py`: all five exact device names arrived with shapes
  `(1,120,160)` or `(1,120,160,4)`, the required scalar types, header version 2,
  and all four metadata keys; both processes exited 0.
- A separate pyigtl client received `UC1_SIM_NOTICE` with the expected
  simulated/non-classifier text, exit code 0.
- Ran the launcher against a copied header with its marker removed: it refused
  classification with the named `STRATUM SIMULATED CUBE` interlock and exited 1.
- No files under `extensions/`, `apps/`, `source/`, `knowledge/`, generated
  build trees, or local configuration were modified. The manual verification
  `Result` cells remain empty for the project owner to perform.

## Review findings

Reviewed against this card on 2026-09-03. Six findings, all fixed on the branch;
the acceptance criteria and manual steps were re-run afterwards.

1. **The `knnProbability` documentation requirement was not met in code.** The
   card requires `knnProbability` to be documented explicitly as the same
   arithmetic at a different temperature, not a second algorithm. Only the
   architecture document and the README said so; `uc1_maps.py` carried a bare
   `"knnTemperature": 1.6` entry. A reader of the module - which is where the
   claim matters - had nothing to read. Fixed with a note beside the constant
   and a second one at the derivation, both stating that the SVM and k-NN names
   mirror the contract's device names and that neither map is produced by the
   method its name refers to.

2. **`uc1_sim.py` imported the private `_InterruptFlag` from `acquisition_sim`.**
   The leading underscore says "internal to that module", and a second simulator
   reaching across for it means the next one will too. The class is coupled to
   the pyigtl server, not to the acquisition simulator - its own docstring
   explains that it must be installed after `OpenIGTLinkServer.__init__`
   registers its handlers - so it moved to `igtl_transport.InterruptFlag`, which
   both simulators already import. `acquisition_sim` no longer imports `signal`.

3. **`test_moduleDocstringStatesItIsNotAClassifier` asserted only a prefix of the
   required docstring.** The assertion stopped at "It was not", so the two
   clauses the medical-data policy actually turns on - "it was never validated"
   and "no diagnostic meaning whatsoever" - could both be deleted with the test
   still green. It now asserts the whole sentence by equality, checks
   `NON_CLASSIFIER_NOTICE` against the same text, and additionally covers the
   per-cycle banner and the wire-level `SimulationDetail`, which the acceptance
   criterion names alongside the docstring and were untested.

4. **The per-cycle banner was an inline f-string.** It is one of the card's
   redundant, non-optional "not a classifier" signals, and nothing could assert
   what an operator reads. Extracted to `uc1_sim.CYCLE_BANNER`.

5. **`writeClassMapBMP` had no test.** The byte-exactness and round-trip criteria
   were both covered, but the function that joins them - and the one manual step
   5 exercises - was not, including its acceptance of the contract's
   `(1, lines, samples)` shape. Added
   `test_bmp.test_classMapBmpUsesThePaletteOnTheContractShape`, hand-computed
   against the palette.

6. **Housekeeping.** Three lines in `uc1_maps.py` exceeded the 99-column ceiling
   the rest of `stratum_sim` holds to; `ImageStreamServer._sendMessage` and
   `mapMessages` were the only unannotated signatures in two otherwise fully
   annotated modules; and `sendMaps` tested `image is None` immediately after a
   `validateMaps` call that raises on an absent map, which made a dead branch
   return the same `False` that means "no client connected". All corrected.

Checked and found correct, so left alone: the BMP header layout, row order,
pixel order, padding and the deliberately padding-free `filesize` field against
`gpu_single_bsq/source/functions.cu`; the palette against the `rgbMv` writes in
`functions_cuda.cu` read through the `map[pix*3+2]` de-swizzle in
`writeMatrixRGB`; and the float32 path by which `deriveMaps` and `validateMaps`
compute `mean` identically, which is what lets the self-check compare the
derived maps by exact equality.

## Human approval

Required before review and completion.
