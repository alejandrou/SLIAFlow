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
$moduleSourcePath = "extensions/SLIAFlow/SLIAFlow"

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

Write-Host "Target:     $moduleSourcePath"
Write-Host ""

Push-Location -LiteralPath $repositoryRoot
try {
    & $ruffPath check $moduleSourcePath
    $ruffExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($ruffExitCode -ne 0) {
    Write-Host ""
    Write-Host "ERROR: Ruff failed with exit code $ruffExitCode." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Python quality checks passed."
exit 0
