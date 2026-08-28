$ErrorActionPreference = "Stop"

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$configPath = Join-Path $repositoryRoot "config\local.json"
$modulePath = Join-Path $repositoryRoot "extensions\SLIAFlow\SLIAFlow"
$launcherPath = Join-Path $repositoryRoot "build\SLIAFlow\SlicerWithSLIAFlow.exe"
$testName = "SLIAFlow"

function Stop-WithError {
    param([string]$Message)

    Write-Host "ERROR: $Message" -ForegroundColor Red
    Write-Host "No files or configuration were installed or modified."
    exit 1
}

if (Test-Path -LiteralPath $launcherPath -PathType Leaf) {
    $slicerExecutable = $launcherPath
}
else {
    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
        Stop-WithError "SLIAFlow launcher and configuration file are missing. Build the extension or create $configPath from config/local.example.json."
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
            $slicerExecutable = [System.IO.Path]::GetFullPath($configuredExecutable)
        }
        else {
            $slicerExecutable = [System.IO.Path]::GetFullPath((Join-Path $repositoryRoot $configuredExecutable))
        }
    }
    catch {
        Stop-WithError "Configured slicerExecutable path cannot be resolved: '$configuredExecutable'."
    }

    if (-not (Test-Path -LiteralPath $slicerExecutable -PathType Leaf)) {
        Stop-WithError "Configured Slicer executable does not exist: $slicerExecutable. Update config/local.json."
    }
}

$pythonPaths = @($modulePath) | ConvertTo-Json -Compress
$pythonTestName = $testName | ConvertTo-Json -Compress
$pythonCode = "import slicer.testing; slicer.testing.runUnitTest($pythonPaths, $pythonTestName)"
$slicerArguments = @(
    "--testing",
    "--no-splash",
    "--no-main-window",
    "--disable-cli-modules",
    "--additional-module-paths",
    $modulePath,
    "--python-code",
    $pythonCode
)

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

Write-Host "Slicer executable: $slicerExecutable"
Write-Host "Test: $testName"

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
