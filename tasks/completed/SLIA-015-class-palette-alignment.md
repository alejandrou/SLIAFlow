---
id: SLIA-015
title: Align the class map palette with the UC1 pipeline
status: active
branch: feature/SLIA-015-class-palette-alignment
priority: medium
depends_on: SLIA-010
required_skills: [slicer]
optional_tools: []
related_adrs: []
---

# SLIA-015 - Align the class map palette with the UC1 pipeline

## Goal

Make SLIAFlow paint each UC1 class in the colour the UC1 pipeline itself assigns
to that class, so a map read on screen means the same thing as the map read from
the pipeline's own output.

## Context

Found while implementing SLIA-010 and deliberately left unfixed there, because a
palette change is a display-semantics change and had nothing to do with that
task's provenance boundary.

`_getOrCreateClassColorNode` in `SLIAFlowLib/SLIAFlowLogic.py` builds a
five-entry table:

| Index | Label | SLIAFlow colour |
| --- | --- | --- |
| 0 | Unused | transparent |
| 1 | Normal | green `(0.1, 0.8, 0.2)` |
| 2 | Tumour | red `(0.9, 0.1, 0.1)` |
| 3 | Hypervascularized | orange `(1.0, 0.65, 0.0)` |
| 4 | Background | dark grey `(0.2, 0.2, 0.2)` |

The UC1 pipeline writes blue for class 3 and black for class 4. So a
hypervascularized region and the image background are both rendered in a colour
the pipeline does not use, and orange in particular reads as a warning tone for
a class that is not the tumour class.

This is a real disagreement between two components about what a pixel means, not
a preference. Nothing in the current tests would catch it, because the tests
assert that a class map uses a five-entry colour table, not which colours.

### The authoritative palette, read from source at activation (2026-09-15)

The UC1 binary SLIAFlow receives is built from `gpu_single_bsq/source/`
(`docs/development/uc1_local_build.md`, staging layout). Its majority-voting
output is produced in two steps, and both must be read to get the palette right:

1. `majorityVoting` in
   `workspace/components/UC1_Brain_Tumor-GPU_optimization/UC1_Brain_Tumor-GPU_optimization/gpu_single_bsq/source/functions_cuda.cu`
   (lines 1554-1597) writes a per-pixel triple `rgbMv[3i], rgbMv[3i+1], rgbMv[3i+2]`
   for each class: class 1 `(0, 255, 0)`, class 2 `(0, 0, 255)`, class 3
   `(255, 0, 0)`, class 4 `(0, 0, 0)`. The buffer is in **B, G, R** order.
2. `writeMatrixRGB` in `gpu_single_bsq/source/BitmapWriter.cpp` (lines 98-139),
   called from `main.cu:164`, writes `map[3i+2]` to `red.txt`, `map[3i+1]` to
   `green.txt` and `map[3i]` to `blue.txt`, which reverses that order.

Read as R, G, B, the pipeline's palette is therefore:

| Class | Meaning | UC1 RGB (0-255) | SLIAFlow RGBA (0-1) |
| --- | --- | --- | --- |
| 1 | normal | `(0, 255, 0)` | `(0.0, 1.0, 0.0, 1.0)` |
| 2 | tumour | `(255, 0, 0)` | `(1.0, 0.0, 0.0, 1.0)` |
| 3 | hypervascularized | `(0, 0, 255)` | `(0.0, 0.0, 1.0, 1.0)` |
| 4 | background | `(0, 0, 0)` | `(0.0, 0.0, 0.0, 1.0)` |

`workspace/` is ignored and the UC1 copy has no Git metadata of its own, so the
files are pinned by SHA-256 as read on 2026-09-15. A reviewer who gets the same
hashes inspected the same source:

