[CmdletBinding()]
param(
    # Which producer takes port 18945 at startup. The session swaps between the
    # two with the `s` key, which is manual step 3.
    [ValidateSet("genuine", "standin")]
    [string]$MapProducer = "genuine",

    # Reuse an existing dataset instead of writing a new one. The overwrite
    # interlock still applies, so a folder that is not a simulated dataset is
    # refused by the acquisition stand-in itself.
    [string]$DatasetFolder,

    [ValidateSet("demo", "medium", "full")]
    [string]$Preset = "demo",

    # Build runs the compiled launcher under build\SLIAFlow. Source runs the
    # configured Slicer with extensions\SLIAFlow\SLIAFlow on the module path,
    # which is what to use while editing the module.
    [ValidateSet("Build", "Source")]
    [string]$SlicerFrom = "Build",

    # Bring the producers up and leave Slicer to be started by hand.
    [switch]$NoSlicer,

    # End the session automatically after this many seconds. 0, the default,
    # runs until q or Ctrl-C. Use it with -NoSlicer to check the rig comes up
    # and tears down cleanly without sitting through a session.
    [int]$RunSeconds = 0,

    # Stop whatever already holds 18944 or 18945 (and 18947 and 18950 with -Case)
    # instead of refusing to start.
    # Off by default: a stray producer from an earlier run is indistinguishable
    # from a healthy session in the panel, and that is what forced a whole run
    # to be discarded the first time this procedure was followed.
    [switch]$StopStrays,

    # Run a recorded case of the public HSI Human Brain Database instead of
    # writing a phantom dataset, for example -Case 004-02. The acquisition
    # stand-in then streams the laptop camera on LiveView, publishes the case's
    # cube on each capture (the c key), and writes nothing. The map producer
    # starts on the case once the first capture reports READY. Only one process
    # can hold the camera, so leave SLIAFlow's own camera path off.
    [string]$Case,

    # Where recorded cases live, for -Case. Defaults to input\bin\bin. Read,
    # never written.
    [string]$DatasetRoot,

    # Complete each capture at once instead of holding the 5-8 s delay.
    [switch]$InstantCapture
)

$ErrorActionPreference = "Stop"

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$simulatorsPath = Join-Path $repositoryRoot "tools\simulators"
$pythonPath = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
$configPath = Join-Path $repositoryRoot "config\local.json"
$moduleSourcePath = Join-Path $repositoryRoot "extensions\SLIAFlow\SLIAFlow"
$launcherPath = Join-Path $repositoryRoot "build\SLIAFlow\SlicerWithSLIAFlow.exe"
$uc1BuildRoot = Join-Path $repositoryRoot "build\uc1\UC1"

$liveViewPort = 18944
$mapPort = 18945
$cubePort = 18947
$controlPort = 18950
# Reserved for producers that do not exist yet. Nothing in this rig binds them.
$reservedPorts = @(18948, 18949)

$recordedSession = -not [string]::IsNullOrWhiteSpace($Case)
$sessionPorts = if ($recordedSession) { @($liveViewPort, $mapPort, $cubePort, $controlPort) } else { @($liveViewPort, $mapPort) }

$sessionStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$sessionRoot = Join-Path $repositoryRoot "workspace\simulators\sessions\session-$sessionStamp"

# One record per running producer. `Log` is the file its stdout is tailed from,
# `Reader` the open handle the tail loop reads through.
$script:producers = @{}
$script:slicerProcess = $null
$script:slicerExitReported = $false
$script:datasetFolder = $null
$script:lastLinkReport = ""
$script:keyboardUsable = $true
$script:mapProducerStarted = $false
$script:captureReadySeen = $false
$script:captureCount = 0

function Write-Stage {
    param([string]$Text)

    Write-Host ""
    Write-Host "== $Text " -ForegroundColor Cyan -NoNewline
    Write-Host ("=" * [Math]::Max(1, 74 - $Text.Length)) -ForegroundColor DarkCyan
}

function Write-Tagged {
    param([string]$Tag, [string]$Text, [string]$Color = "Gray")

    Write-Host ("{0,-10}" -f "[$Tag]") -ForegroundColor $Color -NoNewline
    Write-Host " $Text"
}

