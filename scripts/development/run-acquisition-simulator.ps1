[CmdletBinding()]
param(
    # The recorded case to publish on each capture, for example 004-02. Required:
    # the stand-in reads one case of the HSI Human Brain Database and nothing else.
    [string]$Case,

    # Where recorded cases live. Defaults to input\bin\bin. Read, never written.
    [string]$DatasetRoot,

    # LiveView frame size. `demo` is the default because CRC over a larger frame
    # is what holds the achieved frame rate down. LiveView is the laptop camera,
    # which SLIAFlowLogic.startCamera also wants: on Windows the second open
    # fails, so the SLIAFlow live pane and this stand-in cannot both run.
    [ValidateSet("demo", "medium", "full")]
    [string]$Preset,

    [int]$Port,

    [double]$FrameRate,

    # Complete each capture at once instead of holding the 5-8 s delay.
    [switch]$InstantCapture
)

$ErrorActionPreference = "Stop"

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$simulatorsPath = Join-Path $repositoryRoot "tools\simulators"
$requirementsPath = Join-Path $simulatorsPath "requirements.txt"

function Stop-WithError {
    param([string]$Message)

    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

# The simulators reuse the repository-root virtual environment. There is
# deliberately no second one: the pins in tools/simulators/requirements.txt are
# development dependencies, and the Slicer-runtime requirements file stays
# OpenCV-only.
$pythonPath = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    Write-Host "ERROR: The repository virtual environment was not found at $pythonPath." -ForegroundColor Red
    Write-Host ""
    Write-Host "Create it and install the simulator dependencies:"
    Write-Host "  py -3 -m venv .venv"
    Write-Host "  .\.venv\Scripts\python.exe -m pip install -r tools\simulators\requirements.txt"
    Write-Host ""
    Write-Host "Note that crcmod 1.7 publishes no Windows wheel, so pip compiles it from"
    Write-Host "source. A working C toolchain is an environment prerequisite."
    exit 1
}

if (-not (Test-Path -LiteralPath $requirementsPath -PathType Leaf)) {
    Stop-WithError "The simulator requirements file is missing: $requirementsPath"
}

if ([string]::IsNullOrWhiteSpace($Case)) {
    Stop-WithError "The acquisition stand-in publishes one recorded case. Pass -Case, for example -Case 004-02."
}

$simulatorArguments = @("-m", "stratum_sim", "acquisition", "--case", $Case)
if ($PSBoundParameters.ContainsKey("DatasetRoot")) { $simulatorArguments += @("--recorded-root", $DatasetRoot) }
if ($PSBoundParameters.ContainsKey("Preset")) { $simulatorArguments += @("--preset", $Preset) }
if ($PSBoundParameters.ContainsKey("Port")) { $simulatorArguments += @("--port", $Port) }
if ($PSBoundParameters.ContainsKey("FrameRate")) { $simulatorArguments += @("--frame-rate", $FrameRate) }
if ($InstantCapture) { $simulatorArguments += "--instant-capture" }

Write-Host "== STRATUM acquisition stand-in =="
Write-Host "Interpreter: $pythonPath"
Write-Host "Package:     $simulatorsPath"
Write-Host ""

# `stratum_sim` is a standalone package rather than an installed distribution,
# so its parent directory goes on PYTHONPATH for the duration of this call.
$previousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = if ([string]::IsNullOrEmpty($previousPythonPath)) {
    $simulatorsPath
} else {
    "$simulatorsPath;$previousPythonPath"
}

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
    Write-Host "ERROR: The acquisition simulator exited with code $simulatorExitCode." -ForegroundColor Red
    exit $simulatorExitCode
}

exit 0
