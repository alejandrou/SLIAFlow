---
id: SLIA-011
title: Simulator toolchain and acquisition simulator
status: active
branch: feature/SLIA-011-acquisition-simulator
priority: high
depends_on: SLIA-010
required_skills: []
optional_tools: []
related_adrs: []
---

# SLIA-011 - Simulator toolchain and acquisition simulator

## Goal

Stand in for the missing hyperspectral camera with a separate process that writes
a real ENVI/BSQ dataset and streams an RGB `LiveView` frame over OpenIGTLink, so
that the genuine UC1 pipeline and the real acquisition application both have
something valid to consume.

## Context

SLIAFlow is the visualization end of a three-part system: `AcquisitionSystemApp`
produces a hyperspectral cube and a LiveView stream, the UC1 CUDA pipeline turns
the cube into brain-tumour maps, and SLIAFlow displays them. Only the first box
is unavailable; the CUDA toolchain for the second is installed and proven
(see SLIA-013).

The stand-ins deliberately live **outside** `extensions/`, as separate processes
standing where the real components stand. That is what keeps SLIA-010's rule
intact and what makes the eventual swap trivial: the seam is the network boundary
the architecture already has. Stopping a simulator and starting the real
application on the same port is the entire migration.

`AcquisitionSystemForm/SimulatedCaptureWorker.cpp` shows the real acquisition
application already has a hardware-free mode that replays an ENVI cube loaded by
`HSCubeLoader`, so a correctly formed generated dataset has three consumers: the
real UC1 binary, the real acquisition application's simulated capture, and our
own stand-in.

Cube format facts verified against vendored source, not to be re-derived:

- BSQ index is `band * totalPixels + line * samples + sample`, so a NumPy
  `(bands, lines, samples)` C-order array's `.tobytes()` is already BSQ.
- White and dark references are **full cubes**, so one dataset is three times the
  cube size.
- The UC1 header parser reads exactly three keys with `sscanf` and stops after
  three hits, so `samples`, `lines` and `bands` must be at column 0 before the
  long `wavelength` block.
- `MAX_PATH_LENGTH` is 128 and the same buffer reads header lines, so both the
  dataset path plus `/whiteReference.dat` and every header line must stay under
  128 bytes.
- `HSCubeLoader` requires `data type = 12`, `interleave = bsq`, strips `;`, and
  wants `data file = raw.dat`; one header serves both consumers if it never
  contains a `;`.
- LiveView is RGB rotated 180 degrees: `std::reverse` over a `Format24bppRgb`
  buffer flips rows, flips columns and swaps BGR to RGB in one pass.
- `numberOfClasses = 4` and `w_vector` is `bands * 6 * 4` bytes, which
  double-confirms `bands = 93`.

## Requirements

- Create `tools/simulators/` as a standalone Python package (`stratum_sim`) with
  `__init__.py`, `__main__.py`, `config.py`, `contract.py`, `envi.py`,
  `spectra.py`, `frames.py`, `igtl_transport.py`, and `acquisition_sim.py`, plus
  a `tests/` directory with a stdlib `unittest` runner.
- Add `scripts/development/run-acquisition-simulator.ps1`.
- Read configuration from a `simulators` block in the already-ignored
  `config/local.json`, documented in `config/local.example.json`. Write datasets
  under `workspace/simulators/`. Neither location needs a `.gitignore` change.
- Reuse the root `.venv` (Python 3.10.11). Do not create a second virtual
  environment.
- Synthesize the cube as a NumPy `(bands, lines, samples)` C-order array with 93
  bands linearly spaced over the real Headwall range 400.482 to 1000.73 nm
  (step 6.5244 nm), taken from `VNIRwhiteReferenceUHDrN.hdr`.
- Build reflectance by resizing the BGR frame, normalizing it, and mixing
  Gaussian response curves (B mu=470 sigma=45, G mu=540 sigma=45, R mu=620
  sigma=55) plus a broad luminance-driven NIR envelope over 700 to 1000 nm.
- Scale by inverting UC1's own calibration `100 * (raw - dark) / (white - dark)`:
  generate `dark` and `white` first, then `raw = dark + reflectance * (white -
  dark)`, keeping `white > dark` strictly everywhere so UC1's `white != 0` guard
  never fires.
- Draw the white and dark references once per process, and derive per-frame noise
  from `default_rng([seed, frameIndex])`. Default `noiseCounts` to 0 so the
  round-trip test is exact.