function Stop-WithError {
    param([string]$Message)

    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

function Get-ListenerProcessIds {
    param([int]$Port)

    try {
        $connections = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop
        return @($connections | ForEach-Object { $_.OwningProcess } | Sort-Object -Unique)
    }
    catch [Microsoft.PowerShell.Cmdletization.Cim.CimJobException] {
        # No listener on that port is an error from this cmdlet, not an empty
        # result, so an empty list is the correct answer here.
        return @()
    }
    catch {
        # Get-NetTCPConnection is absent on some Windows editions. netstat is
        # always present, and its last column is the owning process id.
        $rows = netstat -ano -p TCP | Select-String -Pattern (":" + $Port + "\s.*LISTENING")
        return @($rows | ForEach-Object { ($_.ToString().Trim() -split "\s+")[-1] } | Sort-Object -Unique)
    }
}

function Get-EstablishedCount {
    param([int]$Port)

    try {
        return @(Get-NetTCPConnection -State Established -LocalPort $Port -ErrorAction Stop).Count
    }
    catch [Microsoft.PowerShell.Cmdletization.Cim.CimJobException] {
        return 0
    }
    catch {
        return @(netstat -ano -p TCP | Select-String -Pattern (":" + $Port + "\s.*ESTABLISHED")).Count
    }
}

function Assert-PortAvailable {
    param([int]$Port, [string]$Purpose)

    $owners = @(Get-ListenerProcessIds -Port $Port | Where-Object { $_ -and $_ -ne 0 })
    if ($owners.Count -eq 0) {
        Write-Tagged "check" "Port $Port is free ($Purpose)." "Green"
        return
    }

    foreach ($processId in $owners) {
        $owner = Get-Process -Id $processId -ErrorAction SilentlyContinue
        $name = if ($owner) { $owner.ProcessName } else { "unknown" }
        Write-Tagged "check" "Port $Port is already held by PID $processId ($name)." "Yellow"
    }

    if (-not $StopStrays) {
        Write-Host ""
        Stop-WithError ("Port $Port is not free. A stray producer left over from an earlier run " +
            "looks exactly like a healthy session in the SLIAFlow panel, so this script will not " +
            "start on top of one. Stop the process listed above, or re-run with -StopStrays.")
    }

    foreach ($processId in $owners) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        Write-Tagged "check" "Stopped PID $processId." "Yellow"
    }
    Start-Sleep -Milliseconds 500
}

function Get-ClientProcessIds {
    param([int]$Port)

    # Connections *to* the port, i.e. processes dialling it as a client. A
    # listener check cannot see these: a Slicer left over from an earlier
    # session holds no port of its own, it only keeps retrying ours.
    try {
        $connections = Get-NetTCPConnection -RemotePort $Port -ErrorAction Stop
        return @($connections | ForEach-Object { $_.OwningProcess } | Sort-Object -Unique)
    }
    catch [Microsoft.PowerShell.Cmdletization.Cim.CimJobException] {
        return @()
    }
    catch {
        $rows = netstat -ano -p TCP | Select-String -Pattern ("\s127\.0\.0\.1:" + $Port + "\s")
        return @($rows | ForEach-Object { ($_.ToString().Trim() -split "\s+")[-1] } | Sort-Object -Unique)
    }
}

function Assert-NoStaleClients {
    param([int[]]$Ports)

    $owners = @()
    foreach ($port in $Ports) {
        $owners += @(Get-ClientProcessIds -Port $port | Where-Object { $_ -and $_ -ne 0 })
    }
    $owners = @($owners | Sort-Object -Unique)

    if ($owners.Count -eq 0) {
        Write-Tagged "check" "Nothing is already dialling $($Ports -join ', '). No stale client." "Green"
        return
    }

    foreach ($processId in $owners) {
        $owner = Get-Process -Id $processId -ErrorAction SilentlyContinue
        $name = if ($owner) { $owner.ProcessName } else { "unknown" }
        Write-Tagged "check" "PID $processId ($name) is already dialling the session ports." "Yellow"
    }

    if (-not $StopStrays) {
        Write-Host ""
        Stop-WithError ("A client from an earlier session is still retrying these ports. " +
            "pyigtl serves one client at a time, so that process will take both links the " +
            "moment the producers come up, and the Slicer you are about to start will show " +
            "Connected with empty panes for as long as the old one lives. Close the Slicer " +
            "listed above, or re-run with -StopStrays.")
    }

    foreach ($processId in $owners) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        Write-Tagged "check" "Stopped PID $processId." "Yellow"
    }
    Start-Sleep -Milliseconds 500
}

