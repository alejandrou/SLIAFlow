[CmdletBinding()]
param(
    # Source runs the tests against the working tree under extensions/.
    # Build runs them against the compiled copy under build/SLIAFlow/.
    [ValidateSet("Source", "Build")]
    [string]$Target = "Source",

    # Keep the main window for layout-manager and renderer coverage.
    [switch]$Headful,

    # Run only the SLIAFlowTest methods whose names contain one of these
    # case-sensitive fragments: -Test receivedCube,Connections.
    [string[]]$Test = @(),

    # Stop Slicer and every process it started after this many seconds.
    [ValidateRange(1, 2147483)]
    [int]$TimeoutSeconds = 900
)

$ErrorActionPreference = "Stop"

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$configPath = Join-Path $repositoryRoot "config\local.json"
$moduleSourcePath = Join-Path $repositoryRoot "extensions\SLIAFlow\SLIAFlow"
$buildRootPath = Join-Path $repositoryRoot "build\SLIAFlow"
$launcherPath = Join-Path $buildRootPath "SlicerWithSLIAFlow.exe"
# The pinned SlicerOpenIGTLink build (docs/development/openigtlink_setup.md).
$openIGTLinkBuildPath = Join-Path $repositoryRoot "build\SlicerOpenIGTLink\inner-build"
$testName = "SLIAFlow"

function Stop-WithError {
    param([string]$Message)

    Write-Host "ERROR: $Message" -ForegroundColor Red
    Write-Host "No files or configuration were installed or modified."
    exit 1
}

# The processes this run started, by ID: Slicer, SlicerApp-real, the stand-in
# for IUMA's app and their console hosts. Each entry holds its process open, so
# Windows cannot give that ID to another process while the run refers to it,
# and a process whose parent has already exited is still found through it.
function Update-ProcessTree {
    param([System.Collections.Generic.Dictionary[int, object]]$Tree)

    $snapshot = @(Get-CimInstance -ClassName Win32_Process -Property ProcessId, ParentProcessId, CreationDate, Name)
    do {
        $added = $false
        foreach ($entry in $snapshot) {
            $id = [int]$entry.ProcessId
            $parentId = [int]$entry.ParentProcessId
            if ($Tree.ContainsKey($id) -or -not $Tree.ContainsKey($parentId)) {
                continue
            }
            # A process created before its recorded parent was started by an
            # earlier process that had the same ID, so it is not part of the run.
            if ($entry.CreationDate -lt $Tree[$parentId].Created) {
                continue
            }
            try {
                $candidate = [System.Diagnostics.Process]::GetProcessById($id)
                $null = $candidate.SafeHandle
            }
            catch {
                continue
            }
            # The ID may have passed to a new process since the snapshot; the
            # held process is the listed one only if it started at that time.
            if ([math]::Abs(($candidate.StartTime - $entry.CreationDate).TotalMilliseconds) -ge 1) {
                $candidate.Dispose()
                continue
            }
            $Tree[$id] = [pscustomobject]@{ Process = $candidate; Created = $entry.CreationDate; Name = $entry.Name }
            $added = $true
        }
    } while ($added)
}

# Stops every process in the tree that is still running, including any started
# since the last scan, and nothing else.
function Stop-ProcessTree {
    param([System.Collections.Generic.Dictionary[int, object]]$Tree)

    $stopped = [System.Collections.Generic.List[string]]::new()
    for ($pass = 0; $pass -lt 3; $pass++) {
        Update-ProcessTree -Tree $Tree
        $running = @($Tree.Values | Where-Object { -not $_.Process.HasExited })
        if ($running.Count -eq 0) {
            break
        }
        foreach ($member in $running) {
            try {
                $member.Process.Kill()
                $stopped.Add("$($member.Name) ($($member.Process.Id))")
            }
            catch { }
        }
        foreach ($member in $running) {
            [void]$member.Process.WaitForExit(5000)
        }
    }
    if ($stopped.Count -gt 0) {
        Write-Host "Stopped $($stopped.Count) processes this run started: $($stopped -join ', ')"
    }
    $survivors = @($Tree.Values | Where-Object { -not $_.Process.HasExited } | ForEach-Object { "$($_.Name) ($($_.Process.Id))" })
    if ($survivors.Count -gt 0) {
        Write-Host "WARNING: still running after the stop: $($survivors -join ', ')" -ForegroundColor Red
    }
}

