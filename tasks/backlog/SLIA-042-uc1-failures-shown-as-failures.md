---
id: SLIA-042
title: UC1 failures shown as failures - a GPU error ends the run, and cubes over the measured size are refused
status: backlog
branch:
priority: high
depends_on: SLIA-040
required_skills: [slicer]
optional_tools: []
related_adrs: [ADR-0004, ADR-0006]
---

# SLIA-042 - UC1 failures shown as failures - a GPU error ends the run, and cubes over the measured size are refused

## Goal

A UC1 run that fails on the GPU ends as a failure, with the reason on the
panel, instead of exiting normally with blank or single-colour images that
SLIAFlow shows as a result. A cube larger than UC1 was measured to handle on
this laptop is refused before Capture freezes anything, saying why.

## Context

*Created on 2026-10-09* at the project owner's request ("Do all"), from the
project audit of 2026-10-09 (`workspace/audits/`, gitignored) and the review of
it.

- UC1 checks almost none of its GPU calls. Out of GPU memory, it exits 0 and
  writes images (`docs/development/uc1_performance.md`, size limit). On this
  laptop 2300 x 2300 (5.3 million pixels) ran and 2430 x 2430 failed in each
  of four runs; 2700 x 2700 failed too. The `SLIA-034` review kept this as a
  documented limitation.
- In the staged `functions_cuda.cu` all 39 `checkCudaError(__LINE__)` calls are
  commented out. `checkCudaError` (line 1662) prints `Cuda Error: ...` and
  returns -1. The only call to `cudaGetLastError` in UC1's source is inside it,
  so nothing clears CUDA's last error during a run: one check at the end sees
  any earlier failure. `main.cu` ends without a return statement, so UC1 exits
  0 whatever happened.
- SLIAFlow accepts outputs that exist, were written by this run, are valid BMPs
  and have the cube's size (`SLIAFlowUc1Run.collectOutputs`). It fails a run on
  a start failure, a timeout, a crash, a nonzero exit or `Path too long` in
  UC1's output (`_processFailure`). Blank images of the right size pass.
- IUMA's 16 captures are 1.2 to 1.4 million pixels. The camera's full frame,
  4096 x 2160, is 8.8 million.
- `build-uc1.ps1` builds for compute capability 12.0 only (`sm_120` and PTX
  `compute_120`, line 127). It prints the GPU's `compute_cap` (line 341) but
  does not compare it. On an older GPU it builds without complaint, and UC1's
  kernels cannot run there.
- `ADR-0004` decision 3 allows UC1 changes as versioned patches applied at
  staging and documented in `uc1_changes.md`. `ADR-0006` decision 3: a capture
  that cannot run is listed, and says why.

## Requirements

### 1. UC1 exits with an error when a GPU call failed (patch 0004)

- After `computingClassification` returns, and before `imageRGB.bmp` is
  written, UC1 waits for the GPU (`cudaDeviceSynchronize`) and reads CUDA's
  last error (`cudaGetLastError`). On any error it prints
  `Cuda Error: <cudaGetErrorString>` on stderr and returns 1.
- A run without a CUDA error is unchanged: no output differs, and
  `check-uc1.py` passes with the hashes recorded on 2026-10-07.
- Documented in `uc1_changes.md` as patches 0001-0003 are: what, why, the
  command run and what came out.
- Check at specification: whether a run that succeeds today leaves a harmless
  CUDA error behind that would now fail it (`check-uc1.py`, and
  `check-captures.py` on all 16 captures).

### 2. SLIAFlow reads UC1's error line

- `Cuda Error` in UC1's output fails the run, as `Path too long` does, with
  UC1's line in the reason. The previous result stays, marked as previous.

### 3. Cubes over the measured size are refused

- A cube whose lines x samples exceed the largest size measured to run on this
  laptop, 2300 x 2300 (5,290,000 pixels), is refused before Capture freezes,
  saves or starts anything. The reason names the cube's size, the limit and
  where it was measured. The same holds for a cube received from the app, and
  `check-captures.py`'s Cube step reports it.