| File under `gpu_single_bsq/source/` | SHA-256 |
| --- | --- |
| `functions_cuda.cu` | `eec8282f6dc07e386a6ecb0145fef79bd986320d8d3d24c42705b38e4e0f25c3` |
| `BitmapWriter.cpp` | `61ebffe98a8399cc03251333edcae5c93f1b5153c3cf5b174fa878c03b4880b5` |
| `BitmapWriter.hpp` | `b4987ab229c969ca68fd6722366d9c79401e50a7b53034792c2810d70c0db3f5` |
| `main.cu` | `63d0e9ee5e77b06876dfa7d76965b1f67719d841d7a4012742f85e2540c788c0` |

The source comments (`GREEN - Normal Tissue`, `RED - Tumour Tissue`,
`BLUE - Hypervascularized Tissue`, `BLACK - Background`) agree, as does
`FOUR_COLORS_MAP` in `gpu_single_bsq/source/BitmapWriter.hpp`. So does the
repository's own palette inverse, `CLASS_PALETTE` in
`tools/simulators/stratum_sim/bmp.py`, which SLIA-013 already exercised against
the genuine binary's output without an unknown-colour failure.

### Refinement at activation

The backlog card said classes 1 and 2 "agree" and asked to leave them untouched.
They agree in hue only: SLIAFlow draws `(0.1, 0.8, 0.2)` and `(0.9, 0.1, 0.1)`,
not the pipeline's pure green and pure red. The card's goal and its first
acceptance criterion ("matches the UC1 palette entry for entry") cannot both hold
with classes 1 and 2 left as they are, so the requirement is refined to correct
all four class entries. This stays inside the card's stated goal and changes no
other behaviour.

### Scope extension approved by the project owner (2026-09-15)

During manual step 1 the owner found that Slicer's **Reload and Test** button
stops at `test_headlessPresentationFallback` with `unittest.case.SkipTest`. The
inherited `ScriptedLoadableModuleTest.runTest` calls each test method directly
(`ScriptedLoadableModule.py:503-507`), so the first `skipTest` escapes and every
later test silently does not run. The defect predates this card (the skips came
in `0a46664`), but it blocks the owner's GUI test loop, and the owner asked for
it to be fixed here rather than in a separate card. The extension adds a
`runTest` override, its regression test, and the `testing_strategy.md`
paragraph that until now said "do not override `runTest`".

The same instruction asked for a pre-review report's findings to be addressed:
the table test did not prove what a slice view draws, the UC1 source was not
pinned, and the contract claimed a UC1-side change would fail a test.

## Requirements

- Establish the authoritative palette from the UC1 source rather than from
  screenshots or memory, and record where it was read from. Done above.
- Change the class 1 to 4 entries to match it exactly.
- Keep index 0 fully transparent. It is the "no class" entry and must not become
  a visible colour just because the pipeline has a fifth `FOUR_COLORS_MAP` row.
- Keep the entry names (`Unused`, `Normal`, `Tumour`, `Hypervascularized`,
  `Background`) and the five-entry size unchanged.
- Document the palette in `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`
  alongside the rest of the class map contract, so the next disagreement is a
  documentation diff rather than a discovery.
- Add a test asserting the specific RGBA of every entry, so a future edit to the
  table fails loudly instead of silently changing what a map means.
- Add a test asserting the RGBA the result display node emits to the slice views
  for each class, after window/level, not only the table entries.
- Pin the UC1 source files the palette was read from by SHA-256, and state in
  the contract that a UC1-side change is not detected automatically.
- Make **Reload and Test** run every test through unittest, reporting skips and
  continuing, and still failing on any failure or error, with a regression test
  shown failing against the inherited loop first.

## Out of scope

- The probability colour ramp. Only the discrete class table is in question.
- Any change to window/level handling, to `_configureResultDisplay`, or to which
  map roles are class maps.
- Colour-blind-safe or otherwise "improved" palettes. The goal is agreement with
  UC1, not a better palette; a different palette is a separate conversation with
  the pipeline's owner.
- Any change to UC1, to `tools/simulators/`, or to `bmp.py`, which already agrees.

## Files allowed

- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`
- `docs/development/testing_strategy.md` (added with the owner-approved scope
  extension, 2026-09-15)
- `tasks/{backlog,active,review,completed}/SLIA-015-class-palette-alignment.md`

## Relevant skills and references

- Slicer skill: `vtkMRMLColorTableNode::GetColor(int entry, double color[4])` and
  `GetColorName(int entry)` in `Libs/MRML/Core/vtkMRMLColorTableNode.h`, for
  reading the table back in the test.
- The UC1 source locations cited in the context above.
- `docs/development/testing_strategy.md`, rule 4: the expected palette is an
  external contract, so the test carries its own literal citing the UC1 source
  and never imports it from production.

## Implementation plan

1. Add `SLIAFlowTest.test_classColorTableMatchesUc1Palette` with an independent
   expected table citing the UC1 source, and run it against the current code to
   record the failure.
2. Change the four class entries in `_getOrCreateClassColorNode`, with a comment
   naming the source.
3. Add the palette table to the class-value paragraph of the image contract.
4. Run `run-python-quality.ps1` and `run-slicer-tests.ps1`, and record both.

## Acceptance criteria

- The class colour table matches the UC1 palette entry for entry, with the
  source of truth cited in the card.
- Index 0 stays fully transparent.
- The image contract document states the palette.
- A test fails if any entry's RGBA changes.
- A test fails if the RGBA the display node emits for any class differs from the
  UC1 palette.
- The UC1 source files are pinned by SHA-256 in this card, and the contract does
  not claim a UC1-side change is detected.
- **Reload and Test** in a Slicer window runs the whole suite, reports skipped
  tests, and fails only on a failure or error.
- `scripts/development/run-python-quality.ps1` and
  `scripts/development/run-slicer-tests.ps1` both pass, headless and `-Headful`.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| The class table matches the UC1 palette entry for entry | `SLIAFlowTest.test_classColorTableMatchesUc1Palette`; manual steps 1 and 2 using a recorded UC1 run | automated; manual |
| Index 0 stays fully transparent | `SLIAFlowTest.test_classColorTableMatchesUc1Palette` | automated |
| The image contract states the palette | Manual step 3 | manual |
| A test fails if any entry's RGBA changes | Failure of `test_classColorTableMatchesUc1Palette` against the pre-change table, recorded below | automated |
| The emitted slice RGBA matches the palette | `SLIAFlowTest.test_classMapSlicePipelineEmitsUc1Colors`, shown failing against the pre-change table; manual step 1 using a recorded UC1 result | automated; manual |
| UC1 source pinned; contract claims corrected | Hash table in the context above; manual step 3 | manual |
| Reload and Test runs past skips | `SLIAFlowTest.test_reloadAndTestRunsPastSkippedTests`, shown failing against the inherited loop; manual step 4 | automated; manual |
| Quality and Slicer test scripts pass | `run-python-quality.ps1`, `run-slicer-tests.ps1`, `run-slicer-tests.ps1 -Headful` | automated |

Tests to add or change, and how each one will be shown to fail first:

- `test_classColorTableMatchesUc1Palette` presents a valid `majorityVotingMap`
  through `presentSelectedResult`, takes the class colour node from the result
  display node, and asserts the name and RGBA of all five entries against an
  expected table written in the test and citing the UC1 source. It is run
  against the current table before the logic changes and must fail on the class
  1 entry, which is the first that disagrees. Its small in-memory map is an
  automated unit-test fixture only; it is not a manual image and must not be
  used as evidence for the recorded-input visual check.
- `test_resultPresentationForSupportedMapTypes` is not changed.

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Run the genuine UC1 pipeline against an approved recorded input (for example `input\\bin\\bin\\004-02`, using `run-end-to-end-session.ps1 -Case 004-02`), connect the UC1 link, enable **Demo mode** (the recorded-session acquisition is simulated and the banner must remain visible), then display its `majorityVotingMap` in SLIAFlow | Every class present in the recorded UC1 result uses its contract colour: normal pure green, tumour pure red, hypervascularized pure blue, and background black; no orange or dark-grey substitution appears. The result banner says the input is simulated but the UC1 pipeline is real. Do not create or load a synthetic four-class map for this step. | |
| 2 | Compare the pane against `output/<dataset>/imageRGB.bmp` written by that same genuine UC1 run on the recorded input | The pane and that run's BMP agree in class colouring, and the Slicer pane is the expected 180° rotation of the BMP. Do not use `workspace\\simulators\\datasets\\sim-*` or any phantom-generated BMP for this comparison. | |
| 3 | Read the class-value section of `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md` | It states the four class colours, cites the UC1 source they were read from, and says a UC1-side change is not detected | |
| 4 | In a Slicer window with Developer Mode on, open SLIAFlow and press **Reload and Test** | No error dialog; the Python console lists every `test_*` with `ok` or `skipped`, ending in `OK` (1 expected skip: `test_headlessPresentationFallback`) | |

## Risks

Reading the palette from the wrong place would encode a second wrong answer that
looks authoritative because it is now documented and tested. The requirement to
cite the source exists for that reason. The `rgbMv` buffer is in B, G, R order,
so reading `majorityVoting` alone would swap tumour and hypervascularized - the
most dangerous possible error for this card. The citation names both functions
for that reason.

UC1 draws the background class in black, and the result slice view is black
behind it. A class 4 region is therefore not visually distinguishable from an
empty view. That is what the pipeline does and matching it is the point of this
card; the waiting status and annotation remain what tells the operator whether a
map is displayed. Changing it is a conversation with the pipeline's owner.

## Documentation impact

- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`: the class palette, with its
  source.