- Size the spectral basis to the rank the downstream pipeline needs, and measure
  that rank rather than assuming it. Three Gaussian channel curves plus one broad
  NIR envelope span a rank-4 subspace, and with the default `noiseCounts` of 0
  that is the exact numerical rank of the whole cube no matter how many bands are
  nonzero. Add independent basis curves - narrow features at distinct centres
  whose spatial weights are generated independently of the RGB channels - until
  the measured numerical rank of the calibrated cube's band covariance clears the
  number of principal components UC1 requests, read from `parameters.txt` rather
  than assumed. Achieve the rank through the basis, not through noise, so the
  default `noiseCounts` of 0 can stay and the calibration round-trip stays
  exact.
- Offer `demo` (160x120), `medium` (320x240) and `full` (640x480) presets, with
  `demo` as the default. Keep `samples` a multiple of 4 so BMP row padding is
  zero.
- Emit the ENVI header with `samples`, `lines` and `bands` at column 0 before the
  wavelength block, containing no `;`, and carrying a `STRATUM SIMULATED CUBE`
  marker in its description.
- Refuse to write if the dataset path would exceed the 128-byte cap; refuse to
  overwrite a folder whose existing `raw.hdr` lacks the simulated marker; name
  folders `sim-YYYYMMDD-HHMMSS`; assert the generated `w_vector.bin` size equals
  `bands * 6 * 4`.
- Send LiveView exactly as `OpenIGTLinkServer.cpp` lines 194-226 does: a
  **server** socket on `127.0.0.1:18944`, device name `LiveView`, uint8, three
  components, dimensions `{w, h, 1}`, spacing `{1, 1, 1}`, identity matrix, LPS,
  send only on sequence change, and reconnect on failure. Default
  `rotate180: true` so the simulator matches real acquisition behaviour and
  SLIA-008 does not "fix" it.
- Default `frameSource` to `synthetic`, and define a `FrameSource` protocol with
  a single `read() -> ndarray | None` method so `synthetic` and `webcam` are
  interchangeable.
- Define the producer seam in `contract.py` around a **dataset**, not an
  in-memory cube: a frozen `DatasetRef` dataclass carrying the dataset folder
  path, `samples`, `lines`, `bands`, the wavelength array, the simulated-marker
  flag, and a `loadCalibratedCube()` method that reads and calibrates on demand.
  Define the `Classifier` protocol as `classify(dataset: DatasetRef) -> Uc1Maps`.
  A calibrated cube plus wavelengths is **not** a sufficient input: SLIA-013's
  producer is an executable that takes a folder path and opens `raw.dat`,
  `whiteReference.dat`, `darkReference.dat` and `raw.hdr` itself, so a protocol
  accepting only an array cannot express the real producer at all. The stand-in
  calls `loadCalibratedCube()`; the real runner uses `dataset.folder` and never
  materializes the cube.
- Make every field of `Uc1Maps` optional, defaulting to `None` and meaning "this
  producer did not produce this map". A consumer must never substitute zeros for
  an absent map. SLIA-013 populates one field of five, and that has to be
  representable without lying.
- Have the writer return a `DatasetRef` for the dataset it just wrote, and
  provide a loader that builds an equal one from an existing folder, so both
  producers reach a dataset by the same route.
- `Classifier` is unimplemented here; it is the seam SLIA-012 and SLIA-013 plug
  into.
- Send every OpenIGTLink message with pyigtl header version 2. This is measured,
  not assumed: on pyigtl 0.3.4 a freshly constructed `ImageMessage` has
  `header_version = 1`, and packing the four provenance keys at version 1 emits
  only a `logger.warning` - "Metadata will not be packed" - then returns a
  well-formed 146-byte message whose metadata unpacks to `{}`. The identical
  message at version 2 packs to 316 bytes and round-trips all four keys. So a
  version-1 send drops every provenance attribute SLIA-012 and SLIA-013 depend
  on, silently, behind a successful-looking send and a warning on the wrong side
  of the wire.
- Note the pyigtl API shape while wrapping it: `metadata` is **not** a
  constructor argument. `ImageMessage.__init__` takes only `image`,
  `ijk_to_world_matrix`, `world_coordinate_system`, `timestamp` and
  `device_name`, so `ImageMessage(..., metadata={...})` raises `TypeError`. Both
  `metadata` and `header_version` are plain attributes assigned after
  construction. Set them in one place in `igtl_transport.py` so no producer can
  forget either, and prove it with a test that asserts the metadata survives a
  pack and unpack round-trip, not merely that it was passed in.
