# Building the SlicerOpenIGTLink dependency

> **Used again since `SLIA-035`.** Capture and UC1 still run inside Slicer with
> no network hop (`ADR-0003`), but the **Connections** section connects to IUMA's
> acquisition app on 18944, 18945 and 18946 as an OpenIGTLink client (`ADR-0004`
> decision 2), so SLIAFlow declares this dependency again. Received data is not
> yet used by the module; `SLIA-030` receives the cube. The Connections section
> is described in `extensions/SLIAFlow/README.md`, and the stand-in for the app in
> `tools/simulators/README.md`.

SLIAFlow will carry `LiveView` frames and UC1 image maps over OpenIGTLink as
independent TCP/IP streams. That transport comes from the official
SlicerOpenIGTLink extension, which is built here as a separate, pinned
dependency.

The base Slicer application under `apps/SR` is not moved, edited, or rebuilt.
The dependency is a second extension build that the SLIAFlow launcher is told
about at configure time.

This page covers the build and the discovery wiring only. The connectors and
what they receive belong to the Connections section (`SLIA-035`).

## Canonical paths

| Purpose | Path |
| --- | --- |
| Base Slicer build | `C:\stratum\apps\SR\Slicer-build` |
| Dependency source | `C:\stratum\workspace\dependencies\SlicerOpenIGTLink` |
| Dependency superbuild | `C:\stratum\build\SlicerOpenIGTLink` |
| Dependency package directory | `C:\stratum\build\SlicerOpenIGTLink\inner-build` |
| Extension source | `C:\stratum\extensions\SLIAFlow` |
| Extension build | `C:\stratum\build\SLIAFlow` |

Both `workspace/` and `build/` are ignored by Git, so the dependency source and
all of its build output stay out of this repository's history.

## Pinned revision

| Item | Value |
| --- | --- |
| Repository | `https://github.com/openigtlink/SlicerOpenIGTLink.git` |
| Commit | `85e5f764f3ad3d4adbaa568db0104b2b8f5998e8` |
| Subject | `COMP: Fix Qt6 compiler error due to unavailable buttonClicked(int) signal` |

The clone is left in detached `HEAD` at that commit rather than on `master`.
A branch would silently move the day someone runs `git pull` in that directory;
a detached checkout makes the pin the state of the working tree itself, so
`rev-parse HEAD` is the whole verification.

The source tree is never modified. Any local change there is a defect, not a
customisation.

## Clone and pin

```powershell
git clone https://github.com/openigtlink/SlicerOpenIGTLink.git `
  C:\stratum\workspace\dependencies\SlicerOpenIGTLink

git -C C:\stratum\workspace\dependencies\SlicerOpenIGTLink `
  checkout --detach 85e5f764f3ad3d4adbaa568db0104b2b8f5998e8
```

Verify:

```powershell
git -C C:\stratum\workspace\dependencies\SlicerOpenIGTLink rev-parse HEAD
git -C C:\stratum\workspace\dependencies\SlicerOpenIGTLink status --short
```

`rev-parse` must print the pinned commit and `status --short` must print
nothing.

## Configure and build the dependency

SlicerOpenIGTLink is a superbuild: it fetches and builds OpenIGTLink and
OpenIGTLinkIO first, then its own modules into `inner-build`.

```powershell
cmake `
  -S C:\stratum\workspace\dependencies\SlicerOpenIGTLink `
  -B C:\stratum\build\SlicerOpenIGTLink `
  -G "Visual Studio 17 2022" `
  -A x64 `
  -DSlicer_DIR:PATH=C:\stratum\apps\SR\Slicer-build `
  -DCMAKE_BUILD_TYPE:STRING=Release

cmake --build C:\stratum\build\SlicerOpenIGTLink --config Release
```

The generator, architecture, and configuration match the base Slicer build; a
Debug dependency will not load into this Release Slicer.

The build downloads OpenIGTLink and OpenIGTLinkIO from GitHub, so it needs
network access the first time. `SlicerOpenIGTLink_USE_VP9` is left `OFF`: video
compression is not part of the SLIAFlow transport.

