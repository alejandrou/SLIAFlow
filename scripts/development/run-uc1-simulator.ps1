[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$DatasetFolder,

    [int]$Port,

    # Stop after this many complete five-map cycles. 0, the default, streams
    # until Ctrl-C.
    [int]$Cycles,

    [double]$Interval,

    # The marker is required by default. This switch is only for an explicitly
    # approved synthetic test folder whose header does not carry the marker.
    [switch]$ForceUnmarked,

    # Also send a human-readable UC1_SIM_NOTICE STRING message after connect.
    [switch]$SendNotice
)

$ErrorActionPreference = "Stop"

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$simulatorsPath = Join-Path $repositoryRoot "tools\simulators"
$pythonPath = Join-Path $repositoryRoot ".venv\Scripts\python.exe"

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

$simulatorArguments = @(
    "-m",
    "stratum_sim",
    "uc1",
    (Resolve-Path -LiteralPath $DatasetFolder).Path
)
if ($PSBoundParameters.ContainsKey("Port")) { $simulatorArguments += @("--port", $Port) }
if ($PSBoundParameters.ContainsKey("Cycles")) { $simulatorArguments += @("--cycles", $Cycles) }
if ($PSBoundParameters.ContainsKey("Interval")) { $simulatorArguments += @("--interval", $Interval) }
if ($ForceUnmarked) { $simulatorArguments += "--force-unmarked" }
if ($SendNotice) { $simulatorArguments += "--send-notice" }

Write-Host "== STRATUM UC1 arithmetic stand-in =="
Write-Host "Interpreter: $pythonPath"
Write-Host "Dataset:     $($simulatorArguments[3])"
Write-Host ""
Write-Host "This output is simulated, non-clinical arithmetic and is not a classifier."
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
    Write-Host "ERROR: The UC1 simulator exited with code $simulatorExitCode." -ForegroundColor Red
    exit $simulatorExitCode
}

exit 0