- Define the wire metadata contract once, in
  `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`: the four string keys
  `SLIAFlow.ResultMap`, `SLIAFlow.DeviceName`, `SLIAFlow.DataOrigin` and
  `SLIAFlow.SimulationDetail`. SLIAFlow's `findResultSource` matches on role,
  device **and** origin together, so a producer that sends origin alone is
  received and then never discovered, which looks exactly like a transport
  failure and is not one.
- Record in that same document that SLIAFlow's receiving side does **not** see
  these keys verbatim. `vtkMRMLIGTLConnectorNode.cxx` copies incoming metadata
  onto the MRML node as `std::string tag = "OpenIGTLink." + iter->first;`,
  unconditionally, so the wire key `SLIAFlow.DataOrigin` becomes the attribute
  `OpenIGTLink.SLIAFlow.DataOrigin`. Send the bare names anyway - the prefix is
  the receiver's business, and changing what goes on the wire to pre-compensate
  would break the real applications this stand-in imitates. Reconciling the two
  names stays SLIA-008's job. The line above was read at commit
  `85e5f764f3ad3d4adbaa568db0104b2b8f5998e8`, which is the commit SLIA-007 pins,
  so it describes the build SLIAFlow will actually run against.
- Never let SLIAFlow infer `simulated` from a port or hostname. Provenance
  travels with the data, never with the endpoint.
- Measure and print the achieved frame rate on startup and record it in the
  completion evidence; treat throughput as an acceptance criterion, not an
  assumption.
- State the non-clinical nature of the generated data in the first paragraph of
  `tools/simulators/README.md`.

## Out of scope

- Any UC1 map generation or sending; that is SLIA-012 and SLIA-013.
- Any change inside `extensions/`.
- Changes to `AcquisitionSystemApp` or any vendored source under `workspace/`.
- Physically accurate tissue spectra. The synthetic scene only has to be
  non-degenerate, not realistic.

## Files allowed

