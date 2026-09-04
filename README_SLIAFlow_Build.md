# Build And Test SLIAFlow On Windows

SLIAFlow is a non-clinical STRATUM visualization prototype implemented as a
Python scripted extension for 3D Slicer. The extension build is regenerable;
the existing base Slicer build must not be deleted or modified.

## Canonical paths

| Purpose | Path |
| --- | --- |
| Base Slicer build | `C:\stratum\apps\SR\Slicer-build` |
| Extension source | `C:\stratum\extensions\SLIAFlow` |
| Extension build | `C:\stratum\build\SLIAFlow` |
| Extension launcher | `C:\stratum\build\SLIAFlow\SlicerWithSLIAFlow.exe` |
| SlicerOpenIGTLink package | `C:\stratum\build\SlicerOpenIGTLink\inner-build` |

Machine-specific paths belong in the ignored `config/local.json`; use
`config/local.example.json` as its portable template.

## Prerequisites

- Windows 11.
- Visual Studio 2022 with the Desktop development with C++ workload.
- CMake 3.28 or newer.
- The existing Release base Slicer build at `apps/SR/Slicer-build`.
- The SlicerOpenIGTLink dependency built at `build/SlicerOpenIGTLink`. See
  `docs/development/openigtlink_setup.md`.
- Ruff for Python quality checks. `scripts/development/run-python-quality.ps1`
  finds it in the ignored root `.venv` or on `PATH`.

Run configure and build commands from an x64 Native Tools Command Prompt for
Visual Studio 2022 when the compiler environment is not already active.

## Configure

Only the ignored extension build directory may be regenerated. Do not remove
or rebuild `apps/SR` for normal SLIAFlow development.

```powershell
cmake `
  -S C:\stratum\extensions\SLIAFlow `
  -B C:\stratum\build\SLIAFlow `
  -G "Visual Studio 17 2022" `
  -A x64 `
  -DSlicer_DIR:PATH=C:\stratum\apps\SR\Slicer-build `
  -DBUILD_TESTING:BOOL=ON `
  -DSlicerOpenIGTLink_DIR:PATH=C:\stratum\build\SlicerOpenIGTLink\inner-build
```

A successful configure creates
`build\SLIAFlow\SlicerWithSLIAFlow.exe` without modifying the base Slicer
tree.

`SlicerOpenIGTLink_DIR` is what turns the `EXTENSION_DEPENDS` declaration in
`extensions/SLIAFlow/CMakeLists.txt` into module paths inside the generated
launcher. It is the `inner-build` subdirectory of the dependency superbuild.
Reconfigure after the dependency is rebuilt or moved; the launcher argument
list is generated at configure time.

## Build

```powershell
cmake --build C:\stratum\build\SLIAFlow --config Release
```

Python-only edits normally need Reload or Reload and Test in Slicer, not a
rebuild. Reconfigure after editing CMake files or adding resources.

## Automated tests

Run the focused CTest registration:

```powershell
ctest --test-dir C:\stratum\build\SLIAFlow -C Release --output-on-failure
```

Run the same module test directly through Slicer:

```powershell
powershell -ExecutionPolicy Bypass -File C:\stratum\scripts\development\run-slicer-tests.ps1
```

Run Python quality checks:

```powershell
powershell -ExecutionPolicy Bypass -File C:\stratum\scripts\development\run-python-quality.ps1
```

## Launch and manual verification

```powershell
C:\stratum\build\SLIAFlow\SlicerWithSLIAFlow.exe
```

In Slicer:

1. Enable Developer Mode in Application Settings if it is not already enabled.
2. Select `SLIAFlow` from the `STRATUM` category.
3. Confirm the prototype warning and the two volume-reference selectors appear.
4. Open the scripted-module Reload and Test section.
5. Run Reload, then Reload and Test.

The module is a scaffold only. It must not generate diagnostic images, present
simulated clinical results, or be used with private or identifiable patient
data.