function Start-Producer {
    param([string]$Name, [string[]]$Arguments, [string]$Color)

    $logPath = Join-Path $sessionRoot "$Name.log"
    Set-Content -LiteralPath $logPath -Value "" -NoNewline

    $process = Start-Process -FilePath $pythonPath -ArgumentList $Arguments `
        -WorkingDirectory $repositoryRoot -NoNewWindow -PassThru `
        -RedirectStandardOutput $logPath -RedirectStandardError "$logPath.err"
    # Touching the handle keeps the exit code readable after the process ends.
    # Without it `ExitCode` can come back empty for a process that has exited,
    # and a trigger client's exit code is how its outcome is reported.
    $null = $process.Handle

    $stream = New-Object System.IO.FileStream(
        $logPath,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::ReadWrite)

    $script:producers[$Name] = [pscustomobject]@{
        Name    = $Name
        Process = $process
        Log     = $logPath
        Reader  = New-Object System.IO.StreamReader($stream)
        Color   = $Color
    }

    Write-Tagged "session" "Started $Name as PID $($process.Id)." "Cyan"
}

function Show-ProducerOutput {
    # Every producer runs with PYTHONUNBUFFERED set. Without it a redirected
    # Python stdout is block-buffered, and the last thing a producer said is
    # lost when the process is stopped - which is how the acquisition rate line
    # went missing from the first recorded session.
    foreach ($producer in @($script:producers.Values)) {
        while ($true) {
            $line = $producer.Reader.ReadLine()
            if ($null -eq $line) { break }
            if ($line.Trim().Length -eq 0) { continue }
            Write-Tagged $producer.Name $line $producer.Color

            # The stand-in says when a capture is complete. The map producer is
            # started from the session loop rather than from here, because
            # starting it waits on its port and that wait tails output too.
            if ($recordedSession -and $producer.Name -eq "acq" -and $line -match "complete: READY ") {
                $script:captureReadySeen = $true
            }
        }
    }
}

function Stop-Producer {
    param([string]$Name)

    $producer = $script:producers[$Name]
    if (-not $producer) { return }

    if (-not $producer.Process.HasExited) {
        Stop-Process -Id $producer.Process.Id -Force -ErrorAction SilentlyContinue
        $producer.Process.WaitForExit(5000) | Out-Null
    }
    Show-ProducerOutput
    $producer.Reader.Dispose()
    $script:producers.Remove($Name)
    Write-Tagged "session" "Stopped $Name." "Cyan"
}

function Show-LinkState {
    param([switch]$Always)

    $liveClients = Get-EstablishedCount -Port $liveViewPort
    $mapClients = Get-EstablishedCount -Port $mapPort
    $mapName = if ($script:producers.ContainsKey("uc1-genuine")) { "genuine UC1 pipeline" }
    elseif ($script:producers.ContainsKey("uc1-standin")) { "arithmetic stand-in" }
    elseif ($recordedSession -and -not $script:mapProducerStarted) { "waiting for the first capture" }
    else { "no producer" }
    $slicerState = if ($script:slicerProcess -and -not $script:slicerProcess.HasExited) { "running" } else { "not running" }

    $report = "live ${liveViewPort}: $liveClients client(s) | map ${mapPort}: $mapClients client(s), $mapName"
    if ($recordedSession) {
        $report += " | cube ${cubePort}: $(Get-EstablishedCount -Port $cubePort) client(s)"
    }
    $report += " | Slicer: $slicerState"
    if (-not $Always -and $report -eq $script:lastLinkReport) { return }

    $script:lastLinkReport = $report
    $colour = if ($liveClients -gt 0 -and $mapClients -gt 0) { "Green" } else { "Yellow" }
    Write-Tagged "status" $report $colour

    # A producer serves one client at a time. A second one completes its TCP
    # handshake in the accept backlog, so it reports itself connected and then
    # receives nothing until the first client lets go. Empty panes under a
    # Connected label look like a broken module and are not one, so say it here.
    if ($liveClients -gt 1 -or $mapClients -gt 1) {
        Write-Tagged "status" ("More than one client is attached. Only the first one " +
            "receives anything; the others show Connected and stay empty. Close the " +
            "other Slicer.") "Red"
    }
}