- `tools/simulators/**`
- `scripts/development/run-acquisition-simulator.ps1`
- `scripts/development/run-python-quality.ps1`
- `pyproject.toml`
- `config/local.example.json`
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`
- `AGENTS.md`
- `docs/development/project_structure.md`
- `docs/development/coding_standards.md`
- `tasks/{backlog,active,review,completed}/SLIA-011-acquisition-simulator.md`

## Relevant skills and references

- `.ai/policies/medical-data-policy.md` and `.ai/policies/dependency-policy.md`
- `workspace/components/UC1_Brain_Tumor-GPU_optimization/.../source/functions.cu`
  lines 21 and 114-146 (BSQ index, full-cube references)
- `workspace/components/.../source/functions_cuda.cu` lines 835-839 (calibration)
- `workspace/components/.../source/data_loader.cpp` lines 66-79 and 94-110
  (dataset name derivation, three-key header parse)
- `workspace/components/.../source/data_loader.hpp` line 11 (`MAX_PATH_LENGTH`)
- `workspace/components/AcquisitionSystemApp/AcquisitionSystemForm/HSCubeLoader.cpp`
  lines 43-51
- `workspace/components/AcquisitionSystemApp/AcquisitionSystemForm/OpenIGTLinkServer.cpp`
  lines 194-226
- `workspace/components/AcquisitionSystemApp/AcquisitionSystemForm/GUI.cpp` line 114
- `workspace/components/AcquisitionSystemApp/AcquisitionSystemForm/SimulatedCaptureWorker.cpp`

## Approved dependencies

Per `.ai/policies/dependency-policy.md`, this task approves the following for
`tools/simulators/requirements.txt` only. They are installed into the existing
root `.venv` and are never added to
`extensions/SLIAFlow/SLIAFlow/Resources/requirements.txt`, which is the
Slicer-runtime file and stays OpenCV-only.

| Package | Pin | Why the standard library is insufficient |
| --- | --- | --- |
| `numpy` | `==2.2.6` | Cube synthesis and BSQ serialization need vectorized float arrays; 2.2.6 is the last 2.x supporting Python 3.10. |
| `pyigtl` | `==0.3.4` | OpenIGTLink framing, CRC and the server socket; there is no stdlib equivalent and re-implementing the wire format would defeat the swap-to-real-app seam. Header version 2 is required for metadata. |
| `crcmod` | `==1.7` | Required transitive dependency of `pyigtl`, imported unconditionally at `pyigtl/messages.py` line 8 and used at module scope to build the CRC64 function, so it loads before any message can be constructed. Listed explicitly because the dependency policy approves what is installed, not only what is imported directly. |
| `opencv-python-headless` | `==5.0.0.93` | Frame resize and the optional webcam source. Same pin already approved for SLIAFlow, imported lazily so the synthetic path does not need it. |

`crcmod` is **not** an optional performance fallback. `pyigtl` imports it
unconditionally, so it is installed either way; the earlier framing of it as a
tuning knob was wrong and must not be reintroduced.

Both pins were resolved by installing into the root `.venv` and observing the
result rather than by reading an index listing. Two things came out of that, and
both belong here because both are ways the install can bite later.

`crcmod` 1.7 publishes **no** Windows wheel. pip fetched the sdist and compiled
it, so every machine that installs these requirements needs a working C
toolchain. That is free on this machine and on any developer box carrying the
Visual Studio C++ workload the SLIAFlow build already requires, but it is a real
failure mode on a bare CI runner. It is an environment prerequisite, not a
surprise to be met during a demo.

`pyigtl`'s in-package `__version__` reports `0.3.2` while the installed
distribution is `0.3.4` - `pyigtl/_version.py` was not bumped for the release.
Pin and verify against `importlib.metadata.version("pyigtl")`. A check written
against `pyigtl.__version__` would record a version that is simply false, and
would keep passing while doing so.

Project-owner sign-off on the completed table is still required before
activation.

## Implementation plan

1. Create the package skeleton, `requirements.txt`, and
   `tools/simulators/ruff.toml` with `target-version = "py310"` and the same
   `select` list as the root configuration, plus a `sys.version_info` runtime
   guard.
2. Widen `pyproject.toml`'s `include` to cover `tools/simulators/**/*.py`, and
   extend `run-python-quality.ps1` to loop over both targets, accumulating exit
   codes and failing if `ruff check --show-files` reports zero files.
3. Implement `spectra.py` (band grid, Gaussian mixing, NIR envelope, calibration
   inversion) and `envi.py` (header emission, BSQ write, all four interlocks).
4. Implement `frames.py` with the `FrameSource` protocol and both the synthetic
   and lazily imported webcam sources, and `contract.py` with `DatasetRef`, the
   dataset loader, the all-optional `Uc1Maps` dataclass, and the
   `classify(dataset)` `Classifier` protocol.
5. Implement `igtl_transport.py` as a server-socket LiveView sender mirroring the
   C++ sender field for field, and `acquisition_sim.py` as the CLI that writes a
   dataset and streams frames.
6. Write the stdlib `unittest` suite and its runner, then the README, the
   PowerShell launcher, and the governance and documentation updates.

## Acceptance criteria

- Running the acquisition simulator writes a `sim-YYYYMMDD-HHMMSS` dataset whose
  three `.dat` files are each exactly `samples * lines * 93 * 2` bytes and whose
  `raw.hdr` re-parses under the same three-key `sscanf` semantics UC1 uses.
- A NumPy re-implementation of `100 * (raw - dark) / (white - dark)` recovers
  `100 * reflectance` from the written cube to within one part in 2000.
- The header contains no `;`, keeps every line under 128 bytes, carries
  `data type = 12`, `interleave = bsq`, `data file = raw.dat`, and the
  `STRATUM SIMULATED CUBE` marker.
- The writer refuses an over-length path and refuses to overwrite an existing
  dataset folder whose header lacks the simulated marker.
- The written cube is numerically non-degenerate in the spectral dimension: the
  numerical rank of the calibrated cube's band covariance, measured with
  `numpy.linalg.matrix_rank`, is at least the number of principal components UC1
  requests in `parameters.txt`, and the covariance condition number is finite and
  recorded. A nonzero band count is **not** evidence of this - a scene mixed from
  a handful of basis curves has every band nonzero and a covariance whose rank
  equals the basis size - so this is measured, never inferred.
- A pyigtl client connecting to `127.0.0.1:18944` receives frames with device
  name `LiveView`, uint8 scalar type, three components, and the configured
  dimensions, and the achieved frame rate is recorded.
- Metadata set through `igtl_transport.py` survives a pyigtl pack and unpack
  round-trip, proving header version 2 is actually in force rather than
  requested.
- A `DatasetRef` returned by the writer equals one loaded from the folder it
  wrote, and its `loadCalibratedCube()` returns the contract's shape and dtype.
- `ruff check` reports a non-zero number of checked files for both targets and
  exits 0.

## Test plan

Automated tests run through `tools/simulators/tests/run_tests.py` using the
standard-library `unittest` runner, **not** the Slicer test runner. This task's
evidence must not claim Slicer test coverage.

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| Dataset byte sizes and header re-parse | `test_envi.test_datasetRoundTripsThroughUc1HeaderSemantics` | automated |
| Calibration inversion recovers reflectance | `test_spectra.test_calibrationRoundTripRecoversReflectance` | automated |
| Header constraints (no `;`, line length, required keys, marker) | `test_envi.test_headerSatisfiesBothConsumers` | automated |
| Path-cap and unmarked-overwrite refusals | `test_envi.test_writerInterlocksRefuseUnsafeTargets` | automated |
| Band covariance rank clears the PCA component count | `test_spectra.test_bandCovarianceRankClearsPcaComponentCount` | automated |
| LiveView stream shape, device name and rate | `test_config` plus manual step 3 | automated and manual |
| Metadata survives a pyigtl pack and unpack round-trip | `test_igtl_transport.test_metadataSurvivesPackUnpackRoundTrip` | automated |
| `DatasetRef` round-trips and loads a contract-shaped cube | `test_contract.test_datasetRefRoundTripsFromWrittenFolder` | automated |
| Ruff checks a non-zero file count for both targets | Manual step 1 | manual |

Tests added beyond the planned set, and why:

| Test | Why it exists |
| --- | --- |
| `test_spectra.test_channelOnlyBasisIsRankDeficient` | Pins the measured rank of the channel-only basis at 3, which is what makes the rank floor non-vacuous |
| `test_spectra.test_bandGridMatchesTheHeadwallRange` | Pins the 400.482-1000.73 nm grid and the 6.5244 nm step against the real sensor header |
| `test_envi.test_weightVectorMatchesTheBandCount` | The `w_vector.bin` size interlock the requirements list |
| `test_envi.test_datasetFolderNameUsesTheAgreedStamp` | The `sim-YYYYMMDD-HHMMSS` naming rule |
| `test_igtl_transport.test_defaultHeaderVersionSilentlyDropsMetadata` | Keeps the silent-drop failure mode itself under test, not just its absence |
| `test_igtl_transport.test_imageMessageMirrorsTheCppSender` | Dimensions, components, identity matrix and LPS, against `OpenIGTLinkServer.cpp` |
| `test_igtl_transport.test_frameIsPreparedAsKjiComponentsAndRotates` | The BGR-to-RGB swap and the 180-degree rotation `std::reverse` performs in one pass |
| `test_igtl_transport.test_installedVersionIsReadFromDistributionMetadata` | `pyigtl.__version__` reports 0.3.2 for the 0.3.4 release, so the check reads distribution metadata |
| `test_contract.*` (protocol and optional-map tests) | That an array-only producer does *not* satisfy `Classifier`, and that one map of five is representable |
| `test_config.*` (preset, override and rejection tests) | Preset sizes, BMP row alignment, `local.json` overriding defaults, and named rejection of unknown values |

Tests to add or change, and how each one will be shown to fail first:

- Every test above is new and fails with `ModuleNotFoundError` for `stratum_sim`
  before the package exists; record that output.
- After the package skeleton lands, each test is shown red a second time against
  the stub implementation it targets, and that output is recorded too.
- The writer-interlock test is written to fail against a deliberately weakened
  implementation with the interlocks removed, to prove it is not vacuous.
- `test_bandCovarianceRankClearsPcaComponentCount` is shown red against the
  three-Gaussian-plus-one-envelope basis, which is exactly the low-rank scene a
  nonzero-band check would wave through. That red run is the evidence that the
  replaced criterion was not measuring what it claimed.
- `test_metadataSurvivesPackUnpackRoundTrip` is shown red against a sender left
  at pyigtl's default header version, which is the silent-drop failure mode this
  requirement exists to prevent.

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Run `scripts/development/run-python-quality.ps1` | Both targets are linted, each reports a non-zero checked-file count, and the script exits 0 | PASS - 6 files in `extensions/SLIAFlow/SLIAFlow`, 18 in `tools/simulators`, exit 0 |
| 2 | Run `scripts/development/run-acquisition-simulator.ps1` with the `demo` preset | A `sim-YYYYMMDD-HHMMSS` folder appears under `workspace/simulators/datasets/` with `raw.hdr`, `raw.dat`, `whiteReference.dat` and `darkReference.dat`, and the console states the data is simulated and non-clinical | PASS - `sim-20260902-133645`, three `.dat` files of 3,571,200 bytes each, non-clinical notice printed first |
| 3 | With the simulator running, connect the small pyigtl client from `tools/simulators/tests/` | Frames arrive with device name `LiveView`, three uint8 components and the configured dimensions; the achieved frame rate is printed and recorded | PASS - `LiveView`, `(1, 120, 160, 3)` uint8, LPS, header version 2, all three provenance keys; 12.74 fps enqueue-side, 12.50 fps receiver-side |
| 4 | Point the simulator at an existing non-simulated dataset folder | It refuses to overwrite and explains that the folder lacks the `STRATUM SIMULATED CUBE` marker | PASS - refused with the marker named, exit 1, folder left holding only its original `raw.hdr` |
| 5 | Stop the simulator with Ctrl-C | It shuts the server socket down cleanly and leaves the written dataset intact | PASS via scripted `CTRL_BREAK_EVENT` - clean shutdown message, exit 0, dataset intact. A literal console keypress is still worth one owner confirmation |

## Risks

CRC computation over a 640x480x3 frame (922 KB) may hold the achieved rate to a
few frames per second. This is why the default preset is the small one and why
the achieved rate is an acceptance criterion rather than an assumption. The
available fallbacks are lower resolution and a lower frame rate. `crcmod` is not
one of them: it is already installed as a `pyigtl` requirement, so it cannot be
held in reserve.

The webcam source and `SLIAFlowLogic.startCamera` both want camera index 0, and
Windows will fail the second open. The default is therefore `synthetic`, and the
conflict is stated in the runbook.

`pyproject.toml`'s `include` narrows Ruff's discovery, so without widening it
`ruff check tools/simulators` would match zero files, exit 0, and report green
having checked nothing. The emptiness guard exists because this is the project's
only static gate.

`AGENTS.md` currently lists neither `tools/` nor `scripts/` as normally editable,
yet BSSL-009 already created `scripts/development/build-sliaflow.ps1` under its
`Files allowed` list. This card resolves that ambiguity by adding both
directories, which needs project-owner sign-off because `AGENTS.md` is the root
source of truth.

## Documentation impact

- `AGENTS.md`: add `tools/` and `scripts/` to the normally editable list.
- `docs/development/project_structure.md`: document `tools/`.
- `docs/development/coding_standards.md` line 32: the Ruff scope statement is
  stale once a second target exists.
- `config/local.example.json`: document the `simulators` block.
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`: the four wire metadata
  keys, the header-version-2 requirement, and the note that the received MRML
  attribute names are established in SLIA-008 rather than assumed here.