function Get-ConfiguredSlicerExecutable {
    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
        Stop-WithError "Configuration file is missing: $configPath. Create it from config/local.example.json."
    }

    try {
        $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    }
    catch {
        Stop-WithError "Configuration file is malformed JSON: $configPath. Correct the JSON and verify slicerExecutable."
    }

    $configuredExecutable = $config.slicerExecutable
    if ($null -eq $configuredExecutable -or $configuredExecutable -isnot [string] -or [string]::IsNullOrWhiteSpace($configuredExecutable)) {
        Stop-WithError "Configuration field 'slicerExecutable' is absent or empty in $configPath. Set it to an absolute or repository-relative Slicer executable path."
    }

    try {
        if ([System.IO.Path]::IsPathRooted($configuredExecutable)) {
            $resolved = [System.IO.Path]::GetFullPath($configuredExecutable)
        }
        else {
            $resolved = [System.IO.Path]::GetFullPath((Join-Path $repositoryRoot $configuredExecutable))
        }
    }
    catch {
        Stop-WithError "Configured slicerExecutable path cannot be resolved: '$configuredExecutable'."
    }

    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
        Stop-WithError "Configured Slicer executable does not exist: $resolved. Update config/local.json."
    }

    return $resolved
}

# The build launcher embeds its own copy of the scripted module, and that copy
# shadows anything passed through --additional-module-paths. Using the launcher
# for the Source target would silently test the last compiled snapshot instead
# of the files being edited, so each target gets the executable that can
# actually load the code it claims to exercise.
if ($Target -eq "Source") {
    if (-not (Test-Path -LiteralPath (Join-Path $moduleSourcePath "SLIAFlow.py") -PathType Leaf)) {
        Stop-WithError "Module source is missing: $moduleSourcePath\SLIAFlow.py."
    }
    $slicerExecutable = Get-ConfiguredSlicerExecutable
    $modulePaths = @($moduleSourcePath)
    $expectedModuleRoot = $moduleSourcePath

    # SLIAFlow's Connections section needs OpenIGTLinkIF (SLIA-035). The
    # configured Slicer does not carry it, so the pinned build is loaded the way
    # the SLIAFlow launcher loads it: its launcher settings put its libraries on
    # the path, and its module directories are added. A missing build fails the
    # run rather than letting the connector tests fail one by one.
    $openIGTLinkSettings = Join-Path $openIGTLinkBuildPath "AdditionalLauncherSettings.ini"
    if (-not (Test-Path -LiteralPath $openIGTLinkSettings -PathType Leaf)) {
        Stop-WithError "The SlicerOpenIGTLink build is missing: $openIGTLinkSettings. Build it as docs/development/openigtlink_setup.md describes."
    }
    $openIGTLinkLibRoots = @(Get-ChildItem -LiteralPath (Join-Path $openIGTLinkBuildPath "lib") -Directory -Filter "Slicer-*" -ErrorAction SilentlyContinue)
    if ($openIGTLinkLibRoots.Count -ne 1) {
        Stop-WithError "Expected exactly one lib\Slicer-* folder under $openIGTLinkBuildPath, found $($openIGTLinkLibRoots.Count)."
    }
    $openIGTLinkModulePaths = @(
        (Join-Path $openIGTLinkLibRoots[0].FullName "qt-loadable-modules\Release"),
        (Join-Path $openIGTLinkLibRoots[0].FullName "qt-scripted-modules")
    )
    foreach ($path in $openIGTLinkModulePaths) {
        if (-not (Test-Path -LiteralPath $path -PathType Container)) {
            Stop-WithError "The SlicerOpenIGTLink module folder is missing: $path."
        }
    }
    $modulePaths += $openIGTLinkModulePaths
    $launcherSettings = $openIGTLinkSettings
}
else {
    if (-not (Test-Path -LiteralPath $launcherPath -PathType Leaf)) {
        Stop-WithError "Build launcher is missing: $launcherPath. Build the extension, or run with -Target Source."
    }
    $slicerExecutable = $launcherPath
    $modulePaths = @()
    $expectedModuleRoot = $buildRootPath
    # The launcher passes its own dependency settings.
    $launcherSettings = $null
}