A successful build produces the loadable modules under
`build\SlicerOpenIGTLink\inner-build\lib\Slicer-5.13\qt-loadable-modules\Release`
and the OpenIGTLink runtime libraries under
`build\SlicerOpenIGTLink\bin\Release`.

## Point SLIAFlow at the dependency

`extensions/SLIAFlow/CMakeLists.txt` declares the dependency:

```cmake
set(EXTENSION_DEPENDS "SlicerOpenIGTLink")
```

Slicer's extension CPack module reads that name and appends `${dep}_DIR` to the
module paths baked into the generated `SlicerWithSLIAFlow` launcher. The
declaration alone is not enough; the configure step must also say where the
built dependency is:

```powershell
cmake `
  -S C:\stratum\extensions\SLIAFlow `
  -B C:\stratum\build\SLIAFlow `
  -G "Visual Studio 17 2022" `
  -A x64 `
  -DSlicer_DIR:PATH=C:\stratum\apps\SR\Slicer-build `
  -DBUILD_TESTING:BOOL=ON `
  -DSlicerOpenIGTLink_DIR:PATH=C:\stratum\build\SlicerOpenIGTLink\inner-build

cmake --build C:\stratum\build\SLIAFlow --config Release
```

`SlicerOpenIGTLink_DIR` is the `inner-build` directory, not the superbuild root.
The superbuild root holds the external projects; `inner-build` is the generated
extension package with the module tree and the extension config file.

Reconfiguring is required because the launcher argument list is generated at
configure time. Rebuilding without it leaves a launcher that still knows nothing
about OpenIGTLink. `scripts\development\build-sliaflow.ps1 -Configure`
does this with the `SlicerOpenIGTLink_DIR` already in `build\SLIAFlow`'s CMake
cache.

`SLIA-027` set `EXTENSION_DEPENDS` to `NA`, and a launcher configured then does
not load OpenIGTLinkIF; `SLIA-035` declares the dependency again, so such a
build must be reconfigured.

## How the runtime libraries are found

`qSlicerOpenIGTLinkIFModule.dll` links `OpenIGTLink.dll`, and the only copy of
that library is under `build\SlicerOpenIGTLink\bin\Release`. That directory is
not in the `[LibraryPaths]` of `SlicerWithSLIAFlowLauncherSettings.ini`, which
is the file worth checking first and the wrong place to look.

The dependency's own library paths reach the launcher through a second settings
file. `SlicerExtensionGenerateConfig.cmake` exports
`SlicerOpenIGTLink_LIBRARY_PATHS_LAUNCHER_BUILD` into the extension config file
in `inner-build`. When SLIAFlow is configured with `SlicerOpenIGTLink_DIR`, that
list is written into `build\SLIAFlow\AdditionalLauncherSettings.ini`, and
`SlicerExtensionCPack.cmake` passes that file to the launcher with
`--launcher-additional-settings`. The OpenIGTLink, OpenIGTLinkIO, and
`bin\Release` directories are all in it.

So the dependency's DLL directories are on the search path, just through the
additional settings file rather than the main one. To see them:

```powershell
Select-String -Path C:\stratum\build\SLIAFlow\AdditionalLauncherSettings.ini `
  -Pattern SlicerOpenIGTLink
```

This is also why a reconfigure is mandatory after the dependency moves: the
additional settings file is generated with absolute paths at configure time.

## Verify discovery

Ask the running application which modules it has, rather than reading the
launcher `.ini` and inferring:

```powershell
$code = "import slicer; print(slicer.util.modulePath('OpenIGTLinkIF')); print(slicer.util.modulePath('SLIAFlow'))"
& C:\stratum\build\SLIAFlow\SlicerWithSLIAFlow.exe `
  --no-splash --no-main-window --testing --python-code $code
```

Both paths must resolve, `OpenIGTLinkIF` under
`build\SlicerOpenIGTLink\inner-build\...` and `SLIAFlow` under
`build\SLIAFlow\...`. A path pointing anywhere else means a previously
installed extension is shadowing this build.

To prove the native library actually loaded, and not merely that a module was
registered, instantiate a node the dependency owns:

```powershell
$code = "import slicer; print(slicer.vtkMRMLIGTLConnectorNode().GetClassName())"
& C:\stratum\build\SLIAFlow\SlicerWithSLIAFlow.exe `
  --no-splash --no-main-window --testing --python-code $code
```