function Wait-ForListener {
    param([int]$Port, [string]$What, [int]$TimeoutSec = 300)

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        Show-ProducerOutput

        foreach ($producer in @($script:producers.Values)) {
            # A trigger client is meant to exit, so its exit is not a producer failing.
            if ($producer.Name -like "capture-*") { continue }
            if ($producer.Process.HasExited) {
                Show-ProducerOutput
                Get-Content -LiteralPath ($producer.Log + ".err") -ErrorAction SilentlyContinue |
                    ForEach-Object { Write-Tagged $producer.Name $_ "Red" }
                Stop-WithError "$($producer.Name) exited with code $($producer.Process.ExitCode) before its port was open."
            }
        }

        if (@(Get-ListenerProcessIds -Port $Port | Where-Object { $_ -and $_ -ne 0 }).Count -gt 0) {
            Write-Tagged "session" "$What is listening on 127.0.0.1:$Port." "Green"
            return $true
        }
        Start-Sleep -Milliseconds 250
    }

    Stop-WithError "$What did not open port $Port within $TimeoutSec seconds."
}

function Start-MapProducer {
    param([string]$Which)

    if ($Which -eq "genuine") {
        Write-Tagged "session" "The genuine pipeline classifies the cube on the GPU before it opens the port, so this takes a moment." "DarkGray"
        Start-Producer -Name "uc1-genuine" -Color "Magenta" -Arguments @(
            "-m", "stratum_sim", "uc1-real", $script:datasetFolder,
            "--build-root", $uc1BuildRoot, "--port", "$mapPort")
        Wait-ForListener -Port $mapPort -What "The genuine UC1 pipeline" | Out-Null
    }
    else {
        Start-Producer -Name "uc1-standin" -Color "DarkYellow" -Arguments @(
            "-m", "stratum_sim", "uc1", $script:datasetFolder,
            "--port", "$mapPort", "--cycles", "0", "--send-notice")
        Wait-ForListener -Port $mapPort -What "The arithmetic stand-in" | Out-Null
    }
    $script:mapProducerStarted = $true
}

function Invoke-ProducerSwap {
    Write-Stage "Manual step 3 - the producer swap on port $mapPort"
    Write-Tagged "action" "Change nothing in Slicer. No Disconnect, no restart, no change of result map." "Yellow"

    $wasGenuine = $script:producers.ContainsKey("uc1-genuine")
    if ($wasGenuine) { Stop-Producer -Name "uc1-genuine" } else { Stop-Producer -Name "uc1-standin" }

    Write-Tagged "session" "Nothing is serving port $mapPort now. Watch what the UC1 link row says for the next few seconds." "Cyan"
    for ($second = 0; $second -lt 6; $second++) {
        Show-ProducerOutput
        Show-LinkState -Always
        Start-Sleep -Seconds 1
    }

    if ($wasGenuine) {
        Start-MapProducer -Which "standin"
        Write-Tagged "expect" "Banner should change to: SIMULATED - NOT A GENUINE UC1 RESULT" "Cyan"
        Write-Tagged "expect" "                          arithmetic stand-in, not a classifier" "Cyan"
    }
    else {
        Start-MapProducer -Which "genuine"
        Write-Tagged "expect" "Banner should change to: SIMULATED INPUT - REAL UC1 PIPELINE, NOT A CLINICAL RESULT" "Cyan"
        Write-Tagged "expect" "                          real UC1 pipeline, synthetic tissue phantom" "Cyan"
    }
}

function Start-CaptureTrigger {
    if (-not $recordedSession) {
        Write-Tagged "session" "c triggers a capture only in a recorded session. Start with -Case, for example -Case 004-02." "Yellow"
        return
    }

    # One short-lived client per press, leaving as soon as the stand-in has
    # answered. pyigtl serves one client at a time, so a client that waited for
    # READY would hold the control port for the whole delay: a second press
    # would then be read only after the first capture, and start a new one
    # instead of being answered IGNORED.
    $script:captureCount++
    Write-Tagged "session" "Capture trigger $($script:captureCount): sending CAPTURE to 127.0.0.1:$controlPort." "Cyan"
    Start-Producer -Name "capture-$($script:captureCount)" -Color "Green" -Arguments @(
        "-m", "stratum_sim", "capture", "--port", "$controlPort", "--no-wait", "--timeout", "15")
}

