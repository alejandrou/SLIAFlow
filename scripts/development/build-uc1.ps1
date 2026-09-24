<#
.SYNOPSIS
    Stage and build the vendored UC1 CUDA pipeline for this GPU.

.DESCRIPTION
    Copies the vendored `gpu_single_bsq/source/` and `svm_model/` trees into the
    already-ignored `build/uc1/UC1/`, builds two binaries from them with the
    GUIDE section 3.1-B command lines retargeted at `sm_120`, and then asserts by
    SHA-256 that every staged source file is still byte-identical to its
    `workspace/components/` original.

    - `stratum.opt.exe`, the release build, used by the standalone Python
      runner.
    - `stratum.opt.intermediate.exe`, the intermediate build
      (`-lineinfo -DPROFILE_MODE -DINTERMEDIATE_OUTPUT`), which SLIAFlow runs
      inside Slicer and whose per-stage BMPs it displays (SLIA-027, ADR-0003).

    Three things about this build are deliberate and must not be "fixed".

    The binary is never built or run in place. `main.cu` writes its output into
    the source tree it runs from, so building in `workspace/components/` would
    put generated files inside the vendored reference copy. Staging is
    mandatory, and the two-level layout is load-bearing: `main.cu` opens the
    SVM model as the literal relative path `../../svm_model/*.bin`.

    `nvcc` is invoked directly rather than through `make`. The Makefile's
    `FLAGS` carries the POSIX-only `-ldl`, which does not link on Windows.

    Each binary has its own list of expected compiler warnings, because the
    two command lines compile different code. They are not silenced and the
    vendored source is not edited to remove them. An absent expected warning is
    a surprise, and it is reported as one.

.PARAMETER Clean
    Delete the staged build root before staging. Removes previous run outputs
    along with the binary.

.PARAMETER SkipBuild
    Stage and run the hash assertion without invoking the compiler.
