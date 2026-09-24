---
id: SLIA-032
title: Show the calibrated LCTF cube - bands, colour preview and pixel spectrum
status: completed
branch: feature/SLIA-032-show-the-lctf-cube
priority: high
depends_on: SLIA-031
required_skills: [slicer]
optional_tools: []
related_adrs: [ADR-0004]
---

# SLIA-032 - Show the calibrated LCTF cube - bands, colour preview and pixel spectrum

## Goal

Load IUMA's calibrated float32 cube `002-04` into SLIAFlow and let the operator
look at it:

- browse it band by band, with the wavelength of the current band shown;
- see a colour preview built from three bands;
- click a pixel and see its spectrum (reflectance against wavelength).

This is the first task that works with the future data format, and it does not
need UC1.

## Context

`LCTF_Calibrated_Cube_Single` is ENVI data type 4 (float32), BSQ, byte order 0,
header offset 0, 1080 x 1080 x 109, wavelengths 460-1000 nm in 5 nm steps
(`wavelength units = Nanometers`), values in [0, 1.5]. The data file is
`LCTF_Calibrated_Cube_Single.dat`, 508,550,400 bytes, which is exactly
1080 x 1080 x 109 x 4. Measured at specification on bands 470, 550 and 650 nm:
medians 0.05, 0.04 and 0.40, 99th percentile of the three together 0.99, no NaN.

Since `SLIA-031`, Capture reads one configured folder, `SLIAFlowLogic.cubeFolder`
(default `input/reference_hsi_brain_db/020-01`). It runs UC1 on that folder and
shows its `raw.dat` in the HS Cube panel through `SLIAFlowLogic.acceptCube`.
The panel shows a module-owned scalar volume with the band on the third axis, so
a slice view scrolls it band by band. It opens at the middle band, with one
window and level for the whole cube. That code reads uint16 only, and
`parseEnviHeader` skips the wavelength block, so there is no notion of
wavelength.

The IUMA app also offers a cube viewer ("Load HS Cube",
`docs/hardware/acquisition_app_and_hardware.md` section 3.5). It is a reference
for what the IUMA team expects to see, not something to copy.

Slicer APIs checked in the Slicer skill at specification:

- `slicer.qMRMLPlotWidget` with `setMRMLScene` and `setMRMLPlotViewNode`, and
  `vtkMRMLPlotViewNode.SetPlotChartNodeID`
  (`Modules/Loadable/Plots/Testing/Python/PlotsSelfTest.py`);
- `vtkMRMLPlotChartNode.SetTitle`, `SetXAxisTitle` and `SetYAxisTitle`, plus
  `vtkMRMLPlotSeriesNode` with `SetAndObserveTableNodeID`, `SetXColumnName` and
  `SetYColumnName` (`script_repository/plots.md`);
- slice view XY to IJK through
  `sliceLogic.GetBackgroundLayer().GetXYToIJKTransform().TransformDoublePoint`,
  as `DataProbe.py` does. A device position becomes XY through
  `qMRMLSliceView.convertDeviceToXYZ`, and RAS becomes XY through
  `convertRASToXYZ`;
- a click on a slice view is observed with
  `sliceView.interactorStyle().GetInteractor().AddObserver(vtk.vtkCommand.LeftButtonPressEvent, ...)`
  (`slicer/util.py`, `clickAndDrag`).

## Requirements

- Read a float32 BSQ ENVI cube with its wavelengths, and check the header
  against the file size before reshaping, as the uint16 reader does.
- Show it in the HS Cube panel as the configured display cube, on every Capture,
  whether or not UC1 can run. UC1 keeps running on the reference case until
  `SLIA-033`. The panel states which cube it shows, and the Tumour Delineation
  panel states which cube its result came from, so the two are never confused.
- Band browsing shows the band number and its wavelength in nm.
- A colour preview from three bands chosen by wavelength, with defaults near
  red, green and blue (650, 550 and 470 nm), stated in the panel. The preview is
  labelled as a band composite, not a photograph.
- Clicking a pixel in the cube view shows that pixel's spectrum as a Slicer plot,
  with the axis units stated (reflectance, nm).
- No resampling, smoothing or rescaling of the stored values. Display window and
  level are display settings only.
- Provenance on the cube node as `ADR-0004` decision 7 states.

### Decisions taken at specification