# Fail loudly when the module that Slicer actually loaded is not the one this
# invocation was supposed to test. Without this guard a stale build copy
# produces a green run that says nothing about the working tree.
$fragments = @()
if ($PSBoundParameters.ContainsKey("Test")) {
    $fragments = @($Test | ForEach-Object { $_ -split "," } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    if ($fragments.Count -eq 0) {
        Stop-WithError "-Test was given without a test-name fragment."
    }
}

$pythonExpectedRoot = $expectedModuleRoot | ConvertTo-Json -Compress
$pythonTestName = $testName | ConvertTo-Json -Compress
# The selection reaches Slicer only inside this code, never through the
# environment, so Reload and Test cannot inherit it.
$pythonFragments = ConvertTo-Json -InputObject @($fragments) -Compress
$pythonStatements = @(
    "import os, slicer, slicer.testing, slicer.util",
    "expectedRoot = os.path.normcase(os.path.realpath($pythonExpectedRoot))",
    "loadedPath = os.path.realpath(slicer.util.modulePath($pythonTestName))",
    "print('SLIAFlow module loaded from: ' + loadedPath)",
    "os.path.normcase(loadedPath).startswith(expectedRoot) or slicer.testing.exitFailure('SLIAFlow was loaded from ' + loadedPath + ' but this run must exercise ' + expectedRoot + '. A built-in module of a build launcher shadows --additional-module-paths.')",
    # Run the tests from the directory the module was actually loaded from, so
    # the reported test path can never disagree with the checked module path.
    "import importlib, sys",
    "sys.path.append(os.path.dirname(loadedPath))",
    "module = importlib.import_module($pythonTestName)",
    "testLibrary = importlib.import_module('SLIAFlowLib.SLIAFlowTest')",
    "hasattr(testLibrary, 'runCommandLineTests') or slicer.testing.exitFailure('This SLIAFlow copy has no runCommandLineTests (SLIA-038). Rebuild it with build-sliaflow.ps1.')",
    # Prints a Started line before each test, so a hung test is named.
    "testLibrary.runCommandLineTests(module, module.SLIAFlowTest, $pythonFragments) or slicer.testing.exitFailure('Slicer test failed.')"
)
$pythonCode = $pythonStatements -join "; "

$slicerArguments = @()
if ($null -ne $launcherSettings) {
    # A launcher option, so it comes first.
    $slicerArguments += "--launcher-additional-settings"
    $slicerArguments += $launcherSettings
}
$slicerArguments += @(
    "--testing",
    "--no-splash",
    "--disable-cli-modules"
)
if (-not $Headful) {
    $slicerArguments += "--no-main-window"
}
if ($modulePaths.Count -gt 0) {
    $slicerArguments += "--additional-module-paths"
    $slicerArguments += $modulePaths
}
$slicerArguments += "--python-code"
$slicerArguments += $pythonCode

function ConvertTo-WindowsCommandLineArgument {
    param([string]$Argument)

    $builder = [System.Text.StringBuilder]::new()
    [void]$builder.Append('"')
    $backslashes = 0
    foreach ($character in $Argument.ToCharArray()) {
        if ([int][char]$character -eq 92) {
            $backslashes++
            continue
        }

        if ($character -eq '"') {
            for ($index = 0; $index -lt (2 * $backslashes + 1); $index++) {
                [void]$builder.Append([char]92)
            }
            [void]$builder.Append('"')
            $backslashes = 0
            continue
        }

        for ($index = 0; $index -lt $backslashes; $index++) {
            [void]$builder.Append([char]92)
        }
        [void]$builder.Append($character)
        $backslashes = 0
    }

    for ($index = 0; $index -lt (2 * $backslashes); $index++) {
        [void]$builder.Append([char]92)
    }
    [void]$builder.Append('"')
    return $builder.ToString()
}

Write-Host "Target:            $Target"
Write-Host "Window mode:       $(if ($Headful) { 'headful' } else { 'headless' })"
Write-Host "Slicer executable: $slicerExecutable"
Write-Host "Expected module:   $expectedModuleRoot"
if ($null -ne $launcherSettings) {
    Write-Host "OpenIGTLinkIF:     $openIGTLinkBuildPath"
}
Write-Host "Test:              $testName"
if ($fragments.Count -gt 0) {
    Write-Host "Selection:         $($fragments -join ', ')"
}
Write-Host "Timeout:           $TimeoutSeconds s"

$process = [System.Diagnostics.Process]::new()
$process.StartInfo = [System.Diagnostics.ProcessStartInfo]::new()
$process.StartInfo.FileName = $slicerExecutable
$process.StartInfo.UseShellExecute = $false
$process.StartInfo.RedirectStandardOutput = $true
$process.StartInfo.RedirectStandardError = $true
$process.StartInfo.Arguments = ($slicerArguments | ForEach-Object {
    ConvertTo-WindowsCommandLineArgument $_
}) -join " "

$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$beforeStart = Get-Date
try {
    $started = $process.Start()
}
catch {
    $started = $false
}
if (-not $started) {
    Stop-WithError "Slicer could not be started at '$slicerExecutable'. Verify that the configured file is a usable Slicer executable."
}
try {
    $processStartTime = $process.StartTime
}
catch {
    $processStartTime = $beforeStart
}
# The started process keeps its own handle, so its ID stays reserved too.
$processTree = [System.Collections.Generic.Dictionary[int, object]]::new()
$processTree[$process.Id] = [pscustomobject]@{
    Process = $process
    Created = $processStartTime
    Name = [System.IO.Path]::GetFileName($slicerExecutable)
}
# Often enough to hold each process before a short-lived parent exits.
$scanIntervalSeconds = 2
# How long output is still read after Slicer has exited. A pipe still open by
# then is held by a process Slicer left running, which the stop below ends.
$drainSeconds = 2

$lastStarted = $null
$partialRun = $null
$timedOut = $false
$exitCode = 1
try {
    # Both streams are read a line at a time as Slicer writes them, and neither
    # read waits for the other, so a full pipe cannot stall Slicer.
    $readers = @(
        @{ Reader = $process.StandardOutput; Color = $null; Line = $null },
        @{ Reader = $process.StandardError; Color = "Yellow"; Line = $null }
    )
    foreach ($reader in $readers) {
        $reader.Line = $reader.Reader.ReadLineAsync()
    }
    $nextScan = 0.0
    $exitedAt = $null
    while ($true) {
        $elapsed = $stopwatch.Elapsed.TotalSeconds
        if ($elapsed -ge $TimeoutSeconds) {
            $timedOut = $true
            break
        }
        if ($elapsed -ge $nextScan) {
            Update-ProcessTree -Tree $processTree
            $nextScan = $elapsed + $scanIntervalSeconds
        }
        $open = @($readers | Where-Object { $null -ne $_.Line })
        if ($process.HasExited) {
            if ($null -eq $exitedAt) {
                $exitedAt = $elapsed
            }
            if ($open.Count -eq 0 -or ($elapsed - $exitedAt) -ge $drainSeconds) {
                break
            }
        }
        if ($open.Count -eq 0) {
            # The pipes can close before Slicer exits; the timeout still holds.
            [void]$process.WaitForExit(200)
            continue
        }
        [void][System.Threading.Tasks.Task]::WaitAny([System.Threading.Tasks.Task[]]@($open | ForEach-Object { $_.Line }), 200)
        foreach ($reader in $open) {
            while ($null -ne $reader.Line -and $reader.Line.IsCompleted) {
                $line = $reader.Line.Result
                if ($null -eq $line) {
                    $reader.Line = $null
                    break
                }
                if ($line -match '^Started: (\S+)') {
                    $lastStarted = $Matches[1]
                }
                elseif ($line.StartsWith("Partial run: ")) {
                    $partialRun = $line
                }
                if ($null -ne $reader.Color) {
                    Write-Host $line -ForegroundColor $reader.Color
                }
                else {
                    Write-Host $line
                }
                $reader.Line = $reader.Reader.ReadLineAsync()
            }
        }
    }
    if (-not $timedOut) {
        $exitCode = $process.ExitCode
    }
}
finally {
    if ($timedOut) {
        $lastTest = if ($null -ne $lastStarted) { $lastStarted } else { "no test had started" }
        Write-Host "TIMEOUT after $TimeoutSeconds s. Last test started: $lastTest" -ForegroundColor Red
    }
    # Runs whether Slicer timed out, exited, or the run was interrupted with
    # Ctrl+C, so no process the run started outlives it.
    Stop-ProcessTree -Tree $processTree
    foreach ($member in $processTree.Values) {
        $member.Process.Dispose()
    }
}

if ($timedOut) {
    $exitCode = 1
}
elseif ($exitCode -ne 0) {
    Write-Host "ERROR: Slicer test '$testName' failed with exit code $exitCode." -ForegroundColor Red
}
# A partial run says so as the last line, so it cannot pass for the suite.
if ($null -ne $partialRun) {
    Write-Host $partialRun
}
exit $exitCode
