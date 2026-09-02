---
id: SLIA-012
title: Stand-in UC1 maps and map sender
status: backlog
branch:
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
| The unmarked-cube refusal holds | `test_uc1_maps.test_unmarkedCubeIsRefusedWithoutForceFlag` | automated; manual step 3 |
| All five device names arrive with simulated provenance | Manual step 2 | manual |
| The output is plainly labelled as not a classifier | `test_uc1_maps.test_moduleDocstringStatesItIsNotAClassifier` | automated; manual step 4 |

Tests to add or change, and how each one will be shown to fail first:

- All five tests fail with `ModuleNotFoundError` for `stratum_sim.uc1_maps` and
  `stratum_sim.bmp` before those modules exist; record that output.
- `test_contractCheckRejectsCorruptedMaps` is additionally shown red against a
  self-check that returns true unconditionally, proving the check has teeth.
- `test_paletteRoundTripsForAllClasses` is shown red against an inverse table
  written independently of the forward one, which is the drift this shared
  definition prevents.

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Generate a `demo` dataset with the SLIA-011 acquisition simulator, then run `scripts/development/run-uc1-simulator.ps1` against it | Each cycle prints a banner stating the output is an arithmetic stand-in and not a classifier | |
| 2 | Connect the small pyigtl client to `127.0.0.1:18945` and print the full metadata dictionary of each received message | All five device names arrive with the contract's shapes and scalar types, and each metadata dictionary contains all four keys: `SLIAFlow.ResultMap`, `SLIAFlow.DeviceName`, `SLIAFlow.DataOrigin = simulated`, and `SLIAFlow.SimulationDetail = arithmetic stand-in, not a classifier`. An empty metadata dictionary means the sender fell back to header version 1 | |
| 3 | Point the stand-in at a folder whose `raw.hdr` lacks the `STRATUM SIMULATED CUBE` marker | It refuses to run and names the missing marker; it proceeds only when `--force-unmarked` is passed explicitly | |
| 4 | Read the first line of the `uc1_maps.py` docstring | It states verbatim that this is not a classifier, was not fitted to data, was never validated, and has no diagnostic meaning | |
| 5 | Write a BMP from a known class map and open it | Colours match the UC1 palette exactly: green normal, red tumour, blue hyper, black background | |

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

Reserved for implementation evidence.

## Review findings

Reserved for review.

## Human approval

Required before review and completion.