- **Where the cube comes from.** A new logic setting, `calibratedCubeHeader`,
  defaults to `input/002-04/LCTF_Calibrated_Cube_Single.hdr` under the
  repository. Like `cubeFolder`, it is a plain logic attribute rather than a
  parameter-node field, it is reset by `setRunEnvironment`, and it is read at
  every Capture. The data file is the header's stem with `.dat`, or `.raw` if
  there is no `.dat`. `cubeFolder` keeps meaning the folder UC1 runs on.
- **What a valid display cube is.** `data type = 4`, `interleave = bsq`,
  `byte order = 0`, `header offset = 0` (or absent), positive integer `samples`,
  `lines` and `bands`, and a `wavelength` block of exactly `bands` finite
  numbers that strictly increase. `wavelength units` may be absent or say
  nanometers (`Nanometers` or `nm`, case-insensitive); any other unit is
  refused. The data file size must equal samples x lines x bands x 4, checked
  both when the cube is described and again right before it is read. Every
  refusal is translated and names the file and the reason. The 109->93 band
  mapping of `ADR-0004` decision 4 is UC1's check and belongs to `SLIA-033`.
- **Reading.** The file is read straight into the volume's own buffer, with no
  intermediate copy and no conversion: float32 in, float32 displayed. The
  volume's shape is (bands, lines, samples), and it keeps the same upright
  directions as today.
- **Band numbering** is 1-based for the operator ("Band 39 of 109 - 650 nm").
- **Colour preview.** A separate RGB volume (uint8, one slice) with the same
  in-plane geometry. Each of the three channels is the band whose wavelength is
  nearest to its target (650, 550 and 470 nm). The channels share one fixed
  display scale: reflectance 0 maps to 0, reflectance 1.0 maps to 255, and
  values of 1.0 and above show at 255. Values are rounded half up
  (`floor(v * 255 + 0.5)`). That is a display mapping of a derived
  picture, fixed and stated. It is not a stretch fitted to the data, and the
  cube's stored values are untouched. The preview wavelengths are fixed in this
  task.
- **Operator controls.** An **HS Cube shows** selector in the Operator group,
  with two entries: **Bands** (the default) and **Colour preview**.
- **Captions on the views.** HS Cube carries a caption at the top: the first
  line names the cube (`Recorded cube 002-04, calibrated reflectance`). The
  second line gives the current band and wavelength, or the preview's three
  wavelengths with `band composite, not a photograph`. Tumour Delineation
  carries a caption at the bottom, `Result for recorded case <case>`, whenever
  a result is shown. Both follow the owner rule of 2026-09-18
  (`test_panelTextNamesOnlyWhatThePanelWaitsFor`): text on a view names the
  input, never the pipeline, partner or task, so `UC1` and `IUMA` stay in the
  module panel's status lines.
- **Pixel spectrum.** Clicking the HS Cube view, in either mode, picks the pixel
  under the cursor and shows its stored values in a plot inside the module
  panel. The plot sits in a collapsible **Pixel spectrum** section, and the
  six-view layout is unchanged. X axis `Wavelength (nm)`, Y axis
  `Reflectance (stored value)`. A line under the plot names the cube and the
  pixel and says `stored values, not an analysis`. A click outside the cube
  leaves the previous spectrum and says the click was outside the cube.