- `tools/simulators/README.md`: new, non-clinical statement first, then how to
  run and stop each simulator and the webcam conflict.

## Completion evidence

Branch: `feature/SLIA-011-acquisition-simulator`.

### Automated tests

Runner: `tools/simulators/tests/run_tests.py` (standard-library `unittest`,
**not** the Slicer test runner - nothing under `stratum_sim` imports `slicer`).

```text
.\.venv\Scripts\python.exe tools\simulators\tests\run_tests.py
Ran 33 tests in 0.132s
OK
exit code 0
```

26 of those were the original set; the remaining 7 were added by the review
round recorded under `## Review findings`.

### Static analysis

```text
.\scripts\development\run-python-quality.ps1
ruff 0.15.21
-- Target: extensions/SLIAFlow/SLIAFlow   Files checked: 6    All checks passed!
-- Target: tools/simulators               Files checked: 19   All checks passed!
Python quality checks passed.
exit code 0
```

Both targets report a non-zero checked-file count, which is the emptiness guard
the task asked for.

### Red-first evidence

Each test was recorded failing before the code that satisfies it existed, and
the three tests the card singles out were additionally recorded failing against
a deliberately weakened implementation.

1. Before the package existed, all five test modules failed to import:
   `ImportError: cannot import name 'spectra' from 'stratum_sim' (unknown
   location)`, `Ran 5 tests`, `FAILED (errors=5)`.