#>
[CmdletBinding()]
param(
    [switch]$Clean,

    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$vendoredRoot = Join-Path $repositoryRoot "workspace\components\UC1_Brain_Tumor-GPU_optimization\UC1_Brain_Tumor-GPU_optimization"
$vendoredSource = Join-Path $vendoredRoot "gpu_single_bsq\source"
$vendoredModel = Join-Path $vendoredRoot "svm_model"

$stagedRoot = Join-Path $repositoryRoot "build\uc1\UC1"
$stagedSource = Join-Path $stagedRoot "gpu_single_bsq\source"
$stagedModel = Join-Path $stagedRoot "svm_model"
$stagedRgbOutput = Join-Path $stagedSource "output\rgb"


# The GPU this build targets. `sm_120` compiles and executes natively on the
# RTX 5050, so there is no PTX-JIT fallback; the second -gencode emits PTX only
# so the binary survives a future GPU change.
$computeCapability = "120"

# The binaries this script builds. `Flags` is appended to the GUIDE section
# 3.1-B release command line; for the intermediate build that is exactly the
# difference GUIDE 3.1-B shows between the two. `ExpectedWarnings` are the
# compiler diagnostics that command line is known to emit. Their absence means
# the toolchain changed, not that the code improved.
$binaries = @(
    [PSCustomObject]@{
        Name = "stratum.opt.exe"
        Flags = ""
        ExpectedWarnings = @(
            @{ Code = "#550-D"; Where = "functions_cuda.cu line 63, num_th_last_block set but never used" },
            @{ Code = "C4068"; Where = "matrixlib.cpp lines 205, 221, 293, unknown pragma unroll" }
        )
    },
    [PSCustomObject]@{
        Name = "stratum.opt.intermediate.exe"
        Flags = "-lineinfo -DPROFILE_MODE -DINTERMEDIATE_OUTPUT"
        ExpectedWarnings = @(
            @{ Code = "#550-D"; Where = "functions_cuda.cu line 63, num_th_last_block set but never used" },
            @{ Code = "C4068"; Where = "matrixlib.cpp lines 205, 221, 293, unknown pragma unroll" }
        )
    }
)

# Files the build produces inside the staged source tree. They have no
# `workspace/components/` original, so the hash assertion expects them. Each
# binary brings its import library and export file.
$buildProductPatterns = @("output\*", ".uc1-runner.lock")
foreach ($binary in $binaries) {
    $stem = [System.IO.Path]::GetFileNameWithoutExtension($binary.Name)
    $buildProductPatterns += @($binary.Name, "$stem.exp", "$stem.lib")
}

function Stop-WithError {
    param([string]$Message)

    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

function Get-VcVarsPath {
    $vsWhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path -LiteralPath $vsWhere -PathType Leaf)) {
        Stop-WithError "vswhere.exe was not found at $vsWhere. Install the Visual Studio C++ workload."
    }

    $installationPath = & $vsWhere -latest -products * `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -property installationPath | Select-Object -First 1
    if ([string]::IsNullOrWhiteSpace($installationPath)) {
        Stop-WithError "vswhere found no Visual Studio installation carrying the MSVC x64 toolset."
    }

    $vcVarsPath = Join-Path $installationPath "VC\Auxiliary\Build\vcvars64.bat"
    if (-not (Test-Path -LiteralPath $vcVarsPath -PathType Leaf)) {
        Stop-WithError "vcvars64.bat was not found at $vcVarsPath."
    }
    return $vcVarsPath
}

function Copy-Tree {
    param([string]$Source, [string]$Destination)

    $sourceRoot = (Resolve-Path -LiteralPath $Source).Path
    $copiedCount = 0
    foreach ($file in Get-ChildItem -LiteralPath $sourceRoot -Recurse -File) {
        $relativePath = $file.FullName.Substring($sourceRoot.Length).TrimStart('\')
        $target = Join-Path $Destination $relativePath
        $targetParent = Split-Path -Parent $target
        if (-not (Test-Path -LiteralPath $targetParent -PathType Container)) {
            New-Item -ItemType Directory -Path $targetParent -Force | Out-Null
        }
        Copy-Item -LiteralPath $file.FullName -Destination $target -Force
        $copiedCount++
    }
    return $copiedCount
}

function Test-IsBuildProduct {
    param([string]$RelativePath)

    foreach ($pattern in $buildProductPatterns) {
        if ($RelativePath -like $pattern) { return $true }
    }
    return $false
}

function Assert-StagedTreeIsUnchanged {
    param([string]$Original, [string]$Staged, [string]$Label)

    $originalRoot = (Resolve-Path -LiteralPath $Original).Path
    $stagedRootPath = (Resolve-Path -LiteralPath $Staged).Path

    $mismatches = @()
    $comparedCount = 0

    foreach ($file in Get-ChildItem -LiteralPath $originalRoot -Recurse -File) {
        $relativePath = $file.FullName.Substring($originalRoot.Length).TrimStart('\')
        $stagedFile = Join-Path $stagedRootPath $relativePath
        if (-not (Test-Path -LiteralPath $stagedFile -PathType Leaf)) {
            $mismatches += "MISSING  $Label\$relativePath"
            continue
        }
        $originalHash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
        $stagedHash = (Get-FileHash -LiteralPath $stagedFile -Algorithm SHA256).Hash
        if ($originalHash -ne $stagedHash) {
            $mismatches += "CHANGED  $Label\$relativePath`n           original $originalHash`n           staged   $stagedHash"
        }
        $comparedCount++
    }

    # A file that exists only in the staging area is either a build product or
    # an edit made by addition, which a per-file hash comparison alone would
    # never see.
    foreach ($file in Get-ChildItem -LiteralPath $stagedRootPath -Recurse -File) {
        $relativePath = $file.FullName.Substring($stagedRootPath.Length).TrimStart('\')
        if (Test-IsBuildProduct -RelativePath $relativePath) { continue }
        $originalFile = Join-Path $originalRoot $relativePath
        if (-not (Test-Path -LiteralPath $originalFile -PathType Leaf)) {
            $mismatches += "EXTRA    $Label\$relativePath"
        }
    }

    return [PSCustomObject]@{
        Label = $Label
        ComparedCount = $comparedCount
        Mismatches = $mismatches
    }
}

Write-Host "== STRATUM UC1 build =="
Write-Host "Vendored source: $vendoredSource"
Write-Host "Staged build:    $stagedRoot"
Write-Host ""

if (-not (Test-Path -LiteralPath $vendoredSource -PathType Container)) {
    Stop-WithError "The vendored UC1 source is missing: $vendoredSource"
}
if (-not (Test-Path -LiteralPath $vendoredModel -PathType Container)) {
    Stop-WithError "The vendored SVM model is missing: $vendoredModel"
}

# Capture the toolchain before anything else, so a machine change is detected
# rather than assumed away. The binary is only ever proven against the versions
# recorded in the task card and docs/development/uc1_local_build.md.
Write-Host "-- Toolchain --"
# Piped through Write-Host so the versions appear where they belong in the
# transcript. A bare native call writes to the host's own stdout, which is
# flushed after this script's output rather than interleaved with it.
(& nvcc --version 2>&1) | ForEach-Object { Write-Host $_ }
if ($LASTEXITCODE -ne 0) {
    Stop-WithError "nvcc is not on PATH. Install the CUDA Toolkit or open a CUDA-enabled shell."
}
(& nvidia-smi --query-gpu=name,driver_version,compute_cap,memory.total --format=csv 2>&1) |
    ForEach-Object { Write-Host $_ }
if ($LASTEXITCODE -ne 0) {
    Stop-WithError "nvidia-smi failed. The GPU or its driver is unavailable."
}
Write-Host ""

if ($Clean -and (Test-Path -LiteralPath $stagedRoot -PathType Container)) {
    Write-Host "-- Cleaning $stagedRoot --"
    Remove-Item -LiteralPath $stagedRoot -Recurse -Force
}

Write-Host "-- Staging --"
$stagedSourceCount = Copy-Tree -Source $vendoredSource -Destination $stagedSource
$stagedModelCount = Copy-Tree -Source $vendoredModel -Destination $stagedModel
Write-Host "Copied $stagedSourceCount source file(s) and $stagedModelCount model file(s)."

# The binary creates neither output directory and fails quietly without them.
New-Item -ItemType Directory -Path $stagedRgbOutput -Force | Out-Null
Write-Host "Pre-created $stagedRgbOutput"
Write-Host ""

function Invoke-Uc1Build {
    param([string]$VcVarsPath, [PSCustomObject]$Binary)

    $stagedExecutable = Join-Path $stagedSource $Binary.Name
    Write-Host "-- Building $($Binary.Name) --"

    # The GUIDE section 3.1-B command line, transcribed. The only changes are
    # the architecture and the additional PTX-emitting -gencode.
    # `-allow-unsupported-compiler` is deliberately absent: nvcc 12.9 accepts
    # this MSVC, and adding it would suppress a real diagnostic on a future
    # toolchain.
    $outputFlags = "-lcublas -O3"
    if ($Binary.Flags) { $outputFlags += " $($Binary.Flags)" }
    $commandLines = @(
        "@echo off",
        "call `"$VcVarsPath`" >nul",
        "if errorlevel 1 exit /b 1",
        "cd /d `"$stagedSource`"",
        "if errorlevel 1 exit /b 1",
        "nvcc main.cu functions.cu functions_kmeans.cu functions_cuda.cu ^",
        "     HySimeFilter\hysime.cu HySimeFilter\hysimefunc.cu HySimeFilter\lib.cu ^",
        "     HySimeFilter\matrixlib.cpp HySimeFilter\matrixop.cpp ^",
        "     HySimeFilter\ompfunc.cpp HySimeFilter\svd.cpp ^",
        "     BitmapWriter.cpp data_loader.cpp ^",
        "     -IHySimeFilter\ -I. ^",
        "     -gencode arch=compute_$computeCapability,code=sm_$computeCapability ^",
        "     -gencode arch=compute_$computeCapability,code=compute_$computeCapability ^",
        "     -std=c++17 ^",
        "     -DOPTIMIZE_KMEANS=1 -DPCA_PD=1 ^",
        "     $outputFlags -o $($Binary.Name)",
        "exit /b %errorlevel%"
    )

    $stem = [System.IO.Path]::GetFileNameWithoutExtension($Binary.Name)
    $batchPath = Join-Path $stagedRoot "build-$stem-generated.cmd"
    Set-Content -LiteralPath $batchPath -Value $commandLines -Encoding ASCII

    $buildOutput = & cmd.exe /c "`"$batchPath`"" 2>&1 | ForEach-Object { $_.ToString() }
    $buildExitCode = $LASTEXITCODE
    $buildOutput | ForEach-Object { Write-Host $_ }
    Write-Host ""

    if ($buildExitCode -ne 0) {
        Stop-WithError "nvcc exited with code $buildExitCode building $($Binary.Name). The staged sources were not modified; fix the toolchain, not the vendored source."
    }
    if (-not (Test-Path -LiteralPath $stagedExecutable -PathType Leaf)) {
        Stop-WithError "nvcc reported success but $stagedExecutable was not produced."
    }

    $executableSize = (Get-Item -LiteralPath $stagedExecutable).Length

    # The requirement is "only this binary's expected warnings may appear", so
    # both halves are enforced and both fail the build. A missing expected
    # warning means the toolchain or the source changed; an unexpected one means
    # this binary is not the one the evidence on the task card describes.
    # Reporting either in yellow and exiting 0 would leave the contract
    # unchecked, which is the same as not having it.
    Write-Host "-- Warnings: $($Binary.Name) --"
    $joinedOutput = $buildOutput -join "`n"
    $warningFailures = @()

    foreach ($warning in $Binary.ExpectedWarnings) {
        if ($joinedOutput -like "*$($warning.Code)*") {
            Write-Host "  present  $($warning.Code)  ($($warning.Where))"
        } else {
            Write-Host "  ABSENT   $($warning.Code)  ($($warning.Where))" -ForegroundColor Red
            $warningFailures += "expected warning $($warning.Code) did not appear ($($warning.Where))"
        }
    }

    # Every diagnostic line nvcc or cl emits, matched on the two forms they use:
    # `warning #550-D:` from nvcc and `warning C4068:` from MSVC. Anything that
    # is not one of the expected codes is unexpected by construction, so a new
    # diagnostic cannot slip through by being unlisted.
    $expectedCodes = $Binary.ExpectedWarnings | ForEach-Object { $_.Code }
    $unexpected = @{}
    foreach ($line in $buildOutput) {
        if ($line -notmatch 'warning\s+(#[0-9]+-[A-Z]|C[0-9]+)') { continue }
        $code = $Matches[1]
        if ($expectedCodes -contains $code) { continue }
        if (-not $unexpected.ContainsKey($code)) { $unexpected[$code] = $line.Trim() }
    }

    foreach ($code in ($unexpected.Keys | Sort-Object)) {
        Write-Host "  UNEXPECTED  $code" -ForegroundColor Red
        Write-Host "              $($unexpected[$code])" -ForegroundColor Red
        $warningFailures += "unexpected warning $code"
    }

    if ($warningFailures.Count -gt 0) {
        Write-Host ""
        Write-Host "  The vendored source is not to be silenced or 'fixed' to clear this." -ForegroundColor Red
        Write-Host "  Investigate the toolchain, then re-record the expected set on the task" -ForegroundColor Red
        Write-Host "  card if it has genuinely changed." -ForegroundColor Red
        Stop-WithError ("The build warning contract for $($Binary.Name) failed: " + ($warningFailures -join "; ") + ".")
    }
    Write-Host ""
    Write-Host "Produced $stagedExecutable ($executableSize bytes)."
    Write-Host ""
}