function Show-ReservedPorts {
    $held = @()
    foreach ($port in $reservedPorts) {
        $owners = @(Get-ListenerProcessIds -Port $port | Where-Object { $_ -and $_ -ne 0 })
        if ($owners.Count -gt 0) { $held += "$port (PID $($owners -join ', '))" }
    }
    if ($held.Count -eq 0) {
        Write-Tagged "check" "Nothing is listening on the reserved ports $($reservedPorts -join ' or ')." "Green"
    }
    else {
        Write-Tagged "check" "A reserved port is held: $($held -join '; '). Nothing in this rig may bind it; record that as a finding." "Red"
    }
}

function Invoke-RateMeasurement {
    Write-Stage "Manual step 2 - the delivered LiveView frame rate"
    Write-Tagged "session" "pyigtl serves one client at a time, so this measures nothing while SLIAFlow holds the link." "Cyan"
    Write-Tagged "action" "Press Disconnect on the Acquisition link row in Slicer, then press Enter here." "Yellow"
    [void](Read-Host)

    & $pythonPath (Join-Path $simulatorsPath "tests\liveview_client.py") --port $liveViewPort
    Write-Tagged "action" "Press Connect on the Acquisition link row again and confirm the live pane returns." "Yellow"
}

function Start-Slicer {
    if ($script:slicerProcess -and -not $script:slicerProcess.HasExited) {
        Write-Tagged "session" "Slicer is already running as PID $($script:slicerProcess.Id)." "Yellow"
        return
    }

    # A Slicer that will not start is not a reason to tear the session down: the
    # producers are up and working, and the l key can try again once whatever
    # was wrong is fixed. So everything here reports and returns.
    if ($SlicerFrom -eq "Build") {
        if (-not (Test-Path -LiteralPath $launcherPath -PathType Leaf)) {
            Write-Tagged "session" "The SLIAFlow launcher is missing: $launcherPath. Build it with .\scripts\development\build-sliaflow.ps1, or restart with -SlicerFrom Source." "Red"
            return
        }
        $executable = $launcherPath
        $slicerArguments = @()
    }
    else {
        if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
            Write-Tagged "session" "config\local.json is missing. Copy config\local.example.json and set slicerExecutable." "Red"
            return
        }
        $localConfig = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
        $executable = $localConfig.slicerExecutable
        if ([string]::IsNullOrWhiteSpace($executable)) {
            Write-Tagged "session" "config\local.json has no slicerExecutable." "Red"
            return
        }
        if (-not [System.IO.Path]::IsPathRooted($executable)) {
            $executable = [System.IO.Path]::GetFullPath((Join-Path $repositoryRoot $executable))
        }
        $slicerArguments = @("--additional-module-paths", $moduleSourcePath)
    }

    # The compiled launcher takes no arguments, and Start-Process rejects an
    # empty -ArgumentList rather than ignoring it, so the parameter is only
    # supplied when there is something to pass.
    $startArguments = @{ FilePath = $executable; PassThru = $true }
    if ($slicerArguments.Count -gt 0) { $startArguments["ArgumentList"] = $slicerArguments }

    try {
        $script:slicerProcess = Start-Process @startArguments
    }
    catch {
        Write-Tagged "session" "Slicer did not start: $($_.Exception.Message)" "Red"
        Write-Tagged "session" "The producers are still up. Fix it and press l to try again." "Yellow"
        return
    }

    $script:slicerExitReported = $false
    Write-Tagged "session" "Started Slicer as PID $($script:slicerProcess.Id): $executable" "Cyan"
    Write-Tagged "session" "This session starts Slicer only here and on the l key. A window that opens or closes at any other time is not from this script." "DarkGray"
}

function Read-SessionKey {
    # A host with redirected input has no console keyboard and throws here, so
    # the keys are switched off once rather than throwing every 150 ms. The
    # session still runs; it is just driven by Ctrl-C instead.
    if (-not $script:keyboardUsable) { return $null }

    try {
        if (-not [Console]::KeyAvailable) { return $null }
        return [Console]::ReadKey($true).KeyChar
    }
    catch {
        $script:keyboardUsable = $false
        Write-Tagged "session" "This host has no interactive keyboard, so the session keys are off. Stop the session with Ctrl-C." "Yellow"
        return $null
    }
}