2. Rank test against the three-Gaussian-plus-one-envelope basis
   (`DEFAULT_TEXTURE_FEATURE_COUNT = 0`):
   `AssertionError: 3 not greater than or equal to 8`.
3. Metadata test against pyigtl's default header version (the
   `message.header_version = 2` assignment removed):
   `AssertionError: 1 != 2`.
4. Interlock test against a writer with `_assertTargetIsSafe` emptied:
   `AssertionError: DatasetWriteError not raised`.

The tests added by the review round were recorded the same way, each against the
behaviour it replaces:

5. Occupied-folder interlock, with the new branch of `_assertTargetIsSafe`
   replaced by `return`: `AssertionError: DatasetWriteError not raised`.
6. Configuration floors, with the two checks replaced by the previous
   `bands < 1` test: `AssertionError: ConfigurationError not raised`.
7. Device-name agreement, with `liveViewMetadata` hard-coding the constant:
   `AssertionError: 'LiveView' != 'LiveView_Bench2'`.
8. Rank enforcement and the rate divisor, with the guard disabled and the
   divisor returned to the frame count: `AssertionError:
   SpectralRankTooLowError not raised` and `AssertionError: 11.1111037037241 !=
   10.0 within 1 places`.

### Measured numbers

- Achieved frame rate, `demo` preset, 15 fps target: **12.74 fps** enqueue-side
  over the first 30 frames, **12.50 fps** receiver-side over 60 frames. The
  enqueue figure now sits just above the receiver figure, which is the
  relationship it should have; the 13.35 fps recorded before the review round
  was inflated by dividing 30 frames by the 29 intervals they span.
