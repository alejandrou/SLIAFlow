---
id: SLIA-021
title: Run UC2 blood-vessel enhancement as an independent map producer
status: backlog
branch:
priority: high
depends_on: SLIA-022, SLIA-023
required_skills: []
optional_tools: []
related_adrs: [ADR-0001]
---

# SLIA-021 - Run UC2 blood-vessel enhancement as an independent map producer

## Goal

Turn the vendored UC2 blood-vessel enhancement into a process that reads a
dataset and streams its result over OpenIGTLink, the way `SLIA-013` did for UC1,
and show that result in the vascularization panel. This is MS5 point 3, and the
second of WP2's three critical epics.

## Context

WP2 marks three epics critical: the common HSI contract, the independent UC2
service, and cube-and-result transport. Two of the three have been worked. UC2
has nothing: no map role, no device name, no port, no runner, no test.

The component builds and runs unchanged. It has been compiled with the MinGW GCC
on this machine and **already run on four recorded cases** - `007-01`, `008-01`,
`008-02`, `010-03` - each producing a BVMap PNG, with no change to either side.
So EPIC 1's critical acceptance criterion, a cube processed by UC2 without manual
renaming, already holds.

This card was rewritten on 2026-09-11 against
`docs/architecture/WP5_MS5_DEMO_PLAN.md`, workstream D. Four of its original
findings changed, and three of them shorten the work.

### The band mismatch is gone

The original card's central finding was that `main.c`'s hard-coded band indices
54, 20 and 8 named 708.97, 539.44 and 479.06 nm but landed on 752.80, 530.97 and
452.68 nm on the synthetic 93-band grid, putting the red enhancer band 43.8 nm
into the near infrared. It concluded that bands must be selected by wavelength.

All 61 recorded cases share one grid: **440 to 900 nm in 5 nm steps**. Indices
54, 20 and 8 resolve to exactly **710, 540 and 480 nm**. The mismatch was an
artefact of the synthetic grid, not of the algorithm, and recorded data removes
it. Verified across all 61 headers on 2026-09-11.

The wavelength-selection requirement is therefore dropped, and it could not have
been implemented anyway: see the next finding.

### The four parameters cannot be passed from a wrapper, and neither can the band indices

The original card required `high_in`, `high_out`, `gamma` and `bValue` to be
"settable at the wrapper boundary", and called that the one thing lengthening the
task. It is not implementable. They are **local variables inside `main()`**, in
both branches of its switch, and the binary takes exactly one argument:

```
if (argc != 2) { fprintf(stderr, "Usage: %s <HSI_folder_path>\n", argv[0]); return 0; }
```

The band indices are locals in the same function. Setting any of the seven from
outside requires editing `main.c`, which is out of scope in this card and in the
plan. So the runner **records** the fixed values (`high_in = 0.15`,
`high_out = 0.8`, `gamma = 1`, `bValue = 3`; bands 54, 20, 8) as part of each
run's provenance, and configurability stays a written request to ULPGC. The
source flags it itself, in capitals: `SHOULD BE INPUT VARIABLES!!!!!!!`.

### The output form is settled the other way

The original card chose to stream the float map before `normalize_rgb_array`,
because per-image normalization is not comparable between captures. That
reasoning is still correct and is still worth reporting, but the binary
**can only write the PNG**. `computeBVmapLCTF` returns the float map to `main()`,
which passes it straight to `save_BVMap_as_png` and frees it. Getting the float
out requires editing UC2.

So this card streams **the PNG, as an RGB image, as written**. The deliverable's
reference image is a colour image in any case. The cost is recorded rather than
hidden: `normalize_rgb_array` rescales each channel to its own min and max within
one image, so two captures of the same tissue can come out different colours and
cannot carry a colour bar. It goes on the request list.

### The saturation question is answered, and the answer is not `high_in`

The original card said `high_in = 0.15` saturates most of the frame, citing
`SLIA-019`'s phantom measurement. The four recorded BVMaps answer it without
running anything. Fraction of pixels at 255, measured 2026-09-11:

| Case | Blue | Green | Red |
| --- | ---: | ---: | ---: |
| 007-01 | 47.1% | 1.4% | 3.1% |
| 008-01 | 96.3% | 0.0% | 0.1% |
| 008-02 | 69.7% | 0.2% | 0.5% |
| 010-03 | 89.2% | 0.0% | 0.1% |

Real data still saturates heavily, but through a different mechanism. The blue
output channel is `|I2 * bValue - calibrated[0]|` with `bValue = 3`, and
`clip_array` clamps it at 1.0 before normalization, so nearly every pixel above
the clip maps to 255. It is the `bValue` multiply clipping, not the `high_in`
stretch. `SLIA-019`'s diagnosis stands as a phantom diagnosis and does not
transfer. This is an observation about the algorithm on real data: recorded,
reported, not corrected and not compensated for.