- The limit is one named constant beside `MAX_PATH_LENGTH` in
  `SLIAFlowUc1Run.py`, with its source.
- Check at specification: a constant, or a key in `config/local.example.json`,
  since the limit belongs to the GPU rather than to the code; and whether
  `ADR-0006` decision 2 ("any dimensions") needs a note, since this is a
  capacity limit, not a shape assumption.

### 4. The UC1 build stops on a GPU it cannot target

- `build-uc1.ps1` compares the GPU's `compute_cap` with its target and stops,
  with a message saying both and what to change, when the GPU's is lower.
- Check at specification: refuse only, or take the target from the GPU found,
  and what that means for the recorded hashes on another machine.

### 5. Documents

`uc1_changes.md` (patch 0004), `uc1_performance.md` (the size limit now ends
with an error), `capture_compatibility.md` (failure table: over the supported
size; `Cuda Error`), the module README (the refusal and the failure), and
`uc1_local_build.md` (the GPU check).

## Out of scope

- Checking every CUDA call, cuBLAS status and kernel launch one by one. A later
  card can do that; requirement 1 already catches the measured failure.
- Raising the limit: `PCA_PD=0`, tiling, cropping or binning a cube. Each
  changes UC1's outputs and is the owner's or the partners' decision.
- Building for another GPU.
- Any change to UC1's outputs on a run that succeeds.

## Files allowed

Proposed; confirmed at specification.

- `scripts/development/uc1-patches/0004-cuda-error-exit.patch` (new)
- `scripts/development/build-uc1.ps1`
- `scripts/development/measure-uc1.py` (its size ladder reads the new exit code)
- `scripts/development/check-captures.py` (the Cube step calls the size check)
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowUc1Run.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `extensions/SLIAFlow/README.md`
- `docs/development/uc1_changes.md`, `uc1_performance.md`, `uc1_local_build.md`,
  `capture_compatibility.md`

## Relevant skills and references

- Slicer skill for the module change and its tests.
- `docs/development/uc1_performance.md` (size limit), `uc1_changes.md` (how a
  patch is added), `SLIA-034` (how the size ladder was measured).

## Implementation plan

To be written at specification.

## Acceptance criteria

To be written at specification. At least:

1. On 2430 x 2430 (`measure-uc1.py sizes 2430x2430`) UC1 exits 1 with a
   `Cuda Error` line; 2300 x 2300 still runs and its SVM map is the tiled
   baseline.
2. `check-uc1.py` passes with the recorded hashes, and `check-captures.py`
   passes 16 of 16.
3. A run whose output holds `Cuda Error` fails, with that line in the reason
   and the previous result kept as previous, whatever its exit code.
4. Capture refuses a cube over the limit before freezing, with its size, the
   limit and where it was measured; a received cube is refused the same way;
   `check-captures.py` reports it as a Cube failure.
5. `build-uc1.ps1` stops with its message when the GPU is below the target.

## Test plan

To be written at specification. Proposed:

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| 1 | `measure-uc1.py sizes 2430x2430` and `sizes 2300x2300` | scripted |
| 2 | `check-uc1.py`; `check-captures.py` | scripted |
| 3 | A test with a fake UC1 process that prints `Cuda Error: out of memory`, once with exit 0 and once with exit 1 | automated |
| 4 | A test with the limit lowered below a placeholder cube, for a cube on disk and a received cube | automated |
| 5 | `build-uc1.ps1` with the target set above this GPU's 12.0 | scripted |

## Manual verification

To be written at specification: the built application on `S-N-002-04` and a
1080 x 1301 capture (both run as before), and a cube over the limit sent by the
stand-in for IUMA's app (refused before freezing, with the reason).

## Risks

- A harmless CUDA error left by a run that succeeds today would now fail it.
  Requirement 1's check at specification finds it before the patch is adopted.
- The limit is this laptop's. More GPU memory used by the desktop lowers it,
  and another GPU moves it (`uc1_performance.md`).
- A patch changes the staged tree; the reference-tree check of `build-uc1.ps1`
  includes it, as for 0001-0003.

## Documentation impact

Requirement 5.

## Completion evidence

## Review findings

## Human approval