function Show-Help {
    Write-Stage "Keys"
    if ($recordedSession) {
        Write-Host "  c   trigger a capture of case $Case on port $controlPort"
    }
    else {
        Write-Host "  s   swap the map producer on port $mapPort        (manual step 3)"
    }
    Write-Host "  m   measure the delivered LiveView frame rate  (manual step 2)"
    Write-Host "  l   start Slicer again after closing it       (manual step 6)"
    Write-Host "  n   show what is listening on $($sessionPorts -join ', ')"
    Write-Host "  d   print the dataset folder and the log paths"
    Write-Host "  ?   this list"
    Write-Host "  q   stop both producers and end the session"
    Write-Host ""
}

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

Write-Stage "STRATUM end-to-end session"
if ($recordedSession) {
    Write-Host "Nothing here is a clinical result. The cube is recorded case $Case of the public," -ForegroundColor DarkGray
    Write-Host "anonymized HSI Human Brain Database, read where it lies and never written; only" -ForegroundColor DarkGray
    Write-Host "the acquisition is simulated. Quick start: docs\development\pipeline_test_quickstart.md" -ForegroundColor DarkGray
}
else {
    Write-Host "Nothing here is a clinical result: the scene is a synthetic phantom and the" -ForegroundColor DarkGray
    Write-Host "pipeline is run over invented data. Procedure and evidence tables:" -ForegroundColor DarkGray
    Write-Host "docs\development\end_to_end_verification.md" -ForegroundColor DarkGray
}

foreach ($recordedOnly in @("DatasetRoot", "InstantCapture")) {
    if (-not $recordedSession -and $PSBoundParameters.ContainsKey($recordedOnly)) {
        Stop-WithError "-$recordedOnly is only used with -Case."
    }
}
if ($recordedSession -and $MapProducer -ne "genuine") {
    Stop-WithError ("-MapProducer $MapProducer cannot run on a recorded case: the arithmetic stand-in's " +
        "marker interlock accepts only datasets this simulator wrote. A recorded session uses the genuine pipeline.")
}
if ($recordedSession -and $DatasetFolder) {
    Stop-WithError "-DatasetFolder names a dataset this simulator wrote and -Case names a recorded one. Pass one of them."
}

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    Stop-WithError "The repository virtual environment was not found at $pythonPath. Create it and install tools\simulators\requirements.txt."
}
Write-Tagged "check" "Interpreter: $pythonPath" "Green"

if ($MapProducer -eq "genuine") {
    if (-not (Test-Path -LiteralPath $uc1BuildRoot -PathType Container)) {
        Stop-WithError "The staged UC1 build was not found at $uc1BuildRoot. Build it with .\scripts\development\build-uc1.ps1, or start with -MapProducer standin."
    }
    Write-Tagged "check" "UC1 build: $uc1BuildRoot" "Green"
}

Assert-PortAvailable -Port $liveViewPort -Purpose "LiveView"
Assert-PortAvailable -Port $mapPort -Purpose "UC1 maps"
if ($recordedSession) {
    Assert-PortAvailable -Port $cubePort -Purpose "HSCube"
    Assert-PortAvailable -Port $controlPort -Purpose "capture control"
}
Assert-NoStaleClients -Ports $sessionPorts

New-Item -ItemType Directory -Path $sessionRoot -Force | Out-Null
Write-Tagged "check" "Session folder: $sessionRoot" "Green"

if ($recordedSession) {
    if ($DatasetRoot) {
        if (-not (Test-Path -LiteralPath $DatasetRoot -PathType Container)) {
            Stop-WithError "The dataset root does not exist: $DatasetRoot"
        }
        $recordedRoot = (Resolve-Path -LiteralPath $DatasetRoot).Path
    }
    else {
        $recordedRoot = Join-Path $repositoryRoot "input\bin\bin"
    }
    $script:datasetFolder = Join-Path $recordedRoot $Case
    if (-not (Test-Path -LiteralPath $script:datasetFolder -PathType Container)) {
        Stop-WithError "There is no recorded case folder $($script:datasetFolder). Check -Case and -DatasetRoot."
    }
}
elseif ($DatasetFolder) {
    if (-not (Test-Path -LiteralPath $DatasetFolder -PathType Container)) {
        Stop-WithError "The dataset folder does not exist: $DatasetFolder"
    }
    $script:datasetFolder = (Resolve-Path -LiteralPath $DatasetFolder).Path
}
else {
    $script:datasetFolder = Join-Path $sessionRoot "dataset"
}
$datasetNote = if ($recordedSession) { " (recorded case, read-only)" } else { "" }
Write-Tagged "check" "Dataset: $($script:datasetFolder)$datasetNote" "Green"