### The enhancer channel is still the blue band

`computeBVmapLCTF` takes `enhancer_ch` from calibrated plane 0, which after
`extract_selected_bands_LCTF_BSQ(cube, lines, samples, red=54, green=20, blue=8)`
is the **blue** band at 480 nm, while the adjacent comment says red and "the
third band". The C output is documented as matching its MATLAB reference, so the
behaviour is presumably intended and the comment stale. Either way it is the
authors' to resolve. Report it; do not change it, and do not compensate for it in
the wrapper, because a wrapper that silently corrects an algorithm produces
results nobody can trace.

### One mechanical constraint on the runner

`save_BVMap_as_png` is called from `main()` with a hard-coded output folder of
`"."`, so the PNG lands in the **process working directory**, named
`<case>-BVMap.png`. The runner controls the output location only through CWD, and
needs the same freshness guard `uc1_runner.py` already has - a timestamp taken
immediately before the process starts - or a stale PNG from an earlier run passes
for this run's result. Two cases with the same folder name would also collide.

### Both copies of the component are identical

The two copies were diffed on 2026-09-11. Every source file is byte-identical;
only `CODE_REVIEW.md`, the four output PNGs, an `input/` folder and `main.out`
differ. `git status` over the vendored copy is therefore a sufficient untouched
check, and the desktop copy is checked the same way.

## Requirements

- Build the vendored component reproducibly on Windows and record the exact
  command, the toolchain and its version.
- Provide a runner that takes a dataset folder, runs UC2, and streams the result
  over OpenIGTLink on port 18946, following the structure of
  `stratum_sim/uc1_runner.py` rather than inventing a second shape.
- Run the binary with its working directory set so the PNG lands where the runner
  expects it, and take a timestamp immediately before the process starts so that
  a stale PNG is a failure rather than a result.
- Read the PNG back and stream it as a three-component `uint8` RGB image.
- Record, in the runner's output and in the task evidence, the band indices and
  the four algorithm parameters the binary used, stating that they are fixed in
  `main.c` and cannot be set from outside.
- Carry provenance as the UC1 runner does. A map computed by the genuine UC2
  binary on a recorded cube is a real pipeline under a simulated acquisition, and
  its detail must say so in wording distinct from UC1's.
- Define the map role `bloodVesselMap` and the device name `UC2_BV`, and add them
  to the OpenIGTLink contract table with component count and data type.
- Show the result in the vascularization panel as a layer, per `ADR-0001`.
- Make no change of any kind to the files under
  `workspace/components/blood_vessels_enhancement` or to the desktop copy. A
  defect found in the component is reported to its authors, not patched here and
  not compensated for in the wrapper.

## Out of scope

- Any correction to the component's own code, including the `enhancer_ch` index,
  the hard-coded parameters, the hard-coded band indices and the hard-coded
  output folder.
- Streaming the float map. The binary cannot produce it without being modified.
- Selecting bands by wavelength. The indices are locals in `main()`; there is no
  boundary at which a wrapper could supply them.
- Deciding the final output form for the consortium. This card streams the PNG
  because that is what the binary produces, and records the comparability cost as
  input to the decision. It does not close the question.
- Transporting the cube over the network, which is `SLIA-023`.
- Any metric computed against `gtMap`, and any comparison of UC1's and UC2's
  outputs presented as validation. Neither has a ground truth here.

## Files allowed