This must print `vtkMRMLIGTLConnectorNode`.

## Tests against the working tree

`scripts\development\run-slicer-tests.ps1` (the Source target) runs the
configured `Slicer.exe`, which does not carry this dependency. It therefore
passes `--launcher-additional-settings
build\SlicerOpenIGTLink\inner-build\AdditionalLauncherSettings.ini` for the
libraries and adds the build's `qt-loadable-modules\Release` and
`qt-scripted-modules` folders to the module paths, and it stops with an error
naming the folder when the build is missing. `SLIAFlowTest.test_openIGTLinkIFIsLoaded`
fails if OpenIGTLinkIF did not load, so the connector tests can never pass by
being skipped.

## Client connectors on Windows

Measured on this laptop for `SLIA-035`:

- A client connector retries every 100 ms and does not log a failed attempt.
- `Stop()` waits for the attempt in progress. With nothing listening, Windows
  takes about 2 s to refuse a connection to a closed local port, so stopping a
  waiting connector blocks for 1.0 to 2.1 s; a connected one stops in about
  15 ms.
- A connector can be stopped and started again. When the node a device wrote
  into has been removed, the next message of that device creates a new one
  (`ProcessIncomingDeviceModifiedEvent`), so SLIAFlow keeps its connectors
  listed while disconnected and removes only what they received.
- When a device's first image arrives, Slicer warns that the image geometry is
  not the identity (`vtkMRMLVolumeNode::SetAndObserveImageData`). OpenIGTLinkIF
  resets the geometry right after, so the warning appears once per received
  device, not once per message: 2 warnings for 100 LiveView frames.
- A connector receiving an IMAGE device takes the first scene volume of that
  class whose name is the device name. SLIAFlow's camera volume is therefore
  named `Laptop camera`, not `LiveView`.

## Measuring what a server sends

`SLIA-030` measures IUMA's app with a recorder outside Slicer,
`python -m stratum_sim.igtl_recorder` (`tools/simulators/README.md`). It logs
every message's header, metadata and image properties, and matches each band
against a cube on disk to find band order and orientation. It is the ports' one
client while it runs, so SLIAFlow must be disconnected.

The app's protocol, measured on 2026-09-27, is recorded in
`docs/hardware/acquisition_app_and_hardware.md` section 4.1. In short, the
`HsCube` port sends header version 1 with no metadata. Every IMAGE declares
the whole cube and carries one band as a sub-volume at offset
(0, 0, band − 1). No message marks the end of a cube.

OpenIGTLinkIF assembles such sub-volumes into one volume of the full size
(`igtlioImageConverter::IGTLToVTKImageData`), reused while size, type and
components are unchanged. It does not clear that volume, so a band that did not
arrive holds old memory, and the volume node does not say which bands arrived.
A connector on 18946 therefore yields a whole cube, but not the proof that the
cube is complete.

## Regression gate

This dependency adds no SLIAFlow behaviour, so it gets no new test. It is
guarded by re-running the existing suite against the rebuilt extension:

```powershell
powershell -ExecutionPolicy Bypass -File C:\stratum\scripts\development\run-slicer-tests.ps1
powershell -ExecutionPolicy Bypass -File C:\stratum\scripts\development\run-slicer-tests.ps1 -Target Build
ctest --test-dir C:\stratum\build\SLIAFlow -C Release --output-on-failure
```

The `Build` target matters here: it exercises the compiled copy that the
reconfigured launcher actually loads, which is the thing this change touched.

## Notes and limitations

The base Slicer build and the dependency must stay on the same Slicer revision.
Rebuilding or replacing `apps/SR` invalidates `build\SlicerOpenIGTLink` and both
extension builds have to be reconfigured against the new Slicer directory.

Nothing here is packaged or published. Both extensions are local development
builds, discovered through the generated `SlicerWithSLIAFlow` launcher and not
through the Slicer Extensions Manager.
