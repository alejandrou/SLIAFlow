---
id: SLIA-005
title: Display the Windows laptop camera
status: completed
branch: feature/SLIA-005-laptop-camera
priority: high
depends_on: SLIA-004
required_skills: [slicer]
optional_tools: []
related_adrs: []
---

# SLIA-005 - Display the Windows laptop camera

## Goal

Display a real live laptop-camera feed in the left Slicer pane while keeping the
UC1 result pane black.

## Context

`SLIA-004` established a monolithic scripted module entry point with a custom
two-pane layout, disabled future controls, and module-owned waiting annotation.
This task is the first usable demonstrator checkpoint and works without HSI
hardware or a running UC1 implementation. Camera capture remains presentation
only and must not affect the genuine-result pane.

## Requirements

- Pin `opencv-python-headless==5.0.0.93` for Slicer's Python environment.
- Detect whether `cv2` is available without installing anything at module import.
- Provide an explicit Install Camera Support action using
  `slicer.util.pip_install` and request a Slicer restart afterward.
- Default to camera index 0, 640 by 480 pixels, and a 66 ms Qt timer interval.
- Try `CAP_MSMF`, then `CAP_DSHOW`, then the OpenCV default backend.
- Convert OpenCV BGR frames to RGB and update one module-owned `vtkMRMLVectorVolumeNode` with KJI-compatible array shape.
- Store and retrieve the live node through its MRML ID.
- Start and stop without blocking Slicer's main UI thread.
- Release the timer and camera on Stop, module exit, scene close, reload, and error.
- Leave the live pane black and show an actionable message if no camera opens.
- Never change the UC1 result pane or create diagnostic output.

## Out of scope

- Recording video or saving frames.
- Camera calibration, stereoscopic processing, or HSI simulation.
- UC1 result generation or networking.

## Files allowed

- `extensions/SLIAFlow/SLIAFlow/CMakeLists.txt`
- `extensions/SLIAFlow/SLIAFlow/Resources/requirements.txt`
- `extensions/SLIAFlow/SLIAFlow/Resources/UI/SLIAFlow.ui`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlow.py`
- `docs/development/camera_setup.md`
- `tasks/{backlog,active,review,completed}/SLIA-005-laptop-camera.md`

## Relevant skills and references

- `slicer` skill and its local Slicer source checkout for MRML vector-volume,
  NumPy KJI ordering, slice-composite, Qt timer, and `pip_install` patterns.
- OpenCV Windows `VideoCapture` backends.
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`

## Implementation plan

1. Add a packaged pinned requirement plus dependency detection and explicit
   installation UI without importing or installing OpenCV at module import.
2. Implement injectable backend selection, frame conversion, timer ownership,
   and idempotent cleanup in `SLIAFlowLogic`.
3. Create or recover one module-owned vector-volume node through the parameter
   node reference and update it from RGB KJI arrays on Qt timer callbacks.
4. Bind the node to only the left slice view, fit it to view, and keep all
   right-pane presentation state unchanged.
5. Add fail-first Slicer-hosted tests for fallback, conversion, lifecycle,
   node ownership, and pane isolation, then add the one-time setup note.

## Acceptance criteria

- A working laptop camera updates only the left pane at a responsive rate.
- Stop releases the camera, and repeated start/stop remains stable.
- Missing OpenCV or missing camera produces a clear status and black live pane.
- The right pane remains black with the genuine-result waiting message.
- Reload and Reload and Test do not leave a locked camera.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| A working laptop camera updates only the left pane at a responsive rate | `SLIAFlowTest.test_cameraFrameConversion` and `SLIAFlowTest.test_cameraFrameUpdatesOnlyLiveView`, plus manual steps 3-4 | automated + manual |
| Stop releases the camera, and repeated start/stop remains stable | `SLIAFlowTest.test_cameraBackendFallbackAndLifecycle`, plus manual step 6 | automated + manual |
| Missing OpenCV or missing camera produces a clear status and black live pane | `SLIAFlowTest.test_cameraSupportAndFailureStates`, plus manual steps 1 and 7 | automated + manual |
| The right pane remains black with the genuine-result waiting message | `SLIAFlowTest.test_cameraFrameUpdatesOnlyLiveView`, plus manual step 5 | automated + manual |
| Reload and Reload and Test do not leave a locked camera | `SLIAFlowTest.test_cameraBackendFallbackAndLifecycle`, plus manual steps 8-9 | automated + manual |

Tests to add or change, and how each one will be shown to fail first:

- Add `test_cameraFrameConversion`; before implementation it fails because the
  camera conversion API does not exist.
- Add `test_cameraBackendFallbackAndLifecycle`; before implementation it fails
  because the camera backend/timer lifecycle API does not exist.
- Add `test_cameraSupportAndFailureStates`; before implementation it fails
  because dependency detection and camera failure UI are absent.
- Add `test_cameraFrameUpdatesOnlyLiveView`; before implementation it fails
  because no live vector volume can be updated or assigned to the left pane.
- Run `scripts/development/run-python-quality.ps1` and
  `scripts/development/run-slicer-tests.ps1` after implementation.

## Manual verification

