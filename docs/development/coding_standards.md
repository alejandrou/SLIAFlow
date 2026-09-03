# Coding Standards

Mandatory code-quality policy lives in `.ai/policies/code-quality.md`. This document gives technical guidance for SLIAFlow Slicer development.

## Priorities

Prefer code that is:

1. Readable.
2. Maintainable.
3. Robust.

Do not optimize for performance before the behavior and boundaries are clear.

## Local Python Quality Checks

From the repository root, run:

```powershell
.\scripts\development\run-python-quality.ps1
```

Ruff is the only static analysis gate. The script resolves it from the ignored root `.venv` first and from `PATH` second, so activating the environment is optional; it prints the executable and version it used and exits nonzero when Ruff is missing or reports a finding. Ruff is a development tool, not a Slicer runtime dependency, and the script does not install it.

Create the environment once:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install ruff
```

The script lints two targets and fails if either one reports a finding: `extensions/SLIAFlow/SLIAFlow`, configured by the root `pyproject.toml`, and `tools/simulators`, configured by `tools/simulators/ruff.toml`. Both use the same rule set - `E4`, `E7`, `E9`, `F`, `I`, and `B` - but they target different Python versions, because the Slicer module runs inside Slicer's interpreter and the simulators run under the repository `.venv` (3.10).

The script also fails a target that matches zero files. `include` in `pyproject.toml` narrows Ruff's discovery, so a target it does not cover would otherwise exit 0 and report green having checked nothing. Ruff is the project's only static gate, so an empty run is a failure rather than a pass.

There is deliberately no static type checker. `docs/development/testing_strategy.md` records the measured reason: Slicer injects `slicer.app`, `slicer.util`, `slicer.mrmlScene`, and the VTK bindings into the module namespace at runtime, so a type checker either resolves nothing and silently checks nothing, or resolves the package and reports the injected attributes as errors.

## Separate Responsibilities

Keep UI, logic, I/O, tests, and reusable helpers separate when practical.

For Slicer scripted modules:

- Module entry point: metadata, startup setup, and public exports.
- Widget class: UI loading, user interaction, signal connections, and display updates.
- Logic class: computation, validation, MRML inspection, and reusable workflow logic.
- Test class: automated checks that exercise logic and important integration behavior.

Avoid putting algorithms directly in button callbacks.

## Naming

Use clear names instead of abbreviations.

Prefer:

- `inputVolumeNode`
- `segmentationNode`
- `targetPoint_RAS`
- `needleToTargetDistanceMm`
- `gaussianSigmaPixel`

Include units when relevant:

- `distanceMm`
- `angleDeg`
- `spacingMm`
- `timeSec`
- `indexPixel`

## Coordinate Systems

When working with medical images, transforms, points, or vectors, include the coordinate system when it matters.

Examples:

- `entryPoint_RAS`
- `targetPoint_RAS`
- `imagePlaneNormalVector_IJK`
- `imageToWorldTransform`
- `probeToReferenceTransform`

Avoid vague names such as `ProbeTransform`, `NeedleTrackerMatrix`, or `NeedleTipVector` when the coordinate system is significant.

## Avoid Magic Values

Use named constants, enums, or clear string values for non-obvious values.

All non-obvious numeric values should have a name or explanation, especially thresholds, units, coordinate-system assumptions, and image-processing parameters.

## Comments

Prefer self-documenting code. Use comments to explain:

- why something is done;
- medical-image or processing assumptions;
- coordinate-system assumptions;
- non-obvious constraints;
- safety checks.

Do not use comments as change logs or to restate obvious syntax.

Use TODO comments only when they are specific and actionable.

## Cohesion

Keep functions focused.

Rules of thumb:

- One function should do one thing.
- Avoid functions longer than one or two screens.
- Declare variables close to where they are used.
- Split unclear functions instead of creating vague containers such as `Manager` or `Controller`.
