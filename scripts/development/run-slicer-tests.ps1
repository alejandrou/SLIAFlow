[CmdletBinding()]
param(
    # Source runs the tests against the working tree under extensions/.
    # Build runs them against the compiled copy under build/SLIAFlow/.
    [ValidateSet("Source", "Build")]
    [string]$Target = "Source",

    # Keep the main window for layout-manager and renderer coverage.
    [switch]$Headful
)

$ErrorActionPreference = "Stop"

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$configPath = Join-Path $repositoryRoot "config\local.json"
$moduleSourcePath = Join-Path $repositoryRoot "extensions\SLIAFlow\SLIAFlow"
$buildRootPath = Join-Path $repositoryRoot "build\SLIAFlow"
$launcherPath = Join-Path $buildRootPath "SlicerWithSLIAFlow.exe"
$testName = "SLIAFlow"

function Stop-WithError {
    param([string]$Message)

    Write-Host "ERROR: $Message" -ForegroundColor Red
    Write-Host "No files or configuration were installed or modified."
    exit 1
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
}
else {
    if (-not (Test-Path -LiteralPath $launcherPath -PathType Leaf)) {
        Stop-WithError "Build launcher is missing: $launcherPath. Build the extension, or run with -Target Source."
    }
    $slicerExecutable = $launcherPath
    $modulePaths = @()
    $expectedModuleRoot = $buildRootPath
}

# Fail loudly when the module that Slicer actually loaded is not the one this
# invocation was supposed to test. Without this guard a stale build copy
# produces a green run that says nothing about the working tree.
$pythonExpectedRoot = $expectedModuleRoot | ConvertTo-Json -Compress
$pythonTestName = $testName | ConvertTo-Json -Compress
$pythonStatements = @(
    "import os, slicer, slicer.testing, slicer.util",
    "expectedRoot = os.path.normcase(os.path.realpath($pythonExpectedRoot))",
    "loadedPath = os.path.realpath(slicer.util.modulePath($pythonTestName))",
    "print('SLIAFlow module loaded from: ' + loadedPath)",
    "os.path.normcase(loadedPath).startswith(expectedRoot) or slicer.testing.exitFailure('SLIAFlow was loaded from ' + loadedPath + ' but this run must exercise ' + expectedRoot + '. A built-in module of a build launcher shadows --additional-module-paths.')",
    # Run the tests from the directory the module was actually loaded from, so
    # the reported test path can never disagree with the checked module path.
    "slicer.testing.runUnitTest([os.path.dirname(loadedPath)], $pythonTestName)"
)
$pythonCode = $pythonStatements -join "; "

$slicerArguments = @(
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
Write-Host "Test:              $testName"

$process = [System.Diagnostics.Process]::new()
$process.StartInfo = [System.Diagnostics.ProcessStartInfo]::new()
$process.StartInfo.FileName = $slicerExecutable
$process.StartInfo.UseShellExecute = $false
$process.StartInfo.RedirectStandardOutput = $true
$process.StartInfo.RedirectStandardError = $true
$process.StartInfo.Arguments = ($slicerArguments | ForEach-Object {
    ConvertTo-WindowsCommandLineArgument $_
}) -join " "

try {
    if (-not $process.Start()) {
        Stop-WithError "Slicer could not be started at '$slicerExecutable'. Verify that the configured file is a usable Slicer executable."
    }
    $standardOutput = $process.StandardOutput.ReadToEndAsync()
    $standardError = $process.StandardError.ReadToEndAsync()
    $process.WaitForExit()
    $standardOutput.Result | Write-Host -NoNewline
    $standardError.Result | Write-Host -ForegroundColor Yellow -NoNewline
    $exitCode = $process.ExitCode
}
catch {
    Stop-WithError "Slicer could not be started at '$slicerExecutable'. Verify that the configured file is a usable Slicer executable."
}

if ($exitCode -ne 0) {
    Write-Error "Slicer test '$testName' failed with exit code $exitCode."
    exit $exitCode
}

exit 0
