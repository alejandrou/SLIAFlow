<#
.SYNOPSIS
    Stage, patch and build the vendored UC2 blood-vessel enhancement.

.DESCRIPTION
    Checks that the vendored copy under `workspace/components/` is a clean
    checkout of the partner commit, copies its C sources into the
    already-ignored `build\uc2\source\`, applies the versioned patches in
    `scripts\development\uc2-patches\` to the staged copy in name order, builds
    there with the MSYS2 GCC, and asserts by SHA-256 that every staged source
    equals the vendored original plus those patches. The vendored copy itself is
    never written to (`docs/development/uc2_changes.md`).

    Five things about this build are deliberate and must not be "fixed".

    The compiler is the MSYS2 POSIX-layer GCC in `C:\msys64\usr\bin`, not the
    UCRT64 one. `hdr_reader.c` calls `getline`, which the Windows C runtime does
    not provide, and GCC 14 and later make the implicit declaration an error. The
    MSYS2 runtime provides it. The `main.out` UC2 was first run with on this
    machine was built the same way: it reports `GCC: (GNU) 15.3.0` and links
    `msys-2.0.dll`. That DLL is copied beside the binary so the runner does not
    depend on MSYS2 being on PATH.

    The compile line is the vendored README's, minus `logger.h`. A header named
    on the command line makes GCC write a precompiled `logger.h.gch`; `main.c`
    still includes it.

    The binary is never built or run in place. It writes its PNG into its working
    directory, so running it in `workspace/components/` would put generated files
    inside the vendored reference copy. SLIAFlow runs it from `build\uc2\run\`.

    Every change to UC2 is a patch, applied with `git apply`, which refuses a
    hunk whose context does not match instead of guessing. The vendored sources
    are CRLF in the working tree and the patches carry CRLF lines to match, so
    `core.autocrlf` is off for the call. A patch that no longer applies fails the
    build; it is never skipped.

    Four compiler warnings are expected on every build and are not silenced:
    `-Wunused-variable` for `BVMap` in `main.c` (the `default:` branch computes a
    map and never writes it) and three `-Wchar-subscripts` in `hdr_reader.c`.
    Their absence is the surprise, and it fails the build as surely as a new one.

.PARAMETER Clean
    Delete the staged build root before staging. Removes previous run outputs
    along with the binary.

.PARAMETER SkipBuild
    Run the untouched checks, stage and patch without invoking the compiler.

.PARAMETER PatchDirectory
    The folder of `*.patch` files to apply. Defaults to
    `scripts\development\uc2-patches`; another folder is only for checking how
    the script reacts to a patch that does not apply, or for building without
    the patches to compare against.

.PARAMETER MsysRoot
    The MSYS2 installation. Defaults to C:\msys64.
#>
[CmdletBinding()]
param(
    [switch]$Clean,

    [switch]$SkipBuild,

    [string]$PatchDirectory = (Join-Path $PSScriptRoot "uc2-patches"),

    [string]$MsysRoot = "C:\msys64"
)

$ErrorActionPreference = "Stop"

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$vendoredRoot = Join-Path $repositoryRoot "workspace\components\blood_vessels_enhancement"

$stagedRoot = Join-Path $repositoryRoot "build\uc2"
$stagedSource = Join-Path $stagedRoot "source"
$stagedRun = Join-Path $stagedRoot "run"
# The vendored source plus the same patches, rebuilt on every run, which the
# staged source must equal.
$expectedSource = Join-Path $stagedRoot "expected"

$executableName = "uc2_bvmap.exe"
$stagedExecutable = Join-Path $stagedSource $executableName

# The partner commit both copies were checked out at on 2026-09-16.
$expectedCommit = "1b5e9ae"

# The sources the binary is built from: every C file and header the vendored
# README compiles or includes.
$sourceFiles = @(
    "main.c", "params.c", "params.h", "functions.c", "functions.h",
    "hdr_reader.c", "hdr_reader.h", "BV_enhancement.c", "BV_enhancement.h",
    "png_writer.c", "png_writer.h", "logger.h", "stb_image_write.h"
)
$compiledFiles = @("main.c", "params.c", "functions.c", "hdr_reader.c", "BV_enhancement.c", "png_writer.c")
$compilerFlags = @("-Wall", "-O3", "-g")

$msysBin = Join-Path $MsysRoot "usr\bin"
$gccPath = Join-Path $msysBin "gcc.exe"
$runtimeDllName = "msys-2.0.dll"

# Compiler diagnostics the patched source is known to emit, as file:line and
# flag. Their absence means the toolchain or the source changed. Patch 0002
# inserts 29 lines before the `default:` branch, so its unused `BVMap` is
# reported at line 196 (167 in the unpatched source).
$expectedWarnings = @(
    @{ Location = "main.c:196"; Flag = "-Wunused-variable" },
    @{ Location = "hdr_reader.c:50"; Flag = "-Wchar-subscripts" },
    @{ Location = "hdr_reader.c:102"; Flag = "-Wchar-subscripts" },
    @{ Location = "hdr_reader.c:109"; Flag = "-Wchar-subscripts" }
)

function Stop-WithError {
    param([string]$Message)

    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

function Invoke-Git {
    param([string[]]$Arguments)

    $ErrorActionPreference = "Continue"
    $output = & git -C $vendoredRoot @Arguments 2>&1 | ForEach-Object { $_.ToString() }
    $ErrorActionPreference = "Stop"
    if ($LASTEXITCODE -ne 0) {
        Stop-WithError "git $($Arguments -join ' ') failed in $vendoredRoot`: $($output -join ' ')"
    }
    # Nothing at all, not one null, when git printed nothing: callers count lines.
    if ($output) { $output }
}

