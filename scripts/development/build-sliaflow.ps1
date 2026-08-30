[CmdletBinding()]
param(
    # Visual Studio is a multi-configuration generator, so the configuration
    # has to be named on every build invocation.
    [ValidateSet("Release", "Debug", "RelWithDebInfo", "MinSizeRel")]
    [string]$Configuration = "Release",

    # Re-run the CMake configure step before building. Needed only when the
    # build tree is missing, when its cache points at a different Slicer build,
    # or when the generator has to change. Adding, renaming, or removing files
    # in extensions/SLIAFlow does not need it: the generator re-runs CMake by
    # itself whenever a CMakeLists.txt is newer than the cache.
    [switch]$Configure,

    # Start build\SLIAFlow\SlicerWithSLIAFlow.exe once the build tree matches
    # the working tree.
    [switch]$Launch
)

$ErrorActionPreference = "Stop"

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$configPath = Join-Path $repositoryRoot "config\local.json"
$extensionSourcePath = Join-Path $repositoryRoot "extensions\SLIAFlow"
$moduleSourcePath = Join-Path $extensionSourcePath "SLIAFlow"
$buildRootPath = Join-Path $repositoryRoot "build\SLIAFlow"
$launcherPath = Join-Path $buildRootPath "SlicerWithSLIAFlow.exe"

function Stop-WithError {
    param([string]$Message)

    Write-Host "ERROR: $Message" -ForegroundColor Red
    Write-Host "The Slicer installation under apps\ was not modified."
    exit 1
}

function Get-CMakeExecutable {
    $pathCommand = Get-Command cmake -ErrorAction SilentlyContinue
    if ($null -ne $pathCommand) {
        return $pathCommand.Source
    }

    # CMake is frequently installed without being added to PATH, and the
    # default installer location is stable enough to be worth trying before
    # telling the operator that nothing can be built.
    $defaultPath = "C:\Program Files\CMake\bin\cmake.exe"
    if (Test-Path -LiteralPath $defaultPath -PathType Leaf) {
        return $defaultPath
    }

    Stop-WithError "CMake was not found on PATH or at $defaultPath. Install CMake or add it to PATH."
}

# Slicer_DIR is the Slicer-build directory that contains SlicerConfig.cmake,
# which is exactly the directory holding the configured Slicer executable. It
# is derived from config/local.json so that this script and
# run-slicer-tests.ps1 can never disagree about which Slicer build is in use.
function Get-ConfiguredSlicerDirectory {
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
        Stop-WithError "Configuration field 'slicerExecutable' is absent or empty in $configPath."
    }

    if ([System.IO.Path]::IsPathRooted($configuredExecutable)) {
        $resolvedExecutable = [System.IO.Path]::GetFullPath($configuredExecutable)
    }
    else {
        $resolvedExecutable = [System.IO.Path]::GetFullPath((Join-Path $repositoryRoot $configuredExecutable))
    }

    if (-not (Test-Path -LiteralPath $resolvedExecutable -PathType Leaf)) {
        Stop-WithError "Configured Slicer executable does not exist: $resolvedExecutable. Update config/local.json."
    }

    $slicerDirectory = Split-Path -Parent $resolvedExecutable
    if (-not (Test-Path -LiteralPath (Join-Path $slicerDirectory "SlicerConfig.cmake") -PathType Leaf)) {
        Stop-WithError "SlicerConfig.cmake was not found next to $resolvedExecutable. slicerExecutable must point into a Slicer build tree."
    }

    return $slicerDirectory
}

# The copied module lives under lib\Slicer-<version>\qt-scripted-modules. The
# version is discovered rather than hard-coded so that a Slicer upgrade does
# not silently make this script inspect a directory that no longer exists.
function Get-ScriptedModulesPath {
    $candidates = @(Get-ChildItem -Path (Join-Path $buildRootPath "lib") -Directory -Filter "Slicer-*" -ErrorAction SilentlyContinue |
        ForEach-Object { Join-Path $_.FullName "qt-scripted-modules" } |
        Where-Object { Test-Path -LiteralPath $_ -PathType Container })

    if ($candidates.Count -eq 0) {
        return $null
    }
    if ($candidates.Count -gt 1) {
        Stop-WithError "Several scripted-module directories exist under $buildRootPath\lib: $($candidates -join ', '). Delete build\SLIAFlow and re-run with -Configure."
    }

    return $candidates[0]
}