## Completion evidence

Implementation recorded 2026-09-15 on `feature/SLIA-015-class-palette-alignment`.
The recorded-input manual evidence is now available below; the Result cells,
independent review, and final approval remain project-owner lifecycle actions.

### Changed files

- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`: class entries 1-4
  set to `(0,1,0)`, `(1,0,0)`, `(0,0,1)`, `(0,0,0)`, opaque; index 0 unchanged
  and transparent; source cited in a comment.
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`: added
  `UC1_CLASS_PALETTE` (independent literal citing the UC1 source),
  `test_classColorTableMatchesUc1Palette`,
  `test_classMapSlicePipelineEmitsUc1Colors` (reads the display node's
  `GetOutputImageDataConnection()` RGBA per voxel), a `runTest` override that
  runs `moduleTestNames` through `unittest.TextTestRunner`, and
  `test_reloadAndTestRunsPastSkippedTests` (two local probe cases: skip-then-pass
  must run both and report the skip; a failure must raise `AssertionError`).
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`: palette table, its source,
  the B,G,R buffer warning, the black-background note, and a corrected statement
  of what the tests protect (SLIAFlow's side only).
- `docs/development/testing_strategy.md`: "Test discovery" no longer forbids
  overriding `runTest`; it explains why the override exists and names its guard.
- This card: moved from backlog to active, specification completed, scope
  extension and source hashes recorded.

### Test observed failing first

`.\scripts\development\run-slicer-tests.ps1` with the new test and the original
table (exit code 1, `Ran 51 tests`, `FAILED (failures=1, skipped=6)`):

```text
FAIL: test_classColorTableMatchesUc1Palette
AssertionError: 0.10196078431372549 != 0.0 within 6 places (0.10196078431372549 difference) : entry 1 (Normal) component 0: got (0.10196078431372549, 0.8, 0.2, 1.0), expected (0.0, 1.0, 0.0, 1.0)
```

The stored `0.10196` is `26/255`: the colour table quantizes to 8 bits. The UC1
values are all 0 or 1, which are exact at 8 bits, so the six-place comparison is
sound.

After the scope extension, the two new tests were run with the original table
temporarily restored in `_getOrCreateClassColorNode` and without the `runTest`
override (exit code 1, `Ran 53 tests`, `FAILED (failures=3, skipped=6)`); the
table was then put back to the UC1 palette:

```text
FAIL: test_classMapSlicePipelineEmitsUc1Colors
AssertionError: Tuples differ: (26, 204, 51, 255) != (0, 255, 0, 255) : voxel 0, class 1 (Normal)

