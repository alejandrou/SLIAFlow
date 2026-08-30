# Laptop camera setup

SLIAFlow can show a Windows laptop camera in its left `Live Image` pane. This
is prototype presentation functionality only. It does not create a diagnostic
result, is not clinically validated, and must not be used with private or
identifiable patient data.

## One-time installation

SLIAFlow pins `opencv-python-headless==5.0.0.93` for Slicer's own Python
environment. The module never installs it during import or startup.

1. Start the Slicer executable configured in `config/local.json`.
2. Open the SLIAFlow module.
3. If the status says camera support is missing, select **Install Camera
   Support**.
4. Wait for the installation to finish, close Slicer, and start it again.

Do not use a system Python or a separate `pip` command. The button delegates to
`slicer.util.pip_install`, which installs into the Slicer environment that runs
SLIAFlow.

## Starting and stopping

1. Open SLIAFlow and keep **Camera index** at `0` for the built-in laptop
   camera.
2. Select **Start**. The module tries the Windows Media Foundation backend,
   then DirectShow, then OpenCV's default backend.
3. Select **Stop** before opening the camera in another application.

Capture requests 640 by 480 pixels and updates on a 66 ms Qt timer. The timer
keeps camera reads on short UI-thread callbacks; no blocking capture loop is
started. Stop, module exit, scene close, Reload, and capture errors all release
the timer and camera.

The `UC1 Result` pane must remain black and show `Waiting for genuine UC1
result` while laptop capture runs.

## Troubleshooting

- **No camera opens:** verify the camera index, enable camera access under
  Windows **Settings > Privacy & security > Camera**, and close Teams, Zoom,
  browsers, or other software that may own the device.
- **The wrong camera opens:** stop capture, choose another index, and start
  again. Index `0` is only the default; Windows device ordering can vary.
- **The camera remains busy:** press Stop or leave SLIAFlow, then retry. If a
  Reload was interrupted, close and restart Slicer before retrying.
- **Installation fails:** read the Slicer Python console for the package error
  and confirm that the machine can reach the configured Python package index.
- **Colours look incorrect:** report the camera model and selected backend.
  SLIAFlow converts OpenCV BGR frames to RGB before updating its vector volume.

For developer verification, enable Developer Mode and use **Reload** or
**Reload and Test**. Automated tests use injected fake captures and synthetic
in-memory colour arrays; they never open the physical camera.