Perform in the Slicer executable configured in `config/local.json`, with
Developer Mode enabled. Use no patient or private medical data.

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Open SLIAFlow before OpenCV is installed; if it is already installed, review the equivalent documented first-run state | Missing support is reported clearly, the live pane stays black, and only the explicit Install Camera Support action offers installation | |
| 2 | If needed, press Install Camera Support and follow the restart instruction | The pinned package is installed only after the click, and Slicer explicitly asks to restart | |
| 3 | Restart Slicer, open SLIAFlow, keep camera index `0`, and press Start | The status reports live capture and the left pane begins updating without freezing the UI | |
| 4 | Move an object in front of the laptop camera | Motion and correct RGB colours appear responsively in only the `Live Image` pane | |
| 5 | Inspect the `UC1 Result` pane while capture runs | It remains black and continues to show `Waiting for genuine UC1 result` | |
| 6 | Press Stop and Start three times | Each Stop releases capture and blacks the live pane; every subsequent Start reacquires the camera without freezing Slicer | |
| 7 | Stop, choose an unavailable camera index, and press Start | The live pane stays black and an actionable camera/permission message appears; no diagnostic image is created | |
| 8 | Restore index `0`, start capture, press Reload, then start capture again | Reload releases the old capture and the camera can be reacquired | |
| 9 | With capture stopped, press Reload and Test; then start capture again | Every `SLIAFlowTest.test_*` method reports `ok`, and the camera remains available afterward | |
| 10 | Start capture, then leave SLIAFlow for Welcome | The camera feed disappears and the layout that was active before SLIAFlow is restored | |
| 11 | Return to SLIAFlow, press Start, then press Stop | The camera can be reacquired after module exit; Stop blacks the live pane | |
| 12 | Leave SLIAFlow for Welcome | The previous layout is restored again and no SLIAFlow camera feed remains visible | |

## Risks

Windows camera backends vary by driver. Ordered backend fallback and explicit
resource cleanup prevent a failed attempt from locking the device. Camera
orientation and backend availability vary by hardware; this task preserves the
raw frame orientation and treats unsupported devices as an actionable failure.

## Documentation impact

Add `docs/development/camera_setup.md` with the one-time pinned OpenCV
installation, restart, Windows permission, camera-index, and device-lock
troubleshooting procedure.

## Completion evidence

- Selected because `SLIA-004` is completed, `SLIA-005` is its direct dependent,
  every later high-priority task depends transitively on it, and the roadmap
  places it next. `tasks/active/` and `tasks/review/` were empty and the
  worktree was clean before activation.
- Branch created and used: `feature/SLIA-005-laptop-camera`, from approved local
  `main` at `ae22189`.
- Added explicit, user-triggered installation of
  `opencv-python-headless==5.0.0.93`; module import never imports or installs
  OpenCV. A completed installation disables capture and asks the operator to
  restart Slicer.
- Added ordered `CAP_MSMF`, `CAP_DSHOW`, and default-backend fallback; requested
  640 by 480 capture; converted BGR `uint8` frames to contiguous RGB arrays in
  `[K, J, I, C]` shape; and scheduled reads with a 66 ms PythonQt timer.
- Added idempotent timer/capture cleanup on Stop, error, widget cleanup, module
  exit, and scene close. Failed backend attempts are released immediately.
- Added one non-persisted module-owned `vtkMRMLVectorVolumeNode`, referenced by
  MRML node ID. The implementation migrates a legacy scalar `liveVolume`
  reference safely, updates only the live slice composite, and never assigns a
  camera frame to the result composite.
- Added the Install, Start, and Stop UI states and actionable messages for
  missing support, install/restart, unavailable devices, and frame failure.
  Future result controls remain disabled.
- Added `docs/development/camera_setup.md` and packaged
  `Resources/requirements.txt` through the scripted-module CMake resource list.
- Fail-first evidence: before production implementation,
  `.\scripts\development\run-slicer-tests.ps1` exited `1` with
  `AttributeError` for missing `SLIAFlowLogic.startCamera`,
  `SLIAFlowLogic.frameToRGBKJI`, `SLIAFlowLogic.OPENCV_REQUIREMENT`,
  `SLIAFlowWidget._displayCameraFrame`, and the missing
  `installCameraSupportButton`. The run reported 5 errors across 9 discovered
  tests.
- `.\scripts\development\run-python-quality.ps1`: Ruff 0.15.21, all checks
  passed, exit code `0`.
- `.\scripts\development\run-slicer-tests.ps1`: loaded the working-tree module
  from `C:\stratum\extensions\SLIAFlow\SLIAFlow\SLIAFlow.py`; all 9
  `SLIAFlowTest.test_*` methods passed, plus Slicer's imported base `runTest`;
  10 tests total, exit code `0`.
- Headful source-backed Slicer invocation with a real layout manager and fake
  captures: the same 10 tests passed, exit code `0`. This exercised the custom
  layout and real PythonQt `QTimer` connection without opening physical camera
  hardware.
- PowerShell UI XML parse and exact requirement-pin assertion passed, exit code
  `0`. `git diff --check` passed, exit code `0`; its only output was Git's
  existing LF-to-CRLF working-copy warning.
- Compiled-extension build and CTest were not run because they would modify
  protected generated build outputs; source-backed Slicer tests are the fast
  implementation gate for this Python/UI change.
- Physical-camera installation, motion/colour/responsiveness, Windows driver
  fallback, device-lock release, Reload, Reload and Test, and operator-facing
  failure messages remain pending in manual steps 1-12. No manual result has
  been marked complete.

## Review findings

Reserved for review.

## Human approval

Required before review and completion.