- Band covariance rank of the written cube: **9**, condition number over the
  retained subspace **8.648e+02** (finite).
- Dataset file sizes, `demo` preset: 3,571,200 bytes each for `raw.dat`,
  `whiteReference.dat` and `darkReference.dat`, which is
  `160 * 120 * 93 * 2` exactly.
- `svm_model/w_vector.bin`: **2232 bytes** = `93 * 6 * 4`, byte-for-byte the
  size of the shipped model, which is the second confirmation of 93 bands.
- Installed pins verified through `importlib.metadata`: `pyigtl 0.3.4`
  (its in-package `__version__` still reports 0.3.2), `numpy 2.2.6`,
  `crcmod 1.7`, `opencv-python-headless 5.0.0.93`.

### Findings that changed the specification

**The rank criterion as written was vacuous, and was strengthened.** The card
asked for the numerical rank of the *calibrated* cube's band covariance,
measured with `numpy.linalg.matrix_rank`. Measured: rounding `raw` to uint16
lifts every singular value of that covariance to about `8e-11` of the largest,
so `matrix_rank` at its default tolerance returns **93 for every scene**,
including one mixed from three curves. The exact, unquantized cube has rank 3
and 9 respectively. `spectralRankReport` therefore measures against a
documented relative tolerance of `1e-8`, which sits roughly three orders below
the smallest genuine direction (`5.45e-6`) and three orders above the
quantization floor. Without this the criterion would have passed on any input
at all.

**The vendored `parameters.txt` requests 1 PCA band, not more than 4.** The card
assumed the PCA component count would be a meaningful floor. In
`gpu_single_bsq/source/parameters.txt` the second value - `numberOfPcaBands`,
read by `main.cu` - is `1`, and `checkHySime` is `0`, so it is used directly.
The literal criterion (`rank >= pcaBandCount`) is therefore trivially satisfied
and could never have been shown red. The test still asserts it, against the
value read from the file rather than an assumed one, and skips that half when
the ignored `workspace/` tree is absent. The floor that actually does the work
is the named `MINIMUM_SPECTRAL_RANK = 8`.

**The channel-only basis is rank 3, not the rank 4 the card predicted.** The
near-infrared envelope is driven by luminance, and luminance is a fixed linear
combination of the B, G and R weight maps, so the envelope contributes a curve
but no new direction. This is recorded in `spectra.py` and pinned by
`test_channelOnlyBasisIsRankDeficient`.

**pyigtl's server installs its own SIGINT handler after ours.**
`OpenIGTLinkServer.__init__` registers SIGINT and SIGTERM handlers that close
the socket and re-send the signal to the default handler. An interrupt flag
installed before the server is therefore silently replaced, and Ctrl-C would
have bypassed the clean-shutdown path entirely. `_InterruptFlag` is now
installed after the server starts, and handles SIGBREAK alongside SIGINT
because on Windows Ctrl-C and Ctrl-Break arrive as different signals.

**Two small additions the manual steps required.** `--dataset-folder`
(`-DatasetFolder` on the launcher) names an exact folder, without which manual
step 4 could not be performed at all: folders are otherwise named
`sim-YYYYMMDD-HHMMSS` and an operator cannot land on an existing one. And each
dataset carries an `svm_model/` sized for its band count, because the
`w_vector.bin` interlock the card specifies is only meaningful against a file
this process generates, and because the shipped model is sized for 93 bands and
would not fit a different preset.

### Manual verification

Performed on this machine; results are in the table above. Two notes on how
steps were carried out:

- Step 3 used `tools/simulators/tests/liveview_client.py`, which is deliberately
  not named `test_*` so `run_tests.py` never collects it. It reported device
  name `LiveView`, shape `(1, 120, 160, 3)`, `uint8`, LPS, header version 2, and
  all three LiveView provenance keys.
