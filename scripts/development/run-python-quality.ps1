$ErrorActionPreference = "Stop"

# Ruff is the only static analysis gate for this project.
#
# A static type checker (Pyright) was evaluated and removed. Slicer injects
# `slicer.app`, `slicer.util`, `slicer.mrmlScene`, and the VTK bindings into the
# module namespace at runtime from C++, so a type checker either fails to
# resolve them - in which case every expression that touches Slicer becomes
# `Unknown` and is not checked at all - or resolves the package and then reports
# the injected attributes as errors. Neither outcome produces usable signal.
# See docs/development/testing_strategy.md for the recorded evidence.

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))

# Two targets, two Ruff configurations. The Slicer module is checked against the
# root `pyproject.toml`; the stand-in simulators are checked against
# `tools/simulators/ruff.toml`, which pins `py310` because they run under the
# repository `.venv` rather than inside Slicer's interpreter.
$analysisTargets = @(
    "extensions/SLIAFlow/SLIAFlow",
    "tools/simulators"
)

# Prefer the repository-local virtual environment over PATH. A PATH-only lookup
# reports the tool as missing on any shell where `.venv` was never activated,
# which previously made this script exit without checking anything.
$candidatePaths = @(
    (Join-Path $repositoryRoot ".venv\Scripts\ruff.exe"),
    (Join-Path $repositoryRoot ".venv\bin\ruff")
)

$ruffPath = $null
foreach ($candidate in $candidatePaths) {
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        $ruffPath = $candidate
        break
    }
}

if ($null -eq $ruffPath) {
    $pathCommand = Get-Command ruff -ErrorAction SilentlyContinue
    if ($null -ne $pathCommand) {
        $ruffPath = $pathCommand.Source
    }
}

if ($null -eq $ruffPath) {
    Write-Host "ERROR: Ruff was not found." -ForegroundColor Red
    Write-Host "Looked in the repository virtual environment and on PATH:"
    foreach ($candidate in $candidatePaths) {
        Write-Host "  $candidate"
    }
    Write-Host "  PATH"
    Write-Host ""
    Write-Host "Create the ignored root virtual environment and install Ruff into it:"
    Write-Host "  py -3 -m venv .venv"
    Write-Host "  .\.venv\Scripts\python.exe -m pip install ruff"
    Write-Host ""
    Write-Host "No tools were installed or modified."
    exit 1
}

Write-Host "== Ruff =="
Write-Host "Executable: $ruffPath"
& $ruffPath --version
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: '$ruffPath --version' failed with exit code $LASTEXITCODE." -ForegroundColor Red
    exit 1
}
Write-Host ""

$failureCount = 0

Push-Location -LiteralPath $repositoryRoot
try {
    foreach ($analysisTarget in $analysisTargets) {
        Write-Host "-- Target: $analysisTarget"

        # `include` in pyproject.toml narrows Ruff's discovery, so a target it
        # does not cover matches zero files, exits 0, and reports green having
        # checked nothing. Ruff is the project's only static gate, so an empty
        # run is treated as a failure rather than a pass.
        $discoveredFiles = & $ruffPath check --show-files $analysisTarget
        if ($LASTEXITCODE -ne 0) {
            Write-Host "ERROR: Ruff could not enumerate files under $analysisTarget." -ForegroundColor Red
            $failureCount++
            continue
        }

        $discoveredFileCount = @($discoveredFiles | Where-Object { $_ -and $_.Trim() }).Count
        Write-Host "   Files checked: $discoveredFileCount"
        if ($discoveredFileCount -eq 0) {
            Write-Host "ERROR: Ruff matched no files under $analysisTarget." -ForegroundColor Red
            Write-Host "       Widen 'include' in pyproject.toml or check the target path."
            $failureCount++
            continue
        }

        & $ruffPath check $analysisTarget
        if ($LASTEXITCODE -ne 0) {
            Write-Host "ERROR: Ruff reported findings in $analysisTarget (exit code $LASTEXITCODE)." -ForegroundColor Red
            $failureCount++
            continue
        }

        Write-Host "   OK"
        Write-Host ""
    }
}
finally {
    Pop-Location
}

if ($failureCount -ne 0) {
    Write-Host ""
    Write-Host "ERROR: $failureCount of $($analysisTargets.Count) target(s) failed." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Python quality checks passed."
exit 0
