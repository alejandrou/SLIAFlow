---
id: SLIA-005
title: Display the Windows laptop camera
status: backlog
branch:
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

This is the first usable demonstrator checkpoint and works without HSI hardware
or a running UC1 implementation.

## Requirements

- Pin `opencv-python-headless==5.0.0.93` for Slicer's Python environment.
- Detect whether `cv2` is available without installing anything at module import.
- Provide an explicit Install Camera Support action using `slicer.util.pip_install` and request a Slicer restart afterward.
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

- `extensions/SLIAFlow/SLIAFlow/Resources/requirements.txt`
- `extensions/SLIAFlow/SLIAFlow/Resources/UI/SLIAFlow.ui`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowParameterNode.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `extensions/SLIAFlow/SLIAFlow/Testing/**`
- `docs/development/camera_setup.md`
- `tasks/{backlog,active,review,completed}/SLIA-005-laptop-camera.md`

## Relevant skills and references

- Slicer MRML volume/NumPy and Qt timer patterns.
- OpenCV Windows `VideoCapture` backends.
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`

## Implementation plan

1. Add dependency detection and explicit installation UI.
2. Implement backend selection and camera ownership in logic.
3. Update the live vector-volume node from timer callbacks.
4. Bind the node to only the left slice view and fit it to view.
5. Add cleanup, failure tests, and the one-time setup note.

## Acceptance criteria

- A working laptop camera updates only the left pane at a responsive rate.
- Stop releases the camera, and repeated start/stop remains stable.
- Missing OpenCV or missing camera produces a clear status and black live pane.
- The right pane remains black with the genuine-result waiting message.
- Reload and Reload and Test do not leave a locked camera.

## Test plan

- Unit-test backend fallback and cleanup through injected fake capture objects.
- Test frame shape and BGR-to-RGB conversion without showing the fixture in the module UI.
- Run Python quality and focused CTest.
- Manually test the physical laptop camera, Stop/Start, Reload, and error behavior.

## Manual verification

Start the camera, verify live motion in the left pane, confirm the right pane is
still black, stop/restart, and run Reload and Reload and Test.

## Risks

Windows camera backends vary by driver. Ordered backend fallback and explicit
resource cleanup prevent a failed attempt from locking the device.

## Documentation impact

Add the one-time OpenCV installation and camera troubleshooting procedure.

## Completion evidence

Reserved for implementation evidence.

## Review findings

Reserved for review.

## Human approval

Required before review and completion.