- Step 5 was driven by a scripted `CTRL_BREAK_EVENT` to a new process group
  rather than a literal keypress in an interactive console. Both signals reach
  the same handler and the same shutdown path; the difference is delivery only.
  A literal Ctrl-C in an interactive console has not been keyed by hand and is
  worth one confirming keypress by the project owner.

`workspace/simulators/foreign-dataset/` was left in place. It is the unmarked
folder step 4 uses, it is inside the already-ignored `workspace/` tree, and
keeping it makes that step repeatable.

### Not done

- `Classifier` has no implementation. It is the seam SLIA-012 and SLIA-013 plug
  into, as the card specifies.
- No Slicer-side change, and no Slicer test coverage is claimed.
- Human approval and completion remain outstanding. One independent review round
  has been run and its findings are recorded and addressed below. No Git mutation
  beyond creating and switching to the task branch has been made: the work is
  uncommitted.
- End-to-end verification against the genuine UC1 binary and against the real
  acquisition application's simulated-capture mode has not been performed, and
  no claim of it is made here. See review finding 3.

## Review findings

An independent review raised five findings. Four were defects and are fixed; the
fifth is a real gap that belongs to a later card and is now recorded rather than
left implicit. Every fix carries a test, and each of those tests was recorded
failing against the behaviour it replaces (red-first entries 5 to 8 above).

**1 (high) - an existing headerless folder could be overwritten.** The interlock
only rejected an existing `raw.hdr` without the marker. A folder with no header
at all had no marker to check and was accepted, and `raw.dat`,
`whiteReference.dat` and `darkReference.dat` were then replaced. `--dataset-folder`
takes an arbitrary path, so a typo reached it. Fixed in
`envi._assertTargetIsSafe`: an empty folder is still a fresh target, but a
folder with no header that holds anything at all is refused by name. Verified
end to end - a folder holding a sentinel `raw.dat` produced
`ERROR: Refusing to overwrite ... it is not empty (holds raw.dat)`, exit code 1,
sentinel byte-for-byte intact.

**2 (high) - settings could produce a dataset that violates the contract.**
`bands = 1` passed validation and crashed later in `bandWavelengthsNm`;
`textureFeatureCount = 0` wrote a rank-3 cube, printed the rank, and exited 0.
Both are now rejected where they are set, against floors derived from the
contract rather than picked: `MINIMUM_BAND_COUNT` because a rank cannot exceed
the band count, and `MINIMUM_TEXTURE_FEATURE_COUNT` because the channel basis
reaches `CHANNEL_BASIS_RANK` alone. The prediction is not trusted on its own -
`assertSpectralRankIsSufficient` now checks the rank *measured* on the written
dataset and exits non-zero below the floor, so a degenerate dataset can no
longer look like a successful run.

**3 (medium) - real-consumer compatibility is inferred, not measured.**
Correct, and it stays that way within this card's scope: the tests re-implement
UC1's and `HSCubeLoader`'s parsing rules from the vendored source, and neither
real application has been run against a generated dataset. The review also
found a concrete instance - `main.cu` opens the SVM model as the literal
relative paths `../../svm_model/*.bin`, resolved against the binary's working
directory, while this writer puts the model inside the dataset folder. Both
facts are now stated in `envi.py` and in the README rather than left to be
discovered, and both are SLIA-013's to settle, since that is the card where the
binary is actually invoked. The `w_vector.bin` size interlock still binds
wherever the file is eventually read from.

**4 (medium) - a renamed stream produced self-contradictory metadata.** The
message header used the configured device name while `SLIAFlow.DeviceName` was
hard-coded to `LiveView`. Since the metadata is the half a consumer is asked to
trust, `liveViewMetadata` now takes the device name as a parameter and the
caller passes the configured one.

**5 (low) - the sender-side rate was optimistic.** Two causes, both real:
`send_message(wait=False)` returns on enqueue rather than on delivery, and the
divisor was the frame count rather than the intervals those frames span. The
divisor is fixed in `enqueueRate`; the enqueue-versus-delivery distinction
cannot be fixed from the sender, so it is named instead - in the function, in
`sendImage`, in the printed line, and in the README - and the receiver-side
figure is stated as the one that settles the criterion.

Both gates were re-run after the fixes: 33 tests OK, exit 0; Ruff 6 and 19 files
across the two targets, all checks passed, exit 0.

## Human approval

Required before review and completion.