function Copy-Sources {
    param([string]$Destination)

    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    foreach ($name in $sourceFiles) {
        Copy-Item -LiteralPath (Join-Path $vendoredRoot $name) -Destination (Join-Path $Destination $name) -Force
    }
}

function Get-Patches {
    if (-not (Test-Path -LiteralPath $PatchDirectory -PathType Container)) {
        Stop-WithError "The patch folder is missing: $PatchDirectory"
    }
    # Name order is application order: the patches are numbered 0001, 0002...
    return @(Get-ChildItem -LiteralPath $PatchDirectory -Filter "*.patch" -File | Sort-Object Name)
}

function Invoke-Patches {
    param([string]$Directory, [object[]]$Patches)

    # Inside a repository, `git apply` reads patch paths from the repository
    # root and silently skips any file it then finds outside the current
    # folder, exiting 0. So it runs from the root, the staged folder is given
    # as a prefix, and a "Skipped patch" line is a failure like any other.
    $fullDirectory = [System.IO.Path]::GetFullPath($Directory)
    if (-not $fullDirectory.StartsWith($repositoryRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        Stop-WithError "$Directory is outside the repository $repositoryRoot."
    }
    $relativeDirectory = $fullDirectory.Substring($repositoryRoot.Length).TrimStart('\').Replace('\', '/')

    foreach ($patch in $Patches) {
        # core.autocrlf is off for this call: the staged sources are CRLF, the
        # patches carry CRLF lines, and nothing may be converted on the way.
        $ErrorActionPreference = "Continue"
        $output = & git -c core.autocrlf=false -C $repositoryRoot apply --verbose --whitespace=nowarn `
            "--directory=$relativeDirectory" $patch.FullName 2>&1 | ForEach-Object { $_.ToString() }
        $exitCode = $LASTEXITCODE
        $ErrorActionPreference = "Stop"
        $skipped = @($output | Where-Object { $_ -like "Skipped patch*" })
        $applied = @($output | Where-Object { $_ -like "Applied patch*" })
        if ($exitCode -ne 0 -or $skipped.Count -gt 0 -or $applied.Count -eq 0) {
            $output | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
            Stop-WithError "$($patch.Name) does not apply to $Directory. The vendored UC2 source has changed or the patch is wrong; the build does not continue without it."
        }
    }
}

function Assert-StagedSourcesMatch {
    param([string]$Reference)

    $mismatches = @()
    foreach ($name in $sourceFiles) {
        $original = Join-Path $Reference $name
        $staged = Join-Path $stagedSource $name
        if (-not (Test-Path -LiteralPath $staged -PathType Leaf)) {
            $mismatches += "MISSING  $name"
            continue
        }
        $originalHash = (Get-FileHash -LiteralPath $original -Algorithm SHA256).Hash
        $stagedHash = (Get-FileHash -LiteralPath $staged -Algorithm SHA256).Hash
        if ($originalHash -ne $stagedHash) {
            $mismatches += "CHANGED  $name`n           expected $originalHash`n           staged   $stagedHash"
        }
    }
    return $mismatches
}

Write-Host "== STRATUM UC2 build =="
Write-Host "Vendored source: $vendoredRoot"
Write-Host "Staged build:    $stagedRoot"
Write-Host "Patches:         $PatchDirectory"
Write-Host ""

if (-not (Test-Path -LiteralPath $vendoredRoot -PathType Container)) {
    Stop-WithError "The vendored UC2 component is missing: $vendoredRoot"
}

# The outer repository ignores /workspace/, so `git status` from the project root
# says nothing about this copy. It is a clone of the partner repository, and the
# check has to run inside it.
Write-Host "-- Vendored copy is untouched --"
$commit = (Invoke-Git @("rev-parse", "--short=7", "HEAD")) | Select-Object -First 1
$trackedChanges = @(Invoke-Git @("status", "--porcelain", "--untracked-files=no"))
$untracked = @(Invoke-Git @("status", "--porcelain", "--untracked-files=normal") | Where-Object { $_.StartsWith("?? ") })
Write-Host "Commit:           $commit (expected $expectedCommit)"
Write-Host "Tracked changes:  $($trackedChanges.Count)"
foreach ($line in $untracked) { Write-Host "Untracked:        $($line.Substring(3))" }
if ($commit -ne $expectedCommit) {
    Stop-WithError "The vendored UC2 copy is at $commit, not $expectedCommit. The patches and the evidence for this build describe $expectedCommit."
}
if ($trackedChanges.Count -gt 0) {
    $trackedChanges | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    Stop-WithError "The vendored UC2 copy has modified tracked files. It must not be edited; change UC2 through a patch in $PatchDirectory instead."
}
Write-Host ""

if (-not $SkipBuild) {
    Write-Host "-- Toolchain --"
    if (-not (Test-Path -LiteralPath $gccPath -PathType Leaf)) {
        Stop-WithError "The MSYS2 GCC is not at $gccPath. Install MSYS2 and its gcc package, or pass -MsysRoot."
    }
    # cc1 loads the MSYS2 runtime DLLs from PATH. Another MSYS runtime earlier on
    # PATH, such as Git for Windows', makes it fail to start.
    $env:PATH = "$msysBin;$env:PATH"
    (& $gccPath --version 2>&1) | Select-Object -First 1 | ForEach-Object { Write-Host "$_" }
    (& $gccPath -dumpmachine 2>&1) | ForEach-Object { Write-Host "Target: $_" }
    Write-Host ""
}

if ($Clean -and (Test-Path -LiteralPath $stagedRoot -PathType Container)) {
    Write-Host "-- Cleaning $stagedRoot --"
    Remove-Item -LiteralPath $stagedRoot -Recurse -Force
}

Write-Host "-- Staging --"
# Staging always starts from the vendored copy, so the patches apply to the
# delivered code and never to an earlier patched result.
Copy-Sources -Destination $stagedSource
New-Item -ItemType Directory -Path $stagedRun -Force | Out-Null
Write-Host "Copied $($sourceFiles.Count) source file(s). Run directory: $stagedRun"
Write-Host ""

Write-Host "-- Patches --"
$patches = Get-Patches
Invoke-Patches -Directory $stagedSource -Patches $patches
foreach ($patch in $patches) {
    $patchHash = (Get-FileHash -LiteralPath $patch.FullName -Algorithm SHA256).Hash
    Write-Host "  applied  $($patch.Name)  $patchHash"
}
Write-Host "Applied $($patches.Count) patch(es) to the staged source."
Write-Host ""

$warningFailures = @()
if ($SkipBuild) {
    Write-Host "-- Build skipped (-SkipBuild) --"
    Write-Host ""
} else {
    Write-Host "-- Building --"
    $gccArguments = $compilerFlags + $compiledFiles + @("-lm", "-o", $executableName)
    Write-Host "cd $stagedSource"
    Write-Host "$gccPath $($gccArguments -join ' ')"

    # GCC writes its diagnostics to stderr. Windows PowerShell 5.1 turns redirected
    # native stderr into a terminating error under "Stop", so the warnings would
    # end the build before they could be checked.
    Push-Location $stagedSource
    $ErrorActionPreference = "Continue"
    try {
        $buildOutput = & $gccPath @gccArguments 2>&1 | ForEach-Object { $_.ToString() }
        $buildExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = "Stop"
        Pop-Location
    }
    $buildOutput | ForEach-Object { Write-Host $_ }
    Write-Host ""

    if ($buildExitCode -ne 0) {
        Stop-WithError "gcc exited with code $buildExitCode. Fix the toolchain or the patch, never the vendored source."
    }
    if (-not (Test-Path -LiteralPath $stagedExecutable -PathType Leaf)) {
        Stop-WithError "gcc reported success but $stagedExecutable was not produced."
    }

    $runtimeDll = Join-Path $msysBin $runtimeDllName
    Copy-Item -LiteralPath $runtimeDll -Destination (Join-Path $stagedSource $runtimeDllName) -Force
    Write-Host "Copied $runtimeDllName beside the binary."
    Write-Host ""

    Write-Host "-- Warnings --"
    $seen = @{}
    foreach ($line in $buildOutput) {
        if ($line -match '^([A-Za-z_]+\.c):(\d+):\d+: warning: .*\[(-W[a-z-]+)\]') {
            $seen["$($Matches[1]):$($Matches[2]) $($Matches[3])"] = $line.Trim()
        }
    }
    foreach ($warning in $expectedWarnings) {
        $key = "$($warning.Location) $($warning.Flag)"
        if ($seen.ContainsKey($key)) {
            Write-Host "  present     $key"
            $seen.Remove($key)
        } else {
            Write-Host "  ABSENT      $key" -ForegroundColor Red
            $warningFailures += "expected warning $key did not appear"
        }
    }
    foreach ($key in ($seen.Keys | Sort-Object)) {
        Write-Host "  UNEXPECTED  $key" -ForegroundColor Red
        $warningFailures += "unexpected warning $key"
    }
    Write-Host ""

    $executableHash = (Get-FileHash -LiteralPath $stagedExecutable -Algorithm SHA256).Hash
    $executableSize = (Get-Item -LiteralPath $stagedExecutable).Length
    Write-Host "-- Binary --"
    Write-Host "$stagedExecutable"
    Write-Host "Size:    $executableSize bytes"
    Write-Host "SHA-256: $executableHash"
    Write-Host ""
}

# The compliance property - "the staged source is the vendored UC2 plus the
# versioned patches, and nothing else" - is re-tested on every build rather
# than trusted once. `build/` is gitignored, so `git status` proves nothing
# about the staged copy. The reference is rebuilt from a fresh copy.
Write-Host "-- Staged sources equal the vendored copy plus the patches --"
if (Test-Path -LiteralPath $expectedSource -PathType Container) {
    Remove-Item -LiteralPath $expectedSource -Recurse -Force
}
Copy-Sources -Destination $expectedSource
Invoke-Patches -Directory $expectedSource -Patches $patches
$mismatches = @(Assert-StagedSourcesMatch -Reference $expectedSource)
if ($mismatches.Count -gt 0) {
    $mismatches | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    Stop-WithError "$($mismatches.Count) staged source(s) differ from the vendored copy plus the patches. Change UC2 only through a patch in $PatchDirectory; re-stage with -Clean."
}
Write-Host "All $($sourceFiles.Count) staged source(s) equal $vendoredRoot plus $($patches.Count) patch(es)."
Write-Host ""

if ($warningFailures.Count -gt 0) {
    Stop-WithError "The compiler diagnostics differ from the recorded set: $($warningFailures -join '; '). This binary is not the one the build record describes."
}

Write-Host "UC2 build ready. Press Capture in SLIAFlow to run $executableName on the configured cube."
exit 0