# `stratum_sim` is a standalone package rather than an installed distribution,
# so its parent goes on PYTHONPATH for the duration of this session.
$previousPythonPath = $env:PYTHONPATH
$previousUnbuffered = $env:PYTHONUNBUFFERED
$env:PYTHONPATH = if ([string]::IsNullOrEmpty($previousPythonPath)) { $simulatorsPath } else { "$simulatorsPath;$previousPythonPath" }
$env:PYTHONUNBUFFERED = "1"

try {
    # -----------------------------------------------------------------------
    # Startup, in the order the procedure fixes
    # -----------------------------------------------------------------------

    if ($recordedSession) {
        Write-Stage "Acquisition stand-in on 127.0.0.1:$liveViewPort, $cubePort and $controlPort"
        Write-Tagged "session" "It reads recorded case $Case and writes nothing. LiveView comes from the laptop camera; the cube is published on each capture." "DarkGray"
        $acquisitionArguments = @(
            "-m", "stratum_sim", "acquisition", "--scene-mode", "recorded",
            "--case", $Case, "--recorded-root", $recordedRoot, "--frame-source", "webcam",
            "--preset", $Preset, "--port", "$liveViewPort",
            "--cube-port", "$cubePort", "--control-port", "$controlPort")
        if ($InstantCapture) { $acquisitionArguments += "--instant-capture" }
        Start-Producer -Name "acq" -Color "Blue" -Arguments $acquisitionArguments
        Wait-ForListener -Port $liveViewPort -What "The acquisition stand-in's LiveView" | Out-Null
        Wait-ForListener -Port $cubePort -What "The HSCube channel" | Out-Null
        Wait-ForListener -Port $controlPort -What "The capture control channel" | Out-Null
        Show-ReservedPorts

        Write-Stage "Map producer on 127.0.0.1:$mapPort"
        Write-Tagged "session" "Not started yet. It starts on the case when the first capture reports READY: camera, capture, cube, UC1. Press c." "Yellow"
    }
    else {
        Write-Stage "Acquisition stand-in on 127.0.0.1:$liveViewPort"
        Write-Tagged "session" "It writes the ENVI dataset first and serves LiveView afterwards. The dataset write is the slow part." "DarkGray"
        Start-Producer -Name "acq" -Color "Blue" -Arguments @(
            "-m", "stratum_sim", "acquisition", "--preset", $Preset,
            "--port", "$liveViewPort", "--dataset-folder", $script:datasetFolder)
        Wait-ForListener -Port $liveViewPort -What "The acquisition stand-in" | Out-Null

        Write-Stage "Map producer on 127.0.0.1:$mapPort"
        Start-MapProducer -Which $MapProducer
    }

    if ($NoSlicer) {
        Write-Tagged "session" "Slicer was not started (-NoSlicer). Press l when you want it." "Yellow"
    }
    else {
        Write-Stage "Slicer"
        Start-Slicer
    }

    Write-Stage "In Slicer"
    Write-Host "  1. Open SLIAFlow from the STRATUM category."
    Write-Host "  2. Live source -> AcquisitionSystemApp LiveView, then Connect on the Acquisition link row."
    Write-Host "  3. Result map -> majorityVotingMap, then Connect on the UC1 link row."
    if ($recordedSession) {
        Write-Host "     In a recorded session nothing serves the UC1 link until the first capture is READY. Press c here first." -ForegroundColor Yellow
    }
    Write-Host "  4. Tick Demo mode. The red banner appears over the result pane."
    Write-Host ""
    Write-Host "  The status line below turns green once Slicer has connected to both ports." -ForegroundColor DarkGray
    Show-Help
    Show-LinkState -Always

    # -----------------------------------------------------------------------
    # The session loop: tail both producers, report the links, take keys
    # -----------------------------------------------------------------------

    $lastHeartbeat = Get-Date
    $sessionDeadline = if ($RunSeconds -gt 0) { (Get-Date).AddSeconds($RunSeconds) } else { $null }
    if ($sessionDeadline) {
        Write-Tagged "session" "This session ends by itself in $RunSeconds seconds (-RunSeconds)." "Yellow"
    }

    $running = $true
    while ($running) {
        if ($sessionDeadline -and (Get-Date) -gt $sessionDeadline) {
            Write-Tagged "session" "The -RunSeconds window is over." "Yellow"
            break
        }

        Show-ProducerOutput

        if ((Get-Date) -gt $lastHeartbeat.AddSeconds(2)) {
            Show-LinkState
            $lastHeartbeat = Get-Date
        }

        foreach ($producer in @($script:producers.Values)) {
            if ($producer.Process.HasExited) {
                Show-ProducerOutput
                if ($producer.Name -like "capture-*") {
                    $colour = if ($producer.Process.ExitCode -eq 0) { "DarkGray" } else { "Yellow" }
                    Write-Tagged "session" "$($producer.Name) finished with exit code $($producer.Process.ExitCode) (0 started, 2 ignored, 1 failed)." $colour
                }
                else {
                    Write-Tagged "session" "$($producer.Name) exited on its own with code $($producer.Process.ExitCode). Its log is $($producer.Log)." "Red"
                }
                $producer.Reader.Dispose()
                $script:producers.Remove($producer.Name)
            }
        }

        if ($recordedSession -and $script:captureReadySeen -and -not $script:mapProducerStarted) {
            Write-Stage "Map producer on 127.0.0.1:$mapPort"
            Write-Tagged "session" "The first capture is ready. Starting the genuine UC1 pipeline on $($script:datasetFolder)." "Cyan"
            Start-MapProducer -Which "genuine"
        }

        if ($script:slicerProcess -and $script:slicerProcess.HasExited -and -not $script:slicerExitReported) {
            $script:slicerExitReported = $true
            Write-Tagged "session" "Slicer exited. Both producers are still up, which is manual step 6. Press l to reconnect a fresh session." "Cyan"
            Write-Tagged "expect" "A pyigtl traceback and 'Error while sending data' from a producer here is the expected shutdown path, not a defect." "Cyan"
            Show-LinkState -Always
        }

        $pressedKey = Read-SessionKey
        if ($null -ne $pressedKey) {
            switch ($pressedKey) {
                "s" {
                    if ($recordedSession) {
                        Write-Tagged "session" "No swap in a recorded session: the arithmetic stand-in refuses a recorded case, so there is nothing to swap to." "Yellow"
                    }
                    else { Invoke-ProducerSwap }
                }
                "c" { Start-CaptureTrigger }
                "m" { Invoke-RateMeasurement }
                "l" { Start-Slicer }
                "n" {
                    netstat -ano -p TCP |
                        Select-String -Pattern (($sessionPorts + $reservedPorts | ForEach-Object { ":$_\s" }) -join "|") |
                        ForEach-Object { Write-Tagged "netstat" $_.ToString().Trim() "Gray" }
                }
                "d" {
                    Write-Tagged "session" "Dataset: $($script:datasetFolder)" "Cyan"
                    foreach ($producer in @($script:producers.Values)) {
                        Write-Tagged "session" "$($producer.Name) log: $($producer.Log)" "Cyan"
                    }
                }
                "?" { Show-Help }
                "q" { $running = $false }
                default { Write-Tagged "session" "Unknown key. Press ? for the list." "Yellow" }
            }
        }

        Start-Sleep -Milliseconds 150
    }
}
finally {
    Write-Stage "Shutdown"
    if ($recordedSession) { Show-ReservedPorts }
    foreach ($name in @($script:producers.Keys)) { Stop-Producer -Name $name }

    $remaining = @()
    foreach ($port in $sessionPorts) {
        $owners = @(Get-ListenerProcessIds -Port $port | Where-Object { $_ -and $_ -ne 0 })
        if ($owners.Count -gt 0) { $remaining += "$port (PID $($owners -join ', '))" }
    }
    if ($remaining.Count -eq 0) {
        $portList = if ($recordedSession) { $sessionPorts -join ", " } else { "$liveViewPort or $mapPort" }
        Write-Tagged "check" "Nothing is listening on $portList. No socket was left held." "Green"
    }
    else {
        Write-Tagged "check" "Still listening: $($remaining -join '; '). Record that in the failures table." "Red"
    }

    if ($script:slicerProcess -and -not $script:slicerProcess.HasExited) {
        Write-Tagged "session" "Slicer (PID $($script:slicerProcess.Id)) is still running and has been left alone." "Yellow"
    }

    Write-Tagged "session" "Logs and dataset: $sessionRoot" "Cyan"
    Write-Tagged "session" "Write the measurements into docs\development\end_to_end_verification.md." "Cyan"

    $env:PYTHONPATH = $previousPythonPath
    $env:PYTHONUNBUFFERED = $previousUnbuffered
}