# Relative paths are computed by substring rather than by
# [System.IO.Path]::GetRelativePath, which does not exist in Windows
# PowerShell 5.1.
function Get-RelativePath {
    param([string]$Root, [string]$FullPath)

    $normalizedRoot = [System.IO.Path]::GetFullPath($Root).TrimEnd('\')
    $normalizedFull = [System.IO.Path]::GetFullPath($FullPath)
    return $normalizedFull.Substring($normalizedRoot.Length).TrimStart('\')
}

# Everything the build owns and can regenerate. Compiled bytecode is excluded
# because it is derived from the copies, not from the working tree.
function Get-TrackedFiles {
    param([string]$Root)

    return @(Get-ChildItem -Path $Root -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Extension -ne ".pyc" -and
            $_.FullName -notlike "*\__pycache__\*" -and
            $_.Name -ne "CMakeLists.txt"
        })
}

$cmakeExecutable = Get-CMakeExecutable

if (-not (Test-Path -LiteralPath (Join-Path $moduleSourcePath "SLIAFlow.py") -PathType Leaf)) {
    Stop-WithError "Module source is missing: $moduleSourcePath\SLIAFlow.py."
}

Write-Host "== SLIAFlow build =="
Write-Host "CMake:         $cmakeExecutable"
Write-Host "Source:        $extensionSourcePath"
Write-Host "Build tree:    $buildRootPath"
Write-Host "Configuration: $Configuration"
Write-Host ""

$cacheExists = Test-Path -LiteralPath (Join-Path $buildRootPath "CMakeCache.txt") -PathType Leaf
if ($Configure -or -not $cacheExists) {
    if (-not $cacheExists) {
        Write-Host "No CMake cache in $buildRootPath; configuring."
    }
    $slicerDirectory = Get-ConfiguredSlicerDirectory
    Write-Host "Slicer_DIR:    $slicerDirectory"
    Write-Host ""
    Write-Host "== Configure =="
    & $cmakeExecutable -S $extensionSourcePath -B $buildRootPath "-DSlicer_DIR=$slicerDirectory" "-DBUILD_TESTING=ON"
    if ($LASTEXITCODE -ne 0) {
        Stop-WithError "CMake configure failed with exit code $LASTEXITCODE."
    }
    Write-Host ""
}

# The copy steps CMake generates never delete anything. A file that was renamed
# or removed in the working tree therefore survives in the build tree, and the
# launcher keeps importing it, so a manual check of "the change is visible" can
# pass against code that no longer exists. Removing the copied module before
# every build is what makes one run of this script equivalent to a clean build
# of the module. Only generated output is deleted here.
$existingScriptedModules = Get-ScriptedModulesPath
if ($null -ne $existingScriptedModules) {
    Write-Host "== Prune stale copies =="
    Write-Host "Removing $existingScriptedModules"
    Remove-Item -LiteralPath $existingScriptedModules -Recurse -Force
    # The bytecode step records completion in a stamp file; without removing it
    # the recreated .py copies would not be recompiled.
    Get-ChildItem -Path (Join-Path $buildRootPath "SLIAFlow") -Filter "python_compile_*_complete" -File -ErrorAction SilentlyContinue |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }
    Write-Host ""
}

Write-Host "== Build =="
& $cmakeExecutable --build $buildRootPath --config $Configuration
if ($LASTEXITCODE -ne 0) {
    Stop-WithError "CMake build failed with exit code $LASTEXITCODE."
}
Write-Host ""

# A build that reports success is not by itself evidence that the launcher will
# load the edited files: a file the working tree gained but CMakeLists.txt does
# not list is simply never copied, and the build stays green. Comparing the two
# trees by content is the check that actually answers "does the launcher run
# what I just edited".
Write-Host "== Verify =="
$scriptedModulesPath = Get-ScriptedModulesPath
if ($null -eq $scriptedModulesPath) {
    Stop-WithError "The build produced no qt-scripted-modules directory under $buildRootPath\lib."
}
Write-Host "Deployed to: $scriptedModulesPath"

$problems = @()

$sourceFiles = Get-TrackedFiles -Root $moduleSourcePath
if ($sourceFiles.Count -eq 0) {
    Stop-WithError "No module source files were found under $moduleSourcePath."
}

$expectedRelativePaths = @{}
foreach ($sourceFile in $sourceFiles) {
    $relativePath = Get-RelativePath -Root $moduleSourcePath -FullPath $sourceFile.FullName
    $expectedRelativePaths[$relativePath.ToLowerInvariant()] = $true
    $deployedPath = Join-Path $scriptedModulesPath $relativePath

    if (-not (Test-Path -LiteralPath $deployedPath -PathType Leaf)) {
        $problems += "not deployed: $relativePath (add it to MODULE_PYTHON_SCRIPTS or MODULE_PYTHON_RESOURCES in $moduleSourcePath\CMakeLists.txt)"
        continue
    }

    $sourceHash = (Get-FileHash -LiteralPath $sourceFile.FullName -Algorithm SHA256).Hash
    $deployedHash = (Get-FileHash -LiteralPath $deployedPath -Algorithm SHA256).Hash
    if ($sourceHash -ne $deployedHash) {
        $problems += "content differs: $relativePath"
        continue
    }

    Write-Host "  ok  $relativePath"
}

foreach ($deployedFile in (Get-TrackedFiles -Root $scriptedModulesPath)) {
    $relativePath = Get-RelativePath -Root $scriptedModulesPath -FullPath $deployedFile.FullName
    if (-not $expectedRelativePaths.ContainsKey($relativePath.ToLowerInvariant())) {
        $problems += "orphan in build tree: $relativePath (no counterpart in $moduleSourcePath)"
    }
}

if ($problems.Count -gt 0) {
    Write-Host ""
    foreach ($problem in $problems) {
        Write-Host "  $problem" -ForegroundColor Red
    }
    Stop-WithError "The build tree does not match the working tree. $launcherPath would not show the current sources."
}

Write-Host ""
Write-Host "The build tree matches the working tree." -ForegroundColor Green
Write-Host "Launch: $launcherPath"

if ($Launch) {
    if (-not (Test-Path -LiteralPath $launcherPath -PathType Leaf)) {
        Stop-WithError "Build launcher is missing: $launcherPath."
    }
    Write-Host ""
    Write-Host "== Launch =="
    Start-Process -FilePath $launcherPath
}

exit 0