if ($SkipBuild) {
    Write-Host "-- Build skipped (-SkipBuild) --"
    Write-Host ""
} else {
    $vcVarsPath = Get-VcVarsPath
    Write-Host "vcvars64: $vcVarsPath"
    Write-Host ""
    foreach ($binary in $binaries) {
        Invoke-Uc1Build -VcVarsPath $vcVarsPath -Binary $binary
    }
}

# The compliance property - "no changes to vendored UC1 source" - is re-tested
# on every build rather than trusted once. `build/` is gitignored, so
# `git status` proves nothing about the staged copy.
Write-Host "-- SHA-256 source assertion --"
$results = @(
    (Assert-StagedTreeIsUnchanged -Original $vendoredSource -Staged $stagedSource -Label "gpu_single_bsq\source"),
    (Assert-StagedTreeIsUnchanged -Original $vendoredModel -Staged $stagedModel -Label "svm_model")
)

$allMismatches = @()
foreach ($result in $results) {
    Write-Host "  $($result.Label): compared $($result.ComparedCount) file(s)."
    $allMismatches += $result.Mismatches
}

$mainHash = (Get-FileHash -LiteralPath (Join-Path $stagedSource "main.cu") -Algorithm SHA256).Hash
Write-Host "  main.cu SHA-256: $mainHash"

if ($allMismatches.Count -gt 0) {
    Write-Host ""
    foreach ($mismatch in $allMismatches) { Write-Host "  $mismatch" -ForegroundColor Red }
    Stop-WithError "The staged tree is not byte-identical to workspace\components. Modifying vendored UC1 source is out of scope for this project; re-stage with -Clean, and escalate if the difference is intentional."
}

Write-Host "  All staged files are byte-identical to workspace\components." -ForegroundColor Green
Write-Host ""
Write-Host "Press Capture in SLIAFlow to run stratum.opt.intermediate.exe on the configured cube."
exit 0