- `tools/simulators/stratum_sim/uc2_runner.py`
- `tools/simulators/stratum_sim/__main__.py`
- `tools/simulators/stratum_sim/contract.py`
- `tools/simulators/tests/test_uc2_runner.py`
- `tools/simulators/tests/run_tests.py`
- `tools/simulators/README.md`
- `scripts/development/build-uc2.ps1`
- `scripts/development/run-end-to-end-session.ps1`
- `docs/development/uc2_local_build.md`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`
- `docs/architecture/WP5_MS5_DEMO_PLAN.md`
- `tasks/{backlog,active,review,completed}/SLIA-021-uc2-independent-map-producer.md`

## Relevant skills and references

- `docs/architecture/WP5_MS5_DEMO_PLAN.md`, workstream D
- `docs/architecture/decisions/ADR-0001-overlay-result-on-cube-derived-rgb.md`
- `tools/simulators/stratum_sim/uc1_runner.py`, the shape this follows, in
  particular its freshness guard and its exclusive lock
- `docs/development/uc1_local_build.md`, the precedent for recording a build
- `workspace/components/blood_vessels_enhancement/main.c`, `BV_enhancement.c`,
  `png_writer.c`
- `.ai/policies/algorithm-boundary-policy.md`

## Approved dependencies

None beyond the MinGW GCC toolchain already installed, which is recorded rather
than added, and OpenCV, already a simulator dependency, for reading the PNG back.

## Implementation plan

1. Record the build: command, toolchain version, warnings, and the checksum of
   the binary produced.
2. Write the freshness guard and its failure case first, and show a stale PNG
   being accepted before it exists.
3. Write the runner, following `uc1_runner.py`, and prove the provenance wording
   differs from UC1's.
4. Add the role, the device name and the port to the contract and the roadmap.
5. Add the vascularization layer to the panel.
6. Run against a recorded case and record the parameters, the wall-clock per
   cycle, the saturated fraction of each output channel, and what the map
   contains.

## Acceptance criteria

- The component builds from a recorded command on this machine.
- The runner streams a UC2 result on port 18946 and a client receives it.
- A stale PNG from a previous run is refused rather than sent.
- The fixed band indices and the four parameters are reported with every run,
  with a statement that they cannot be set from outside.
- Provenance identifies a genuine UC2 pipeline under a simulated acquisition, in
  wording distinct from UC1's.
- The result appears in the vascularization panel.
- No file under either copy of `blood_vessels_enhancement` is modified.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| A stale output PNG is refused | `test_uc2_runner.test_refuses_stale_output_png` | automated |
| A missing output PNG is refused | `test_uc2_runner.test_refuses_missing_output_png` | automated |
| A non-zero exit is refused, never fallen back from | `test_uc2_runner.test_refuses_failed_process` | automated |
| Parameters and band indices are reported with the run | `test_uc2_runner.test_run_record_states_fixed_parameters` | automated |
| Provenance is distinct from UC1's | `test_uc2_runner.test_provenance_names_uc2_pipeline` | automated |
| The map is sent as three-component uint8 | `test_uc2_runner.test_sends_rgb_uint8` | automated |
| The component builds from the recorded command | Manual step 1 | manual |
| A client receives the streamed map | Manual step 2 | manual |
| Both component copies are untouched | Manual step 3 | manual |
| The vascularization panel shows the map | Manual step 4 | manual |
| Per-image normalization is demonstrated, not asserted | Manual step 5 | manual |

Tests to add or change, and how each one will be shown to fail first:

- `test_refuses_stale_output_png` writes a PNG with an old modification time and
  is shown being accepted as a result before the freshness guard exists. This is
  the test that matters most: the output path is fixed and shared, so an
  existence check cannot tell this run's output from last week's.
- `test_provenance_names_uc2_pipeline` is first written asserting UC1's wording
  and shown failing, to prove the assertion is not vacuous.

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Run `scripts/development/build-uc2.ps1` on a clean checkout | The binary is produced; command, toolchain version and warnings are recorded | |
| 2 | Start the runner against a recorded case and attach a client | The client receives the map; the console names the fixed band indices and the four parameters and states they are not settable from outside | |
| 3 | `git status` on the vendored copy, and a recursive diff against the desktop copy | No modification in either | |
| 4 | Run a full session and look at the vascularization panel | The BVMap is shown as a layer under the simulated banner | |
| 5 | Run two different cases and compare the colours of comparable tissue | The colours differ between captures; the measurement is recorded as the evidence for the comparability request, not treated as a defect to fix here | |

## Risks

Running two genuine pipelines against one dataset makes it tempting to compare
their outputs and call agreement validation. It is not. Neither output has a
ground truth here, and `gtMap` is out of scope by design.

The component contains at least three things that look like defects - the
enhancer channel taken from the blue band while the comment says red, the fixed
parameters, the fixed output folder - and none of them may be treated as one
here. A wrapper that silently corrects an algorithm produces results nobody can
trace.

The output path is fixed and shared between runs, so the single most likely way
this card ships a wrong result is a stale PNG passing for a fresh one. That is
why the freshness guard is written and shown failing first, exactly as
`uc1_runner.py` did.

`pyigtl.OpenIGTLinkServer` serves one client at a time, which `SLIA-018` records.
A third producer on a third port inherits that behaviour and the same diagnostic
gap.

## Documentation impact

- `docs/development/uc2_local_build.md`: new, mirroring the UC1 build record.
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`: the new role, device
  name and port in the contract table, and UC2 in the implementation order.
- `tools/simulators/README.md`: the runner, its inputs, its refusals, and the
  fixed parameters it can only report.
- `docs/architecture/WP5_MS5_DEMO_PLAN.md`: mark workstream D done, and record
  the measured comparability evidence.

## Completion evidence

Reserved.

## Review findings

Reserved for review.

## Human approval

Required before activation and before completion.