FAIL: test_reloadAndTestRunsPastSkippedTests
  File "...\slicer\ScriptedLoadableModule.py", line 506, in runTest
    getattr(self, test_name)()
unittest.case.SkipTest: probe skip
AssertionError: a skipped test ended the run early: probe skip
```

The third failure in that run was `test_classColorTableMatchesUc1Palette`, with
the same message as above.

### After the change

| Check | Command | Result | Exit |
| --- | --- | --- | --- |
| Static analysis | `.\scripts\development\run-python-quality.ps1` | Ruff 0.15.21, both targets `All checks passed!` | 0 |
| Slicer tests, source, headless | `.\scripts\development\run-slicer-tests.ps1` | `Ran 53 tests`, `OK (skipped=6)`; module loaded from `C:\stratum\extensions\SLIAFlow\SLIAFlow\SLIAFlow.py`; the three new tests and `test_resultPresentationForSupportedMapTypes` all `ok` | 0 |
| Slicer tests, source, headful | `.\scripts\development\run-slicer-tests.ps1 -Headful` | `Ran 53 tests`, `OK (skipped=1)`; the only skip is `test_headlessPresentationFallback` ("covers only Slicer's no-main-window fallback"); the six headless-skipped layout, banner and pane-binding tests `ok` | 0 |
| Whitespace | `git diff --check` | clean | 0 |

The first Ruff run flagged `B905` (`zip()` without `strict=`) in the new test;
fixed with `strict=True` before the red run.

Both runners go through `unittest.TextTestRunner`, so neither exercises the
button's own entry point. `test_reloadAndTestRunsPastSkippedTests` covers the
override by calling `runTest` directly, as the button does; manual step 4 is the
end-to-end check.

### Correction to an earlier verification attempt

The earlier visual capture based on `sim-20260904-150404/imageRGB.bmp` came from
the simulator's synthetic tissue-phantom path. It is invalid evidence for manual
steps 1 and 2 and must be ignored. The corrected check uses recorded case
`004-02`, the genuine UC1 `majorityVotingMap`, and the `imageRGB.bmp` produced by
that run; it is the only candidate evidence for steps 1 and 2. The Result column
remains for the project owner to fill from the observed run.

### Remaining or owner-entered items

- `-Target Build` and CTest: the launcher was not rebuilt; the Slicer test
  command checks the existing build, not a rebuilt launcher.
- The Result cells remain blank for the project owner to fill.

### Recorded-input manual evidence

- Step 1 used recorded case `004-02`, connected the genuine UC1 server, and
  displayed `majorityVotingMap` in Demo mode. The received node was
  `(1, 389, 345)` `uint8`, contained classes 1-4, and the result report was
  `PASS`. The banner identified simulated acquisition and the real UC1
  pipeline.
- Step 2 compared the received class map with the `imageRGB.bmp` from that
  run: the decoded class colours matched all pixels, and the visible Slicer
  result pane was the expected 180-degree rotation of the BMP.
- Step 3 confirmed the contract palette and UC1 source citation.
- Step 4 ran the headful suite in the built Slicer application: 53 tests,
  `OK (skipped=1)`.

### Pre-review findings addressed (2026-09-15)

| # | Finding | Resolution |
| --- | --- | --- |
| 1 | High: the table test does not prove the rendered appearance | `test_classMapSlicePipelineEmitsUc1Colors` asserts per-class emitted RGBA after window/level, including opaque black for class 4; the screen itself remains manual step 1 |
| 2 | Medium: UC1 source not reproducibly pinned | SHA-256 of the four source files recorded in the context section |
| 3 | Medium: contract overstated regression protection | Contract now says only SLIAFlow-side changes fail a test and points to the hashes |
| 4 | Low: review snapshot not durable in Git | Resolved by the owner's explicit authorization to commit and push the final non-WIP task commit |

## Review findings

Reserved for review.

## Human approval

Activated on 2026-09-15 under the project owner's `Start the next task`
instruction. Required again before review and completion.
