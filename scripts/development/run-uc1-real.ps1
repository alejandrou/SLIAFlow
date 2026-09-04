[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$DatasetFolder,

    # Staged UC1 build root. Defaults to build\uc1\UC1, where build-uc1.ps1
    # puts it.
    [string]$BuildRoot,

    [int]$Port,

    # Stop after this many sends. 0, the default, streams until Ctrl-C.
    [int]$Cycles,

    [double]$Interval,

    # The marker is required by default. This switch is only for an explicitly
    # approved synthetic test folder whose header does not carry the marker.
    [switch]$ForceUnmarked,

    # Run the pipeline and report the recovered map without opening a server.
    [switch]$ClassifyOnly
)

$ErrorActionPreference = "Stop"

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$simulatorsPath = Join-Path $repositoryRoot "tools\simulators"
$pythonPath = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
$defaultBuildRoot = Join-Path $repositoryRoot "build\uc1\UC1"

function Stop-WithError {
    param([string]$Message)

    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    Stop-WithError "The repository virtual environment was not found at $pythonPath. Install tools\simulators\requirements.txt first."
}

if (-not (Test-Path -LiteralPath $DatasetFolder -PathType Container)) {
    Stop-WithError "The dataset folder does not exist: $DatasetFolder"
}

$resolvedBuildRoot = if ($PSBoundParameters.ContainsKey("BuildRoot")) { $BuildRoot } else { $defaultBuildRoot }
if (-not (Test-Path -LiteralPath $resolvedBuildRoot -PathType Container)) {
    Write-Host "ERROR: The staged UC1 build was not found at $resolvedBuildRoot." -ForegroundColor Red
    Write-Host ""
    Write-Host "Build it once with:"
    Write-Host "  .\scripts\development\build-uc1.ps1"
    exit 1
}

$simulatorArguments = @(
    "-m",
    "stratum_sim",
    "uc1-real",
    (Resolve-Path -LiteralPath $DatasetFolder).Path,
    "--build-root",
    (Resolve-Path -LiteralPath $resolvedBuildRoot).Path
)
if ($PSBoundParameters.ContainsKey("Port")) { $simulatorArguments += @("--port", $Port) }
if ($PSBoundParameters.ContainsKey("Cycles")) { $simulatorArguments += @("--cycles", $Cycles) }
if ($PSBoundParameters.ContainsKey("Interval")) { $simulatorArguments += @("--interval", $Interval) }
if ($ForceUnmarked) { $simulatorArguments += "--force-unmarked" }
if ($ClassifyOnly) { $simulatorArguments += "--classify-only" }

Write-Host "== STRATUM genuine UC1 pipeline =="
Write-Host "Interpreter: $pythonPath"
Write-Host "Dataset:     $($simulatorArguments[3])"
Write-Host "Build root:  $($simulatorArguments[5])"
Write-Host ""
Write-Host "The pipeline is the vendored UC1 CUDA binary, compiled unmodified. The scene is"
Write-Host "synthetic and non-clinical, so the result is marked simulated on the wire."
Write-Host "UC1 keeps one of the five contract maps, so this sends UC1_MV_CLASS alone."
Write-Host ""

# `stratum_sim` is a standalone package rather than an installed distribution,
# so its parent directory goes on PYTHONPATH for the duration of this call.
$previousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = if ([string]::IsNullOrEmpty($previousPythonPath)) {
    $simulatorsPath
} else {
    "$simulatorsPath;$previousPythonPath"
}

$simulatorExitCode = 1
Push-Location -LiteralPath $repositoryRoot
try {
    & $pythonPath @simulatorArguments
    $simulatorExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
    $env:PYTHONPATH = $previousPythonPath
}

if ($simulatorExitCode -ne 0) {
    Write-Host ""
    Write-Host "ERROR: The UC1 runner exited with code $simulatorExitCode." -ForegroundColor Red
    exit $simulatorExitCode
}

exit 0