- **Provenance.** The cube volume, the preview volume and the spectrum table
  carry `SLIAFlow.DataOrigin = simulated`, `SLIAFlow.RecordedCase = 002-04`
  (the cube folder's name) and the Capture ID. The
  `SLIAFlow.SimulationDetail` reads `recorded IUMA LCTF capture 002-04,
  calibrated by IUMA (simulated acquisition)`. The cube volume also carries its
  wavelengths as `SLIAFlow.WavelengthsNm`, and the node is named after its data
  file.
- **Order within Capture.** UC1 is started first and the cube is read after, so
  the run proceeds while the cube is read. If the display cube cannot be read,
  the capture and UC1 go on. The HS Cube panel then says it could not show the
  cube and why.

## Out of scope

- Running UC1 on this cube (`SLIA-033`), including the band-mapping check.
- Reading the raw uint16 cube and calibrating it ourselves. IUMA calibrates.
- Receiving the cube over the network (`SLIA-030`).
- Operator-chosen preview wavelengths, contrast controls beyond Slicer's own
  window and level, spectra of more than one pixel, and saving a spectrum.
- Showing the cube without a Capture (for example on module entry).
- Caching the cube between Captures. Load time is measured here, and
  improvements belong to `SLIA-034`.

## Files allowed

- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowCalibratedCube.py` (new)
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowCube.py` (a shared ENVI block parser, if needed)
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowParameterNode.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `extensions/SLIAFlow/SLIAFlow/Resources/UI/SLIAFlow.ui`
- `extensions/SLIAFlow/SLIAFlow/CMakeLists.txt`
- `extensions/SLIAFlow/README.md`
- `docs/development/uc1_demo_runbook.md`
- `tasks/{backlog,active,review,completed}/SLIA-032-show-the-lctf-cube.md`
- `input/README.txt` (gitignored; one sentence about 002-04 being read; never staged)

## Relevant skills and references

- Slicer skill: checked at specification (see Context).
- `docs/architecture/decisions/ADR-0004-iuma-lctf-cube-and-acquisition-app.md`,
  decisions 1, 5, 6 and 7
- `docs/hardware/acquisition_app_and_hardware.md`, sections 3.4 and 3.5
- `.ai/policies/medical-data-policy.md`, "IUMA LCTF capture 002-04"
- `docs/development/testing_strategy.md`

## Implementation plan

1. `SLIAFlowCalibratedCube.py`: a `CalibratedCube` dataclass (name, header
   path, data path, samples, lines, bands, wavelengths),
   `CalibratedCubeError(ValueError)`, `loadCalibratedCube(headerPath)`,
   `readCalibratedCube(cube, out=None)` (it checks the size again and reads into
   `out` when given), and `nearestBand(cube, nanometres)`. The wavelength block
   is parsed here, and `parseEnviHeader` from `SLIAFlowCube` is reused for the
   scalar keys. Register the file in `CMakeLists.txt`.
2. `SLIAFlowParameterNode.py`: `calibratedCubeDetail(name)` and the
   `SLIAFlow.WavelengthsNm` attribute name.
3. `SLIAFlowLogic.py`: `CALIBRATED_CUBE_RELATIVE_PATH`, the
   `calibratedCubeHeader` property and setter (reset by `setRunEnvironment`),
   and `loadConfiguredCalibratedCube()`. `acceptCube(cube, captureId)` now
   builds the float32 volume by reading into its buffer, and carries the new
   provenance. Add `acceptColourPreview(cubeNode)` with owner
   `CalibratedCubePreview`, `cubeBandAt(node, ras)` for the band caption, and
   `pixelSpectrum(node, i, j)` returning (wavelengths, values). Add
   `showPixelSpectrum(node, i, j)`, which fills a module-owned table, series and
   chart and returns the chart. Removing the cube also removes the preview and
   the spectrum nodes.
4. `SLIAFlowWidget.py`: in `_startCapture`, start UC1 first, then show the
   display cube in all cases. Add the **HS Cube shows** selector with the Bands
   and Colour preview modes. Add the HS Cube caption, updated from a
   slice-node observer on the HS Cube view, and the Tumour Delineation caption.
   Add a left-press observer on the HS Cube interactor that converts the
   position to XY and then IJK, and `_pickCubePixelAtXYZ` for it. The plot
   widget and the spectrum label live in the module panel. `panelCaption(viewName)`
   is added for tests. Observers and actors are released on exit, cleanup and
   scene close.
5. `SLIAFlow.ui`: the selector row, and the **Pixel spectrum** collapsible
   section with a plot container and a label.
6. Tests (see Test plan), README, runbook and `input/README.txt`.

## Acceptance criteria

1. The display cube loads with the stored float32 values unchanged: the volume
   is float32, shaped (bands, lines, samples), and equal element for element to
   the file.
2. A cube whose header and file disagree, or whose header is not a float32 BSQ
   little-endian cube with nanometre wavelengths, one per band, is refused. The
   reason names the file and the defect, is translated, and is shown on the
   HS Cube panel. The capture and UC1 carry on.
3. Each band shows its number and wavelength on the HS Cube panel as the
   operator scrolls.
4. The colour preview is built from the bands nearest 650, 550 and 470 nm,
   with the fixed 0-1.0 display scale. Its caption names the three actual
   wavelengths and says it is a band composite, not a photograph.
5. A clicked pixel's spectrum matches the stored values at that pixel, against
   the header's wavelengths. The plot's axes state nm and reflectance, and the
   plot says it shows stored values.
6. HS Cube names the cube it shows (`002-04`). Tumour Delineation names the
   recorded case its result came from, so the two are never confused.
7. The cube, preview and spectrum nodes carry `ADR-0004` decision 7
   provenance and the Capture ID.
8. The cube is shown on every Capture from the configured header, even when
   UC1 is refused, and input files are never written.
9. The real `002-04` cube in the built app: it loads, scrolls with wavelengths,
   previews, plots a clicked pixel, and the load time and Slicer's memory after
   load are recorded.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| 1. Stored float32 values unchanged | `SLIAFlowTest.test_calibratedCubeIsReadWithItsValuesUnchanged` (reader) and `test_capturedCubeIsShownBandByBand` (volume) | automated |
| 2. Inconsistent cube refused with reason | `SLIAFlowTest.test_calibratedCubeRejectsIncompatibleContents`, `test_cubeRefusalReasonsAreTranslated` (extended to the new module), `test_unreadableCubeIsExplainedOnThePanel` | automated |
| 3. Band number and wavelength while scrolling | `SLIAFlowTest.test_cubeCaptionNamesTheBandAndItsWavelength` (headful) | automated |
| 3. Legible while scrolling the real cube | Manual step 2 | manual |
| 4. Colour preview bands, scale and caption | `SLIAFlowTest.test_colourPreviewUsesTheNamedBandsOnAFixedScale`, `test_colourPreviewCaptionNamesItsWavelengths` (headful) | automated |
| 4. Preview looks like a band composite of the real cube | Manual step 3 | manual |
| 5. Pixel spectrum equals stored values | `SLIAFlowTest.test_pixelSpectrumIsTheStoredValues` and `test_clickedCubePixelIsThePixelUnderTheCursor` (headful) | automated |
| 5. A real click plots the right pixel | Manual step 4 | manual |
| 6. Both panels name their cube | `SLIAFlowTest.test_panelsNameTheCubeTheyShow` (headful) | automated |
| 7. Provenance | `SLIAFlowTest.test_capturedCubeIsShownBandByBand` and `test_colourPreviewUsesTheNamedBandsOnAFixedScale` (attribute assertions) | automated |
| 8. Shown on every Capture, even when UC1 is refused; input not written | `SLIAFlowTest.test_cubeIsShownEvenWhenUc1IsRefused` and `test_cubeReadingDoesNotWriteToInput` (extended) | automated |
| 9. Real cube in the built app, load time and memory | Manual steps 1-5 | manual |

Tests to add or change, and how each one will be shown to fail first:

- New fixture: `_writeFixtureCalibratedCube(root, ...)` writes a 4 x 3 x 109
  float32 cube with the 002-04 header layout (wavelengths 460-1000 nm in 5 nm
  steps) and distinct values per voxel. `_makeFixtureRepository` places it at
  `input/002-04/LCTF_Calibrated_Cube_Single.{hdr,dat}`.
- `test_calibratedCubeIsReadWithItsValuesUnchanged` (new): the reader returns
  float32 values equal to the fixture array, and the wavelengths are the header
  list. Fails first: `SLIAFlowCalibratedCube` does not exist.
- `test_calibratedCubeRejectsIncompatibleContents` (new): data type 12,
  interleave bip, byte order 1, header offset 10, a file 4 bytes short, no
  wavelength block, 108 wavelengths for 109 bands, an empty entry or a
  trailing comma beside 109 wavelengths, decreasing wavelengths,
  units in micrometres, and a missing data file. Each is refused with a
  non-empty reason naming the file. Fails first: module missing.
- `test_colourPreviewUsesTheNamedBandsOnAFixedScale` (new): the preview is
  uint8 (1, lines, samples, 3). Channel R equals
  `clip(band[38] / 1.0, 0, 1) * 255`, rounded, where 38 = (650 - 460) / 5 comes
  from the header grid. G uses 18 (550 nm) and B uses 2 (470 nm). The fixture
  holds values above 1.0 to exercise the clip. Fails first: no
  `acceptColourPreview`.
- `test_pixelSpectrumIsTheStoredValues` (new): `pixelSpectrum(node, i, j)` and
  the plot table equal `fixture[:, j, i]` and the header wavelengths, and the
  chart's axis titles contain `nm` and `Reflectance`. Fails first: no
  `pixelSpectrum`.
- `test_capturedCubeIsShownBandByBand` (changed): the cube node is float32,
  named `LCTF_Calibrated_Cube_Single.dat`, equal to the fixture, and carries
  `RecordedCase = 002-04`, the new detail, the wavelengths and the Capture ID.
  UC1 still runs on the reference case folder. Fails first: the node today is
  uint16 `raw.dat`.
- `test_cubeIsShownEvenWhenUc1IsRefused` (new): with the UC1 case folder
  missing, Capture fails with the folder's reason but the cube node exists.
  Fails first: today a refused case shows no cube.
- `test_unreadableCubeIsExplainedOnThePanel` (new, headful): a truncated
  `.dat`; HS Cube's panel message names the file and "bytes", and UC1 still
  runs. Fails first: today's panel only says it is waiting.
- `test_cubeCaptionNamesTheBandAndItsWavelength` (new, headful): setting the
  HS Cube slice offset to band k gives a caption with
  `Band k+1 of 109 - <460 + 5k> nm`, after the event loop runs. Fails first: no
  caption.
- `test_colourPreviewCaptionNamesItsWavelengths` (new, headful): switching to
  Colour preview binds the preview node and gives a caption containing
  `650`, `550`, `470` and `not a photograph`. Fails first: no selector.
- `test_clickedCubePixelIsThePixelUnderTheCursor` (new, headful): the XY of
  pixel (i, j)'s centre, from `convertRASToXYZ`, passed to
  `_pickCubePixelAtXYZ`, plots `fixture[:, j, i]`. Fails first: no picker.
- `test_panelsNameTheCubeTheyShow` (new, headful): after a Capture, HS Cube's
  caption contains `002-04` and Tumour Delineation's contains the reference
  case name, and neither carries a word of `PANEL_TEXT_FORBIDDEN_WORDS`.
  Fails first: no captions.
- `test_cubeReadingDoesNotWriteToInput` and `test_cubeRefusalReasonsAreTranslated`
  (extended): also cover the calibrated reader. The source scan also covers
  `SLIAFlowCalibratedCube.py`. Fails first: module missing.
- `test_operatorControlsHaveStatedReasons` (changed): the operator group also
  holds `cubeDisplaySelector`, with a tooltip.
- `test_unreadableCubeDoesNotFailTheCapture`, `test_volumeNamesAreTheImageAndNothingElse`
  and `test_cubeReachesTheCubePanelAndNowhereElse` keep their assertions over
  the new cube.

## Manual verification

Before the steps: `.\scripts\development\build-sliaflow.ps1 -Launch`, open
SLIAFlow, press **Start**.

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Press **Capture** and wait for the result | Within a few seconds HS Cube shows a grey image and a caption reading `Recorded cube 002-04, calibrated reflectance` and `Band 55 of 109 - 730 nm`. Tumour Delineation shows the result with `Result for recorded case 020-01` at the bottom. Record how long HS Cube took to appear and Slicer's memory in Task Manager after the load | Observed 2026-09-24: PASS. HS Cube appeared in 1.69 s on the successful active run (warm file cache); the caption and result caption matched. Slicer working set after load was 1,150,021,632 bytes (~1.07 GiB). |
| 2 | Hover HS Cube and scroll with the mouse wheel or arrow keys, down to band 1 and up to band 109 | The caption changes on every step, from `Band 1 of 109 - 460 nm` to `Band 109 of 109 - 1000 nm`, and the image changes with it | Observed 2026-09-24: PASS. Mouse-wheel events changed the caption one band at a time; band 1 and band 109 showed the expected wavelength captions and different images. |
| 3 | Set **HS Cube shows** to **Colour preview** | HS Cube shows a colour picture of the scene. The caption names `R 650 nm, G 550 nm, B 470 nm` and says `band composite, not a photograph`. Switch back to **Bands**: the band view returns | Observed 2026-09-24: PASS. The colour composite was visible with the exact wavelength/provenance caption, and switching back restored Bands. |
| 4 | Open **Pixel spectrum** and click a bright pixel on HS Cube, then a dark one | The plot shows a curve over 460-1000 nm with axis titles `Wavelength (nm)` and `Reflectance (stored value)`. The line under it names `002-04` and the pixel, and says `stored values, not an analysis`. The curve changes with the second click. Hovering the same pixel shows B values in the Data Probe that agree with the curve at the current band | Observed 2026-09-24: PASS. Real left-press events plotted two labelled pixels; the curves differed, the axes and stored-value wording were present, and Data Probe B values agreed with the selected curve to display rounding. |
| 5 | Press **Capture** again | The cube is reloaded (load time noted again), the band caption returns to band 55, and nothing else changes | Observed 2026-09-24: PASS. The second load took 2.01 s, returned to `Band 55 of 109 - 730 nm`, completed UC1, and kept the result panel labelled `Result for recorded case 020-01`. Working set after load was 1,133,813,760 bytes (~1.06 GiB). |
| 6 | Leave SLIAFlow by selecting another module | The SLIAFlow presentation is deactivated and the previous conventional Slicer layout is restored | Observed 2026-09-24: PASS. Selecting Data removed the SLIAFlow controls/presentation and restored the conventional layout. |

## Risks

- Memory: the cube is 485 MiB as a float32 volume, and the preview adds about
  3.3 MiB. Reading into the volume buffer avoids a second copy, but the old cube
  node lives until the new one is complete, so the peak holds about 1 GiB of
  cube data (1,607 MiB for the whole windowed process, measured below).
  Measure Slicer's memory after load and record it.
- Load time on the main thread, at every Capture. UC1 starts first, so the
  run is not delayed, but the UI is busy while the file is read. Measure it and
  record it. Caching belongs to `SLIA-034`.
- A spectrum plot can look like an analysis result. It shows stored values only
  and says so.
- A left click on a slice view also starts Slicer's window and level drag, so
  dragging from a pixel both plots it and changes the contrast. That is
  accepted and stated in the README.

## Documentation impact

Module README; the in-Slicer section of the UC1 demo runbook; `input/README.txt`
(002-04 is now read).

## Completion evidence

Implementation, automated tests, the pre-verification measurement and manual
verification were recorded 2026-09-24 on
`feature/SLIA-032-show-the-lctf-cube` (before commit).

### Manual verification

- The built launcher was refreshed with
  `.\scripts\development\build-sliaflow.ps1` (exit 0); the build tree
  matched the working tree.
- The windowed built launcher was opened with the approved local `002-04`
  input. The Slicer MCP server was used only for UI interaction/state and
  screenshot inspection because visual verification cannot be established by
  headless tests. No verification screenshots were kept in the repository.
- Steps 1-6 passed in the active six-panel presentation. The input files under
  `input\002-04` retained their pre-run timestamps; capture snapshots were
  written only under the intended ignored `workspace\captures` directory.
- A developer reload performed while SLIAFlow remained the selected module
  left the replacement widget visible but did not reactivate its six-panel
  presentation until the module was left and re-entered. The acceptance steps
  were then repeated after re-entry and passed. This is a reload-lifecycle
  caveat to review separately if Reload is required to preserve presentation
  without re-entry; it did not affect the completed acceptance steps.
  It predates this task and is fixed under "Follow-up to the verification
  notes" below; Reload while selected still needs one manual check.

### Changes

- New `SLIAFlowCalibratedCube.py`, registered in `CMakeLists.txt`. It holds the
  float32 BSQ reader with the header and size checks listed under Decisions,
  a wavelength block parser, `readCalibratedCube(out=...)` that reads into the
  volume's own buffer, and `nearestBand`.
- `SLIAFlowLogic.py`:
  - `calibratedCubeHeader` (reset by `setRunEnvironment`) and
    `loadConfiguredCalibratedCube`;
  - `acceptCube(cube, captureId)` now builds the float32 volume with
    provenance and `SLIAFlow.WavelengthsNm`, and logs its load time;
  - `acceptColourPreview`, `colourPreviewNode`, `previewWavelengths`,
    `cubeBandAt`, `cubeWavelengths`, `pixelSpectrum`, `showPixelSpectrum`,
    `spectrumPlotViewNode` and `removeSpectrumNodes`;
  - `removeCubeNode` also removes the preview and the spectrum.
- `SLIAFlowWidget.py`:
  - UC1 is started before the cube is read, and the cube is shown on every
    Capture;
  - new **HS Cube shows** selector;
  - captions on HS Cube (cube, band and wavelength, or the preview's
    wavelengths) and on Tumour Delineation (the result's case);
  - an unreadable cube is explained on the panel;
  - a left-press observer on HS Cube calls `_pickCubePixelAtXYZ`, and the
    `qMRMLPlotWidget` sits in the new **Pixel spectrum** section;
  - observers and captions are released on deactivate.
- `SLIAFlowParameterNode.py`: `calibratedCubeDetail` and `WAVELENGTHS_ATTRIBUTE`.
- `SLIAFlowCube.py`: `readCube` and `CUBE_FILE_STEM` removed. They only fed the
  HS Cube panel and would be dead code; docstrings updated.
- `SLIAFlow.ui`: the selector row, the Pixel spectrum section, and the Capture
  tooltip.
- `README.md`, `uc1_demo_runbook.md` (step 7 and a status row), and
  `input/README.txt` (gitignored, not staged).

### Tests observed failing first (before any implementation code)

`.\scripts\development\run-slicer-tests.ps1` on the pre-change code with the
new tests: `Ran 85 tests`, `FAILED (failures=3, errors=9, skipped=14)`, exit 1.
`-Headful`: `Ran 85 tests`, `FAILED (failures=4, errors=16, skipped=1)`, exit 1.
The failure messages were:

- `ModuleNotFoundError: No module named 'SLIAFlowLib.SLIAFlowCalibratedCube'`
  (x4): `test_calibratedCubeIsReadWithItsValuesUnchanged`,
  `test_calibratedCubeRejectsIncompatibleContents`,
  `test_cubeReadingDoesNotWriteToInput` and
  `test_cubeRefusalReasonsAreTranslated`.
- `AssertionError: 'raw.dat' != 'LCTF_Calibrated_Cube_Single.dat'`:
  `test_capturedCubeIsShownBandByBand`.
- `AssertionError: unexpectedly None : A refused UC1 case kept the cube off the panel`:
  `test_cubeIsShownEvenWhenUc1IsRefused`.
- `AssertionError: Lists differ: [...] != ['captureButton', 'cubeDisplaySelector', ...]`:
  `test_operatorControlsHaveStatedReasons`.
- `AttributeError: 'SLIAFlowLogic' object has no attribute 'acceptColourPreview'`
  and `... 'pixelSpectrum'`: `test_colourPreviewUsesTheNamedBandsOnAFixedScale`
  and `test_pixelSpectrumIsTheStoredValues`.
- Headful only:
  - `AttributeError: 'SLIAFlowWidget' object has no attribute 'panelCaption'`:
    `test_cubeCaptionNamesTheBandAndItsWavelength` and
    `test_panelsNameTheCubeTheyShow`;
  - `... '_pickCubePixelAtXYZ'`: `test_clickedCubePixelIsThePixelUnderTheCursor`;
  - `AttributeError: '' object has no attribute 'cubeDisplaySelector'`:
    `test_colourPreviewCaptionNamesItsWavelengths`;
  - `AssertionError: <vtkMRMLScalarVolumeNode ...> is not None`:
    `test_unreadableCubeIsExplainedOnThePanel`, because the old code showed the
    reference case's uint16 `raw.dat` instead.

Every pre-existing test passed in both runs.

### Checks after implementation

| Check | Command | Result | Exit |
| --- | --- | --- | --- |
| Static analysis | `.\scripts\development\run-python-quality.ps1` | Ruff 0.15.21: `extensions/SLIAFlow/SLIAFlow` 10 files OK, `tools/simulators` 7 files OK. The first run reported one B905 (`zip()` without `strict=`) in the new module, now fixed | 0 |
| Automated, working tree, headless | `.\scripts\development\run-slicer-tests.ps1` | module loaded from `C:\stratum\extensions\SLIAFlow\SLIAFlow\SLIAFlow.py`; `Ran 85 tests`, `OK (skipped=14)`; the skips are the headful-only tests | 0 |
| Automated, working tree, headful | `.\scripts\development\run-slicer-tests.ps1 -Headful` | `Ran 85 tests`, `OK (skipped=1)`; the one skip is `test_headlessPresentationFallback` | 0 |
| Launcher refresh | `.\scripts\development\build-sliaflow.ps1` | every module file `ok` in Verify, including `SLIAFlowLib\SLIAFlowCalibratedCube.py`; "The build tree matches the working tree." | 0 |
| Automated, built launcher | `.\scripts\development\run-slicer-tests.ps1 -Target Build` | module loaded from `C:\stratum\build\SLIAFlow\lib\Slicer-5.13\qt-scripted-modules\SLIAFlow.py`; `Ran 85 tests`, `OK (skipped=14)` | 0 |

The runner's 85 tests are 84 `SLIAFlowTest` methods plus the base-class entry
that `testing_strategy.md` describes.

### Real 002-04 cube, measured through the module's logic

`SlicerWithSLIAFlow.exe --no-splash --no-main-window --python-script measure_cube.py`
(scratch script, not committed). It called `loadConfiguredCalibratedCube`,
`acceptCube` twice, `acceptColourPreview` and `showPixelSpectrum(540, 540)` on
`C:\stratum\input\002-04\LCTF_Calibrated_Cube_Single.hdr`:

- volume `float32 [109, 1080, 1080]`, element for element identical to
  `np.fromfile` of the `.dat`;
- load in 0.886 s the first time and 0.910 s the second, from a warm file cache;
- process working set 343 MiB before, 838 MiB after the first load (+494 MiB,
  which is the cube). The peak during the second load is 1,329 MiB, while the
  old and new cube nodes coexist; the working set after it is 833 MiB;
- colour preview in 0.017 s, with bands `[650, 550, 470]` nm; spectrum in under
  1 ms.

The windowed figures and the cold-cache bound are under "Follow-up to the
verification notes".

### Follow-up to the verification notes (2026-09-24)

Three notes were raised after manual verification.

1. **Reload while SLIAFlow is selected left the presentation off.** Slicer's
   Reload calls `cleanup()` on the old widget and `setup()` on the new one, but
   not `enter()`. The module stays entered
   (`slicer.util.reloadScriptedModule`, then
   `qSlicerScriptedLoadableModuleWidget::reload`). `setup`, `cleanup`, `enter`
   and `exit` are unchanged from `main`, so the fault predates this task. It is
   fixed here because it breaks the developer Reload step of
   `manual-verification-workflow.md`, and `SLIAFlowWidget.py` is an allowed
   file. `setup()` now ends by calling `enter()` when `self.parent.isEntered`,
   the same check `onSceneEndClose` uses. On first setup the module is not yet
   entered, so nothing activates twice. New headful test
   `test_reloadWhileSelectedKeepsThePresentation` selects SLIAFlow, calls the
   real `slicer.util.reloadScriptedModule("SLIAFlow")`, and requires the new
   widget to hold the six-panel layout.
2. **Empty wavelength entries were dropped.** The parser discarded empty
   comma-separated entries, so `{460, , 465, ...}` with 109 numbers passed,
   against the "exactly `bands` numbers" rule above. Empty entries are now kept
   and refused as `lists a wavelength that is not a number`. The real 002-04
   header has neither empty entries nor a trailing comma, so it still loads.
   `test_calibratedCubeRejectsIncompatibleContents` gains `empty-wavelength-entry`
   and `trailing-comma`.
3. **Cold load and peak memory.** Windows cannot empty its file cache without
   administrator rights, so the cold read was bounded instead. The `.dat` was
   read with `FILE_FLAG_NO_BUFFERING` (read-only, scratch script, nothing
   copied), which bypasses the cache: 0.238, 0.219 and 0.226 s for 508,550,400
   bytes, about 2.1 GiB/s on this machine's NVMe SSD (KIOXIA EXCERIA PLUS G3).
   A cold cache therefore adds at most about 0.25 s here. A slower disk on
   another machine would add more. The logic measurement was repeated with the
   main window open (`SlicerWithSLIAFlow.exe --no-splash --python-script`):
   - working set 623 MiB before, 1,117 MiB after the first load, which agrees
     with the manual step 1 figure;
   - loads of 1.194 s and 1.383 s from a warm cache;
   - a peak working set of 1,607 MiB during the second load, while the old and
     new cubes coexist;
   - committed private memory 1,674 MiB before and 2,172 MiB after.

   The script's own later comparison copy of the file raised its peak to 1,728
   MiB; that copy is not module memory. Caching and the old/new overlap remain
   `SLIA-034`.

Tests observed failing first:

- Headless: `Ran 85 tests`, `FAILED (failures=2, skipped=14)`, exit 1. Both
  failures were `AssertionError: CalibratedCubeError not raised`, in the
  subtests `empty-wavelength-entry` and `trailing-comma`.
- Headful, with the parser already fixed: `Ran 86 tests`,
  `FAILED (failures=1, skipped=1)`, exit 1. The failure was
  `test_reloadWhileSelectedKeepsThePresentation`:
  `AssertionError: False is not true : The reloaded widget left the presentation off`.

Checks after the fixes, all exit 0:

| Check | Result |
| --- | --- |
| `run-python-quality.ps1` | `All checks passed!` (both targets) |
| `run-slicer-tests.ps1` | `Ran 86 tests`, `OK (skipped=15)`, the headful-only tests |
| `run-slicer-tests.ps1 -Headful` | `Ran 86 tests`, `OK (skipped=1)`, `test_headlessPresentationFallback` |
| `build-sliaflow.ps1` | "The build tree matches the working tree." |
| `run-slicer-tests.ps1 -Target Build` | module from `build\SLIAFlow\...`; `Ran 86 tests`, `OK (skipped=15)` |

Still manual: with SLIAFlow selected and the presentation on, press **Reload**
in the module's developer section. The six-panel layout stays, and Start and
Capture work without leaving the module. Then run **Reload and Test**.

## Review findings

## Human approval

The project owner confirmed on 2026-09-24 that SLIA-032 is completed and
requested that this card be included in the task commit.
