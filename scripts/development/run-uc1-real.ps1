[CmdletBinding()]
param(
    # A recorded case folder, for example input\bin\bin\004-02. Read, never
    # written. A folder that is not a recorded case is refused.
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$DatasetFolder,

    # Staged UC1 build root. Defaults to build\uc1\UC1, where build-uc1.ps1
    # puts it.
    [string]$BuildRoot,

    [int]$Port,

    # Stop after this many sends. 0, the default, streams until Ctrl-C.
    [int]$Cycles,

    [double]$Interval,

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

# The same identification `envi.isRecordedDatabaseCase` makes, done here so the
# banner below never calls a folder recorded before it is known to be one.
$groundTruthHeader = Join-Path $DatasetFolder "gtMap.hdr"
if (-not (Test-Path -LiteralPath $groundTruthHeader -PathType Leaf) -or
    -not (Get-Content -LiteralPath $groundTruthHeader -Raw).Contains("HSI Human Brain Database")) {
    Stop-WithError "Refusing ${DatasetFolder}: its gtMap.hdr does not identify it as a case of the HSI Human Brain Database."
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
if ($ClassifyOnly) { $simulatorArguments += "--classify-only" }

Write-Host "== STRATUM genuine UC1 pipeline =="
Write-Host "Interpreter: $pythonPath"
Write-Host "Dataset:     $($simulatorArguments[3])"
Write-Host "Build root:  $($simulatorArguments[5])"
Write-Host ""
Write-Host "The pipeline is the vendored UC1 CUDA binary, compiled unmodified. The cube is a"
Write-Host "recorded case and only its acquisition is simulated, so the result is marked"
Write-Host "simulated on the wire. It is not a clinical result."
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
